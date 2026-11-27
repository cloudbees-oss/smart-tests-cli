import gzip
import json
import os
import tempfile
from unittest import mock

import responses  # type: ignore

from smart_tests.utils.http_client import get_base_url
from tests.cli_test_case import CliTestCase


class CoverageTest(CliTestCase):
    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_coverage(self):
        TEST_CONTENT = b"SF:src/Foo.java\nDA:1,1\nend_of_record\n"

        coverage_file = tempfile.NamedTemporaryFile(delete=False)
        coverage_file.write(TEST_CONTENT)
        coverage_file.close()

        body = None

        def verify_body(request):
            nonlocal body
            body = gzip.decompress(b''.join(list(request.body)))
            return (200, [], json.dumps({"sourceFilesRecorded": 1, "filesWithData": 1}))

        responses.add_callback(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/"
            f"{self.workspace}/builds/{self.build_name}/test_sessions/{self.session_id}/coverage",
            callback=verify_body)

        result = self.cli("record", "coverage", "--session", self.session, coverage_file.name)
        self.assert_success(result)
        self.assertEqual(TEST_CONTENT, body)
        self.assertIn(coverage_file.name, result.output)
        self.assertIn("✓ Recorded successfully", result.output)
        self.assertIn("Coverage Files", result.output)
        self.assertIn("Source Files", result.output)

        os.unlink(coverage_file.name)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_coverage_concatenates_multiple_files_into_one_request(self):
        content_a = b"SF:src/A.java\nDA:1,1\nend_of_record\n"
        content_b = b"SF:src/B.java\nDA:1,0\nend_of_record\n"

        file_a = tempfile.NamedTemporaryFile(delete=False)
        file_a.write(content_a)
        file_a.close()
        file_b = tempfile.NamedTemporaryFile(delete=False)
        file_b.write(content_b)
        file_b.close()

        requests_received = []

        def verify_body(request):
            requests_received.append(gzip.decompress(b''.join(list(request.body))))
            return (200, [], json.dumps({"sourceFilesRecorded": 2, "filesWithData": 1}))

        responses.add_callback(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/"
            f"{self.workspace}/builds/{self.build_name}/test_sessions/{self.session_id}/coverage",
            callback=verify_body)

        result = self.cli("record", "coverage", "--session", self.session, file_a.name, file_b.name)

        self.assert_success(result)
        # Exactly one request, not one per file, carrying both files' content concatenated.
        self.assertEqual(1, len(requests_received))
        self.assertEqual(content_a + b"\n" + content_b, requests_received[0])
        self.assertIn(file_a.name, result.output)
        self.assertIn(file_b.name, result.output)
        self.assertIn("Coverage Files", result.output)
        self.assertIn("Source Files", result.output)

        os.unlink(file_a.name)
        os.unlink(file_b.name)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_coverage_bazel_auto_discovery_tags_each_target_and_sends_one_request(self):
        with tempfile.TemporaryDirectory() as workspace:
            testlogs = os.path.join(workspace, "bazel-testlogs")
            net_dir = os.path.join(testlogs, "net", "AllTests")
            strings_dir = os.path.join(testlogs, "util", "strings", "AllTests")
            os.makedirs(net_dir)
            os.makedirs(strings_dir)

            with open(os.path.join(net_dir, "coverage.dat"), "wb") as f:
                f.write(b"SF:src/net/URIs.java\nDA:1,1\nend_of_record\n")
            with open(os.path.join(strings_dir, "coverage.dat"), "wb") as f:
                f.write(b"SF:src/util/strings/Strings.java\nDA:1,0\nend_of_record\n")

            requests_received = []

            def verify_body(request):
                requests_received.append(gzip.decompress(b''.join(list(request.body))))
                return (200, [], json.dumps({"sourceFilesRecorded": 2, "filesWithData": 1}))

            responses.add_callback(
                responses.POST,
                f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/"
                f"{self.workspace}/builds/{self.build_name}/test_sessions/{self.session_id}/coverage",
                callback=verify_body)

            cwd = os.getcwd()
            os.chdir(workspace)
            try:
                result = self.cli("record", "coverage", "--session", self.session)
            finally:
                os.chdir(cwd)

            self.assert_success(result)
            self.assertEqual(1, len(requests_received))
            body = requests_received[0]

            # Each target's SF: block is preceded by a TN: record derived from its path, since
            # Bazel's own coverage.dat carries no target identity on its own.
            self.assertIn(b"TN://net:AllTests\nSF:src/net/URIs.java\n", body)
            self.assertIn(b"TN://util/strings:AllTests\nSF:src/util/strings/Strings.java\n", body)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_coverage_upload_failure(self):
        coverage_file = tempfile.NamedTemporaryFile(delete=False)
        coverage_file.write(b"not valid lcov")
        coverage_file.close()

        responses.add(
            responses.POST,
            "{}/intake/organizations/{}/workspaces/{}/builds/{}/test_sessions/{}/coverage".format(
                get_base_url(), self.organization, self.workspace, self.build_name, self.session_id),
            json={"error": "No SF: blocks found in coverage report"},
            status=400)

        result = self.cli("record", "coverage", "--session", self.session, coverage_file.name)

        self.assertIn("⚠ Failed to record", result.output)

        os.unlink(coverage_file.name)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_testmap_alone_uploads_json_when_there_is_no_coverage_to_find(self):
        rules = b'{"format": "testmap-v1", "mappings": {"repo": {"src/**": ["file=tests/**"]}}}'
        testmap_file = tempfile.NamedTemporaryFile(delete=False)
        testmap_file.write(rules)
        testmap_file.close()

        received = []

        def capture(request):
            received.append((request.headers["Content-Type"], gzip.decompress(b''.join(list(request.body)))))
            return (200, [], "{}")

        base = (f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/"
                f"{self.workspace}/builds/{self.build_name}/test_sessions/{self.session_id}")
        responses.add_callback(responses.POST, f"{base}/testmap", callback=capture)

        result = self.cli("record", "coverage", "--session", self.session, "--testmap", testmap_file.name)

        self.assert_success(result)
        self.assertEqual([("application/json", rules)], received)
        self.assertIn("✓ Recorded successfully", result.output)
        self.assertIn("Testmap file", result.output)
        self.assertNotIn("Coverage Files", result.output)
        self.assertNotIn("⚠ Failed to record", result.output)

        os.unlink(testmap_file.name)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_testmap_with_coverage_files_uploads_both(self):
        coverage_file = tempfile.NamedTemporaryFile(delete=False)
        coverage_file.write(b"SF:src/Foo.java\nDA:1,1\nend_of_record\n")
        coverage_file.close()
        testmap_file = tempfile.NamedTemporaryFile(delete=False)
        testmap_file.write(b'{"format": "testmap-v1", "mappings": {}}')
        testmap_file.close()

        base = (f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/"
                f"{self.workspace}/builds/{self.build_name}/test_sessions/{self.session_id}")
        responses.add(responses.POST, f"{base}/coverage", json={"sourceFilesRecorded": 1})
        responses.add(responses.POST, f"{base}/testmap", json={})

        result = self.cli("record", "coverage", "--session", self.session, "--testmap", testmap_file.name,
                          coverage_file.name)

        self.assert_success(result)
        paths = [c.request.url.rsplit("/", 1)[1] for c in responses.calls if c.request.method == "POST"]
        self.assertEqual(["coverage", "testmap"], paths)
        self.assertIn("Coverage Files", result.output)
        self.assertIn("Testmap file", result.output)

        os.unlink(coverage_file.name)
        os.unlink(testmap_file.name)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_testmap_shows_what_the_expansion_found(self):
        result = self._upload_testmap_answered_with({
            "isReupload": False, "changedFiles": 20, "testsRecorded": 28, "rulesFired": 4,
            "testsMatched": 3, "repositoriesWithoutRules": []})

        self.assert_success(result)
        self.assertIn("Tests matched", result.output)
        self.assertIn(" 20 |", result.output)
        self.assertIn(" 3 |", result.output)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_testmap_does_not_suppress_auto_discovered_coverage(self):
        # Adding --testmap to an existing `record coverage` call must not silently stop uploading
        # coverage: one invocation uploads both.
        testmap_file = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        testmap_file.write(b'{"format": "testmap-v1", "mappings": {}}')
        testmap_file.close()

        with tempfile.TemporaryDirectory() as workspace:
            target_dir = os.path.join(workspace, "bazel-testlogs", "net", "AllTests")
            os.makedirs(target_dir)
            with open(os.path.join(target_dir, "coverage.dat"), "wb") as f:
                f.write(b"SF:src/net/URIs.java\nDA:1,1\nend_of_record\n")

            base = (f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/"
                    f"{self.workspace}/builds/{self.build_name}/test_sessions/{self.session_id}")
            responses.add(responses.POST, f"{base}/coverage", json={"sourceFilesRecorded": 1})
            responses.add(responses.POST, f"{base}/testmap", json={})

            cwd = os.getcwd()
            os.chdir(workspace)
            try:
                result = self.cli("record", "coverage", "--session", self.session,
                                  "--testmap", testmap_file.name)
            finally:
                os.chdir(cwd)

        self.assert_success(result)
        paths = [c.request.url.rsplit("/", 1)[1] for c in responses.calls if c.request.method == "POST"]
        self.assertEqual(["coverage", "testmap"], paths)
        self.assertIn("Coverage Files", result.output)
        self.assertIn("Testmap file", result.output)

        os.unlink(testmap_file.name)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_no_coverage_and_no_testmap_is_still_an_error(self):
        # Coverage was the point of the call, so finding none must still fail.
        with tempfile.TemporaryDirectory() as workspace:
            cwd = os.getcwd()
            os.chdir(workspace)
            try:
                result = self.cli("record", "coverage", "--session", self.session)
            finally:
                os.chdir(cwd)

        self.assertIn("⚠ Failed to record", result.output)

    def _upload_testmap_answered_with(self, response_body: dict):
        testmap_file = tempfile.NamedTemporaryFile(delete=False)
        testmap_file.write(b'{"format": "testmap-v1", "mappings": {}}')
        testmap_file.close()
        responses.add(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/"
            f"{self.workspace}/builds/{self.build_name}/test_sessions/{self.session_id}/testmap",
            json=response_body)
        try:
            return self.cli("record", "coverage", "--session", self.session, "--testmap", testmap_file.name)
        finally:
            os.unlink(testmap_file.name)
