import datetime
import glob
import os
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from http import HTTPStatus
from typing import Callable, Dict, Generator, List, Optional, Sequence, Tuple, Union

import click
from dateutil.parser import parse
from junitparser import JUnitXml, JUnitXmlError, TestCase, TestSuite  # type: ignore  # noqa: F401
from more_itertools import ichunked
from tabulate import tabulate

from launchable.utils.authentication import ensure_org_workspace
from launchable.utils.tracking import Tracking, TrackingClient

from ...testpath import FilePathNormalizer, TestPathComponent, unparse_test_path
from ...utils.click import DATETIME_WITH_TZ, KEY_VALUE, validate_past_datetime
from ...utils.commands import Command
from ...utils.exceptions import InvalidJUnitXMLException
from ...utils.fail_fast_mode import (FailFastModeValidateParams, fail_fast_mode_validate,
                                     set_fail_fast_mode, warn_and_exit_if_fail_fast_mode)
from ...utils.launchable_client import LaunchableClient
from ...utils.logger import Logger
from ...utils.no_build import NO_BUILD_BUILD_NAME, NO_BUILD_TEST_SESSION_ID
from ...utils.session import parse_session, read_build
from ..helper import find_or_create_session, time_ns
from .case_event import CaseEvent, CaseEventType

GROUP_NAME_RULE = re.compile("^[a-zA-Z0-9][a-zA-Z0-9_-]*$")
RESERVED_GROUP_NAMES = ["group", "groups", "nogroup", "nogroups"]


def _validate_group(ctx, param, value):
    if value is None:
        return ""

    if str(value).lower() in RESERVED_GROUP_NAMES:
        raise click.BadParameter("{} is reserved name.".format(value))

    if GROUP_NAME_RULE.match(value):
        return value
    else:
        raise click.BadParameter("group option supports only alphabet(a-z, A-Z), number(0-9), '-', and '_'")


@click.group()
@click.option(
    '--base',
    'base_path',
    help='(Advanced) base directory to make test names portable',
    type=click.Path(exists=True, file_okay=False),
    metavar="DIR",
)
@click.option(
    '--session',
    'session',
    help='In the format builds/<build-name>/test_sessions/<test-session-id>',
    type=str,
)
@click.option(
    '--build',
    'build_name',
    help='build name',
    type=str,
    metavar='BUILD_NAME',
    hidden=True,
)
@click.option(
    '--subset-id',
    'subsetting_id',
    help='subset_id',
    type=str,
)
@click.option(
    '--post-chunk',
    help='Post chunk',
    default=1000,
    type=int
)
@click.option(
    "--flavor",
    "flavor",
    help='flavors',
    metavar='KEY=VALUE',
    type=KEY_VALUE,
    default=(),
    multiple=True,
)
@click.option(
    "--no_base_path_inference",
    "no_base_path_inference",
    help="""Do not guess the base path to relativize the test file paths.

    By default, if the test file paths are absolute file paths, it automatically
    guesses the repository root directory and relativize the paths. With this
    option, the command doesn't do this guess work.

    If --base_path is specified, the absolute file paths are relativized to the
    specified path irrelevant to this option. Use it if the guessed base path is
    incorrect.
    """,
    is_flag=True
)
@click.option(
    '--report-paths',
    help='Instead of POSTing test results, just report test paths in the report file then quit. '
         'For diagnostics. Use with --dry-run',
    is_flag=True,
    hidden=True
)
@click.option(
    '--group',
    "group",
    help='Grouping name for test results',
    type=str,
    callback=_validate_group,
)
@click.option(
    "--allow-test-before-build",
    "is_allow_test_before_build",
    help="",
    is_flag=True,
    hidden=True,
)
@click.option(
    '--link',
    'links',
    help="Set external link of title and url",
    multiple=True,
    default=(),
    type=KEY_VALUE,
)
@click.option(
    '--no-build',
    'is_no_build',
    help="If you want to only send test reports, please use this option",
    is_flag=True,
)
@click.option(
    '--session-name',
    'session_name',
    help='test session name',
    required=False,
    type=str,
    metavar='SESSION_NAME',
)
@click.option(
    '--lineage',
    'lineage',
    help='Set lineage name. This option value will be passed to the record session command if a session isn\'t created yet.',
    required=False,
    type=str,
    metavar='LINEAGE',
)
@click.option(
    '--test-suite',
    'test_suite',
    help='Set test suite name. This option value will be passed to the record session command if a session isn\'t created yet.',  # noqa: E501
    required=False,
    type=str,
    metavar='TEST_SUITE',
)
@click.option(
    '--timestamp',
    'timestamp',
    help='Used to overwrite the test executed times when importing historical data. Note: Format must be `YYYY-MM-DDThh:mm:ssTZD` or `YYYY-MM-DDThh:mm:ss` (local timezone applied)',  # noqa: E501
    type=DATETIME_WITH_TZ,
    default=None,
    callback=validate_past_datetime,
)
@click.pass_context
def tests(
    context: click.core.Context,
    base_path: str,
    session: Optional[str],
    build_name: Optional[str],
    post_chunk: int,
    subsetting_id: str,
    flavor: Sequence[Tuple[str, str]],
    no_base_path_inference: bool,
    report_paths: bool,
    group: str,
    is_allow_test_before_build: bool,
    links: Sequence[Tuple[str, str]] = (),
    is_no_build: bool = False,
    session_name: Optional[str] = None,
    lineage: Optional[str] = None,
    test_suite: Optional[str] = None,
    timestamp: Optional[datetime.datetime] = None,
):
    logger = Logger()

    org, workspace = ensure_org_workspace()

    test_runner = context.invoked_subcommand

    tracking_client = TrackingClient(Command.RECORD_TESTS, app=context.obj)
    client = LaunchableClient(test_runner=test_runner, app=context.obj, tracking_client=tracking_client)
    set_fail_fast_mode(client.is_fail_fast_mode())

    fail_fast_mode_validate(FailFastModeValidateParams(
        command=Command.RECORD_TESTS,
        session=session,
        build=build_name,
        flavor=flavor,
        links=links,
        is_no_build=is_no_build,
        test_suite=test_suite,
    ))

    file_path_normalizer = FilePathNormalizer(base_path, no_base_path_inference=no_base_path_inference)

    if is_no_build and (read_build() and read_build() != ""):
        msg = 'The cli already created `.launchable` file.' \
            'If you want to use `--no-build` option, please remove `.launchable` file before executing.'
        tracking_client.send_error_event(
            event_name=Tracking.ErrorEvent.INTERNAL_CLI_ERROR,
            stack_trace=msg,

        )
        raise click.UsageError(message=msg)  # noqa: E501

    if is_no_build and session:
        warn_and_exit_if_fail_fast_mode(
            "WARNING: `--session` and `--no-build` are set.\nUsing --session option value ({}) and ignoring `--no-build` option".format(session),  # noqa: E501
        )

        is_no_build = False

    if session and links:
        warn_and_exit_if_fail_fast_mode(
            "WARNING: `--link` and `--session` are set together.\n--link option can't be used with existing sessions."
        )

    try:
        if is_no_build:
            session_id = "builds/{}/test_sessions/{}".format(NO_BUILD_BUILD_NAME, NO_BUILD_TEST_SESSION_ID)
            record_start_at = INVALID_TIMESTAMP
        elif subsetting_id:
            result = get_session_and_record_start_at_from_subsetting_id(subsetting_id, client)
            session_id = result["session"]
            record_start_at = result["start_at"]
        elif session_name:
            if not build_name:
                raise click.UsageError(
                    '--build option is required when you uses a --session-name option ')

            sub_path = "builds/{}/test_session_names/{}".format(build_name, session_name)
            res = client.request("get", sub_path)
            res.raise_for_status()

            session_id = "builds/{}/test_sessions/{}".format(build_name, res.json().get("id"))
            record_start_at = get_record_start_at(session_id, client)
        else:
            # The session_id must be back, so cast to str
            session_id = str(find_or_create_session(
                context=context,
                session=session,
                build_name=build_name,
                flavor=flavor,
                links=links,
                lineage=lineage,
                test_suite=test_suite,
                timestamp=timestamp,
                tracking_client=tracking_client))
            build_name = read_build()
            record_start_at = get_record_start_at(session_id, client)

        build_name, test_session_id = parse_session(session_id)
    except Exception as e:
        tracking_client.send_error_event(
            event_name=Tracking.ErrorEvent.INTERNAL_CLI_ERROR,
            stack_trace=str(e),
        )
        client.print_exception_and_recover(e)
        # To prevent users from stopping the CI pipeline, the cli exits with a
        # status code of 0, indicating that the program terminated successfully.
        exit(0)

    # TODO: placed here to minimize invasion in this PR to reduce the likelihood of
    # PR merge hell. This should be moved to a top-level class
    class RecordTests:
        # The most generic form of parsing, where a path to a test report
        # is turned into a generator by using CaseEvent.create()
        ParseFunc = Callable[[str], Generator[CaseEventType, None, None]]

        # A common mechanism to build ParseFunc by building JUnit XML report in-memory (or build it the usual way
        # and patch it to fix things up). This is handy as some libraries
        # produce invalid / broken JUnit reports
        JUnitXmlParseFunc = Callable[[str], ET.Element]

        @property
        def path_builder(self) -> CaseEvent.TestPathBuilder:
            """
            This function, if supplied, is used to build a test path
            that uniquely identifies a test case
            """
            return self._path_builder

        @path_builder.setter
        def path_builder(self, v: CaseEvent.TestPathBuilder):
            self._path_builder = v

        @property
        def parse_func(self) -> ParseFunc:
            return self._parse_func

        @parse_func.setter
        def parse_func(self, f: ParseFunc):
            self._parse_func = f

        @property
        def build_name(self) -> str:
            return self._build_name

        @build_name.setter
        def build_name(self, build_name: str):
            self._build_name = build_name

        @property
        def test_session_id(self) -> int:
            return self._test_session_id

        @test_session_id.setter
        def test_session_id(self, test_session_id: int):
            self._test_session_id = test_session_id

        # session is generated by `launchable record session` command
        # the session format is `builds/<BUILD_NUMBER>/test_sessions/<TEST_SESSION_ID>`
        @property
        def session(self) -> str:
            return self._session

        @session.setter
        def session(self, session: str):
            self._session = session

        @property
        def is_no_build(self) -> bool:
            return self._is_no_build

        @is_no_build.setter
        def is_no_build(self, is_no_build: bool):
            self._is_no_build = is_no_build

        @property
        def metadata_builder(self) -> CaseEvent.DataBuilder:
            """
            This function, if supplied, is used to build a test path
            that uniquely identifies a test case
            """
            return self._metadata_builder

        @metadata_builder.setter
        def metadata_builder(self, v: CaseEvent.DataBuilder):
            self._metadata_builder = v

        # setter only property that sits on top of the parse_func property
        def set_junitxml_parse_func(self, f: JUnitXmlParseFunc):
            """
            Parse XML report file with the JUnit report file, possibly with the custom parser function 'f'
            that can be used to build JUnit ET.Element tree from scratch or do some patch up.

            If f=None, the default parse code from JUnitParser module is used.
            """

            def parse(report: str) -> Generator[CaseEventType, None, None]:
                # To understand JUnit XML format, https://llg.cubic.org/docs/junit/ is helpful
                # TODO: robustness: what's the best way to deal with broken XML
                # file, if any?
                try:
                    xml = JUnitXml.fromfile(report, f)
                except Exception as e:
                    # `JUnitXml.fromfile()` will raise `JUnitXmlError` and other lxml related errors
                    # if the file has wrong format.
                    # https://github.com/weiwei/junitparser/blob/master/junitparser/junitparser.py#L321
                    warn_and_exit_if_fail_fast_mode(
                        "Warning: error reading JUnitXml file {filename}: {error}".format(
                            filename=report, error=e))
                    return
                if isinstance(xml, JUnitXml):
                    testsuites = [suite for suite in xml]
                elif isinstance(xml, TestSuite):
                    testsuites = [xml]
                else:
                    raise InvalidJUnitXMLException(filename=report)

                try:
                    for suite in testsuites:
                        for case in suite:
                            yield CaseEvent.from_case_and_suite(self.path_builder, case, suite, report, self.metadata_builder)
                except Exception as e:
                    warn_and_exit_if_fail_fast_mode(
                        "Warning: error parsing JUnitXml file {filename}: {error}".format(
                            filename=report, error=e))

            self.parse_func = parse

        junitxml_parse_func = property(None, set_junitxml_parse_func)

        @property
        def check_timestamp(self):
            return self._check_timestamp

        @check_timestamp.setter
        def check_timestamp(self, enable: bool):
            self._check_timestamp = enable

        def __init__(self, dry_run=False):
            self.reports = []
            self.skipped_reports = []
            self.path_builder = CaseEvent.default_path_builder(file_path_normalizer)
            self.junitxml_parse_func = None
            self.check_timestamp = True
            self.base_path = base_path
            self.dry_run = dry_run
            self.no_base_path_inference = no_base_path_inference
            self.is_allow_test_before_build = is_allow_test_before_build
            self.build_name = build_name
            self.test_session_id = test_session_id
            self.session = session_id
            self.is_no_build = is_no_build
            self.metadata_builder = CaseEvent.default_data_builder()

        def make_file_path_component(self, filepath) -> TestPathComponent:
            """Create a single TestPathComponent from the given file path"""
            if base_path:
                filepath = os.path.relpath(filepath, start=base_path)
            return {"type": "file", "name": filepath}

        def report(self, junit_report_file: str):
            ctime = datetime.datetime.fromtimestamp(
                os.path.getctime(junit_report_file))

            if (
                    not self.is_allow_test_before_build  # nlqa: W503
                    and not self.is_no_build  # noqa: W503
                    and timestamp is None  # noqa: W503
                    and self.check_timestamp  # noqa: W503
                    and ctime.timestamp() < record_start_at.timestamp()  # noqa: W503
            ):
                format = "%Y-%m-%d %H:%M:%S"
                logger.warning("skip: {} is too old to report. start_record_at: {} file_created_at: {}".format(
                    junit_report_file, record_start_at.strftime(format), ctime.strftime(format)))
                self.skipped_reports.append(junit_report_file)

                return

            self.reports.append(junit_report_file)

        def scan(self, base: str, pattern: str):
            """
            Starting at the 'base' path, recursively add everything that matches the given GLOB pattern

            scan('build/test-reports', '**/*.xml')
            """
            for t in glob.iglob(os.path.join(base, pattern), recursive=True):
                self.report(t)

        def run(self):
            count = 0  # count number of test cases sent
            is_observation = False

            def testcases(reports: List[str]) -> Generator[CaseEventType, None, None]:
                exceptions = []
                for report in reports:
                    try:
                        for tc in self.parse_func(report):
                            # trim empty test path
                            if len(tc.get('testPath', [])) == 0:
                                continue

                            # Set specific time for importing historical data
                            if timestamp is not None:
                                tc["createdAt"] = timestamp.isoformat()

                            yield tc

                    except Exception as e:
                        exceptions.append(Exception("Failed to process a report file: {}".format(report), e))

                if len(exceptions) > 0:
                    # defer XML parsing exceptions so that we can send what we
                    # can send before we bail out
                    raise Exception(exceptions)

            # generator that creates the payload incrementally
            def payload(
                    cases: Generator[TestCase, None, None],
                    test_runner, group: str,
                    test_suite_name: str,
                    flavors: Dict[str, str]) -> Tuple[Dict[str, Union[str, List, dict, bool]], List[Exception]]:
                nonlocal count
                cs = []
                exs = []

                while True:
                    try:
                        cs.append(next(cases))
                    except StopIteration:
                        break
                    except Exception as ex:
                        exs.append(ex)

                count += len(cs)
                return {
                    "events": cs,
                    "testRunner": test_runner,
                    "group": group,
                    "metadata": get_env_values(client),
                    "noBuild": self.is_no_build,
                    # NOTE:
                    # testSuite and flavors are applied only when the no-build option is enabled
                    "testSuite": test_suite_name,
                    "flavors": flavors,
                }, exs

            def send(payload: Dict[str, Union[str, List]]) -> None:
                res = client.request(
                    "post", "{}/events".format(self.session), payload=payload, compress=True)

                if res.status_code == HTTPStatus.NOT_FOUND:
                    if session:
                        build, _ = parse_session(session)
                        warn_and_exit_if_fail_fast_mode(
                            "Session {} was not found. Make sure to run `launchable record session --build {}` before `launchable record tests`".format(session, build))  # noqa: E501

                    elif build_name:
                        warn_and_exit_if_fail_fast_mode(
                            "Build {} was not found. Make sure to run `launchable record build --name {}` before `launchable record tests`".format(build_name, build_name))  # noqa: E501

                res.raise_for_status()

                nonlocal is_observation
                is_observation = res.json().get("testSession", {}).get("isObservation", False)

                # If don’t override build, test session and session_id, build and test session will be made per chunk request.
                if is_no_build:
                    self.build_name = res.json().get("build", {}).get("build", NO_BUILD_BUILD_NAME)
                    self.test_session_id = res.json().get("testSession", {}).get("id", NO_BUILD_TEST_SESSION_ID)
                    self.session = "builds/{}/test_sessions/{}".format(self.build_name, self.test_session_id)
                    self.is_no_build = False

            def recorded_result() -> Tuple[int, int, int, float]:
                test_count = 0
                success_count = 0
                fail_count = 0
                duration = float(0)

                for tc in testcases(self.reports):
                    test_count += 1
                    status = tc.get("status")
                    if status == 0:
                        fail_count += 1
                    elif status == 1:
                        success_count += 1
                    duration += float(tc.get("duration") or 0)  # sec

                return test_count, success_count, fail_count, duration / 60   # sec to min

            try:
                start = time_ns()
                tc = testcases(self.reports)
                end = time_ns()
                tracking_client.send_event(
                    event_name=Tracking.Event.PERFORMANCE,
                    metadata={
                        "elapsedTime": end - start,
                        "measurementTarget": "testcases method(parsing report file)"
                    }
                )

                if report_paths:
                    # diagnostics mode to just report test paths
                    for t in tc:
                        print(unparse_test_path(t['testPath']))
                    return

                MAX_UPLOAD_WORKERS = 3

                start = time_ns()
                exceptions = []
                with ThreadPoolExecutor(max_workers=MAX_UPLOAD_WORKERS) as executor:
                    futures = []
                    for chunk in ichunked(tc, post_chunk):
                        p, es = payload(
                            cases=chunk,
                            test_runner=test_runner,
                            group=group,
                            test_suite_name=test_suite if test_suite else "",
                            flavors=dict(flavor),
                        )
                        exceptions.extend(es)
                        futures.append(executor.submit(send, p))

                    for future in as_completed(futures):
                        future.result()
                end = time_ns()
                tracking_client.send_event(
                    event_name=Tracking.Event.PERFORMANCE,
                    metadata={
                        "elapsedTime": end - start,
                        "measurementTarget": "events API"
                    }
                )

                if len(exceptions) > 0:
                    raise Exception(exceptions)

            except Exception as e:
                tracking_client.send_error_event(
                    event_name=Tracking.ErrorEvent.INTERNAL_CLI_ERROR,
                    stack_trace=str(e),
                )
                client.print_exception_and_recover(e)
                return

            if count == 0:
                if len(self.skipped_reports) != 0:
                    warn_and_exit_if_fail_fast_mode(
                        "{} test report(s) were skipped because they were created before this build was recorded.\n"
                        "Make sure to run your tests after you run `launchable record build`.\n"
                        "Otherwise, if these are really correct test reports, use the `--allow-test-before-build` option.".
                        format(len(self.skipped_reports)))
                    return
                else:
                    warn_and_exit_if_fail_fast_mode(
                        "Looks like tests didn't run? If not, make sure the right files/directories were passed into `launchable record tests`")  # noqa: E501
                    return

            file_count = len(self.reports)
            test_count, success_count, fail_count, duration = recorded_result()

            click.echo(
                "Launchable recorded tests for build {} (test session {}) to workspace {}/{} from {} files:".format(
                    self.build_name,
                    self.test_session_id,
                    org,
                    workspace,
                    file_count,
                ))

            if is_observation:
                click.echo("(This test session is under observation mode)")

            click.echo("")

            header = ["Files found", "Tests found", "Tests passed", "Tests failed", "Total duration (min)"]

            rows = [[file_count, test_count, success_count, fail_count, duration]]
            click.echo(tabulate(rows, header, tablefmt="github", floatfmt=".2f"))

            if duration == 0:
                click.echo(click.style("\nTotal test duration is 0."
                                       "\nPlease check whether the test duration times in report files are correct.", "yellow"))

            click.echo(
                "\nVisit https://app.launchableinc.com/organizations/{organization}/workspaces/"
                "{workspace}/test-sessions/{test_session_id} to view uploaded test results "
                "(or run `launchable inspect tests --test-session-id {test_session_id}`)"
                .format(
                    organization=org,
                    workspace=workspace,
                    test_session_id=self.test_session_id,
                ))

    context.obj = RecordTests(dry_run=context.obj.dry_run)


# if we fail to determine the timestamp of the build, we err on the side of collecting more test reports
# than no test reports, so we use the 'epoch' timestamp
INVALID_TIMESTAMP = datetime.datetime.fromtimestamp(0)


def get_record_start_at(session: Optional[str], client: LaunchableClient):
    """
    Determine the baseline timestamp to be used for up-to-date checks of report files.
    Only files newer than this timestamp will be collected.

    Based on the thinking that if a build doesn't exist tests couldn't have possibly run, we attempt
    to use the timestamp of a build, with appropriate fallback.
    """
    if session is None:
        raise click.UsageError('Either --build or --session has to be specified')

    if session:
        build_name, _ = parse_session(session)

    sub_path = "builds/{}".format(build_name)

    res = client.request("get", sub_path)
    if res.status_code != 200:
        if res.status_code == 404:
            msg = "Build {} was not found. " \
                  "Make sure to run `launchable record build --name {}` before `launchable record tests`".format(
                      build_name, build_name)
        else:
            msg = "Unable to determine the timestamp of the build {}. HTTP response code was {}".format(
                build_name,
                res.status_code)
        click.echo(click.style(msg, 'yellow'), err=True)

        # to avoid stop report command
        return INVALID_TIMESTAMP

    created_at = res.json()["createdAt"]
    Logger().debug("Build {} timestamp = {}".format(build_name, created_at))
    t = parse_launchable_timeformat(created_at)
    return t


def parse_launchable_timeformat(t: str) -> datetime.datetime:
    # e.g) "2021-04-01T09:35:47.934+00:00"
    try:
        return parse(t)
    except Exception as e:
        Logger().error("parse time error {}. time: {}".format(str(e), t))
        return INVALID_TIMESTAMP


def get_session_and_record_start_at_from_subsetting_id(subsetting_id: str, client: LaunchableClient):
    s = subsetting_id.split('/')

    # subset/{id}
    if len(s) != 2:
        raise click.UsageError('Invalid subset id. like `subset/123/slice` but got {}'.format(subsetting_id))

    res = client.request("get", subsetting_id)
    if res.status_code != 200:
        raise click.UsageError(click.style("Unable to get subset information from subset id {}".format(
            subsetting_id), 'yellow'))

    build_number = res.json()["build"]["buildNumber"]
    created_at = res.json()["build"]["createdAt"]
    test_session_id = res.json()["testSession"]["id"]

    return {
        "session": "builds/{}/test_sessions/{}".format(build_number, test_session_id),
        "start_at": parse_launchable_timeformat(created_at)
    }


def get_env_values(client: LaunchableClient) -> Dict[str, str]:
    sub_path = "slack/notification/key/list"
    res = client.request("get", sub_path=sub_path)

    metadata: Dict[str, str] = {}
    if res.status_code != 200:
        return metadata

    keys = res.json().get("keys", [])
    for key in keys:
        val = os.getenv(key, "")
        metadata[key] = val

    return metadata
