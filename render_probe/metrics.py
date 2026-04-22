"""Prometheus metrics for browser render probe results."""

from __future__ import annotations

import time

from prometheus_client import Counter, Gauge, CollectorRegistry

from render_probe.probe import RenderProbeResult


REGISTRY = CollectorRegistry()

RENDER_STATUS = Gauge(
    "dashboard_render_status",
    "1 when the browser-rendered dashboard is healthy, 0 when degraded",
    ["dashboard_uid"],
    registry=REGISTRY,
)

RENDER_TIME = Gauge(
    "dashboard_render_time_seconds",
    "Browser-observed time for the full Grafana dashboard to render",
    ["dashboard_uid"],
    registry=REGISTRY,
)

RENDER_LAST_PROBE_TIMESTAMP = Gauge(
    "dashboard_render_last_probe_timestamp",
    "Unix epoch of the most recent completed browser render probe",
    ["dashboard_uid"],
    registry=REGISTRY,
)

RENDER_ERROR_TOTAL = Counter(
    "dashboard_render_error_total",
    "Cumulative browser render probe failures",
    ["dashboard_uid", "error_type"],
    registry=REGISTRY,
)


def record_result(result: RenderProbeResult) -> None:
    labels = {"dashboard_uid": result.dashboard_uid}
    RENDER_STATUS.labels(**labels).set(1.0 if result.status == "healthy" else 0.0)
    RENDER_TIME.labels(**labels).set(result.duration_seconds)
    RENDER_LAST_PROBE_TIMESTAMP.labels(**labels).set(result.timestamp or time.time())
    if result.status != "healthy" and result.error_type:
        RENDER_ERROR_TOTAL.labels(result.dashboard_uid, result.error_type).inc()

