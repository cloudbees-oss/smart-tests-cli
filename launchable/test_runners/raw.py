import datetime
import json
import sys
from typing import Generator

import click
import dateutil.parser

from ..commands.record.case_event import CaseEvent, CaseEventType
from ..testpath import TestPath, parse_test_path, unparse_test_path
from . import launchable


@click.argument('test_path_file', required=False, type=click.File('r'))
@launchable.subset
def subset(client, test_path_file):
    """Subset tests

    TEST_PATH_FILE is a file that contains test paths (e.g.
    "file=a.py#class=classA") one per line. Lines start with a hash ('#') are
    considered as a comment and ignored.
    """

    if not client.is_get_tests_from_previous_sessions and test_path_file is None:
        raise click.BadArgumentUsage("Missing argument 'TEST_PATH_FILE'.")

    if client.is_output_exclusion_rules:
        raise click.BadArgumentUsage(
            "Don't need to use `--output-exclusion-rules` option. Please use `--rest` option and use it for exclusion"
        )

    if not client.is_get_tests_from_previous_sessions:
        tps = [s.strip() for s in test_path_file.readlines()]
        for tp_str in tps:
            if not tp_str or tp_str.startswith('#'):
                continue
            try:
                tp = parse_test_path(tp_str)
            except ValueError as e:
                sys.exit(e.args[0])
            client.test_path(tp)

    client.formatter = unparse_test_path
    client.separator = '\n'
    client.run()


split_subset = launchable.CommonSplitSubsetImpls(__name__, formatter=unparse_test_path, seperator='\n').split_subset()

launchable.CommonFlakeDetectionImpls(__name__).detect_flakes()


@click.argument('test_result_files', required=True, type=click.Path(exists=True), nargs=-1)
@launchable.record.tests
def record_tests(client, test_result_files):
    """Record test results

    TEST_RESULT_FILE is a file that contains a JSON document or JUnit XML file
    that describes the test results.

    ## Example JSON document

    {
      "testCases": [
         {
           "testPath": "file=a.py#class=classA",
           "duration": 42,
           "status": "TEST_PASSED",
           "stdout": "This is stdout",
           "stderr": "This is stderr",
           "createdAt": "2021-10-05T12:34:00"
         }
      ]
    }

    ## JSON schema

    {
      "$id": "https://launchableinc.com/schema/RecordTestInput",
      "$schema": "https://json-schema.org/draft/2020-12/schema",
      "title": "RecordTestInput",
      "description": "The input to record test",
      "type": "object",
      "properties": {
        "testCases": {
          "description": "Result of test cases",
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "testPath": {
                "description": "TestPath for the test",
                "type": "string"
              },
              "testPathComponents": {
                "description": "TestPath for the test",
                "type": "array",
                "items": {
                  "type": "object"
                }
              },
              "duration": {
                "description": "Time taken to finish the test in seconds. If unspecified, assume 0 sec.",
                "type": "number",
                "minimum": 0
              },
              "status": {
                "description": "Test result",
                "type": "string",
                "enum": [
                  "TEST_PASSED",
                  "TEST_FAILED",
                  "TEST_SKIPPED"
                ]
              },
              "stdout": {
                "description": "Standard output of the test. If unspecified, assume empty.",
                "type": "string"
              },
              "stderr": {
                "description": "Standard error of the test. If unspecified, assume empty",
                "type": "string"
              },
              "createdAt": {
                "description": "The timestamp that the test started at. If unspecified, assume the current timestamp
                that the CLI is invoked.",
                "type": "string",
                "format": "date-time"
              },
              "junitSuiteTime": {
                "description": "Wall-clock duration (seconds) of the suite this test belongs to, from the JUnit
                <testsuite time> attribute. Used to compute session elapsed time. If unspecified, the server falls
                back to the sum of case durations.",
                "type": "string"
              },
              "data": {
                "description": "Metadata of the test, e.g. line number.",
                "type": "object",
                "properties": {
                  "lineNumber": {
                    "description": "Line number of the test (1-based).",
                    "type": "number"
                  }
                }
              }
            },
            "required": [
              "status"
            ],
            "oneOf": [
              {
                "required": [
                  "testPath"
                ]
              },
              {
                "required": [
                  "testPathComponents"
                ]
              }
            ]
          }
        }
      },
      "required": [
        "testCases"
      ]
    }

    ## JUnit XML TestPath mapping

    If the file path ends with '.xml', the command parses the file as a JUnit XML file. When this mode is used the subset input
    TestPath should look like 'class={classname}#testcase={testcase}'.
    """

    def parse_json(test_result_file: str) -> Generator[CaseEventType, None, None]:
        with open(test_result_file, 'r') as f:
            doc = json.load(f)
        default_created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        for case in doc['testCases']:
            test_path_components: TestPath = case.get('testPathComponents', None)
            test_path: str = case.get('testPath', None)
            if test_path_components is None and test_path is None:
                raise ValueError("Missing testPath or testPathComponents field in the test case.")
            if test_path_components and test_path:
                raise ValueError("Specifying both testPath and testPathComponents fields is invalid.")
            if test_path:
                test_path_components = parse_test_path(test_path)
            status = case['status']
            duration_secs = case.get('duration', 0)
            if isinstance(duration_secs, str):
                try:
                    duration_secs = float(duration_secs)
                except ValueError:
                    raise ValueError("The duration of {} in {} isn't a valid format (was {}). Make sure set a valid duration".format(test_path_components, test_result_file, duration_secs))  # noqa

            created_at = case.get('createdAt', default_created_at)

            if status not in CaseEvent.STATUS_MAP:
                raise ValueError(
                    "The status of {} should be one of {} (was {})".format(test_path_components,
                                                                           list(CaseEvent.STATUS_MAP.keys()), status))

            if duration_secs < 0:
                raise ValueError("The duration of {} should be positive (was {})".format(test_path_components, duration_secs))
            dateutil.parser.parse(created_at)
            metadata = case.get('data', None)
            suite_time = case.get('junitSuiteTime', None)
            if suite_time is not None:
                suite_time = str(suite_time)

            yield CaseEvent.create(
                test_path=test_path_components,
                duration_secs=duration_secs,
                status=CaseEvent.STATUS_MAP[status],
                stdout=case.get('stdout', ''),
                stderr=case.get('stderr', ''),
                timestamp=created_at,
                data=metadata,
                suite_time=suite_time)

    for test_result_file in test_result_files:
        if not test_result_file.endswith('.xml'):
            client.parse_func = parse_json
            break

    for test_result_file in test_result_files:
        client.report(test_result_file)

    client.run()
