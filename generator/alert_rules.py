"""Alert rules generator — produces Grafana Alerting YAML for a dashboard.

Generates one alert rule per panel × failure_type, plus dashboard-level
rules for slow load and health score drop.  Output is valid Grafana 9+
alerting provisioning YAML.
"""

from __future__ import annotations

from typing import Any

from probe.config import PanelProbeSpec, VariableProbeSpec

ALERT_DATASOURCE_UID = "probe-metrics"

# Short codes for UIDs — Grafana enforces a 40-char limit on rule UIDs.
_UID_SHORT: dict[str, str] = {
    "no_data": "nd", "stale_data": "sd", "query_timeout": "qt",
    "slow_query": "sq", "cardinality_spike": "cs", "panel_error": "pe",
    "var_resolution_fail": "vf", "health_score": "hs", "slow_dashboard": "sl",
    "datasource_api": "da", "grafana_panel_path": "gp",
    "variable_dependency": "vd",
}

# Probe types that generate per-panel alerts.
_PANEL_PROBE_TYPES = [
    ("datasource_api", "Datasource API", "critical",
     "Raw datasource API checks are failing for this panel."),
    ("grafana_panel_path", "Grafana Panel Path", "critical",
     "Grafana's datasource plugin path is failing for this panel, even if raw datasource checks pass."),
    ("variable_dependency", "Variable Dependency", "critical",
     "Panel depends on a failed dashboard variable. The underlying data may be healthy, "
     "but the user-facing dashboard query cannot be rendered with the failed variable."),
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


def _classic_condition(expression: str, evaluator_type: str, value: int) -> dict[str, Any]:
    return {
        "type": "classic_conditions",
        "refId": "C",
        "expression": expression,
        "datasource": {"uid": "__expr__", "type": "__expr__"},
        "conditions": [
            {
                "type": "query",
                "query": {"params": ["B"]},
                "reducer": {"params": [], "type": "last"},
                "evaluator": {"params": [value], "type": evaluator_type},
                "operator": {"type": "and"},
            }
        ],
    }


def generate_alert_rules(
    dashboard: dict[str, Any],
    panels: list[PanelProbeSpec],
    variables: list[VariableProbeSpec],
    *,
    datasource_uid: str = ALERT_DATASOURCE_UID,
) -> dict[str, Any]:
    """Generate Grafana Alerting provisioning YAML structure."""
    uid = dashboard.get("uid", "unknown")
    title = dashboard.get("title", "Unknown")

    rules: list[dict] = []

    # Per-panel × per-probe-type rules.
    for spec in panels:
        for probe_type, label, severity, description in _PANEL_PROBE_TYPES:
            rules.append(
                _panel_rule(
                    uid,
                    title,
                    spec,
                    probe_type,
                    label,
                    severity,
                    description,
                    datasource_uid,
                )
            )

    # Per-variable rules.
    for var in variables:
        rules.append(_variable_rule(uid, title, var, datasource_uid))

    # Dashboard-level rules.
    rules.append(_dashboard_health_rule(uid, title, datasource_uid))
    rules.append(_dashboard_slow_load_rule(uid, title, datasource_uid))

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
    datasource_uid: str,
) -> dict:
    short = _UID_SHORT.get(probe_type, probe_type[:4])
    rule_uid = f"sre-{dashboard_uid[:16]}-{short}-p{spec.panel_id}"
    return {
        "uid": rule_uid,
        "title": f"[{dashboard_title}] Panel '{spec.panel_title}' -- {probe_label}",
        "condition": "C",
        "data": [
            {
                "refId": "B",
                "queryType": "",
                "relativeTimeRange": {"from": 300, "to": 0},
                "datasourceUid": datasource_uid,
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
                "model": _classic_condition("B", "lt", 1),
            },
        ],
        "noDataState": "Alerting",
        "execErrState": "Alerting",
        "for": "2m",
        "annotations": {
            "summary": f"Panel '{spec.panel_title}' in dashboard '{dashboard_title}' -- {probe_label}",
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
    datasource_uid: str,
) -> dict:
    rule_uid = f"sre-{dashboard_uid[:16]}-vf-{var.name}"
    return {
        "uid": rule_uid,
        "title": f"[{dashboard_title}] Variable '{var.name}' -- Resolution or Query Failed",
        "condition": "C",
        "data": [
            {
                "refId": "B",
                "queryType": "",
                "relativeTimeRange": {"from": 300, "to": 0},
                "datasourceUid": datasource_uid,
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
                "model": _classic_condition("B", "lt", 1),
            },
        ],
        "noDataState": "Alerting",
        "execErrState": "Alerting",
        "for": "2m",
        "annotations": {
            "summary": f"Variable '{var.name}' in dashboard '{dashboard_title}' failed to resolve or query",
            "description": (
                f"Template variable {var.name} is empty or failing to query. "
                "Panels depending on this variable may show broken data or keep stale selected values."
            ),
        },
        "labels": {
            "severity": "critical",
            "dashboard_uid": dashboard_uid,
            "variable_name": var.name,
            "probe_type": "variable_resolution",
        },
    }


def _dashboard_health_rule(
    dashboard_uid: str,
    dashboard_title: str,
    datasource_uid: str,
) -> dict:
    return {
        "uid": f"sre-{dashboard_uid[:16]}-hs",
        "title": f"[{dashboard_title}] Health Score Drop",
        "condition": "C",
        "data": [
            {
                "refId": "B",
                "queryType": "",
                "relativeTimeRange": {"from": 300, "to": 0},
                "datasourceUid": datasource_uid,
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
                "model": _classic_condition("B", "lt", 1),
            },
        ],
        "noDataState": "Alerting",
        "execErrState": "Alerting",
        "for": "2m",
        "annotations": {
            "summary": f"Dashboard '{dashboard_title}' health score has dropped below 100%",
            "description": "One or more panels or variables are reporting degraded status.",
        },
        "labels": {
            "severity": "warning",
            "dashboard_uid": dashboard_uid,
            "probe_type": "health_score",
        },
    }


def _dashboard_slow_load_rule(
    dashboard_uid: str,
    dashboard_title: str,
    datasource_uid: str,
) -> dict:
    return {
        "uid": f"sre-{dashboard_uid[:16]}-sl",
        "title": f"[{dashboard_title}] Slow Dashboard Load",
        "condition": "C",
        "data": [
            {
                "refId": "B",
                "queryType": "",
                "relativeTimeRange": {"from": 300, "to": 0},
                "datasourceUid": datasource_uid,
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
                "model": _classic_condition("B", "gt", 15),
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
