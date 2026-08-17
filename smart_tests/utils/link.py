import re
from enum import Enum
from typing import Dict, List, Mapping, Sequence

from smart_tests.args4p.exceptions import BadCmdLineException
from smart_tests.utils.typer_types import KeyValue

JENKINS_URL_KEY = 'JENKINS_URL'
JENKINS_BUILD_URL_KEY = 'BUILD_URL'
JENKINS_BUILD_DISPLAY_NAME_KEY = 'BUILD_DISPLAY_NAME'
JENKINS_JOB_NAME_KEY = 'JOB_NAME'
GITHUB_ACTIONS_KEY = 'GITHUB_ACTIONS'
GITHUB_ACTIONS_SERVER_URL_KEY = 'GITHUB_SERVER_URL'
GITHUB_ACTIONS_REPOSITORY_KEY = 'GITHUB_REPOSITORY'
GITHUB_ACTIONS_RUN_ID_KEY = 'GITHUB_RUN_ID'
GITHUB_ACTIONS_RUN_ATTEMPT_KEY = 'GITHUB_RUN_ATTEMPT'
GITHUB_ACTIONS_RUN_NUMBER_KEY = 'GITHUB_RUN_NUMBER'
GITHUB_ACTIONS_RUNNER_NAME_KEY = 'RUNNER_NAME'
GITHUB_ACTIONS_JOB_KEY = 'GITHUB_JOB'
GITHUB_ACTIONS_WORKFLOW_KEY = 'GITHUB_WORKFLOW'
GITHUB_PULL_REQUEST_URL_KEY = 'GITHUB_PULL_REQUEST_URL'
CIRCLECI_KEY = 'CIRCLECI'
CIRCLECI_BUILD_URL_KEY = 'CIRCLE_BUILD_URL'
CIRCLECI_BUILD_NUM_KEY = 'CIRCLE_BUILD_NUM'
CIRCLECI_JOB_KEY = 'CIRCLE_JOB'

GITHUB_PR_REGEX = re.compile(r"^https://github\.com/[^/]+/[^/]+/pull/\d+$")


class LinkKind(Enum):

    LINK_KIND_UNSPECIFIED = 0
    CUSTOM_LINK = 1
    JENKINS = 2
    GITHUB_ACTIONS = 3
    GITHUB_PULL_REQUEST = 4
    CIRCLECI = 5


def capture_link(env: Mapping[str, str]) -> List[Dict[str, str]]:
    links = []

    # see https://launchableinc.atlassian.net/wiki/spaces/PRODUCT/pages/612892698/ for the list of
    # environment variables used by various CI systems
    if env.get(JENKINS_URL_KEY):
        links.append({
            "kind": LinkKind.JENKINS.name, "url": env.get(JENKINS_BUILD_URL_KEY, ""),
            "title": f"{env.get(JENKINS_JOB_NAME_KEY)} {env.get(JENKINS_BUILD_DISPLAY_NAME_KEY)}"
        })
    if env.get(GITHUB_ACTIONS_KEY):
        links.append({
            "kind": LinkKind.GITHUB_ACTIONS.name,
            "url": f"{env.get(GITHUB_ACTIONS_SERVER_URL_KEY)}/{env.get(GITHUB_ACTIONS_REPOSITORY_KEY)}"
            f"/actions/runs/{env.get(GITHUB_ACTIONS_RUN_ID_KEY)}",
            # the nomenclature in GitHub PR comment from GHA has the optional additional part "(a,b,c)" that refers
            # to the matrix, but that doesn't appear to be available as env var. Interestingly, run numbers are not
            # included. Maybe it was seen as too much details and unnecessary for deciding which link to click?
            "title": f"{env.get(GITHUB_ACTIONS_WORKFLOW_KEY)} / {env.get(GITHUB_ACTIONS_JOB_KEY)} "
                     f"#{env.get(GITHUB_ACTIONS_RUN_NUMBER_KEY)}"
                     })
    if env.get(GITHUB_PULL_REQUEST_URL_KEY):
        # TODO: where is this environment variable coming from?
        links.append({
            "kind": LinkKind.GITHUB_PULL_REQUEST.name,
            "url": env.get(GITHUB_PULL_REQUEST_URL_KEY, ""),
            "title": ""
        })
    if env.get(CIRCLECI_KEY):
        # Their UI is organized as "project > branch > workflow > job (buildNum)" and it's not clear to me
        # how much of that information should be present in title.
        links.append({
            "kind": LinkKind.CIRCLECI.name, "url": env.get(CIRCLECI_BUILD_URL_KEY, ""),
            "title": f"{env.get(CIRCLECI_JOB_KEY)} ({env.get(CIRCLECI_BUILD_NUM_KEY)})"
        })

    return links


def capture_links_from_options(link_options: Sequence[KeyValue]) -> List[Dict[str, str]]:
    """
    Validate user-provided link options, inferring the kind when not explicitly specified.

    Each link option is expected in the format "kind|title=url" or "title=url".
    If the kind is not provided, it infers the kind based on the URL pattern.

    Returns:
        A list of dictionaries, where each dictionary contains the validated title, URL, and kind for each link.

    Raises:
        BadCmdLineException: If an invalid kind is provided or URL doesn't match with the specified kind.
    """
    links = []
    for kv in link_options:
        k = kv.key
        url = kv.value.strip()

        # if k,v in format "kind|title=url"
        if '|' in k:
            kind, title = (part.strip() for part in k.split('|', 1))
            if kind not in _valid_kinds():
                raise BadCmdLineException(
                    f"Invalid kind '{kind}' passed to --link option.\nSupported kinds are {_valid_kinds()}")

            if not _url_matches_kind(url, kind):
                raise BadCmdLineException(
                    f"Invalid url '{url}' passed to --link option.\nURL doesn't match with the specified kind '{kind}'")
        # if k,v in format "title=url"
        else:
            kind = _infer_kinds(url)
            title = k.strip()

        links.append({
            "title": title,
            "url": url,
            "kind": kind,
        })

    return links


def capture_links(link_options: Sequence[KeyValue], env: Mapping[str, str]) -> List[Dict[str, str]]:
    links = capture_links_from_options(link_options)

    env_links = capture_link(env)
    for env_link in env_links:
        if not _has_kind(links, env_link['kind']):
            links.append(env_link)

    return links


def _infer_kinds(url: str) -> str:
    if GITHUB_PR_REGEX.match(url):
        return LinkKind.GITHUB_PULL_REQUEST.name

    return LinkKind.CUSTOM_LINK.name


def _has_kind(input_links: List[Dict[str, str]], kind: str) -> bool:
    return any(link for link in input_links if link['kind'] == kind)


def _valid_kinds() -> List[str]:
    return [kind.name for kind in LinkKind if kind != LinkKind.LINK_KIND_UNSPECIFIED]


def _url_matches_kind(url: str, kind: str) -> bool:
    if kind == LinkKind.GITHUB_PULL_REQUEST.name:
        return bool(GITHUB_PR_REGEX.match(url))

    return True
