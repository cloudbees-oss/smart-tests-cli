import os.path
import pathlib
import subprocess
import sys
import tempfile
import unittest

# hello smart tests
from launchable.testpath import FilePathNormalizer, parse_test_path, prepend_path_if_missing, relative_subpath, unparse_test_path


class TestPathEncodingTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_test_path('a=b#c=d'), [{'type': 'c', 'name': 'b'}, {'type': 'c', 'name': 'd'}])
        self.assertEqual(parse_test_path('&name=b#&type=c'), [{'name': 'b'}, {'type': 'c'}])
        self.assertEqual(parse_test_path('t=n&a=aa&x=xx'), [{'a': 'aa', 'name': 'n', 'type': 't', 'x': 'xx'}])
        self.assertEqual(parse_test_path('&a=aa&type=t&x=xx'), [{'a': 'aa', 'type': 't', 'x': 'xx'}])
        self.assertEqual(parse_test_path('a=x%25%3D%23%26'), [{'type': 'a', 'name': 'x%=#&'}])
        self.assertEqual(parse_test_path(''), [])
        # See the comment on the parse_test_path.
        # self.assertEqual(
        #     parse_test_path('&'),
        #     [{None: None}])
        # self.assertEqual(
        #     parse_test_path('&#&'),
        #     [{None: None}, {None: None}])

    def test_unparse(self):
        self.assertEqual(
            unparse_test_path([{'type': 'a', 'name': 'b'}, {'type': 'c', 'name': 'd'}]), 'a=b#c=d')
        self.assertEqual(
            unparse_test_path([{'type': None, 'name': 'b'}, {'type': 'c', 'name': None}]), '&name=b#&type=c')
        self.assertEqual(
            unparse_test_path([{'a': 'aa', 'name': 'n', 'type': 't', 'x': 'xx'}]), 't=n&a=aa&x=xx')
        self.assertEqual(
            unparse_test_path([{'a': 'aa', 'type': 't', 'x': 'xx'}]), '&a=aa&type=t&x=xx')
        self.assertEqual(unparse_test_path([{'a': 'x%=#&'}]), '&a=x%25%3D%23%26')
        self.assertEqual(unparse_test_path([]), '')
        self.assertEqual(unparse_test_path([{None: None}]), '&')
        self.assertEqual(unparse_test_path([{None: None}, {None: None}]), '&#&')


class TestFilePathNormalizer(unittest.TestCase):
    def test_relative_path(self):
        n = FilePathNormalizer()
        relpath = os.path.join('foo', 'bar', 'baz')
        self.assertEqual(relpath, n.relativize(relpath))

    def test_base_path(self):
        base = os.path.abspath('base')
        relpath = os.path.join('foo', 'bar', 'baz')
        abspath = os.path.join(base, 'foo', 'bar', 'baz')

        n = FilePathNormalizer(base_path=base)
        self.assertEqual(relpath, n.relativize(relpath))
        self.assertEqual(relpath, n.relativize(abspath))

    def test_normalize_path(self):
        relpath = os.path.join('foo', 'bar', 'baz')
        non_normalized = os.path.join('foo', 'bar', 'omit', '..', 'baz')

        n = FilePathNormalizer()
        self.assertEqual(relpath, n.relativize(non_normalized))

    def test_no_base_path_inference(self):
        base = os.path.abspath('base')
        relpath = os.path.join('foo', 'bar', 'baz')
        abspath = os.path.join(base, 'foo', 'bar', 'baz')

        n = FilePathNormalizer(no_base_path_inference=True)
        self.assertEqual(relpath, n.relativize(relpath))
        self.assertEqual(abspath, n.relativize(abspath))

        n = FilePathNormalizer(base_path=base, no_base_path_inference=True)
        self.assertEqual(relpath, n.relativize(relpath))
        self.assertEqual(relpath, n.relativize(abspath))

    @unittest.skipIf(
        sys.platform.startswith("win"),
        "tempfile creates 8.3 filenames, and it's hard to deal with them. "
        "Practically, we don't see them often, so do not support them now until it's needed."
    )
    def test_inference_git(self):
        with tempfile.TemporaryDirectory() as tempdirname:
            temppath = pathlib.PurePath(tempdirname)
            base = str(temppath.joinpath("gitrepo"))
            relpath = os.path.join('foo', 'bar', 'baz')
            abspath = os.path.join(base, 'foo', 'bar', 'baz')

            self._run_command(['git', 'init', base])

            n = FilePathNormalizer()
            self.assertEqual(relpath, n.relativize(abspath))

    @unittest.skipIf(
        sys.platform.startswith("win"),
        "tempfile creates 8.3 filenames, and it's hard to deal with them. "
        "Practically, we don't see them often, so do not support them now until it's needed. "
        "Also when this runs on Windows, GIT_AUTHOR_NAME etc. is ignored and fails."
    )
    def test_inference_git_submodule(self):
        with tempfile.TemporaryDirectory() as tempdirname:
            temppath = pathlib.PurePath(tempdirname)

            self._run_command(['git', 'init', str(temppath.joinpath("submod"))])
            self._run_command(
                ['git', 'commit', '--allow-empty', '--message', 'test commit'],
                cwd=str(temppath.joinpath("submod")))

            self._run_command(['git', 'init', str(temppath.joinpath("gitrepo"))])
            self._run_command(
                ['git', '-c', 'protocol.file.allow=always', 'submodule', 'add', str(temppath.joinpath("submod")), 'submod'],
                cwd=str(temppath.joinpath("gitrepo")))

            base = str(temppath.joinpath("gitrepo"))
            relpath = os.path.join('submod', 'foo', 'bar', 'baz')
            abspath = os.path.join(base, 'submod', 'foo', 'bar', 'baz')

            n = FilePathNormalizer()
            self.assertEqual(relpath, n.relativize(abspath))

    def _run_command(self, args, cwd=None):
        # Use check_output here to capture stderr for a better error message.
        try:
            subprocess.check_output(
                args,
                cwd=cwd,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                env={
                    "GIT_AUTHOR_NAME": "Test User",
                    "GIT_AUTHOR_EMAIL": "user@example.com",
                    "GIT_COMMITTER_NAME": "Test User",
                    "GIT_COMMITTER_EMAIL": "user@example.com",
                })
        except subprocess.CalledProcessError as e:
            self.fail("Failed to execute a command: {}\nSTDOUT: {}\nSTDERR: {}\n".                format(e, e.stdout, e.stderr))


class TestPathHelpers(unittest.TestCase):
    def test_relative_subpath(self):
        self.assertEqual(
            "tests",
            relative_subpath(str(pathlib.Path("repo", "tests")), str(pathlib.Path("repo"))))

    def test_relative_subpath_returns_empty_when_same_path(self):
        self.assertEqual(
            "",
            relative_subpath(str(pathlib.Path("repo")), str(pathlib.Path("repo"))))

    def test_relative_subpath_returns_empty_when_not_under_base(self):
        self.assertEqual(
            "",
            relative_subpath(str(pathlib.Path("repo", "tests")), str(pathlib.Path("other"))))

    def test_prepend_path_if_missing(self):
        self.assertEqual(
            "tests/a.spec.ts",
            prepend_path_if_missing("a.spec.ts", "tests"))

    def test_prepend_path_if_missing_when_already_prefixed(self):
        self.assertEqual(
            "tests/a.spec.ts",
            prepend_path_if_missing("tests/a.spec.ts", "tests"))

    def test_prepend_path_if_missing_when_empty_input(self):
        self.assertEqual("", prepend_path_if_missing("", "tests"))
        self.assertEqual("a.spec.ts", prepend_path_if_missing("a.spec.ts", ""))


if __name__ == '__main__':
    unittest.main()
