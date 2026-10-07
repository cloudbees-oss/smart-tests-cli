import os
from typing import BinaryIO, Dict

import click
import requests
from requests import HTTPError, Session, Timeout

from smart_tests.utils.http_client import _HttpClient, _join_paths
from smart_tests.utils.tracking import Tracking, TrackingClient  # type: ignore

from ..app import Application
from .authentication import ensure_org_workspace, get_org_workspace
from .env_keys import REPORT_ERROR_KEY


class SmartTestsClient:
    def __init__(self, tracking_client: TrackingClient | None = None, base_url: str = "", session: Session | None = None,
                 app: Application | None = None, require_org_workspace: bool = True):
        self.http_client = _HttpClient(
            base_url=base_url,
            session=session,
            app=app
        )
        self.tracking_client = tracking_client
        # Workspace-unscoped flows (e.g. the OIDC-only Jenkins subset, where the server resolves the
        # workspace from the token subject) don't need org/workspace, and requiring it would force
        # redundant configuration. Such callers pass require_org_workspace=False; org/workspace then
        # stay whatever the environment provides (possibly None) and are simply not used to build a
        # workspace-scoped path.
        if require_org_workspace:
            self.organization, self.workspace = ensure_org_workspace()
        else:
            self.organization, self.workspace = get_org_workspace()
        self._workspace_state_cache: Dict[str, str | bool] | None = None
        self._cbp_workspace_cache: tuple[str, str] | None = None

    def request(
        self,
        method: str,
        sub_path: str,
        payload: dict | BinaryIO | None = None,
        params: dict | None = None,
        timeout: tuple[int, int] = (5, 60),
        compress: bool = False,
        additional_headers: dict | None = None,
        workspace_scoped: bool = True,
    ) -> requests.Response:
        # Most endpoints live under /intake/organizations/{org}/workspaces/{ws}, where RESTAuthFilter
        # authenticates the caller against the URL workspace. A few endpoints (e.g. the OIDC-only
        # Jenkins subset at /intake/jenkins/subset) resolve the workspace from the presented token's
        # subject instead, so they must NOT carry org/workspace in the path: pass
        # workspace_scoped=False for those.
        if workspace_scoped:
            path = _join_paths(
                f"/intake/organizations/{self.organization}/workspaces/{self.workspace}",
                sub_path
            )
        else:
            path = _join_paths("/intake", sub_path)

        # report an error and bail out
        def track(event_name: Tracking.ErrorEvent, e: Exception):
            if self.tracking_client:
                self.tracking_client.send_error_event(
                    event_name=event_name,
                    stack_trace=str(e),
                    api=sub_path,
                )
            raise e

        try:
            response = self.http_client.request(
                method=method,
                path=path,
                payload=payload,
                params=params,
                timeout=timeout,
                compress=compress,
                additional_headers=additional_headers
            )
            return response
        except ConnectionError as e:
            track(Tracking.ErrorEvent.NETWORK_ERROR, e)
        except Timeout as e:
            track(Tracking.ErrorEvent.TIMEOUT_ERROR, e)
        except HTTPError as e:
            track(Tracking.ErrorEvent.UNEXPECTED_HTTP_STATUS_ERROR, e)
        except Exception as e:
            track(Tracking.ErrorEvent.INTERNAL_SERVER_ERROR, e)

        # should never come here, but needed to make type checker happy
        assert False

    def print_exception_and_recover(self, e: Exception, warning: str | None = None, warning_color='yellow'):
        """
        Print the exception raised from the request method, then recover from it

        :param warning: optional warning message to contextualize the HTTP error
        """

        # a diagnostics flag to abort and report the details
        if os.getenv(REPORT_ERROR_KEY):
            raise e

        click.echo(e, err=True)
        if isinstance(e, HTTPError):
            # if the payload is present, report that as well to assist troubleshooting
            res = e.response
            if res and res.text:
                click.echo(res.text, err=True)

        if warning:
            click.secho(warning, fg=warning_color, err=True)

    def base_url(self) -> str:
        return self.http_client.base_url

    def is_fail_fast_mode(self) -> bool:
        state = self._get_workspace_state()
        return state.get('fail_fast_mode', False)

    def is_pts_v2_enabled(self) -> bool:
        state = self._get_workspace_state()
        return state.get('pts_v2', False)

    def get_cbp_workspace(self) -> tuple[str, str] | None:
        """
        Returns (org_cbp_id, workspace_cbp_id) if this is a CBP workspace, else None.
        """
        state = self._get_workspace_state()
        if not state.get('is_cbp_workspace', False):
            return None

        if self._cbp_workspace_cache is not None:
            return self._cbp_workspace_cache

        try:
            res = self.request("get", "cbp-workspace")
            res.raise_for_status()
            data = res.json()
            self._cbp_workspace_cache = (data['organizationCbpId'], data['workspaceCbpId'])
            return self._cbp_workspace_cache
        except Exception as e:
            self.print_exception_and_recover(e, "Failed to get CBP workspace info")
            return None

    def _get_workspace_state(self) -> dict:
        """
        Get the current state of the workspace.
        """
        if self._workspace_state_cache is not None:
            return self._workspace_state_cache
        # Workspace state lives at a workspace-scoped path; without an org/workspace (e.g. the
        # OIDC-only Jenkins flow) there is nothing to query, so fall back to defaults.
        if not self.organization or not self.workspace:
            return {}
        try:
            res = self.request("get", "state")
            res.raise_for_status()

            state = res.json()
            self._workspace_state_cache = {
                'fail_fast_mode': state.get('isFailFastMode', False),
                'pts_v2': state.get('isPtsV2Enabled', False),
                'is_cbp_workspace': state.get('isCbpWorkspace', False),
            }
            return self._workspace_state_cache
        except Exception as e:
            self.print_exception_and_recover(e, "Failed to get workspace state")

        return {}
