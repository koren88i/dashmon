"""Meta-dashboard generator — builds a Grafana dashboard JSON that monitors
the probe engine's Prometheus metrics for a given target dashboard.

The output is importable into a real Grafana instance pointed at the probe
engine's /metrics endpoint.
"""

from __future__ import annotations

from typing import Any

from probe.config import PanelProbeSpec, VariableProbeSpec

DEFAULT_METRICS_DATASOURCE_NAME = "Probe Metrics"
DEFAULT_METRICS_DATASOURCE_UID = "probe-metrics"
DEFAULT_METRICS_DATASOURCE_VARIABLE = "sre_datasource"
DEFAULT_METRICS_DATASOURCE_REF = "${sre_datasource}"

# ---------------------------------------------------------------------------
# Grafana panel-type helpers
# ---------------------------------------------------------------------------

_NEXT_ID = 0


def _id() -> int:
    global _NEXT_ID
    _NEXT_ID += 1
    return _NEXT_ID


def _reset_ids() -> None:
    global _NEXT_ID
    _NEXT_ID = 0


def _stat_panel(
    title: str,
    expr: str,
    grid: dict,
    *,
    description: str = "",
    unit: str = "",
    thresholds: list[dict] | None = None,
    color_mode: str = "background",
    decimals: int | None = None,
    no_value: str = "N/A",
) -> dict:
    th = thresholds or [
        {"color": "green", "value": None},
        {"color": "red", "value": 80},
    ]
    overrides: dict[str, Any] = {}
    if unit:
        overrides["unit"] = unit
    if decimals is not None:
        overrides["decimals"] = decimals
    panel = {
        "id": _id(),
        "title": title,
        "type": "stat",
        "gridPos": grid,
        "datasource": {"uid": DEFAULT_METRICS_DATASOURCE_REF, "type": "prometheus"},
        "targets": [{"refId": "A", "expr": expr}],
        "options": {
            "colorMode": color_mode,
            "graphMode": "none",
            "textMode": "auto",
            "reduceOptions": {"calcs": ["lastNotNull"]},
        },
        "fieldConfig": {
            "defaults": {
                "thresholds": {"mode": "absolute", "steps": th},
                "noValue": no_value,
                **overrides,
            },
            "overrides": [],
        },
    }
    if description:
        panel["description"] = description
    return panel


def _timeseries_panel(
    title: str,
    targets: list[dict],
    grid: dict,
    *,
    unit: str = "s",
) -> dict:
    return {
        "id": _id(),
        "title": title,
        "type": "timeseries",
        "gridPos": grid,
        "datasource": {"uid": DEFAULT_METRICS_DATASOURCE_REF, "type": "prometheus"},
        "targets": targets,
        "fieldConfig": {
            "defaults": {"unit": unit},
            "overrides": [],
        },
        "options": {"tooltip": {"mode": "multi"}},
    }


def _table_panel(
    title: str,
    expr: str,
    grid: dict,
    *,
    unit: str = "",
    transformations: list[dict] | None = None,
    field_overrides: list[dict] | None = None,
) -> dict:
    defaults: dict[str, Any] = {}
    if unit:
        defaults["unit"] = unit
    return {
        "id": _id(),
        "title": title,
        "type": "table",
        "gridPos": grid,
        "datasource": {"uid": DEFAULT_METRICS_DATASOURCE_REF, "type": "prometheus"},
        "targets": [{"refId": "A", "expr": expr, "format": "table", "instant": True}],
        "options": {},
        "fieldConfig": {"defaults": defaults, "overrides": field_overrides or []},
        "transformations": transformations or [],
    }


def _row(title: str, y: int, collapsed: bool = False) -> dict:
    return {
        "id": _id(),
        "title": title,
        "type": "row",
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": y},
        "collapsed": collapsed,
        "panels": [],
    }


def _alertlist_panel(title: str, grid: dict, dashboard_uid: str) -> dict:
    return {
        "id": _id(),
        "title": title,
        "type": "alertlist",
        "gridPos": grid,
        "datasource": {"uid": "-- Grafana --", "type": "datasource"},
        "options": {
            "showOptions": "current",
            "maxItems": 20,
            "sortOrder": 1,
            "alertName": "",
            "dashboardAlerts": False,
            "stateFilter": {"firing": True, "pending": True, "noData": True,
                            "normal": False, "error": True},
            "folder": None,
            "alertInstanceLabelFilter": f'dashboard_uid="{dashboard_uid}"',
        },
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_meta_dashboard(
    dashboard: dict[str, Any],
    panels: list[PanelProbeSpec],
    variables: list[VariableProbeSpec],
) -> dict[str, Any]:
    """Generate a Grafana meta-dashboard JSON for *dashboard*."""
    _reset_ids()

    uid = dashboard.get("uid", "unknown")
    title = dashboard.get("title", "Unknown")
    meta_uid = f"sre-{uid}"

    all_panels: list[dict] = []
    y = 0

    # ---- Row 1: Overview ----
    all_panels.append(_row("Overview", y))
    y += 1
    all_panels.extend(_overview_panels(uid, y))
    y += 4

    # ---- Row 2: Panel health grid ----
    all_panels.append(_row("Panel Health", y))
    y += 1
    all_panels.extend(_panel_health_grid(uid, panels, y))
    grid_rows = (len(panels) + 5) // 6  # 6 panels per row, 4h each
    y += grid_rows * 4

    # ---- Row 3: Probe layers ----
    all_panels.append(_row("Probe Layers", y))
    y += 1
    all_panels.extend(_probe_layer_panels(uid, y))
    y += 4

    # ---- Row 4: Query performance ----
    all_panels.append(_row("Query Performance", y))
    y += 1
    all_panels.extend(_query_performance_panels(uid, panels, y))
    y += 8

    # ---- Row 5: Variable health ----
    if variables:
        all_panels.append(_row("Variable Health", y))
        y += 1
        all_panels.extend(_variable_health_panels(uid, variables, y))
        y += 8

    # ---- Row 6: Issue log ----
    all_panels.append(_row("Issue Log", y))
    y += 1
    all_panels.append(_table_panel(
        "Recent Issue Events",
        f'dashboard_issue_event_timestamp_seconds{{dashboard_uid="{uid}"}} * 1000',
        {"h": 8, "w": 24, "x": 0, "y": y},
        transformations=[
            {
                "id": "sortBy",
                "options": {
                    "fields": {},
                    "sort": [{"field": "Value", "desc": True}],
                },
            },
            {
                "id": "organize",
                "options": {
                "excludeByName": {
                    "Time": True,
                    "__name__": True,
                    "dashboard_uid": True,
                    "event_id": True,
                        "instance": True,
                        "job": True,
                        "panel_id": True,
                },
                "indexByName": {
                    "Value": 0,
                    "panel_title": 1,
                    "probe_type": 2,
                    "error_type": 3,
                    "message": 4,
                },
                "renameByName": {
                    "Value": "Event Time",
                    "panel_title": "Panel",
                    "probe_type": "Path",
                    "error_type": "Type",
                    "message": "Message",
                },
            },
            },
        ],
        field_overrides=[
            {
                "matcher": {"id": "byName", "options": "Event Time"},
                "properties": [{"id": "unit", "value": "dateTimeAsIso"}],
            },
        ],
    ))
    y += 8

    # ---- Row 7: Alerts ----
    all_panels.append(_row("Alerts", y))
    y += 1
    all_panels.append(_alertlist_panel(
        "Active Alerts",
        {"h": 8, "w": 24, "x": 0, "y": y},
        uid,
    ))
    y += 8

    return {
        "id": None,
        "uid": meta_uid,
        "title": f"[SRE] {title}",
        "description": f"Meta-dashboard monitoring the health of '{title}'",
        "schemaVersion": 39,
        "version": 1,
        "timezone": "browser",
        "editable": True,
        "graphTooltip": 1,
        "time": {"from": "now-1h", "to": "now"},
        "refresh": "10s",
        "templating": {
            "list": [
                {
                    "name": DEFAULT_METRICS_DATASOURCE_VARIABLE,
                    "type": "datasource",
                    "query": "prometheus",
                    "current": {
                        "selected": True,
                        "text": DEFAULT_METRICS_DATASOURCE_NAME,
                        "value": DEFAULT_METRICS_DATASOURCE_UID,
                    },
                    "hide": 0,
                }
            ]
        },
        "panels": all_panels,
    }


# ---------------------------------------------------------------------------
# Row builders
# ---------------------------------------------------------------------------

def _overview_panels(uid: str, y: int) -> list[dict]:
    return [
        _stat_panel(
            "Health Score",
            f'dashboard_health_score{{dashboard_uid="{uid}"}}',
            {"h": 4, "w": 6, "x": 0, "y": y},
            unit="percentunit",
            decimals=0,
            thresholds=[
                {"color": "red", "value": None},
                {"color": "yellow", "value": 0.8},
                {"color": "green", "value": 1.0},
            ],
        ),
        _stat_panel(
            "Active Issues",
            f'dashboard_issue_count{{dashboard_uid="{uid}"}}',
            {"h": 4, "w": 6, "x": 6, "y": y},
            thresholds=[
                {"color": "green", "value": None},
                {"color": "yellow", "value": 1},
                {"color": "red", "value": 3},
            ],
        ),
        _stat_panel(
            "Estimated Load Time",
            f'dashboard_load_time_seconds{{dashboard_uid="{uid}"}}',
            {"h": 4, "w": 6, "x": 12, "y": y},
            unit="s",
            decimals=1,
            thresholds=[
                {"color": "green", "value": None},
                {"color": "yellow", "value": 5},
                {"color": "red", "value": 15},
            ],
        ),
        _stat_panel(
            "Last Probe Run",
            f'time() - dashboard_last_probe_timestamp{{dashboard_uid="{uid}"}}',
            {"h": 4, "w": 6, "x": 18, "y": y},
            unit="s",
            decimals=0,
            thresholds=[
                {"color": "green", "value": None},
                {"color": "yellow", "value": 30},
                {"color": "red", "value": 60},
            ],
            no_value="No data yet",
        ),
    ]


def _panel_health_grid(
    uid: str,
    panels: list[PanelProbeSpec],
    y: int,
) -> list[dict]:
    """One stat panel per target dashboard panel — green/red."""
    result = []
    cols = 6
    w = 24 // cols
    for i, spec in enumerate(panels):
        col = i % cols
        row = i // cols
        result.append(_stat_panel(
            spec.panel_title,
            f'min(dashboard_panel_status{{dashboard_uid="{uid}", panel_id="{spec.panel_id}"}}) or vector(1)',
            {"h": 4, "w": w, "x": col * w, "y": y + row * 4},
            thresholds=[
                {"color": "red", "value": None},
                {"color": "green", "value": 1},
            ],
        ))
    return result


def _probe_layer_panels(uid: str, y: int) -> list[dict]:
    return [
        _stat_panel(
            "Datasource API",
            f'min(dashboard_panel_status{{dashboard_uid="{uid}", probe_type="datasource_api"}})',
            {"h": 4, "w": 8, "x": 0, "y": y},
            description=(
                "Probe engine queries the target datasource or proxy directly with "
                "Prometheus GET /api/v1/query. This turns red when the direct "
                "datasource path returns errors or no usable data."
            ),
            thresholds=[
                {"color": "red", "value": None},
                {"color": "green", "value": 1},
            ],
        ),
        _stat_panel(
            "Grafana Panel Path",
            f'min(dashboard_panel_status{{dashboard_uid="{uid}", probe_type="grafana_panel_path"}})',
            {"h": 4, "w": 8, "x": 8, "y": y},
            description=(
                "Probe engine asks Grafana /api/ds/query to run the panel query "
                "through Grafana's datasource plugin path. This catches user-facing "
                "panel failures even when the direct datasource query is healthy."
            ),
            thresholds=[
                {"color": "red", "value": None},
                {"color": "green", "value": 1},
            ],
        ),
        _stat_panel(
            "Variable Dependency",
            f'min(dashboard_panel_status{{dashboard_uid="{uid}", probe_type="variable_dependency"}}) or vector(1)',
            {"h": 4, "w": 8, "x": 16, "y": y},
            description=(
                "Probe engine maps failed dashboard variables back to panels that "
                "reference them. This turns red when a panel is user-blocked by "
                "variable interpolation even though underlying data queries may be healthy."
            ),
            thresholds=[
                {"color": "red", "value": None},
                {"color": "green", "value": 1},
            ],
        ),
    ]


def _query_performance_panels(
    uid: str,
    panels: list[PanelProbeSpec],
    y: int,
) -> list[dict]:
    targets_p50 = []
    targets_p95 = []
    for spec in panels:
        pid = str(spec.panel_id)
        targets_p50.append({
            "refId": f"p50_{pid}",
            "expr": f'histogram_quantile(0.5, rate(dashboard_panel_query_duration_seconds_bucket{{dashboard_uid="{uid}", panel_id="{pid}"}}[5m]))',
            "legendFormat": f"{spec.panel_title} p50",
        })
        targets_p95.append({
            "refId": f"p95_{pid}",
            "expr": f'histogram_quantile(0.95, rate(dashboard_panel_query_duration_seconds_bucket{{dashboard_uid="{uid}", panel_id="{pid}"}}[5m]))',
            "legendFormat": f"{spec.panel_title} p95",
        })

    return [
        _timeseries_panel(
            "Query Duration — p50 / p95",
            targets_p50 + targets_p95,
            {"h": 8, "w": 16, "x": 0, "y": y},
        ),
        {
            "id": _id(),
            "title": "Query Duration Heatmap",
            "type": "heatmap",
            "gridPos": {"h": 8, "w": 8, "x": 16, "y": y},
            "datasource": {"uid": DEFAULT_METRICS_DATASOURCE_REF, "type": "prometheus"},
            "targets": [{
                "refId": "A",
                "expr": f'sum(increase(dashboard_panel_query_duration_seconds_bucket{{dashboard_uid="{uid}"}}[5m])) by (le)',
                "format": "heatmap",
                "legendFormat": "{{le}}",
            }],
            "options": {"calculate": False, "yAxis": {"unit": "s"}},
        },
    ]


def _variable_health_panels(
    uid: str,
    variables: list[VariableProbeSpec],
    y: int,
) -> list[dict]:
    result: list[dict] = []
    w = min(8, 24 // max(len(variables), 1))

    # Stat panels per variable.
    for i, var in enumerate(variables):
        result.append(_stat_panel(
            f"${var.name}",
            f'dashboard_variable_status{{dashboard_uid="{uid}", variable_name="{var.name}"}}',
            {"h": 4, "w": w, "x": i * w, "y": y},
            thresholds=[
                {"color": "red", "value": None},
                {"color": "green", "value": 1},
            ],
        ))

    # Timeseries: variable query duration.
    var_targets = []
    for var in variables:
        var_targets.append({
            "refId": var.name,
            "expr": f'histogram_quantile(0.95, rate(dashboard_variable_query_duration_seconds_bucket{{dashboard_uid="{uid}", variable_name="{var.name}"}}[5m]))',
            "legendFormat": f"${var.name} p95",
        })
    result.append(_timeseries_panel(
        "Variable Query Duration",
        var_targets,
        {"h": 4, "w": 8, "x": 0, "y": y + 4},
    ))
    result.append(_table_panel(
        "Variable Error Types",
        f'sum by (variable_name, error_type) '
        f'(increase(dashboard_variable_error_total{{dashboard_uid="{uid}"}}[1h]))',
        {"h": 4, "w": 8, "x": 8, "y": y + 4},
        transformations=[
            {
                "id": "organize",
                "options": {
                    "excludeByName": {"Time": True},
                    "indexByName": {
                        "variable_name": 0,
                        "error_type": 1,
                        "Value": 2,
                    },
                    "renameByName": {
                        "variable_name": "Variable",
                        "error_type": "Type",
                        "Value": "Events",
                    },
                },
            },
        ],
    ))
    result.append(_table_panel(
        "Variable Blast Radius",
        f'dashboard_variable_dependency_impact{{dashboard_uid="{uid}"}} == 1',
        {"h": 4, "w": 8, "x": 16, "y": y + 4},
        transformations=[
            {
                "id": "organize",
                "options": {
                    "excludeByName": {
                        "Time": True,
                        "__name__": True,
                        "dashboard_uid": True,
                        "panel_id": True,
                    },
                    "indexByName": {
                        "variable_name": 0,
                        "panel_title": 1,
                        "error_type": 2,
                        "Value": 3,
                    },
                    "renameByName": {
                        "variable_name": "Variable",
                        "panel_title": "Panel",
                        "error_type": "Variable Error",
                        "Value": "Impacted",
                    },
                },
            },
        ],
    ))

    return result
