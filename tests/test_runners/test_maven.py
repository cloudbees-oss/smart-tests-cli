import os
import shutil
import tempfile
from unittest import mock

import responses  # type: ignore
from junitparser import JUnitXml  # type: ignore

from smart_tests.commands.record.case_event import CaseEvent
from smart_tests.test_runners import maven
from smart_tests.testpath import FilePathNormalizer
from smart_tests.utils.java import junit5_nested_class_path_builder
from tests.cli_test_case import CliTestCase


class MavenTest(CliTestCase):
    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_subset(self):
        result = self.cli('subset', 'maven', '--session', self.session, '--target', '10%',
                          str(self.test_files_dir.joinpath('java/test/src/java/').resolve()))
        self.assert_success(result)
        self.assert_subset_payload('subset_result.json')

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_subset_from_file(self):
        # if we prepare listed file with slash e.g) com/example/launchable/model/aModelATest.class
        # the test will be failed at Windows environment. So, we generate file
        # path list
        def save_file(list, file_name):
            file = str(self.test_files_dir.joinpath(file_name))
            with open(file, 'w+') as file:
                for test_class in list:
                    file.write(test_class.replace(".", os.path.sep) + ".class\n")

        list_1 = ["com.example.sampleapp.model.a.ModelATest",
                  "com.example.sampleapp.model.b.ModelBTest",
                  "com.example.sampleapp.model.b.ModelBTest$SomeInner",
                  "com.example.sampleapp.model.c.ModelCTest",

                  ]

        list_2 = ["com.example.sampleapp.service.ServiceATest",
                  "com.example.sampleapp.service.ServiceATest$Inner1$Inner2",
                  "com.example.sampleapp.service.ServiceBTest",
                  "com.example.sampleapp.service.ServiceCTest",
                  ]

        save_file(list_1, "createdFile_1.lst")
        save_file(list_2, "createdFile_2.lst")

        result = self.cli('subset', 'maven', '--session', self.session, '--target', '10%',
                          "--test-compile-created-file",
                          str(self.test_files_dir.joinpath("createdFile_1.lst")),
                          "--test-compile-created-file",
                          str(self.test_files_dir.joinpath("createdFile_2.lst")))
        self.assert_success(result)
        self.assert_subset_payload('subset_from_file_result.json')

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_scan_test_compile_lst(self):

        list = [
            "com.example.sampleapp.service.ServiceATest",
            "com.example.sampleapp.service.ServiceATest$Inner1$Inner2",
            "com.example.sampleapp.service.ServiceBTest",
            "com.example.sampleapp.service.ServiceCTest",
        ]

        base_tmp_dir = os.path.join(".", "tmp-maven-scan/")

        os.makedirs(base_tmp_dir, exist_ok=True)
        temp_dir = tempfile.mkdtemp(dir=base_tmp_dir)
        os.makedirs(os.path.join(temp_dir, 'testCompile', 'default-testCompile'), exist_ok=True)

        file = os.path.join(temp_dir, 'testCompile', 'default-testCompile', 'createdFiles.lst')
        with open(file, 'w+') as file:
            for test_class in list:
                file.write(test_class.replace(".", os.path.sep) + ".class\n")

        result = self.cli('subset', 'maven', '--session', self.session, '--target', '10%', "--scan-test-compile-lst")
        # clean up test directory
        shutil.rmtree(base_tmp_dir)

        self.assert_success(result)
        self.assert_subset_payload('subset_scan_test_compile_lst_result.json')

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_subset_by_absolute_time(self):
        result = self.cli('subset', 'maven', '--session', self.session, '--time', '1h30m',
                          str(self.test_files_dir.joinpath('java/test/src/java/').resolve()))
        self.assert_success(result)
        self.assert_subset_payload('subset_by_absolute_time_result.json')

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_subset_by_confidence(self):
        result = self.cli('subset', 'maven', '--session', self.session, '--confidence', '90%',
                          str(self.test_files_dir.joinpath('java/test/src/java/').resolve()))
        self.assert_success(result)
        self.assert_subset_payload('subset_by_confidence_result.json')

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_record_test_maven(self):
        result = self.cli('record', 'tests', 'maven', '--session', self.session, str(self.test_files_dir) + "/**/reports")
        self.assert_success(result)
        self.assert_record_tests_payload("record_test_result.json")

    def _build_path_builder(self):
        """Builds the same wrapped path_builder that maven.py's record_tests wires up."""
        default_path_builder = CaseEvent.default_path_builder(FilePathNormalizer())
        return junit5_nested_class_path_builder(default_path_builder)

    def _class_path_for_first_case(self, report_path):
        path_builder = self._build_path_builder()
        xml = JUnitXml.fromfile(str(self.test_files_dir.joinpath(report_path)))
        suite = next(iter(xml))
        case = next(iter(suite))
        test_path = path_builder(case, suite, str(report_path))
        return next(item["name"] for item in test_path if item["type"] == "class")

    def test_junit5_nested_class_path_builder_strips_dollar_suffix(self):
        """@Nested class WITHOUT @DisplayName: Surefire keeps "Outer$Inner" as classname."""
        class_name = self._class_path_for_first_case('reports/TEST-nested.xml')
        self.assertEqual(class_name, "com.example.sample_app_maven.NestedTest")
        self.assertNotIn("$", class_name)

    def test_junit5_nested_class_path_builder_falls_back_to_suite_name(self):
        """@Nested class WITH @DisplayName: Surefire (>= ~3.5.x) drops the outer class from
        `classname` entirely (e.g. classname="addFollowList"). We must fall back to the
        enclosing <testsuite name="..."> attribute, which is always the outer class FQCN."""
        class_name = self._class_path_for_first_case('reports-nested-displayname/TEST-nested-displayname.xml')
        self.assertEqual(class_name, "com.example.sample_app_maven.NestedDisplayNameTest")
        self.assertNotIn("$", class_name)
        self.assertNotEqual(class_name, "addFollowList")

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_record_test_maven_with_nested_class(self):
        """Verify that class names containing $ (inner class marker) are processed correctly during test recording"""
        result = self.cli('record', 'tests', 'maven', '--session', self.session,
                          str(self.test_files_dir.joinpath('reports/TEST-1.xml')),
                          str(self.test_files_dir.joinpath('reports/TEST-2.xml')),
                          str(self.test_files_dir.joinpath('reports/TEST-nested.xml')))
        self.assert_success(result)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_record_test_maven_with_nested_displayname_class(self):
        """Verify the bare-@DisplayName-as-classname bug (no dot, no $) is corrected end-to-end."""
        result = self.cli('record', 'tests', 'maven', '--session', self.session,
                          str(self.test_files_dir.joinpath('reports-nested-displayname/TEST-nested-displayname.xml')))
        self.assert_success(result)
        self.assert_record_tests_payload("record_test_nested_displayname_result.json")

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_subset_with_exclude(self):
        # Invalid regexp case
        result = self.cli('subset', '--target', '10%', '--session',
                          self.session, 'maven',
                          '--exclude', r'[invalid',
                          str(self.test_files_dir.joinpath('java/test/src/java/').resolve()))
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Invalid regular expression", result.output)

        # Success case
        result = self.cli('subset', '--target', '10%', '--session',
                          self.session, 'maven',
                          '--exclude', r'\.e2e\.',
                          str(self.test_files_dir.joinpath('java/test/src/java/').resolve()))
        self.assert_success(result)
        self.assert_subset_payload('subset_with_exclude_rules_result.json')

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_scan_dryrun_results(self):
        # Reports live under <dryrun-test>/target/surefire-reports/. The flag globs
        # **/target/surefire-reports/TEST-*.xml relative to the cwd, so run from there.
        test_data_dir = str(self.test_files_dir.joinpath('dryrun-test').resolve())
        original_dir = os.getcwd()
        try:
            os.chdir(test_data_dir)
            result = self.cli('subset', '--target', '10%', '--session',
                              self.session, 'maven', '--scan-dryrun-results')
            self.assert_success(result)
            self.assert_subset_payload('subset_scan_dryrun_results_result.json')
        finally:
            os.chdir(original_dir)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_scan_dryrun_results_no_reports(self):
        original_dir = os.getcwd()
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                os.chdir(temp_dir)
                result = self.cli('subset', '--target', '10%', '--session',
                                  self.session, 'maven', '--scan-dryrun-results')
                self.assertNotEqual(result.exit_code, 0)
                self.assertIn("No surefire reports found", result.output)
            finally:
                os.chdir(original_dir)

    def test_glob(self):
        for x in [
            'foo/BarTest.java',
            'foo/BarTest.class',
            'FooTest.class',
            'TestFoo.class',
        ]:
            self.assertTrue(maven.is_file(x))

        for x in [
            'foo/Bar$Test.class',
            'foo/MyTest$Inner.class',
            'foo/Util.class',
        ]:
            self.assertFalse(maven.is_file(x))
