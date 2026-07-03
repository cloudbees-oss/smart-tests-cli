import base64
import json
import os
from subprocess import CalledProcessError
from unittest import TestCase
from unittest.mock import patch

import responses  # type: ignore

from smart_tests.commands.verify import check_java_version, compare_java_version, compare_version, parse_version
from smart_tests.utils.http_client import get_base_url
from tests.cli_test_case import CliTestCase


class VersionTest(TestCase):
    def test_compare_version(self):
        def sign(x):
            if x < 0:
                return -1
            if x > 0:
                return 1
            return 0

        def f(expected, a, b):
            """Ensure symmetry on two sides"""
            self.assertEqual(sign(compare_version(a, b)), expected)
            self.assertEqual(sign(compare_version(b, a)), -expected)

        f(0, [1, 1, 0], [1, 1])     # 1.1.0 = 1.1
        f(1, [1, 1], [1, 0])        # 1.1 > 1.0
        f(1, [1, 0, 1], [1])        # 1.0.1 > 1

    def test_python_version_with_plus_sign(self):
        """Test that Python versions with '+' character are parsed correctly"""
        self.assertEqual(parse_version('3.13.0+'), [3, 13, 0])
        self.assertEqual(parse_version('3.13+'), [3, 13])
        self.assertEqual(parse_version('3.13.0'), [3, 13, 0])

    def test_java_version(self):
        self.assertTrue(compare_java_version(
            """
    java version "1.8.0_144"
    Java(TM) SE Runtime Environment (build 1.8.0_144-b01)
    Java HotSpot(TM) 64-Bit Server VM (build 25.144-b01, mixed mode)
    """
        ) >= 0)

        self.assertTrue(compare_java_version(
            """
    java version "1.5.0_22"
    Java(TM) 2 Runtime Environment, Standard Edition (build 1.5.0_22-b03)
    Java HotSpot(TM) 64-Bit Server VM (build 1.5.0_22-b03, mixed mode)
    """
        ) < 0)

    @patch('smart_tests.commands.verify.subprocess.run')
    def test_check_java_version(self, mock_run):
        mock_run.side_effect = CalledProcessError(1, 'java -version')
        result = check_java_version('java')
        self.assertEqual(result, -1)


class VerifyCommandTest(CliTestCase):
    """Test the verify command with display names"""

    @responses.activate
    @patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_verify_shows_display_name(self):
        """Test that verify displays organizationDisplayName and workspaceDisplayName from API response"""
        verification_url = f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/verification"

        # Mock server response with displayName fields
        responses.add(
            responses.GET,
            verification_url,
            json={
                "organization": self.organization,
                "organizationDisplayName": "My Company",
                "workspace": self.workspace,
                "workspaceDisplayName": "Production"
            },
            status=200
        )

        result = self.cli("verify")
        self.assert_success(result)

        # Verify displayName appears in output
        self.assertIn("'My Company'", result.output)
        self.assertIn("'Production'", result.output)

    @responses.activate
    @patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_verify_fallback_when_no_display_name(self):
        """Test that verify falls back to org/workspace when displayName not in response"""
        verification_url = f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/verification"

        # Mock server response without displayName fields
        responses.add(
            responses.GET,
            verification_url,
            json={},
            status=200
        )

        result = self.cli("verify")
        self.assert_success(result)

        # Should show original org/workspace names
        self.assertIn(f"'{self.organization}'", result.output)
        self.assertIn(f"'{self.workspace}'", result.output)


class VerifyOidcCommandTest(CliTestCase):
    """Test the credential-free `verify --oidc` bootstrap flow."""

    oidc_token = "header.payload.signature"
    base_url = "http://localhost:8080"
    oidc_verify_url = f"{base_url}/intake/oidc/verify"
    oidc_env = {"SMART_TESTS_OIDC_TOKEN": oidc_token, "SMART_TESTS_BASE_URL": base_url}

    @responses.activate
    @patch.dict(os.environ, oidc_env, clear=True)
    def test_oidc_registered_emits_exports(self):
        """200 → print eval-able export lines for org/workspace/token, exit 0."""
        responses.add(
            responses.POST,
            self.oidc_verify_url,
            json={"organization": "acme", "workspace": "prod"},
            status=200,
        )

        result = self.cli("verify", "--oidc")
        self.assert_success(result)

        self.assertIn("export SMART_TESTS_ORGANIZATION='acme'", result.output)
        self.assertIn("export SMART_TESTS_WORKSPACE='prod'", result.output)
        self.assertIn(f"export SMART_TESTS_OIDC_TOKEN='{self.oidc_token}'", result.output)

        # The token must be presented as the bearer to the verify endpoint.
        self.assertEqual(responses.calls[0].request.headers["Authorization"], f"Bearer {self.oidc_token}")

    @responses.activate
    @patch.dict(os.environ, oidc_env, clear=True)
    def test_oidc_unregistered_shows_paste_block(self):
        """403 → show the copy/paste registration block (issuer + normalized-sub), exit 1, no exports."""
        issuer = "https://jenkins.example.com/oidc"
        sub = "https://jenkins.example.com/job/my-pipeline/"
        responses.add(
            responses.POST,
            self.oidc_verify_url,
            json={"issuer": issuer, "sub": sub},
            status=403,
        )

        result = self.cli("verify", "--oidc")
        self.assert_exit_code(result, 1)
        self.assertIn("########## start ##########", result.output)
        self.assertIn("########## end ##########", result.output)
        self.assertIn(issuer, result.output)
        self.assertIn(sub, result.output)
        self.assertIn("normalized-sub", result.output)
        self.assertNotIn("export SMART_TESTS_ORGANIZATION", result.output)

    @responses.activate
    @patch.dict(os.environ, oidc_env, clear=True)
    def test_oidc_invalid_token_fails(self):
        """401 → authentication failed, exit 1."""
        responses.add(
            responses.POST,
            self.oidc_verify_url,
            json={"reason": "bad token"},
            status=401,
        )

        result = self.cli("verify", "--oidc")
        self.assert_exit_code(result, 1)
        self.assertNotIn("export SMART_TESTS_ORGANIZATION", result.output)

    @patch.dict(os.environ, {}, clear=True)
    def test_oidc_missing_token(self):
        """No OIDC token in the environment → usage error, exit 2."""
        result = self.cli("verify", "--oidc")
        self.assert_exit_code(result, 2)
        self.assertIn("SMART_TESTS_OIDC_TOKEN", result.output)


def _make_jwt(claims: dict) -> str:
    """Build an unsigned-looking JWT (header.payload.signature) with the given claims payload."""
    def seg(obj):
        raw = json.dumps(obj).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    return f"{seg({'alg': 'RS256', 'typ': 'JWT'})}.{seg(claims)}.signature"


class VerifyOidcFetchIssuerCommandTest(CliTestCase):
    """Test `verify --oidc-fetch-issuer`: discover the issuer's JWKS from inside the private network
    and print an {issuer, jwks} paste block. It must NOT hit the credential-free verify endpoint."""

    issuer = "http://jenkins.internal:8080/oidc"
    token = _make_jwt({"iss": issuer, "sub": "http://jenkins.internal:8080/job/pipeline/"})
    jwks = {"keys": [{"kty": "RSA", "kid": "k1", "n": "AAAA", "e": "AQAB"}]}

    def _mock_discovery(self):
        responses.add(
            responses.GET,
            f"{self.issuer}/.well-known/openid-configuration",
            json={"jwks_uri": f"{self.issuer}/jwks"},
            status=200,
        )
        responses.add(responses.GET, f"{self.issuer}/jwks", json=self.jwks, status=200)

    @responses.activate
    @patch.dict(os.environ, {"SMART_TESTS_OIDC_TOKEN": token}, clear=True)
    def test_fetch_issuer_prints_issuer_jwks_block(self):
        """--oidc-fetch-issuer → discover JWKS, print {issuer, jwks} block, exit 0."""
        self._mock_discovery()

        result = self.cli("verify", "--oidc-fetch-issuer")
        self.assert_success(result)

        self.assertIn("########## start ##########", result.output)
        self.assertIn("########## end ##########", result.output)

        # The stdout block must parse to {issuer, jwks} with the discovered keys.
        start = result.output.index("########## start ##########") + len("########## start ##########")
        end = result.output.index("########## end ##########")
        parsed = json.loads(result.output[start:end])
        self.assertEqual(parsed["issuer"], self.issuer)
        self.assertEqual(parsed["jwks"], self.jwks)

        # It must NOT call the credential-free verify endpoint — the key never travels with the token.
        for call in responses.calls:
            self.assertNotIn("/oidc/verify", call.request.url)

    @patch.dict(os.environ, {}, clear=True)
    def test_fetch_issuer_missing_token(self):
        """No OIDC token → usage error, exit 2."""
        result = self.cli("verify", "--oidc-fetch-issuer")
        self.assert_exit_code(result, 2)
        self.assertIn("SMART_TESTS_OIDC_TOKEN", result.output)

    @patch.dict(os.environ, {"SMART_TESTS_OIDC_TOKEN": "not-a-jwt"}, clear=True)
    def test_fetch_issuer_malformed_token(self):
        """Token that isn't a well-formed JWT → exit 2, mentions iss."""
        result = self.cli("verify", "--oidc-fetch-issuer")
        self.assert_exit_code(result, 2)
        self.assertIn("iss", result.output)

    @responses.activate
    @patch.dict(os.environ, {"SMART_TESTS_OIDC_TOKEN": token}, clear=True)
    def test_fetch_issuer_unreachable_issuer_fails(self):
        """Discovery endpoint unreachable/404 → exit 1, no paste block."""
        responses.add(
            responses.GET,
            f"{self.issuer}/.well-known/openid-configuration",
            status=404,
        )
        result = self.cli("verify", "--oidc-fetch-issuer")
        self.assert_exit_code(result, 1)
        self.assertNotIn("########## start ##########", result.output)

    @responses.activate
    @patch.dict(os.environ, {"SMART_TESTS_OIDC_TOKEN": token}, clear=True)
    def test_fetch_issuer_cross_origin_jwks_uri_rejected(self):
        """A tampered discovery document whose jwks_uri points at a different host is rejected:
        exit 1, no paste block, and the off-origin JWKS URL is never fetched."""
        evil_jwks_uri = "http://169.254.169.254/latest/meta-data/jwks"
        responses.add(
            responses.GET,
            f"{self.issuer}/.well-known/openid-configuration",
            json={"jwks_uri": evil_jwks_uri},
            status=200,
        )
        responses.add(responses.GET, evil_jwks_uri, json=self.jwks, status=200)

        result = self.cli("verify", "--oidc-fetch-issuer")
        self.assert_exit_code(result, 1)
        self.assertNotIn("########## start ##########", result.output)

        # The off-origin jwks_uri must never be fetched.
        for call in responses.calls:
            self.assertNotIn("169.254.169.254", call.request.url)

    @patch.dict(os.environ, {"SMART_TESTS_OIDC_TOKEN": token}, clear=True)
    def test_oidc_and_fetch_issuer_mutually_exclusive(self):
        """--oidc together with --oidc-fetch-issuer → usage error, exit 2."""
        result = self.cli("verify", "--oidc", "--oidc-fetch-issuer")
        self.assert_exit_code(result, 2)
