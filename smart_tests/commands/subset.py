import glob
import json
import os
import pathlib
import re
import subprocess
import sys
from multiprocessing import Process
from os.path import join
from typing import Annotated, Any, Callable, TextIO

import typer
from tabulate import tabulate

from smart_tests.utils.authentication import get_org_workspace
from smart_tests.utils.tracking import Tracking, TrackingClient

from ..app import Application
from ..testpath import FilePathNormalizer, TestPath
from ..utils.dynamic_commands import DynamicCommandBuilder, extract_callback_options
from ..utils.env_keys import REPORT_ERROR_KEY
from ..utils.fail_fast_mode import (FailFastModeValidateParams, fail_fast_mode_validate,
                                    set_fail_fast_mode, warn_and_exit_if_fail_fast_mode)
from ..utils.launchable_client import LaunchableClient
from ..utils.typer_types import ignorable_error, validate_duration, validate_percentage
from .helper import get_session_id, parse_session
from .test_path_writer import TestPathWriter

# TODO: rename files and function accordingly once the PR landscape


app = typer.Typer(name="subset", help="Subsetting tests")


@app.callback()
def subset(
    ctx: typer.Context,
    session: Annotated[str, typer.Option(
        "--session",
        help="test session name or session ID in the format builds/<build-name>/test_sessions/<test-session-id>",
        metavar="SESSION_NAME"
    )],
    build: Annotated[str | None, typer.Option(
        "--build",
        help="build name",
        metavar="BUILD_NAME"
    )] = None,
    target: Annotated[str | None, typer.Option(
        help="subsetting target from 0% to 100%"
    )] = None,
    time: Annotated[str | None, typer.Option(
        help="subsetting by absolute time, in seconds e.g) 300, 5m"
    )] = None,
    confidence: Annotated[str | None, typer.Option(
        help="subsetting by confidence from 0% to 100%"
    )] = None,
    goal_spec: Annotated[str | None, typer.Option(
        help="subsetting by programmatic goal definition"
    )] = None,
    base: Annotated[str | None, typer.Option(
        help="(Advanced) base directory to make test names portable",
        metavar="DIR"
    )] = None,
    rest: Annotated[str | None, typer.Option(
        help="Output the subset remainder to a file, e.g. `--rest=remainder.txt`"
    )] = None,
    flavor: Annotated[list[str], typer.Option(
        help="flavors",
        metavar="KEY=VALUE"
    )] = [],
    split: Annotated[bool, typer.Option(
        help="split"
    )] = False,
    no_base_path_inference: Annotated[bool, typer.Option(
        "--no-base-path-inference",
        help="Do not guess the base path to relativize the test file paths. "
             "By default, if the test file paths are absolute file paths, it automatically "
             "guesses the repository root directory and relativize the paths. With this "
             "option, the command doesn't do this guess work. "
             "If --base is specified, the absolute file paths are relativized to the "
             "specified path irrelevant to this option. Use it if the guessed base path is incorrect."
    )] = False,
    ignore_new_tests: Annotated[bool, typer.Option(
        "--ignore-new-tests",
        help="Ignore tests that were added recently. NOTICE: this option will ignore tests that you added just now as well"
    )] = False,
    observation: Annotated[bool, typer.Option(
        help="enable observation mode"
    )] = False,
    get_tests_from_previous_sessions: Annotated[bool, typer.Option(
        "--get-tests-from-previous-sessions",
        help="get subset list from previous full tests"
    )] = False,
    output_exclusion_rules: Annotated[bool, typer.Option(
        "--output-exclusion-rules",
        help="outputs the exclude test list. Switch the subset and rest."
    )] = False,
    non_blocking: Annotated[bool, typer.Option(
        "--non-blocking",
        help="Do not wait for subset requests in observation mode.",
        hidden=True
    )] = False,
    ignore_flaky_tests_above: Annotated[float | None, typer.Option(
        help="Ignore flaky tests above the value set by this option. You can confirm flaky scores in WebApp",
        min=0.0, max=1.0
    )] = None,
    no_build: Annotated[bool, typer.Option(
        "--no-build",
        help="If you want to only send test reports, please use this option"
    )] = False,
    prioritize_tests_failed_within_hours: Annotated[int | None, typer.Option(
        help="Prioritize tests that failed within the specified hours; maximum 720 hours (= 24 hours * 30 days)",
        min=0, max=24 * 30
    )] = None,
    prioritized_tests_mapping: Annotated[typer.FileText | None, typer.Option(
        "--prioritized-tests-mapping",
        help="Prioritize tests based on test mapping file",
        mode="r"
    )] = None,
    session_name: Annotated[str | None, typer.Option(
        "--session-name",
        help="test session name",
        metavar="SESSION_NAME"
    )] = None,
    lineage: Annotated[str | None, typer.Option(
        "--lineage",
        help="Set lineage name. This option value will be passed to the record session command if a session isn't created yet.",
        metavar="LINEAGE"
    )] = None,
    test_suite: Annotated[str | None, typer.Option(
        "--test-suite",
        help="Set test suite name. This option value will be passed to the record session command "
             "if a session isn't created yet.",
        metavar="TEST_SUITE"
    )] = None,
    get_tests_from_guess: Annotated[bool, typer.Option(
        "--get-tests-from-guess",
        help="get subset list from git managed files"
    )] = False,
):
    app = ctx.obj

    # Parse and validate parameters
    parsed_target = validate_percentage(target) if target else None
    parsed_duration = validate_duration(time) if time else None
    parsed_confidence = validate_percentage(confidence) if confidence else None

    # Map parameter names to match original function
    base_path = base
    build_name = build
    duration_value = parsed_duration
    target_value = parsed_target
    confidence_value = parsed_confidence
    is_observation = observation
    is_get_tests_from_previous_sessions = get_tests_from_previous_sessions
    is_output_exclusion_rules = output_exclusion_rules
    is_non_blocking = non_blocking
    is_no_build = no_build
    is_get_tests_from_guess = get_tests_from_guess
    prioritized_tests_mapping_file = prioritized_tests_mapping

    tracking_client = TrackingClient(Tracking.Command.SUBSET, app=app)

    # Create client early to check fail-fast mode
    try:
        client = LaunchableClient(test_runner="subset", app=app, tracking_client=tracking_client)
        set_fail_fast_mode(client.is_fail_fast_mode())
        fail_fast_mode_validate(FailFastModeValidateParams(
            command=Tracking.Command.SUBSET,
            session=session,
            build=build_name,
            flavor=[(kv.split('=', 1) if '=' in kv else kv.split(':', 1)) for kv in flavor],
            links=[],  # subset command doesn't have links
            is_no_build=is_no_build,
            is_observation=is_observation,
        ))
    except Exception as e:
        tracking_client.send_error_event(
            event_name=Tracking.ErrorEvent.INTERNAL_CLI_ERROR,
            stack_trace=str(e),
        )
        raise

    def print_error_and_die(msg: str, event: Tracking.ErrorEvent):
        typer.echo(typer.style(msg, fg=typer.colors.RED), err=True)
        tracking_client.send_error_event(event_name=event, stack_trace=msg)
        sys.exit(1)

    def warn(msg: str):
        typer.echo(typer.style("Warning: " + msg, fg=typer.colors.YELLOW), err=True)
        tracking_client.send_error_event(
            event_name=Tracking.ErrorEvent.WARNING_ERROR,
            stack_trace=msg
        )

    if is_get_tests_from_guess and is_get_tests_from_previous_sessions:
        print_error_and_die(
            "--get-tests-from-guess (list up tests from git ls-files and subset from there) and --get-tests-from-previous-sessions (list up tests from the recent runs and subset from there) are mutually exclusive. Which one do you want to use?",  # noqa E501
            Tracking.ErrorEvent.USER_ERROR
        )

    if is_observation and is_output_exclusion_rules:
        warn("--observation and --output-exclusion-rules are set. No output will be generated.")

    if prioritize_tests_failed_within_hours is not None and prioritize_tests_failed_within_hours > 0:
        if ignore_new_tests or (ignore_flaky_tests_above is not None and ignore_flaky_tests_above > 0):
            print_error_and_die(
                "Cannot use --ignore-new-tests or --ignore-flaky-tests-above options with --prioritize-tests-failed-within-hours",
                Tracking.ErrorEvent.INTERNAL_CLI_ERROR
            )

    if is_no_build and session:
        typer.echo(
            typer.style(
                f"WARNING: `--session` and `--no-build` are set.\nUsing --session option value ({session}) and ignoring `--no-build` option",  # noqa: E501
                fg=typer.colors.YELLOW),
            err=True)
        is_no_build = False

    session_id = None
    try:
        if session_name:
            if not build_name:
                raise typer.BadParameter(
                    '--build option is required when you use a --session-name option ')
            sub_path = "builds/{}/test_session_names/{}".format(build_name, session_name)
            res = client.request("get", sub_path)
            res.raise_for_status()
            session_id = "builds/{}/test_sessions/{}".format(build_name, res.json().get("id"))
        else:
            session_id = get_session_id(session, build_name, is_no_build, client)
    except typer.BadParameter as e:
        typer.echo(
            typer.style(
                str(e),
                fg=typer.colors.RED),
            err=True,
        )
        tracking_client.send_error_event(event_name=Tracking.ErrorEvent.USER_ERROR, stack_trace=str(e))
        sys.exit(1)
    except Exception as e:
        tracking_client.send_error_event(
            event_name=Tracking.ErrorEvent.INTERNAL_CLI_ERROR,
            stack_trace=str(e),

        )
        if os.getenv(REPORT_ERROR_KEY):
            raise e
        else:
            typer.echo(ignorable_error(e), err=True)

    if is_non_blocking:
        if (not is_observation) and session_id:
            try:
                client = LaunchableClient(
                    app=app,
                    tracking_client=tracking_client)
                res = client.request("get", session_id)
                is_observation_in_recorded_session = res.json().get("isObservation", False)
                if not is_observation_in_recorded_session:
                    print_error_and_die(
                        "You have to specify --observation option to use non-blocking mode",
                        Tracking.ErrorEvent.INTERNAL_CLI_ERROR)
            except Exception as e:
                tracking_client.send_error_event(
                    event_name=Tracking.ErrorEvent.INTERNAL_CLI_ERROR,
                    stack_trace=str(e),
                )
                typer.echo(ignorable_error(e), err=True)

    file_path_normalizer = FilePathNormalizer(base_path, no_base_path_inference=no_base_path_inference)

    # TODO: placed here to minimize invasion in this PR to reduce the likelihood of
    # PR merge hell. This should be moved to a top-level class

    TestPathWriter.base_path = base_path
    TestPathWriter.base_path_explicitly_set = (base_path is not None)

    class Optimize(TestPathWriter):
        # test_paths: List[TestPath]  # doesn't work with Python 3.5
        # is_get_tests_from_previous_sessions: bool

        # Where we take TestPath, we also accept a path name as a string.
        TestPathLike = str | TestPath

        # output_handler: Callable[[
        #   List[TestPathLike], List[TestPathLike]], None]
        # exclusion_output_handler: Callable[[List[TestPathLike],
        # List[TestPathLike], bool], None]]

        def __init__(self, app: Application, client: LaunchableClient, tracking_client: TrackingClient):
            self.rest = rest
            self.input_given = False  # set to True when an attempt was made to add to self.test_paths
            self.test_paths: list[list[dict[str, str]]] = []
            self.output_handler = self._default_output_handler
            self.exclusion_output_handler = self._default_exclusion_output_handler
            self.is_get_tests_from_previous_sessions = is_get_tests_from_previous_sessions
            self.is_output_exclusion_rules = is_output_exclusion_rules
            self.is_get_tests_from_guess = is_get_tests_from_guess
            self.test_runner: str | None = None  # Will be set by set_test_runner
            self.client = client
            self.tracking_client = tracking_client
            super(Optimize, self).__init__(app=app)

        def set_test_runner(self, test_runner: str):
            """Set the test runner name for this subset operation"""
            self.test_runner = test_runner

        @property
        def base_path(self):
            """Provide access to base_path for test runners compatibility"""
            return TestPathWriter.base_path

        def _default_output_handler(self, output: list[TestPath], rests: list[TestPath]):
            if rest:
                self.write_file(rest, rests)

            if output:
                self.print(output)

        def _default_exclusion_output_handler(self, subset: list[TestPath], rest: list[TestPath]):
            self.output_handler(rest, subset)

        def test_path(self, path: TestPathLike):
            """register one test"""

            def rel_base_path(path):
                if isinstance(path, str):
                    return pathlib.Path(file_path_normalizer.relativize(path)).as_posix()
                else:
                    return path

            self.input_given = True
            if isinstance(path, str) and any(s in path for s in ('*', "?")):
                for i in glob.iglob(path, recursive=True):
                    if os.path.isfile(i):
                        self.test_paths.append(self.to_test_path(rel_base_path(i)))
            else:
                self.test_paths.append(self.to_test_path(rel_base_path(path)))

        def stdin(self) -> TextIO | list:
            """
            Returns sys.stdin, but after ensuring that it's connected to something reasonable.

            This prevents a typical problem where users think CLI is hanging because
            they didn't feed anything from stdin
            """

            # To avoid the cli continue to wait from stdin
            if self.is_get_tests_from_previous_sessions or self.is_get_tests_from_guess:
                return []

            if sys.stdin.isatty():
                typer.echo(
                    typer.style(
                        "Warning: this command reads from stdin but it doesn't appear to be connected to anything. "
                        "Did you forget to pipe from another command?",
                        fg=typer.colors.YELLOW),
                    err=True)
            return sys.stdin

        @staticmethod
        def to_test_path(x: TestPathLike) -> TestPath:
            """Convert input to a TestPath"""
            if isinstance(x, str):
                # default representation for a file
                return [{'type': 'file', 'name': x}]
            else:
                return x

        def scan(self, base: str, pattern: str,
                 path_builder: Callable[[str], TestPath | str | None] | None = None):
            """
            Starting at the 'base' path, recursively add everything that matches the given GLOB pattern

            scan('src/test/java', '**/*.java')

            'path_builder' is a function used to map file name into a custom test path.
            It takes a single string argument that represents the portion matched to the glob pattern,
            and its return value controls what happens to that file:
                - skip a file by returning a False-like object
                - if a str is returned, that's interpreted as a path name and
                  converted to the default test path representation. Typically, `os.path.join(base,file_name)
                - if a TestPath is returned, that's added as is
            """

            self.input_given = True

            if path_builder is None:
                # default implementation of path_builder creates a file name relative to `source` so as not
                # to be affected by the path
                def default_path_builder(file_name):
                    return pathlib.Path(file_path_normalizer.relativize(join(base, file_name))).as_posix()

                path_builder = default_path_builder

            for b in glob.iglob(base):
                for t in glob.iglob(join(b, pattern), recursive=True):
                    if path_builder:
                        path = path_builder(os.path.relpath(t, b))
                    if path:
                        self.test_paths.append(self.to_test_path(path))

        def get_payload(
            self,
            session_id: str,
            target: float | None,
            duration: float | None,
            confidence: float | None,
            test_runner: str,
        ):
            payload: dict[str, Any] = {
                "testPaths": self.test_paths,
                "testRunner": test_runner,
                "session": {
                    # expecting just the last component, not the whole path
                    "id": os.path.basename(session_id)
                },
                "ignoreNewTests": ignore_new_tests,
                "getTestsFromPreviousSessions": self.is_get_tests_from_previous_sessions,
            }

            if target is not None:
                payload["goal"] = {
                    "type": "subset-by-percentage",
                    "percentage": target,
                }
            elif duration is not None:
                payload["goal"] = {
                    "type": "subset-by-absolute-time",
                    "duration": duration,
                }
            elif confidence is not None:
                payload["goal"] = {
                    "type": "subset-by-confidence",
                    "percentage": confidence
                }
            elif goal_spec is not None:
                payload["goal"] = {
                    "type": "subset-by-goal-spec",
                    "goal": goal_spec
                }
            else:
                payload['useServerSideOptimizationTarget'] = True

            if ignore_flaky_tests_above:
                payload["dropFlakinessThreshold"] = ignore_flaky_tests_above

            if prioritize_tests_failed_within_hours:
                payload["hoursToPrioritizeFailedTest"] = prioritize_tests_failed_within_hours

            if prioritized_tests_mapping_file:
                payload['prioritizedTestsMapping'] = json.load(prioritized_tests_mapping_file)

            return payload

        def _collect_potential_test_files(self):
            LOOSE_TEST_FILE_PATTERN = r'(\.(test|spec)\.|_test\.|Test\.|Spec\.|test/|tests/|__tests__/|src/test/)'
            EXCLUDE_PATTERN = r'\.(xml|json|txt|yml|yaml|md)$'

            try:
                git_managed_files = subprocess.run(['git', 'ls-files'], stdout=subprocess.PIPE,
                                                   universal_newlines=True, check=True).stdout.strip().split('\n')
            except subprocess.CalledProcessError as e:
                warn_and_exit_if_fail_fast_mode(f"git ls-files failed (exit code={e.returncode})")
                return
            except OSError as e:
                warn_and_exit_if_fail_fast_mode(f"git ls-files failed: {e}")
                return

            found = False
            for f in git_managed_files:
                if re.search(LOOSE_TEST_FILE_PATTERN, f) and not re.search(EXCLUDE_PATTERN, f):
                    self.test_paths.append(self.to_test_path(f))
                    found = True

            if not found:
                warn_and_exit_if_fail_fast_mode("Nothing that looks like a test file in the current git repository.")

        def request_subset(self, session_id: str, target_value: float | None,
                           duration_value: float | None, confidence_value: float | None,
                           is_non_blocking: bool) -> SubsetResult:
            test_runner = self.test_runner
            # temporarily extend the timeout because subset API response has become slow
            # TODO: remove this line when API response return response
            # within 300 sec
            timeout = (5, 300)
            payload = self.get_payload(session_id, target_value, duration_value, confidence_value, test_runner)

            if is_non_blocking:
                # Create a new process for requesting a subset.
                process = Process(target=subset_request, args=(self.client, timeout, payload))
                process.start()
                typer.echo("The subset was requested in non-blocking mode.", err=True)
                self.output_handler(self.test_paths, [])
                # With non-blocking mode, we don't need to wait for the response
                sys.exit(0)

            try:
                res = subset_request(client=self.client, timeout=timeout, payload=payload)
                # The status code 422 is returned when validation error of the test mapping file occurs.
                if res.status_code == 422:
                    print_error_and_die("Error: {}".format(res.reason), Tracking.ErrorEvent.USER_ERROR)

                return SubsetResult.from_response(res.json())
            except Exception as e:
                self.tracking_client.send_error_event(
                    event_name=Tracking.ErrorEvent.INTERNAL_CLI_ERROR,
                    stack_trace=str(e),
                )
                self.client.print_exception_and_recover(
                    e, "Warning: the service failed to subset. Falling back to running all tests")
                return SubsetResult.from_test_paths(self.test_paths)

        def run(self, session_id: str | None, target_value: float | None,
                duration_value: float | None, confidence_value: float | None,
                is_non_blocking: bool, split: bool):
            """called after tests are scanned to compute the optimized order"""

            if self.is_get_tests_from_guess:
                self._collect_potential_test_files()

            if not self.is_get_tests_from_previous_sessions and len(self.test_paths) == 0:
                if self.input_given:
                    print_error_and_die("ERROR: Given arguments did not match any tests. They appear to be incorrect/non-existent.", Tracking.ErrorEvent.USER_ERROR)  # noqa E501
                else:
                    print_error_and_die(
                        "ERROR: Expecting tests to be given, but none provided. See https://www.launchableinc.com/docs/features/predictive-test-selection/requesting-and-running-a-subset-of-tests/subsetting-with-the-launchable-cli/ and provide ones, or use the `--get-tests-from-previous-sessions` option",  # noqa E501
                        Tracking.ErrorEvent.USER_ERROR)

            # When Error occurs, return the test name as it is passed.
            if not session_id:
                # Session ID in --session is missing. It might be caused by
                # Launchable API errors.
                subset_result = SubsetResult.from_test_paths(self.test_paths)
            else:
                subset_result = self.request_subset(session_id, target_value, duration_value, confidence_value, is_non_blocking)

            if len(subset_result.subset) == 0:
                warn_and_exit_if_fail_fast_mode("Error: no tests found matching the path.")
                return

            return subset_result

    optimize = Optimize(app=app, client=client, tracking_client=tracking_client)
    optimize.set_test_runner("subset")  # Set default test runner
    ctx.obj = optimize

    # Execute the optimization
    subset_result = optimize.run(session_id, target_value, duration_value, confidence_value, is_non_blocking, split)

    if subset_result is None:
        return

    # Handle output
    if split:
        typer.echo(f"subset/{subset_result.subset_id}")
    else:
        output_subset, output_rests = subset_result.subset, subset_result.rest

        if subset_result.is_observation:
            output_subset = output_subset + output_rests
            output_rests = []

        if is_output_exclusion_rules:
            optimize.exclusion_output_handler(output_subset, output_rests)
        else:
            optimize.output_handler(output_subset, output_rests)

    # Show summary report
    original_subset = subset_result.subset
    original_rest = subset_result.rest
    summary = subset_result.summary
    if "subset" not in summary.keys() or "rest" not in summary.keys():
        return

    build_name, test_session_id = parse_session(session_id) if session_id else ("", "")
    org, workspace = get_org_workspace()

    header = ["", "Candidates",
              "Estimated duration (%)", "Estimated duration (min)"]
    rows = [
        [
            "Subset",
            len(original_subset),
            summary["subset"].get("rate", 0.0),
            summary["subset"].get("duration", 0.0),
        ],
        [
            "Remainder",
            len(original_rest),
            summary["rest"].get("rate", 0.0),
            summary["rest"].get("duration", 0.0),
        ],
        [],
        [
            "Total",
            len(original_subset) + len(original_rest),
            summary["subset"].get("rate", 0.0) + summary["rest"].get("rate", 0.0),
            summary["subset"].get("duration", 0.0) + summary["rest"].get("duration", 0.0),
        ],
    ]

    if subset_result.is_brainless:
        typer.echo(
            "Your model is currently in training", err=True)

    typer.echo(
        f"Launchable created subset {subset_result.subset_id} for build {build_name} "
        f"(test session {test_session_id}) in workspace {org}/{workspace}",
        err=True,
    )
    if subset_result.is_observation:
        typer.echo(
            "(This test session is under observation mode)",
            err=True)

    typer.echo("", err=True)
    typer.echo(tabulate(rows, header, tablefmt="github", floatfmt=".2f"), err=True)

    typer.echo(
        f"\nRun `launchable inspect subset --subset-id {subset_result.subset_id}` to view full subset details",
        err=True)


def subset_request(client: LaunchableClient, timeout: tuple[int, int], payload: dict[str, Any]):
    return client.request("post", "subset", timeout=timeout, payload=payload, compress=True)


class SubsetResult:
    def __init__(
            self,
            subset: list[TestPath] = None,
            rest: list[TestPath] = None,
            subset_id: str = "",
            summary: dict[str, Any] = None,
            is_brainless: bool = False,
            is_observation: bool = False):
        self.subset = subset or []
        self.rest = rest or []
        self.subset_id = subset_id
        self.summary = summary or {}
        self.is_brainless = is_brainless
        self.is_observation = is_observation

    @classmethod
    def from_response(cls, response: dict[str, Any]) -> 'SubsetResult':
        return cls(
            subset=response.get("testPaths", []),
            rest=response.get("rest", []),
            subset_id=response.get("subsettingId", ""),
            summary=response.get("summary", {}),
            is_brainless=response.get("isBrainless", False),
            is_observation=response.get("isObservation", False)
        )

    @classmethod
    def from_test_paths(cls, test_paths: list[TestPath]) -> 'SubsetResult':
        return cls(
            subset=test_paths,
            rest=[],
            subset_id='',
            summary={},
            is_brainless=False,
            is_observation=False
        )


# NestedCommand implementation: create test runner-specific commands
# This section adds the new command structure where test runners come before options
nested_command_app = typer.Typer(name="subset", help="Subsetting tests (NestedCommand)")


def create_nested_commands():
    """Create NestedCommand commands after all test runners are loaded."""
    builder = DynamicCommandBuilder()

    # Extract options from the original subset callback
    callback_options = extract_callback_options(subset)

    # Create test runner-specific subset commands
    builder.create_subset_commands(nested_command_app, subset, callback_options)

# The commands will be created when test runners are loaded
