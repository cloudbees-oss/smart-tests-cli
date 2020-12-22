import click
import os, sys
from . import launchable


@click.argument('files', required=True, nargs=-1)
@launchable.optimize.tests
def optimize_tests(client, files):
    def parse(fname:str):
        '''
        Scan a file, directory full of *.rb, or @FILE
        '''
        if os.path.isdir(fname):
            client.scan(fname, '**/*_test.rb')
        elif fname=='@-':
            # read stdin
            for l in sys.stdin:
                parse(l)
        elif fname.startswith('@'):
            # read response file
            with open(fname[1:]) as f:
                for l in f:
                    parse(l)
        else:
            # assume it's a file
            client.test(fname)

    for f in files:
        parse(f)

    client.run()


@click.argument('report_dirs', required=True, nargs=-1)
@launchable.record.tests
def record_tests(client, report_dirs):
    for root in report_dirs:
        client.scan(root, "*.xml")
    client.run()
