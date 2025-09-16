import os
from unittest import mock

import responses  # type: ignore

from launchable.utils.http_client import get_base_url
from tests.cli_test_case import CliTestCase


class DetectFlakeTest(CliTestCase):
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
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/detect-flake",
            json=mock_json_response,
            status=200,
        )
        result = self.cli(
            "detect-flake",
            "--session",
            self.session,
            "--retry-threshold",
            "high",
            "file",
            mix_stderr=False,
        )
        self.assert_success(result)
        self.assertIn("test_flaky_1.py", result.stdout)
        self.assertIn("test_flaky_2.py", result.stdout)

    @responses.activate
    @mock.patch.dict(os.environ, {"LAUNCHABLE_TOKEN": CliTestCase.launchable_token})
    def test_flake_detection_without_retry_threshold_success(self):
        mock_json_response = {
            "testPaths": [
                [{"type": "file", "name": "test_flaky_1.py"}],
                [{"type": "file", "name": "test_flaky_2.py"}],
            ]
        }
        responses.add(
            responses.GET,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/detect-flake",
            json=mock_json_response,
            status=200,
        )
        result = self.cli(
            "detect-flake",
            "--session",
            self.session,
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
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/detect-flake",
            json=mock_json_response,
            status=200,
        )
        result = self.cli(
            "detect-flake",
            "--session",
            self.session,
            "--retry-threshold",
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
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/detect-flake",
            status=500,
        )
        result = self.cli(
            "detect-flake",
            "--session",
            self.session,
            "--retry-threshold",
            "medium",
            "file",
            mix_stderr=False,
        )
        self.assert_exit_code(result, 0)
        self.assertIn("Error", result.stderr)
        self.assertEqual(result.stdout, "")
