import datetime
import os
import re
import sys
from typing import List, Optional, Sequence, Tuple

import click
from tabulate import tabulate

from launchable.utils.link import CIRCLECI_KEY, GITHUB_ACTIONS_KEY, JENKINS_URL_KEY, capture_links
from launchable.utils.tracking import Tracking, TrackingClient

from ...utils import subprocess
from ...utils.authentication import get_org_workspace
from ...utils.click import DATETIME_WITH_TZ, KEY_VALUE, validate_past_datetime
from ...utils.commands import Command
from ...utils.fail_fast_mode import set_fail_fast_mode, warn_and_exit_if_fail_fast_mode
from ...utils.launchable_client import LaunchableClient
from ...utils.session import clean_session_files, write_build
from .commit import commit

JENKINS_GIT_BRANCH_KEY = "GIT_BRANCH"
JENKINS_GIT_LOCAL_BRANCH_KEY = "GIT_LOCAL_BRANCH"
GITHUB_ACTIONS_GITHUB_HEAD_REF_KEY = "GITHUB_HEAD_REF"
GITHUB_ACTIONS_GITHUB_BASE_REF_KEY = "GITHUB_BASE_REF"
CIRCLECI_CIRCLE_BRANCH_KEY = "CIRCLE_BRANCH"
CODE_BUILD_BUILD_ID_KEY = "CODEBUILD_BUILD_ID"
CODE_BUILD_WEBHOOK_HEAD_REF_KEY = "CODEBUILD_WEBHOOK_HEAD_REF"


@click.command()
@click.option(
    '--name',
    'build_name',
    help='build name',
    required=True,
    type=str,
    metavar='BUILD_NAME'
)
@click.option(
    '--source',
    help='path to local Git workspace, optionally prefixed by a label.  '
         ' like --source path/to/ws or --source main=path/to/ws',
    default=["."],
    metavar="REPO_NAME",
    multiple=True
)
@click.option(
    '--max-days',
    help="the maximum number of days to collect commits retroactively",
    default=30
)
@click.option(
    '--no-submodules',
    is_flag=True,
    help="stop collecting information from Git Submodules",
    default=False
)
@click.option(
    '--no-commit-collection',
    is_flag=True,
    help="""do not collect commit data.

    This is useful if the repository is a shallow clone and the RevWalk is not
    possible. The commit data must be collected with a separate fully-cloned
    repository.
    """,
    default=False
)
@click.option('--scrub-pii', is_flag=True, help='Scrub emails and names', hidden=True)
@click.option(
    '--commit',
    'commits',
    help="set repository name and commit hash when you use --no-commit-collection option",
    multiple=True,
    default=(),
    type=KEY_VALUE,
)
@click.option(
    '--link',
    'links',
    help="Set external link of title and url",
    multiple=True,
    default=(),
    type=KEY_VALUE,
)
@click.option(
    '--branch',
    'branches',
    help="Set repository name and branch name when you use --no-commit-collection option. Please use the same repository name with a commit option",  # noqa: E501
    multiple=True,
    default=(),
    # this is a pseudo key/value that we need to process on our own
    # type=KEY_VALUE,
)
@click.option(
    # hidden option to directly specify the lineage name without relying on branches
    '--lineage',
    'lineage',
    hidden=True,
)
@click.option(
    '--timestamp',
    'timestamp',
    help='Used to overwrite the build time when importing historical data. Note: Format must be `YYYY-MM-DDThh:mm:ssTZD` or `YYYY-MM-DDThh:mm:ss` (local timezone applied)',  # noqa: E501
    type=DATETIME_WITH_TZ,
    default=None,
    callback=validate_past_datetime,
)
@click.pass_context
def build(
        ctx: click.core.Context, build_name: str, source: List[str],
        max_days: int, no_submodules: bool, no_commit_collection: bool, scrub_pii: bool,
        commits: Sequence[Tuple[str, str]],
        links: Sequence[Tuple[str, str]],
        branches: Sequence[str], lineage: str, timestamp: Optional[datetime.datetime]):

    tracking_client = TrackingClient(Command.RECORD_BUILD, app=ctx.obj)
    client = LaunchableClient(app=ctx.obj, tracking_client=tracking_client)
    set_fail_fast_mode(client.is_fail_fast_mode())

    if "/" in build_name or "%2f" in build_name.lower():
        sys.exit("--name must not contain a slash and an encoded slash")
    if "%25" in build_name:
        sys.exit("--name must not contain encoded % (%25)")
    if not no_commit_collection and len(commits) != 0:
        sys.exit("--no-commit-collection must be specified when --commit is used")

    clean_session_files(days_ago=14)

    # Information we want to collect for each Git repository
    # The key data structure throughout the implementation of this command
    class Workspace:
        # identifier given to a Git repository to track the same repository from one 'record build' to next
        name: str
        # path to the Git workspace. Can be None if there's no local workspace present
        dir: str
        # current branch of this workspace
        branch: Optional[str] = None
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
                ctx.invoke(commit, name=w.name, source=w.dir, max_days=max_days)
        else:
            click.echo(click.style(
                "Warning: Commit collection is turned off. The commit data must be collected separately.",
                fg='yellow'), err=True)

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

        branch_name_map = dict()
        if len(branches) == 1 and len(ws) == 1 and not ('=' in branches[0]):
            # if there's only one repo and the short form "--branch NAME" is used, then we assign that to the first repo
            branch_name_map[ws[0].name] = branches[0]
        else:
            for b in branches:
                kv = b.split('=')
                if len(kv) != 2:
                    click.echo(click.style(
                        "Expected --branch REPO=BRANCHNAME but got {}".format(kv),
                        fg="yellow"),
                        err=True)
                    sys.exit(1)

                if not ws_by_name.get(kv[0]):
                    warn_and_exit_if_fail_fast_mode("Invalid repository name {repo} in a --branch option.\nThe repository “{repo}” is not specified via `--source` or `--commit` option.".format(repo=kv[0]))  # noqa: E501

                branch_name_map[kv[0]] = kv[1]

        for w in ws:
            try:
                if not w.commit_hash:
                    w.commit_hash = subprocess.check_output("git rev-parse HEAD".split(), cwd=w.dir).decode().replace("\n", "")
            except Exception as e:
                click.echo(
                    click.style(
                        "Can't get commit hash for {}. Do you run command under git-controlled directory? "
                        "If not, please set a directory use by --source option.".format(w.dir),
                        fg='yellow'),
                    err=True)
                print(e, file=sys.stderr)
                sys.exit(1)
            if w.name in branch_name_map:
                w.branch = branch_name_map[w.name]
            else:
                w.calc_branch_name()

    # Rely on --commit to create a list of workspaces, even when there's no local Git workspaces
    def synthesize_workspaces() -> List[Workspace]:
        ws = []

        commit_pattern = re.compile("[0-9A-Fa-f]{5,40}$")

        for name, hash in commits:
            if not commit_pattern.match(hash):
                click.echo(click.style(
                    "{}'s commit hash `{}` is invalid.".format(name, hash),
                    fg="yellow"),
                    err=True)
                sys.exit(1)

            ws.append(Workspace(name=name, commit_hash=hash))

        return ws

    # send all the data to server and obtain build_id, or none if the service is down, to recover
    def send(ws: List[Workspace]) -> Optional[str]:
        # figure out all the CI links to capture
        def compute_links():
            return capture_links(links, os.environ)

        try:
            payload = {
                "buildNumber": build_name,
                "lineage": lineage or ws[0].branch,
                "commitHashes": [{
                    'repositoryName': w.name,
                    'commitHash': w.commit_hash,
                    'branchName': w.branch or ""
                } for w in ws],
                "links": compute_links(),
                "timestamp": timestamp.isoformat() if timestamp else None,
            }

            res = client.request("post", "builds", payload=payload)
            res.raise_for_status()

            # at this point we've successfully send the data, so it's OK to record this build
            write_build(build_name)

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
            "Launchable recorded build {} to workspace {}/{} with commits from {} {}:\n".format(
                build_name,
                org,
                workspace,
                len(ws),
                ("repositories" if len(ws) > 1 else "repository"),
            ),
        )

        header = ["Name", "Path", "HEAD Commit"]
        rows = [[w.name, w.dir, w.commit_hash] for w in ws]
        click.echo(tabulate(rows, header, tablefmt="github"))
        click.echo(
            "\nVisit https://app.launchableinc.com/organizations/{organization}/workspaces/"
            "{workspace}/data/builds/{build_id} to view this build and its test sessions"
            .format(
                organization=org,
                workspace=workspace,
                build_id=build_id,
            ))

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
