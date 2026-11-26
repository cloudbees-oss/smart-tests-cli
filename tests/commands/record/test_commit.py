import io
import json
import os
import subprocess
import threading
from contextlib import redirect_stderr
from http.server import HTTPServer, SimpleHTTPRequestHandler
from unittest import mock

from smart_tests.commands.record.commit import _build_proxy_option, _check_embedding_env, exec_jar
from smart_tests.utils.embedding import EmbeddingOptions
from smart_tests.utils.env_keys import BASE_URL_KEY, EMBEDDING_API_KEY, EMBEDDING_ENDPOINT
from tests.cli_test_case import CliTestCase


class CommitHandler(SimpleHTTPRequestHandler):
    # mock commits/latest
    def do_GET(self):
        response = []
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(response).encode("utf-8"))

    # mock commits/collect
    def do_POST(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()


class CommitTest(CliTestCase):

    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_run_commit(self):
        server = HTTPServer(("", 0), CommitHandler)
        thread = threading.Thread(None, server.serve_forever)
        thread.start()

        host, port = server.server_address
        endpoint = f"http://{host}:{port}"

        with mock.patch.dict(os.environ, {BASE_URL_KEY: endpoint}):
            result = self.cli("record", "commit", "--name", "test-commit")
            self.assert_success(result)

        server.shutdown()
        thread.join()

    def test_embedding_env_present(self):
        env = {EMBEDDING_ENDPOINT: "https://llm.example.com/v1", EMBEDDING_API_KEY: "secret"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertTrue(_check_embedding_env())

    def test_embedding_env_missing_warns_and_continues(self):
        stderr = io.StringIO()
        with mock.patch.dict(os.environ, {EMBEDDING_API_KEY: "secret"}, clear=True), \
                mock.patch("smart_tests.utils.fail_fast_mode._fail_fast_mode_cache", False), \
                redirect_stderr(stderr):
            self.assertFalse(_check_embedding_env())
        self.assertIn(EMBEDDING_ENDPOINT, stderr.getvalue())
        self.assertNotIn(EMBEDDING_API_KEY, stderr.getvalue())

    def test_embedding_env_missing_exits_in_fail_fast_mode(self):
        stderr = io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch("smart_tests.utils.fail_fast_mode._fail_fast_mode_cache", True), \
                redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as cm:
                _check_embedding_env()
        self.assertEqual(cm.exception.code, 1)
        self.assertIn(EMBEDDING_ENDPOINT, stderr.getvalue())
        self.assertIn(EMBEDDING_API_KEY, stderr.getvalue())

    def _exec_jar_command(self, embedding_config):
        """Runs exec_jar with subprocess and java mocked out, and returns the command it would have run."""
        app = mock.Mock(dry_run=False, skip_cert_verification=False)
        env = {EMBEDDING_ENDPOINT: "https://llm.example.com/v1/embeddings", EMBEDDING_API_KEY: "secret-key"}
        with mock.patch.dict(os.environ, env), \
                mock.patch("smart_tests.commands.record.commit.get_java_command", return_value="java"), \
                mock.patch("smart_tests.commands.record.commit.subprocess.run") as run:
            exec_jar("test", "/repo", 30, app, False, True, embedding_config)
        return run.call_args[0][0]

    def test_exec_jar_passes_model_details_in_client_mode(self):
        config = EmbeddingOptions("client", 7, "OpenAI", "text-embedding-3-small", 1536)

        command = self._exec_jar_command(config)

        self.assertIn("-client-embedding", command)
        for flag, value in (("-embedding-provider", "OpenAI"), ("-embedding-model-name", "text-embedding-3-small"),
                            ("-embedding-model-id", "7"), ("-embedding-dimensions", "1536")):
            self.assertEqual(command[command.index(flag) + 1], value)

    def test_exec_jar_never_puts_the_endpoint_or_key_on_the_command_line(self):
        config = EmbeddingOptions("client", 7, "OpenAI", "text-embedding-3-small", 1536)

        command = " ".join(self._exec_jar_command(config))

        self.assertNotIn("secret-key", command)
        self.assertNotIn("llm.example.com", command)

    def test_exec_jar_adds_no_embedding_flags_otherwise(self):
        for config in (None, EmbeddingOptions("server")):
            command = self._exec_jar_command(config)
            self.assertFalse([c for c in command if c.startswith("-embedding") or c == "-client-embedding"])

    def _run_commit_with_jar_failure(self, options, exit_status):
        """Runs `record commit` where collect/options answers `options` and the jar exits with `exit_status`."""
        response = mock.Mock()
        response.json.return_value = options
        stderr = io.StringIO()
        env = {"SMART_TESTS_TOKEN": self.smart_tests_token,
               EMBEDDING_ENDPOINT: "https://x/v1/embeddings", EMBEDDING_API_KEY: "k"}
        with mock.patch("smart_tests.commands.record.commit.SmartTestsClient.request", return_value=response), \
                mock.patch("smart_tests.commands.record.commit.exec_jar") as exec_jar_mock, \
                mock.patch("smart_tests.utils.fail_fast_mode._fail_fast_mode_cache", False), \
                mock.patch.dict(os.environ, env), \
                redirect_stderr(stderr):
            exec_jar_mock.side_effect = subprocess.CalledProcessError(exit_status, "java")
            result = self.cli("record", "commit", "--name", "test-commit")
        return exec_jar_mock, result, stderr.getvalue() + result.output

    def test_commit_reports_embedding_failure_instead_of_blaming_the_git_directory(self):
        options = {"files": True, "embedding": {"mode": "client", "modelId": 7, "provider": "OpenAI",
                                                "modelName": "m", "dimensions": 4}}

        exec_jar_mock, _, output = self._run_commit_with_jar_failure(options, 3)

        self.assertIn("Client-side embedding failed.", output)
        self.assertNotIn("Do you run command root of git-controlled directory", output)
        # the model details were handed to the jar
        self.assertTrue(exec_jar_mock.call_args[0][-1].is_client_mode)

    def test_commit_other_jar_failures_still_get_the_git_message(self):
        _, _, output = self._run_commit_with_jar_failure({"files": True, "embedding": {"mode": "server"}}, 1)

        self.assertIn("Do you run command root of git-controlled directory", output)

    def test_commit_does_not_use_client_embedding_when_files_are_not_collected(self):
        options = {"files": False, "embedding": {"mode": "client", "modelId": 7, "provider": "OpenAI",
                                                 "modelName": "m", "dimensions": 4}}

        exec_jar_mock, _, _ = self._run_commit_with_jar_failure(options, 1)

        self.assertIsNone(exec_jar_mock.call_args[0][-1])

    def test_proxy_options(self):
        self.assertEqual(_build_proxy_option("https://some_proxy:1234"),
                         ['-Dhttps.proxyHost=some_proxy', '-Dhttps.proxyPort=1234'])
        self.assertEqual(_build_proxy_option("some_proxy:1234"), ['-Dhttps.proxyHost=some_proxy', '-Dhttps.proxyPort=1234'])
        self.assertEqual(_build_proxy_option("some_proxy"), ['-Dhttps.proxyHost=some_proxy'])
        self.assertEqual(_build_proxy_option("https://some_proxy"), ['-Dhttps.proxyHost=some_proxy'])
        self.assertEqual(_build_proxy_option("http://yoyoyo"), ['-Dhttps.proxyHost=yoyoyo'])
