import json
import sys
from abc import ABCMeta, abstractmethod
from http import HTTPStatus
from typing import List

import click
from tabulate import tabulate

from ...utils.launchable_client import LaunchableClient


class SubsetResult (object):
    def __init__(self, result: dict, is_subset: bool):
        self._estimated_duration_sec = result.get("duration", 0.0) / 1000  # convert to sec from msec
        self._density = result.get("density", 0.0)
        self._is_new = result.get("numNewTests", 0) > 0
        self._test_path = "#".join([path["type"] + "=" + path["name"]
                                   for path in result["testPath"] if path.keys() >= {"type", "name"}])
        self._is_subset = is_subset


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
        results = self._results.list()
        if new_tests_only:
            results = [r for r in results if r._is_new]
        rows = []
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
        result_json = {
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


@click.command()
@click.option(
    '--subset-id',
    'subset_id',
    help='subest id',
    required=True,
)
@click.option(
    '--json',
    'is_json_format',
    help='display JSON format',
    is_flag=True
)
@click.option(
    '--new-tests-only',
    'new_tests_only',
    help='Only display new tests',
    is_flag=True
)
@click.pass_context
def subset(context: click.core.Context, subset_id: int, is_json_format: bool, new_tests_only: bool):
    subset = []
    rest = []
    client = LaunchableClient(app=context.obj)
    try:
        res = client.request("get", "subset/{}".format(subset_id), timeout=(30, 300))

        if res.status_code == HTTPStatus.NOT_FOUND:
            click.echo(click.style(
                "Subset {} not found. Check subset ID and try again.".format(subset_id), 'yellow'), err=True)
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
