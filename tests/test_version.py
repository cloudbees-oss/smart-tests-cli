from unittest import TestCase

from click.testing import CliRunner  # type: ignore

from launchable.__main__ import main
from launchable.version import __version__


class VersionTest(TestCase):
    def test_version(self):
        runner = CliRunner()
        result = runner.invoke(main, ['--version'])
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(result.output, 'launchable-cli, version {}\n'.format(__version__))
