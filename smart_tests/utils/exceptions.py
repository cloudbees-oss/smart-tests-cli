# TODO: add cli-specific custom exceptions
import sys
from typing import NoReturn

import click

from smart_tests.utils.tracking import Tracking, TrackingClient


class ParseSessionException(Exception):
    def __init__(
        self,
        session: str,
        message: str = "Wrong session format; session format is like 'builds/<build name>/test_sessions/<test session id>'.",
    ):
        self.session = session
        self.message = f"{message}: {self.session}"
        super().__init__(self.message)


class InvalidJUnitXMLException(Exception):
    def __init__(
        self,
        filename: str,
        message: str = "Invalid JUnit XML file format",
    ):
        self.filename = filename
        self.message = f"{message}: {filename}"
        super().__init__(self.message)


def print_error_and_die(msg: str, tracking_client: TrackingClient, event: Tracking.ErrorEvent) -> NoReturn:
    click.secho(msg, fg='red', err=True)
    tracking_client.send_error_event(event_name=event, stack_trace=msg)
    sys.exit(1)
