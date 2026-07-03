import base64
import binascii
import json
import os
import platform
import re
import subprocess
import urllib.parse
from typing import Annotated, List, Optional

import click
import requests

import smart_tests.args4p.typer as typer
from smart_tests.utils.tracking import Tracking, TrackingClient

from .. import args4p
from ..app import Application
from ..utils.authentication import ensure_org_workspace, get_oidc_token, get_org_workspace
from ..utils.commands import Command
from ..utils.env_keys import OIDC_TOKEN_KEY, ORGANIZATION_KEY, TOKEN_KEY, WORKSPACE_KEY
from ..utils.http_client import DEFAULT_GET_TIMEOUT, _HttpClient
from ..utils.java import get_java_command
from ..utils.smart_tests_client import SmartTestsClient
from ..utils.typer_types import emoji
from ..version import __version__ as version

# Credential-free OIDC bootstrap endpoint. Served at /intake/oidc/verify (the app runs under the
# /intake context-path). It is intentionally NOT workspace-scoped: it self-verifies the presented
# OIDC token and resolves the org/workspace it maps to.
OIDC_VERIFY_PATH = "/intake/oidc/verify"


def parse_version(version_string: str) -> List[int]:
    """Parse version string and extract numeric parts.

    Handles version strings with special characters like '3.13.0+' by extracting
    only the numeric prefix from each component.
    """
    return [int(x) for x in version_string.replace('+', '').split('.')]


def compare_version(a: List[int], b: List[int]):
    """Compare two version numbers represented as int arrays"""

    def pick(a, i):
        return a[i] if i < len(a) else 0

    for i in range(max(len(a), len(b))):
        d = pick(a, i) - pick(b, i)
        if d != 0:
            return d  # if they are different, we have the result
    return 0  # identical


def compare_java_version(output: str) -> int:
    """Check if the Java version meets what we need. returns >=0 if we meet the requirement"""
    pattern = re.compile('"([^"]+)"')
    for line in output.splitlines():
        if line.find("java version") != -1:
            # line is like: java version "1.8.0_144"
            m = pattern.search(line)
            if m:
                tokens = m.group(1).split(".")
                if len(tokens) >= 2:
                    versions = [int(x) for x in tokens[0:2]]
                    required = [1, 8]
                    return compare_version(versions, required)
    # couldn't determine, so err on the safe side
    return 0


def check_java_version(javacmd: str) -> int:
    """Check if the Java version meets what we need. returns >=0 if we meet the requirement"""
    try:
        v = subprocess.run([javacmd, "-version"], check=True, stderr=subprocess.PIPE, universal_newlines=True)
        return compare_java_version(v.stderr)
    except subprocess.CalledProcessError:
        return -1


@args4p.command(help="Verify CLI setup and connectivity")
def verify(
    app_instance: Application,
    oidc: Annotated[bool, typer.Option(
        "--oidc",
        help="Authenticate this pipeline with its OIDC id-token (from " + OIDC_TOKEN_KEY + ") "
             "instead of an API key, and resolve the org/workspace it is registered to "
             "(the credential-free bootstrap).")] = False,
    oidc_fetch_issuer: Annotated[bool, typer.Option(
        "--oidc-fetch-issuer",
        help="Run this from INSIDE a private network to fetch the OIDC issuer's public JWKS (read "
             "from the id-token in " + OIDC_TOKEN_KEY + ") and print a block an admin pastes into "
             "the WebApp (Trusted OIDC issuers). Use this when Intake cannot reach the issuer "
             "directly, so its keys must be registered for manual verification. This authenticates "
             "nothing and contacts only the issuer.")] = False,
):
    # Run the verification (no subcommands in this app)
    # In this command, regardless of REPORT_ERROR_KEY, always report an unexpected error with full stack trace
    # to assist troubleshooting. `typer.BadParameter` is handled by the invoking
    # Click gracefully.

    if oidc and oidc_fetch_issuer:
        click.secho(
            "Use either --oidc or --oidc-fetch-issuer, not both.", fg='red', err=True)
        raise typer.Exit(2)
    if oidc_fetch_issuer:
        fetch_oidc_issuer(app_instance)
        return
    if oidc:
        verify_oidc(app_instance)
        return

    org, workspace = get_org_workspace()
    tracking_client = TrackingClient(Command.VERIFY, app=app_instance)
    client = SmartTestsClient(tracking_client=tracking_client, app=app_instance)
    java = get_java_command()

    # raise an error here after we print out the basic diagnostics if LAUNCHABLE_TOKEN is not set.
    ensure_org_workspace()

    # Fetch display names from the verification endpoint
    org_display = org
    workspace_display = workspace
    try:
        res = client.request("get", "verification")
        if res.status_code == 401:
            if os.getenv(TOKEN_KEY):
                msg = ("Authentication failed. Most likely the value for the SMART_TESTS_TOKEN "
                       "environment variable is invalid.")
            else:
                msg = ("Authentication failed. Please set the SMART_TESTS_TOKEN. "
                       "If you intend to use tokenless authentication, "
                       "kindly reach out to our support team for further assistance.")
            click.secho(msg, fg='red', err=True)
            tracking_client.send_error_event(
                event_name=Tracking.ErrorEvent.USER_ERROR,
                stack_trace=msg,
            )
            raise typer.Exit(2)
        res.raise_for_status()

        # Parse display names from response, with fallback to original values
        try:
            data = res.json()
            org_display = data.get("organizationDisplayName", org)
            workspace_display = data.get("workspaceDisplayName", workspace)
        except Exception:
            # If JSON parsing fails, continue with original values
            pass
    except Exception as e:
        tracking_client.send_error_event(
            event_name=Tracking.ErrorEvent.INTERNAL_CLI_ERROR,
            stack_trace=str(e),
            api="verification",
        )
        client.print_exception_and_recover(e)

    # Print the system information after fetching display names
    click.echo("Organization: " + repr(org_display))
    click.echo("Workspace: " + repr(workspace_display))
    click.echo("Proxy: " + repr(os.getenv("HTTPS_PROXY")))
    click.echo("Platform: " + repr(platform.platform()))
    click.echo("Python version: " + repr(platform.python_version()))
    click.echo("Java command: " + repr(java))
    click.echo("smart-tests version: " + repr(version))

    if java is None:
        msg = "Java is not installed. Install Java version 8 or newer to use the Smart Tests CLI."
        tracking_client.send_error_event(
            event_name=Tracking.ErrorEvent.INTERNAL_CLI_ERROR,
            stack_trace=msg
        )
        click.secho(msg, fg='red', err=True)
        raise typer.Exit(1)

    # Level 2 check: versions. This is more fragile than just reporting the number, so we move
    # this out here

    python_version = parse_version(platform.python_version())
    if compare_version(python_version, [3, 6]) < 0:
        msg = "Python 3.6 or later is required"
        tracking_client.send_error_event(
            event_name=Tracking.ErrorEvent.INTERNAL_CLI_ERROR,
            stack_trace=msg
        )
        click.secho(msg, fg='red', err=True)
        raise typer.Exit(1)

    if check_java_version(java) < 0:
        msg = "Java 8 or later is required"
        tracking_client.send_error_event(
            event_name=Tracking.ErrorEvent.INTERNAL_CLI_ERROR,
            stack_trace=msg
        )
        click.secho(msg, fg='red', err=True)
        raise typer.Exit(1)

    click.secho("Your CLI configuration is successfully verified" + emoji(" \U0001f389"), fg='green')


def verify_oidc(app_instance: Application):
    '''
    Credential-free OIDC bootstrap. Presents the pipeline's OIDC id-token to Intake's
    /intake/oidc/verify endpoint and translates the 200/403/401 contract into CLI behavior:

      - 200: the subject is registered. Print `export` lines (org/workspace/oidc-token) so the
             pipeline can `eval "$(smart-tests verify --oidc)"` and authenticate subsequent
             commands with the same token. Exit 0.
      - 403: the token verified but its subject isn't registered to any workspace yet. Show the
             normalized `sub` so the user can register it from the WebApp settings. Exit 1.
      - 401: the token is missing/expired/invalid. Exit 1.
    '''
    tracking_client = TrackingClient(Command.VERIFY, app=app_instance)

    token = get_oidc_token()
    if not token:
        msg = (f"OIDC authentication requires the {OIDC_TOKEN_KEY} environment variable to hold the "
               "pipeline's OIDC id-token. In Jenkins, bind an id-token credential to this variable; "
               "see the OIDC pipeline-authentication setup guide.")
        click.secho(msg, fg='red', err=True)
        tracking_client.send_error_event(
            event_name=Tracking.ErrorEvent.USER_ERROR,
            stack_trace=msg,
        )
        raise typer.Exit(2)

    # The endpoint is not workspace-scoped, so we bypass SmartTestsClient (which requires an
    # org/workspace) and call the low-level client directly. The OIDC token is supplied as the
    # bearer by authentication_headers().
    http_client = _HttpClient(app=app_instance)
    try:
        res = http_client.request("post", OIDC_VERIFY_PATH, payload={})
    except Exception as e:
        tracking_client.send_error_event(
            event_name=Tracking.ErrorEvent.INTERNAL_CLI_ERROR,
            stack_trace=str(e),
            api="oidc/verify",
        )
        click.secho(f"Could not reach the OIDC verification endpoint: {e}", fg='red', err=True)
        raise typer.Exit(1)

    if res.status_code == 401:
        msg = ("OIDC authentication failed: the presented token was rejected (invalid, expired, or "
               "from an unrecognized issuer).")
        click.secho(msg, fg='red', err=True)
        tracking_client.send_error_event(
            event_name=Tracking.ErrorEvent.USER_ERROR,
            stack_trace=msg,
        )
        raise typer.Exit(1)

    if res.status_code == 403:
        issuer = ""
        sub = ""
        try:
            body = res.json()
            issuer = body.get("issuer", "")
            sub = body.get("sub", "")
        except Exception:
            pass
        click.secho(
            "This pipeline's OIDC identity is not yet registered with Smart Tests.", fg='yellow', err=True)
        if issuer and sub:
            # Emit a copy/paste block the user pastes verbatim into the WebApp's
            # "Trusted OIDC subjects" registration form (Settings page). The keys match what the
            # WebApp parses: "issuer" and "normalized-sub".
            block = json.dumps({"issuer": issuer, "normalized-sub": sub}, indent=4)
            click.secho(
                "Please copy and paste the block below into your workspace settings "
                "(Trusted OIDC subjects) to authorize this pipeline:",
                fg='yellow', err=True)
            click.echo("########## start ##########", err=True)
            click.echo(block, err=True)
            click.echo("########## end ##########", err=True)
        tracking_client.send_error_event(
            event_name=Tracking.ErrorEvent.USER_ERROR,
            stack_trace=f"unregistered OIDC subject: {sub}",
        )
        raise typer.Exit(1)

    res.raise_for_status()

    data = res.json()
    org = data.get("organization")
    workspace = data.get("workspace")
    if not org or not workspace:
        msg = "OIDC verification returned an unexpected response (missing organization/workspace)."
        click.secho(msg, fg='red', err=True)
        tracking_client.send_error_event(
            event_name=Tracking.ErrorEvent.INTERNAL_SERVER_ERROR,
            stack_trace=msg,
            api="oidc/verify",
        )
        raise typer.Exit(1)

    # Emit eval-able export lines so the pipeline can hydrate its environment:
    #   eval "$(smart-tests verify --oidc)"
    # Subsequent commands then read org/workspace from these vars and present the same OIDC token
    # (kept in SMART_TESTS_OIDC_TOKEN) as their bearer.
    click.echo(f'export {ORGANIZATION_KEY}={_shell_quote(org)}')
    click.echo(f'export {WORKSPACE_KEY}={_shell_quote(workspace)}')
    click.echo(f'export {OIDC_TOKEN_KEY}={_shell_quote(token)}')
    click.secho(
        f"OIDC authentication verified for organization {org!r}, workspace {workspace!r}" + emoji(" \U0001f389"),
        fg='green', err=True)


def fetch_oidc_issuer(app_instance: Application):
    '''
    Helper for issuers Intake cannot reach (e.g. a private Jenkins), enabling manual verification.
    This runs INSIDE the private network — where the issuer's discovery endpoint IS reachable —
    reads the pipeline's OIDC id-token, extracts the `iss` claim, fetches that issuer's public JWKS
    via standard OIDC discovery, and prints an `{issuer, jwks}` copy/paste block.

    An admin then pastes that block into the WebApp (Settings → Trusted OIDC issuers) to register
    the issuer. This command deliberately does NOT register anything itself and never sends the JWKS
    to Intake: the verification key must never travel to the credential-free `verify` endpoint on the
    same channel as the token it verifies. Registration is an authenticated admin action; this is
    transport only.

    A JWKS contains only PUBLIC keys, so printing/pasting it exposes no secret.
    '''
    tracking_client = TrackingClient(Command.VERIFY, app=app_instance)

    token = get_oidc_token()
    if not token:
        msg = (f"--oidc-fetch-issuer requires the {OIDC_TOKEN_KEY} environment variable to hold the "
               "pipeline's OIDC id-token so its issuer can be discovered. In Jenkins, bind an "
               "id-token credential to this variable; see the OIDC pipeline-authentication setup guide.")
        click.secho(msg, fg='red', err=True)
        tracking_client.send_error_event(
            event_name=Tracking.ErrorEvent.USER_ERROR,
            stack_trace=msg,
        )
        raise typer.Exit(2)

    try:
        issuer = _issuer_from_jwt(token)
    except ValueError as e:
        msg = f"Could not read the issuer (iss) from {OIDC_TOKEN_KEY}: {e}"
        click.secho(msg, fg='red', err=True)
        tracking_client.send_error_event(
            event_name=Tracking.ErrorEvent.USER_ERROR,
            stack_trace=msg,
        )
        raise typer.Exit(2)

    click.secho(f"Discovering the JWKS for issuer {issuer!r} from inside this network...",
                fg='yellow', err=True)
    try:
        jwks = _fetch_issuer_jwks(issuer, app_instance)
    except Exception as e:
        msg = (f"Could not fetch the JWKS for {issuer!r}: {e}. "
               "Run this from a host that can reach the issuer's OIDC discovery endpoint.")
        click.secho(msg, fg='red', err=True)
        tracking_client.send_error_event(
            event_name=Tracking.ErrorEvent.INTERNAL_CLI_ERROR,
            stack_trace=str(e),
            api="oidc-discovery",
        )
        raise typer.Exit(1)

    # Emit the copy/paste block. Keys match what the WebApp's parseTrustedOidcIssuerBlock() expects:
    # "issuer" and "jwks" (jwks as a nested JSON object).
    block = json.dumps({"issuer": issuer, "jwks": jwks}, indent=4)
    click.secho(
        "Copy the block below and paste it into the WebApp (Settings -> Trusted OIDC issuers). "
        "NOTE: a registered issuer is a platform-wide trust anchor, so this must be done by an "
        "organization admin who trusts this issuer's keys:",
        fg='yellow', err=True)
    click.echo("########## start ##########")
    click.echo(block)
    click.echo("########## end ##########")


def _issuer_from_jwt(token: str) -> str:
    '''
    Extract the `iss` claim from an unverified JWT. We do NOT verify the signature here — this is a
    local convenience to learn which issuer's JWKS to fetch; the resulting JWKS is what Intake later
    uses to verify tokens for real.
    '''
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("not a well-formed JWT (expected three dot-separated segments)")
    try:
        payload_raw = base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4))
        payload = json.loads(payload_raw)
    except (binascii.Error, ValueError) as e:
        raise ValueError(f"could not decode the JWT payload: {e}") from e
    issuer = payload.get("iss")
    if not issuer or not isinstance(issuer, str):
        raise ValueError("the token has no 'iss' claim")
    return issuer


def _fetch_issuer_jwks(issuer: str, app_instance: Application) -> dict:
    '''
    Standard OIDC discovery, mirroring the backend's HttpJwksUriDiscovery:
    GET {iss}/.well-known/openid-configuration -> jwks_uri -> GET jwks_uri.
    Returns the parsed JWKS document (a dict with a non-empty "keys" list).

    Talks to the issuer's OWN host (absolute URLs), not the Smart Tests base URL, so we use
    `requests` directly rather than _HttpClient. Public discovery/JWKS endpoints need no auth.
    Honors --skip-cert-verification and the standard HTTPS_PROXY environment variable.
    '''
    verify_tls = not app_instance.skip_cert_verification

    config_url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    res = requests.get(config_url, timeout=DEFAULT_GET_TIMEOUT, verify=verify_tls)
    res.raise_for_status()
    jwks_uri = res.json().get("jwks_uri")
    if not jwks_uri or not isinstance(jwks_uri, str):
        raise ValueError("the issuer's discovery document has no 'jwks_uri'")

    # SSRF guard: manual mode runs inside the private network with no backend PrivateNetworkGuard,
    # so a tampered discovery document could point jwks_uri at an arbitrary internal host (cloud
    # metadata, another internal service). A self-hosted issuer (e.g. Jenkins) always advertises a
    # same-origin jwks_uri, so require it to live on the issuer's own host/scheme rather than
    # following wherever the (unverified) document points.
    if not _same_origin(issuer, jwks_uri):
        raise ValueError(
            f"the discovery document's jwks_uri {jwks_uri!r} is not on the issuer's origin "
            f"{issuer!r}; refusing to fetch keys from a different host")

    res = requests.get(jwks_uri, timeout=DEFAULT_GET_TIMEOUT, verify=verify_tls)
    res.raise_for_status()
    jwks = res.json()
    keys = jwks.get("keys") if isinstance(jwks, dict) else None
    if not keys:
        raise ValueError("the fetched JWKS has no keys")
    return jwks


def _same_origin(a: str, b: str) -> bool:
    '''
    True iff URLs `a` and `b` share the same (scheme, host, port) origin. Used to require an
    issuer's advertised jwks_uri to live on the issuer's own host — a self-hosted OIDC provider
    always does, and it prevents a tampered discovery document from redirecting the JWKS fetch to
    an arbitrary host. Comparison is case-insensitive on scheme/host and normalizes the default
    port for http/https.
    '''
    def origin(url: str):
        p = urllib.parse.urlsplit(url)
        scheme = p.scheme.lower()
        host = (p.hostname or "").lower()
        default_port = {"http": 80, "https": 443}.get(scheme)
        port = p.port if p.port is not None else default_port
        return (scheme, host, port)

    return origin(a) == origin(b)


def _shell_quote(value: str) -> str:
    """Single-quote a value for safe use in a POSIX `export VAR=...` line."""
    return "'" + value.replace("'", "'\\''") + "'"
