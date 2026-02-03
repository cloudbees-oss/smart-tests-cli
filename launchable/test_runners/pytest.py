import glob
import json
import os
import pathlib
import subprocess
from enum import Enum
from typing import Generator, List

import click
from junitparser import Properties, TestCase  # type: ignore

from launchable.commands.record.case_event import CaseEvent, CaseEventType, MetadataTestCase
from launchable.testpath import TestPath

from . import launchable


# Please specify junit_family=legacy for pytest report format. if using pytest version 6 or higher.
# - pytest has changed its default test report format from xunit1 to xunit2 since version 6.
#     - https://docs.pytest.org/en/latest/deprecations.html#junit-family-default-value-change-to-xunit2
# - The xunit2 format no longer includes file names.
#     - It is possible to output in xunit1 format by specifying junit_family=legacy.
#     - The xunit1 format includes the file name.
# The format of pytest changes depending on the existence of the class. They are also incompatible with
# the junit format.
# Therefore, it converts to junit format at the timing of sending the subset, and converts the returned
# value to pytest format.
# for Example
# $ pytest --collect-only -q
# > tests/test_mod.py::TestClass::test__can_print_aaa
# > tests/fooo/func4_test.py::test_func6
# >
# > 2 tests collected in 0.02s
# result.xml(junit)
# <testcase classname="tests.fooo.func4_test" name="test_func6" file="tests/fooo/func4_test.py"
# line="0" time="0.000" />
# <testcase classname="tests.test_mod.TestClass" name="test__can_print_aaa" file="tests/test_mod.py"
# line="3" time="0.001" />
#
@click.argument('source_roots', required=False, nargs=-1)
@launchable.subset
def subset(client, source_roots: List[str]):
    def _add_testpaths(lines: List[str]):
        for line in lines:
            line = line.rstrip()
            # When an empty line comes, it's done.
            if not line:
                break

            test_path = _parse_pytest_nodeid(line)
            client.test_path(test_path)
    if not source_roots:
        _add_testpaths(client.stdin())
    else:
        command = ["pytest", "--collect-only", "-q"]
        command.extend(source_roots)
        try:
            result = subprocess.run(command, stdout=subprocess.PIPE, universal_newlines=True)
            _add_testpaths(result.stdout.split(os.linesep))
        except FileNotFoundError:
            raise click.ClickException("pytest command not found. Please check the path.")

    client.formatter = _pytest_formatter
    client.run()


def _parse_pytest_nodeid(nodeid: str) -> TestPath:
    data = nodeid.split("::")
    file = data[0]
    class_name = _path_to_class_name(file)
    normalized_file = os.path.normpath(file)

    # file name only
    if len(data) == 1:
        return [
            {"type": "file", "name": normalized_file},
            {"type": "class", "name": class_name},
        ]
    # file + testcase, or file + class + testcase
    else:
        testcase = data[-1]
        if len(data) == 3:
            class_name += "." + data[1]

        return [
            {"type": "file", "name": normalized_file},
            {"type": "class", "name": class_name},
            {"type": "testcase", "name": testcase},
        ]


def _path_to_class_name(path):
    '''
    tests/fooo/func4_test.py -> tests.fooo.func4_test
    '''
    return os.path.splitext(os.path.normpath(path))[0].replace(os.sep, ".")


def _pytest_formatter(test_path):
    for path in test_path:
        t = path.get('type', '')
        n = path.get('name', '')
        if t == 'class':
            cls_name = n
        elif t == 'testcase':
            case = n
        elif t == 'file':
            file = n
    # If there is no class, junitformat use package name, but pytest will be omitted
    # pytest -> tests/fooo/func4_test.py::test_func6
    # junitformat -> <testcase classname="tests.fooo.func4_test"
    # name="test_func6" file="tests/fooo/func4_test.py" line="0" time="0.000"
    # />
    if cls_name == _path_to_class_name(file):
        return "{}::{}".format(file, case)

    else:
        # junitformat's class name includes package, but pytest does not
        # pytest -> tests/test_mod.py::TestClass::test__can_print_aaa
        # junitformat -> <testcase classname="tests.test_mod.TestClass"
        # name="test__can_print_aaa" file="tests/test_mod.py" line="3"
        # time="0.001" />
        return "{}::{}::{}".format(file, cls_name.split(".")[-1], case)


split_subset = launchable.CommonSplitSubsetImpls(__name__, formatter=_pytest_formatter).split_subset()


class ReportKind(Enum):
    JSON = 0
    XML = 1


def _parse_markers(props: List, kind: ReportKind) -> List[dict]:
    """
    Parse marker properties from either XML properties or JSON user_properties format.
    """
    markers = []
    marker = {}

    for prop in props:
        if kind == ReportKind.JSON:
            # JSON format: prop is a list like ["name", "value"]
            if not isinstance(prop, list) or len(prop) != 2:
                continue
            prop_name, prop_value = prop[0], prop[1]
        else:
            # XML format: prop has .name and .value attributes
            prop_name, prop_value = prop.name, prop.value

        if prop_name == "name":
            marker["name"] = prop_value
        elif prop_name == "args":
            if isinstance(prop_value, str):
                if prop_value not in ("()", "{}"):
                    marker["value"] = prop_value
            else:
                if prop_value not in ((), {}):
                    marker["value"] = json.dumps(prop_value)
        elif prop_name == "kwargs":
            if isinstance(prop_value, str):
                if prop_value not in ("()", "{}"):
                    marker["value"] = prop_value
            else:
                if prop_value not in ((), {}):
                    marker["value"] = json.dumps(prop_value)
            if "value" not in marker:
                marker["value"] = ""
            markers.append(marker)
            marker = {}

    return markers


@click.option('--json', 'json_report', help="use JSON report files produced by pytest-dev/pytest-reportlog",
              is_flag=True)
@click.argument('source_roots', required=True, nargs=-1)
@launchable.record.tests
def record_tests(client, json_report, source_roots):

    def data_builder(case: TestCase):
        props = case.child(Properties)
        result = {}
        if props is not None:
            """
                Here is an example of an XML file with markers.
                ```
                    <properties>
                        <property name="name" value="parametrize" />
                        <property name="args" value="('y', [2, 3])" />
                        <property name="kwargs" value="{}" />
                        <property name="name" value="parametrize" />
                        <property name="args" value="('x', [0, 1])" />
                        <property name="kwargs" value="{}" />
                    </properties>
                ```
            """
            markers = _parse_markers(props, kind=ReportKind.XML)
            result["markers"] = markers if markers else []

        metadata = MetadataTestCase.fromelem(case)
        if metadata and metadata.line is not None:
            # Please note that line numbers start from 0.
            # https://github.com/pytest-dev/pytest/blob/8.1.1/src/_pytest/_code/source.py#L93
            result["lineNumber"] = metadata.line + 1
        return result

    ext = "json" if json_report else "xml"
    for root in source_roots:
        match = False
        for t in glob.iglob(root, recursive=True):
            match = True
            if os.path.isdir(t):
                client.scan(t, "*.{}".format(ext))
            else:
                client.report(t)

        if not match:
            click.echo("No matches found: {}".format(root), err=True)
            return

    if json_report:
        client.parse_func = PytestJSONReportParser(client).parse_func

    client.metadata_builder = data_builder

    client.run()


"""
If you want to use --json option, please install pytest-dev/pytest-reportlog.
(https://github.com/pytest-dev/pytest-reportlog)

Usage

```
$ pip install -U pytest-reportlog
$ pytest --report-log report.json
$ launchable record tests --json report.json
```
"""


class PytestJSONReportParser:
    def __init__(self, client):
        self.client = client

    def parse_func(
            self, report_file: str) -> Generator[CaseEventType, None, None]:
        with open(report_file, 'r') as json_file:
            for line in json_file:
                try:
                    data = json.loads(line)
                except Exception as e:
                    raise Exception("Can't read JSON format report file {}. Make sure to confirm report file.".format(
                        report_file)) from e

                nodeid = data.get("nodeid", "")
                if nodeid == "":
                    continue

                when = data.get("when", "")
                outcome = data.get("outcome", "")

                if not (when == "call" or (when == "setup" and outcome == "skipped")):
                    continue

                status = CaseEvent.TEST_FAILED
                if outcome == "passed":
                    status = CaseEvent.TEST_PASSED
                elif outcome == "skipped":
                    status = CaseEvent.TEST_SKIPPED

                """example json
                  "longrepr": {
                    "reprcrash": {
                        "lineno": 6,
                        "message": "assert 1 == False",
                        "path": "/Users/yabuki-ryosuke/src/github.com/launchableinc/cli/tests/data/pytest/tests/test_funcs1.py"
                        },
                    "reprtraceback": {
                    "extraline": null,
                    "reprentries": [
                        {
                        "data": {
                            "lines": [
                            "    def test_func2():",
                            ">       assert 1 == False",
                            "E       assert 1 == False"
                            ],
                            "reprfileloc": {
                            "lineno": 6,
                            "message": "AssertionError",
                            "path": "tests/test_funcs1.py"
                            },
                            "reprfuncargs": {
                            "args": []
                            },
                            "reprlocals": null,
                            "style": "long"
                        },
                        "type": "ReprEntry"
                        }
                    ],
                    "style": "long"
                    },
                    "sections": []
                  }
                """
                stdout = ""
                stderr = ""
                longrepr = data.get("longrepr", None)
                if longrepr:
                    # https://github.com/pytest-dev/pytest/blob/1d7d63555e431d4562bcacbdc97038b0613d20ba/src/_pytest/reports.py#L60
                    if isinstance(longrepr, dict):
                        # https://github.com/pytest-dev/pytest/blob/1d7d63555e431d4562bcacbdc97038b0613d20ba/src/_pytest/reports.py#L361
                        message = None
                        reprcrash = longrepr.get("reprcrash", None)
                        if reprcrash:
                            message = reprcrash.get("message", None)

                        text = None
                        reprtraceback = longrepr.get("reprtraceback", None)
                        if reprtraceback:
                            reprentries = reprtraceback.get("reprentries", None)
                            if reprentries:
                                for r in reprentries:
                                    d = r.get("data", None)
                                    if d:
                                        text = "\n".join(d.get("lines", []))

                        if message and text:
                            stderr = message + "\n" + text
                        elif message:
                            stderr = stderr + message
                        elif text:
                            stderr = stderr + text
                    elif isinstance(longrepr, list):
                        # [path, lineno, messge]
                        # https://github.com/pytest-dev/pytest/blob/1d7d63555e431d4562bcacbdc97038b0613d20ba/src/_pytest/reports.py#L371
                        if len(longrepr) == 3:
                            stderr = longrepr[2]

                    elif isinstance(longrepr, str):
                        # When longrepr is a string, it is the same as the stderr.
                        # https://github.com/pytest-dev/pytest/blob/1d7d63555e431d4562bcacbdc97038b0613d20ba/src/_pytest/reports.py#L377
                        # https://github.com/pytest-dev/pytest/blob/1d7d63555e431d4562bcacbdc97038b0613d20ba/src/_pytest/nodes.py#L470
                        stderr = longrepr

                """example json
                "user_properties": [
                    ["name", "dependency"],
                    ["args", []],
                    ["kwargs", { "name": "c", "depends": ["a"] }],
                    ["name", "order"],
                    ["args", [2]],
                    ["kwargs", {}]
                ]
                """
                props = data.get('user_properties')
                if isinstance(props, list):
                    markers = _parse_markers(props, kind=ReportKind.JSON)
                    if len(props) > 0:
                        props = {'markers': markers}
                    else:
                        props = None

                test_path = _parse_pytest_nodeid(nodeid)
                for path in test_path:
                    if path.get("type") == "file":
                        path["name"] = pathlib.Path(path["name"]).as_posix()

                yield CaseEvent.create(
                    test_path=test_path,
                    duration_secs=data.get("duration", 0),
                    status=status,
                    stdout=stdout,
                    stderr=stderr,
                    data=props)
