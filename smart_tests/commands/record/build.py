import os
import re
import sys
from typing import Annotated, List

import click
from tabulate import tabulate

import smart_tests.args4p.typer as typer
from smart_tests.commands.record.session import KeyValue, parse_key_value
from smart_tests.utils.link import CIRCLECI_KEY, GITHUB_ACTIONS_KEY, JENKINS_URL_KEY, capture_links
from smart_tests.utils.tracking import Tracking, TrackingClient

from ... import args4p
from ...app import Application
from ...utils import subprocess
from ...utils.authentication import get_org_workspace
from ...utils.commands import Command
from ...utils.fail_fast_mode import set_fail_fast_mode, warn_and_exit_if_fail_fast_mode
from ...utils.smart_tests_client import SmartTestsClient
from ...utils.typer_types import validate_datetime_with_tz, validate_key_value, validate_past_datetime
from .commit import commit

JENKINS_GIT_BRANCH_KEY = "GIT_BRANCH"
JENKINS_GIT_LOCAL_BRANCH_KEY = "GIT_LOCAL_BRANCH"
GITHUB_ACTIONS_GITHUB_HEAD_REF_KEY = "GITHUB_HEAD_REF"
GITHUB_ACTIONS_GITHUB_BASE_REF_KEY = "GITHUB_BASE_REF"
CIRCLECI_CIRCLE_BRANCH_KEY = "CIRCLE_BRANCH"
CODE_BUILD_BUILD_ID_KEY = "CODEBUILD_BUILD_ID"
CODE_BUILD_WEBHOOK_HEAD_REF_KEY = "CODEBUILD_WEBHOOK_HEAD_REF"


@args4p.command(help="Record build information")
def build(
    app: Application,
    build_name: Annotated[str, typer.Option(
        "--build",
        help="Build name",
        metavar="NAME",
        required=True
    )],
    branch: Annotated[str | None, typer.Option(
        "--branch",
        help="Set branch name. A branch is a set of test sessions grouped and this option value will be used for a branch name.",
        metavar="NAME"
    )] = None,
    repositories: Annotated[List[str], typer.Option(
        "--repo-branch-map",
        multiple=True,
        help="Set repository name and branch name when you use --no-commit-collection option. "
             "Please use the same repository name with a commit option",
        metavar="REPO_NAME=BRANCH_NAME"
    )] = [],
    source: Annotated[List[str], typer.Option(
        multiple=True,
        help="Path to local Git workspace, optionally prefixed by a label. "
             "like --source path/to/ws or --source main=path/to/ws",
        metavar="DIR"
    )] = ["."],
    max_days: Annotated[int, typer.Option(
        help="The maximum number of days to collect commits retroactively",
        metavar="DAYS"
    )] = 30,
    no_submodules: Annotated[bool, typer.Option(
        help="Stop collecting information from Git Submodules"
    )] = False,
    no_commit_collection: Annotated[bool, typer.Option(
        help="Do not collect commit data. "
             "This is useful if the repository is a shallow clone and the RevWalk is not "
             "possible. The commit data must be collected with a separate fully-cloned "
             "repository."
    )] = False,
    commits: Annotated[List[str], typer.Option(
        "--commit",
        multiple=True,
        help="Set repository name and commit hash when you use --no-commit-collection option",
        metavar="REPO_NAME=COMMIT_HASH"
    )] = [],
    timestamp: Annotated[str | None, typer.Option(
        help="Used to overwrite the build time when importing historical data. "
             "Note: Format must be `YYYY-MM-DDThh:mm:ssTZD` or `YYYY-MM-DDThh:mm:ss` (local timezone applied)",
        metavar="TIMESTAMP"
    )] = None,
    links: Annotated[List[KeyValue], typer.Option(
        "--link",
        multiple=True,
        help="Set external link of a title and url",
        type=parse_key_value,
    )] = [],
    components: Annotated[List[KeyValue], typer.Option(
        "--component",
        multiple=True,
        help="Include another build as a named component. Format: NAME=BUILD_OR_ALIAS",
        metavar="NAME=BUILDNAME",
        type=parse_key_value,
    )] = [],
    include_environment: Annotated[str | None, typer.Option(
        "--include-environment",
        help="Include all services deployed to this environment as components. See 'record deployment' command.",
        metavar="NAME",
    )] = None,
):

    # Parse key-value pairs for commits
    parsed_commits = [validate_key_value(c) for c in commits]

    # Parse timestamp if provided
    parsed_timestamp = None
    if timestamp:
        parsed_timestamp = validate_past_datetime(validate_datetime_with_tz(timestamp))

    tracking_client = TrackingClient(Command.RECORD_BUILD, app=app)
    client = SmartTestsClient(app=app, tracking_client=tracking_client)
    set_fail_fast_mode(client.is_fail_fast_mode())

    if "/" in build_name or "%2f" in build_name.lower():
        click.echo("--build must not contain a slash and an encoded slash", err=True)
        raise typer.Exit(1)
    if "%25" in build_name:
        click.echo("--build must not contain encoded % (%25)", err=True)
        raise typer.Exit(1)
    if not no_commit_collection and len(parsed_commits) != 0:
        click.echo("--no-commit-collection must be specified when --commit is used", err=True)
        raise typer.Exit(1)
    if not no_commit_collection and len(repositories) != 0:
        click.echo("--no-commit-collection must be specified when --repo-branch-map is used", err=True)
        raise typer.Exit(1)

    # Information we want to collect for each Git repository
    # The key data structure throughout the implementation of this command

    class Workspace:
        # identifier given to a Git repository to track the same repository from one 'record build' to next
        name: str
        # path to the Git workspace. Can be None if there's no local workspace present
        dir: str
        # current branch of this workspace
        branch: str | None = None
        # SHA1 commit hash that's currently checked out
        commit_hash: str

        def __init__(self, name, dir=None, commit_hash=None):
            self.name = name
            self.dir = dir
            self.commit_hash = commit_hash

        def calc_branch_name(self):
            '''
            figure out the branch using the workspace. requires `dir` and `commit_hash` to be set.
            '''

            # Jenkins
            # ref:
            # https://www.theserverside.com/blog/Coffee-Talk-Java-News-Stories-and-Opinions/Complete-Jenkins-Git-environment-variables-list-for-batch-jobs-and-shell-script-builds
            if os.environ.get(JENKINS_URL_KEY):
                self.branch = os.environ.get(JENKINS_GIT_BRANCH_KEY) or os.environ.get(JENKINS_GIT_LOCAL_BRANCH_KEY)

            # Github Actions
            # ref: https://docs.github.com/en/actions/learn-github-actions/variables#default-environment-variables
            # These environment variables cannot be retrieved when a `push` event is emitted.
            # Here is a note regarding the output of `git show-ref`:
            # - Git tag is pushed during a `push` event
            #   => ed6de84bde58d51deebe90e01ddfa5fa78899b1c refs/tags/tag-name
            # - Git commit is pushed during a `push` event
            #   => ed6de84bde58d51deebe90e01ddfa5fa78899b1c refs/heads/branch/branch-name
            if os.environ.get(GITHUB_ACTIONS_KEY):
                self.branch = os.environ.get(GITHUB_ACTIONS_GITHUB_HEAD_REF_KEY) or \
                    os.environ.get(GITHUB_ACTIONS_GITHUB_BASE_REF_KEY)

            # CircleCI
            # ref: https://circleci.com/docs/variables/
            if os.environ.get(CIRCLECI_KEY):
                self.branch = os.environ.get(CIRCLECI_CIRCLE_BRANCH_KEY)
            # AWS CodeBuild
            # ref: https://docs.aws.amazon.com/codebuild/latest/userguide/build-env-ref-env-vars.html
            if os.environ.get(CODE_BUILD_BUILD_ID_KEY):
                v = os.environ.get(CODE_BUILD_WEBHOOK_HEAD_REF_KEY)
                if v:
                    # refs/head/<branch name>
                    self.branch = v.split("/")[-1]

            if self.branch:
                return      # if we've figured this out, great

            try:
                show_ref = subprocess.check_output(["git", "show-ref"], cwd=self.dir).decode()
                refs = [ref for ref in show_ref.split("\n") if self.commit_hash in ref]

                if len(refs) > 0:
                    # We assume the following values:
                    # * ed6de84bde58d51deebe90e01ddfa5fa78899b1c refs/heads/branch/branch-name
                    # * ed6de84bde58d51deebe90e01ddfa5fa78899b1c refs/remotes/origin/branch-name
                    match = re.search('[a-f0-9]{40} refs/(heads|remotes/origin)/(.*)', refs[0])
                    if match:
                        self.branch = match.group(2)
                    else:
                        self.branch = refs[0].split("/")[-1]
            except Exception:
                # cannot get branch name by git command
                pass

    # The first order of business is to ascertain what Git repositories we have in the workspace
    def list_sources() -> List[Workspace]:
        # This command accepts REPO_NAME=REPO_DIR as well as just REPO_DIR
        pattern = re.compile(r'[^=]+=[^=]+')
        ws: List[Workspace] = []
        for s in source:
            if pattern.match(s):
                kv = s.split('=')
                ws.append(Workspace(name=kv[0], dir=kv[1]))
            else:
                ws.append(Workspace(name=s, dir=s))
            # TODO: if repo_dir is absolute path, warn the user that that's probably
            # not what they want to do
        return ws

    # `record commit` on each top-level (= non submodule) Git repository
    # `record commit` command processes Git submodule on its own,
    # so we need to do this between list_sources and list_submodules
    def collect_commits():
        if not no_commit_collection:
            for w in ws:
                commit.callback(app, name=w.name, source=w.dir, max_days=max_days)
        else:
            click.secho(
                "Warning: Commit collection is turned off. The commit data must be collected separately.",
                fg='yellow', err=True)

    # tally up all the submodules, unless we are told not to
    def list_submodules(workspaces: List[Workspace]) -> List[Workspace]:
        if no_submodules:
            return workspaces

        r = workspaces.copy()
        for w in workspaces:
            submodule_pattern = re.compile(r"^[\+\-U ](?P<hash>[a-f0-9]{40}) (?P<name>\S+)")

            # invoke git directly because dulwich's submodule feature was broken
            submodule_stdouts = subprocess.check_output("git submodule status --recursive".split(),
                                                        cwd=w.dir).decode().splitlines()
            for submodule_stdout in submodule_stdouts:
                # the output is e.g.
                # "+bbf213437a65e82dd6dda4391ecc5d598200a6ce sub1 (heads/master)"
                matched = submodule_pattern.search(submodule_stdout)
                if matched:
                    commit_hash = matched.group('hash')
                    name = matched.group('name')
                    if commit_hash and name:
                        r.append(Workspace(
                            name=w.name + "/" + name,
                            dir=w.dir + "/" + name,
                            commit_hash=commit_hash))
        return r

    # figure out the commit hash and branch of those workspaces
    def compute_hash_and_branch(ws: List[Workspace]):
        ws_by_name = {w.name: w for w in ws}

        # Process repository options to create branch name mappings
        branch_name_map = dict()
        if len(repositories) == 1 and len(ws) == 1 and not ('=' in repositories[0]):
            # if there's only one repo and the short form "--repository NAME" is used, then we assign that to the first repo
            branch_name_map[ws[0].name] = repositories[0]
        else:
            for r in repositories:
                kv = r.split('=')
                if len(kv) != 2:
                    click.secho(
                        f"Expected --repo-branch-map REPO=BRANCHNAME but got {kv}",
                        fg='yellow', err=True)
                    raise typer.Exit(1)

                if not ws_by_name.get(kv[0]):
                    warn_and_exit_if_fail_fast_mode("Invalid repository name {repo} in a --branch option.\nThe repository “{repo}” is not specified via `--source` or `--commit` option.".format(repo=kv[0]))  # noqa: E501

                branch_name_map[kv[0]] = kv[1]

        for w in ws:
            try:
                if not w.commit_hash:
                    w.commit_hash = subprocess.check_output("git rev-parse HEAD".split(), cwd=w.dir).decode().replace("\n", "")
            except Exception as e:
                click.secho(
                    "Can't get commit hash for {}. Do you run command under git-controlled directory? "
                    "If not, please set a directory use by --source option.",
                    fg='yellow', err=True)
                print(e, file=sys.stderr)
                raise typer.Exit(1)
            if w.name in branch_name_map:
                w.branch = branch_name_map[w.name]
            else:
                w.calc_branch_name()

    # Rely on --commit to create a list of workspaces, even when there's no local Git workspaces
    def synthesize_workspaces() -> List[Workspace]:
        ws = []

        commit_pattern = re.compile("[0-9A-Fa-f]{5,40}$")

        for name, hash in parsed_commits:
            if not commit_pattern.match(hash):
                click.secho(
                    f"{name}'s commit hash `{hash}` is invalid.",
                    fg='yellow', err=True)
                raise typer.Exit(1)

            ws.append(Workspace(name=name, commit_hash=hash))

        return ws

    # send all the data to server and obtain build_id, or none if the service is down, to recover
    def send(ws: List[Workspace]) -> str | None:
        # TODO(Konboi): port forward #1128
        # figure out all the CI links to capture
        def compute_links():
            return capture_links(link_options=links, env=os.environ)

        def compute_components():
            all_components = list(components)
            if include_environment:
                res = client.request("get", "builds/aliases",
                                     params={"name": f"deployment:{include_environment}:*"})
                res.raise_for_status()
                json = res.json()
                if len(json) == 0:
                    warn_and_exit_if_fail_fast_mode(f"Error: no such environment: {include_environment}")
                click.echo("Components in this environment:")
                for alias_obj in json:
                    service = alias_obj["alias"].split(":", 2)[2]
                    point_to = alias_obj["buildName"]
                    all_components.append(KeyValue(key=service, value=point_to))
                    click.echo(f"  - {service} -> {point_to}")

            for c in all_components:
                if not c.key:
                    click.echo("Component name must not be empty", err=True)
                    raise typer.Exit(1)
            names_seen: set = set()
            for c in all_components:
                if c.key in names_seen:
                    click.echo(f"Duplicate component name: '{c.key}'", err=True)
                    raise typer.Exit(1)
                names_seen.add(c.key)
            return [{"name": c.key, "build": c.value} for c in all_components]

        try:
            lineage = branch or ws[0].branch
            if lineage is None:
                click.echo("Unable to determine branch name. Please specify --branch option.", err=True)
                raise typer.Exit(1)

            payload = {
                "buildNumber": build_name,
                "lineage": lineage,
                "commitHashes": [{
                    'repositoryName': w.name,
                    'commitHash': w.commit_hash,
                    'branchName': w.branch or ""
                } for w in ws],
                "links": compute_links(),
                "timestamp": parsed_timestamp.isoformat() if parsed_timestamp else None,
                "components": compute_components(),
            }

            res = client.request("post", "builds", payload=payload)
            res.raise_for_status()

            return res.json().get("id", None)
        except Exception as e:
            tracking_client.send_error_event(
                event_name=Tracking.ErrorEvent.INTERNAL_CLI_ERROR,
                stack_trace=str(e),
            )
            client.print_exception_and_recover(e)
            return None

    # report what we did to the user to assist diagnostics
    def report(ws: List[Workspace], build_id: str):
        org, workspace = get_org_workspace()
        click.echo(
            f"Smart Tests recorded build {build_name} to workspace {org} / {workspace} with commits from "
            f"{len(ws)} {'repositories' if len(ws) > 1 else 'repository'}: \n")

        header = ["Name", "Path", "HEAD Commit"]
        rows = [[w.name, w.dir, w.commit_hash] for w in ws]
        click.echo(tabulate(rows, header, tablefmt="github"))

        url = _get_build_url(build_id, org, workspace)
        click.echo(f"\nVisit {url} to view this build and its test sessions")

    def _get_build_url(build_id, org, workspace) -> str:
        cbp_workspace = client.get_cbp_workspace()
        if cbp_workspace:
            org_cbp_id, ws_cbp_id = cbp_workspace
            url = f"https://cloudbees.io/{org_cbp_id}/{ws_cbp_id}/smart-tests/data/builds/{build_id}"
        else:
            url = f"https://app.launchableinc.com/organizations/{org}/workspaces/{workspace}/data/builds/{build_id}"
        return url

    # all the logics at the high level
    if len(commits) == 0:
        ws = list_sources()
        collect_commits()
        ws = list_submodules(ws)
    else:
        ws = synthesize_workspaces()
    compute_hash_and_branch(ws)
    build_id = send(ws)
    if not build_id:
        return  # recover from service outage gracefully
    report(ws, build_id)
