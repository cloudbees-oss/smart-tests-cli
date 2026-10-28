import sys
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

from junitparser import Error, Failure, IntAttr, Skipped, TestCase, TestSuite

from ...testpath import FilePathNormalizer, TestPath

POSSIBLE_RESULTS = (Failure, Error, Skipped)

# Surefire's rerun/flaky extension tags. junitparser's TestCase.ITER_TYPES (and thus
# case.result/case.system_out/case.system_err) doesn't know about these, so they're
# read directly off the raw element.
RERUN_TAGS = ("rerunFailure", "rerunError")
FLAKY_TAGS = ("flakyFailure", "flakyError")

# Internal-only key tagging which original <testcase> an event came from (see
# from_case_and_suite). Used by summarize_case_events to group retry/flaky attempts of the
# SAME testcase without relying on testPath (which can be lossy, e.g. Maven's nested-class
# $-stripping, or missing/extra attributes from the raw runner's free-form TestPathComponent).
# Must be stripped before a payload is uploaded (see tests.py's payload()).
BATCH_ID_KEY = "testcaseBatchId"

CaseEventType = Dict[str, Any]


class CaseEvent:
    EVENT_TYPE = "case"
    TEST_SKIPPED = 2
    TEST_PASSED = 1
    TEST_FAILED = 0

    STATUS_MAP = {
        'TEST_SKIPPED': TEST_SKIPPED,
        'TEST_PASSED': TEST_PASSED,
        'TEST_FAILED': TEST_FAILED,
    }

    # function that computes TestPath from a test case
    # The 3rd argument is the report file path
    TestPathBuilder = Callable[[TestCase, TestSuite, str], TestPath]

    DataBuilder = Callable[[TestCase], Optional[Dict[str, Any]]]

    @staticmethod
    def default_path_builder(
            file_path_normalizer: FilePathNormalizer) -> TestPathBuilder:
        """
        Obtains a default TestPathBuilder that uses a base directory to relativize the file name
        """

        def f(case: TestCase, suite: TestSuite, report_file: str) -> TestPath:
            classname = case._elem.attrib.get("classname") or suite._elem.attrib.get("classname")
            filepath = case._elem.attrib.get("file") or suite._elem.attrib.get("filepath")
            if filepath:
                filepath = file_path_normalizer.relativize(filepath)

            test_path = []
            if filepath:
                test_path.append({"type": "file", "name": filepath})
            if classname:
                test_path.append({"type": "class", "name": classname})
            if case.name:
                test_path.append({"type": "testcase", "name": case._elem.attrib.get("name")})
            return test_path

        return f

    @staticmethod
    def default_data_builder() -> DataBuilder:
        def f(case: TestCase):
            """
            case for:
                <testcase ... file="tests/commands/inspect/test_tests.py" line="133">
                </testcase>
            """
            metadata = MetadataTestCase.fromelem(case)
            if metadata and metadata.line is not None:
                return {
                    "lineNumber": metadata.line
                }
            return None

        return f

    @classmethod
    def from_case_and_suite(
        cls,
        path_builder: TestPathBuilder,
        case: TestCase,
        suite: TestSuite,
        report_file: str,
        data_builder: DataBuilder
    ) -> List[Dict]:
        """
        Builds JSON representations of CaseEvent(s) from JUnitParser objects.

        Normally a <testcase> maps to a single event. But Surefire's rerun/flaky
        reports pack multiple attempts into one <testcase> (see RERUN_TAGS/FLAKY_TAGS);
        each attempt is expanded into its own FAILED event here, in addition to the
        testcase's own final PASSED/FAILED/SKIPPED result.
        """

        def path_canonicalizer(test_path: TestPath) -> TestPath:
            if sys.platform == "win32":
                for p in test_path:
                    p['name'] = p['name'].replace("\\", "/")

            return test_path

        def stdout(case: TestCase) -> str:
            """
            case for:
                <testcase>
                <system-out>...</system-out>
                </testcase>
            """
            if case.system_out is not None:
                return case.system_out

            return ""

        # TODO(Improvement): when <system-err> is present, it currently replaces the failure's own
        # text/message below instead of being appended to it. A test can both fail AND
        # print to stderr (e.g. a logged warning before the assertion), so this can hide
        # the actual failure detail behind unrelated captured output. Consider
        # concatenating (failure text/message first, then system-err) instead of
        # returning early here.
        def stderr(case: TestCase) -> str:
            """
            case for:
                <testcase>
                <system-err>...</system-err>
                </testcase>
            """
            if case.system_err is not None:
                return case.system_err

            """
            case for:
                <testcase>
                <failure message="...">...</failure>
                </testcase>
            """
            stderr = ""
            for result in case.result:
                if type(result) in POSSIBLE_RESULTS:
                    # Since the `message` property is a summary of the `text` property,
                    # we should attempt to retrieve the `text` property first in order to obtain a detailed log.
                    if result.text:
                        stderr = stderr + result.text
                    elif result.message:
                        stderr = stderr + result.message + "\n"

            return stderr

        def final_result() -> Tuple[int, str, str, float]:
            """
            The testcase's own final result: unchanged from before this method supported reruns.
            <testcase time> is defined by Surefire as the duration of THIS run (the first failing
            run, or the last successful run), so this is the one attempt that keeps it.
            """
            # TODO: reconsider the initial value of the status.
            status = CaseEvent.TEST_PASSED
            for r in case.result:
                if any(isinstance(r, s) for s in (Failure, Error)):
                    status = CaseEvent.TEST_FAILED
                    break
                elif isinstance(r, Skipped):
                    status = CaseEvent.TEST_SKIPPED
            return status, stdout(case), stderr(case), case.time

        def attempt_result(elem) -> Tuple[int, str, str, float]:
            """
            One <flakyFailure>/<flakyError>/<rerunFailure>/<rerunError> attempt: always FAILED.
            Surefire doesn't record a separate duration for these, so duration is 0 (avoids
            double-counting the testcase's total time against final_result()'s duration).
            """
            def child_text(tag: str) -> Optional[str]:
                child = elem.find(tag)
                return child.text if child is not None and child.text else None

            attempt_stdout = child_text("system-out") or ""
            attempt_stderr = child_text("system-err") or child_text("stackTrace") or elem.attrib.get("message") or ""
            return CaseEvent.TEST_FAILED, attempt_stdout, attempt_stderr, 0.0

        rerun_elems = [c for c in case._elem if c.tag in RERUN_TAGS]
        flaky_elems = [c for c in case._elem if c.tag in FLAKY_TAGS]

        if rerun_elems:
            # failed on the first attempt and on every rerun
            attempts = [final_result()] + [attempt_result(e) for e in rerun_elems]
        elif flaky_elems:
            # failed on earlier attempts, passed on the last one
            attempts = [attempt_result(e) for e in flaky_elems] + [final_result()]
        else:
            # no reruns: unchanged, single-event behavior
            attempts = [final_result()]

        test_path = path_canonicalizer(path_builder(case, suite, report_file))
        data = data_builder(case)
        # One id per original <testcase>, shared by every attempt derived from it here, so
        # summarize_case_events can group retries correctly without relying on test_path.
        batch_id = uuid.uuid4()

        return [
            {
                **CaseEvent.create(
                    test_path=test_path,
                    duration_secs=attempt_duration,
                    status=attempt_status,
                    stdout=attempt_stdout,
                    stderr=attempt_stderr,
                    timestamp=suite.timestamp,
                    data=data,
                ),
                BATCH_ID_KEY: batch_id,
            }
            for attempt_status, attempt_stdout, attempt_stderr, attempt_duration in attempts
        ]

    @classmethod
    def create(cls, test_path: TestPath, duration_secs: float, status,
               stdout: Optional[str] = None, stderr: Optional[str] = None,
               timestamp: Optional[str] = None, data: Optional[Dict] = None) -> Dict:
        """
        Builds a JSON representation of CaseEvent from arbitrary set of values

        status:    TEST_FAILED or TEST_PASSED
        timestamp: the raw <testsuite timestamp> string, sent unresolved. The server owns timezone
                   resolution (see mothership TestTimestampResolver); the CLI holds no framework-TZ
                   knowledge. None when the runner emits no suite timestamp.
        data:      arbitrary data to be submitted to the server. reserved for future enhancement.
        """
        return {
            "type": cls.EVENT_TYPE,
            "testPath": test_path,
            "duration": duration_secs if duration_secs and duration_secs >= 0.0 else 0.0,
            "status": status,
            "stdout": stdout or "",
            "stderr": stderr or "",
            "junitSuiteTimestamp": timestamp,
            "data": data
        }


class MetadataTestCase(TestCase):
    line = IntAttr()
