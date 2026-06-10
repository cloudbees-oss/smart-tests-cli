import json
import sys
from enum import Enum
from http import HTTPStatus
from typing import Annotated

import click

import smart_tests.args4p.typer as typer
from smart_tests.args4p.converters import intType
from smart_tests.args4p.exceptions import BadCmdLineException

from ... import args4p
from ...app import Application
from ...utils.smart_tests_client import SmartTestsClient
from ...utils.typer_types import DateTimeWithTimezone, parse_datetime_with_timezone


class TestStatus(str, Enum):
    """Test execution status"""
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    SKIP = "SKIP"
    FLAKE = "FLAKE"

    @staticmethod
    def from_str(value: str) -> "TestStatus":
        """Parse status from string"""
        for member in TestStatus:
            if member.value.lower() == value.lower():
                return member
        raise BadCmdLineException(
            f"Invalid status: '{value}'. Valid values: SUCCESS, FAILURE, SKIP, FLAKE"
        )


@args4p.command(help="View detailed test execution results")
def test_results(
    app: Application,
    test_path: Annotated[str, typer.Option(
        "--test-path",
        help="Test path to query results for (required)",
        metavar="PATH",
        required=True
    )],
    status: Annotated[TestStatus | None, typer.Option(
        "--status",
        help="Filter by test status (SUCCESS, FAILURE, SKIP, FLAKE)",
        type=TestStatus.from_str,
        metavar="STATUS"
    )] = None,
    branch: Annotated[str | None, typer.Option(
        "--branch",
        help="Filter by branch/lineage (exact match)",
        metavar="BRANCH"
    )] = None,
    test_suite: Annotated[str | None, typer.Option(
        "--test-suite",
        help="Filter by test suite name (e.g., 'unit-tests')",
        metavar="NAME"
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
    limit: Annotated[int | None, typer.Option(
        "--limit",
        help="Max results to return (default: 50, max: 500)",
        type=intType(min=1, max=500),
        metavar="N"
    )] = None,
    offset: Annotated[int | None, typer.Option(
        "--offset",
        help="Pagination offset (default: 0)",
        type=intType(min=0),
        metavar="N"
    )] = None,
    logs: Annotated[bool, typer.Option(
        "--logs",
        help="Include full stdout/stderr from failed test case executions"
    )] = False,
):
    """View detailed test execution results with filters"""
    client = SmartTestsClient(app=app)

    # Build query parameters
    params = {
        "test-path": test_path
    }
    if status:
        params["status"] = status.value
    if branch:
        params["branch"] = branch
    if test_suite:
        params["test-suite"] = test_suite
    if from_date:
        params["from"] = from_date.datetime().strftime("%Y-%m-%d")
    if to_date:
        params["to"] = to_date.datetime().strftime("%Y-%m-%d")
    if logs:
        params["include-logs"] = "true"
    if limit:
        params["limit"] = str(limit)
    if offset:
        params["offset"] = str(offset)

    try:
        res = client.request("get", "view/test-results", params=params)

        if res.status_code == HTTPStatus.NOT_FOUND:
            click.secho(
                "No test results found. Check your filters and try again.",
                fg='yellow', err=True
            )
            sys.exit(1)

        res.raise_for_status()
        response_json = res.json()

        # Output JSON format
        click.echo(json.dumps(response_json, indent=2))

    except Exception as e:
        client.print_exception_and_recover(
            e,
            "Warning: failed to retrieve test results from server"
        )
        sys.exit(1)
