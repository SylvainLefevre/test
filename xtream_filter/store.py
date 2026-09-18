"""Holds the latest filtered catalog snapshot in memory and refreshes it
periodically from the upstream Xtream source.
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional, Set

from .config import Config
from .filters import LanguageMatcher, allowed_category_ids, filter_by_category
from .xtream_client import Client

logger = logging.getLogger(__name__)


@dataclass
class Snapshot:
    live_categories: List[dict] = field(default_factory=list)
    vod_categories: List[dict] = field(default_factory=list)
    series_categories: List[dict] = field(default_factory=list)

    live_streams: List[dict] = field(default_factory=list)
    vod_streams: List[dict] = field(default_factory=list)
    series: List[dict] = field(default_factory=list)

    # Stream/series ids that survived filtering, for fast membership checks
    # on playback requests: an id not in the set is refused even if the
    # source has it.
    allowed_live_ids: Set[str] = field(default_factory=set)
    allowed_vod_ids: Set[str] = field(default_factory=set)
    allowed_series_ids: Set[str] = field(default_factory=set)

    source_login: Optional[dict] = None
    refreshed_at: float = 0.0


class Store:
    def __init__(self, client: Client, cfg: Config, lm: LanguageMatcher):
        self._client = client
        self._cfg = cfg
        self._lm = lm
        self._lock = threading.RLock()
        self._snapshot: Optional[Snapshot] = None

    def get(self) -> Optional[Snapshot]:
        with self._lock:
            return self._snapshot

    def refresh_once(self) -> None:
        """Fetches the catalog from the source, applies the filters, and
        swaps the snapshot in atomically. Raises on any upstream failure,
        leaving the previous snapshot (if any) untouched.
        """
        login = self._client.login()

        live_categories = self._client.get_live_categories()
        vod_categories = self._client.get_vod_categories()
        series_categories = self._client.get_series_categories()

        live_streams = self._client.get_live_streams()
        vod_streams = self._client.get_vod_streams()
        series_list = self._client.get_series()

        kept_live_categories, live_ids = allowed_category_ids(self._lm, self._cfg.filters.live, live_categories)
        kept_vod_categories, vod_ids = allowed_category_ids(self._lm, self._cfg.filters.vod, vod_categories)
        kept_series_categories, series_ids = allowed_category_ids(
            self._lm, self._cfg.filters.series, series_categories
        )

        filtered_live = filter_by_category(live_streams, live_ids)
        filtered_vod = filter_by_category(vod_streams, vod_ids)
        filtered_series = filter_by_category(series_list, series_ids)

        for stream in filtered_live:
            stream.setdefault("stream_type", "live")
        for stream in filtered_vod:
            stream.setdefault("stream_type", "movie")

        snapshot = Snapshot(
            live_categories=kept_live_categories,
            vod_categories=kept_vod_categories,
            series_categories=kept_series_categories,
            live_streams=filtered_live,
            vod_streams=filtered_vod,
            series=filtered_series,
            allowed_live_ids={str(s.get("stream_id")) for s in filtered_live},
            allowed_vod_ids={str(s.get("stream_id")) for s in filtered_vod},
            allowed_series_ids={str(s.get("series_id")) for s in filtered_series},
            source_login=login,
            refreshed_at=time.time(),
        )

        with self._lock:
            self._snapshot = snapshot

        logger.info(
            "catalog refreshed: live %d/%d, vod %d/%d, series %d/%d",
            len(filtered_live), len(live_streams),
            len(filtered_vod), len(vod_streams),
            len(filtered_series), len(series_list),
        )

    def run(self, stop_event: threading.Event, ready_event: threading.Event, errors: list) -> None:
        """Performs the initial refresh, signals `ready_event` (whether it
        succeeded or not, with the exception appended to `errors` on
        failure), then keeps refreshing on the configured interval until
        `stop_event` is set.
        """
        try:
            self.refresh_once()
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller via `errors`
            errors.append(exc)
            ready_event.set()
            return
        ready_event.set()

        interval = self._cfg.refresh.interval_minutes * 60
        while not stop_event.wait(interval):
            try:
                self.refresh_once()
            except Exception:  # noqa: BLE001 - keep the previous snapshot and retry later
                logger.exception("catalog refresh failed, keeping previous snapshot")
