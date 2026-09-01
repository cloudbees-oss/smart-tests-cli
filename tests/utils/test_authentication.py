import os
from unittest import TestCase, mock

import smart_tests.utils.authentication as authentication
from smart_tests.utils.authentication import authentication_headers, get_org_workspace


class AuthenticationTest(TestCase):
    @mock.patch.dict(os.environ, {}, clear=True)
    def test_get_org_workspace_no_environment_variables(self):
        org, workspace = get_org_workspace()
        self.assertIsNone(org)
        self.assertIsNone(workspace)

    @mock.patch.dict(os.environ,
                     {"SMART_TESTS_TOKEN": "v1:launchableinc/test:token"})
    def test_get_org_workspace_valid_SMART_TESTS_TOKEN(self):
        org, workspace = get_org_workspace()
        self.assertEqual("launchableinc", org)
        self.assertEqual("test", workspace)

    @mock.patch.dict(
        os.environ,
        {"SMART_TESTS_ORGANIZATION": "launchableinc", "SMART_TESTS_WORKSPACE": "test"},
        clear=True,
    )
    def test_get_org_workspace_SMART_TESTS_ORGANIZATION_and_SMART_TESTS_WORKSPACE(
            self):
        org, workspace = get_org_workspace()
        self.assertEqual("launchableinc", org)
        self.assertEqual("test", workspace)

    @mock.patch.dict(
        os.environ,
        {"SMART_TESTS_TOKEN": "v1:token_org/token_wp:token",
            "SMART_TESTS_ORGANIZATION": "org", "SMART_TESTS_WORKSPACE": "wp"},
    )
    def test_get_org_workspace_SMART_TESTS_TOKEN_and_SMART_TESTS_ORGANIZATION_and_SMART_TESTS_WORKSPACE(
            self):
        org, workspace = get_org_workspace()
        self.assertEqual("token_org", org)
        self.assertEqual("token_wp", workspace)

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_authentication_headers_empty(self):
        header = authentication_headers()
        self.assertEqual(len(header), 0)

    @mock.patch.dict(os.environ,
                     {"SMART_TESTS_TOKEN": "v1:launchableinc/test:token"})
    def test_authentication_headers_SMART_TESTS_TOKEN(self):
        header = authentication_headers()
        self.assertEqual(len(header), 1)
        self.assertEqual(
            header["Authorization"],
            "Bearer v1:launchableinc/test:token")

    @mock.patch.dict(
        os.environ,
        {"GITHUB_ACTIONS": "true", "GITHUB_RUN_ID": "1", "GITHUB_REPOSITORY": "launchableinc/test",
         "GITHUB_WORKFLOW": "build", "GITHUB_RUN_NUMBER": "1", "GITHUB_EVENT_NAME": "push",
         "GITHUB_PR_HEAD_SHA": "test0", "GITHUB_SHA": "test1"},
        clear=True,
    )
    def test_authentication_headers_GitHub_Actions_with_PR_head(self):
        header = authentication_headers()
        self.assertEqual(len(header), 8)
        self.assertEqual(header["GitHub-Actions"], "true")
        self.assertEqual(header["GitHub-Run-Id"], "1")
        self.assertEqual(header["GitHub-Repository"], "launchableinc/test")
        self.assertEqual(header["GitHub-Workflow"], "build")
        self.assertEqual(header["GitHub-Run-Number"], "1")
        self.assertEqual(header["GitHub-Event-Name"], "push")
        self.assertEqual(header["GitHub-Pr-Head-Sha"], "test0")
        self.assertEqual(header["GitHub-Sha"], "test1")

    @mock.patch.dict(
        os.environ,
        {"GITHUB_ACTIONS": "true", "GITHUB_RUN_ID": "1", "GITHUB_REPOSITORY": "launchableinc/test",
         "GITHUB_WORKFLOW": "build", "GITHUB_RUN_NUMBER": "1", "GITHUB_EVENT_NAME": "push",
         "GITHUB_SHA": "test"},
        clear=True,
    )
    def test_authentication_headers_GitHub_Actions_without_PR_head(self):
        header = authentication_headers()
        self.assertEqual(len(header), 7)
        self.assertEqual(header["GitHub-Actions"], "true")
        self.assertEqual(header["GitHub-Run-Id"], "1")
        self.assertEqual(header["GitHub-Repository"], "launchableinc/test")
        self.assertEqual(header["GitHub-Workflow"], "build")
        self.assertEqual(header["GitHub-Run-Number"], "1")
        self.assertEqual(header["GitHub-Event-Name"], "push")
        self.assertEqual(header["GitHub-Sha"], "test")

    @mock.patch.dict(
        os.environ,
        {"SMART_TESTS_TOKEN": "v1:launchableinc/test:token", "GITHUB_ACTIONS": "true", "GITHUB_RUN_ID": "1",
         "GITHUB_REPOSITORY": "launchableinc/test", "GITHUB_WORKFLOW": "build", "GITHUB_RUN_NUMBER": "1",
         "GITHUB_EVENT_NAME": "push", "GITHUB_SHA": "test"},
        clear=True,
    )
    def test_authentication_headers_SMART_TESTS_TOKEN_and_GitHub_Actions(self):
        header = authentication_headers()
        self.assertEqual(len(header), 1)
        self.assertEqual(
            header["Authorization"],
            "Bearer v1:launchableinc/test:token")

    @mock.patch("smart_tests.utils.authentication.requests.get")
    @mock.patch.dict(
        os.environ,
        {"SMART_TESTS_GITHUB_OIDC_TOKEN_AUTH": "1",
         "ACTIONS_ID_TOKEN_REQUEST_URL": "https://runner.example/token?api-version=2.0",
         "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "rt-token"},
        clear=True,
    )
    def test_authentication_headers_github_oidc_generic(self, mock_get):
        mock_get.return_value = mock.Mock(
            raise_for_status=mock.Mock(), json=mock.Mock(return_value={"value": "id-token"}))

        header = authentication_headers()

        # Generic path: plain OIDC bearer, no legacy header.
        self.assertEqual(header, {"Authorization": "Bearer id-token"})
        # The id-token is requested for the Smart Tests audience so Intake's aud check passes.
        requested_url = mock_get.call_args[0][0]
        self.assertIn("audience=https%3A%2F%2Fapp.cloudbees.io%2Fsmart-tests", requested_url)

    @mock.patch("smart_tests.utils.authentication.requests.get")
    @mock.patch.dict(
        os.environ,
        {"EXPERIMENTAL_GITHUB_OIDC_TOKEN_AUTH": "1",
         "ACTIONS_ID_TOKEN_REQUEST_URL": "https://runner.example/token?api-version=2.0",
         "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "rt-token"},
        clear=True,
    )
    def test_authentication_headers_github_oidc_legacy(self, mock_get):
        mock_get.return_value = mock.Mock(
            raise_for_status=mock.Mock(), json=mock.Mock(return_value={"value": "id-token"}))

        header = authentication_headers()

        # Legacy path: bearer plus the opt-in header that routes Intake to the deprecated flow.
        self.assertEqual(header["Authorization"], "Bearer id-token")
        self.assertEqual(header["GitHub-OIDC-Legacy"], "1")
        # Legacy path does not enforce aud, so no audience is requested.
        self.assertNotIn("audience=", mock_get.call_args[0][0])

    @mock.patch("smart_tests.utils.authentication.click.secho")
    @mock.patch("smart_tests.utils.authentication.requests.get")
    @mock.patch.dict(
        os.environ,
        {"EXPERIMENTAL_GITHUB_OIDC_TOKEN_AUTH": "1",
         "ACTIONS_ID_TOKEN_REQUEST_URL": "https://runner.example/token?api-version=2.0",
         "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "rt-token"},
        clear=True,
    )
    def test_authentication_headers_legacy_warning_printed_once(self, mock_get, mock_secho):
        mock_get.return_value = mock.Mock(
            raise_for_status=mock.Mock(), json=mock.Mock(return_value={"value": "id-token"}))
        # The once-per-process guard is module state; reset it so this test is deterministic.
        authentication._legacy_oidc_warning_shown = False

        # authentication_headers() runs on every API request; the deprecation warning must not
        # repeat on each call.
        authentication_headers()
        authentication_headers()
        authentication_headers()

        self.assertEqual(mock_secho.call_count, 1)

    @mock.patch("smart_tests.utils.authentication.requests.get")
    @mock.patch.dict(
        os.environ,
        {"SMART_TESTS_GITHUB_OIDC_TOKEN_AUTH": "1",
         "EXPERIMENTAL_GITHUB_OIDC_TOKEN_AUTH": "1",
         "ACTIONS_ID_TOKEN_REQUEST_URL": "https://runner.example/token?api-version=2.0",
         "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "rt-token"},
        clear=True,
    )
    def test_authentication_headers_github_oidc_generic_wins_over_legacy(self, mock_get):
        mock_get.return_value = mock.Mock(
            raise_for_status=mock.Mock(), json=mock.Mock(return_value={"value": "id-token"}))

        header = authentication_headers()

        # When both flags are set, the generic (non-deprecated) path takes precedence.
        self.assertEqual(header, {"Authorization": "Bearer id-token"})
