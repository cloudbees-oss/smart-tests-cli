import os
import tempfile
from unittest import mock

import responses  # type: ignore

from smart_tests.utils.http_client import get_base_url
from tests.cli_test_case import CliTestCase


class SubsetTest(CliTestCase):
    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_subset(self):
        pipe = "test_1.py\ntest_2.py\ntest_3.py\ntest_4.py"
        mock_json_response = {
            "testPaths": [
                [{"type": "file", "name": "test_1.py"}],
                [{"type": "file", "name": "test_2.py"}],

            ],
            "testRunner": "file",
            "rest": [
                [{"type": "file", "name": "test_3.py"}],
                [{"type": "file", "name": "test_4.py"}],

            ],
            "subsettingId": 123,
            "summary": {
                "subset": {"duration": 10, "candidates": 3, "rate": 50},
                "rest": {"duration": 10, "candidates": 3, "rate": 50}
            },
            "isObservation": False,
        }
        responses.replace(responses.POST,
                          f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/subset",
                          json=mock_json_response,
                          status=200)

        rest = tempfile.NamedTemporaryFile(delete=False)
        result = self.cli(
            "subset",
            "file",
            "--target",
            "30%",
            "--session",
            self.session,
            "--rest",
            rest.name,
            mix_stderr=False,
            input=pipe)
        self.assert_success(result)
        self.assertEqual(result.stdout, "test_1.py\ntest_2.py\n")
        self.assertEqual(rest.read().decode(), os.linesep.join(["test_3.py", "test_4.py"]))
        rest.close()
        os.unlink(rest.name)

        # case: rest is empty
        mock_json_response = {
            "testPaths": [
                [{"type": "file", "name": "test_1.py"}],
                [{"type": "file", "name": "test_2.py"}],
                [{"type": "file", "name": "test_3.py"}],
                [{"type": "file", "name": "test_4.py"}],
            ],
            "testRunner": "file",
            "rest": [],
            "subsettingId": 123,
            "summary": {
                "subset": {"duration": 10, "candidates": 3, "rate": 50},
                "rest": {"duration": 10, "candidates": 3, "rate": 50}
            },
            "isObservation": False,
        }
        responses.replace(responses.POST,
                          f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/subset",
                          json=mock_json_response,
                          status=200)

        rest = tempfile.NamedTemporaryFile(delete=False)
        result = self.cli(
            "subset",
            "file",
            "--target",
            "30%",
            "--session",
            self.session,
            "--rest",
            rest.name,
            mix_stderr=False,
            input=pipe)
        self.assert_success(result)
        self.assertEqual(result.stdout, "test_1.py\ntest_2.py\ntest_3.py\ntest_4.py\n")
        self.assertEqual(rest.read().decode(), "")
        rest.close()
        os.unlink(rest.name)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_subset_print_input_snapshot_id(self):
        pipe = "test_1.py\ntest_2.py"
        mock_json_response = {
            "testPaths": [
                [{"type": "file", "name": "test_1.py"}],
                [{"type": "file", "name": "test_2.py"}],
            ],
            "testRunner": "file",
            "rest": [],
            "subsettingId": 456,
            "summary": {
                "subset": {"duration": 10, "candidates": 2, "rate": 50},
                "rest": {"duration": 10, "candidates": 0, "rate": 50},
            },
            "isObservation": False,
        }
        responses.replace(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/subset",
            json=mock_json_response,
            status=200,
        )

        result = self.cli(
            "subset",
            "file",
            "--session",
            self.session,
            "--print-input-snapshot-id",
            mix_stderr=False,
            input=pipe,
        )

        self.assert_success(result)
        self.assertEqual(result.stdout, "456\n")

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_subset_print_input_snapshot_id_disallows_subset_options(self):
        pipe = "test_1.py\n"

        result = self.cli(
            "subset",
            "file",
            "--target",
            "30%",
            "--session",
            self.session,
            "--print-input-snapshot-id",
            mix_stderr=False,
            input=pipe,
        )

        self.assert_exit_code(result, 1)
        self.assertIn("--print-input-snapshot-id cannot be used with --target", result.stderr)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_subset_with_observation_session(self):
        pipe = "test_1.py\ntest_2.py\ntest_3.py\ntest_4.py"
        mock_json_response = {
            "testPaths": [
                [{"type": "file", "name": "test_1.py"}],
                [{"type": "file", "name": "test_2.py"}],
            ],
            "testRunner": "file",
            "rest": [
                [{"type": "file", "name": "test_3.py"}],
                [{"type": "file", "name": "test_4.py"}],

            ],
            "subsettingId": 123,
            "summary": {
                "subset": {"duration": 10, "candidates": 3, "rate": 50},
                "rest": {"duration": 10, "candidates": 3, "rate": 50}
            },
            "isObservation": True,
        }

        responses.replace(responses.POST,
                          f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/subset",
                          json=mock_json_response,
                          status=200)

        observation_mode_rest = tempfile.NamedTemporaryFile(delete=False)
        result = self.cli(
            "subset",
            "file",
            "--target",
            "30%",
            "--session",
            self.session,
            "--rest",
            observation_mode_rest.name,
            input=pipe,
            mix_stderr=False)
        self.assert_success(result)

        self.assertEqual(result.stdout, "test_1.py\ntest_2.py\ntest_3.py\ntest_4.py\n")
        self.assertEqual(observation_mode_rest.read().decode(), "")
        observation_mode_rest.close()
        os.unlink(observation_mode_rest.name)

        # case: rest is empty
        mock_json_response = {
            "testPaths": [
                [{"type": "file", "name": "test_1.py"}],
                [{"type": "file", "name": "test_2.py"}],
                [{"type": "file", "name": "test_3.py"}],
                [{"type": "file", "name": "test_4.py"}],
            ],
            "testRunner": "file",
            "rest": [],
            "subsettingId": 123,
            "summary": {
                "subset": {"duration": 10, "candidates": 3, "rate": 50},
                "rest": {"duration": 10, "candidates": 3, "rate": 50}
            },
            "isObservation": True,
        }
        responses.replace(responses.POST,
                          f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/subset",
                          json=mock_json_response,
                          status=200)

        rest = tempfile.NamedTemporaryFile(delete=False)
        result = self.cli(
            "subset",
            "file",
            "--target",
            "30%",
            "--session",
            self.session,
            "--rest",
            rest.name,
            mix_stderr=False,
            input=pipe)
        self.assert_success(result)
        self.assertEqual(result.stdout, "test_1.py\ntest_2.py\ntest_3.py\ntest_4.py\n")
        self.assertEqual(rest.read().decode(), "")
        rest.close()
        os.unlink(rest.name)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_subset_targetless(self):
        pipe = "test_aaa.py\ntest_bbb.py\ntest_ccc.py\ntest_eee.py\ntest_fff.py\ntest_ggg.py"
        responses.replace(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/subset",
            json={
                "testPaths": [
                    [{"type": "file", "name": "test_aaa.py"}],
                    [{"type": "file", "name": "test_bbb.py"}],
                    [{"type": "file", "name": "test_ccc.py"}],
                ],
                "testRunner": "file",
                "rest": [
                    [{"type": "file", "name": "test_eee.py"}],
                    [{"type": "file", "name": "test_fff.py"}],
                    [{"type": "file", "name": "test_ggg.py"}],
                ],
                "subsettingId": 123,
                "summary": {
                    "subset": {"duration": 10, "candidates": 3, "rate": 50},
                    "rest": {"duration": 10, "candidates": 3, "rate": 50}
                },
            },
            status=200)

        result = self.cli(
            "subset",
            "file",
            "--session",
            self.session,
            input=pipe,
            mix_stderr=False)
        self.assert_success(result)

        payload = self.decode_request_body(self.find_request('/subset').request.body)
        self.assertTrue(payload.get('useServerSideOptimizationTarget'))

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_confidence_subset_with_empty_valid_subset_when_pts_v2_enabled(self):
        pipe = "test_aaa.py\ntest_bbb.py\ntest_ccc.py"
        responses.replace(
            responses.GET,
            "{}/intake/organizations/{}/workspaces/{}/state".format(
                get_base_url(),
                self.organization,
                self.workspace),
            json={"isFailFastMode": False, "isPtsV2Enabled": True},
            status=200)
        responses.replace(
            responses.POST,
            "{}/intake/organizations/{}/workspaces/{}/subset".format(
                get_base_url(),
                self.organization,
                self.workspace),
            json={
                "testPaths": [],
                "testRunner": "file",
                "rest": [
                    [{"type": "file", "name": "test_aaa.py"}],
                    [{"type": "file", "name": "test_bbb.py"}],
                    [{"type": "file", "name": "test_ccc.py"}],
                ],
                "subsettingId": 123,
                "summary": {
                    "subset": {"duration": 0, "candidates": 99, "rate": 0},
                    "rest": {"duration": 30, "candidates": 0, "rate": 100}
                },
                "isObservation": False,
            },
            status=200)

        result = self.cli(
            "subset",
            "--confidence",
            "90%",
            "--session",
            self.session,
            "file",
            input=pipe,
            mix_stderr=False)
        self.assert_success(result)
        self.assertEqual(result.stdout, "")
        self.assertIn("No tests were selected for this code change.", result.stderr)
        self.assertIn("Smart Tests created subset 123", result.stderr)
        self.assertNotIn("Error: no tests found matching the path.", result.stderr)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_confidence_subset_with_empty_subset_and_rest_is_error_even_if_summary_has_candidates(self):
        pipe = "test_aaa.py\ntest_bbb.py\ntest_ccc.py"
        responses.replace(
            responses.GET,
            "{}/intake/organizations/{}/workspaces/{}/state".format(
                get_base_url(),
                self.organization,
                self.workspace),
            json={"isFailFastMode": False, "isPtsV2Enabled": True},
            status=200)
        responses.replace(
            responses.POST,
            "{}/intake/organizations/{}/workspaces/{}/subset".format(
                get_base_url(),
                self.organization,
                self.workspace),
            json={
                "testPaths": [],
                "testRunner": "file",
                "rest": [],
                "subsettingId": 123,
                "summary": {
                    "subset": {"duration": 0, "candidates": 99, "rate": 0},
                    "rest": {"duration": 30, "candidates": 99, "rate": 100}
                },
                "isObservation": False,
            },
            status=200)

        result = self.cli(
            "subset",
            "--confidence",
            "90%",
            "--session",
            self.session,
            "file",
            input=pipe,
            mix_stderr=False)
        self.assert_success(result)
        self.assertEqual(result.stdout, "")
        self.assertIn("Error: no tests found matching the path.", result.stderr)
        self.assertNotIn("No tests were selected for this code change.", result.stderr)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_subset_goalspec(self):
        # make sure --goal-spec gets translated properly to a JSON request payload
        responses.replace(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/subset",
            json={
                "testPaths": [
                    [{"type": "file", "name": "test_aaa.py"}],
                ],
                "testRunner": "file",
                "rest": [],
                "subsettingId": 123,
            },
            status=200)

        result = self.cli(
            "subset",
            "file",
            "--session", self.session,
            "--goal-spec", "foo(),bar(zot=3%)",
            input="test_aaa.py")
        self.assert_success(result)

        payload = self.decode_request_body(self.find_request('/subset').request.body)
        self.assertEqual(payload.get('goal').get('goal'), "foo(),bar(zot=3%)")

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_subset_ignore_flaky_tests_above(self):
        pipe = "test_aaa.py\ntest_bbb.py\ntest_ccc.py\ntest_flaky.py"
        responses.replace(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/subset",
            json={
                "testPaths": [
                    [{"type": "file", "name": "test_aaa.py"}],
                    [{"type": "file", "name": "test_bbb.py"}],

                ],
                "testRunner": "file",
                "rest": [
                    [{"type": "file", "name": "test_ccc.py"}],
                ],
                "subsettingId": 123,
                "summary": {
                    "subset": {"duration": 20, "candidates": 2, "rate": 67},
                    "rest": {"duration": 10, "candidates": 1, "rate": 33}
                },
            },
            status=200)

        result = self.cli(
            "subset",
            "file",
            "--session", self.session,
            "--ignore-flaky-tests-above", 0.05,
            input=pipe,
            mix_stderr=False)
        self.assert_success(result)

        payload = self.decode_request_body(self.find_request('/subset').request.body)
        self.assertEqual(payload.get('dropFlakinessThreshold'), 0.05)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_subset_with_get_tests_from_previous_full_runs(self):
        # check error when input candidates are empty without --get-tests-from-previous-sessions option
        result = self.cli("subset", "file", "--target", "30%", "--session", self.session)
        self.assert_exit_code(result, 1)
        self.assertIn("use the `--get-tests-from-previous-sessions` option", result.stdout)

        responses.replace(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/subset",
            json={
                "testPaths": [
                    [{"type": "file", "name": "test_aaa.py"}],
                    [{"type": "file", "name": "test_bbb.py"}],
                    [{"type": "file", "name": "test_ccc.py"}],
                ],
                "testRunner": "file",
                "rest": [
                    [{"type": "file", "name": "test_eee.py"}],
                    [{"type": "file", "name": "test_fff.py"}],
                    [{"type": "file", "name": "test_ggg.py"}],
                ],
                "subsettingId": 123,
                "summary": {
                    "subset": {"duration": 10, "candidates": 3, "rate": 50},
                    "rest": {"duration": 10, "candidates": 3, "rate": 50}
                },
            },
            status=200)

        rest = tempfile.NamedTemporaryFile(delete=False)
        result = self.cli(
            "subset",
            "file",
            "--target",
            "30%",
            "--session",
            self.session,
            "--rest",
            rest.name,
            "--get-tests-from-previous-sessions",
            mix_stderr=False)

        self.assert_success(result)
        self.assertEqual(result.stdout, "test_aaa.py\ntest_bbb.py\ntest_ccc.py\n")
        self.assertEqual(rest.read().decode(), os.linesep.join(["test_eee.py", "test_fff.py", "test_ggg.py"]))
        rest.close()
        os.unlink(rest.name)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_subset_with_output_exclusion_rules(self):
        pipe = "test_aaa.py\ntest_111.py\ntest_bbb.py\ntest_222.py\ntest_ccc.py\ntest_333.py\n"
        responses.replace(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/subset",
            json={
                "testPaths": [
                    [{"type": "file", "name": "test_aaa.py"}],
                    [{"type": "file", "name": "test_bbb.py"}],
                    [{"type": "file", "name": "test_ccc.py"}],
                ],
                "testRunner": "file",
                "rest": [
                    [{"type": "file", "name": "test_111.py"}],
                    [{"type": "file", "name": "test_222.py"}],
                    [{"type": "file", "name": "test_333.py"}],
                ],
                "subsettingId": 123,
                "summary": {
                    "subset": {"duration": 15, "candidates": 3, "rate": 70},
                    "rest": {"duration": 6, "candidates": 3, "rate": 30}
                },
            }, status=200)

        rest = tempfile.NamedTemporaryFile(delete=False)
        result = self.cli(
            "subset",
            "file",
            "--target",
            "70%",
            "--session",
            self.session,
            "--rest",
            rest.name,
            input=pipe,
            mix_stderr=False)

        self.assert_success(result)
        self.assertEqual(result.stdout, "test_aaa.py\ntest_bbb.py\ntest_ccc.py\n")
        self.assertEqual(rest.read().decode(), os.linesep.join(["test_111.py", "test_222.py", "test_333.py"]))
        rest.close()
        os.unlink(rest.name)

        rest = tempfile.NamedTemporaryFile(delete=False)
        result = self.cli(
            "subset",
            "file",
            "--target",
            "70%",
            "--session",
            self.session,
            "--rest",
            rest.name,
            "--output-exclusion-rules",
            input=pipe,
            mix_stderr=False)

        self.assert_success(result)
        self.assertEqual(result.stdout, "test_111.py\ntest_222.py\ntest_333.py\n")

        self.assertEqual(rest.read().decode(), os.linesep.join(["test_aaa.py", "test_bbb.py", "test_ccc.py"]))
        rest.close()
        os.unlink(rest.name)

        # case: reset is empty
        responses.replace(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/subset",
            json={
                "testPaths": [
                    [{"type": "file", "name": "test_aaa.py"}],
                    [{"type": "file", "name": "test_bbb.py"}],
                    [{"type": "file", "name": "test_ccc.py"}],
                    [{"type": "file", "name": "test_111.py"}],
                    [{"type": "file", "name": "test_222.py"}],
                    [{"type": "file", "name": "test_333.py"}],
                ],
                "testRunner": "file",
                "rest": [],
                "subsettingId": 123,
                "summary": {
                    "subset": {"duration": 15, "candidates": 6, "rate": 100},
                    "rest": {"duration": 0, "candidates": 0, "rate": 0}
                },
            }, status=200)

        rest = tempfile.NamedTemporaryFile(delete=False)
        result = self.cli(
            "subset",
            "file",
            "--target",
            "70%",
            "--session",
            self.session,
            "--rest",
            rest.name,
            "--output-exclusion-rules",
            input=pipe,
            mix_stderr=False)

        self.assert_success(result)
        self.assertEqual(result.stdout, "")

        self.assertEqual(rest.read().decode(), os.linesep.join(
            ["test_aaa.py", "test_bbb.py", "test_ccc.py", "test_111.py", "test_222.py", "test_333.py"]))
        rest.close()
        os.unlink(rest.name)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_subset_prioritize_tests_failed_within_hours(self):
        pipe = "test_aaa.py\ntest_bbb.py\ntest_ccc.py\ntest_flaky.py"
        responses.replace(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/subset",
            json={
                "testPaths": [
                    [{"type": "file", "name": "test_aaa.py"}],
                    [{"type": "file", "name": "test_bbb.py"}],

                ],
                "testRunner": "file",
                "rest": [
                    [{"type": "file", "name": "test_ccc.py"}],
                ],
                "subsettingId": 123,
                "summary": {
                    "subset": {"duration": 20, "candidates": 2, "rate": 67},
                    "rest": {"duration": 10, "candidates": 1, "rate": 33}
                },
            },
            status=200)

        result = self.cli(
            "subset",
            "file",
            "--session",
            self.session,
            "--prioritize-tests-failed-within-hours",
            24,
            input=pipe,
            mix_stderr=False)

        self.assert_success(result)

        payload = self.decode_request_body(self.find_request('/subset').request.body)
        self.assertEqual(payload.get('hoursToPrioritizeFailedTest'), 24)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_subset_with_get_tests_from_guess(self):
        responses.replace(
            responses.GET,
            "{}/intake/organizations/{}/workspaces/{}/state".format(
                get_base_url(),
                self.organization,
                self.workspace),
            json={"state": 'HANDS_ON_LAB_V2', "isFailFastMode": True, "isPtsV2Enabled": True},
            status=200)
        responses.replace(
            responses.POST,
            "{}/intake/organizations/{}/workspaces/{}/subset".format(
                get_base_url(),
                self.organization,
                self.workspace),
            json={
                "testPaths": [
                    [{"type": "file", "name": "tests/commands/test_subset.py"}],
                ],
                "testRunner": "file",
                "rest": [],
                "subsettingId": 123,
            },
            status=[200]
        )

        result = self.cli("subset", "file", "--session", self.session, "--get-tests-from-guess")
        self.assert_success(result)
        """
        1. request to  /state
        2. request to /subset with test paths that are collected from auto collection
        """
        payload = self.decode_request_body(self.find_request('/subset').request.body)
        self.assertIn([{"type": "file", "name": "tests/commands/test_subset.py"}], payload.get("testPaths", []))

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_subset_with_bin_option(self):
        pipe = "test_1.py\ntest_2.py\n"
        mock_json_response = {
            "testPaths": [[{"type": "file", "name": "test_1.py"}]],
            "rest": [[{"type": "file", "name": "test_2.py"}]],
            "subsettingId": 999,
            "summary": {"subset": {"duration": 1, "candidates": 1, "rate": 50},
                        "rest": {"duration": 1, "candidates": 1, "rate": 50}},
            "isObservation": False,
        }
        responses.replace(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/subset",
            json=mock_json_response,
            status=200,
        )

        result = self.cli("subset", "file", "--session", self.session, "--target", "10%", "--bin", "1/4",
                          "--input-snapshot-id", "222", mix_stderr=False, input=pipe)

        self.assert_success(result)
        payload = self.decode_request_body(self.find_request('/subset').request.body)
        self.assertEqual(payload.get('subsettingId'), 222)
        self.assertEqual(
            payload.get('splitSubset'),
            {"sliceIndex": 1, "sliceCount": 4, "sameBins": []},
        )

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_subset_input_snapshot_id_from_file(self):
        pipe = "test_1.py\ntest_2.py\n"
        mock_json_response = {
            "testPaths": [[{"type": "file", "name": "test_1.py"}]],
            "rest": [[{"type": "file", "name": "test_2.py"}]],
            "subsettingId": 999,
            "summary": {"subset": {"duration": 1, "candidates": 1, "rate": 50},
                        "rest": {"duration": 1, "candidates": 1, "rate": 50}},
            "isObservation": False,
        }
        responses.replace(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/subset",
            json=mock_json_response,
            status=200,
        )

        with tempfile.NamedTemporaryFile("w+", delete=False) as snapshot_file:
            snapshot_file.write("777\n")
            snapshot_file.flush()
            result = self.cli(
                "subset",
                "file",
                "--session",
                self.session,
                "--target",
                "10%",
                "--input-snapshot-id",
                f"@{snapshot_file.name}",
                mix_stderr=False,
                input=pipe,
            )
        os.unlink(snapshot_file.name)

        self.assert_success(result)
        payload = self.decode_request_body(self.find_request('/subset').request.body)
        self.assertEqual(payload.get('subsettingId'), 777)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_subset_with_same_bin_file(self):
        # Test invalid case
        # --same-bin requires --bin options
        with tempfile.NamedTemporaryFile("w+", delete=False) as same_bin_file:
            same_bin_file.write("example.AddTest\n")
            same_bin_file.flush()
            result = self.cli(
                "subset",
                "go-test",
                "--session",
                self.session,
                "--input-snapshot-id",
                123,
                "--same-bin",
                same_bin_file.name,
                mix_stderr=False)
            self.assert_exit_code(result, 1)
            self.assertIn("--same-bin option requires --bin option", result.stderr)

        # Test valid case
        mock_json_response = {
            "testPaths": [[
                {"type": "class", "name": "rocket-car-gotest"},
                {"type": "testcase", "name": "TestExample1"},
            ]],
            "rest": [],
            "subsettingId": 123,
            "summary": {
                "subset": {"duration": 1, "candidates": 1, "rate": 50},
                "rest": {"duration": 1, "candidates": 0, "rate": 50},
            },
            "isObservation": False,
        }
        responses.replace(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/subset",
            json=mock_json_response,
            status=200,
        )

        with tempfile.NamedTemporaryFile("w+", delete=False) as same_bin_file:
            same_bin_file.write("example.AddTest\nexample.DivTest\n")
            same_bin_file.flush()
            result = self.cli("subset", "go-test", "--session", self.session, "--target", "20%", "--input-snapshot-id", 123,
                              "--bin", "2/5", "--same-bin", same_bin_file.name, mix_stderr=False)
            self.assert_success(result)
            payload = self.decode_request_body(self.find_request('/subset').request.body)
            split_subset = payload.get('splitSubset')
            self.assertEqual(split_subset.get('sliceIndex'), 2)
            self.assertEqual(split_subset.get('sliceCount'), 5)
            self.assertEqual(
                split_subset.get('sameBins'),
                [[
                    [
                        {"type": "class", "name": "example"},
                        {"type": "testcase", "name": "AddTest"},
                    ],
                    [
                        {"type": "class", "name": "example"},
                        {"type": "testcase", "name": "DivTest"},
                    ],
                ]],
            )

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_subset_id_file_not_set(self):
        pipe = "test_1.py\ntest_2.py\n"
        mock_json_response = {
            "testPaths": [
                [{"type": "file", "name": "test_1.py"}],
                [{"type": "file", "name": "test_2.py"}],
            ],
            "testRunner": "file",
            "rest": [],
            "subsettingId": self.subsetting_id,
            "summary": {
                "subset": {"duration": 10, "candidates": 2, "rate": 100},
                "rest": {"duration": 0, "candidates": 0, "rate": 0},
            },
            "isObservation": False,
        }
        responses.replace(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/subset",
            json=mock_json_response,
            status=200,
        )

        sentinel = tempfile.NamedTemporaryFile(delete=False)
        sentinel_path = sentinel.name
        sentinel.close()
        os.unlink(sentinel_path)

        result = self.cli(
            "subset", "file",
            "--session", self.session,
            mix_stderr=False,
            input=pipe,
        )
        self.assert_success(result)
        self.assertEqual(result.stdout, "test_1.py\ntest_2.py\n")
        self.assertFalse(os.path.exists(sentinel_path))

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_subset_id_file_written(self):
        pipe = "test_1.py\ntest_2.py\n"
        mock_json_response = {
            "testPaths": [
                [{"type": "file", "name": "test_1.py"}],
                [{"type": "file", "name": "test_2.py"}],
            ],
            "testRunner": "file",
            "rest": [],
            "subsettingId": self.subsetting_id,
            "summary": {
                "subset": {"duration": 10, "candidates": 2, "rate": 100},
                "rest": {"duration": 0, "candidates": 0, "rate": 0},
            },
            "isObservation": False,
        }
        responses.replace(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/subset",
            json=mock_json_response,
            status=200,
        )

        with tempfile.NamedTemporaryFile(delete=False) as id_file:
            id_file_path = id_file.name

        try:
            result = self.cli(
                "subset", "file",
                "--session", self.session,
                "--subset-id-file", id_file_path,
                mix_stderr=False,
                input=pipe,
            )
            self.assert_success(result)
            self.assertEqual(result.stdout, "test_1.py\ntest_2.py\n")
            with open(id_file_path) as f:
                self.assertEqual(f.read(), f"{self.subsetting_id}\n")
        finally:
            os.unlink(id_file_path)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_subset_id_file_with_target(self):
        pipe = "test_1.py\ntest_2.py\ntest_3.py\n"
        mock_json_response = {
            "testPaths": [
                [{"type": "file", "name": "test_1.py"}],
            ],
            "testRunner": "file",
            "rest": [
                [{"type": "file", "name": "test_2.py"}],
                [{"type": "file", "name": "test_3.py"}],
            ],
            "subsettingId": self.subsetting_id,
            "summary": {
                "subset": {"duration": 5, "candidates": 1, "rate": 33},
                "rest": {"duration": 10, "candidates": 2, "rate": 67},
            },
            "isObservation": False,
        }
        responses.replace(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/subset",
            json=mock_json_response,
            status=200,
        )

        with tempfile.NamedTemporaryFile(delete=False) as id_file:
            id_file_path = id_file.name

        try:
            result = self.cli(
                "subset", "file",
                "--session", self.session,
                "--target", "30%",
                "--subset-id-file", id_file_path,
                mix_stderr=False,
                input=pipe,
            )
            self.assert_success(result)
            self.assertEqual(result.stdout, "test_1.py\n")
            with open(id_file_path) as f:
                self.assertEqual(f.read(), f"{self.subsetting_id}\n")
        finally:
            os.unlink(id_file_path)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_subset_id_file_with_rest(self):
        pipe = "test_1.py\ntest_2.py\n"
        mock_json_response = {
            "testPaths": [
                [{"type": "file", "name": "test_1.py"}],
            ],
            "testRunner": "file",
            "rest": [
                [{"type": "file", "name": "test_2.py"}],
            ],
            "subsettingId": self.subsetting_id,
            "summary": {
                "subset": {"duration": 5, "candidates": 1, "rate": 50},
                "rest": {"duration": 5, "candidates": 1, "rate": 50},
            },
            "isObservation": False,
        }
        responses.replace(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/subset",
            json=mock_json_response,
            status=200,
        )

        with tempfile.NamedTemporaryFile(delete=False) as id_file, \
                tempfile.NamedTemporaryFile(delete=False) as rest_file:
            id_file_path = id_file.name
            rest_file_path = rest_file.name

        try:
            result = self.cli(
                "subset", "file",
                "--session", self.session,
                "--rest", rest_file_path,
                "--subset-id-file", id_file_path,
                mix_stderr=False,
                input=pipe,
            )
            self.assert_success(result)
            self.assertEqual(result.stdout, "test_1.py\n")
            with open(id_file_path) as f:
                self.assertEqual(f.read(), f"{self.subsetting_id}\n")
            with open(rest_file_path) as f:
                self.assertIn("test_2.py", f.read())
        finally:
            os.unlink(id_file_path)
            os.unlink(rest_file_path)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_subset_id_file_no_id_returned(self):
        pipe = "test_1.py\n"
        mock_json_response = {
            "testPaths": [
                [{"type": "file", "name": "test_1.py"}],
            ],
            "testRunner": "file",
            "rest": [],
            "subsettingId": "",
            "summary": {
                "subset": {"duration": 5, "candidates": 1, "rate": 100},
                "rest": {"duration": 0, "candidates": 0, "rate": 0},
            },
            "isObservation": False,
        }
        responses.replace(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/subset",
            json=mock_json_response,
            status=200,
        )

        with tempfile.NamedTemporaryFile(delete=False) as id_file:
            id_file_path = id_file.name

        try:
            result = self.cli(
                "subset", "file",
                "--session", self.session,
                "--subset-id-file", id_file_path,
                mix_stderr=False,
                input=pipe,
            )
            self.assert_exit_code(result, 1)
            self.assertIn("Subset request did not return a subset ID", result.stderr)
        finally:
            if os.path.exists(id_file_path):
                os.unlink(id_file_path)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_subset_id_file_round_trip(self):
        pipe = "test_1.py\ntest_2.py\n"
        mock_json_response = {
            "testPaths": [
                [{"type": "file", "name": "test_1.py"}],
                [{"type": "file", "name": "test_2.py"}],
            ],
            "testRunner": "file",
            "rest": [],
            "subsettingId": self.subsetting_id,
            "summary": {
                "subset": {"duration": 10, "candidates": 2, "rate": 100},
                "rest": {"duration": 0, "candidates": 0, "rate": 0},
            },
            "isObservation": False,
        }
        responses.replace(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/subset",
            json=mock_json_response,
            status=200,
        )

        with tempfile.NamedTemporaryFile(delete=False) as id_file:
            id_file_path = id_file.name

        try:
            # Step 1: capture the subset ID into a file
            result = self.cli(
                "subset", "file",
                "--session", self.session,
                "--subset-id-file", id_file_path,
                mix_stderr=False,
                input=pipe,
            )
            self.assert_success(result)

            # Step 2: feed the file back via --input-snapshot-id @file
            result2 = self.cli(
                "subset", "file",
                "--session", self.session,
                "--input-snapshot-id", f"@{id_file_path}",
                mix_stderr=False,
            )
            self.assert_success(result2)
            payload = self.decode_request_body(self.find_request('/subset', n=1).request.body)
            self.assertEqual(payload.get('subsettingId'), self.subsetting_id)
        finally:
            os.unlink(id_file_path)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_subset_shows_new_test_count_in_table(self):
        pipe = "test_new.py\ntest_known.py\ntest_known2.py"
        responses.replace(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/subset",
            json={
                "testPaths": [
                    [{"type": "file", "name": "test_new.py"}],
                    [{"type": "file", "name": "test_known.py"}],
                ],
                "rest": [
                    [{"type": "file", "name": "test_known2.py"}],
                ],
                "subsettingId": 123,
                "summary": {
                    "subset": {"duration": 0, "candidates": 2, "rate": 67, "newTestCount": 1},
                    "rest": {"duration": 5, "candidates": 1, "rate": 33, "newTestCount": 0},
                },
                "isObservation": False,
            },
            status=200,
        )

        result = self.cli(
            "subset", "file",
            "--target", "70%",
            "--session", self.session,
            mix_stderr=False,
            input=pipe,
        )
        self.assert_success(result)
        self.assertIn("Subset (New Tests)", result.stderr)
        self.assertIn("2 (1)", result.stderr)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_subset_shows_plain_subset_label_when_no_new_tests(self):
        pipe = "test_known.py\ntest_known2.py"
        responses.replace(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/subset",
            json={
                "testPaths": [
                    [{"type": "file", "name": "test_known.py"}],
                ],
                "rest": [
                    [{"type": "file", "name": "test_known2.py"}],
                ],
                "subsettingId": 123,
                "summary": {
                    "subset": {"duration": 10, "candidates": 1, "rate": 50},
                    "rest": {"duration": 10, "candidates": 1, "rate": 50},
                },
                "isObservation": False,
            },
            status=200,
        )

        result = self.cli(
            "subset", "file",
            "--target", "50%",
            "--session", self.session,
            mix_stderr=False,
            input=pipe,
        )
        self.assert_success(result)
        self.assertIn("| Subset", result.stderr)
        self.assertNotIn("Subset (New Tests)", result.stderr)

    # Environment presented by a GitHub Actions job. detect_github_action_context reads these.
    github_actions_env = {
        "SMART_TESTS_TOKEN": CliTestCase.smart_tests_token,
        "GITHUB_ACTIONS": "true",
        "GITHUB_RUN_ID": "12345678",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_REPOSITORY": "cloudbees-oss/smart-tests-cli",
        "GITHUB_JOB": "unit-tests",
        "RUNNER_NAME": "GitHub Actions 1",
    }

    @responses.activate
    @mock.patch.dict(os.environ, github_actions_env, clear=True)
    def test_subset_from_github_actions(self):
        pipe = "test_1.py\ntest_2.py\n"
        mock_json_response = {
            "testPaths": [[{"type": "file", "name": "test_1.py"}]],
            "testRunner": "file",
            "rest": [[{"type": "file", "name": "test_2.py"}]],
            "subsettingId": 123,
            "summary": {
                "subset": {"duration": 10, "candidates": 1, "rate": 50},
                "rest": {"duration": 10, "candidates": 1, "rate": 50},
            },
            "isObservation": False,
        }
        responses.replace(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/subset",
            json=mock_json_response,
            status=200,
        )

        result = self.cli("subset", "file", "--from-github-actions", "--target", "50%",
                          mix_stderr=False, input=pipe)
        self.assert_success(result)
        self.assertEqual(result.stdout, "test_1.py\n")

        payload = self.decode_request_body(self.find_request('/subset').request.body)
        # The GitHub App flow sends run/repo/job identifiers instead of a client-side session.
        self.assertNotIn("session", payload)
        self.assertEqual(payload.get("fromGithubActions"), True)
        self.assertEqual(payload.get("githubActionsRunId"), "12345678")
        self.assertEqual(payload.get("githubActionsRunAttempt"), "1")
        self.assertEqual(payload.get("repositoryOwner"), "cloudbees-oss")
        self.assertEqual(payload.get("repositoryName"), "smart-tests-cli")
        self.assertEqual(payload.get("githubActionsJobName"), "unit-tests")
        self.assertEqual(payload.get("githubActionsRunnerName"), "GitHub Actions 1")
        # The build/session summary line is omitted when there is no client-side session.
        self.assertNotIn("test session", result.stderr)

    @responses.activate
    @mock.patch.dict(os.environ, github_actions_env, clear=True)
    def test_subset_from_github_actions_with_session_is_error(self):
        result = self.cli("subset", "file", "--from-github-actions", "--session", self.session,
                          mix_stderr=False, input="test_1.py\n")
        self.assert_exit_code(result, 1)
        self.assertIn("--from-github-actions cannot be used with --session", result.stderr)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token}, clear=True)
    def test_subset_from_github_actions_outside_github_is_error(self):
        # GITHUB_ACTIONS and friends are absent, so detection returns None.
        result = self.cli("subset", "file", "--from-github-actions",
                          mix_stderr=False, input="test_1.py\n")
        self.assert_exit_code(result, 1)
        self.assertIn("--from-github-actions requires running inside GitHub Actions", result.stderr)

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token}, clear=True)
    def test_subset_without_session_and_without_flag_is_error(self):
        result = self.cli("subset", "file", mix_stderr=False, input="test_1.py\n")
        self.assert_exit_code(result, 1)
        self.assertIn("Missing option '--session'", result.stderr)

    @responses.activate
    @mock.patch.dict(os.environ, {**github_actions_env, "GITHUB_RUN_ID": ""}, clear=True)
    def test_subset_from_github_actions_missing_env_var_is_error(self):
        # Inside GitHub Actions but a required variable is missing: the error should name it,
        # not claim we're outside GitHub Actions.
        result = self.cli("subset", "file", "--from-github-actions",
                          mix_stderr=False, input="test_1.py\n")
        self.assert_exit_code(result, 1)
        self.assertIn("required environment variable(s) not set", result.stderr)
        self.assertIn("GITHUB_RUN_ID", result.stderr)

    @responses.activate
    @mock.patch.dict(os.environ, {**github_actions_env, "GITHUB_REPOSITORY": "no-slash"}, clear=True)
    def test_subset_from_github_actions_malformed_repository_is_error(self):
        result = self.cli("subset", "file", "--from-github-actions",
                          mix_stderr=False, input="test_1.py\n")
        self.assert_exit_code(result, 1)
        self.assertIn("owner/repo", result.stderr)
        self.assertIn("no-slash", result.stderr)

    @responses.activate
    @mock.patch.dict(os.environ, {
        "SMART_TESTS_TOKEN": CliTestCase.smart_tests_token,
        "SMART_TESTS_MATRIX": '{"shard": "1", "os": "ubuntu"}',
    })
    def test_subset_sends_flavors_from_matrix_env_var(self):
        pipe = "test_1.py"
        result = self.cli(
            "subset", "file",
            "--target", "50%",
            "--session", self.session,
            mix_stderr=False,
            input=pipe,
        )
        self.assert_success(result)
        payload = self.decode_request_body(self.find_request('/subset').request.body)
        self.assertEqual(payload.get('flavors'), {"shard": "1", "os": "ubuntu"})

    @responses.activate
    @mock.patch.dict(os.environ, {"SMART_TESTS_TOKEN": CliTestCase.smart_tests_token})
    def test_subset_sends_no_flavors_when_matrix_env_var_absent(self):
        pipe = "test_1.py"
        result = self.cli(
            "subset", "file",
            "--target", "50%",
            "--session", self.session,
            mix_stderr=False,
            input=pipe,
        )
        self.assert_success(result)
        payload = self.decode_request_body(self.find_request('/subset').request.body)
        self.assertNotIn('flavors', payload)
