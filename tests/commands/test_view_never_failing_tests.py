import json
import os
from unittest import mock

import responses

from smart_tests.utils.http_client import get_base_url
from tests.cli_test_case import CliTestCase


class ViewNeverFailingTestsTest(CliTestCase):
    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_never_failing_tests_basic(self):
        """Test basic never failing tests query with default parameters"""
        mock_json_response = {
            "data": {
                "weeks": [
                    {
                        "weekDate": "2026-W19",
                        "calculationStatus": "CALCULATED",
                        "calculationTime": "2026-05-11T10:30:00Z",
                        "neverFailingTests": [
                            {
                                "testPath": [
                                    {"type": "class", "name": "TestClass"},
                                    {"type": "testCase", "name": "testMethod"}
                                ],
                                "executionCount": 42,
                                "totalDurationMs": 218400,
                                "averageDurationMs": 5200
                            },
                            {
                                "testPath": [
                                    {"type": "class", "name": "AnotherTest"},
                                    {"type": "testCase", "name": "anotherMethod"}
                                ],
                                "executionCount": 38,
                                "totalDurationMs": 129200,
                                "averageDurationMs": 3400
                            }
                        ],
                        "testCount": 2
                    }
                ]
            },
            "metadata": {
                "weeksRequested": 1,
                "weeksReturned": 1,
                "latestWeek": "2026-W19"
            }
        }

        responses.add(
            responses.GET,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/view/never-failing-tests",
            json=mock_json_response,
            status=200,
        )

        result = self.cli("view", "never-failing-tests", mix_stderr=False)
        self.assert_success(result)

        output_json = json.loads(result.stdout)
        self.assertEqual(output_json["data"]["weeks"][0]["weekDate"], "2026-W19")
        self.assertEqual(len(output_json["data"]["weeks"][0]["neverFailingTests"]), 2)
        self.assertEqual(output_json["metadata"]["weeksRequested"], 1)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_never_failing_tests_with_year_week(self):
        """Test never failing tests query with specific year-week parameter"""
        mock_json_response = {
            "data": {
                "weeks": [
                    {
                        "weekDate": "2026-W15",
                        "calculationStatus": "CALCULATED",
                        "calculationTime": "2026-04-12T10:30:00Z",
                        "neverFailingTests": [],
                        "testCount": 0
                    }
                ]
            },
            "metadata": {
                "weeksRequested": 1,
                "weeksReturned": 1,
                "latestWeek": "2026-W19"
            }
        }

        responses.add(
            responses.GET,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/view/never-failing-tests",
            json=mock_json_response,
            status=200,
        )

        result = self.cli("view", "never-failing-tests", "--year-week", "2026-W15", mix_stderr=False)
        self.assert_success(result)

        self.assertEqual(len(responses.calls), 1)
        self.assertIn("/view/never-failing-tests", responses.calls[0].request.url)
        self.assertIn("year-week=2026-W15", responses.calls[0].request.url)

        output_json = json.loads(result.stdout)
        self.assertEqual(output_json["data"]["weeks"][0]["weekDate"], "2026-W15")

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_never_failing_tests_with_multiple_weeks(self):
        """Test never failing tests query with multiple weeks parameter"""
        mock_json_response = {
            "data": {
                "weeks": [
                    {
                        "weekDate": "2026-W19",
                        "calculationStatus": "CALCULATED",
                        "calculationTime": "2026-05-11T10:30:00Z",
                        "neverFailingTests": [],
                        "testCount": 0
                    },
                    {
                        "weekDate": "2026-W18",
                        "calculationStatus": "CALCULATED",
                        "calculationTime": "2026-05-04T10:30:00Z",
                        "neverFailingTests": [],
                        "testCount": 0
                    }
                ]
            },
            "metadata": {
                "weeksRequested": 2,
                "weeksReturned": 2,
                "latestWeek": "2026-W19"
            }
        }

        responses.add(
            responses.GET,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/view/never-failing-tests",
            json=mock_json_response,
            status=200,
        )

        result = self.cli("view", "never-failing-tests", "--weeks", "2", mix_stderr=False)
        self.assert_success(result)

        self.assertGreater(len(responses.calls), 0)
        self.assertIn("/view/never-failing-tests", responses.calls[0].request.url)
        self.assertIn("weeks=2", responses.calls[0].request.url)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_never_failing_tests_with_date_range(self):
        """Test never failing tests query with from/to date parameters"""
        mock_json_response = {
            "data": {"weeks": []},
            "metadata": {
                "weeksRequested": 1,
                "weeksReturned": 0,
                "latestWeek": "2026-W19"
            }
        }

        responses.add(
            responses.GET,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/view/never-failing-tests",
            json=mock_json_response,
            status=200,
        )

        result = self.cli(
            "view", "never-failing-tests",
            "--from", "2026-04-08",
            "--to", "2026-04-14",
            mix_stderr=False
        )
        self.assert_success(result)

        self.assertGreater(len(responses.calls), 0)
        self.assertIn("/view/never-failing-tests", responses.calls[0].request.url)
        self.assertIn("from=", responses.calls[0].request.url)
        self.assertIn("to=", responses.calls[0].request.url)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_never_failing_tests_with_test_path(self):
        """Test never failing tests query with test-path filter"""
        mock_json_response = {
            "data": {
                "weeks": [
                    {
                        "weekDate": "2026-W19",
                        "calculationStatus": "CALCULATED",
                        "calculationTime": "2026-05-11T10:30:00Z",
                        "neverFailingTests": [],
                        "testCount": 0
                    }
                ]
            },
            "metadata": {
                "weeksRequested": 1,
                "weeksReturned": 1,
                "latestWeek": "2026-W19"
            }
        }

        responses.add(
            responses.GET,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/view/never-failing-tests",
            json=mock_json_response,
            status=200,
        )

        result = self.cli("view", "never-failing-tests", "--test-path", "com.example.MyTest", mix_stderr=False)
        self.assert_success(result)

        self.assertGreater(len(responses.calls), 0)
        self.assertIn("/view/never-failing-tests", responses.calls[0].request.url)
        self.assertIn("test-path=com.example.MyTest", responses.calls[0].request.url)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_never_failing_tests_with_limit(self):
        """Test never failing tests query with limit parameter"""
        mock_json_response = {
            "data": {
                "weeks": [
                    {
                        "weekDate": "2026-W19",
                        "calculationStatus": "CALCULATED",
                        "calculationTime": "2026-05-11T10:30:00Z",
                        "neverFailingTests": [],
                        "testCount": 0
                    }
                ]
            },
            "metadata": {
                "weeksRequested": 1,
                "weeksReturned": 1,
                "latestWeek": "2026-W19"
            }
        }

        responses.add(
            responses.GET,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/view/never-failing-tests",
            json=mock_json_response,
            status=200,
        )

        result = self.cli("view", "never-failing-tests", "--limit", "100", mix_stderr=False)
        self.assert_success(result)

        self.assertGreater(len(responses.calls), 0)
        self.assertIn("/view/never-failing-tests", responses.calls[0].request.url)
        self.assertIn("limit=100", responses.calls[0].request.url)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_never_failing_tests_not_found(self):
        """Test never failing tests query when data is not found"""
        responses.add(
            responses.GET,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/view/never-failing-tests",
            json={},
            status=404,
        )

        result = self.cli("view", "never-failing-tests", mix_stderr=False)
        self.assert_exit_code(result, 1)
        self.assertIn("No never failing test data found", result.stderr)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_never_failing_tests_api_error(self):
        """Test never failing tests query when API returns error"""
        responses.add(
            responses.GET,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/view/never-failing-tests",
            status=500,
        )

        result = self.cli("view", "never-failing-tests", mix_stderr=False)
        self.assert_exit_code(result, 1)
        self.assertIn("Error", result.stderr)

    def test_never_failing_tests_invalid_year_week(self):
        """Test never failing tests query with invalid year-week format"""
        result = self.cli("view", "never-failing-tests", "--year-week", "2026W15", mix_stderr=False)
        self.assert_exit_code(result, 1)
        self.assertIn("Invalid year-week format", result.stderr)
        self.assertIn("Expected format: YYYY-Www", result.stderr)

    def test_never_failing_tests_year_week_zero(self):
        """Test never failing tests query with week number 00 (invalid)"""
        result = self.cli("view", "never-failing-tests", "--year-week", "2026-W00", mix_stderr=False)
        self.assert_exit_code(result, 1)
        self.assertIn("Invalid week number", result.stderr)
        self.assertIn("Week must be between 01 and 53", result.stderr)

    def test_never_failing_tests_year_week_too_high(self):
        """Test never failing tests query with week number 54 (invalid)"""
        result = self.cli("view", "never-failing-tests", "--year-week", "2026-W54", mix_stderr=False)
        self.assert_exit_code(result, 1)
        self.assertIn("Invalid week number", result.stderr)
        self.assertIn("Week must be between 01 and 53", result.stderr)

    def test_never_failing_tests_year_week_99(self):
        """Test never failing tests query with week number 99 (invalid)"""
        result = self.cli("view", "never-failing-tests", "--year-week", "2026-W99", mix_stderr=False)
        self.assert_exit_code(result, 1)
        self.assertIn("Invalid week number", result.stderr)
        self.assertIn("Week must be between 01 and 53", result.stderr)

    def test_never_failing_tests_invalid_limit(self):
        """Test never failing tests query with out-of-range limit"""
        result = self.cli("view", "never-failing-tests", "--limit", "600", mix_stderr=False)
        self.assert_exit_code(result, 1)
        self.assertIn("cannot be larger than 500", result.stderr)

    def test_never_failing_tests_invalid_weeks(self):
        """Test never failing tests query with out-of-range weeks"""
        result = self.cli("view", "never-failing-tests", "--weeks", "15", mix_stderr=False)
        self.assert_exit_code(result, 1)
        self.assertIn("cannot be larger than 12", result.stderr)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_never_failing_tests_empty_response(self):
        """Test never failing tests query with empty weeks data"""
        mock_json_response = {
            "data": {"weeks": []},
            "metadata": {
                "weeksRequested": 1,
                "weeksReturned": 0,
                "latestWeek": "2026-W19"
            }
        }

        responses.add(
            responses.GET,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/view/never-failing-tests",
            json=mock_json_response,
            status=200,
        )

        result = self.cli("view", "never-failing-tests", mix_stderr=False)
        self.assert_success(result)

        output_json = json.loads(result.stdout)
        self.assertEqual(len(output_json["data"]["weeks"]), 0)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_never_failing_tests_not_ready_status(self):
        """Test never failing tests query with NOT_READY calculation status"""
        mock_json_response = {
            "data": {
                "weeks": [
                    {
                        "weekDate": "2026-W19",
                        "calculationStatus": "NOT_READY",
                        "neverFailingTests": [],
                        "testCount": 0
                    }
                ]
            },
            "metadata": {
                "weeksRequested": 1,
                "weeksReturned": 1,
                "latestWeek": "2026-W19"
            }
        }

        responses.add(
            responses.GET,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/view/never-failing-tests",
            json=mock_json_response,
            status=200,
        )

        result = self.cli("view", "never-failing-tests", mix_stderr=False)
        self.assert_success(result)

        output_json = json.loads(result.stdout)
        self.assertEqual(output_json["data"]["weeks"][0]["calculationStatus"], "NOT_READY")
