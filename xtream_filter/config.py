"""Loads and validates the xtream-filter YAML configuration."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

import yaml

VALID_MODES = {"all", "include", "exclude"}


class ConfigError(Exception):
    """Raised when the config file is missing required fields or invalid."""


@dataclass
class SourceConfig:
    base_url: str
    username: str
    password: str
    timeout_seconds: int = 20


@dataclass
class ServerConfig:
    listen_addr: str = ":8081"
    username: str = ""
    password: str = ""
    public_base_url: str = ""


@dataclass
class RefreshConfig:
    interval_minutes: int = 30


@dataclass
class StreamingConfig:
    # "redirect": HTTP 302 to the real source URL (default, near-zero cost
    # on a Raspberry Pi). "proxy": relay every byte through this process.
    mode: str = "redirect"


@dataclass
class CategoryFilter:
    mode: str = "all"  # all | include | exclude
    names: List[str] = field(default_factory=list)


@dataclass
class LanguageFilter:
    mode: str = "all"  # all | include | exclude
    codes: List[str] = field(default_factory=list)


@dataclass
class SectionFilter:
    categories: CategoryFilter = field(default_factory=CategoryFilter)
    languages: LanguageFilter = field(default_factory=LanguageFilter)


@dataclass
class FiltersConfig:
    live: SectionFilter = field(default_factory=SectionFilter)
    vod: SectionFilter = field(default_factory=SectionFilter)
    series: SectionFilter = field(default_factory=SectionFilter)


@dataclass
class Config:
    source: SourceConfig
    server: ServerConfig
    refresh: RefreshConfig
    streaming: StreamingConfig
    filters: FiltersConfig
    languages: Dict[str, List[str]]


def _section_filter_from_dict(raw: dict) -> SectionFilter:
    cats = raw.get("categories") or {}
    langs = raw.get("languages") or {}
    return SectionFilter(
        categories=CategoryFilter(
            mode=cats.get("mode") or "all",
            names=list(cats.get("names") or []),
        ),
        languages=LanguageFilter(
            mode=langs.get("mode") or "all",
            codes=list(langs.get("codes") or []),
        ),
    )


def load(path: str) -> Config:
    try:
        raw = yaml.safe_load(Path(path).read_text()) or {}
    except OSError as exc:
        raise ConfigError(f"reading config file {path!r}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"parsing config file {path!r}: {exc}") from exc

    source_raw = raw.get("source") or {}
    if not source_raw.get("base_url") or not source_raw.get("username") or not source_raw.get("password"):
        raise ConfigError("source.base_url, source.username and source.password are required")
    source = SourceConfig(
        base_url=source_raw["base_url"],
        username=source_raw["username"],
        password=source_raw["password"],
        timeout_seconds=int(source_raw.get("timeout_seconds") or 20),
    )

    server_raw = raw.get("server") or {}
    if not server_raw.get("username") or not server_raw.get("password"):
        raise ConfigError(
            "server.username and server.password are required "
            "(credentials for the republished API)"
        )
    server = ServerConfig(
        listen_addr=server_raw.get("listen_addr") or ":8081",
        username=server_raw["username"],
        password=server_raw["password"],
        public_base_url=server_raw.get("public_base_url") or "",
    )

    refresh = RefreshConfig(interval_minutes=int((raw.get("refresh") or {}).get("interval_minutes") or 30))

    streaming_mode = (raw.get("streaming") or {}).get("mode") or "redirect"
    if streaming_mode not in ("redirect", "proxy"):
        raise ConfigError('streaming.mode must be either "redirect" or "proxy"')
    streaming = StreamingConfig(mode=streaming_mode)

    filters_raw = raw.get("filters") or {}
    filters = FiltersConfig(
        live=_section_filter_from_dict(filters_raw.get("live") or {}),
        vod=_section_filter_from_dict(filters_raw.get("vod") or {}),
        series=_section_filter_from_dict(filters_raw.get("series") or {}),
    )

    languages = {code: list(patterns) for code, patterns in (raw.get("languages") or {}).items()}

    for name, sf in (("live", filters.live), ("vod", filters.vod), ("series", filters.series)):
        if sf.categories.mode not in VALID_MODES:
            raise ConfigError(f"filters.{name}.categories.mode must be one of all|include|exclude")
        if sf.languages.mode not in VALID_MODES:
            raise ConfigError(f"filters.{name}.languages.mode must be one of all|include|exclude")
        for code in sf.languages.codes:
            if code not in languages:
                raise ConfigError(
                    f"filters.{name}.languages.codes references unknown language {code!r} "
                    "(declare it under top-level languages:)"
                )

    return Config(
        source=source,
        server=server,
        refresh=refresh,
        streaming=streaming,
        filters=filters,
        languages=languages,
    )
