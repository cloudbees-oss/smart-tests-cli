import random
from unittest import TestCase


class TestFlaky(TestCase):
    def test_flaky_function(self):
        # Flaky by design: passes 95% of the time, fails 5%
        self.assertGreater(random.random(), 0.05)
