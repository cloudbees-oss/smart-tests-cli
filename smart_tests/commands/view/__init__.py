from ... import args4p
from ...app import Application
from .flaky_tests import flaky_tests
from .longest_tests import longest_tests
from .never_failing_tests import never_failing_tests
from .test_results import test_results


@args4p.group(help="View historical test data and insights")
def view(app: Application):
    return app


view.add_command(flaky_tests)
view.add_command(longest_tests)
view.add_command(never_failing_tests)
view.add_command(test_results)
