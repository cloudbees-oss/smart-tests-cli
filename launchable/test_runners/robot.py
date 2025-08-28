from datetime import datetime
from xml.etree import ElementTree as ET

import click
from junitparser import JUnitXml  # type: ignore

from ..testpath import TestPath
from . import launchable


def parse_func(p: str) -> ET.ElementTree:

    def parse_suite(suite: ET.Element):
        DATETIME_FORMAT = '%Y%m%d %H:%M:%S.%f'

        suite_name = suite.get('name')
        for test in suite.iter("test"):
            test_name = test.get('name')

            status_node = test.find('status')
            status = status_node.get(
                'status') if status_node is not None else None

            nested_status_node = test.find('./kw/status')
            nested_status = nested_status_node.get('status') if nested_status_node is not None else None

            if status is not None:
                start_time_str = status_node.get('starttime') if status_node is not None else ''
                end_time_str = status_node.get('endtime') if status_node is not None else ''

                if start_time_str != '' and end_time_str != '':
                    start_time = datetime.strptime(str(start_time_str), DATETIME_FORMAT)
                    end_time = datetime.strptime(str(end_time_str), DATETIME_FORMAT)

                    duration = end_time - start_time

                testcase = ET.SubElement(testsuite, "testcase", {
                    "name": str(test_name),
                    "classname": str(suite_name),
                    "time": str(duration.total_seconds()) if duration is not None else '0',
                })

                if status_node is not None:
                    out = ET.SubElement(testcase, 'system-out')
                    out.text = status_node.text if status_node.text else ''

                if status == "FAIL":
                    failure = ET.SubElement(testcase, 'failure')

                    msgs = []
                    for msg in test.findall('kw/msg'):
                        if msg is not None and msg.text is not None:
                            msgs.append(msg.text)
                    failure.text = "\n".join(msgs) if msgs else ''
                if status == "NOT_RUN" or nested_status == 'NOT_RUN':
                    skipped = ET.SubElement(testcase, "skipped")  # noqa: F841

    original_tree = ET.parse(p)
    testsuite = ET.Element("testsuite", {"name": "robot"})

    SUITE_TAG_NAME = "suite"
    for suites in original_tree.findall(SUITE_TAG_NAME):
        nested_suites = suites.findall(SUITE_TAG_NAME)

        if nested_suites:
            # Run tests in a directory
            for suite in nested_suites:
                parse_suite(suite)
        else:
            # Run tests in a single file
            parse_suite(suites)

    return ET.ElementTree(testsuite)


@click.argument('reports', required=True, nargs=-1)
@launchable.record.tests
def record_tests(client, reports):
    for r in reports:
        client.report(r)

    client.junitxml_parse_func = parse_func
    client.run()


@click.argument('reports', required=True, nargs=-1)
@launchable.subset
def subset(client, reports):
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


@launchable.split_subset
def split_subset(client):
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
        return "-s '{}' -t '{}'".format(cls_name, case)

    return ''
