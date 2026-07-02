import os
from typing import Tuple

import click
import requests

import smart_tests.args4p.typer as typer

from .env_keys import OIDC_TOKEN_KEY, ORGANIZATION_KEY, WORKSPACE_KEY, get_token


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

    if os.getenv('EXPERIMENTAL_GITHUB_OIDC_TOKEN_AUTH'):
        req_url = os.getenv('ACTIONS_ID_TOKEN_REQUEST_URL')
        rt_token = os.getenv('ACTIONS_ID_TOKEN_REQUEST_TOKEN')
        if not req_url or not rt_token:
            click.secho(
                "GitHub Actions OIDC tokens cannot be retrieved."
                "Confirm that you have added necessary permissions following "
                "https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-cloud-providers#adding-permissions-settings",  # noqa: E501
                fg='red', err=True)
            raise typer.Exit(1)
        r = requests.get(req_url,
                         headers={
                             'Authorization': f'Bearer {rt_token}',
                             'Accept': 'application/json; api-version=2.0',
                             'Content-Type': 'application/json',
                         })
        r.raise_for_status()
        return {"Authorization": f"Bearer {r.json()['value']}"}

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
