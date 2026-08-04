import json
import sys
from abc import ABCMeta, abstractmethod
from http import HTTPStatus
from typing import Annotated, List

import click
from tabulate import tabulate

import smart_tests.args4p.typer as typer

from ... import args4p
from ...app import Application
from ...utils.smart_tests_client import SmartTestsClient


class SubsetResult (object):
    def __init__(self, result: dict, is_subset: bool):
        self._estimated_duration_sec = result.get("duration", 0.0) / 1000  # convert to sec from msec
        self._test_path = "#".join([path["type"] + "=" + path["name"]
                                   for path in result["testPath"] if path.keys() >= {"type", "name"}])
        self._is_subset = is_subset
        self._density = result.get("density", 0.0)
        self._is_new = result.get("numNewTests", 0) > 0


class SubsetResults(object):
    def __init__(self, results: List[SubsetResult]):
        self._results = results

    def add_subset(self, subset: List):
        for result in subset:
            self._results.append(SubsetResult(result, True))

    def add_rest(self, rest: List):
        for result in rest:
            self._results.append(SubsetResult(result, False))

    def list(self) -> List[SubsetResult]:
        return self.list_subset() + self.list_rest()

    def list_subset(self) -> List[SubsetResult]:
        return [result for result in self._results if result._is_subset]

    def list_rest(self) -> List[SubsetResult]:
        return [result for result in self._results if not result._is_subset]


class SubsetResultAbstractDisplay(metaclass=ABCMeta):
    def __init__(self, results: SubsetResults):
        self._results = results

    @abstractmethod
    def display(self, new_tests_only: bool = False):
        raise NotImplementedError("display method is not implemented")


class SubsetResultTableDisplay(SubsetResultAbstractDisplay):
    def __init__(self, results: SubsetResults):
        super().__init__(results)

    def display(self, new_tests_only: bool = False):
        header = ["Order", "Test Path", "In Subset", "Density", "Duration", "New"]
        rows = []
        results = [r for r in self._results.list() if r._is_new] if new_tests_only else self._results.list()
        for idx, result in enumerate(results):
            rows.append(
                [
                    idx + 1,
                    result._test_path,
                    "✔" if result._is_subset else "",
                    result._density,
                    "{:.3f}s".format(result._estimated_duration_sec),
                    "Yes" if result._is_new else "No",
                ]
            )
        click.echo_via_pager(tabulate(rows, header, tablefmt="github", floatfmt=".3f"))


class SubsetResultJSONDisplay(SubsetResultAbstractDisplay):
    def __init__(self, results: SubsetResults):
        super().__init__(results)

    def display(self, new_tests_only: bool = False):
        result_json: dict = {
            "subset": [],
            "rest": []
        }
        for result in self._results.list_subset():
            if new_tests_only and not result._is_new:
                continue
            result_json["subset"].append({
                "test_path": result._test_path,
                "estimated_duration_sec": round(result._estimated_duration_sec, 2),
                "density": result._density,
                "is_new": result._is_new,
            })
        for result in self._results.list_rest():
            if new_tests_only and not result._is_new:
                continue
            result_json["rest"].append({
                "test_path": result._test_path,
                "estimated_duration_sec": round(result._estimated_duration_sec, 2),
                "density": result._density,
                "is_new": result._is_new,
            })

        click.echo(json.dumps(result_json, indent=2))


@args4p.command(help="Inspect subset data")
def subset(
    app: Application,
    subset_id: Annotated[int, typer.Option(
        help="Subset id",
        required=True
    )],
    json: Annotated[bool, typer.Option(
        help="Display JSON format"
    )] = False,
    new_tests_only: Annotated[bool, typer.Option(
        "--new-tests-only",
        help="Show only tests that have no duration history"
    )] = False,
):
    is_json_format = json  # Map parameter name

    subset = []
    rest = []
    client = SmartTestsClient(app=app)
    try:
        res = client.request("get", f"subset/{subset_id}", timeout=(30, 300))

        if res.status_code == HTTPStatus.NOT_FOUND:
            click.secho(
                f"Subset {subset_id} not found. Check subset ID and try again.", fg='yellow', err=True)
            sys.exit(1)

        res.raise_for_status()
        subset = res.json()["testPaths"]
        rest = res.json()["rest"]
    except Exception as e:
        client.print_exception_and_recover(e, "Warning: failed to inspect subset")

    results = SubsetResults([])
    results.add_subset(subset)
    results.add_rest(rest)

    displayer: SubsetResultAbstractDisplay
    if is_json_format:
        displayer = SubsetResultJSONDisplay(results)
    else:
        displayer = SubsetResultTableDisplay(results)

    displayer.display(new_tests_only=new_tests_only)
