import os
from unittest import mock

import responses  # type: ignore

from smart_tests.test_runners.robot import parse_func
from tests.cli_test_case import CliTestCase


class RobotTest(CliTestCase):
    def test_suite_start_timestamp(self):
        # Each leaf suite carries its own start as an ISO-8601 naive string for the server to
        # resolve. RF < 7.0 'starttime' (naive, space-separated) is normalized to ISO.
        legacy = parse_func(str(self.test_files_dir) + "/output_legacy.xml").getroot()
        self.assertEqual(
            [s.get("timestamp") for s in legacy.findall("testsuite")],
            ["2021-03-19T11:34:50.080000", "2021-03-19T11:34:50.092000"],
        )
        # RF 7.0+ 'start' is already ISO and passes through; every suite must be tagged.
        modern = parse_func(str(self.test_files_dir) + "/output.xml").getroot()
        self.assertTrue(all(s.get("timestamp") for s in modern.findall("testsuite")))

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_subset(self):
        result = self.cli('subset', 'robot', '--target', '10%', '--session',
                          self.session, str(self.test_files_dir) + "/dryrun.xml")
        self.assert_success(result)
        self.assert_subset_payload('subset_result.json')

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_record_test(self):
        result = self.cli('record', 'tests', 'robot', '--session', self.session, str(self.test_files_dir) + "/output.xml")
        self.assert_success(result)
        self.assert_record_tests_payload("record_test_result.json")

    # for RF < 7.0 legacy format (starttime/endtime attributes)
    @responses.activate
    @mock.patch.dict(os.environ, {"LAUNCHABLE_TOKEN": CliTestCase.smart_tests_token})
    def test_record_test_legacy(self):

        result = self.cli('record', 'tests', '--session', self.session,
                          'robot', str(self.test_files_dir) + "/output_legacy.xml")
        self.assert_success(result)
        self.assert_record_tests_payload("record_test_legacy_result.json")

    # for #637
    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_record_test_executed_only_one_file(self):
        result = self.cli('record', 'tests', 'robot', '--session', self.session, str(self.test_files_dir) + "/single-output.xml")
        self.assert_success(result)
        self.assert_record_tests_payload("record_test_executed_only_one_file_result.json")
