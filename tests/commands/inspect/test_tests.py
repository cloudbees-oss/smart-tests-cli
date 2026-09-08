import os
from unittest import mock

import responses  # type: ignore

from smart_tests.utils.http_client import get_base_url
from tests.cli_test_case import CliTestCase


class TestsTest(CliTestCase):
    response_json = [
        {"testPath": [
            {
                "type": "file",
                "name": "test_file1.py",
            },
        ],
            "duration": 1.2,
            "stderr": "",
            "stdout": "",
            "createdAt": "2021-01-02T03:04:05.000+00:00",
            "status": "SUCCESS",
        },
        {"testPath": [
            {
                "type": "file",
                "name": "test_file3.py",
            },
        ],
            "duration": 0.6,
            "stderr": "",
            "stdout": "",
            "createdAt": "2021-01-02T03:04:05.000+00:00",
            "status": "SUCCESS",
        },


        {"testPath": [
            {
                "type": "file",
                "name": "test_file4.py",
            },
        ],
            "duration": 1.8,
            "stderr": "",
            "stdout": "",
            "createdAt": "2021-01-02T03:04:05.000+00:00",
            "status": "FAILURE",
        },
        {"testPath": [
            {
                "type": "file",
                "name": "test_file2.py",
            },
        ],
            "duration": 0.1,
            "stderr": "",
            "stdout": "",
            "createdAt": "2021-01-02T03:04:05.000+00:00",
            "status": "FAILURE",
        },
    ]

    expect = """| Test Path          |   Duration (sec) | Status   | Uploaded At                   |
|--------------------|------------------|----------|-------------------------------|
| file=test_file1.py |             1.20 | SUCCESS  | 2021-01-02T03:04:05.000+00:00 |
| file=test_file3.py |             0.60 | SUCCESS  | 2021-01-02T03:04:05.000+00:00 |
| file=test_file4.py |             1.80 | FAILURE  | 2021-01-02T03:04:05.000+00:00 |
| file=test_file2.py |             0.10 | FAILURE  | 2021-01-02T03:04:05.000+00:00 |
+-----------+----------------+------------------------+
| Summary   |   Report Count |   Total Duration (min) |
+===========+================+========================+
| Total     |              4 |                   0.06 |
+-----------+----------------+------------------------+
| Success   |              2 |                   0.03 |
+-----------+----------------+------------------------+
| Failure   |              2 |                   0.03 |
+-----------+----------------+------------------------+
| Skip      |              0 |                   0.00 |
+-----------+----------------+------------------------+
"""

    expect_json = """{
  "summary": {
    "total": {
      "report_count": 4,
      "duration_min": 0.06
    },
    "success": {
      "report_count": 2,
      "duration_min": 0.03
    },
    "failure": {
      "report_count": 2,
      "duration_min": 0.03
    },
    "skip": {
      "report_count": 0,
      "duration_min": 0.0
    }
  },
  "results": [
    {
      "test_path": "file=test_file1.py",
      "duration_sec": 1.2,
      "status": "SUCCESS",
      "created_at": "2021-01-02T03:04:05.000+00:00"
    },
    {
      "test_path": "file=test_file3.py",
      "duration_sec": 0.6,
      "status": "SUCCESS",
      "created_at": "2021-01-02T03:04:05.000+00:00"
    },
    {
      "test_path": "file=test_file4.py",
      "duration_sec": 1.8,
      "status": "FAILURE",
      "created_at": "2021-01-02T03:04:05.000+00:00"
    },
    {
      "test_path": "file=test_file2.py",
      "duration_sec": 0.1,
      "status": "FAILURE",
      "created_at": "2021-01-02T03:04:05.000+00:00"
    }
  ],
  "test_session_app_url": "https://app.launchableinc.com/organizations/launchableinc/workspaces/mothership/test-sessions/16"
}
"""

    @responses.activate
    @mock.patch.dict(os.environ, {"LAUNCHABLE_TOKEN": CliTestCase.smart_tests_token})
    def test_tests(self):
        responses.replace(responses.GET, "{}/intake/organizations/{}/workspaces/{}/test_sessions/{}/events".format(
            get_base_url(),
            self.organization,
            self.workspace,
            self.session_id), json=self.response_json, status=200)

        result = self.cli('inspect', 'tests', '--test-session-id', self.session_id, mix_stderr=False)
        self.assert_success(result)
        self.assertEqual(result.stdout, self.expect)

    @responses.activate
    @mock.patch.dict(os.environ, {"LAUNCHABLE_TOKEN": CliTestCase.smart_tests_token})
    def test_tests_json_format(self):
        responses.replace(responses.GET, "{}/intake/organizations/{}/workspaces/{}/test_sessions/{}/events".format(
            get_base_url(),
            self.organization,
            self.workspace,
            self.session_id), json=self.response_json, status=200)

        result = self.cli('inspect', 'tests', "--json", '--test-session-id', self.session_id)
        self.assert_success(result)
        self.assertEqual(result.stdout, self.expect_json)
