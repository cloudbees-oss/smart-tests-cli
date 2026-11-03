from datetime import datetime
from typing import Annotated, List, Optional
from xml.etree import ElementTree as ET

from junitparser import JUnitXml  # type: ignore

import smart_tests.args4p.typer as typer

from ..commands.record.tests import RecordTests
from ..commands.subset import Subset
from ..testpath import TestPath
from . import smart_tests


def parse_func(p: str) -> ET.ElementTree:
    DATETIME_FORMAT = '%Y%m%d %H:%M:%S.%f'

    def suite_timestamp(suite: ET.Element) -> Optional[str]:
        """The suite's start time as an ISO-8601 naive string, or None if absent.

        Robot records a naive, local wall-clock start (e.g. '20210319 11:34:50.085',
        no timezone). The server owns timezone resolution (naive -> agent-local);
        the CLI only normalizes the shape to ISO-8601.
        """
        status = suite.find('status')
        if status is None:
            return None
        # RF 7.0+: already-ISO 'start' attribute; hand it over untouched.
        iso_start = status.get('start')
        if iso_start:
            return iso_start
        raw = status.get('starttime')
        if not raw:
            return None
        try:
            return datetime.strptime(raw, DATETIME_FORMAT).isoformat()
        except ValueError:
            return None

    def parse_suite(suite: ET.Element, testsuite: ET.Element):
        suite_name = suite.get('name')
        for test in suite.iter("test"):
            test_name = test.get('name')

            status_node = test.find('status')
            status = status_node.get(
                'status') if status_node is not None else None

            nested_status_node = test.find('./kw/status')
            nested_status = nested_status_node.get('status') if nested_status_node is not None else None

            if status is not None:
                duration_seconds = None

                if status_node is not None:
                    # RF 7.0+: elapsed attribute in seconds
                    elapsed_str = status_node.get('elapsed')
                    if elapsed_str is not None:
                        duration_seconds = float(elapsed_str)
                    else:
                        # RF < 7.0: starttime/endtime attributes
                        start_time_str = status_node.get('starttime', '')
                        end_time_str = status_node.get('endtime', '')
                        if start_time_str and end_time_str:
                            try:
                                start_time = datetime.strptime(start_time_str, DATETIME_FORMAT)
                                end_time = datetime.strptime(end_time_str, DATETIME_FORMAT)
                                duration_seconds = (end_time - start_time).total_seconds()
                            except ValueError:
                                duration_seconds = 0

                testcase = ET.SubElement(testsuite, "testcase", {
                    "name": str(test_name),
                    "classname": str(suite_name),
                    "time": str(duration_seconds) if duration_seconds is not None else '0',
                })

                if status == "FAIL":
                    failure = ET.SubElement(testcase, 'failure')

                    msg = test.find('kw/msg')
                    failure.text = msg.text if msg is not None else ''
                if status == "NOT_RUN" or nested_status == 'NOT_RUN':
                    skipped = ET.SubElement(testcase, "skipped")  # noqa: F841

    def find_leaf_suites(suite: ET.Element):
        nested = suite.findall(SUITE_TAG_NAME)
        if not nested:
            return [suite]
        leaves = []
        for child in nested:
            leaves.extend(find_leaf_suites(child))
        return leaves

    original_tree = ET.parse(p)
    testsuites = ET.Element("testsuites")

    SUITE_TAG_NAME = "suite"
    for top_suite in original_tree.findall(SUITE_TAG_NAME):
        for leaf_suite in find_leaf_suites(top_suite):
            attribs = {"name": str(leaf_suite.get('name'))}
            timestamp = suite_timestamp(leaf_suite)
            if timestamp:
                attribs["timestamp"] = timestamp
            testsuite = ET.SubElement(testsuites, "testsuite", attribs)
            parse_suite(leaf_suite, testsuite)

    return ET.ElementTree(testsuites)


@smart_tests.record.tests
def record_tests(
    client: RecordTests,
    reports: Annotated[List[str], typer.Argument(
        multiple=True,
        help="Test report files to process"
    )],
):
    for r in reports:
        client.report(r)

    client.junitxml_parse_func = parse_func
    client.run()


@smart_tests.subset
def subset(
    client: Subset,
    reports: Annotated[List[str], typer.Argument(
        multiple=True,
        required=False,
        help="Test report files to process"
    )] = [],
):
    for r in reports:
        xml = JUnitXml.fromfile(r, parse_func)

        for suite in xml:
            for case in suite:
                cls_name = case._elem.attrib.get("classname")
                name = case._elem.attrib.get('name')
                if cls_name != '' and name != '':
                    client.test_path([{'type': 'class', 'name': cls_name}, {'type': 'testcase', 'name': name}])

    client.formatter = robot_formatter
    client.separator = " "
    client.run()


def robot_formatter(x: TestPath):
    cls_name = ''
    case = ''
    for path in x:
        t = path['type']
        if t == 'class':
            cls_name = path['name']
        if t == 'testcase':
            case = path['name']

    if cls_name != '' and case != '':
        return f"-s '{cls_name}' -t '{case}'"

    return ''
