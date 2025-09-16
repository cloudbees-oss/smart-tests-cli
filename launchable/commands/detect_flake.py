import os
import sys

import click

from launchable.app import Application
from launchable.commands.helper import find_or_create_session
from launchable.commands.test_path_writer import TestPathWriter
from launchable.utils.click import ignorable_error
from launchable.utils.env_keys import REPORT_ERROR_KEY
from launchable.utils.launchable_client import LaunchableClient
from launchable.utils.tracking import Tracking, TrackingClient

from ..utils.commands import Command


@click.group(help="Early flake detection")
@click.option(
    '--session',
    'session',
    help='In the format builds/<build-name>/test_sessions/<test-session-id>',
    type=str,
    required=True
)
@click.option(
    '--retry-threshold',
    'retry_threshold',
    help='Throughness of how "flake" is detected',
    type=click.Choice(['low', 'medium', 'high'], case_sensitive=False),
    default='medium',
    required=True,
)
@click.pass_context
def detect_flake(ctx, retry_threshold, session):
    tracking_client = TrackingClient(Command.DETECT_FLAKE, app=ctx.obj)
    client = LaunchableClient(app=ctx.obj, tracking_client=tracking_client, test_runner=ctx.invoked_subcommand)
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

    class FlakeDetection(TestPathWriter):
        def __init__(self, app: Application):
            super(FlakeDetection, self).__init__(app=app)

        def run(self):
            test_paths = []
            try:
                res = client.request(
                    "get",
                    "detect-flake",
                    params={
                        "confidence": retry_threshold.upper(),
                        "session-id": os.path.basename(session_id),
                        "test-runner": ctx.invoked_subcommand})
                res.raise_for_status()
                test_paths = res.json().get("testPaths", [])
                if test_paths:
                    self.print(test_paths)
            except Exception as e:
                tracking_client.send_error_event(
                    event_name=Tracking.ErrorEvent.INTERNAL_CLI_ERROR,
                    stack_trace=str(e),
                )
                if os.getenv(REPORT_ERROR_KEY):
                    raise e
                else:
                    click.echo(ignorable_error(e), err=True)

    ctx.obj = FlakeDetection(app=ctx.obj)
