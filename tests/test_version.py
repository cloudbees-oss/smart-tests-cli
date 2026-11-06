from unittest import TestCase

from click.testing import CliRunner

from smart_tests.__main__ import cli
from smart_tests.version import __version__


class VersionTest(TestCase):
    def test_version(self):
        runner = CliRunner()
        result = runner.invoke(cli, ['--version'])
        self.assertEqual(result.exit_code, 0)
        self.assertIn(__version__, result.stdout)
        self.fail("FAIL")
