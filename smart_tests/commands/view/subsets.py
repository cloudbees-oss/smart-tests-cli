import json
import sys
from http import HTTPStatus
from typing import Annotated

import click

import smart_tests.args4p.typer as typer
from smart_tests.args4p.converters import intType

from ... import args4p
from ...app import Application
from ...utils.smart_tests_client import SmartTestsClient


@args4p.command(help="View subsets requested in a test session")
def subsets(
    app: Application,
    test_session_id: Annotated[int, typer.Option(
        "--test-session-id",
        help="Test session ID to list subsets for (required)",
        type=intType(min=1),
        metavar="ID",
        required=True
    )],
):
    """View subsets requested in a test session, in the order they were requested"""
    client = SmartTestsClient(app=app)

    try:
        res = client.request("get", "view/subsets", params={"test-session-id": str(test_session_id)})

        if res.status_code == HTTPStatus.NOT_FOUND:
            click.secho(
                f"Test session {test_session_id} not found. Check the test session ID and try again.",
                fg='yellow', err=True
            )
            sys.exit(1)

        res.raise_for_status()
        response_json = res.json()

        click.echo(json.dumps(response_json, indent=2))

    except Exception as e:
        client.print_exception_and_recover(
            e,
            "Warning: failed to retrieve subsets from server"
        )
        sys.exit(1)
