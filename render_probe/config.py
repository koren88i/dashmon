"""Configuration helpers for the browser render probe."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Mapping
from urllib.parse import quote


DEFAULT_RENDER_PROBE_PORT = 8012
DEFAULT_DOCKER_GRAFANA_URL = "http://grafana:3000"
DEFAULT_LOCAL_GRAFANA_URL = "http://localhost:3000"


@dataclass(frozen=True)
class RenderTarget:
    key: str
    title: str
    dashboard_uid: str
    url: str


@dataclass(frozen=True)
class RenderProbeSettings:
    enabled: bool = True
    interval_seconds: float = 15.0
    timeout_seconds: float = 15.0
    slow_render_seconds: float = 10.0
    max_concurrency: int = 2
    grafana_url: str = DEFAULT_DOCKER_GRAFANA_URL
    url_mode: str = "docker"
    targets: list[RenderTarget] = field(default_factory=list)


def settings_from_registry(
    registry: Mapping[str, Any],
    *,
    env: Mapping[str, str] | None = None,
) -> RenderProbeSettings:
    """Build render probe settings from dashboard_targets.yaml data."""
    env = env if env is not None else os.environ
    defaults = registry.get("render_probe_defaults", {}) or {}
    grafana_defaults = defaults.get("grafana", {}) or {}
    url_mode = env.get("RENDER_PROBE_URL_MODE", str(defaults.get("url_mode", "docker")))
    default_grafana_url = (
        grafana_defaults.get("docker_url", DEFAULT_DOCKER_GRAFANA_URL)
        if url_mode == "docker"
        else grafana_defaults.get("local_url", DEFAULT_LOCAL_GRAFANA_URL)
    )
    grafana_url = env.get("RENDER_PROBE_GRAFANA_URL", default_grafana_url)

    return RenderProbeSettings(
        enabled=_env_bool(env, "RENDER_PROBE_ENABLED", defaults.get("enabled", True)),
        interval_seconds=_env_float(env, "RENDER_PROBE_INTERVAL_SECONDS", defaults.get("interval_seconds", 15.0)),
        timeout_seconds=_env_float(env, "RENDER_PROBE_TIMEOUT_SECONDS", defaults.get("timeout_seconds", 15.0)),
        slow_render_seconds=_env_float(env, "RENDER_PROBE_SLOW_SECONDS", defaults.get("slow_render_seconds", 10.0)),
        max_concurrency=_env_int(env, "RENDER_PROBE_MAX_CONCURRENCY", defaults.get("max_concurrency", 2)),
        grafana_url=grafana_url,
        url_mode=url_mode,
        targets=[
            target_from_registry(item, grafana_url)
            for item in registry.get("targets", [])
        ],
    )


def target_from_registry(target: Mapping[str, Any], grafana_url: str) -> RenderTarget:
    title = str(target["title"])
    uid = str(target["dashboard_uid"])
    return RenderTarget(
        key=str(target["key"]),
        title=title,
        dashboard_uid=uid,
        url=dashboard_url(grafana_url, uid, title),
    )


def dashboard_url(grafana_url: str, dashboard_uid: str, title: str) -> str:
    slug = slugify(title)
    base = grafana_url.rstrip("/")
    uid = quote(dashboard_uid, safe="")
    return f"{base}/d/{uid}/{slug}?orgId=1&from=now-1h&to=now&refresh=off&kiosk"


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "dashboard"


def _env_bool(env: Mapping[str, str], key: str, default: Any) -> bool:
    raw = env.get(key)
    if raw is None:
        return bool(default)
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(env: Mapping[str, str], key: str, default: Any) -> float:
    raw = env.get(key)
    return float(raw if raw is not None else default)


def _env_int(env: Mapping[str, str], key: str, default: Any) -> int:
    raw = env.get(key)
    return int(raw if raw is not None else default)

