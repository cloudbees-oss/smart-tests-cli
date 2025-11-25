import glob
import os
import sys
import types

import click
from junitparser import TestCase, TestSuite  # type: ignore

from launchable.commands.detect_flakes import detect_flakes as detect_flakes_cmd
from launchable.commands.record.tests import tests as record_tests_cmd
from launchable.commands.split_subset import split_subset as split_subset_cmd
from launchable.commands.subset import subset as subset_cmd

from ..testpath import TestPath


def cmdname(m):
    """figure out the sub-command name from a test runner function"""

    # a.b.cde -> cde
    # xyz -> xyz
    #
    # In python module name the conventional separator is '_' but in command name,
    # it is '-', so we do replace that
    return m[m.rfind('.') + 1:].replace('_', '-')


def wrap(f, group, name=None):
    """
    Wraps a 'plugin' function into a click command and registers it to the given group.

    a plugin function receives the scanner object in its first argument
    """
    if not name:
        name = cmdname(f.__module__)
    d = click.command(name=name)
    cmd = d(click.pass_obj(f))
    group.add_command(cmd)
    return cmd


def subset(f):
    return wrap(f, subset_cmd)


record = types.SimpleNamespace()
record.tests = lambda f: wrap(f, record_tests_cmd)


def flake_detection(f):
    return wrap(f, detect_flakes_cmd)


def split_subset(f):
    return wrap(f, split_subset_cmd)


class CommonSubsetImpls:
    """
    Typical 'subset' implementations that are reusable.
    """

    def __init__(self, module_name):
        self.cmdname = cmdname(module_name)

    def scan_files(self, pattern=None):
        """
        Suitable for test runners that use files as unit of tests where file names follow a naming pattern.

        :param pattern: file masks that identify test files, such as '*_spec.rb'
                        for test runners that do not have natural file naming conventions, pass in None,
                        so that the implementation will refuse to accept directories.
        """
        @click.argument('files', required=True, nargs=-1)
        def subset(client, files):
            # client type: Optimize in def lauchable.commands.subset.subset
            def parse(fname: str):
                if os.path.isdir(fname):
                    if pattern is None:
                        raise click.UsageError(f'{fname} is a directory, but expecting a file or GLOB')
                    client.scan(fname, '**/' + pattern)
                elif fname == '@-':
                    # read stdin
                    for l in sys.stdin:
                        parse(l.rstrip())
                elif fname.startswith('@'):
                    # read response file
                    with open(fname[1:]) as f:
                        for l in f:
                            parse(l.rstrip())
                else:
                    # assume it's a file
                    client.test_path(fname)

            for f in files:
                parse(f)

            client.run()
        return wrap(subset, subset_cmd, self.cmdname)


class CommonRecordTestImpls:
    """
    Typical 'record tests' implementations that are reusable.
    """

    def __init__(self, module_name):
        self.cmdname = cmdname(module_name)

    def report_files(self, file_mask="*.xml"):
        """
        Suitable for test runners that create a directory full of JUnit report files.

        'record tests' expect JUnit report/XML file names.
        """

        @click.argument('source_roots', required=True, nargs=-1)
        def record_tests(client, source_roots):
            CommonRecordTestImpls.load_report_files(client=client, source_roots=source_roots, file_mask=file_mask)

        return wrap(record_tests, record_tests_cmd, self.cmdname)

    def file_profile_report_files(self):
        """
        Suitable for test runners that create a directory full of JUnit report files.

        'record tests' expect JUnit report/XML file names.
        """

        @click.argument('source_roots', required=True, nargs=-1)
        def record_tests(client, source_roots):
            def path_builder(
                case: TestCase, suite: TestSuite, report_file: str
            ) -> TestPath:
                def find_filename():
                    """look for what looks like file names from test reports"""
                    for e in [case, suite]:
                        for a in ["file", "filepath"]:
                            filepath = e._elem.attrib.get(a)
                            if filepath:
                                return filepath
                    return None  # failing to find a test name

                filepath = find_filename()
                if not filepath:
                    raise click.ClickException("No file name found in %s" % report_file)

                # default test path in `subset` expects to have this file name
                test_path = [client.make_file_path_component(filepath)]
                if suite.name:
                    test_path.append({"type": "testsuite", "name": suite.name})
                if case.name:
                    test_path.append({"type": "testcase", "name": case.name})
                return test_path

            client.path_builder = path_builder

            for r in source_roots:
                client.report(r)
            client.run()

        return wrap(record_tests, record_tests_cmd, self.cmdname)

    @classmethod
    def load_report_files(cls, client, source_roots, file_mask="*.xml"):
        # client type: RecordTests in def launchable.commands.record.tests.tests
        # Accept both file names and GLOB patterns
        # Simple globs like '*.xml' can be dealt with by shell, but
        # not all shells consistently deal with advanced GLOBS like '**'
        # so it's worth supporting it here.
        for root in source_roots:
            match = False
            for t in glob.iglob(root, recursive=True):
                match = True
                if os.path.isdir(t):
                    client.scan(t, file_mask)
                else:
                    client.report(t)

            if not match:
                # By following the shell convention, if the file doesn't exist or GLOB doesn't match anything,
                # raise it as an error. Note this can happen for reasons other than a configuration error.
                # For example, if a build catastrophically failed and no
                # tests got run.
                click.echo("No matches found: {}".format(root), err=True)
                # intentionally exiting with zero
                return

        client.run()


class CommonSplitSubsetImpls:
    def __init__(
            self,
            module_name,
            formatter=None,
            seperator=None,
            same_bin_formatter=None,
    ):
        self.cmdname = cmdname(module_name)
        self._formatter = formatter
        self._separator = seperator
        self._same_bin_formatter = same_bin_formatter

    def split_subset(self):
        def split_subset(client):
            # client type: SplitSubset in def
            # lauchable.commands.split_subset.split_subset
            if self._formatter:
                client.formatter = self._formatter

            if self._separator:
                client.separator = self._separator

            if self._same_bin_formatter:
                client.same_bin_formatter = self._same_bin_formatter

            client.run()

        return wrap(split_subset, split_subset_cmd, self.cmdname)


class CommonFlakeDetectionImpls:
    def __init__(
            self,
            module_name,
            formatter=None,
            seperator="\n",
    ):
        self.cmdname = cmdname(module_name)
        self._formatter = formatter
        self._separator = seperator

    def detect_flakes(self):
        def detect_flakes(client):
            if self._formatter:
                client.formatter = self._formatter

            if self._separator:
                client.separator = self._separator

            client.run()

        return wrap(detect_flakes, detect_flakes_cmd, self.cmdname)
