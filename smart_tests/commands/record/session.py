import os
import re
import sys
from http import HTTPStatus
from typing import Annotated, List

import click

import smart_tests.args4p.typer as typer
from smart_tests import args4p
from smart_tests.app import Application
from smart_tests.utils.commands import Command
from smart_tests.utils.exceptions import print_error_and_die
from smart_tests.utils.fail_fast_mode import set_fail_fast_mode
from smart_tests.utils.link import capture_links
from smart_tests.utils.no_build import NO_BUILD_BUILD_NAME
from smart_tests.utils.smart_tests_client import SmartTestsClient
from smart_tests.utils.tracking import Tracking, TrackingClient
from smart_tests.utils.typer_types import KeyValue, parse_key_value, validate_datetime_with_tz

TEST_SESSION_NAME_RULE = re.compile("^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")


@args4p.command(help="Record session information")
def session(
    app: Application,
    build_name: Annotated[str | None, typer.Option(
        "--build",
        help="Build name",
        metavar="NAME",
    )] = None,
    test_suite: Annotated[str, typer.Option(
        "--test-suite",
        help="Set test suite name. A test suite is a collection of test sessions. Setting a test suite allows you to "
             "manage data over test sessions and lineages.",
        metavar="NAME",
        required=True
    )] = "",
    flavors: Annotated[List[KeyValue], typer.Option(
        "--flavor",
        help="Flavors",
        multiple=True,
        metavar="KEY=VALUE",
        type=parse_key_value
    )] = [],
    is_observation: Annotated[bool, typer.Option(
        "--observation",
        help="Enable observation mode"
    )] = False,
    links: Annotated[List[KeyValue], typer.Option(
        "--link",
        help="Set external link of title and url",
        metavar="TITLE=URL",
        multiple=True,
        type=parse_key_value,
    )] = [],
    is_no_build: Annotated[bool, typer.Option(
        "--no-build",
        help="If you want to only send test reports, please use this option"
    )] = False,
    timestamp: Annotated[str | None, typer.Option(
        help="Used to overwrite the session time when importing historical data. Note: Format must be "
             "`YYYY-MM-DDThh:mm:ssTZD` or `YYYY-MM-DDThh:mm:ss` (local timezone applied)",
        metavar="TIMESTAMP"
    )] = None,
):

    # Validate and convert timestamp if provided
    parsed_timestamp = None
    if timestamp:
        parsed_timestamp = validate_datetime_with_tz(timestamp)

    tracking_client = TrackingClient(Command.RECORD_SESSION, app=app)
    client = SmartTestsClient(app=app, tracking_client=tracking_client)
    set_fail_fast_mode(client.is_fail_fast_mode())

    if not is_no_build and not build_name:
        print_error_and_die("Missing option '--build'", tracking_client, Tracking.ErrorEvent.USER_ERROR)

    if is_no_build and build_name:
        print_error_and_die("Cannot use --build option with --no-build option", tracking_client, Tracking.ErrorEvent.USER_ERROR)

    if is_no_build:
        build_name = NO_BUILD_BUILD_NAME

    try:
        payload = {
            "flavors": dict([(f.key, f.value) for f in flavors]),
            "isObservation": is_observation,
            "noBuild": is_no_build,
            "testSuite": test_suite,
            "timestamp": parsed_timestamp.isoformat() if parsed_timestamp else None,
            "links": capture_links(link_options=links, env=os.environ)
        }

        sub_path = f"builds/{build_name}/test_sessions"
        res = client.request("post", sub_path, payload=payload)

        if res.status_code == HTTPStatus.NOT_FOUND:
            msg = f"Build {build_name} was not found. " \
                f"Make sure to run `smart-tests record build --build {build_name}` before you run this command."
            tracking_client.send_error_event(
                event_name=Tracking.ErrorEvent.INTERNAL_CLI_ERROR,
                stack_trace=msg,
            )
            click.secho(msg, fg='yellow', err=True)
            sys.exit(1)

        res.raise_for_status()

        session_id = res.json().get('id', None)
        if is_no_build:
            build_name = res.json().get("buildNumber", "")
            sub_path = f"builds/{build_name}/test_sessions"
            assert build_name is not None

        click.echo(f"{sub_path}/{session_id}", nl=False)

    except Exception as e:
        tracking_client.send_error_event(
            event_name=Tracking.ErrorEvent.INTERNAL_CLI_ERROR,
            stack_trace=str(e),
        )
        client.print_exception_and_recover(e)
