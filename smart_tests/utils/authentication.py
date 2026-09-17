import os
from typing import Optional, Tuple
from urllib.parse import quote

import click
import requests

import smart_tests.args4p.typer as typer

from .env_keys import (GITHUB_OIDC_KEY, LEGACY_GITHUB_OIDC_KEY, OIDC_AUDIENCE_KEY,
                       OIDC_TOKEN_KEY, ORGANIZATION_KEY, WORKSPACE_KEY, get_token)

# Default audience Intake expects in an OIDC id-token (launchableinc.intake.oidc.audience).
DEFAULT_OIDC_AUDIENCE = "https://app.cloudbees.io/smart-tests"
# Header the CLI sends to opt into Intake's deprecated GitHub Actions OIDC path. Absent it, a
# GitHub-issued token is verified through the generic OIDC path. Mirrors RESTAuthConverter.
LEGACY_GITHUB_OIDC_HEADER = "GitHub-OIDC-Legacy"

# authentication_headers() runs on every API request, so guard the legacy deprecation notice to
# print at most once per process instead of once per request.
_legacy_oidc_warning_shown = False


def get_org_workspace():
    '''
    Returns (org,ws) tuple from LAUNCHABLE_TOKEN, or (None,None) if not found.
    Use ensure_org_workspace() if this is supposed to be an error condition
    '''
    token = get_token()
    if token:
        try:
            _, user, _ = token.split(":", 2)
            org, workspace = user.split("/", 1)
            return org, workspace
        except ValueError:
            click.secho("Invalid value in LAUNCHABLE_TOKEN environment variable.", fg="red")
            raise typer.Exit(1)

    return os.getenv(ORGANIZATION_KEY), os.getenv(WORKSPACE_KEY)


def ensure_org_workspace() -> Tuple[str, str]:
    org, workspace = get_org_workspace()
    if org is None or workspace is None:
        click.secho(
            "Could not identify Smart Tests organization/workspace. "
            "Please confirm if you set SMART_TESTS_TOKEN "
            "(or LAUNCHABLE_TOKEN for backward compatibility) or SMART_TESTS_ORGANIZATION and "
            "SMART_TESTS_WORKSPACE environment variables", fg='red', err=True)
        raise typer.Exit(1)
    return org, workspace


def get_oidc_token():
    '''
    Returns the CI-issued OIDC id-token (e.g. a Jenkins-minted RS256 JWT) from the environment,
    or None if not set. This is the same token `smart-tests verify --oidc` exchanges for an
    org/workspace, and the one subsequent workspace-scoped calls present as their bearer.
    '''
    return os.getenv(OIDC_TOKEN_KEY)


def authentication_headers():
    token = get_token()
    if token:
        return {'Authorization': f'Bearer {token}'}

    # A pipeline that authenticated via `verify --oidc` carries no SMART_TESTS_TOKEN; it presents
    # its OIDC id-token directly. Intake routes this by `iss` (RESTAuthVerifier) to the generic OIDC
    # verifier, so subsequent workspace-scoped calls authenticate with the same JWT.
    oidc_token = get_oidc_token()
    if oidc_token:
        return {'Authorization': f'Bearer {oidc_token}'}

    # Generic GitHub Actions OIDC: fetch the id-token minted for the Smart Tests audience and present
    # it like any other OIDC token. Intake routes by `iss` to the generic verifier and matches the
    # normalized `repo:OWNER/REPO` subject against trusted_oidc_subjects. The audience is required
    # here because the generic path enforces `aud` for GitHub's issuer.
    if os.getenv(GITHUB_OIDC_KEY):
        id_token = _fetch_github_id_token(audience=_expected_oidc_audience())
        return {'Authorization': f'Bearer {id_token}'}

    # Deprecated legacy GitHub Actions OIDC: Intake matches the `repository` claim against
    # trusted_github_repositories. The legacy path never checks `aud`, so no audience is requested.
    # The header tells Intake to take the legacy branch; without it the token would be verified
    # through the generic path.
    if os.getenv(LEGACY_GITHUB_OIDC_KEY):
        global _legacy_oidc_warning_shown
        if not _legacy_oidc_warning_shown:
            _legacy_oidc_warning_shown = True
            click.secho(
                f"{LEGACY_GITHUB_OIDC_KEY} enables the deprecated GitHub Actions OIDC flow. Migrate "
                f"by registering your repository as a Trusted OIDC subject and switching to "
                f"{GITHUB_OIDC_KEY}=1. See "
                "https://docs.cloudbees.com/docs/cloudbees-smart-tests/latest/send-data-to-smart-tests/set-up-smart-tests/migration-to-github-oidc-auth",  # noqa: E501
                fg='yellow', err=True)
        id_token = _fetch_github_id_token()
        return {
            'Authorization': f'Bearer {id_token}',
            LEGACY_GITHUB_OIDC_HEADER: '1',
        }

    if os.getenv('GITHUB_ACTIONS'):
        headers = {
            'GitHub-Actions': os.environ['GITHUB_ACTIONS'],
            'GitHub-Run-Id': os.environ['GITHUB_RUN_ID'],
            'GitHub-Repository': os.environ['GITHUB_REPOSITORY'],
            'GitHub-Workflow': os.environ['GITHUB_WORKFLOW'],
            'GitHub-Run-Number': os.environ['GITHUB_RUN_NUMBER'],
            'GitHub-Event-Name': os.environ['GITHUB_EVENT_NAME'],
            'GitHub-Sha': os.environ['GITHUB_SHA'],
        }

        # GITHUB_PR_HEAD_SHA might not exist
        pr_head_sha = os.getenv('GITHUB_PR_HEAD_SHA')
        if pr_head_sha:
            headers['GitHub-Pr-Head-Sha'] = pr_head_sha

        return headers
    return {}


def _expected_oidc_audience() -> str:
    '''Audience the GitHub id-token must carry for Intake's generic OIDC path to accept it.'''
    return os.getenv(OIDC_AUDIENCE_KEY) or DEFAULT_OIDC_AUDIENCE


def _fetch_github_id_token(audience: Optional[str] = None) -> str:
    '''
    Retrieve a GitHub Actions OIDC id-token via the runner's token endpoint.

    Requires the `id-token: write` workflow permission, which populates ACTIONS_ID_TOKEN_REQUEST_URL
    and ACTIONS_ID_TOKEN_REQUEST_TOKEN. When `audience` is given it is requested so the token's `aud`
    claim matches what Intake expects (the generic OIDC path enforces it); the legacy path omits it.
    '''
    req_url = os.getenv('ACTIONS_ID_TOKEN_REQUEST_URL')
    rt_token = os.getenv('ACTIONS_ID_TOKEN_REQUEST_TOKEN')
    if not req_url or not rt_token:
        click.secho(
            "GitHub Actions OIDC tokens cannot be retrieved."
            "Confirm that you have added necessary permissions following "
            "https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-cloud-providers#adding-permissions-settings",  # noqa: E501
            fg='red', err=True)
        raise typer.Exit(1)
    if audience:
        sep = '&' if '?' in req_url else '?'
        req_url = f"{req_url}{sep}audience={quote(audience, safe='')}"
    r = requests.get(req_url,
                     headers={
                         'Authorization': f'Bearer {rt_token}',
                         'Accept': 'application/json; api-version=2.0',
                         'Content-Type': 'application/json',
                     })
    r.raise_for_status()
    return r.json()['value']
