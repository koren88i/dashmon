"""Alert rules generator — produces Grafana Alerting YAML for a dashboard.

Generates one alert rule per panel × failure_type, plus dashboard-level
rules for slow load and health score drop.  Output is valid Grafana 9+
alerting provisioning YAML.
"""

from __future__ import annotations

from typing import Any

from probe.config import PanelProbeSpec, VariableProbeSpec

# Probe types that generate per-panel alerts.
_PANEL_PROBE_TYPES = [
    ("no_data", "No Data", "warning",
     "Panel has been returning empty results for >2 minutes. "
     "The source metric may have disappeared or the exporter may be down."),
    ("stale_data", "Stale Data", "warning",
     "Panel data has not been refreshed within the expected interval. "
     "The exporter or scrape target may be unhealthy."),
    ("query_timeout", "Query Timeout", "critical",
     "Panel query has been timing out for >2 minutes. "
     "The datasource may be overloaded or unreachable."),
    ("slow_query", "Slow Query", "warning",
     "Panel query execution time exceeds the configured threshold."),
    ("cardinality_spike", "Cardinality Spike", "warning",
     "Series count has increased significantly above baseline. "
     "This can cause incorrect aggregated values."),
    ("panel_error", "Panel Error", "critical",
     "Panel is returning errors from the datasource."),
]


def generate_alert_rules(
    dashboard: dict[str, Any],
    panels: list[PanelProbeSpec],
    variables: list[VariableProbeSpec],
) -> dict[str, Any]:
    """Generate Grafana Alerting provisioning YAML structure."""
    uid = dashboard.get("uid", "unknown")
    title = dashboard.get("title", "Unknown")

    rules: list[dict] = []

    # Per-panel × per-probe-type rules.
    for spec in panels:
        for probe_type, label, severity, description in _PANEL_PROBE_TYPES:
            rules.append(_panel_rule(uid, title, spec, probe_type, label, severity, description))

    # Per-variable rules.
    for var in variables:
        rules.append(_variable_rule(uid, title, var))

    # Dashboard-level rules.
    rules.append(_dashboard_health_rule(uid, title))
    rules.append(_dashboard_slow_load_rule(uid, title))

    return {
        "apiVersion": 1,
        "groups": [
            {
                "orgId": 1,
                "name": f"dashboard-sre-{uid}",
                "folder": "Dashboard SRE",
                "interval": "1m",
                "rules": rules,
            }
        ],
    }


# ---------------------------------------------------------------------------
# Rule builders
# ---------------------------------------------------------------------------

def _panel_rule(
    dashboard_uid: str,
    dashboard_title: str,
    spec: PanelProbeSpec,
    probe_type: str,
    probe_label: str,
    severity: str,
    description: str,
) -> dict:
    rule_uid = f"sre-{dashboard_uid}-{probe_type}-{spec.panel_id}"
    return {
        "uid": rule_uid,
        "title": f"[{dashboard_title}] Panel '{spec.panel_title}' — {probe_label}",
        "condition": "C",
        "data": [
            {
                "refId": "A",
                "queryType": "",
                "relativeTimeRange": {"from": 300, "to": 0},
                "datasourceUid": "__expr__",
                "model": {
                    "type": "math",
                    "expression": "",
                    "datasource": {"uid": "__expr__", "type": "__expr__"},
                },
            },
            {
                "refId": "B",
                "queryType": "",
                "relativeTimeRange": {"from": 300, "to": 0},
                "datasourceUid": "${datasource}",
                "model": {
                    "expr": (
                        f'dashboard_panel_status{{dashboard_uid="{dashboard_uid}", '
                        f'panel_id="{spec.panel_id}", probe_type="{probe_type}"}}'
                    ),
                    "refId": "B",
                },
            },
            {
                "refId": "C",
                "queryType": "",
                "relativeTimeRange": {"from": 300, "to": 0},
                "datasourceUid": "__expr__",
                "model": {
                    "type": "threshold",
                    "expression": "B",
                    "conditions": [
                        {
                            "evaluator": {"params": [1], "type": "lt"},
                            "operator": {"type": "and"},
                            "query": {"params": ["C"]},
                            "reducer": {"type": "last"},
                        }
                    ],
                },
            },
        ],
        "noDataState": "Alerting",
        "execErrState": "Alerting",
        "for": "2m",
        "annotations": {
            "summary": f"Panel '{spec.panel_title}' in dashboard '{dashboard_title}' — {probe_label}",
            "description": description,
        },
        "labels": {
            "severity": severity,
            "dashboard_uid": dashboard_uid,
            "panel_id": str(spec.panel_id),
            "probe_type": probe_type,
        },
    }


def _variable_rule(
    dashboard_uid: str,
    dashboard_title: str,
    var: VariableProbeSpec,
) -> dict:
    rule_uid = f"sre-{dashboard_uid}-var-{var.name}"
    return {
        "uid": rule_uid,
        "title": f"[{dashboard_title}] Variable '${var.name}' — Resolution Failed",
        "condition": "C",
        "data": [
            {
                "refId": "A",
                "queryType": "",
                "relativeTimeRange": {"from": 300, "to": 0},
                "datasourceUid": "__expr__",
                "model": {
                    "type": "math",
                    "expression": "",
                    "datasource": {"uid": "__expr__", "type": "__expr__"},
                },
            },
            {
                "refId": "B",
                "queryType": "",
                "relativeTimeRange": {"from": 300, "to": 0},
                "datasourceUid": "${datasource}",
                "model": {
                    "expr": (
                        f'dashboard_variable_status{{dashboard_uid="{dashboard_uid}", '
                        f'variable_name="{var.name}"}}'
                    ),
                    "refId": "B",
                },
            },
            {
                "refId": "C",
                "queryType": "",
                "relativeTimeRange": {"from": 300, "to": 0},
                "datasourceUid": "__expr__",
                "model": {
                    "type": "threshold",
                    "expression": "B",
                    "conditions": [
                        {
                            "evaluator": {"params": [1], "type": "lt"},
                            "operator": {"type": "and"},
                            "query": {"params": ["C"]},
                            "reducer": {"type": "last"},
                        }
                    ],
                },
            },
        ],
        "noDataState": "Alerting",
        "execErrState": "Alerting",
        "for": "2m",
        "annotations": {
            "summary": f"Variable '${var.name}' in dashboard '{dashboard_title}' failed to resolve",
            "description": (
                f"Template variable ${var.name} is returning empty results. "
                "All panels depending on this variable will show broken data."
            ),
        },
        "labels": {
            "severity": "critical",
            "dashboard_uid": dashboard_uid,
            "variable_name": var.name,
            "probe_type": "var_resolution_fail",
        },
    }


def _dashboard_health_rule(dashboard_uid: str, dashboard_title: str) -> dict:
    return {
        "uid": f"sre-{dashboard_uid}-health-drop",
        "title": f"[{dashboard_title}] Health Score Drop",
        "condition": "C",
        "data": [
            {
                "refId": "A",
                "queryType": "",
                "relativeTimeRange": {"from": 300, "to": 0},
                "datasourceUid": "__expr__",
                "model": {
                    "type": "math",
                    "expression": "",
                    "datasource": {"uid": "__expr__", "type": "__expr__"},
                },
            },
            {
                "refId": "B",
                "queryType": "",
                "relativeTimeRange": {"from": 300, "to": 0},
                "datasourceUid": "${datasource}",
                "model": {
                    "expr": f'dashboard_health_score{{dashboard_uid="{dashboard_uid}"}}',
                    "refId": "B",
                },
            },
            {
                "refId": "C",
                "queryType": "",
                "relativeTimeRange": {"from": 300, "to": 0},
                "datasourceUid": "__expr__",
                "model": {
                    "type": "threshold",
                    "expression": "B",
                    "conditions": [
                        {
                            "evaluator": {"params": [1], "type": "lt"},
                            "operator": {"type": "and"},
                            "query": {"params": ["C"]},
                            "reducer": {"type": "last"},
                        }
                    ],
                },
            },
        ],
        "noDataState": "Alerting",
        "execErrState": "Alerting",
        "for": "2m",
        "annotations": {
            "summary": f"Dashboard '{dashboard_title}' health score has dropped below 100%",
            "description": "One or more panels are reporting degraded status.",
        },
        "labels": {
            "severity": "warning",
            "dashboard_uid": dashboard_uid,
            "probe_type": "health_score",
        },
    }


def _dashboard_slow_load_rule(dashboard_uid: str, dashboard_title: str) -> dict:
    return {
        "uid": f"sre-{dashboard_uid}-slow-load",
        "title": f"[{dashboard_title}] Slow Dashboard Load",
        "condition": "C",
        "data": [
            {
                "refId": "A",
                "queryType": "",
                "relativeTimeRange": {"from": 300, "to": 0},
                "datasourceUid": "__expr__",
                "model": {
                    "type": "math",
                    "expression": "",
                    "datasource": {"uid": "__expr__", "type": "__expr__"},
                },
            },
            {
                "refId": "B",
                "queryType": "",
                "relativeTimeRange": {"from": 300, "to": 0},
                "datasourceUid": "${datasource}",
                "model": {
                    "expr": f'dashboard_load_time_seconds{{dashboard_uid="{dashboard_uid}"}}',
                    "refId": "B",
                },
            },
            {
                "refId": "C",
                "queryType": "",
                "relativeTimeRange": {"from": 300, "to": 0},
                "datasourceUid": "__expr__",
                "model": {
                    "type": "threshold",
                    "expression": "B",
                    "conditions": [
                        {
                            "evaluator": {"params": [15], "type": "gt"},
                            "operator": {"type": "and"},
                            "query": {"params": ["C"]},
                            "reducer": {"type": "last"},
                        }
                    ],
                },
            },
        ],
        "noDataState": "OK",
        "execErrState": "Alerting",
        "for": "5m",
        "annotations": {
            "summary": f"Dashboard '{dashboard_title}' is loading slowly (>15s)",
            "description": "The critical path of panel queries exceeds 15 seconds.",
        },
        "labels": {
            "severity": "warning",
            "dashboard_uid": dashboard_uid,
            "probe_type": "slow_dashboard",
        },
    }
