import gzip
import json
import os
import tempfile
from unittest import TestCase, mock

import responses  # type: ignore

from smart_tests.test_runners.pytest import PytestJSONReportParser, _parse_pytest_nodeid
from tests.cli_test_case import CliTestCase


class PytestTest(CliTestCase):
    subset_input = '''tests/funcs3_test.py::test_func4
tests/funcs3_test.py::test_func5
tests/test_funcs1.py::test_func1
tests/test_funcs1.py::test_func2
tests/test_funcs2.py::test_func3
tests/test_funcs2.py::test_func4
tests/test_mod.py::TestClass::test__can_print_aaa
tests/fooo/func4_test.py::test_func6
tests/fooo/filenameonly_test.py

9 tests collected in 0.02s
'''

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_subset(self):
        result = self.cli('subset', 'pytest', '--target', '10%', '--session', self.session, input=self.subset_input)
        self.assert_success(result)

        payload = json.loads(gzip.decompress(self.find_request('/subset').request.body).decode())
        expected = self.load_json_from_file(self.test_files_dir.joinpath('subset_result.json'))
        for test_path in expected["testPaths"]:
            test_path[0]['name'] = os.path.normpath(test_path[0]['name'])
        self.assertEqual(expected, payload)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_record_test_pytest(self):
        result = self.cli('record', 'tests', 'pytest', '--session', self.session,
                          str(self.test_files_dir.joinpath("report.xml")))

        self.assert_success(result)
        self.assert_record_tests_payload('record_test_result.json')

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_record_test_with_json_option(self):
        result = self.cli('record', 'tests', 'pytest', '--session', self.session,
                          '--json', str(self.test_files_dir.joinpath("report.json")))

        self.assert_success(result)
        self.assert_record_tests_payload('record_test_result_json.json')

    def setUp(self):
        super().setUp()
        self.current_dir = os.getcwd()
        os.chdir(str(self.test_files_dir))

    def tearDown(self):
        os.chdir(self.current_dir)
        super().tearDown()

    def test_parse_pytest_nodeid(self):

        self.assertEqual(_parse_pytest_nodeid("tests/test_mod.py::TestClass::test__can_print_aaa"), [
            {"type": "file", "name": os.path.normpath("tests/test_mod.py")},
            {"type": "class", "name": "tests.test_mod.TestClass"},
            {"type": "testcase", "name": "test__can_print_aaa"},
        ])

        self.assertEqual(_parse_pytest_nodeid("tests/fooo/func4_test.py::test_func6"), [
            {"type": "file", "name": os.path.normpath(
                "tests/fooo/func4_test.py")},
            {"type": "class", "name": "tests.fooo.func4_test"},
            {"type": "testcase", "name": "test_func6"},
        ])

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_subset_preserves_parameter_id_containing_separator(self):
        nodeid = 'tests/test_mod.py::TestClass::test_value[left::right]'
        result = self.cli('subset', 'pytest', '--target', '10%', '--session', self.session,
                          input=nodeid + '\n\n')
        self.assert_success(result)
        payload = json.loads(gzip.decompress(self.find_request('/subset').request.body).decode())
        self.assertEqual(payload['testPaths'], [[
            {'type': 'file', 'name': os.path.normpath('tests/test_mod.py')},
            {'type': 'class', 'name': 'tests.test_mod.TestClass'},
            {'type': 'testcase', 'name': 'test_value[left::right]'},
        ]])


class PytestParameterIdTest(TestCase):
    def test_function_parameter_id_preserves_separator(self):
        self.assertEqual(_parse_pytest_nodeid('tests/test_mod.py::test_value[left::right]'), [
            {'type': 'file', 'name': os.path.normpath('tests/test_mod.py')},
            {'type': 'class', 'name': 'tests.test_mod'},
            {'type': 'testcase', 'name': 'test_value[left::right]'},
        ])

    def test_class_parameter_id_preserves_separators_and_brackets(self):
        self.assertEqual(_parse_pytest_nodeid('tests/test_mod.py::TestClass::test_value[a[::b]::c]'), [
            {'type': 'file', 'name': os.path.normpath('tests/test_mod.py')},
            {'type': 'class', 'name': 'tests.test_mod.TestClass'},
            {'type': 'testcase', 'name': 'test_value[a[::b]::c]'},
        ])

    def test_brackets_in_file_path_do_not_start_parameter_id(self):
        self.assertEqual(_parse_pytest_nodeid('tests/[group]/test_mod.py::TestClass::test_value'), [
            {'type': 'file', 'name': os.path.normpath('tests/[group]/test_mod.py')},
            {'type': 'class', 'name': 'tests.[group].test_mod.TestClass'},
            {'type': 'testcase', 'name': 'test_value'},
        ])

    def test_json_report_preserves_parameter_id(self):
        parser = PytestJSONReportParser(mock.Mock())
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'report.json')
            with open(path, 'w') as stream:
                stream.write(json.dumps({'nodeid': 'tests/test_mod.py::test_value[left::right]',
                                         'when': 'call', 'outcome': 'passed'}) + '\n')
            events = list(parser.parse_func(path))
        self.assertEqual(events[0]['testPath'][-1], {'type': 'testcase', 'name': 'test_value[left::right]'})


class PytestJSONReportParserLongreprTest(TestCase):
    class DummyClient:
        pass

    def setUp(self):
        self.parser = PytestJSONReportParser(self.DummyClient())

    def _parse_line(self, data):
        with tempfile.NamedTemporaryFile(mode="w+", delete=False) as f:
            f.write(json.dumps(data) + "\n")
            f.flush()
            results = list(self.parser.parse_func(f.name))
        return results

    def _make_event_data(self, longrepr):
        return {
            "nodeid": "tests/test_sample.py::test_fail",
            "when": "call",
            "outcome": "failed",
            "longrepr": longrepr,
        }

    def _assert_stderr(self, events, expected_stderr):
        self.assertEqual(events[0]["stderr"], expected_stderr)

    def test_longrepr_dict_message_and_text(self):
        data = self._make_event_data(
            {
                "reprcrash": {"message": "AssertionError: fail"},
                "reprtraceback": {
                    "reprentries": [{"data": {"lines": ["line1", "line2"]}}]
                },
            }
        )
        events = self._parse_line(data)
        self._assert_stderr(events, "AssertionError: fail\nline1\nline2")

    def test_longrepr_dict_only_message(self):
        data = self._make_event_data({"reprcrash": {"message": "Only message"}})
        events = self._parse_line(data)
        self._assert_stderr(events, "Only message")

    def test_longrepr_dict_only_text(self):
        data = self._make_event_data(
            {"reprtraceback": {"reprentries": [{"data": {"lines": ["text only"]}}]}}
        )
        events = self._parse_line(data)
        self._assert_stderr(events, "text only")

    def test_longrepr_list(self):
        data = self._make_event_data(["file.py", 10, "list message"])
        events = self._parse_line(data)
        self._assert_stderr(events, "list message")

    def test_longrepr_str(self):
        data = self._make_event_data("string message")
        events = self._parse_line(data)
        self._assert_stderr(events, "string message")
