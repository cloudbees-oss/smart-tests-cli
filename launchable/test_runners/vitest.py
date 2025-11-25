import xml.etree.ElementTree as ET

import click

from . import launchable


@click.argument('reports', required=True, nargs=-1)
@launchable.record.tests
def record_tests(client, reports):
    def parse_func(report: str) -> ET.ElementTree:
        """
        Vitest junit report doesn't set file/filepath attributes on test cases, and it's set as a classname attribute instead.
        So, set the classname value as the file name in this function.
        e.g.) <testcase classname="src/components/Hello.test.tsx" name="renders hello message" time="0.008676833">
          """
        tree = ET.parse(report)
        root = tree.getroot()
        for test_suite in root.findall('testsuite'):
            for test_case in test_suite.findall('testcase'):
                classname = test_case.get('classname', '')
                test_case.set('file', classname)
                test_case.attrib.pop('classname', None)

        return tree

    client.junitxml_parse_func = parse_func
    launchable.CommonRecordTestImpls.load_report_files(client=client, source_roots=reports)


subset = launchable.CommonSubsetImpls(__name__).scan_files()
