import os
from unittest import mock

import responses  # type: ignore

from launchable.utils.http_client import get_base_url
from tests.cli_test_case import CliTestCase


class FlakeDetectionTest(CliTestCase):
    @responses.activate
    @mock.patch.dict(os.environ, {"LAUNCHABLE_TOKEN": CliTestCase.launchable_token})
    def test_flake_detection_success(self):
        mock_json_response = {
            "testPaths": [
                [{"type": "file", "name": "test_flaky_1.py"}],
                [{"type": "file", "name": "test_flaky_2.py"}],
            ]
        }
        responses.add(
            responses.GET,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/retry/flake-detection",
            json=mock_json_response,
            status=200,
        )
        result = self.cli(
            "retry",
            "flake-detection",
            "--session",
            self.session,
            "--confidence",
            "high",
            "file",
            mix_stderr=False,
        )
        self.assert_success(result)
        self.assertIn("test_flaky_1.py", result.stdout)
        self.assertIn("test_flaky_2.py", result.stdout)

    @responses.activate
    @mock.patch.dict(os.environ, {"LAUNCHABLE_TOKEN": CliTestCase.launchable_token})
    def test_flake_detection_no_flakes(self):
        mock_json_response = {"testPaths": []}
        responses.add(
            responses.GET,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/retry/flake-detection",
            json=mock_json_response,
            status=200,
        )
        result = self.cli(
            "retry",
            "flake-detection",
            "--session",
            self.session,
            "--confidence",
            "low",
            "file",
            mix_stderr=False,
        )
        self.assert_success(result)
        self.assertEqual(result.stdout, "")

    @responses.activate
    @mock.patch.dict(os.environ, {"LAUNCHABLE_TOKEN": CliTestCase.launchable_token})
    def test_flake_detection_api_error(self):
        responses.add(
            responses.GET,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/retry/flake-detection",
            status=500,
        )
        result = self.cli(
            "retry",
            "flake-detection",
            "--session",
            self.session,
            "--confidence",
            "medium",
            "file",
            mix_stderr=False,
        )
        self.assert_exit_code(result, 0)
        self.assertIn("Error", result.stderr)
        self.assertEqual(result.stdout, "")
