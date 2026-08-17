"""
Smoke tests for the BYOLLM (bring-your-own-LLM) embedding path in `record commit`.

These tests mock:
- The options endpoint (returns embeddingMode=client + model/dimensions/augmentation)
- exec_jar  (captures the arguments without actually running Java)

They verify that the Python CLI:
1. Passes embedding_endpoint / embedding_model / embedding_dimensions to exec_jar
2. Passes embedding_augmentation=True only when the workspace has it enabled
3. Skips embeddings (passes None) when SMART_TESTS_EMBEDDING_ENDPOINT is unset
4. Skips embeddings when SMART_TESTS_EMBEDDING_API_KEY is unset
5. SMART_TESTS_EMBEDDING_MODEL env var overrides the model name from the options endpoint
6. embeddingMode=server → no embedding args passed
"""

import os
from unittest import mock

import responses

# Ensure the record package is imported so that sys.modules contains
# smart_tests.commands.record.commit as a module (not the Command object).
import smart_tests.commands.record  # noqa: F401
from smart_tests.utils.env_keys import EMBEDDING_API_KEY_KEY, EMBEDDING_ENDPOINT_KEY, EMBEDDING_MODEL_KEY
from smart_tests.utils.http_client import get_base_url
from tests.cli_test_case import CliTestCase

_EXEC_JAR = "smart_tests.commands.record.commit.exec_jar"


def _options_response(embedding_mode=None, embedding_model=None,
                      embedding_dimensions=None, embedding_augmentation=False):
    body = {"commitMessage": False, "files": False}
    if embedding_mode is not None:
        body["embeddingMode"] = embedding_mode
    if embedding_model is not None:
        body["embeddingModel"] = embedding_model
    if embedding_dimensions is not None:
        body["embeddingDimensions"] = embedding_dimensions
    if embedding_augmentation:
        body["embeddingAugmentation"] = True
    return body


class CommitByollmTest(CliTestCase):

    def _replace_options(self, body):
        options_url = (
            f"{get_base_url()}/intake/organizations/{self.organization}"
            f"/workspaces/{self.workspace}/commits/collect/options"
        )
        responses.replace(responses.GET, options_url, json=body, status=200)

    @responses.activate
    def test_embedding_flags_passed_to_jar(self):
        """When embeddingMode=client and env vars are set, all embedding flags reach exec_jar."""
        self._replace_options(_options_response(
            embedding_mode="client",
            embedding_model="text-embedding-3-small",
            embedding_dimensions=1536,
            embedding_augmentation=False,
        ))

        env = {
            "SMART_TESTS_TOKEN": self.smart_tests_token,
            EMBEDDING_ENDPOINT_KEY: "https://api.openai.com/v1/embeddings",
            EMBEDDING_API_KEY_KEY: "sk-test",
        }

        with mock.patch.dict(os.environ, env):
            with mock.patch(_EXEC_JAR) as mock_exec_jar:
                mock_exec_jar.return_value = None
                result = self.cli("record", "commit", "--name", "test-repo")

        self.assert_success(result)
        _, kwargs = mock_exec_jar.call_args
        args = mock_exec_jar.call_args[0]
        # exec_jar(name, source, max_days, app, is_collect_message, is_collect_files,
        #          embedding_endpoint, embedding_model, embedding_dimensions, embedding_augmentation)
        self.assertEqual(args[6], "https://api.openai.com/v1/embeddings")
        self.assertEqual(args[7], "text-embedding-3-small")
        self.assertEqual(args[8], 1536)
        self.assertFalse(args[9])

    @responses.activate
    def test_embedding_augmentation_flag_passed_when_enabled(self):
        """When embeddingAugmentation=true in workspace options, augmentation=True is passed."""
        self._replace_options(_options_response(
            embedding_mode="client",
            embedding_model="text-embedding-3-small",
            embedding_dimensions=1536,
            embedding_augmentation=True,
        ))

        env = {
            "SMART_TESTS_TOKEN": self.smart_tests_token,
            EMBEDDING_ENDPOINT_KEY: "https://api.openai.com/v1/embeddings",
            EMBEDDING_API_KEY_KEY: "sk-test",
        }

        with mock.patch.dict(os.environ, env):
            with mock.patch(_EXEC_JAR) as mock_exec_jar:
                mock_exec_jar.return_value = None
                result = self.cli("record", "commit", "--name", "test-repo")

        self.assert_success(result)
        args = mock_exec_jar.call_args[0]
        self.assertTrue(args[9])  # embedding_augmentation

    @responses.activate
    def test_skips_embeddings_when_endpoint_env_var_missing(self):
        """When SMART_TESTS_EMBEDDING_ENDPOINT is not set, embedding args are None."""
        self._replace_options(_options_response(
            embedding_mode="client",
            embedding_model="text-embedding-3-small",
            embedding_dimensions=1536,
        ))

        env_without_endpoint = {k: v for k, v in os.environ.items()
                                if k != EMBEDDING_ENDPOINT_KEY}
        env_without_endpoint["SMART_TESTS_TOKEN"] = self.smart_tests_token
        env_without_endpoint[EMBEDDING_API_KEY_KEY] = "sk-test"

        with mock.patch.dict(os.environ, env_without_endpoint, clear=True):
            with mock.patch(_EXEC_JAR) as mock_exec_jar:
                mock_exec_jar.return_value = None
                result = self.cli("record", "commit", "--name", "test-repo")

        self.assert_success(result)
        args = mock_exec_jar.call_args[0]
        self.assertIsNone(args[6])   # embedding_endpoint
        self.assertIsNone(args[7])   # embedding_model
        self.assertIsNone(args[8])   # embedding_dimensions

    @responses.activate
    def test_skips_embeddings_when_api_key_env_var_missing(self):
        """When SMART_TESTS_EMBEDDING_API_KEY is not set, embedding args are None."""
        self._replace_options(_options_response(
            embedding_mode="client",
            embedding_model="text-embedding-3-small",
            embedding_dimensions=1536,
        ))

        env_without_key = {k: v for k, v in os.environ.items()
                           if k != EMBEDDING_API_KEY_KEY}
        env_without_key["SMART_TESTS_TOKEN"] = self.smart_tests_token
        env_without_key[EMBEDDING_ENDPOINT_KEY] = "https://api.openai.com/v1/embeddings"

        with mock.patch.dict(os.environ, env_without_key, clear=True):
            with mock.patch(_EXEC_JAR) as mock_exec_jar:
                mock_exec_jar.return_value = None
                result = self.cli("record", "commit", "--name", "test-repo")

        self.assert_success(result)
        args = mock_exec_jar.call_args[0]
        self.assertIsNone(args[6])   # embedding_endpoint

    @responses.activate
    def test_env_var_overrides_server_model(self):
        """SMART_TESTS_EMBEDDING_MODEL env var takes precedence over the model from options."""
        self._replace_options(_options_response(
            embedding_mode="client",
            embedding_model="text-embedding-3-small",
            embedding_dimensions=1536,
        ))

        env = {
            "SMART_TESTS_TOKEN": self.smart_tests_token,
            EMBEDDING_ENDPOINT_KEY: "https://api.openai.com/v1/embeddings",
            EMBEDDING_API_KEY_KEY: "sk-test",
            EMBEDDING_MODEL_KEY: "text-embedding-ada-002",
        }

        with mock.patch.dict(os.environ, env):
            with mock.patch(_EXEC_JAR) as mock_exec_jar:
                mock_exec_jar.return_value = None
                result = self.cli("record", "commit", "--name", "test-repo")

        self.assert_success(result)
        args = mock_exec_jar.call_args[0]
        self.assertEqual(args[7], "text-embedding-ada-002")

    @responses.activate
    def test_no_embedding_flags_when_mode_is_server(self):
        """When embeddingMode=server, embedding args are None."""
        self._replace_options(_options_response(
            embedding_mode="server",
            embedding_model="text-embedding-3-small",
            embedding_dimensions=1536,
        ))

        env = {
            "SMART_TESTS_TOKEN": self.smart_tests_token,
            EMBEDDING_ENDPOINT_KEY: "https://api.openai.com/v1/embeddings",
            EMBEDDING_API_KEY_KEY: "sk-test",
        }

        with mock.patch.dict(os.environ, env):
            with mock.patch(_EXEC_JAR) as mock_exec_jar:
                mock_exec_jar.return_value = None
                result = self.cli("record", "commit", "--name", "test-repo")

        self.assert_success(result)
        args = mock_exec_jar.call_args[0]
        self.assertIsNone(args[6])   # embedding_endpoint
        self.assertIsNone(args[7])   # embedding_model
        self.assertIsNone(args[8])   # embedding_dimensions
