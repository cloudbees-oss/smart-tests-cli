import glob
import os
from io import BytesIO
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional, Tuple

import click
from tabulate import tabulate

import smart_tests.args4p.typer as typer
from smart_tests.utils.session import SessionId, get_session

from ... import args4p
from ...app import Application
from ...args4p.converters import path
from ...utils.smart_tests_client import SmartTestsClient


class CoverageStatus:
    SUCCESS = "✓ Recorded successfully"
    FAILED = "⚠ Failed to record"


@args4p.command(help="Record coverage data (LCOV format) related to a test session. "
                "Passing COVERAGE_FILES is optional for bazel; "
                "files are auto discovered when the command is run inside project root. "
                "Other test runners must pass their coverage report file(s) directly. "
                "Additionally use --testmap to upload your own source-to-test mapping rules (testmap-v1 JSON), "
                "useful for source files that coverage cannot attribute to tests (for example, code "
                "exercised by end-to-end tests where coverage instrumentation is not possible).")
def coverage(
    app: Application,
    session: Annotated[SessionId, SessionId.as_option()],
    coverage_files: Annotated[List[str], typer.Argument(
        multiple=True,
        required=False,
        help="Coverage report files to upload (LCOV format)"
    )] = [],
    testmap: Annotated[Path | None, typer.Option(
        "--testmap",
        type=path(exists=True, dir_okay=False),
        help="JSON file (format: testmap-v1), mapping source file globs to the tests relevant to them. "
             "Useful for source files that coverage cannot attribute to tests (for example, code "
             "exercised by end-to-end tests where coverage instrumentation is not possible). Coverage "
             "reports are still uploaded alongside it; when there are none to find, only the testmap "
             "is uploaded.",
        metavar="FILE"
    )] = None,
):
    client = SmartTestsClient(app=app)
    sources: List[str] = []
    coverage_expected = bool(coverage_files) or testmap is None
    status: Optional[str] = None
    files_recorded: Optional[int] = None
    is_reupload = False
    testmap_status: Optional[str] = None
    testmap_summary: Dict[str, Any] = {}

    try:
        # Assert test session exists
        get_session(session, client)
        testmap_content = _read(testmap) if testmap is not None else None

        blocks: List[bytes] = []
        if coverage_files:
            sources = list(coverage_files)
            blocks = [_read(f) for f in sources]
        else:
            # No files given: auto-discover from the current directory.
            # Auto discovery is Bazel only for now.
            try:
                sources, blocks = discover_bazel_coverage(Path("."))
            except click.UsageError:
                if testmap_content is None:
                    raise
                click.echo("No coverage report found; uploading the testmap only.", err=True)

        if blocks:
            # LCOV tracefiles are just a sequence of SF:...end_of_record blocks, so concatenating
            # multiple files is itself a valid tracefile. Send them as one upload rather than one
            # request per file. The server already unions repeated SF: blocks for the same file
            # within one upload, so this is correct even when the inputs cover overlapping files
            # (e.g. one report from a unit-test run, another from an integration-test run touching
            # the same source file)
            content = b"\n".join(blocks)
            status, files_recorded, is_reupload = post_coverage(client, session, content)

        if testmap_content is not None:
            testmap_status, testmap_summary = post_testmap(client, session, testmap_content)
    except Exception as e:
        client.print_exception_and_recover(e)
        if coverage_expected and status is None:
            status = CoverageStatus.FAILED
        if testmap is not None and testmap_status is None:
            testmap_status = CoverageStatus.FAILED

    if status is not None:
        display_summary(sources, status, files_recorded, is_reupload)
    if testmap is not None:
        display_testmap_summary(str(testmap), testmap_status or CoverageStatus.FAILED, testmap_summary)


def discover_bazel_coverage(workspace: "str | Path") -> Tuple[List[str], List[bytes]]:
    """
    Finds every per-target coverage.dat under <workspace>/bazel-testlogs

    Bazel's own coverage.dat carries no target identity on its own, though TN (Test Name) is a standard LCOV field.
    So we derive TN by file path (same approach used by `record tests bazel`
    (bazel-testlogs/<pkg>/<target>/coverage.dat -> TN://<pkg>:<target>).
    """
    base = Path(workspace).joinpath('bazel-testlogs')
    if not base.exists():
        raise click.UsageError(
            "No such directory: %s. "
            "Pass coverage report file(s) directly as arguments instead." % str(base))

    sources: List[str] = []
    blocks: List[bytes] = []
    for report_file in sorted(glob.iglob(os.path.join(str(base), '**', 'coverage.dat'), recursive=True)):
        pkg_and_target = report_file[len(str(base)) + 1:-len("/coverage.dat")]
        package, target = os.path.dirname(pkg_and_target), os.path.basename(pkg_and_target)
        label = "//{}:{}".format(package.replace(os.sep, '/'), target)
        sources.append(report_file)
        blocks.append(_tag_with_test_name(_read(report_file), label))

    if not blocks:
        raise click.UsageError("No coverage.dat files found under %s" % str(base))

    return sources, blocks


def _tag_with_test_name(content: bytes, label: str) -> bytes:
    tn_line = "TN:{}\n".format(label).encode('utf-8')
    tagged = []
    for line in content.splitlines(keepends=True):
        if line.startswith(b"SF:"):
            tagged.append(tn_line)
        tagged.append(line)
    return b"".join(tagged)


def _read(file: "str | Path") -> bytes:
    with open(file, mode='rb') as f:
        return f.read()


def post_coverage(client: SmartTestsClient, session: SessionId, content: bytes) -> Tuple[str, Optional[int], bool]:
    try:
        res = client.request(
            "post", session.subpath("coverage"), compress=True, payload=BytesIO(content),
            additional_headers={"Content-Type": "text/plain"})
        res.raise_for_status()
        summary = res.json()
        return CoverageStatus.SUCCESS, summary.get("sourceFilesRecorded"), summary.get("isReupload", False)
    except Exception as e:
        click.echo("Failed to upload coverage report: {}".format(str(e)), err=True)
        return CoverageStatus.FAILED, None, False


def post_testmap(client: SmartTestsClient, session: SessionId, content: bytes) -> Tuple[str, Dict[str, Any]]:
    try:
        res = client.request(
            "post", session.subpath("testmap"), compress=True, payload=BytesIO(content),
            additional_headers={"Content-Type": "application/json"})
        res.raise_for_status()
        return CoverageStatus.SUCCESS, res.json()
    except Exception as e:
        click.echo("Failed to upload testmap: {}".format(str(e)), err=True)
        return CoverageStatus.FAILED, {}


def display_testmap_summary(testmap: str, status: str, summary: Optional[Dict[str, Any]] = None):
    summary = summary or {}

    def count(key: str) -> Any:
        value = summary.get(key)
        return "-" if value is None else value

    click.echo(tabulate(
        [[testmap, count("changedFiles"), count("testsRecorded"), count("rulesFired"), count("testsMatched"), status]],
        ["Testmap file", "Changed files", "Tests recorded", "Rules fired", "Tests matched", "Status"],
        tablefmt="github"))

    if summary.get("isReupload"):
        click.echo(
            click.style(
                "⚠ This session already had a testmap recorded. The previous upload was overwritten.",
                fg="yellow"),
            err=True)

    if status != CoverageStatus.SUCCESS:
        return

    without_rules = summary.get("repositoriesWithoutRules") or []
    hint = _zero_match_hint(summary, without_rules)
    if hint:
        click.echo(click.style("⚠ The testmap matched no tests. " + hint, fg="yellow"), err=True)
    elif without_rules:
        click.echo(
            "Changed files in repositories the testmap has no rules for: {}".format(", ".join(without_rules)),
            err=True)


def _zero_match_hint(summary: Dict[str, Any], without_rules: List[str]) -> Optional[str]:
    if summary.get("testsMatched") != 0:
        return None
    if summary.get("changedFiles") == 0:
        return ("The session has no changed files to match against: it made no `subset` request, "
                "or its build changed nothing.")
    if summary.get("testsRecorded") == 0:
        return ("No tests are recorded for this session yet. Run `record tests` before "
                "`record coverage --testmap`, then upload again.")
    if summary.get("rulesFired") == 0:
        message = "None of its source globs matched a changed file."
        if without_rules:
            message += (" The changed files are in repositories it has no key for: {}. A key must equal the "
                        "name given to `record build --source NAME=DIR` exactly, including case."
                        ).format(", ".join(without_rules))
        return message
    return "Its rules matched changed files, but no test glob matched a test recorded for this session."


def display_summary(sources: List[str], status: str, source_files: Optional[int], is_reupload: bool = False):
    if sources:
        click.echo(tabulate([[f] for f in sources], ["Coverage files found"], tablefmt="github"))
        click.echo()
    rows = [[len(sources), source_files if source_files is not None else "-", status]]
    click.echo(tabulate(rows, ["Coverage Files", "Source Files", "Status"], tablefmt="github"))
    if is_reupload:
        click.echo(
            click.style(
                "⚠ This session already had coverage recorded. The previous upload was overwritten. "
                "Refer to --help if you intended to record multiple files",
                fg="yellow"),
            err=True)
