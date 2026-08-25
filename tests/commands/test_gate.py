import json
import os
from unittest import mock

import responses

from launchable.utils.http_client import get_base_url
from tests.cli_test_case import CliTestCase


class GateTest(CliTestCase):
    @responses.activate
    @mock.patch.dict(os.environ, {"LAUNCHABLE_TOKEN": CliTestCase.launchable_token})
    def test_gate_passed(self):
        """Test gate command exits with 0 when status is PASSED"""
        responses.add(
            responses.GET,
            "{}/intake/organizations/{}/workspaces/{}/gate".format(
                get_base_url(),
                self.organization,
                self.workspace),
            json={
                'status': 'PASSED',
                'quarantinedFailures': 5,
                'actionableFailures': 0,
                'actionableFailedTests': []
            },
            status=200)

        result = self.cli('gate', '--session', self.session)
        self.assert_success(result)
        self.assertIn('PASSED', result.output)

    @responses.activate
    @mock.patch.dict(os.environ, {"LAUNCHABLE_TOKEN": CliTestCase.launchable_token})
    def test_gate_failed(self):
        """Test gate command exits with 1 when status is FAILED"""
        responses.add(
            responses.GET,
            "{}/intake/organizations/{}/workspaces/{}/gate".format(
                get_base_url(),
                self.organization,
                self.workspace),
            json={
                'status': 'FAILED',
                'quarantinedFailures': 2,
                'actionableFailures': 1,
                'actionableFailedTests': [
                    {
                        'testPath': [
                            {'type': 'file', 'name': 'src/FooTest.java'},
                            {'type': 'testcase', 'name': 'testBar'}
                        ],
                        'stderr': 'AssertionError: expected true but was false'
                    }
                ]
            },
            status=200)

        result = self.cli('gate', '--session', self.session)
        self.assert_exit_code(result, 1)
        self.assertIn('FAILED', result.output)
        self.assertIn('file=src/FooTest.java#testcase=testBar', result.output)
        self.assertIn('AssertionError: expected true but was false', result.output)

    @responses.activate
    @mock.patch.dict(os.environ, {"LAUNCHABLE_TOKEN": CliTestCase.launchable_token})
    def test_gate_passed_json_format(self):
        """Test gate command with --json flag when status is PASSED"""
        gate_data = {
            'status': 'PASSED',
            'quarantinedFailures': 5,
            'actionableFailures': 0,
            'actionableFailedTests': []
        }

        responses.add(
            responses.GET,
            "{}/intake/organizations/{}/workspaces/{}/gate".format(
                get_base_url(),
                self.organization,
                self.workspace),
            json=gate_data,
            status=200)

        result = self.cli('gate', '--session', self.session, '--json')
        self.assert_success(result)

        # Verify JSON output
        output_json = json.loads(result.output)
        self.assertEqual(output_json['status'], 'PASSED')
        self.assertEqual(output_json['quarantinedFailures'], 5)
        self.assertEqual(output_json['actionableFailures'], 0)

    @responses.activate
    @mock.patch.dict(os.environ, {"LAUNCHABLE_TOKEN": CliTestCase.launchable_token})
    def test_gate_failed_json_format(self):
        """Test gate command with --json flag when status is FAILED"""
        gate_data = {
            'status': 'FAILED',
            'quarantinedFailures': 2,
            'actionableFailures': 1,
            'actionableFailedTests': [
                {
                    'testPath': [
                        {'type': 'file', 'name': 'src/FooTest.java'},
                        {'type': 'testcase', 'name': 'testBar'}
                    ],
                    'stderr': 'AssertionError: expected true but was false'
                }
            ]
        }

        responses.add(
            responses.GET,
            "{}/intake/organizations/{}/workspaces/{}/gate".format(
                get_base_url(),
                self.organization,
                self.workspace),
            json=gate_data,
            status=200)

        result = self.cli('gate', '--session', self.session, '--json')
        self.assert_exit_code(result, 1)

        # Verify JSON output
        output_json = json.loads(result.output)
        self.assertEqual(output_json['status'], 'FAILED')
        self.assertEqual(output_json['quarantinedFailures'], 2)
        self.assertEqual(output_json['actionableFailures'], 1)
        self.assertEqual(len(output_json['actionableFailedTests']), 1)
        self.assertEqual(output_json['actionableFailedTests'][0]['testPath'][0]['name'], 'src/FooTest.java')

    @responses.activate
    @mock.patch.dict(os.environ, {"LAUNCHABLE_TOKEN": CliTestCase.launchable_token, "GITHUB_ACTIONS": "true"})
    def test_gate_failed_github_actions_format(self):
        """Test gate command uses ::group:: syntax when running in GitHub Actions"""
        responses.add(
            responses.GET,
            "{}/intake/organizations/{}/workspaces/{}/gate".format(
                get_base_url(),
                self.organization,
                self.workspace),
            json={
                'status': 'FAILED',
                'quarantinedFailures': 0,
                'actionableFailures': 1,
                'actionableFailedTests': [
                    {
                        'testPath': [
                            {'type': 'file', 'name': 'src/FooTest.java'},
                            {'type': 'testcase', 'name': 'testBar'}
                        ],
                        'stderr': 'AssertionError: expected true but was false'
                    }
                ]
            },
            status=200)

        result = self.cli('gate', '--session', self.session)
        self.assert_exit_code(result, 1)
        self.assertIn('::group::1. file=src/FooTest.java#testcase=testBar', result.output)
        self.assertIn('::stop-commands::', result.output)
        self.assertIn('AssertionError: expected true but was false', result.output)
        self.assertIn('::endgroup::', result.output)

    @responses.activate
    @mock.patch.dict(os.environ, {"LAUNCHABLE_TOKEN": CliTestCase.launchable_token, "GITHUB_ACTIONS": "true"})
    def test_gate_github_actions_stderr_with_command_syntax(self):
        """Test that stderr containing ::patterns:: is safely wrapped with stop-commands"""
        responses.add(
            responses.GET,
            "{}/intake/organizations/{}/workspaces/{}/gate".format(
                get_base_url(),
                self.organization,
                self.workspace),
            json={
                'status': 'FAILED',
                'quarantinedFailures': 0,
                'actionableFailures': 1,
                'actionableFailedTests': [
                    {
                        'testPath': [
                            {'type': 'file', 'name': 'src/FooTest.java'},
                            {'type': 'testcase', 'name': 'testBar'}
                        ],
                        'stderr': (
                            '::error::some error\n'
                            '::warning::spoofed\n'
                            '::add-mask::secret-value\n'
                            '::set-output name=x::y\n'
                            'java.lang.AssertionError'
                        )
                    }
                ]
            },
            status=200)

        result = self.cli('gate', '--session', self.session)
        self.assert_exit_code(result, 1)

        # verify all dangerous commands are sandwiched between stop-commands and resume token
        stop_idx = result.output.index('::stop-commands::')
        # resume token is the line between stop-commands and ::endgroup::
        endgroup_idx = result.output.index('::endgroup::')

        error_idx = result.output.index('::error::some error')
        warning_idx = result.output.index('::warning::spoofed')
        mask_idx = result.output.index('::add-mask::secret-value')
        assertion_idx = result.output.index('java.lang.AssertionError')

        # all stderr content must be after ::stop-commands:: and before ::endgroup::
        self.assertLess(stop_idx, error_idx)
        self.assertLess(stop_idx, warning_idx)
        self.assertLess(stop_idx, mask_idx)
        self.assertLess(stop_idx, assertion_idx)
        self.assertLess(error_idx, endgroup_idx)
        self.assertLess(warning_idx, endgroup_idx)
        self.assertLess(mask_idx, endgroup_idx)
        self.assertLess(assertion_idx, endgroup_idx)

    @responses.activate
    @mock.patch.dict(os.environ, {"LAUNCHABLE_TOKEN": CliTestCase.launchable_token})
    def test_gate_not_found(self):
        """Test gate command when gate data is not available"""
        responses.add(
            responses.GET,
            "{}/intake/organizations/{}/workspaces/{}/gate".format(
                get_base_url(),
                self.organization,
                self.workspace),
            json={},
            status=404)

        result = self.cli('gate', '--session', self.session)
        # Should exit with 0 when gate data is not available (non-error case)
        self.assert_success(result)
        self.assertIn('Gate data currently not available', result.output)
