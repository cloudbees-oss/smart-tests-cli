import json
import os
import platform
import re
import subprocess
from typing import Annotated, List

import click

import smart_tests.args4p.typer as typer
from smart_tests.utils.tracking import Tracking, TrackingClient

from .. import args4p
from ..app import Application
from ..utils.authentication import ensure_org_workspace, get_oidc_token, get_org_workspace
from ..utils.commands import Command
from ..utils.env_keys import OIDC_TOKEN_KEY, ORGANIZATION_KEY, TOKEN_KEY, WORKSPACE_KEY
from ..utils.http_client import _HttpClient
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
             "instead of an API key, and resolve the org/workspace it is registered to.")] = False,
):
    # Run the verification (no subcommands in this app)
    # In this command, regardless of REPORT_ERROR_KEY, always report an unexpected error with full stack trace
    # to assist troubleshooting. `typer.BadParameter` is handled by the invoking
    # Click gracefully.

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


def _shell_quote(value: str) -> str:
    """Single-quote a value for safe use in a POSIX `export VAR=...` line."""
    return "'" + value.replace("'", "'\\''") + "'"
