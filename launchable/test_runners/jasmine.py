import json
from typing import Dict, Generator, List

import click

from ..commands.record.case_event import CaseEvent
from ..testpath import TestPath
from . import launchable


@click.argument('reports', required=True, nargs=-1)
@launchable.record.tests
def record_tests(client, reports):
    client.parse_func = JSONReportParser(client).parse_func

    for r in reports:
        client.report(r)

    client.run()


subset = launchable.CommonSubsetImpls(__name__).scan_files()

split_subset = launchable.CommonSplitSubsetImpls(__name__).split_subset()


class JSONReportParser:
    """
    Sample report format:
    {
      "suite1": {
        "id": "suite1",
        "description": "Player",
        "fullName": "Player",
        "parentSuiteId": null,
        "filename": "/path/to/spec/PlayerSpec.js",
        "failedExpectations": [],
        "deprecationWarnings": [],
        "duration": 3,
        "properties": null,
        "status": "passed",
        "specs": [
          {
            "id": "spec0",
            "description": "should be able to play a Song",
            "fullName": "Player should be able to play a Song",
            "parentSuiteId": "suite1",
            "filename": "/path/to/spec/PlayerSpec.js",
            "failedExpectations": [],
            "passedExpectations": [...],
            "deprecationWarnings": [],
            "pendingReason": "",
            "duration": 1,
            "properties": null,
            "debugLogs": null,
            "status": "passed"
          }
        ]
      }
    }
    """

    def __init__(self, client):
        self.client = client

    def parse_func(self, report_file: str) -> Generator[Dict, None, None]:  # type: ignore
        data: Dict[str, Dict]
        with open(report_file, 'r') as json_file:
            try:
                data = json.load(json_file)
            except Exception:
                click.echo(
                    click.style("Error: Failed to load Json report file: {}".format(report_file), fg='red'), err=True)
                return

        if not self._validate_report_format(data):
            click.echo(
                "Error: {} does not appear to be valid format. "
                "Make sure you are using Jasmine >= v4.6.0 and jasmine-json-test-reporter as the reporter.".format(
                    report_file), err=True)
            return

        # If validation passes, parse the suites
        for suite_id, suite in data.items():
            for event in self._parse_suite(suite):
                yield event

    def _validate_report_format(self, data: Dict) -> bool:
        for suite in data.values():
            if not isinstance(suite, dict):
                return False

            if "filename" not in suite or "specs" not in suite:
                return False

            specs = suite.get("specs", [])
            for spec in specs:
                if not isinstance(spec, dict):
                    return False
                if "status" not in spec or "duration" not in spec:
                    return False

        return True

    def _parse_suite(self, suite: Dict) -> List[Dict]:
        events: List[Dict] = []

        filename = suite.get("filename", "")
        specs = suite.get("specs", [])
        for spec in specs:
            test_path: TestPath = [
                self.client.make_file_path_component(filename),
                {"type": "testcase", "name": spec.get("fullName", spec.get("description", ""))}
            ]

            duration_msec = spec.get("duration", 0)
            status = self._case_event_status_from_str(spec.get("status", ""))
            stderr = self._parse_stderr(spec)

            events.append(CaseEvent.create(
                test_path=test_path,
                duration_secs=duration_msec / 1000 if duration_msec else 0,  # convert msec to sec
                status=status,
                stderr=stderr
            ))

        return events

    def _case_event_status_from_str(self, status_str: str) -> int:
        if status_str == "passed":
            return CaseEvent.TEST_PASSED
        elif status_str == "failed":
            return CaseEvent.TEST_FAILED
        else:
            return CaseEvent.TEST_SKIPPED

    def _parse_stderr(self, spec: Dict) -> str:
        failed_expectations = spec.get("failedExpectations", [])
        if not failed_expectations:
            return ""

        error_messages = []
        for expectation in failed_expectations:
            message = expectation.get("message", "")
            stack = expectation.get("stack", "")

            if message:
                error_messages.append(message)
            if stack:
                error_messages.append(stack)

        return "\n".join(error_messages)
