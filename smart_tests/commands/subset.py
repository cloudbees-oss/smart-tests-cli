import glob
import json
import os
import pathlib
import random
import re
import subprocess
import sys
from enum import Enum
from io import TextIOWrapper
from multiprocessing import Process
from os.path import join
from typing import Annotated, Any, Callable, Dict, Iterable, List

import click
from tabulate import tabulate

import smart_tests.args4p.typer as typer
from smart_tests.utils.authentication import get_org_workspace
from smart_tests.utils.commands import Command
from smart_tests.utils.exceptions import print_error_and_die
from smart_tests.utils.session import SessionId, get_session
from smart_tests.utils.tracking import Tracking, TrackingClient

from ..app import Application
from ..args4p.command import Group
from ..args4p.converters import fileText, floatType, intType
from ..testpath import FilePathNormalizer, TestPath
from ..utils.env_keys import REPORT_ERROR_KEY
from ..utils.fail_fast_mode import (FailFastModeValidateParams, fail_fast_mode_validate,
                                    set_fail_fast_mode, warn_and_exit_if_fail_fast_mode)
from ..utils.input_snapshot import InputSnapshotId
from ..utils.smart_tests_client import SmartTestsClient
from ..utils.typer_types import Duration, Fraction, Percentage, parse_duration, parse_fraction, parse_percentage
from .test_path_writer import TestPathWriter

LARGE_TEST_PATHS_THRESHOLD = 100000
DEFAULT_CONNECT_TIMEOUT = 5
LARGE_PAYLOAD_CONNECT_TIMEOUT = 60


class SubsetUseCase(str, Enum):
    ONE_COMMIT = "one-commit"
    FEATURE_BRANCH = "feature-branch"
    RECURRING = "recurring"


class FallbackMode(str, Enum):
    RUN_ALL = "run-all"
    STOP = "stop"
    RANDOM_SAMPLE = "random-sample"


class SubsetResult:
    def __init__(
            self,
            subset=None,
            rest=None,
            subset_id: str = "",
            summary=None,
            is_brainless: bool = False,
            is_observation: bool = False):
        self.subset = subset or []
        self.rest = rest or []
        self.subset_id = subset_id
        self.summary = summary or {}
        self.is_brainless = is_brainless
        self.is_observation = is_observation

    @classmethod
    def from_response(cls, response: Dict[str, Any]) -> 'SubsetResult':
        return cls(
            subset=response.get("testPaths", []),
            rest=response.get("rest", []),
            subset_id=response.get("subsettingId", ""),
            summary=response.get("summary", {}),
            is_brainless=response.get("isBrainless", False),
            is_observation=response.get("isObservation", False)
        )

    @classmethod
    def from_test_paths(cls, test_paths: List[TestPath]) -> 'SubsetResult':
        return cls(
            subset=test_paths,
            rest=[],
            subset_id='',
            summary={},
            is_brainless=False,
            is_observation=False
        )

    @classmethod
    def from_random_sample(cls, test_paths: List[TestPath], target: float) -> 'SubsetResult':
        count = max(1, round(len(test_paths) * target))
        sampled = random.sample(test_paths, min(count, len(test_paths)))
        sampled_set = {id(t): t for t in sampled}
        rest = [t for t in test_paths if id(t) not in sampled_set]
        return cls(subset=sampled, rest=rest, subset_id='', summary={}, is_brainless=False, is_observation=False)


# Where we take TestPath, we also accept a path name as a string.
TestPathLike = str | TestPath


class Subset(TestPathWriter):
    # test_paths: List[TestPath]  # doesn't work with Python 3.5
    # is_get_tests_from_previous_sessions: bool

    input_given = False  # set to True when an attempt was made to add to self.test_paths

    # output_handler: Callable[[
    #   List[TestPathLike], List[TestPathLike]], None]

    # (Kohsuke) function that takes (subset,rest) and output the rest part, I think.
    # I'm actually not entirely sure what this pluggability does
    exclusion_output_handler: Callable[[List[TestPath], List[TestPath]], None]

    def __init__(
            self,
            app: Application,
            session: Annotated[SessionId, SessionId.as_option()],
            target: Annotated[Percentage | None, typer.Option(
                type=parse_percentage,
                help="Subsetting target from 0% to 100%",
                metavar="PERCENTAGE"
            )] = None,
            time: Annotated[Duration | None, typer.Option(
                type=parse_duration,
                help="Subsetting by absolute time, in seconds e.g) 300, 5m",
                metavar="TIME"
            )] = None,
            confidence: Annotated[Percentage | None, typer.Option(
                type=parse_percentage,
                help="Subsetting by confidence from 0% to 100%",
                metavar="PERCENTAGE"
            )] = None,
            similarity: Annotated[float | None, typer.Option(
                type=floatType(min=0.0, max=1.0),
                help='subsetting by similarity from 0 to 1.0. Tests scoring above this value are included in the subset.',
            )] = None,
            goal_spec: Annotated[str | None, typer.Option(
                help="Subsetting by programmatic goal definition",
                metavar="GOAL_SPEC"
            )] = None,
            base_path: Annotated[str | None, typer.Option(
                '--base',
                help="(Advanced) base directory to make test names portable",
                metavar="DIR"
            )] = None,
            rest: Annotated[str | None, typer.Option(
                help="Output the subset remainder to a file, e.g. --rest=remainder.txt",
                metavar="FILE"
            )] = None,
            # TODO(Konboi): omit from the smart-tests command initial release
            # split: Annotated[bool, typer.Option(
            #        help="split"
            # )] = False,
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
                help="Ignore tests that were added recently. "
                     "NOTICE: this option will ignore tests that you added just now as well"
            )] = False,
            is_get_tests_from_previous_sessions: Annotated[bool, typer.Option(
                "--get-tests-from-previous-sessions",
                help="Get subset list from previous full tests"
            )] = False,
            is_output_exclusion_rules: Annotated[bool, typer.Option(
                "--output-exclusion-rules",
                help="Outputs the exclude test list. Switch the subset and rest."
            )] = False,
            is_non_blocking: Annotated[bool, typer.Option(
                "--non-blocking",
                help="Do not wait for subset requests in observation mode.",
                hidden=True
            )] = False,
            ignore_flaky_tests_above: Annotated[float | None, typer.Option(
                help="Ignore flaky tests above the value set by this option. You can confirm flaky scores in WebApp",
                type=floatType(min=0.0, max=1.0),
                metavar="N"
            )] = None,
            prioritize_tests_failed_within_hours: Annotated[int | None, typer.Option(
                help="Prioritize tests that failed within the specified hours; maximum 720 hours (= 24 hours * 30 days)",
                type=intType(min=0, max=24 * 30),
                metavar="N"
            )] = None,
            prioritized_tests_mapping_file: Annotated[TextIOWrapper | None, typer.Option(
                "--prioritized-tests-mapping",
                help="Prioritize tests based on test mapping file",
                type=fileText(mode="r"),
                metavar="FILE"
            )] = None,
            input_snapshot_id: Annotated[InputSnapshotId | None, InputSnapshotId.as_option()] = None,
            print_input_snapshot_id: Annotated[bool, typer.Option(
                "--print-input-snapshot-id",
                help="Print the input snapshot ID returned from the server instead of the subset results"
            )] = False,
            subset_id_file: Annotated[str | None, typer.Option(
                "--subset-id-file",
                help="Write the subset ID to a file",
                metavar="FILE",
                hidden=True
            )] = None,
            bin_target: Annotated[Fraction | None, typer.Option(
                "--bin",
                help="Split subset into bins, e.g. --bin 1/4",
                metavar="INDEX/COUNT",
                type=parse_fraction
            )] = None,
            same_bin_files: Annotated[List[str], typer.Option(
                "--same-bin",
                help="Keep all tests listed in the file together when splitting; one test per line",
                metavar="FILE",
                multiple=True
            )] = [],
            is_get_tests_from_guess: Annotated[bool, typer.Option(
                "--get-tests-from-guess",
                help="Get subset list from guessed tests"
            )] = False,
            use_case: Annotated[SubsetUseCase | None, typer.Option(
                "--use-case",
                hidden=True
            )] = None,
            fallback_mode: Annotated[FallbackMode, typer.Option(
                "--fallback-mode",
                hidden=True,
                help="Behavior when the subset API is unavailable or the model is untrained. "
                     "'run-all' (default) runs all tests as usual; 'stop' exits with a non-zero status so CI halts; "
                     "'random-sample' picks a random subset locally based on the count derived from --fallback-sampling-target "
                     "(no duration estimates are available in this path).",
            )] = FallbackMode.RUN_ALL,
            fallback_sampling_target: Annotated[Percentage | None, typer.Option(
                "--fallback-sampling-target",
                type=parse_percentage,
                help="Sampling ratio (0%–100%) used when --fallback-mode=random-sample. "
                     "Required when --fallback-mode=random-sample is specified.",
                metavar="PERCENTAGE"
            )] = None,
            test_runner: Annotated[str | None, typer.Argument()] = None,
    ):
        super().__init__(app)

        app.test_runner = test_runner
        self.tracking_client = TrackingClient(Command.SUBSET, app=app)
        self.client = SmartTestsClient(app=app, tracking_client=self.tracking_client)

        set_fail_fast_mode(self.client.is_fail_fast_mode())
        fail_fast_mode_validate(FailFastModeValidateParams(command=Command.SUBSET, session=session))

        def warn(msg: str):
            click.secho("Warning: " + msg, fg="yellow", err=True)
            self.tracking_client.send_error_event(
                event_name=Tracking.ErrorEvent.WARNING_ERROR,
                stack_trace=msg
            )

        # Note(Konboi): when get_session throws exception, is_observation won't be defined
        # To avoid that, we define is_observation here (out of try block)
        is_observation = False
        try:
            test_session = get_session(session, self.client)
            self.build_name = test_session.build_name
            self.session_id = test_session.id
            is_observation = test_session.observation_mode
        except ValueError as e:
            print_error_and_die(msg=str(e), tracking_client=self.tracking_client, event=Tracking.ErrorEvent.USER_ERROR)
        except Exception as e:
            if os.getenv(REPORT_ERROR_KEY):
                raise e
            else:
                # not to block pipeline, parse session and use it
                self.client.print_exception_and_recover(e, "Warning: failed to check test session")
                self.build_name, self.session_id = session.build_part, session.test_part

        if is_get_tests_from_guess and is_get_tests_from_previous_sessions:
            print_error_and_die(
                "--get-tests-from-guess (list up tests from git ls-files and subset from there) and --get-tests-from-previous-sessions (list up tests from the recent runs and subset from there) are mutually exclusive. Which one do you want to use?",  # noqa E501
                self.tracking_client,
                Tracking.ErrorEvent.USER_ERROR
            )

        if is_observation and is_output_exclusion_rules:
            warn("--observation and --output-exclusion-rules are set. No output will be generated.")

        if prioritize_tests_failed_within_hours is not None and prioritize_tests_failed_within_hours > 0:
            if ignore_new_tests or (ignore_flaky_tests_above is not None and ignore_flaky_tests_above > 0):
                print_error_and_die(
                    "Cannot use --ignore-new-tests or --ignore-flaky-tests-above options with --prioritize-tests-failed-within-hours",  # noqa E501
                    self.tracking_client,
                    Tracking.ErrorEvent.INTERNAL_CLI_ERROR)

        if is_non_blocking and not is_observation:
            print_error_and_die(
                "You have to specify --observation option to use non-blocking mode",
                self.tracking_client,
                Tracking.ErrorEvent.INTERNAL_CLI_ERROR)

        if fallback_mode == FallbackMode.RANDOM_SAMPLE and fallback_sampling_target is None:
            print_error_and_die(
                "--fallback-sampling-target is required when --fallback-mode=random-sample",
                self.tracking_client,
                Tracking.ErrorEvent.USER_ERROR
            )

        if fallback_sampling_target is not None and fallback_mode != FallbackMode.RANDOM_SAMPLE:
            print_error_and_die(
                "--fallback-sampling-target can only be used with --fallback-mode=random-sample",
                self.tracking_client,
                Tracking.ErrorEvent.USER_ERROR
            )

        self.target = target
        self.time = time
        self.confidence = confidence
        self.similarity = similarity
        self.goal_spec = goal_spec
        self.base_path = base_path
        self.base_path_explicitly_set = (base_path is not None)
        self.rest = rest
        self.ignore_new_tests = ignore_new_tests
        self.is_get_tests_from_previous_sessions = is_get_tests_from_previous_sessions
        self.is_output_exclusion_rules = is_output_exclusion_rules
        self.is_non_blocking = is_non_blocking
        self.ignore_flaky_tests_above = ignore_flaky_tests_above
        self.prioritize_tests_failed_within_hours = prioritize_tests_failed_within_hours
        self.prioritized_tests_mapping_file = prioritized_tests_mapping_file
        self.input_snapshot_id = input_snapshot_id.value if input_snapshot_id else None
        self.print_input_snapshot_id = print_input_snapshot_id
        self.subset_id_file = subset_id_file
        self.bin_target = bin_target
        self.same_bin_files = list(same_bin_files)
        self.is_get_tests_from_guess = is_get_tests_from_guess
        self.use_case = use_case
        self.fallback_mode = fallback_mode
        self.fallback_sampling_target = fallback_sampling_target

        self._validate_print_input_snapshot_option()

        self.file_path_normalizer = FilePathNormalizer(base_path, no_base_path_inference=no_base_path_inference)

        self.test_paths: list[list[dict[str, str]]] = []
        self.output_handler = self._default_output_handler
        self.exclusion_output_handler = self._default_exclusion_output_handler

    def _default_output_handler(self, output: list[TestPath], rests: list[TestPath]):
        if self.rest:
            self.write_file(self.rest, rests)

        if output:
            self.print(output)

    def _default_exclusion_output_handler(self, subset: list[TestPath], rest: list[TestPath]):
        self.output_handler(rest, subset)

    def test_path(self, path: TestPathLike):
        """register one test"""

        def rel_base_path(path):
            if isinstance(path, str):
                return pathlib.Path(self.file_path_normalizer.relativize(path)).as_posix()
            else:
                return path

        self.input_given = True
        if isinstance(path, str) and any(s in path for s in ('*', "?")):
            for i in glob.iglob(path, recursive=True):
                if os.path.isfile(i):
                    self.test_paths.append(self.to_test_path(rel_base_path(i)))
        else:
            self.test_paths.append(self.to_test_path(rel_base_path(path)))

    def stdin(self) -> Iterable[str]:
        """
        Returns sys.stdin, but after ensuring that it's connected to something reasonable.

        This prevents a typical problem where users think CLI is hanging because
        they didn't feed anything from stdin

        HACK(Kohsuke): When is_get_tests_from_previous_sessions was added, that flag should have
        selected the code path that doesn't use stdin. But instead, for some reasons the change
        was made to make stdin() return empty list. Until we fix that, this function is returning
        Iterable[str], so that we can return [] as "empty stdin".
        """

        # To avoid the cli continue to wait from stdin
        if self._should_skip_stdin():
            return []

        if sys.stdin.isatty():
            warn_and_exit_if_fail_fast_mode(
                "Warning: this command reads from stdin but it doesn't appear to be connected to anything. "
                "Did you forget to pipe from another command?"
            )
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
             path_builder: Callable[[str], TestPathLike | None] | None = None):
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
                return pathlib.Path(self.file_path_normalizer.relativize(join(base, file_name))).as_posix()

            path_builder = default_path_builder

        for b in glob.iglob(base):
            for t in glob.iglob(join(b, pattern), recursive=True):
                path = path_builder(os.path.relpath(t, b))
                if path:
                    self.test_paths.append(self.to_test_path(path))

    def get_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "testPaths": self.test_paths,
            "testRunner": self.app.test_runner,
            "session": {
                # expecting just the last component, not the whole path
                "id": os.path.basename(str(self.session_id))
            },
            "ignoreNewTests": self.ignore_new_tests,
            "getTestsFromPreviousSessions": self.is_get_tests_from_previous_sessions,
            "getTestsFromGuess": self.is_get_tests_from_guess,
        }

        if self.target is not None:
            payload["goal"] = {
                "type": "subset-by-percentage",
                "percentage": float(self.target),
            }
        elif self.time is not None:
            payload["goal"] = {
                "type": "subset-by-absolute-time",
                "duration": float(self.time),
            }
        elif self.confidence is not None:
            payload["goal"] = {
                "type": "subset-by-confidence",
                "percentage": float(self.confidence)
            }
        elif self.goal_spec is not None:
            payload["goal"] = {
                "type": "subset-by-goal-spec",
                "goal": self.goal_spec
            }
        elif self.similarity is not None:
            payload["goal"] = {
                "type": "subset-by-similarity",
                "similarity": self.similarity
            }
        else:
            payload['useServerSideOptimizationTarget'] = True

        if self.ignore_flaky_tests_above:
            payload["dropFlakinessThreshold"] = self.ignore_flaky_tests_above

        if self.prioritize_tests_failed_within_hours:
            payload["hoursToPrioritizeFailedTest"] = self.prioritize_tests_failed_within_hours

        if self.prioritized_tests_mapping_file:
            payload['prioritizedTestsMapping'] = json.load(self.prioritized_tests_mapping_file)

        if self.use_case:
            payload['changesUnderTest'] = self.use_case.value

        if self.input_snapshot_id is not None:
            payload['subsettingId'] = self.input_snapshot_id

        split_subset = self._build_split_subset_payload()
        if split_subset:
            payload['splitSubset'] = split_subset

        return payload

    def _build_split_subset_payload(self) -> dict[str, Any] | None:
        if self.bin_target is None:
            if self.same_bin_files:
                print_error_and_die(
                    "--same-bin option requires --bin option.\nPlease set --bin option to use --same-bin",
                    self.tracking_client,
                    Tracking.ErrorEvent.USER_ERROR,
                )
            return None

        slice_index = self.bin_target.numerator
        slice_count = self.bin_target.denominator

        if slice_index <= 0 or slice_count <= 0:
            print_error_and_die(
                "Invalid --bin value. Both index and count must be positive integers.",
                self.tracking_client,
                Tracking.ErrorEvent.USER_ERROR,
            )

        if slice_count < slice_index:
            print_error_and_die(
                "Invalid --bin value. The numerator cannot exceed the denominator.",
                self.tracking_client,
                Tracking.ErrorEvent.USER_ERROR,
            )

        same_bins = self._read_same_bin_files()

        return {
            "sliceIndex": slice_index,
            "sliceCount": slice_count,
            "sameBins": same_bins,
        }

    def _read_same_bin_files(self) -> list[list[TestPath]]:
        if not self.same_bin_files:
            return []

        formatter = self.same_bin_formatter
        if formatter is None:
            print_error_and_die(
                "--same-bin is not supported for this test runner.",
                self.tracking_client,
                Tracking.ErrorEvent.USER_ERROR,
            )

        same_bins: list[list[TestPath]] = []
        seen_tests: set[str] = set()

        for same_bin_file in self.same_bin_files:
            try:
                with open(same_bin_file, "r", encoding="utf-8") as fp:
                    tests = [line.strip() for line in fp if line.strip()]
            except OSError as exc:
                print_error_and_die(
                    f"Failed to read --same-bin file '{same_bin_file}': {exc}",
                    self.tracking_client,
                    Tracking.ErrorEvent.USER_ERROR,
                )

            unique_tests = list(dict.fromkeys(tests))

            group: list[TestPath] = []
            for test in unique_tests:
                if test in seen_tests:
                    print_error_and_die(
                        f"Error: test '{test}' is listed in multiple --same-bin files.",
                        self.tracking_client,
                        Tracking.ErrorEvent.USER_ERROR,
                    )
                seen_tests.add(test)

                # For type check
                assert formatter is not None, "--same -bin is not supported for this test runner"
                formatted = formatter(test)
                if not formatted:
                    print_error_and_die(
                        f"Failed to parse test '{test}' from --same-bin file {same_bin_file}",
                        self.tracking_client,
                        Tracking.ErrorEvent.USER_ERROR,
                    )
                group.append(formatted)

            same_bins.append(group)

        return same_bins

    def _collect_potential_test_files(self):
        LOOSE_TEST_FILE_PATTERN = r'(\.(test|spec)\.|_test\.|Test\.|Spec\.|test/|tests/|__tests__/|src/test/)'
        EXCLUDE_PATTERN = r'(BUILD|Makefile|Dockerfile|LICENSE|.gitignore|.gitkeep|.keep|id_rsa|rsa|blank|taglib)|\.(xml|json|jsonl|txt|yml|yaml|toml|md|png|jpg|jpeg|gif|svg|sql|html|css|graphql|proto|gz|zip|rz|bzl|conf|config|snap|pem|crt|key|lock|jpi|hpi|jelly|properties|jar|ini|mod|sum|bmp|env|envrc|sh|csv|list)$'  # noqa E501

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

    def _fallback_result(self) -> SubsetResult:
        if self.fallback_mode == FallbackMode.STOP:
            click.echo(
                "Warning: Smart Tests could not retrieve a subset. Stopping build (--fallback-mode=stop).",
                err=True,
            )
            sys.exit(1)
        elif self.fallback_mode == FallbackMode.RANDOM_SAMPLE:
            assert self.fallback_sampling_target is not None
            target_fraction = float(self.fallback_sampling_target)
            click.echo(
                f"Warning: Smart Tests could not retrieve a subset. "
                f"Falling back to local random sample at {target_fraction:.0%}.",
                err=True,
            )
            return SubsetResult.from_random_sample(self.test_paths, target_fraction)
        else:
            return SubsetResult.from_test_paths(self.test_paths)

    def request_subset(self) -> SubsetResult:
        # temporarily extend the timeout because subset API response has become slow
        # TODO: remove this line when API response return response
        # within 300 sec
        connect_timeout = DEFAULT_CONNECT_TIMEOUT
        if (len(self.test_paths) >= LARGE_TEST_PATHS_THRESHOLD):
            connect_timeout = LARGE_PAYLOAD_CONNECT_TIMEOUT
        timeout = (connect_timeout, 300)
        payload = self.get_payload()

        if self.is_non_blocking:
            # Create a new process for requesting a subset.
            process = Process(target=subset_request, args=(self.client, timeout, payload))
            process.start()
            click.echo("The subset was requested in non-blocking mode.", err=True)
            self.output_handler(self.test_paths, [])
            # With non-blocking mode, we don't need to wait for the response
            sys.exit(0)

        try:
            res = subset_request(client=self.client, timeout=timeout, payload=payload)
            # The status code 422 is returned when validation error of the test mapping file occurs.
            if res.status_code == 422:
                print_error_and_die("Error: {}".format(res.reason), self.tracking_client, Tracking.ErrorEvent.USER_ERROR)

            res.raise_for_status()

            return SubsetResult.from_response(res.json())
        except Exception as e:
            self.tracking_client.send_error_event(
                event_name=Tracking.ErrorEvent.INTERNAL_CLI_ERROR,
                stack_trace=str(e),
            )
            self.client.print_exception_and_recover(
                e, "Warning: the service failed to subset. Falling back to running all tests")
            return self._fallback_result()

    def _requires_test_input(self) -> bool:
        return (
            self.input_snapshot_id is None
            and not self.is_get_tests_from_previous_sessions  # noqa: W503
            and len(self.test_paths) == 0  # noqa: W503
        )

    def _should_skip_stdin(self) -> bool:
        if self.is_get_tests_from_previous_sessions or self.is_get_tests_from_guess:
            return True

        if self.input_snapshot_id is not None:
            if not sys.stdin.isatty():
                warn_and_exit_if_fail_fast_mode(
                    "Warning: --input-snapshot-id is set so stdin will be ignored."
                )
            return True
        return False

    def _validate_print_input_snapshot_option(self):
        if not self.print_input_snapshot_id:
            return

        conflicts: list[str] = []
        option_checks = [
            ("--target", self.target is not None),
            ("--time", self.time is not None),
            ("--confidence", self.confidence is not None),
            ("--goal-spec", self.goal_spec is not None),
            ("--rest", self.rest is not None),
            ("--bin", self.bin_target is not None),
            ("--same-bin", bool(self.same_bin_files)),
            ("--ignore-new-tests", self.ignore_new_tests),
            ("--ignore-flaky-tests-above", self.ignore_flaky_tests_above is not None),
            ("--prioritize-tests-failed-within-hours", self.prioritize_tests_failed_within_hours is not None),
            ("--prioritized-tests-mapping", self.prioritized_tests_mapping_file is not None),
            ("--get-tests-from-previous-sessions", self.is_get_tests_from_previous_sessions),
            ("--get-tests-from-guess", self.is_get_tests_from_guess),
            ("--output-exclusion-rules", self.is_output_exclusion_rules),
            ("--non-blocking", self.is_non_blocking),
        ]

        for option_name, is_set in option_checks:
            if is_set:
                conflicts.append(option_name)

        if conflicts:
            conflict_list = ", ".join(conflicts)
            print_error_and_die(
                f"--print-input-snapshot-id cannot be used with {conflict_list}.",
                self.tracking_client,
                Tracking.ErrorEvent.USER_ERROR,
            )

    def _print_input_snapshot_id_value(self, subset_result: SubsetResult):
        if not subset_result.subset_id:
            raise click.ClickException(
                "Subset request did not return an input snapshot ID. Please re-run the command."
            )

        click.echo(subset_result.subset_id)

    def _write_subset_id_to_file(self, subset_result: SubsetResult):
        if not subset_result.subset_id:
            print_error_and_die(
                "Subset request did not return a subset ID. Please re-run the command.",
                self.tracking_client,
                Tracking.ErrorEvent.INTERNAL_CLI_ERROR,
            )

        assert self.subset_id_file is not None  # Early type guard
        with open(self.subset_id_file, 'w', encoding='utf-8') as f:
            f.write(str(subset_result.subset_id) + '\n')

    def run(self):
        """called after tests are scanned to compute the optimized order"""

        if self.is_get_tests_from_guess:
            self._collect_potential_test_files()

        if self._requires_test_input():
            if self.input_given:
                print_error_and_die("ERROR: Given arguments did not match any tests. They appear to be incorrect/non-existent.", tracking_client, Tracking.ErrorEvent.USER_ERROR)  # noqa E501
            else:
                print_error_and_die(
                    "ERROR: Expecting tests to be given, but none provided. See https://help.launchableinc.com/features/predictive-test-selection/requesting-and-running-a-subset-of-tests/ and provide ones, or use the `--get-tests-from-previous-sessions` option",  # noqa E501
                    self.tracking_client,
                    Tracking.ErrorEvent.USER_ERROR)

        # When Error occurs, return the test name as it is passed.
        if not self.session_id:
            # Session ID in --session is missing. It might be caused by
            # Launchable API errors.
            subset_result = self._fallback_result()
        else:
            subset_result = self.request_subset()

        if len(subset_result.subset) == 0:
            if len(subset_result.rest) > 0 and self.client.is_pts_v2_enabled() and self.confidence is not None:
                # Adaptive Dynamic Subset can return an empty subset when the model
                # determines no tests in that suite are relevant to the code change.
                click.echo(click.style("No tests were selected for this code change.", fg="yellow"), err=True)
            else:
                warn_and_exit_if_fail_fast_mode("Error: no tests found matching the path.")

                if self.print_input_snapshot_id:
                    self._print_input_snapshot_id_value(subset_result)
                if self.subset_id_file:
                    self._write_subset_id_to_file(subset_result)
                return

        if self.print_input_snapshot_id:
            self._print_input_snapshot_id_value(subset_result)
            return

        if self.subset_id_file:
            self._write_subset_id_to_file(subset_result)

        # TODO(Konboi): split subset isn't provided for smart-tests initial release
        # if split:
        #   click.echo("subset/{}".format(subset_result.subset_id))
        if subset_result.is_brainless:
            click.echo("Your model is currently in training", err=True)
            # brainless mode split tests on servers. so we don't have to run
            # client side fallback.
            if self.fallback_mode != FallbackMode.RANDOM_SAMPLE:
                subset_result = self._fallback_result()

        output_subset, output_rests = subset_result.subset, subset_result.rest

        if subset_result.is_observation:
            output_subset = output_subset + output_rests
            output_rests = []

        if self.is_output_exclusion_rules:
            self.exclusion_output_handler(output_subset, output_rests)
        else:
            self.output_handler(output_subset, output_rests)

        # When Launchable returns an error, the cli skips showing summary
        # report
        original_subset = subset_result.subset
        original_rest = subset_result.rest
        summary = subset_result.summary
        if "subset" not in summary.keys() or "rest" not in summary.keys():
            return

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

        click.echo(
            "Smart Tests created subset {} for build {} (test session {}) in workspace {}/{}".format(
                subset_result.subset_id,
                self.build_name,
                self.session_id,
                org, workspace,
            ), err=True,
        )
        if subset_result.is_observation:
            click.echo(
                "(This test session is under observation mode)",
                err=True)

        click.echo("", err=True)
        click.echo(tabulate(rows, header, tablefmt="github", floatfmt=".2f"), err=True)

        click.echo(
            "\nRun `smart-tests inspect subset --subset-id {}` to view full subset details".format(subset_result.subset_id),
            err=True)


subset = Group(callback=Subset, help="Subsetting tests")


def subset_request(client: SmartTestsClient, timeout: tuple[int, int], payload: dict[str, Any]):
    return client.request("post", "subset", timeout=timeout, payload=payload, compress=True)
