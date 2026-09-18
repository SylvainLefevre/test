"""A client for an upstream Xtream Codes panel's player_api.php protocol."""

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional


class XtreamError(Exception):
    """Raised when the upstream Xtream source cannot be reached or parsed."""


class Client:
    def __init__(self, base_url: str, username: str, password: str, timeout: float = 20):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout

    def _player_api_url(self, action: str = "", extra: Optional[Dict[str, str]] = None) -> str:
        params = {"username": self.username, "password": self.password}
        if action:
            params["action"] = action
        if extra:
            params.update(extra)
        return f"{self.base_url}/player_api.php?{urllib.parse.urlencode(params)}"

    def _get_json(self, url: str) -> Any:
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                body = resp.read()
        except urllib.error.URLError as exc:
            raise XtreamError(f"request to upstream failed: {exc}") from exc
        if not body.strip():
            raise XtreamError("upstream returned an empty body (check source credentials)")
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise XtreamError(f"decoding upstream JSON: {exc}") from exc

    def login(self) -> dict:
        return self._get_json(self._player_api_url())

    def get_live_categories(self) -> List[dict]:
        return self._get_json(self._player_api_url("get_live_categories"))

    def get_vod_categories(self) -> List[dict]:
        return self._get_json(self._player_api_url("get_vod_categories"))

    def get_series_categories(self) -> List[dict]:
        return self._get_json(self._player_api_url("get_series_categories"))

    def get_live_streams(self) -> List[dict]:
        return self._get_json(self._player_api_url("get_live_streams"))

    def get_vod_streams(self) -> List[dict]:
        return self._get_json(self._player_api_url("get_vod_streams"))

    def get_series(self) -> List[dict]:
        return self._get_json(self._player_api_url("get_series"))

    def raw_passthrough(self, action: str, extra: Dict[str, str]) -> bytes:
        """Forwards an arbitrary player_api.php action verbatim and returns
        the raw response body, for actions the filter does not need to
        understand (get_series_info, get_vod_info, get_short_epg, ...).
        """
        url = self._player_api_url(action, extra)
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                return resp.read()
        except urllib.error.URLError as exc:
            raise XtreamError(f"request to upstream failed: {exc}") from exc

    def stream_url(self, kind: str, stream_id: str, ext: str = "") -> str:
        """Builds the direct playback URL on the upstream source for a
        live/movie/series item.
        """
        return f"{self.base_url}/{kind}/{self.username}/{self.password}/{stream_id}.{ext or 'ts'}"

    def xmltv_url(self) -> str:
        params = {"username": self.username, "password": self.password}
        return f"{self.base_url}/xmltv.php?{urllib.parse.urlencode(params)}"
