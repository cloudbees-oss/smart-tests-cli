import importlib
import importlib.util
import logging
import os
from glob import glob
from os.path import basename, dirname, join

import click

from launchable.app import Application

from .commands.compare import compare
from .commands.detect_flake import detect_flake
from .commands.inspect import inspect
from .commands.record import record
from .commands.split_subset import split_subset
from .commands.stats import stats
from .commands.subset import subset
from .commands.verify import verify
from .utils import logger
from .version import __version__


@click.group()
@click.version_option(version=__version__, prog_name='launchable-cli')
@click.option(
    '--log-level',
    'log_level',
    help='Set logger\'s log level (CRITICAL, ERROR, WARNING, AUDIT, INFO, DEBUG).',
    type=str,
    default=logger.LOG_LEVEL_DEFAULT_STR,
)
@click.option(
    '--plugins',
    'plugin_dir',
    help='Directory to load plugins from',
    type=click.Path(exists=True, file_okay=False)
)
@click.option(
    '--dry-run',
    'dry_run',
    help='Dry-run mode. No data is sent to the server. However, sometimes '
         'GET requests without payload data or side effects could be sent.'
         'note: Since the dry run log is output together with the AUDIT log, '
         'even if the log-level is set to warning or higher, the log level will '
         'be forced to be set to AUDIT.',
    is_flag=True,
)
@click.option(
    '--skip-cert-verification',
    'skip_cert_verification',
    help='Skip the SSL certificate check. This lets you bypass system setup issues '
         'like CERTIFICATE_VERIFY_FAILED, at the expense of vulnerability against '
         'a possible man-in-the-middle attack. Use it as an escape hatch, but with caution.',
    is_flag=True,
)
@click.pass_context
def main(ctx, log_level, plugin_dir, dry_run, skip_cert_verification):
    level = logger.get_log_level(log_level)
    # In the case of dry-run, it is forced to set the level below the AUDIT.
    # This is because the dry-run log will be output along with the audit log.
    if dry_run and level > logger.LOG_LEVEL_AUDIT:
        level = logger.LOG_LEVEL_AUDIT

    if not skip_cert_verification:
        skip_cert_verification = (os.environ.get('LAUNCHABLE_SKIP_CERT_VERIFICATION') is not None)

    logging.basicConfig(level=level)

    # load all test runners
    for f in glob(join(dirname(__file__), 'test_runners', "*.py")):
        f = basename(f)[:-3]
        if f == '__init__':
            continue
        importlib.import_module('launchable.test_runners.%s' % f)

    # load all plugins
    if plugin_dir:
        for f in glob(join(plugin_dir, '*.py')):
            spec = importlib.util.spec_from_file_location(
                "launchable.plugins.{}".format(basename(f)[:-3]), f)
            plugin = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(plugin)

    ctx.obj = Application(dry_run=dry_run, skip_cert_verification=skip_cert_verification)


main.add_command(record)
main.add_command(subset)
main.add_command(split_subset)
main.add_command(verify)
main.add_command(inspect)
main.add_command(stats)
main.add_command(compare)
main.add_command(detect_flake, 'detect-flake')

if __name__ == '__main__':
    main()
