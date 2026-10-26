import unittest

from launchable.commands.record.case_event import CaseEvent


class TestCaseEventTimestamp(unittest.TestCase):
    """The CLI no longer resolves timezones: it sends the raw suite timestamp and the server
    resolves it. These tests pin that raw-passthrough contract."""

    def test_suite_timestamp_is_sent_raw_and_unresolved(self):
        ts = "2024-06-23T12:34:56.789 PDT"
        result = CaseEvent.create(
            test_path=[], duration_secs=1.0, status=CaseEvent.TEST_PASSED, timestamp=ts
        )
        # Sent verbatim, with no client-side timezone resolution, and no resolved createdAt.
        self.assertEqual(result["junitSuiteTimestamp"], ts)
        self.assertNotIn("createdAt", result)

    def test_absent_timestamp_is_none(self):
        result = CaseEvent.create(
            test_path=[], duration_secs=1.0, status=CaseEvent.TEST_PASSED, timestamp=None
        )
        self.assertIsNone(result["junitSuiteTimestamp"])
