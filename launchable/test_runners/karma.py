# This runner only supports recording tests
# For subsetting, use 'ng' test runner instead
# It's possible to use 'karma' runner for recording, and 'ng' runner for subsetting, for the same test session
import json
from typing import Dict, Generator, List

import click

from ..commands.record.case_event import CaseEvent
from ..testpath import TestPath
from . import launchable

# TODO: implement the --with ng option
subset = launchable.CommonSubsetImpls(__name__).scan_files()

@click.argument('reports', required=True, nargs=-1)
@launchable.record.tests
def record_tests(client, reports):
    client.parse_func = JSONReportParser(client).parse_func

    for r in reports:
        client.report(r)

    client.run()


class JSONReportParser:
    """
    Sample Karma report format:
    {
      "browsers": {...},
      "result": {
        "24461741": [
          {
            "fullName": "path/to/spec.ts should do something",
            "description": "should do something",
            "id": "spec0",
            "log": [],
            "skipped": false,
            "disabled": false,
            "pending": false,
            "success": true,
            "suite": [
              "path/to/spec.ts"
            ],
            "time": 92,
            "executedExpectationsCount": 1,
            "passedExpectations": [...],
            "properties": null
          }
        ]
      },
      "summary": {...}
    }
    """

    def __init__(self, client):
        self.client = client

    def parse_func(self, report_file: str) -> Generator[Dict, None, None]:  # type: ignore
        data: Dict
        with open(report_file, 'r') as json_file:
            try:
                data = json.load(json_file)
            except Exception:
                click.echo(
                    click.style("Error: Failed to load Json report file: {}".format(report_file), fg='red'), err=True)
                return

        if not self._validate_report_format(data):
            click.echo(
                "Error: {} does not appear to be valid Karma report format. "
                "Make sure you are using karma-json-reporter or a compatible reporter.".format(
                    report_file), err=True)
            return

        results = data.get("result", {})
        for browser_id, specs in results.items():
            if isinstance(specs, list):
                for event in self._parse_specs(specs):
                    yield event

    def _validate_report_format(self, data: Dict) -> bool:
        if not isinstance(data, dict):
            return False

        if "result" not in data:
            return False

        results = data.get("result", {})
        if not isinstance(results, dict):
            return False

        for browser_id, specs in results.items():
            if not isinstance(specs, list):
                return False

            for spec in specs:
                if not isinstance(spec, dict):
                    return False
                # Check for required fields
                if "suite" not in spec or "time" not in spec:
                    return False
                # Field suite should have at least one element (filename)
                suite = spec.get("suite", [])
                if not isinstance(suite, list) or len(suite) == 0:
                    return False

        return True

    def _parse_specs(self, specs: List[Dict]) -> List[Dict]:
        events: List[Dict] = []

        for spec in specs:
            # TODO:
            # In NextWorld, test filepaths are included in the suite tag
            # But generally in a Karma test report, a suite tag can be any string
            # For the time being let's get filepaths from the suite tag,
            # until we find a standard way to include filepaths in the test reports
            suite = spec.get("suite", [])
            filename = suite[0] if suite else ""

            test_path: TestPath = [
                self.client.make_file_path_component(filename),
                {"type": "testcase", "name": spec.get("fullName", spec.get("description", ""))}
            ]

            duration_msec = spec.get("time", 0)
            status = self._case_event_status_from_spec(spec)
            stderr = self._parse_stderr(spec)

            events.append(CaseEvent.create(
                test_path=test_path,
                duration_secs=duration_msec / 1000 if duration_msec else 0,
                status=status,
                stderr=stderr
            ))

        return events

    def _case_event_status_from_spec(self, spec: Dict) -> int:
        if spec.get("skipped", False) or spec.get("disabled", False) or spec.get("pending", False):
            return CaseEvent.TEST_SKIPPED

        if spec.get("success", False):
            return CaseEvent.TEST_PASSED
        else:
            return CaseEvent.TEST_FAILED

    def _parse_stderr(self, spec: Dict) -> str:
        log_messages = spec.get("log", [])
        if not log_messages:
            return ""

        return "\n".join(str(msg) for msg in log_messages if msg)
