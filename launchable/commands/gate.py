import json
import os
import sys
from http import HTTPStatus

import click
from requests import Response
from tabulate import tabulate

from launchable.commands.helper import find_or_create_session
from launchable.utils.click import ignorable_error
from launchable.utils.env_keys import REPORT_ERROR_KEY
from launchable.utils.tracking import Tracking, TrackingClient

from ..utils.commands import Command
from ..utils.launchable_client import LaunchableClient


@click.command()
@click.option(
    '--session',
    'session',
    help='In the format builds/<build-name>/test_sessions/<test-session-id>',
    type=str,
    required=True
)
@click.option(
    '--json',
    'is_json_format',
    help='display JSON format',
    is_flag=True
)
@click.pass_context
def gate(ctx: click.core.Context, session: str, is_json_format: bool):
    tracking_client = TrackingClient(Command.GATE, app=ctx.obj)
    client = LaunchableClient(app=ctx.obj)
    session_id = None
    try:
        session_id = find_or_create_session(
            context=ctx,
            session=session,
            build_name=None,
            tracking_client=tracking_client
        )
    except click.UsageError as e:
        click.echo(click.style(str(e), fg="red"), err=True)
        sys.exit(1)
    except Exception as e:
        tracking_client.send_error_event(
            event_name=Tracking.ErrorEvent.INTERNAL_CLI_ERROR,
            stack_trace=str(e),
        )
        if os.getenv(REPORT_ERROR_KEY):
            raise e
        else:
            click.echo(ignorable_error(e), err=True)
    if session_id is None:
        return
    try:
        res: Response = client.request("get", "gate", params={"session-id": os.path.basename(session_id)})

        if res.status_code == HTTPStatus.NOT_FOUND:
            click.echo(click.style(
                "Gate data currently not available for this workspace.", 'yellow'), err=True)
            sys.exit()

        res.raise_for_status()

        res_json = res.json()

        if is_json_format:
            display_as_json(res)
        else:
            display_as_table(res)

        # Exit with failure status if gate failed
        if res_json.get('status') == 'FAILED':
            sys.exit(1)

    except Exception as e:
        client.print_exception_and_recover(e, "Warning: failed to fetch gate status")


def display_as_json(res: Response):
    res_json = res.json()
    click.echo(json.dumps(res_json, indent=2))


def display_as_table(res: Response):
    headers = ["Status", "Quarantined (Ignored)", "Actionable Failures"]
    res_json = res.json()

    status_icon = "PASSED" if res_json.get('status') == 'PASSED' else "FAILED"

    rows = [[
        status_icon,
        res_json.get('quarantinedFailures', 0),
        res_json.get('actionableFailures', 0)
    ]]

    click.echo(tabulate(rows, headers, tablefmt="github"))

    failed_tests = res_json.get('actionableFailedTests', [])
    is_github_actions = os.getenv('GITHUB_ACTIONS')
    if failed_tests:
        click.echo("\nActionable Failure Details:\n")
        for i, test in enumerate(failed_tests, 1):
            test_path = "#".join([
                p["type"] + "=" + p["name"]
                for p in test.get("testPath", [])
                if {"type", "name"} <= p.keys()
            ])
            stderr = (test.get("stderr") or "").strip()
            if is_github_actions:
                click.echo("::group::{}. {}".format(i, test_path))
                if stderr:
                    for line in stderr.splitlines():
                        click.echo(line)
                click.echo("::endgroup::")
            else:
                click.echo("{}. {}".format(i, test_path))
                if stderr:
                    for line in stderr.splitlines():
                        click.echo("   {}".format(line))
                click.echo("")
