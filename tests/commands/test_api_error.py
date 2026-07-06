import json
import os
import platform
import tempfile
import threading
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from unittest import mock

import responses  # type: ignore
from requests.exceptions import ReadTimeout

from smart_tests.commands.verify import compare_version
from smart_tests.utils.env_keys import BASE_URL_KEY
from smart_tests.utils.http_client import get_base_url
from tests.cli_test_case import CliTestCase


# dummy server for exe.jar
# exe.jar calls commits/latest (GET) then commits/collect (POST)
class SuccessCommitHandlerMock(SimpleHTTPRequestHandler):
    def do_GET(self):
        body = []
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode("utf-8"))

    def do_POST(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()


class ErrorCommitHandlerMock(SimpleHTTPRequestHandler):
    def do_GET(self):
        body = []
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode("utf-8"))

    def do_POST(self):
        body = {"reason": "Internal server error"}
        self.send_response(500)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode("utf-8"))


CLI_TRACKING_URL = "{base}/intake/cli_tracking"


class APIErrorTest(CliTestCase):
    test_files_dir = Path(__file__).parent.joinpath('../data/minitest/').resolve()

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_verify(self):
        verification_url = f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/verification"
        responses.add(
            responses.GET,
            verification_url,
            body=ReadTimeout("error"))
        result = self.cli("verify")
        self.assert_success(result)

        responses.add(
            responses.GET,
            verification_url,
            body=ConnectionError("error"))
        tracking = responses.add(
            responses.POST,
            f"{get_base_url()}/intake/cli_tracking",
            body=ReadTimeout("error"))
        result = self.cli("verify")
        self.assert_success(result)
        # Since Timeout error is caught inside of LaunchableClient, the tracking event is sent twice.
        self.assert_tracking_count(tracking=tracking, count=2)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_record_commit(self):
        server = HTTPServer(("", 0), ErrorCommitHandlerMock)
        thread = threading.Thread(None, server.serve_forever)
        thread.start()

        host, port = server.server_address
        endpoint = f"http://{host}:{port}"

        with mock.patch.dict(os.environ, {BASE_URL_KEY: endpoint}):
            result = self.cli("record", "commit", "--name", "test-commit", "--source", ".")
            self.assert_success(result)
            self.assertEqual(result.exception, None)

        server.shutdown()
        thread.join(timeout=3)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_record_build(self):
        # case: cli catches error
        success_server = HTTPServer(("", 0), SuccessCommitHandlerMock)
        thread = threading.Thread(None, success_server.serve_forever)
        thread.start()

        host, port = success_server.server_address
        endpoint = f"http://{host}:{port}"
        with mock.patch.dict(os.environ, {BASE_URL_KEY: endpoint}):
            responses.add(
                responses.GET,
                f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/commits/collect/options",
                json={'commitMessage': True},
                status=200)
            responses.add(responses.POST,
                          f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/builds",
                          status=500)
            tracking = responses.add(
                responses.POST,
                f"{get_base_url()}/intake/cli_tracking",
                body=ReadTimeout("error"))

            result = self.cli(
                "record",
                "build",
                "--build",
                "example",
                "--branch",
                "main",
                "--repo-branch-map",
                ".=main",
                "--no-commit-collection")
            self.assert_success(result)
            self.assertEqual(result.exception, None)
            # Since HTTPError is occurred outside of LaunchableClient, the count is 1.
            self.assert_tracking_count(tracking=tracking, count=2)

        success_server.shutdown()
        thread.join(timeout=3)

        # case: exe.jar catches error
        error_server = HTTPServer(("", 0), ErrorCommitHandlerMock)
        thread = threading.Thread(None, error_server.serve_forever)
        thread.start()

        host, port = error_server.server_address
        endpoint = f"http://{host}:{port}"

        with mock.patch.dict(os.environ, {BASE_URL_KEY: endpoint}):
            responses.add(
                responses.GET,
                f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/commits/collect/options",
                json={'commitMessage': True},
                status=200)
            responses.add(responses.POST,
                          f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/builds",
                          status=500)
            tracking = responses.add(
                responses.POST,
                f"{get_base_url()}/intake/cli_tracking",
                body=ReadTimeout("error"))

            result = self.cli(
                "record",
                "build",
                "--build",
                "example",
                "--branch",
                "main",
                "--repo-branch-map",
                ".=main",
                "--no-commit-collection")
            self.assert_success(result)
            self.assertEqual(result.exception, None)
            # Since HTTPError is occurred outside of LaunchableClient, the count is 1.
            self.assert_tracking_count(tracking=tracking, count=2)

        error_server.shutdown()
        thread.join(timeout=3)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_record_session(self):
        build = "internal_server_error"
        responses.add(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/builds/{build}/test_sessions",
            status=500)
        tracking = responses.add(
            responses.POST,
            f"{get_base_url()}/intake/cli_tracking",
            body=ReadTimeout("error"))

        result = self.cli("record", "session", "--build", build, "--test-suite", "test-suite")
        self.assert_success(result)
        self.assert_tracking_count(tracking=tracking, count=1)

        build = "not_found"
        responses.add(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/builds/{build}/test_sessions",
            status=404)
        tracking = responses.add(
            responses.POST,
            f"{get_base_url()}/intake/cli_tracking",
            body=ReadTimeout("error"))

        result = self.cli("record", "session", "--build", build, "--test-suite", "test-suite")
        self.assert_exit_code(result, 1)
        self.assert_tracking_count(tracking=tracking, count=1)

        tracking = responses.add(
            responses.POST,
            f"{get_base_url()}/intake/cli_tracking",
            body=ReadTimeout("error"))

        result = self.cli(
            "record", "session", "--build", self.build_name,
            "--test-suite", "test-suite")
        self.assert_success(result)
        # Since Timeout error is caught inside of LaunchableClient, the tracking event is sent twice.
        self.assert_tracking_count(tracking=tracking, count=0)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_subset(self):
        responses.replace(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/subset",
            status=500)
        tracking = responses.add(
            responses.POST,
            f"{get_base_url()}/intake/cli_tracking",
            body=ReadTimeout("error"))

        subset_file = "example_test.rb"

        with tempfile.NamedTemporaryFile(delete=False) as rest_file:
            result = self.cli(
                "subset",
                "minitest",
                "--target",
                "30%",
                "--session",
                self.session,
                "--rest",
                rest_file.name,
                str(self.test_files_dir) + "/test/**/*.rb",
                mix_stderr=False)

            self.assert_success(result)
            self.assertEqual(len(result.stdout.rstrip().split("\n")), 1)
            self.assertTrue(subset_file in result.stdout)
            self.assertEqual(Path(rest_file.name).read_text(), "")
            # Since HTTPError is occurred outside of LaunchableClient, the count is 1.
            self.assert_tracking_count(tracking=tracking, count=1)

        responses.replace(responses.POST,
                          f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/subset",
                          status=404)

        with tempfile.NamedTemporaryFile(delete=False) as rest_file:
            result = self.cli("subset",
                              "minitest",
                              "--target",
                              "30%",
                              "--session",
                              self.session,
                              "--rest",
                              rest_file.name,
                              str(self.test_files_dir) + "/test/**/*.rb",
                              mix_stderr=False)
            self.assert_success(result)

            self.assertEqual(len(result.stdout.rstrip().split("\n")), 1)
            self.assertTrue(subset_file in result.stdout)
            self.assertEqual(Path(rest_file.name).read_text(), "")

        responses.replace(
            responses.GET,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/"
            f"{self.workspace}/builds/{self.build_name}/test_sessions/{self.session_id}",
            body=ReadTimeout("error"))
        tracking = responses.add(
            responses.POST,
            f"{get_base_url()}/intake/cli_tracking",
            body=ReadTimeout("error"))
        with tempfile.NamedTemporaryFile(delete=False) as rest_file:
            result = self.cli("subset",
                              "minitest",
                              "--target",
                              "30%",
                              "--session",
                              self.session,
                              "--rest",
                              rest_file.name,
                              str(self.test_files_dir) + "/test/**/*.rb", mix_stderr=False)
            self.assert_success(result)
            # Since Timeout error is caught inside of LaunchableClient, the tracking event is sent twice.
            self.assert_tracking_count(tracking=tracking, count=2)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_record_tests(self):
        tracking = responses.add(
            responses.POST,
            f"{get_base_url()}/intake/cli_tracking",
            body=ReadTimeout("error"))

        result = self.cli("record", "tests", "minitest", "--session", self.session, str(self.test_files_dir) + "/")
        self.assert_success(result)
        # Since session name resolution works, the tracking event is sent once.
        self.assert_tracking_count(tracking=tracking, count=2)
        responses.replace(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/"
            f"{self.workspace}/builds/{self.build_name}/test_sessions/{self.session_id}/events",
            json=[], status=500)
        tracking = responses.add(
            responses.POST,
            f"{get_base_url()}/intake/cli_tracking",
            body=ReadTimeout("error"))

        result = self.cli("record", "tests", "minitest", "--session", self.session, str(self.test_files_dir) + "/")
        self.assert_success(result)
        # Since HTTPError is occurred outside of LaunchableClient, the count is 1.
        self.assert_tracking_count(tracking=tracking, count=3)

        responses.replace(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/"
            f"{self.workspace}/builds/{self.build_name}/test_sessions/{self.session_id}/events",
            json=[], status=404)
        tracking = responses.add(
            responses.POST,
            f"{get_base_url()}/intake/cli_tracking",
            body=ReadTimeout("error"))

        result = self.cli("record", "tests", "minitest", "--session", self.session, str(self.test_files_dir) + "/")
        self.assert_success(result)

        self.assert_tracking_count(tracking=tracking, count=3)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_all_workflow_when_server_down(self):
        # setup verify
        responses.add(
            responses.GET,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/verification",
            body=ReadTimeout("error"))
        tracking = responses.add(
            responses.POST,
            f"{get_base_url()}/intake/cli_tracking",
            body=ReadTimeout("error"))
        # setup state
        responses.replace(
            responses.GET,
            "{base}/intake/organizations/{org}/workspaces/{ws}/state".format(
                base=get_base_url(),
                org=self.organization,
                ws=self.workspace),
            body=ReadTimeout("error"))
        # setup build
        responses.replace(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/builds",
            body=ReadTimeout("error"))
        # setup subset
        responses.replace(
            responses.GET,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/"
            f"{self.workspace}/builds/{self.build_name}/test_sessions/{self.session_id}",
            body=ReadTimeout("error"))
        # setup recording tests
        responses.replace(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/"
            f"{self.workspace}/builds/{self.build_name}/test_sessions/{self.session_id}/events",
            body=ReadTimeout("error"))

        # test commands
        result = self.cli("verify")
        self.assert_success(result)
        self.assert_tracking_count(tracking=tracking, count=2)

        result = self.cli(
            "record", "build",
            "--build", "example",
            "--branch", "main",
            "--repo-branch-map", ".=main",
            "--no-commit-collection")
        self.assert_success(result)
        self.assert_tracking_count(tracking=tracking, count=5)

        # set delete=False to solve the error `PermissionError: [Errno 13] Permission denied:` on Windows.
        with tempfile.NamedTemporaryFile(delete=False) as rest_file:
            result = self.cli("subset", "minitest",
                              "--target", "30%",
                              "--session", self.session,
                              "--rest", rest_file.name,
                              str(self.test_files_dir) + "/test/**/*.rb", mix_stderr=False)
            self.assert_success(result)

        self.assert_tracking_count(tracking=tracking, count=7)

        result = self.cli("record", "tests", "minitest", "--session", self.session, str(self.test_files_dir) + "/")
        self.assert_success(result)
        self.assert_tracking_count(tracking=tracking, count=11)

    def assert_tracking_count(self, tracking, count: int):
        # Prior to 3.6, `Response` object can't be obtained.
        if compare_version([int(x) for x in platform.python_version().split('.')], [3, 7]) >= 0:
            # Sometimes, `tracking.call_count` is not updated immediately. So, wait a moment until it is updated.
            attempt = 0
            while tracking.call_count < count:
                time.sleep(0.1)
                attempt += 1
                if attempt > 10:
                    break
            self.assertEqual(tracking.call_count, count)


class FallbackModeTest(CliTestCase):
    test_files_dir = Path(__file__).parent.joinpath('../data/minitest/').resolve()

    def _subset_args(self, rest_file_name, extra_args=()):
        return (
            "subset", "minitest",
            "--target", "50%",
            "--session", self.session,
            "--rest", rest_file_name,
            str(self.test_files_dir) + "/test/**/*.rb",
        ) + tuple(extra_args)

    # --- API error cases ---

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_api_error_fallback_stop(self):
        responses.replace(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/subset",
            status=500)

        with tempfile.NamedTemporaryFile(delete=False) as rest_file:
            result = self.cli(*self._subset_args(rest_file.name, ("--fallback-mode", "stop")), mix_stderr=False)
            self.assertEqual(result.exit_code, 1)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_api_error_fallback_random_sample(self):
        responses.replace(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/subset",
            status=500)

        with tempfile.NamedTemporaryFile(delete=False) as rest_file:
            extra = ("--fallback-mode", "random-sample", "--fallback-sampling-target", "100%")
            result = self.cli(*self._subset_args(rest_file.name, extra), mix_stderr=False)
            self.assert_success(result)
            self.assertIn("example_test.rb", result.stdout)
            self.assertIn("100%", result.stderr)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_api_error_fallback_run_all_default(self):
        responses.replace(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/subset",
            status=500)

        with tempfile.NamedTemporaryFile(delete=False) as rest_file:
            result = self.cli(*self._subset_args(rest_file.name), mix_stderr=False)
            self.assert_success(result)
            self.assertIn("example_test.rb", result.stdout)

    # --- Brainless mode cases ---

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_brainless_fallback_stop(self):
        responses.replace(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/subset",
            json={"testPaths": [[{"type": "file", "name": "example_test.rb"}]],
                  "rest": [], "subsettingId": 1, "isBrainless": True, "summary": {}},
            status=200)

        with tempfile.NamedTemporaryFile(delete=False) as rest_file:
            result = self.cli(*self._subset_args(rest_file.name, ("--fallback-mode", "stop")), mix_stderr=False)
            self.assertEqual(result.exit_code, 1)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_brainless_fallback_random_sample(self):
        # In brainless mode the server already split the tests, so random-sample keeps the server's result as-is.
        responses.replace(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/subset",
            json={"testPaths": [[{"type": "file", "name": "example_test.rb"}]],
                  "rest": [], "subsettingId": 1, "isBrainless": True, "summary": {}},
            status=200)

        with tempfile.NamedTemporaryFile(delete=False) as rest_file:
            extra = ("--fallback-mode", "random-sample", "--fallback-sampling-target", "50%")
            result = self.cli(*self._subset_args(rest_file.name, extra), mix_stderr=False)
            self.assert_success(result)
            self.assertIn("example_test.rb", result.stdout)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_brainless_fallback_run_all_default(self):
        responses.replace(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/subset",
            json={"testPaths": [[{"type": "file", "name": "example_test.rb"}]],
                  "rest": [], "subsettingId": 1, "isBrainless": True, "summary": {}},
            status=200)

        with tempfile.NamedTemporaryFile(delete=False) as rest_file:
            result = self.cli(*self._subset_args(rest_file.name), mix_stderr=False)
            self.assert_success(result)
            self.assertIn("example_test.rb", result.stdout)

    # --- Validation error cases ---

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_random_sample_without_fallback_sampling_target_fails(self):
        with tempfile.NamedTemporaryFile(delete=False) as rest_file:
            result = self.cli(*self._subset_args(rest_file.name, ("--fallback-mode", "random-sample")), mix_stderr=False)
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("--fallback-sampling-target", result.stderr)
