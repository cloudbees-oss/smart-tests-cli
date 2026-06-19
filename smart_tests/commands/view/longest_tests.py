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
from ...utils.typer_types import DateTimeWithTimezone, parse_datetime_with_timezone, validate_iso_week


@args4p.command(help="View longest running test data with weekly scores")
def longest_tests(
    app: Application,
    year_week: Annotated[str | None, typer.Option(
        "--year-week",
        help="Specific ISO week for longest running tests (e.g., '2026-W15')",
        type=validate_iso_week,
        metavar="YYYY-Www"
    )] = None,
    weeks: Annotated[int | None, typer.Option(
        "--weeks",
        help="Number of weeks to retrieve (default: 1, max: 12)",
        type=intType(min=1, max=12),
        metavar="N"
    )] = None,
    from_date: Annotated[DateTimeWithTimezone | None, typer.Option(
        "--from",
        help="Start date/time (ISO 8601 format, e.g., '2026-04-08' or '2026-04-08T00:00:00Z')",
        type=parse_datetime_with_timezone,
        metavar="DATE"
    )] = None,
    to_date: Annotated[DateTimeWithTimezone | None, typer.Option(
        "--to",
        help="End date/time (ISO 8601 format, e.g., '2026-04-14' or '2026-04-14T23:59:59Z')",
        type=parse_datetime_with_timezone,
        metavar="DATE"
    )] = None,
    test_path: Annotated[str | None, typer.Option(
        "--test-path",
        help="Test path filter (full path string, e.g., 'class=MyTest')",
        metavar="NAME"
    )] = None,
    limit: Annotated[int | None, typer.Option(
        "--limit",
        help="Max results to return per week (default: 50, max: 500)",
        type=intType(min=1, max=500),
        metavar="N"
    )] = None,
):
    """View longest running tests with weekly trends"""
    client = SmartTestsClient(app=app)

    params = {}
    if year_week:
        params["year-week"] = year_week
    if weeks:
        params["weeks"] = str(weeks)
    if from_date:
        params["from"] = from_date.datetime().strftime("%Y-%m-%d")
    if to_date:
        params["to"] = to_date.datetime().strftime("%Y-%m-%d")
    if test_path:
        params["test-path"] = test_path
    if limit:
        params["limit"] = str(limit)

    try:
        res = client.request("get", "view/longest-tests", params=params)

        if res.status_code == HTTPStatus.NOT_FOUND:
            click.secho(
                "No longest running test data found. Check your filters and try again.",
                fg='yellow', err=True
            )
            sys.exit(1)

        res.raise_for_status()
        response_json = res.json()

        click.echo(json.dumps(response_json, indent=2))

    except Exception as e:
        client.print_exception_and_recover(
            e,
            "Warning: failed to retrieve longest running tests from server"
        )
        sys.exit(1)
