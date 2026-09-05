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
from ...utils.env_keys import COMMIT_TIMEOUT, EMBEDDING_API_KEY_KEY, EMBEDDING_ENDPOINT_KEY, EMBEDDING_MODEL_KEY, REPORT_ERROR_KEY
from ...utils.fail_fast_mode import set_fail_fast_mode, warn_and_exit_if_fail_fast_mode
from ...utils.git_log_parser import parse_git_log
from ...utils.http_client import get_base_url
from ...utils.java import cygpath, get_java_command
from ...utils.logger import LOG_LEVEL_AUDIT, Logger

jar_file_path = os.path.normpath(os.path.join(os.path.dirname(__file__), "../../jar/exe_deploy.jar"))


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
    embedding_mode = None
    embedding_model = None
    embedding_dimensions = None
    embedding_augmentation = False
    embedding_provider = None
    embedding_endpoint = None
    try:
        res = client.request("get", "commits/collect/options")
        res.raise_for_status()
        opts = res.json()
        is_collect_message = opts.get("commitMessage", False)
        is_collect_files = opts.get("files", False)
        embedding_mode = opts.get("embeddingMode")
        # env var overrides take precedence over server-provided values
        embedding_model = os.getenv(EMBEDDING_MODEL_KEY) or opts.get("embeddingModel")
        embedding_dimensions = opts.get("embeddingDimensions")
        embedding_augmentation = opts.get("embeddingAugmentation", False)
        embedding_provider = opts.get("embeddingProvider")
        embedding_endpoint = os.getenv(EMBEDDING_ENDPOINT_KEY) or opts.get("embeddingEndpoint")
    except Exception as e:
        tracking_client.send_error_event(
            event_name=Tracking.ErrorEvent.INTERNAL_CLI_ERROR,
            stack_trace=str(e),
            api="commits/options",
        )
        client.print_exception_and_recover(e)

    cwd = os.path.abspath(source)
    if not name:
        name = os.path.basename(cwd)

    embedding_api_key = os.getenv(EMBEDDING_API_KEY_KEY)

    if embedding_mode == "client":
        if not embedding_endpoint:
            warn_and_exit_if_fail_fast_mode(
                f"Workspace requires client-side embeddings but no endpoint is configured. "
                f"Set {EMBEDDING_ENDPOINT_KEY} to override.")
            click.secho(
                f"Warning: workspace requires client-side embeddings but no endpoint is configured. "
                f"Set {EMBEDDING_ENDPOINT_KEY} to override. Skipping embeddings.",
                fg="yellow", err=True)
            embedding_mode = None
        elif not embedding_api_key:
            warn_and_exit_if_fail_fast_mode(
                f"Workspace requires client-side embeddings but {EMBEDDING_API_KEY_KEY} is not set.")
            click.secho(
                f"Warning: workspace requires client-side embeddings but "
                f"{EMBEDDING_API_KEY_KEY} is not set. Skipping embeddings.",
                fg="yellow",
                err=True)
            embedding_mode = None

    try:
        exec_jar(name, cwd, max_days, app, is_collect_message, is_collect_files,
                 embedding_endpoint if embedding_mode == "client" else None,
                 embedding_model if embedding_mode == "client" else None,
                 embedding_dimensions if embedding_mode == "client" else None,
                 embedding_augmentation if embedding_mode == "client" else False,
                 embedding_provider if embedding_mode == "client" else None)
    except Exception as e:
        if os.getenv(REPORT_ERROR_KEY):
            raise e
        else:
            warn_and_exit_if_fail_fast_mode(
                "Couldn't get commit history from `{}`. Do you run command root of git-controlled directory? "
                "If not, please set a directory use by --source option.\nerror: {}".format(cwd, e))


def exec_jar(name: str, source: str, max_days: int, app: Application, is_collect_message: bool, is_collect_files: bool,
             embedding_endpoint: str | None = None, embedding_model: str | None = None,
             embedding_dimensions: int | None = None, embedding_augmentation: bool = False,
             embedding_provider: str | None = None):
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
    if os.getenv(COMMIT_TIMEOUT):
        command.append("-enable-timeout")
    if embedding_endpoint:
        command.extend(["-embedding-endpoint", embedding_endpoint])
    if embedding_model:
        command.extend(["-embedding-model", embedding_model])
    if embedding_dimensions is not None:
        command.extend(["-embedding-dimensions", str(embedding_dimensions)])
    if embedding_augmentation:
        command.append("-embedding-augmentation")
    if embedding_provider:
        command.extend(["-embedding-provider", embedding_provider])
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
