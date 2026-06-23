import os
from typing import BinaryIO, Dict, Optional, Tuple, Union

import click
import requests
from requests import HTTPError, Session, Timeout

from launchable.utils.http_client import _HttpClient, _join_paths
from launchable.utils.tracking import Tracking, TrackingClient  # type: ignore

from ..app import Application
from .authentication import ensure_org_workspace
from .env_keys import REPORT_ERROR_KEY


class LaunchableClient:
    def __init__(self, tracking_client: Optional[TrackingClient] = None, base_url: str = "", session: Optional[Session] = None,
                 test_runner: Optional[str] = "", app: Optional[Application] = None):
        self.http_client = _HttpClient(
            base_url=base_url,
            session=session,
            test_runner=test_runner,
            app=app
        )
        self.tracking_client = tracking_client
        self.organization, self.workspace = ensure_org_workspace()
        self._workspace_state_cache: Optional[Dict[str, Union[str, bool]]] = None

    def request(
        self,
        method: str,
        sub_path: str,
        payload: Optional[Union[Dict, BinaryIO]] = None,
        params: Optional[Dict] = None,
        timeout: Tuple[int, int] = (5, 60),
        compress: bool = False,
        additional_headers: Optional[Dict] = None,
    ) -> requests.Response:
        path = _join_paths(
            "/intake/organizations/{}/workspaces/{}".format(self.organization, self.workspace),
            sub_path
        )

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

    def print_exception_and_recover(self, e: Exception, warning: Optional[str] = None, warning_color='yellow'):
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
            click.echo(click.style(warning, fg=warning_color), err=True)

    def base_url(self) -> str:
        return self.http_client.base_url

    def is_fail_fast_mode(self) -> bool:
        state = self._get_workspace_state()
        return state.get('fail_fast_mode', False)

    def is_pts_v2_enabled(self) -> bool:
        state = self._get_workspace_state()
        return state.get('pts_v2', False)

    def _get_workspace_state(self) -> dict:
        """
        Get the current state of the workspace.
        """
        if self._workspace_state_cache is not None:
            return self._workspace_state_cache
        try:
            res = self.request("get", "state")
            res.raise_for_status()

            state = res.json()
            self._workspace_state_cache = {
                'fail_fast_mode': state.get('isFailFastMode', False),
                'pts_v2': state.get('isPtsV2Enabled', False),
            }
            return self._workspace_state_cache
        except Exception as e:
            self.print_exception_and_recover(e, "Failed to get workspace state")

        return {}
