"""Exposes a filtered subset of an Xtream Codes panel over the same
protocol (player_api.php + live/movie/series stream URLs), so any existing
IPTV player can be pointed at it unmodified.
"""

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List

from .config import Config
from .store import Snapshot, Store
from .xtream_client import Client

logger = logging.getLogger(__name__)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, cfg: Config, store: Store, client: Client):
        self.cfg = cfg
        self.store = store
        self.client = client
        super().__init__(address, Handler)


def build_server(cfg: Config, store: Store, client: Client) -> Server:
    host, _, port_str = cfg.server.listen_addr.rpartition(":")
    return Server((host, int(port_str)), cfg, store, client)


def _first(query: Dict[str, List[str]], key: str, default: str = "") -> str:
    values = query.get(key)
    return values[0] if values else default


def _flatten(query: Dict[str, List[str]]) -> Dict[str, str]:
    return {key: values[0] for key, values in query.items() if values}


def _filter_by_category_param(items: List[dict], category_id: str) -> List[dict]:
    if not category_id:
        return items
    return [item for item in items if str(item.get("category_id")) == category_id]


def _resolve_public_host(cfg: Config, host_header: str):
    if cfg.server.public_base_url:
        parsed = urllib.parse.urlsplit(cfg.server.public_base_url)
        host = parsed.hostname or ""
        if parsed.port:
            port = str(parsed.port)
        else:
            port = "443" if parsed.scheme == "https" else "80"
        return parsed.scheme or "http", host, port
    if ":" in host_header:
        host, port = host_header.rsplit(":", 1)
    else:
        host, port = host_header, "80"
    return "http", host, port


class Handler(BaseHTTPRequestHandler):
    server: Server
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        logger.info("%s - %s", self.address_string(), fmt % args)

    # -- low-level helpers ------------------------------------------------

    def _check_creds(self, user: str, password: str) -> bool:
        cfg = self.server.cfg
        return bool(user) and user == cfg.server.username and password == cfg.server.password

    def _write_json(self, payload, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _write_bytes(self, body: bytes, status: int, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _write_text(self, text: str, status: int) -> None:
        self._write_bytes(text.encode("utf-8"), status, "text/plain; charset=utf-8")

    def _redirect(self, url: str) -> None:
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", url)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _proxy(self, url: str) -> None:
        req = urllib.request.Request(url)
        range_header = self.headers.get("Range")
        if range_header:
            req.add_header("Range", range_header)
        try:
            with urllib.request.urlopen(req, timeout=30) as upstream:
                self.send_response(upstream.status)
                for header in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges"):
                    value = upstream.headers.get(header)
                    if value:
                        self.send_header(header, value)
                self.end_headers()
                while True:
                    chunk = upstream.read(65536)
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        return
        except urllib.error.HTTPError as exc:
            self._write_text(str(exc), exc.code)
        except urllib.error.URLError as exc:
            self._write_text(str(exc), HTTPStatus.BAD_GATEWAY)

    def _deliver(self, url: str) -> None:
        if self.server.cfg.streaming.mode == "redirect":
            self._redirect(url)
        else:
            self._proxy(url)

    def _passthrough(self, action: str, query: Dict[str, List[str]]) -> None:
        try:
            body = self.server.client.raw_passthrough(action, _flatten(query))
        except Exception as exc:  # noqa: BLE001 - reported to the client as a gateway error
            self._write_text(str(exc), HTTPStatus.BAD_GATEWAY)
            return
        self._write_bytes(body, HTTPStatus.OK, "application/json")

    def _passthrough_if_allowed(self, action: str, query: Dict[str, List[str]], id_param: str, allowed_ids) -> None:
        item_id = _first(query, id_param)
        if not item_id or item_id not in allowed_ids:
            self._write_text("not found", HTTPStatus.NOT_FOUND)
            return
        self._passthrough(action, query)

    # -- routing ------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 - name mandated by BaseHTTPRequestHandler
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path in ("/player_api.php", "/panel_api.php"):
            self._handle_player_api(query)
            return
        if path == "/xmltv.php":
            self._handle_xmltv(query)
            return
        if path == "/healthz":
            self._handle_health()
            return

        parts = path.strip("/").split("/")
        if len(parts) == 4 and parts[0] in ("live", "movie", "series"):
            self._handle_stream(parts[0], parts[1], parts[2], parts[3])
            return

        self._write_text("not found", HTTPStatus.NOT_FOUND)

    # -- handlers -----------------------------------------------------

    def _handle_health(self) -> None:
        snap = self.server.store.get()
        if snap is None:
            self._write_text("not ready", HTTPStatus.SERVICE_UNAVAILABLE)
            return
        self._write_json({"status": "ok", "refreshed_at": snap.refreshed_at})

    def _handle_player_api(self, query: Dict[str, List[str]]) -> None:
        user = _first(query, "username")
        password = _first(query, "password")
        if not self._check_creds(user, password):
            self._write_json({"user_info": {"auth": 0, "status": "Disabled"}})
            return

        snap = self.server.store.get()
        if snap is None:
            self._write_text("catalog not ready yet", HTTPStatus.SERVICE_UNAVAILABLE)
            return

        action = _first(query, "action")
        category_id = _first(query, "category_id")

        if action == "":
            self._handle_login(snap)
        elif action == "get_live_categories":
            self._write_json(snap.live_categories)
        elif action == "get_vod_categories":
            self._write_json(snap.vod_categories)
        elif action == "get_series_categories":
            self._write_json(snap.series_categories)
        elif action == "get_live_streams":
            self._write_json(_filter_by_category_param(snap.live_streams, category_id))
        elif action == "get_vod_streams":
            self._write_json(_filter_by_category_param(snap.vod_streams, category_id))
        elif action == "get_series":
            self._write_json(_filter_by_category_param(snap.series, category_id))
        elif action == "get_series_info":
            self._passthrough_if_allowed(action, query, "series_id", snap.allowed_series_ids)
        elif action == "get_vod_info":
            self._passthrough_if_allowed(action, query, "vod_id", snap.allowed_vod_ids)
        elif action in ("get_short_epg", "get_simple_data_table"):
            self._passthrough_if_allowed(action, query, "stream_id", snap.allowed_live_ids)
        else:
            # Unknown/exotic action: forward read-only. Credentials were
            # already validated against the local server, not the source.
            self._passthrough(action, query)

    def _handle_login(self, snap: Snapshot) -> None:
        cfg = self.server.cfg
        scheme, host, port = _resolve_public_host(cfg, self.headers.get("Host", ""))

        user_info = {
            "username": cfg.server.username,
            "password": cfg.server.password,
            "auth": 1,
            "status": "Active",
            "allowed_output_formats": ["m3u8", "ts"],
        }
        if snap.source_login:
            src = snap.source_login.get("user_info") or {}
            for key in ("exp_date", "is_trial", "active_cons", "created_at", "max_connections"):
                if src.get(key) is not None:
                    user_info[key] = src[key]
            if src.get("allowed_output_formats"):
                user_info["allowed_output_formats"] = src["allowed_output_formats"]

        now = time.time()
        server_info = {
            "url": host,
            "port": port,
            "server_protocol": scheme,
            "timestamp_now": int(now),
            "time_now": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
        }
        self._write_json({"user_info": user_info, "server_info": server_info})

    def _handle_xmltv(self, query: Dict[str, List[str]]) -> None:
        user = _first(query, "username")
        password = _first(query, "password")
        if not self._check_creds(user, password):
            self._write_text("unauthorized", HTTPStatus.UNAUTHORIZED)
            return
        self._deliver(self.server.client.xmltv_url())

    def _handle_stream(self, kind: str, user: str, password: str, file_name: str) -> None:
        if not self._check_creds(user, password):
            self._write_text("unauthorized", HTTPStatus.UNAUTHORIZED)
            return

        snap = self.server.store.get()
        if snap is None:
            self._write_text("catalog not ready yet", HTTPStatus.SERVICE_UNAVAILABLE)
            return

        if "." in file_name:
            stream_id, _, ext = file_name.rpartition(".")
        else:
            stream_id, ext = file_name, ""

        if kind == "live" and stream_id not in snap.allowed_live_ids:
            self._write_text("not found", HTTPStatus.NOT_FOUND)
            return
        if kind == "movie" and stream_id not in snap.allowed_vod_ids:
            self._write_text("not found", HTTPStatus.NOT_FOUND)
            return
        # Series episode ids are a different id space than series_id (they
        # come from get_series_info) and are not pre-filtered individually,
        # see README "Known limitations".

        self._deliver(self.server.client.stream_url(kind, stream_id, ext))
