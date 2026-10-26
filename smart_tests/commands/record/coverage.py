import glob
import os
from io import BytesIO
from pathlib import Path
from typing import Annotated, List, Optional, Tuple

import click
from tabulate import tabulate

import smart_tests.args4p.typer as typer
from smart_tests.utils.session import SessionId, get_session

from ... import args4p
from ...app import Application
from ...utils.smart_tests_client import SmartTestsClient


class CoverageStatus:
    SUCCESS = "✓ Recorded successfully"
    FAILED = "⚠ Failed to record"


@args4p.command(help="Record coverage data (LCOV format) related to a test session. "
                "Passing COVERAGE_FILES is optional for bazel; "
                "files are auto discovered when the command is run inside project root. "
                "Other test runners must pass their coverage report file(s) directly.")
def coverage(
    app: Application,
    session: Annotated[SessionId, SessionId.as_option()],
    coverage_files: Annotated[List[str], typer.Argument(
        multiple=True,
        required=False,
        help="Coverage report files to upload (LCOV format)"
    )] = [],
):
    client = SmartTestsClient(app=app)
    sources: List[str] = []

    try:
        # Assert test session exists
        get_session(session, client)

        if coverage_files:
            sources = list(coverage_files)
            blocks = [_read(f) for f in sources]
        else:
            # No files given: auto-discover from the current directory
            # Auto discovery is Bazel only for now.
            sources, blocks = discover_bazel_coverage(Path("."))

        # LCOV tracefiles are just a sequence of SF:...end_of_record blocks, so concatenating
        # multiple files is itself a valid tracefile. Send them as one upload rather than one
        # request per file. The server already unions repeated SF: blocks for the same file within
        # one upload, so this is correct even when the inputs cover overlapping files (e.g. one
        # report from a unit-test run, another from an integration-test run touching the same
        # source file)
        content = b"\n".join(blocks)
        status, files_recorded, is_reupload = post_coverage(client, session, content)
    except Exception as e:
        client.print_exception_and_recover(e)
        status, files_recorded, is_reupload = CoverageStatus.FAILED, None, False

    display_summary(sources, status, files_recorded, is_reupload)


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


def _read(path: str) -> bytes:
    with open(path, mode='rb') as f:
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
