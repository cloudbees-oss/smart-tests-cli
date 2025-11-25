#
# The the test runner to support playwright junit and JSON report format.
# https://playwright.dev/
#
import json
from typing import Dict, Generator, List

import click
from junitparser import TestCase, TestSuite  # type: ignore

from ..commands.record.case_event import CaseEvent
from ..testpath import TestPath
from . import launchable

TEST_CASE_DELIMITER = " › "


@click.option('--json', 'json_format', help="use JSON report format", is_flag=True)
@click.argument('reports', required=True, nargs=-1)
@launchable.record.tests
def record_tests(client, reports, json_format):
    def path_builder(case: TestCase, suite: TestSuite,
                     report_file: str) -> TestPath:
        """
        The playwright junit report sets a file name to the name attribute in a testsuite element and the classname attribute in a testcase element. # noqa: E501
        This playwright plugin uses a testsuite attribute value.
        e.g.)
        <testsuite name="tests/demo-todo-app.spec.ts" ...>
            <testcase name="New Todo › should allow me to add todo items" classname="tests/demo-todo-app.spec.ts"></testcase>
            <testcase name="New Todo › should clear text input field when an item is added" classname="tests/demo-todo-app.spec.ts"></testcase>
        </testsuite>
        """
        filepath = suite.name
        if not filepath:
            raise click.ClickException(
                "No file name found in %s" % report_file)

        test_path = [client.make_file_path_component(filepath)]
        if case.name:
            test_path.append({"type": "testcase", "name": case.name})
        return test_path

    if json_format:
        client.parse_func = JSONReportParser(client).parse_func
    else:
        client.path_builder = path_builder

    for r in reports:
        client.report(r)

    client.run()


subset = launchable.CommonSubsetImpls(__name__).scan_files()

split_subset = launchable.CommonSplitSubsetImpls(__name__).split_subset()


class JSONReportParser:
    """
    example of JSON reporter format:
    {
        "suites": [
            {
                "title": "tests/demo-todo-app.spec.ts",
                "file": "tests/demo-todo-app.spec.ts",
                "column": 0,
                "line": 0,
                "specs": [],
                "suites": [
                    {
                        "title": "New Todo",
                        "file": "tests/demo-todo-app.spec.ts",
                        "line": 13,
                        "column": 6,
                        "specs": [
                            {
                                "title": "should allow me to add todo items",
                                "ok": true,
                                "tags": [],
                                "tests": [
                                    {
                                        "timeout": 30000,
                                        "annotations": [],
                                        "expectedStatus": "passed",
                                        "projectId": "chromium",
                                        "projectName": "chromium",
                                        "results": [
                                            {
                                                "workerIndex": 0,
                                                "status": "passed",
                                                "duration": 1254,
                                                "errors": [],
                                                "stdout": [],
                                                "stderr": [],
                                                "retry": 0,
                                                "startTime": "2024-04-08T07:42:17.455Z",
                                                "attachments": []
                                            }
                                        ],
                                        "status": "expected"
                                    },
                                    {
                                        "timeout": 30000,
                                        "annotations": [],
                                        "expectedStatus": "passed",
                                        "projectId": "firefox",
                                        "projectName": "firefox",
                                        "results": [
                                            {
                                                "workerIndex": 5,
                                                "status": "passed",
                                                "duration": 1320,
                                                "errors": [],
                                                "stdout": [],
                                                "stderr": [],
                                                "retry": 0,
                                                "startTime": "2024-04-08T07:42:21.122Z",
                                                "attachments": []
                                            }
                                        ],
                                        "status": "expected"
                                    },
                                    {
                                        "timeout": 30000,
                                        "annotations": [],
                                        "expectedStatus": "passed",
                                        "projectId": "webkit",
                                        "projectName": "webkit",
                                        "results": [
                                            {
                                                "workerIndex": 10,
                                                "status": "passed",
                                                "duration": 805,
                                                "errors": [],
                                                "stdout": [],
                                                "stderr": [],
                                                "retry": 0,
                                                "startTime": "2024-04-08T07:42:26.319Z",
                                                "attachments": []
                                            }
                                        ],
                                        "status": "expected"
                                    }
                                ],
                                "id": "f8b37aaddd8ecd14ecd4-3367671d4d7af1046962",
                                "file": "tests/demo-todo-app.spec.ts",
                                "line": 14,
                                "column": 7
                            }
                        ]
                    }
                ]
            }
        ]
    }
    """

    def __init__(self, client):
        self.client = client

    def parse_func(self, report_file: str) -> Generator[CaseEvent, None, None]:
        data: Dict[str, Dict]
        with open(report_file, 'r') as json_file:
            try:
                data = json.load(json_file)
            except Exception as e:
                raise Exception("Can't read JSON format report file {}. Make sure to confirm report file.".format(
                    report_file)) from e

        suites: List[Dict[str, Dict]] = list(data.get("suites", []))
        if len(suites) == 0:
            click.echo("Can't find test results from {}. Make sure to confirm report file.".format(
                report_file), err=True)

        for s in suites:
            # The title of the root suite object contains the file name.
            test_file = str(s.get("title", ""))

            for event in self._parse_suites(test_file, s, []):
                yield event

    def _parse_suites(self, test_file: str, suite: Dict[str, Dict], test_case_names: List[str] = []) -> List:
        events = []

        # In some cases, suites are nested.
        for s in suite.get("suites", []):
            for e in self._parse_suites(test_file, s, test_case_names + [s.get("title")]):
                events.append(e)

        for spec in suite.get("specs", []):
            spec_name = spec.get("title", "")
            line_no = spec.get("line", None)
            for test in spec.get("tests", []):
                for result in test.get("results", []):
                    test_path: TestPath = [
                        self.client.make_file_path_component(test_file),
                        {"type": "testcase", "name": TEST_CASE_DELIMITER.join(test_case_names + [spec_name])}
                    ]

                    duration_msec = result.get("duration", 0)
                    status = self._case_event_status_from_str(result.get("status", ""))
                    stdout = self._parse_stdout(result.get("stdout", []))
                    stderr = self._parse_stderr(result.get("errors", []))

                    events.append(CaseEvent.create(
                        test_path=test_path,
                        duration_secs=duration_msec / 1000,  # convert msec to sec,
                        status=status,
                        stdout=stdout,
                        stderr=stderr,
                        data={"lineNumber": line_no} if line_no else {}
                    ))

        return events

    def _case_event_status_from_str(self, status_str: str) -> int:
        # see: https://playwright.dev/docs/api/class-testresult#test-result-status
        if status_str == "passed":
            return CaseEvent.TEST_PASSED
        elif status_str == "failed" or status_str == "timedOut" or status_str == "interrupted":
            return CaseEvent.TEST_FAILED
        elif status_str == "skipped":
            return CaseEvent.TEST_SKIPPED
        else:
            return CaseEvent.TEST_PASSED

    def _parse_stdout(self, stdout: List[Dict[str, Dict]]) -> str:
        if len(stdout) == 0:
            return ""

        return "\n".join([str(out.get("text", "")) for out in stdout])

    def _parse_stderr(self, stderr: List[Dict[str, Dict]]) -> str:
        if len(stderr) == 0:
            return ""

        return "\n".join([str(err.get("message", "")) for err in stderr])
