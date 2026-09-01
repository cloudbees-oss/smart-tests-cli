import json
import os
import sys
from http import HTTPStatus
from typing import Annotated

import click
from requests import Response
from tabulate import tabulate

from smart_tests.utils.tracking import TrackingClient

from .. import args4p
from ..app import Application
from ..args4p import typer
from ..testpath import unparse_test_path
from ..utils.commands import Command
from ..utils.session import SessionId
from ..utils.smart_tests_client import SmartTestsClient


@args4p.command()
def gate(app_instance: Application,
         session: Annotated[SessionId, SessionId.as_option()],
         is_json_format: Annotated[bool, typer.Option(
             "--json",
             help="display JSON format")] = False):
    tracking_client = TrackingClient(Command.GATE, app=app_instance)
    client = SmartTestsClient(tracking_client=tracking_client, app=app_instance)
    try:
        res: Response = client.request("get", "gate", params={"session-id": session.test_part})

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


def _escape_github_actions_command_value(value: str) -> str:
    return value.replace('\r', '%0D').replace('\n', '%0A')


def _escape_github_actions_log_line(line: str) -> str:
    return line.replace('::', '%3A%3A', 1) if line.startswith('::') else line


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
            test_path = unparse_test_path(test.get("testPath", []))
            stderr = (test.get("stderr") or "").strip()
            if is_github_actions:
                safe_test_path = _escape_github_actions_command_value(test_path)
                click.echo("::group::{}. {}".format(i, safe_test_path))
                if stderr:
                    for line in stderr.splitlines():
                        click.echo(_escape_github_actions_log_line(line))
                click.echo("::endgroup::")
            else:
                click.echo("{}. {}".format(i, test_path))
                if stderr:
                    for line in stderr.splitlines():
                        click.echo("   {}".format(line))
                click.echo("")
