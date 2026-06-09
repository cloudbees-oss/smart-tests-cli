import os
from unittest import mock

import responses  # type: ignore

from smart_tests.utils.http_client import get_base_url
from tests.cli_test_case import CliTestCase


class SubsetTest(CliTestCase):
    mock_json = {
        "testPaths": [
                {"testPath": [
                    {"type": "file", "name": "test_file1.py"}], "duration": 1200, "density": 0.8, "numNewTests": 0},
                {"testPath": [
                    {"type": "file", "name": "test_file3.py"}], "duration": 600, "density": 0.5, "numNewTests": 0},
        ],
        "rest": [
            {"testPath": [
                {"type": "file", "name": "test_file4.py"}], "duration": 1800, "density": 0.3, "numNewTests": 0},
            {"testPath": [
                {"type": "file", "name": "test_file2.py"}], "duration": 100, "density": 0.1, "numNewTests": 0}

        ]
    }

    mock_json_with_new_tests = {
        "testPaths": [
            {"testPath": [
                {"type": "file", "name": "test_new1.py"}], "duration": 0, "density": 0.0, "numNewTests": 1},
            {"testPath": [
                {"type": "file", "name": "test_known.py"}], "duration": 1200, "density": 0.8, "numNewTests": 0},
        ],
        "rest": [
            {"testPath": [
                {"type": "file", "name": "test_new2.py"}], "duration": 0, "density": 0.0, "numNewTests": 1},
        ]
    }

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_subset(self):
        responses.replace(
            responses.GET,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/"
            f"{self.workspace}/subset/{self.subsetting_id}",
            json=self.mock_json,
            status=200)

        result = self.cli('inspect', 'subset', '--subset-id', self.subsetting_id, mix_stderr=False)
        expect = """|   Order | Test Path          | In Subset   |   Density | Duration   | New   |
|---------|--------------------|-------------|-----------|------------|-------|
|       1 | file=test_file1.py | ✔           |     0.800 | 1.200s     | No    |
|       2 | file=test_file3.py | ✔           |     0.500 | 0.600s     | No    |
|       3 | file=test_file4.py |             |     0.300 | 1.800s     | No    |
|       4 | file=test_file2.py |             |     0.100 | 0.100s     | No    |
"""

        self.assertEqual(result.stdout, expect)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_subset_shows_new_column(self):
        responses.replace(
            responses.GET,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/"
            f"{self.workspace}/subset/{self.subsetting_id}",
            json=self.mock_json_with_new_tests,
            status=200)

        result = self.cli('inspect', 'subset', '--subset-id', self.subsetting_id, mix_stderr=False)
        expect = """|   Order | Test Path          | In Subset   |   Density | Duration   | New   |
|---------|--------------------|-------------|-----------|------------|-------|
|       1 | file=test_new1.py  | ✔           |     0.000 | 0.000s     | Yes   |
|       2 | file=test_known.py | ✔           |     0.800 | 1.200s     | No    |
|       3 | file=test_new2.py  |             |     0.000 | 0.000s     | Yes   |
"""

        self.assertEqual(result.stdout, expect)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_subset_new_tests_only(self):
        responses.replace(
            responses.GET,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/"
            f"{self.workspace}/subset/{self.subsetting_id}",
            json=self.mock_json_with_new_tests,
            status=200)

        result = self.cli(
            'inspect', 'subset', '--subset-id', self.subsetting_id, '--new-tests-only',
            mix_stderr=False)
        expect = """|   Order | Test Path         | In Subset   |   Density | Duration   | New   |
|---------|-------------------|-------------|-----------|------------|-------|
|       1 | file=test_new1.py | ✔           |     0.000 | 0.000s     | Yes   |
|       2 | file=test_new2.py |             |     0.000 | 0.000s     | Yes   |
"""

        self.assertEqual(result.stdout, expect)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_subset_new_tests_only_empty_in_brainless_mode(self):
        brainless_mock_json = {
            "testPaths": [
                {"testPath": [
                    {"type": "file", "name": "test_file1.py"}], "duration": 0, "density": 0.0, "numNewTests": 0},
                {"testPath": [
                    {"type": "file", "name": "test_file2.py"}], "duration": 0, "density": 0.0, "numNewTests": 0},
            ],
            "rest": []
        }
        responses.replace(
            responses.GET,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/"
            f"{self.workspace}/subset/{self.subsetting_id}",
            json=brainless_mock_json,
            status=200)

        result = self.cli(
            'inspect', 'subset', '--subset-id', self.subsetting_id, '--new-tests-only',
            mix_stderr=False)
        expect = """| Order   | Test Path   | In Subset   | Density   | Duration   | New   |
|---------|-------------|-------------|-----------|------------|-------|
"""

        self.assertEqual(result.stdout, expect)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_subset_json_format(self):
        responses.replace(
            responses.GET,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/"
            f"{self.workspace}/subset/{self.subsetting_id}",
            json=self.mock_json,
            status=200)

        result = self.cli('inspect', 'subset', '--subset-id', self.subsetting_id, "--json", mix_stderr=False)
        expect = """{
  "subset": [
    {
      "test_path": "file=test_file1.py",
      "estimated_duration_sec": 1.2
    },
    {
      "test_path": "file=test_file3.py",
      "estimated_duration_sec": 0.6
    }
  ],
  "rest": [
    {
      "test_path": "file=test_file4.py",
      "estimated_duration_sec": 1.8
    },
    {
      "test_path": "file=test_file2.py",
      "estimated_duration_sec": 0.1
    }
  ]
}
"""

        self.assertEqual(result.stdout, expect)
