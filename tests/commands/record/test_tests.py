import gzip
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

import responses  # type: ignore

from smart_tests.commands.record.tests import INVALID_TIMESTAMP, parse_launchable_timeformat, summarize_case_events
from smart_tests.utils.http_client import get_base_url
from tests.cli_test_case import CliTestCase


class TestsTest(CliTestCase):
    report_files_dir = Path(__file__).parent.joinpath(
        '../../data/maven/').resolve()

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_with_group_name(self):
        # also testing the use of @session_file syntax here
        with tempfile.NamedTemporaryFile(mode="w+", delete=False) as tmp:
            tmp.write(self.session)
            tmp.flush()
            session_file = tmp.name

        result = self.cli('record', 'tests', 'maven', '--session', f'@{session_file}', '--group', 'hoge',
                          str(self.report_files_dir) + "**/reports/")

        self.assert_success(result)
        request = json.loads(gzip.decompress(self.find_request('/events').request.body).decode())
        self.assertCountEqual(request.get("group", []), "hoge")

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_filename_in_error_message(self):
        # emulate smart-tests record build

        normal_xml = str(Path(__file__).parent.joinpath('../../data/broken_xml/normal.xml').resolve())
        broken_xml = str(Path(__file__).parent.joinpath('../../data/broken_xml/broken.xml').resolve())
        result = self.cli(
            'record',
            'tests',
            'file',
            '--session',
            self.session,
            normal_xml,
            broken_xml)

        def remove_backslash(input: str) -> str:
            # Hack for Windowns. They containts double escaped backslash such
            # as \\\\
            if sys.platform == "win32":
                return input.replace("\\", "")
            else:
                return input

        # making sure the offending file path name is being printed.
        self.assertIn(remove_backslash(broken_xml), remove_backslash(result.output))

        # normal.xml
        self.assertIn('open_class_user_test.rb', gzip.decompress(self.find_request('/events').request.body).decode())

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_upload_raw_files(self):
        uploads = []

        def callback(request):
            body = request.body
            if hasattr(body, 'read'):
                body = body.read()
            self.assertEqual(int(request.headers['Content-Length']), len(body))
            self.assertTrue(request.headers['Content-Type'].startswith('multipart/form-data; boundary='))
            uploads.append(body)
            return 200, {}, ''

        responses.add_callback(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}"
            f"/builds/{self.build_name}/test_sessions/{self.session_id}/test_result_file",
            callback=callback)

        xml_a = Path(__file__).parent.joinpath('../../data/googletest/output_a.xml').resolve()
        xml_b = Path(__file__).parent.joinpath('../../data/googletest/output_b.xml').resolve()
        result = self.cli('record', 'tests', 'googletest', '--session', self.session, str(xml_a), str(xml_b))

        self.assert_success(result)
        self.assertNotIn("Error uploading raw test result file", result.output)
        self.assertEqual(len(uploads), 2)
        for path in (xml_a, xml_b):
            body = next(b for b in uploads if f'filename="{path.name}"'.encode() in b)
            self.assertIn(path.read_bytes(), body)

    def test_parse_launchable_timeformat(self):
        t1 = "2021-04-01T09:35:47.934+00:00"  # 1617269747.934
        t2 = "2021-05-24T18:29:04.285+00:00"  # 1621880944.285
        t3 = "2021-05-32T26:29:04.285+00:00"  # invalid time format

        parse_launchable_time1 = parse_launchable_timeformat(t1)
        parse_launchable_time2 = parse_launchable_timeformat(t2)

        self.assertEqual(parse_launchable_time1.timestamp(), 1617269747.934)
        self.assertEqual(parse_launchable_time2.timestamp(), 1621880944.285)

        self.assertEqual(INVALID_TIMESTAMP, parse_launchable_timeformat(t3))

    def _case_event(self, test_path, status, duration=0.0):
        return {"type": "case", "testPath": test_path, "status": status, "duration": duration,
                "stdout": "", "stderr": "", "data": None}

    def test_summarize_case_events_single_event_per_test(self):
        """One event per test (the common case, unaffected by flaky/rerun expansion)."""
        passing_path = [{"type": "class", "name": "AppTest"}, {"type": "testcase", "name": "shouldWork"}]
        failing_path = [{"type": "class", "name": "BrokenTest"}, {"type": "testcase", "name": "neverWorks"}]
        events = [
            self._case_event(passing_path, status=1, duration=0.01),
            self._case_event(failing_path, status=0, duration=0.02),
        ]

        test_count, success_count, fail_count, duration = summarize_case_events(events)

        self.assertEqual((test_count, success_count, fail_count), (2, 1, 1))
        self.assertAlmostEqual(duration, (0.01 + 0.02) / 60)

    def test_summarize_case_events_rerun_counts_as_one_test(self):
        """A flaky test (4 FAILED attempts + 1 final PASSED, same testPath) must count as ONE
        test, not five -- this is exactly the bug the raw per-event counting had."""
        flaky_path = [{"type": "class", "name": "FlakyTest"}, {"type": "testcase", "name": "passesEventually"}]
        events = [self._case_event(flaky_path, status=0, duration=0.0) for _ in range(4)]
        events.append(self._case_event(flaky_path, status=1, duration=0.045))

        test_count, success_count, fail_count, duration = summarize_case_events(events)

        self.assertEqual((test_count, success_count, fail_count), (1, 1, 0))
        self.assertAlmostEqual(duration, 0.045 / 60)

    def test_summarize_case_events_normal_and_rerun_mixed(self):
        """A normal test (1 event, PASSED) plus a rerun-fail test (5 events, all FAILED, same
        testPath) should report 2 tests found / 1 passed / 1 failed -- not 6 / 1 / 5."""
        normal_path = [{"type": "class", "name": "AppTest"}, {"type": "testcase", "name": "shouldWork"}]
        rerun_fail_path = [{"type": "class", "name": "AlwaysFailingTest"}, {"type": "testcase", "name": "neverPasses"}]
        events = [self._case_event(normal_path, status=1, duration=0.002)]
        events.append(self._case_event(rerun_fail_path, status=0, duration=0.001))
        events.extend(self._case_event(rerun_fail_path, status=0, duration=0.0) for _ in range(4))

        test_count, success_count, fail_count, duration = summarize_case_events(events)

        self.assertEqual((test_count, success_count, fail_count), (2, 1, 1))
        self.assertAlmostEqual(duration, (0.002 + 0.001) / 60)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_when_total_test_duration_zero(self):
        zero_duration_xml1 = str(Path(__file__).parent.joinpath('../../data/googletest/output_a.xml').resolve())
        zero_duration_xml2 = str(Path(__file__).parent.joinpath('../../data/googletest/output_b.xml').resolve())
        result = self.cli(
            'record', 'tests', 'googletest',
            '--session', self.session,
            zero_duration_xml1,
            zero_duration_xml2)

        self.assert_success(result)
        self.assertIn("Total test duration is 0.", result.output)
