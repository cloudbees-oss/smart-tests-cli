import json
import sys
from abc import ABCMeta, abstractmethod
from http import HTTPStatus
from typing import List

import click
from tabulate import tabulate

from ...utils.authentication import ensure_org_workspace
from ...utils.launchable_client import LaunchableClient
from ...utils.session import parse_session
from ..helper import require_session


class TestResult(object):
    def __init__(self, result: dict):
        self._status = result.get("status", "")
        self._duration_sec = result.get("duration", 0.0)
        self._created_at = result.get("createdAt", None)
        self._test_path = "#".join([path["type"] + "=" + path["name"]
                                   for path in result["testPath"] if path.keys() >= {"type", "name"}])


class TestResults(object):
    def __init__(self, test_session_id: int, results: List[TestResult]):
        self._test_session_id = test_session_id
        self._results = results

    def add(self, result: TestResult):
        self._results.append(result)

    def list(self) -> List[TestResult]:
        return self._results

    def total_duration_sec(self) -> float:
        return sum([result._duration_sec for result in self._results])

    def total_duration_min(self) -> float:
        return (sum([result._duration_sec for result in self._results]) / 60)

    def total_count(self) -> int:
        return len(self._results)

    def filter_by_status(self, status: str) -> 'TestResults':
        return TestResults(self._test_session_id, [result for result in self._results if result._status == status])


class TestResultAbstractDisplay(metaclass=ABCMeta):
    def __init__(self, results: TestResults):
        self._results = results

    @abstractmethod
    def display(self):
        raise NotImplementedError("display method is not implemented")


class TestResultJSONDisplay(TestResultAbstractDisplay):
    def __init__(self, results: TestResults):
        super().__init__(results)

    def display(self):
        result_json = {}
        result_json["summary"] = {
            "total": {
                "report_count": self._results.total_count(),
                "duration_min": round(self._results.total_duration_min(), 2),
            },
            "success": {
                "report_count": self._results.filter_by_status("SUCCESS").total_count(),
                "duration_min": round(self._results.filter_by_status("SUCCESS").total_duration_min(), 2)
            },
            "failure": {
                "report_count": self._results.filter_by_status("FAILURE").total_count(),
                "duration_min": round(self._results.filter_by_status("FAILURE").total_duration_min(), 2)
            },
            "skip": {
                "report_count": self._results.filter_by_status("SKIPPED").total_count(),
                "duration_min": round(self._results.filter_by_status("SKIPPED").total_duration_min(), 2)
            }
        }
        result_json["results"] = []
        for result in self._results.list():
            result_json["results"].append({
                "test_path": result._test_path,
                "duration_sec": result._duration_sec,
                "status": result._status,
                "created_at": result._created_at
            })

        org, workspace = ensure_org_workspace()
        result_json["test_session_app_url"] = "https://app.launchableinc.com/organizations/{}/workspaces/{}/test-sessions/{}".format(  # noqa: E501
            org, workspace, self._results._test_session_id)

        click.echo(json.dumps(result_json, indent=2))


class TestResultTableDisplay(TestResultAbstractDisplay):
    def __init__(self, results: TestResults):
        super().__init__(results)

    def display(self):
        header = ["Test Path",
                  "Duration (sec)", "Status", "Uploaded At"]
        rows = []
        for result in self._results.list():
            rows.append(
                [
                    result._test_path,
                    result._duration_sec,
                    result._status,
                    result._created_at,
                ]
            )
        click.echo(tabulate(rows, header, tablefmt="github", floatfmt=".2f"))

        summary_header = ["Summary", "Report Count", "Total Duration (min)"]
        summary_rows = [
            ["Total", self._results.total_count(),
             self._results.total_duration_min()],
            ["Success", self._results.filter_by_status("SUCCESS").total_count(),
             self._results.filter_by_status("SUCCESS").total_duration_min()],
            ["Failure", self._results.filter_by_status("FAILURE").total_count(),
             self._results.filter_by_status("FAILURE").total_duration_min()],
            ["Skip", self._results.filter_by_status("SKIPPED").total_count(),
             self._results.filter_by_status("SKIPPED").total_duration_min()]]

        click.echo(tabulate(summary_rows, summary_header, tablefmt="grid", floatfmt=["", ".0f", ".2f"]))


@click.command()
@click.option(
    '--test-session-id',
    'test_session_id',
    help='test session id',
)
@click.option(
    '--json',
    'is_json_format',
    help='display JSON format',
    is_flag=True
)
@click.pass_context
def tests(context: click.core.Context, test_session_id: int, is_json_format: bool):
    if (test_session_id is None):
        try:
            session = require_session(None)
            _, test_session_id = parse_session(session)
        except Exception:
            click.echo(
                click.style(
                    "test session id requires.\n"
                    "Use the --test-session-id option or execute after `launchable record tests` command.",
                    fg="yellow"))
            return

    client = LaunchableClient(app=context.obj)
    try:
        res = client.request(
            "get", "/test_sessions/{}/events".format(test_session_id))

        if res.status_code == HTTPStatus.NOT_FOUND:
            click.echo(click.style(
                "Test session {} not found. Check test session ID and try again.".format(test_session_id), 'yellow'),
                err=True,
            )
            sys.exit(1)

        res.raise_for_status()
        results = res.json()
    except Exception as e:
        client.print_exception_and_recover(e, "Warning: failed to inspect tests")
        return

    test_results = TestResults(test_session_id=test_session_id, results=[])
    for result in results:
        if result.keys() >= {"testPath"}:
            test_results.add(TestResult(result))

    displayer: TestResultAbstractDisplay
    if is_json_format:
        displayer = TestResultJSONDisplay(test_results)
    else:
        displayer = TestResultTableDisplay(test_results)

    displayer.display()
