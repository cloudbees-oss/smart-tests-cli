import os
import shutil
import tempfile
from unittest import TestCase

from launchable.utils.exceptions import ParseSessionException
from launchable.utils.session import (SESSION_DIR_KEY, clean_session_files, parse_session, read_build, read_session,
                                      remove_session, validate_session_format, write_build, write_session)


class SessionTestClass(TestCase):
    build_name = '123'
    session_id = '/intake/organizations/launchableinc/workspaces/mothership/builds/123/test_sessions/13'

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        os.environ[SESSION_DIR_KEY] = self.dir

    def tearDown(self):
        clean_session_files()
        del os.environ[SESSION_DIR_KEY]
        shutil.rmtree(self.dir)

    def test_write_read_build(self):
        self.assertEqual(read_build(), None)
        write_build(self.build_name)
        self.assertEqual(read_build(), self.build_name)

    def test_write_read_remove_session(self):
        write_build(self.build_name)
        write_session(self.build_name, self.session_id)
        self.assertEqual(read_session(self.build_name), self.session_id)

        remove_session()
        self.assertEqual(read_session(self.build_name), None)

    def test_read_before_write(self):
        self.assertEqual(read_session(self.build_name), None)

    def test_parse_session(self):
        session = "builds/build-name/test_sessions/123"
        build_name, session_id = parse_session(session)
        self.assertEqual(build_name, "build-name")
        self.assertEqual(session_id, "12")

        with self.assertRaises(Exception):
            parse_session("hoge/fuga")

    def test_validate_session_format(self):
        # Test with a valid session format
        validate_session_format("builds/build-name/test_sessions/123")

        # Test with invalid session formats
        invalid_sessions = [
            "123",                                              # Only id
            "workspaces/mothership/builds/123/test_sessions/13"  # Too many parts
        ]

        for invalid_session in invalid_sessions:
            with self.assertRaises(ParseSessionException):
                validate_session_format(invalid_session)
