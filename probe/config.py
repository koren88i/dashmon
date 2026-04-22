"""Probe configuration and data structures.

PanelProbeSpec / VariableProbeSpec are the intermediate representation
produced by the parser and consumed by probes + generators.

ProbeConfig holds runtime thresholds loaded from config.yaml.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Probe specs (parser output)
# ---------------------------------------------------------------------------

@dataclass
class PanelProbeSpec:
    panel_id: int
    panel_title: str
    datasource_uid: str
    datasource_type: str
    queries: list[str]
    expected_min_series: int = 1
    raw_queries: list[str] = field(default_factory=list)
    variable_dependencies: list[str] = field(default_factory=list)


@dataclass
class VariableProbeSpec:
    name: str
    datasource_uid: str
    query: str
    is_chained: bool = False
    chain_depth: int = 0


# ---------------------------------------------------------------------------
# Probe results
# ---------------------------------------------------------------------------

class ErrorType(str, Enum):
    NO_DATA = "no_data"
    STALE_DATA = "stale_data"
    METRIC_RENAME = "metric_rename"
    QUERY_TIMEOUT = "query_timeout"
    VAR_RESOLUTION_FAIL = "var_resolution_fail"
    VARIABLE_QUERY_ERROR = "variable_query_error"
    BLOCKED_BY_VARIABLE = "blocked_by_variable"
    SLOW_QUERY = "slow_query"
    SLOW_DASHBOARD = "slow_dashboard"
    CARDINALITY_SPIKE = "cardinality_spike"
    PANEL_ERROR = "panel_error"


class ProbeStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


@dataclass
class ProbeResult:
    panel_id: int
    panel_title: str
    status: ProbeStatus
    probe_type: str = "datasource_api"
    error_type: ErrorType | None = None
    message: str = ""
    duration_seconds: float = 0.0
    series_count: int = 0
    max_timestamp: float | None = None


# ---------------------------------------------------------------------------
# Datasource mapping
# ---------------------------------------------------------------------------

@dataclass
class DatasourceConfig:
    uid: str
    url: str
    ds_type: str = "prometheus"


@dataclass
class GrafanaProbeConfig:
    enabled: bool = False
    url: str = "http://localhost:3000"
    query_range_seconds: float = 3600.0
    step_seconds: float = 30.0
    max_data_points: int = 1200


# ---------------------------------------------------------------------------
# Runtime config
# ---------------------------------------------------------------------------

@dataclass
class ProbeConfig:
    probe_interval_seconds: float = 15.0
    max_concurrency: int = 10
    slow_query_seconds: float = 5.0
    slow_dashboard_seconds: float = 15.0
    stale_data_multiplier: float = 3.0
    scrape_interval_seconds: float = 15.0
    cardinality_spike_ratio: float = 1.5
    query_timeout_seconds: float = 25.0
    datasources: list[DatasourceConfig] = field(default_factory=list)
    grafana: GrafanaProbeConfig = field(default_factory=GrafanaProbeConfig)

    @classmethod
    def defaults(cls) -> ProbeConfig:
        return cls(
            datasources=[
                DatasourceConfig(
                    uid="prometheus-main",
                    url="http://localhost:9090",
                ),
            ],
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProbeConfig:
        thresholds = data.get("thresholds", {})
        ds_list = [
            DatasourceConfig(
                uid=d["uid"],
                url=d["url"],
                ds_type=d.get("type", "prometheus"),
            )
            for d in data.get("datasources", [])
        ]
        grafana_data = data.get("grafana", {}) or {}
        return cls(
            probe_interval_seconds=data.get("probe_interval_seconds", 15.0),
            max_concurrency=data.get("max_concurrency", 10),
            slow_query_seconds=thresholds.get("slow_query_seconds", 5.0),
            slow_dashboard_seconds=thresholds.get("slow_dashboard_seconds", 15.0),
            stale_data_multiplier=thresholds.get("stale_data_multiplier", 3.0),
            scrape_interval_seconds=thresholds.get("scrape_interval_seconds", 15.0),
            cardinality_spike_ratio=thresholds.get("cardinality_spike_ratio", 1.5),
            query_timeout_seconds=thresholds.get("query_timeout_seconds", 25.0),
            datasources=ds_list,
            grafana=GrafanaProbeConfig(
                enabled=grafana_data.get("enabled", False),
                url=grafana_data.get("url", "http://localhost:3000"),
                query_range_seconds=grafana_data.get("query_range_seconds", 3600.0),
                step_seconds=grafana_data.get("step_seconds", 30.0),
                max_data_points=grafana_data.get("max_data_points", 1200),
            ),
        )

    def url_for_datasource(self, uid: str) -> str | None:
        for ds in self.datasources:
            if ds.uid == uid:
                return ds.url
        return None
