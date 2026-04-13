"""Prometheus metrics exposition for the probe engine.

All metrics use the dashboard_uid label to scope to a single dashboard.
Panel-level metrics add panel_id and panel_title.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, CollectorRegistry

# Dedicated registry so we don't mix with default process metrics.
REGISTRY = CollectorRegistry()

# ---------------------------------------------------------------------------
# Panel-level metrics
# ---------------------------------------------------------------------------

PANEL_STATUS = Gauge(
    "dashboard_panel_status",
    "Panel probe status (1=healthy, 0=degraded)",
    ["dashboard_uid", "panel_id", "panel_title", "probe_type"],
    registry=REGISTRY,
)

PANEL_QUERY_DURATION = Histogram(
    "dashboard_panel_query_duration_seconds",
    "Panel query execution time",
    ["dashboard_uid", "panel_id", "panel_title"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 25.0),
    registry=REGISTRY,
)

PANEL_SERIES_COUNT = Gauge(
    "dashboard_panel_series_count",
    "Number of time series returned by panel query",
    ["dashboard_uid", "panel_id", "panel_title"],
    registry=REGISTRY,
)

PANEL_LAST_DATAPOINT_AGE = Gauge(
    "dashboard_panel_last_datapoint_age_seconds",
    "Seconds since most recent data point in panel query result",
    ["dashboard_uid", "panel_id", "panel_title"],
    registry=REGISTRY,
)

PANEL_ERROR_TOTAL = Counter(
    "dashboard_panel_error_total",
    "Total panel errors by type",
    ["dashboard_uid", "panel_id", "panel_title", "error_type"],
    registry=REGISTRY,
)

# ---------------------------------------------------------------------------
# Variable-level metrics
# ---------------------------------------------------------------------------

VARIABLE_STATUS = Gauge(
    "dashboard_variable_status",
    "Variable resolution status (1=populated, 0=empty/failed)",
    ["dashboard_uid", "variable_name"],
    registry=REGISTRY,
)

VARIABLE_ERROR_TOTAL = Counter(
    "dashboard_variable_error_total",
    "Total variable resolution errors by type",
    ["dashboard_uid", "variable_name", "error_type"],
    registry=REGISTRY,
)

VARIABLE_QUERY_DURATION = Histogram(
    "dashboard_variable_query_duration_seconds",
    "Variable query execution time",
    ["dashboard_uid", "variable_name"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    registry=REGISTRY,
)

# ---------------------------------------------------------------------------
# Dashboard-level metrics
# ---------------------------------------------------------------------------

HEALTH_SCORE = Gauge(
    "dashboard_health_score",
    "Fraction of panels and variables currently healthy (0-1)",
    ["dashboard_uid"],
    registry=REGISTRY,
)

ISSUE_COUNT = Gauge(
    "dashboard_issue_count",
    "Number of currently degraded panels and variables",
    ["dashboard_uid"],
    registry=REGISTRY,
)

ISSUE_EVENT_TIMESTAMP = Gauge(
    "dashboard_issue_event_timestamp_seconds",
    "Timestamp of recent issue state transitions",
    ["dashboard_uid", "event_id", "panel_id", "panel_title", "error_type", "message"],
    registry=REGISTRY,
)

LOAD_TIME = Gauge(
    "dashboard_load_time_seconds",
    "Estimated total dashboard load time (critical path of parallel queries)",
    ["dashboard_uid"],
    registry=REGISTRY,
)

LAST_PROBE_TIMESTAMP = Gauge(
    "dashboard_last_probe_timestamp",
    "Unix epoch of the most recent completed probe run",
    ["dashboard_uid"],
    registry=REGISTRY,
)
