from ... import args4p
from ...app import Application
from .attachment import attachment
from .build import build
from .commit import commit
from .coverage import coverage
from .deployment import deployment
from .session import session
from .tests import tests


@args4p.group(help="Record test results, builds, commits, and sessions")
def record(app: Application):
    return app


record.add_command(build)
record.add_command(commit)
record.add_command(tests)
record.add_command(session)
record.add_command(attachment)
record.add_command(coverage)
record.add_command(deployment)
