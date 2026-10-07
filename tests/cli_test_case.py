import gzip
import inspect
import json
import os
import shutil
import tempfile
import types
import unittest
from pathlib import Path
from typing import Any, Dict, List

import responses  # type: ignore
from click.testing import CliRunner

from smart_tests.__main__ import cli as main
from smart_tests.utils.env_keys import SESSION_DIR_KEY
from smart_tests.utils.http_client import get_base_url


class CliTestCase(unittest.TestCase):
    """
    Base class for setting up test to invoke CLI
    """
    organization = 'launchableinc'
    workspace = 'mothership'
    smart_tests_token = f"v1:{organization}/{workspace}:auth-token-sample"
    session_id = 16
    build_name = "123"
    session_name = "test_session_name"
    subsetting_id = 456
    session = f"builds/{build_name}/test_sessions/{session_id}"

    # directory where test data files are placed. see get_test_files_dir()
    test_files_dir: Path

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        os.environ[SESSION_DIR_KEY] = self.dir

        self.maxDiff = None

        if not hasattr(self, 'test_files_dir'):
            self.test_files_dir = self.get_test_files_dir()

        # not to use cached configuration between tests
        responses.reset()

        # This is a bad idea -- to have one place where all the mocked responses are defined for all the test cases.
        # These fixtures should be moved closer to where they are used, as much as possible. It'll take time to clean
        # this up, but at least let's not add new ones here.
        # (Kohsuke 2025-11-12)
        responses.add(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}"
            f"/builds/{self.build_name}/test_sessions",
            json={'id': self.session_id},
            status=200)
        responses.add(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/subset",
            json={'testPaths': [], 'rest': [], 'subsettingId': 456},
            status=200)
        responses.add(
            responses.POST,
            f"{get_base_url()}/intake/jenkins/subset",
            json={'testPaths': [], 'rest': [], 'subsettingId': 456},
            status=200)
        responses.add(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}"
            f"/subset/{self.subsetting_id}/slice",
            json={'testPaths': [], 'rest': [], 'subsettingId': 456},
            status=200)
        responses.add(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}"
            f"/subset/{self.subsetting_id}/split-by-groups",
            json={'subsettingId': self.subsetting_id, 'isObservation': False, 'splitGroups': []},
            status=200)
        responses.add(
            responses.GET,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/subset/{self.subsetting_id}",
            json={'testPaths': [], 'rest': [], 'subsettingId': 456},
            status=200)
        responses.add(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}"
            f"/builds/{self.build_name}/test_sessions/{self.session_id}/events",
            json={},
            status=200)
        responses.add(
            responses.GET,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}"
            f"/test_sessions/{self.session_id}/events",
            json=[],
            status=200)
        responses.add(
            responses.GET,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}"
            f"/builds/{self.build_name}/test_sessions/{self.session_id}",
            json={
                'id': self.session_id,
                'isObservation': False,
            },
            status=200)
        responses.add(
            responses.GET,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}"
            f"/builds/{self.build_name}/test_session_names/{self.session_name}",
            json={
                'id': self.session_id,
                'isObservation': False,
            },
            status=404)
        responses.add(
            responses.GET,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}"
            f"/builds/{self.build_name}/test_sessions/{self.session_id}",
            json={
                'id': self.session_id,
                'isObservation': False,
            },
            status=200)
        responses.add(
            responses.PATCH,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}"
            f"/builds/{self.build_name}/test_sessions/{self.session_id}",
            json={'name': self.session_name},
            status=200)
        responses.add(
            responses.PATCH,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}"
            f"/builds/{self.build_name}/test_sessions/{self.session_id}/close",
            json={},
            status=200)
        responses.add(
            responses.POST,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/builds",
            json={'createdAt': "2020-01-02T03:45:56.123+00:00", 'id': 123, "build": self.build_name},
            status=200)
        responses.add(
            responses.GET,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/builds/{self.build_name}",
            json={'createdAt': "2020-01-02T03:45:56.123+00:00", 'id': 123, "build": self.build_name},
            status=200)
        responses.add(
            responses.GET,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/slack/notification/key/list",
            json={'keys': ["GITHUB_ACTOR", "BRANCH_NAME"]},
            status=200)
        responses.add(
            responses.GET,
            f"{get_base_url()}/intake/organizations/{self.organization}/workspaces/{self.workspace}/commits/collect/options",
            json={'commitMessage': True},
            status=200)
        responses.add(
            responses.GET,
            "{}/intake/organizations/{}/workspaces/{}/state".format(
                get_base_url(),
                self.organization,
                self.workspace),
            json={'isFailFastMode': False, 'isPtsV2Enabled': False},
            status=200)
        responses.add(
            responses.GET,
            "{}/intake/organizations/{}/workspaces/{}/model-metadata".format(
                get_base_url(),
                self.organization,
                self.workspace),
            json={'training_cutoff_test_session_id': 256},
            status=200)

    def get_test_files_dir(self):
        file_name = Path(inspect.getfile(self.__class__))  # obtain the file of the concrete type
        stem = file_name.stem.replace('test_', '')  # test_foo.py -> foo
        return file_name.parent.joinpath('../data/%s/' % stem).resolve()

    def tearDown(self):
        del os.environ[SESSION_DIR_KEY]
        shutil.rmtree(self.dir)

    def cli(self, *args, **kwargs):
        """
        Invoke CLI command and returns its result
        """

        # for CliRunner kwargs
        mix_stderr = True
        if 'mix_stderr' in kwargs:
            mix_stderr = kwargs['mix_stderr']
            del kwargs['mix_stderr']

        return CliRunner(mix_stderr=mix_stderr).invoke(cli=main, args=args, catch_exceptions=False, **kwargs)

    def assert_success(self, result):
        self.assert_exit_code(result, 0)

    def assert_exit_code(self, result, expected: int):
        self.assertEqual(result.exit_code, expected, result.output)

    def assert_contents(self, file_path: str, content: str):
        with open(file_path) as f:
            self.assertEqual(f.read(), content)

    def assert_file_exists(self, file_path: str, exists: bool = True):
        self.assertEqual(Path(file_path).exists(), exists)

    def find_request(self, url_suffix: str, n: int = 0):
        '''Find the first (or n-th, if specified) request that matches the given suffix'''
        for call in responses.calls:
            url = call.request.url
            if url and url.endswith(url_suffix):
                if n == 0:
                    return call
                n -= 1

        self.fail("Call to %s didn't happen" % url_suffix)

    def assert_record_tests_payload(self, golden_image_filename: str, payload=None):
        '''
        Compares the request sent by the 'launchable record tests' with the given golden file image

        :param payload
            If none is given, retrieve the payload from what the mock responses captured
        '''

        if not payload:
            payload = self.decode_request_body(self.find_request('/events').request.body)

        # Remove timestamp because it depends on the machine clock
        for c in payload['events']:
            del c['createdAt']
        # metadata includes server dependent data
        del payload['metadata']

        expected = self.load_json_from_file(self.test_files_dir.joinpath(golden_image_filename))
        self.assert_json_orderless_equal(expected, payload)
        self.assert_test_path_orderly_equal(expected, payload)

    def assert_subset_payload(self, golden_image_filename: str, payload=None):
        '''
        Compares the request sent by the 'launchable subset' with the given golden file image

        :param payload
            If none is given, retrieve the payload from what the mock responses captured
        '''

        if not payload:
            payload = self.decode_request_body(self.find_request('/subset').request.body)
        expected = self.load_json_from_file(self.test_files_dir.joinpath(golden_image_filename))
        self.assert_json_orderless_equal(expected, payload)

    def load_json_from_file(self, file):
        try:
            with file.open() as json_file:
                return json.load(json_file)
        except Exception as e:
            raise IOError(f"Failed to parse JSON {file}") from e

    def payload(self, mock_post):
        """
        Given a mock request object, capture the payload sent to the server
        """
        for (args, kwargs) in mock_post.call_args_list:
            if kwargs.get('data'):
                data = kwargs['data']
                if isinstance(data, types.GeneratorType):
                    data = b''.join(data)
                return data

        raise Exception("No data posted")

    def gzipped_json_payload(self, mock_post):
        return json.loads(gzip.decompress(self.payload(mock_post)).decode())

    def json_payload(self, mock_post):
        return json.loads(self.payload(mock_post))

    def decode_request_body(self, request_body):
        """
        Decode request body, handling both compressed and uncompressed data.

        This function became necessary after adding session name resolution API calls.
        Originally, all request bodies were gzip-compressed, so we used
        `json.loads(gzip.decompress(request_body).decode())` directly.
        However, with the addition of session name resolution mocking (GET requests),
        we now have a mix of compressed and uncompressed request bodies.
        This function handles both cases by attempting decompression first,
        then falling back to direct JSON parsing if decompression fails.
        """
        if isinstance(request_body, bytes):
            # Try to decompress first, fall back to direct decoding if not compressed
            try:
                return json.loads(gzip.decompress(request_body).decode())
            except gzip.BadGzipFile:
                return json.loads(request_body.decode())
        else:
            return json.loads(request_body)

    def assert_json_orderless_equal(self, a, b):
        """
        Compare two JSON trees ignoring orders of items in list & dict
        """

        def tree_sorted(obj):
            if isinstance(obj, dict):
                # Convert the dictionary items into a list of tuples,
                # where each tuple contains the key and the recursively sorted value.
                # this sort option `key=lambda item: (item[1] is None, item)`` is for when the value is None
                return sorted([(k, tree_sorted(v)) for k, v in obj.items()], key=lambda item: (item[1] is None, item))
            if isinstance(obj, list):
                return sorted(tree_sorted(x) for x in obj)
            else:
                return obj

        self.assertEqual(tree_sorted(a), tree_sorted(b))

    def assert_test_path_orderly_equal(self, a: Dict[str, Any], b: Dict[str, Any]):
        """
        Compare orders of the values associated with the `testPath` key in two dictionaries

        Pre-conditions:
        - Both 'a' and 'b' should contain 'events' key.
        - The value associated with the 'events' key should be a list of dictionaries,
        and each dictionary must include a 'testPath' key.

        Exceptions:
        - If 'a' or 'b' does not comply with the pre-conditions (e.g., missing keys, wrong data structure),
        the method may raise KeyError or TypeError before the assertion takes place.
        """
        def extract_all_test_paths(obj: Dict[str, Any]) -> List[str]:
            paths_list = []
            for event in obj['events']:
                paths_list.append(event['testPath'])
            return paths_list

        a_test_paths = extract_all_test_paths(a)
        b_test_paths = extract_all_test_paths(b)

        # We cannot compare a and b directory such as `a['events']['testPath']==b['events']['testPath']`.
        # It's because the value associated with the 'events' key is in random order.
        self.assertCountEqual(a_test_paths, b_test_paths)
        for test_path in a_test_paths:
            self.assertIn(test_path, b_test_paths, f"Expected to include {test_path}")
