"""Entry point: `python3 -m xtream_filter --config config.yaml`."""

import argparse
import logging
import signal
import sys
import threading
from types import FrameType
from typing import Optional

from .config import ConfigError, load as load_config
from .filters import LanguageMatcher
from .server import build_server
from .store import Store
from .xtream_client import Client


def main(argv: Optional[list] = None) -> None:
    parser = argparse.ArgumentParser(prog="xtream-filter")
    parser.add_argument("--config", default="config.yaml", help="path to config.yaml")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        logging.error("config error: %s", exc)
        sys.exit(1)

    language_matcher = LanguageMatcher.compile(cfg.languages)
    client = Client(cfg.source.base_url, cfg.source.username, cfg.source.password, cfg.source.timeout_seconds)
    store = Store(client, cfg, language_matcher)

    stop_event = threading.Event()
    ready_event = threading.Event()
    errors: list = []
    refresher = threading.Thread(
        target=store.run, args=(stop_event, ready_event, errors), daemon=True, name="catalog-refresher"
    )
    refresher.start()

    # Wait for the first refresh (or its failure) before serving, so the
    # very first requests don't race an empty snapshot.
    ready_event.wait()
    if errors:
        logging.error("initial catalog refresh failed: %s", errors[0])
        sys.exit(1)

    httpd = build_server(cfg, store, client)

    def _handle_signal(signum: int, frame: Optional[FrameType]) -> None:
        logging.info("shutting down...")
        stop_event.set()
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    logging.info("xtream-filter listening on %s", cfg.server.listen_addr)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
