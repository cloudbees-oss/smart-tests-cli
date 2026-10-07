import json
import os
from unittest import mock

import responses

from smart_tests.utils.http_client import get_base_url
from tests.cli_test_case import CliTestCase


class ViewSubsetsTest(CliTestCase):
    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_subsets_basic(self):
        """Test listing subsets of a test session"""
        mock_json_response = [
            {
                "subsetId": 26876,
                "testSessionId": 6909578,
                "createdAt": "2026-10-01T00:00:00Z",
                "inputTestPathCount": 3,
                "summary": {
                    "subset": {"candidates": 2, "rate": 98.4, "duration": 1.5, "newTestCount": 1},
                    "rest": {"candidates": 1, "rate": 1.6, "duration": 0.025, "newTestCount": 1}
                }
            }
        ]

        responses.add(
            responses.GET,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/view/subsets",
            json=mock_json_response,
            status=200,
        )

        result = self.cli("view", "subsets", "--test-session-id", "6909578", mix_stderr=False)
        self.assert_success(result)

        self.assertEqual(len(responses.calls), 1)
        self.assertIn("test-session-id=6909578", responses.calls[0].request.url)

        output_json = json.loads(result.stdout)
        self.assertEqual(output_json[0]["subsetId"], 26876)
        self.assertEqual(output_json[0]["inputTestPathCount"], 3)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_subsets_empty(self):
        """Test a test session without any subsets"""
        responses.add(
            responses.GET,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/view/subsets",
            json=[],
            status=200,
        )

        result = self.cli("view", "subsets", "--test-session-id", "1", mix_stderr=False)
        self.assert_success(result)
        self.assertEqual(json.loads(result.stdout), [])

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_subsets_not_found(self):
        """Test a test session that does not exist in the workspace"""
        responses.add(
            responses.GET,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/view/subsets",
            json={},
            status=404,
        )

        result = self.cli("view", "subsets", "--test-session-id", "999", mix_stderr=False)
        self.assert_exit_code(result, 1)
        self.assertIn("Test session 999 not found", result.stderr)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_subsets_api_error(self):
        """Test when the API returns an error"""
        responses.add(
            responses.GET,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/view/subsets",
            status=500,
        )

        result = self.cli("view", "subsets", "--test-session-id", "1", mix_stderr=False)
        self.assert_exit_code(result, 1)
        self.assertIn("Error", result.stderr)

    def test_subsets_missing_test_session_id(self):
        """Test that --test-session-id is required"""
        result = self.cli("view", "subsets", mix_stderr=False)
        self.assert_exit_code(result, 1)
        self.assertIn("--test-session-id", result.stderr)

    def test_subsets_invalid_test_session_id(self):
        """Test that --test-session-id must be a positive integer"""
        result = self.cli("view", "subsets", "--test-session-id", "abc", mix_stderr=False)
        self.assert_exit_code(result, 1)
