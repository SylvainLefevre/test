import copy
import tempfile
import unittest
from pathlib import Path

import yaml

from xtream_filter.config import ConfigError, load

BASE_CONFIG = {
    "source": {
        "base_url": "http://example.com:8080",
        "username": "src_user",
        "password": "src_pass",
    },
    "server": {
        "username": "local_user",
        "password": "local_pass",
    },
}


def _write(tmp_dir: str, data: dict) -> str:
    path = Path(tmp_dir) / "config.yaml"
    path.write_text(yaml.safe_dump(data))
    return str(path)


class LoadDefaultsTest(unittest.TestCase):
    def test_defaults_are_applied(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load(_write(tmp, BASE_CONFIG))
        self.assertEqual(cfg.source.timeout_seconds, 20)
        self.assertEqual(cfg.server.listen_addr, ":8081")
        self.assertEqual(cfg.refresh.interval_minutes, 30)
        self.assertEqual(cfg.streaming.mode, "redirect")
        self.assertEqual(cfg.filters.live.categories.mode, "all")
        self.assertEqual(cfg.filters.live.languages.mode, "all")


class LoadValidationTest(unittest.TestCase):
    def test_missing_source_fields_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(tmp, {"server": {"username": "a", "password": "b"}})
            with self.assertRaises(ConfigError):
                load(path)

    def test_missing_server_credentials_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(tmp, {"source": BASE_CONFIG["source"]})
            with self.assertRaises(ConfigError):
                load(path)

    def test_invalid_streaming_mode_raises(self):
        data = copy.deepcopy(BASE_CONFIG)
        data["streaming"] = {"mode": "teleport"}
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ConfigError):
                load(_write(tmp, data))

    def test_unknown_language_code_raises(self):
        data = copy.deepcopy(BASE_CONFIG)
        data["filters"] = {"live": {"languages": {"mode": "include", "codes": ["FR"]}}}
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ConfigError):
                load(_write(tmp, data))

    def test_known_language_code_is_accepted(self):
        data = copy.deepcopy(BASE_CONFIG)
        data["languages"] = {"FR": [r"(?i)^FR"]}
        data["filters"] = {"live": {"languages": {"mode": "include", "codes": ["FR"]}}}
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load(_write(tmp, data))
        self.assertEqual(cfg.filters.live.languages.codes, ["FR"])


if __name__ == "__main__":
    unittest.main()
