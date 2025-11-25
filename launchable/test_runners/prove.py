import re

import click
from junitparser import TestCase, TestSuite  # type: ignore

from ..testpath import TestPath
from . import launchable

TEARDOWN = "(teardown)"


def remove_leading_number_and_dash(input_string: str) -> str:
    result = re.sub(r'^\d+ - ', '', input_string)
    return result


subset = launchable.CommonSubsetImpls(__name__).scan_files()

@click.argument('reports', required=True, nargs=-1)
@launchable.record.tests
def record_tests(client, reports):
    def path_builder(case: TestCase, suite: TestSuite,
                     report_file: str) -> TestPath:
        def find_filename():
            # find file path from test suite attribute first.
            filepath = suite._elem.attrib.get("name")
            if filepath:
                return filepath
            # find file path from test case attribute.
            filepath = case._elem.attrib.get("classname")
            if filepath:
                return filepath
            return None  # failing to find a test name

        filepath = find_filename()
        if not filepath:
            raise click.ClickException(
                "No file name found in %s."
                "Perl prove profile is made to take Junit report produced by "
                "TAP::Formatter::JUnit (https://github.com/bleargh45/TAP-Formatter-JUnit), "
                "which exports the report in stdout."
                "Please export the stdout result to XML report file."
                "If you are not using TAP::Formatter::JUnit, "
                "please change your reporting to TAP::Formatter::JUnit." % report_file)

        # default test path in `subset` expects to have this file name
        test_path = [client.make_file_path_component(filepath)]
        if case.name:
            case_name = remove_leading_number_and_dash(input_string=case.name)
            test_path.append({"type": "testcase", "name": case_name})
        return test_path

    client.path_builder = path_builder

    for r in reports:
        client.report(r)
    client.run()


split_subset = launchable.CommonSplitSubsetImpls(__name__).split_subset()
