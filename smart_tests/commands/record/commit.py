import os
import subprocess
import sys
from typing import Annotated, List
from urllib.parse import urlparse

import click

import smart_tests.args4p.typer as typer
from smart_tests.utils.smart_tests_client import SmartTestsClient
from smart_tests.utils.tracking import Tracking, TrackingClient

from ... import args4p
from ...app import Application
from ...utils.commands import Command
from ...utils.commit_ingester import upload_commits
from ...utils.embedding import EmbeddingOptions
from ...utils.env_keys import COMMIT_TIMEOUT, EMBEDDING_API_KEY, EMBEDDING_ENDPOINT, REPORT_ERROR_KEY
from ...utils.fail_fast_mode import set_fail_fast_mode, warn_and_exit_if_fail_fast_mode
from ...utils.git_log_parser import parse_git_log
from ...utils.http_client import get_base_url
from ...utils.java import cygpath, get_java_command
from ...utils.logger import LOG_LEVEL_AUDIT, Logger

jar_file_path = os.path.normpath(os.path.join(os.path.dirname(__file__), "../../jar/exe_deploy.jar"))

# Exit status of the jar when client-side embedding cannot go on. Keep in sync with Main.EXIT_EMBEDDING_FAILED.
JAR_EXIT_EMBEDDING_FAILED = 3


@args4p.command(help="Record commit information")
def commit(
    app: Application,
    name: Annotated[str | None, typer.Option(
        help="Repository name",
        metavar="NAME",
    )] = None,
    source: Annotated[str, typer.Option(
        help="Repository path",
        metavar="DIR",
    )] = os.getcwd(),
    executable: Annotated[str, typer.Option(
        help="[Obsolete] it was to specify how to perform commit collection but has been removed",
        hidden=True
    )] = "jar",
    max_days: Annotated[int, typer.Option(
        help="The maximum number of days to collect commits retroactively",
        metavar="DAYS",
    )] = 30,
    import_git_log_output: Annotated[str | None, typer.Option(
        help="Import from the git-log output",
        metavar="FILE",
    )] = None,
):
    if executable == 'docker':
        click.echo("--executable docker is no longer supported", err=True)
        raise typer.Exit(1)

    tracking_client = TrackingClient(Command.COMMIT, app=app)
    client = SmartTestsClient(tracking_client=tracking_client, app=app)
    set_fail_fast_mode(client.is_fail_fast_mode())

    if import_git_log_output:
        _import_git_log(import_git_log_output, app)
        return

    # Commit messages are not collected in the default.
    is_collect_message = False
    is_collect_files = False
    embedding_config: EmbeddingOptions | None = None  # None: options call failed
    try:
        res = client.request("get", "commits/collect/options")
        res.raise_for_status()
        is_collect_message = res.json().get("commitMessage", False)
        is_collect_files = res.json().get("files", False)
        embedding_config = EmbeddingOptions.from_collect_options(res.json())
    except Exception as e:
        tracking_client.send_error_event(
            event_name=Tracking.ErrorEvent.INTERNAL_CLI_ERROR,
            stack_trace=str(e),
            api="commits/options",
        )
        client.print_exception_and_recover(e)

    # embedding_config is None only when the collect/options call failed. Treat that like server mode.
    # Embeddings are only needed when the workspace wants file content (`files` in the options), so a
    # workspace without it has nothing to embed, whatever its embedding mode is.
    is_client_embedding = is_collect_files and embedding_config is not None and embedding_config.is_client_mode
    if is_client_embedding:
        # Only warns when the LLM credentials are missing.
        _check_embedding_env()

    cwd = os.path.abspath(source)
    if not name:
        name = os.path.basename(cwd)
    try:
        # In client mode the jar never falls back to server-side embedding (collect/files is not called).
        exec_jar(name, cwd, max_days, app, is_collect_message, is_collect_files,
                 embedding_config if is_client_embedding else None)
    except Exception as e:
        if os.getenv(REPORT_ERROR_KEY):
            raise e
        elif isinstance(e, subprocess.CalledProcessError) and e.returncode == JAR_EXIT_EMBEDDING_FAILED:
            # The jar has already said what is wrong. Blaming the git directory here would send the user the wrong impression.
            warn_and_exit_if_fail_fast_mode("Client-side embedding failed.")
        else:
            warn_and_exit_if_fail_fast_mode(
                "Couldn't get commit history from `{}`. Do you run command root of git-controlled directory? "
                "If not, please set a directory use by --source option.\nerror: {}".format(cwd, e))


def _check_embedding_env() -> bool:
    """True if the LLM credentials are present. Otherwise warn (exit 1 in fail-fast mode)."""
    missing = [k for k in (EMBEDDING_ENDPOINT, EMBEDDING_API_KEY) if not os.getenv(k)]
    if missing:
        warn_and_exit_if_fail_fast_mode(
            "This workspace uses client-side embeddings but {} is not set. "
            "No commits will be recorded until it is.".format(", ".join(missing)))
        return False
    return True


def exec_jar(name: str, source: str, max_days: int, app: Application, is_collect_message: bool, is_collect_files: bool,
             embedding_config: EmbeddingOptions | None):
    java = get_java_command()

    if not java:
        sys.exit("You need to install Java")

    base_url = get_base_url()

    # using subprocess.check_out with shell=False and a list of command to prevent vulnerability
    # https://knowledge-base.secureflag.com/vulnerabilities/code_injection/os_command_injection_python.html
    command = [java]
    debug_opts = os.getenv("LAUNCHABLE_JAVA_DEBUG")
    if debug_opts:
        command.extend(debug_opts.split())
    command.extend(_build_proxy_option(os.getenv("HTTPS_PROXY")))
    command.extend([
        "-jar",
        cygpath(jar_file_path),
        "-endpoint",
        f"{base_url}/intake/",
        "-max-days",
        str(max_days)
    ])

    if Logger().logger.isEnabledFor(LOG_LEVEL_AUDIT):
        command.append("-audit")
    if app.dry_run:
        command.append("-dry-run")
    if app.skip_cert_verification:
        command.append("-skip-cert-verification")
    if is_collect_message:
        command.append("-commit-message")
    if is_collect_files:
        command.append("-files")
    if embedding_config is not None and embedding_config.is_client_mode:
        # Embeddings are generated client-side, so the jar skips the collect/files upload. The model details
        # are not secret, so they can be on the command line. The endpoint and the API key are not passed
        # here: the jar reads them from its own environment, where `ps` can't show them.
        command.append("-client-embedding")
        for flag, value in (
            ("-embedding-provider", embedding_config.provider),
            ("-embedding-model-name", embedding_config.model_name),
            ("-embedding-model-id", embedding_config.model_id),
            ("-embedding-dimensions", embedding_config.dimensions),
        ):
            if value is not None:
                command.extend([flag, str(value)])
    if os.getenv(COMMIT_TIMEOUT):
        command.append("-enable-timeout")
    command.append(name)
    command.append(cygpath(source))

    subprocess.run(
        command,
        check=True,
        shell=False,
    )


def _import_git_log(output_file: str, app: Application):
    try:
        with open(output_file) as fp:
            commits = parse_git_log(fp)
        upload_commits(commits, app)
    except Exception as e:
        if os.getenv(REPORT_ERROR_KEY):
            raise e
        else:
            warn_and_exit_if_fail_fast_mode("Failed to import the git-log output\n error: {}".format(e))


def _build_proxy_option(https_proxy: str | None) -> List[str]:
    if not https_proxy:
        return []

    if not (https_proxy.startswith("https://") or https_proxy.startswith("http://")):
        https_proxy = "https://" + https_proxy
    proxy_url = urlparse(https_proxy)

    options = []
    if proxy_url.hostname:
        options.append(f"-Dhttps.proxyHost={proxy_url.hostname}")
    if proxy_url.port:
        options.append(f"-Dhttps.proxyPort={proxy_url.port}")
    return options
