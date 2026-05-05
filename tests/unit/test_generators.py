"""Unit tests for generator/meta_dashboard.py and generator/alert_rules.py."""

import json
from pathlib import Path

import pytest
import yaml

from generator.alert_rules import generate_alert_rules
from generator.meta_dashboard import generate_meta_dashboard
from probe.parser import parse_dashboard

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).parent.parent.parent


@pytest.fixture(scope="module")
def example_dash():
    return json.loads((REPO_ROOT / "demo" / "example_dashboard.json").read_text())


@pytest.fixture(scope="module")
def mongodb_dash():
    return json.loads((REPO_ROOT / "demo" / "mongodb_dashboard.json").read_text())


@pytest.fixture(scope="module")
def parsed(example_dash):
    panels, variables = parse_dashboard(example_dash)
    return example_dash, panels, variables


@pytest.fixture(scope="module")
def mongodb_parsed(mongodb_dash):
    panels, variables = parse_dashboard(mongodb_dash)
    return mongodb_dash, panels, variables


@pytest.fixture(scope="module")
def meta(parsed):
    dash, panels, variables = parsed
    return generate_meta_dashboard(dash, panels, variables)


@pytest.fixture(scope="module")
def alerts(parsed):
    dash, panels, variables = parsed
    return generate_alert_rules(dash, panels, variables)


@pytest.fixture(scope="module")
def mongodb_meta(mongodb_parsed):
    dash, panels, variables = mongodb_parsed
    return generate_meta_dashboard(dash, panels, variables)


@pytest.fixture(scope="module")
def mongodb_alerts(mongodb_parsed):
    dash, panels, variables = mongodb_parsed
    return generate_alert_rules(dash, panels, variables)


# ---------------------------------------------------------------------------
# Meta-dashboard
# ---------------------------------------------------------------------------

def test_meta_dashboard_is_valid_json(meta):
    # Serialise and re-parse to confirm it's JSON-serialisable.
    json.loads(json.dumps(meta))


def test_meta_dashboard_schema_version(meta):
    assert meta["schemaVersion"] >= 39


def test_meta_dashboard_uid_prefix(meta):
    assert meta["uid"].startswith("sre-")


def test_meta_dashboard_title_prefix(meta):
    assert meta["title"].startswith("[SRE]")


def test_meta_dashboard_has_panels(meta):
    assert len(meta["panels"]) >= 6


def test_meta_dashboard_uses_datasource_variable(meta):
    """No panel should have a hardcoded datasource UID."""
    for panel in meta["panels"]:
        ds = panel.get("datasource", {})
        if isinstance(ds, dict) and ds.get("uid"):
            assert ds["uid"] in ("${sre_datasource}", "-- Grafana --"), (
                f"Panel '{panel.get('title')}' has hardcoded datasource uid: {ds['uid']}"
            )


def test_meta_dashboard_unique_panel_ids(meta):
    ids = [p["id"] for p in meta["panels"]]
    assert len(ids) == len(set(ids))


def test_meta_dashboard_has_datasource_template_var(meta):
    var_names = [v["name"] for v in meta["templating"]["list"]]
    assert "sre_datasource" in var_names


def test_meta_dashboard_defaults_to_probe_metrics_datasource(meta):
    datasource = next(v for v in meta["templating"]["list"] if v["name"] == "sre_datasource")
    assert datasource["current"]["text"] == "Probe Metrics"
    assert datasource["current"]["value"] == "probe-metrics"


def test_meta_dashboard_has_probe_layer_panels(meta):
    panels = {panel.get("title"): panel for panel in meta["panels"]}
    assert "Datasource API" in panels
    assert "Grafana Panel Path" in panels
    assert "Variable Dependency" in panels
    assert "Browser Render" in panels
    assert "GET /api/v1/query" in panels["Datasource API"]["description"]
    assert "/api/ds/query" in panels["Grafana Panel Path"]["description"]
    assert "failed dashboard variables" in panels["Variable Dependency"]["description"]
    assert "Playwright browser" in panels["Browser Render"]["description"]


def test_meta_dashboard_has_browser_render_overview_panels(meta):
    panels = {panel.get("title"): panel for panel in meta["panels"]}
    assert panels["Browser Render Time"]["targets"][0]["expr"] == (
        'dashboard_render_time_seconds{dashboard_uid="service-health-01"}'
    )
    assert panels["Last Render Run"]["targets"][0]["expr"] == (
        'time() - dashboard_render_last_probe_timestamp{dashboard_uid="service-health-01"}'
    )


def test_meta_dashboard_has_variable_error_type_panel(meta):
    panels = {panel.get("title"): panel for panel in meta["panels"]}
    assert "Variable Error Types" in panels
    expr = panels["Variable Error Types"]["targets"][0]["expr"]
    assert "dashboard_variable_error_total" in expr
    assert "variable_name" in expr
    assert "error_type" in expr
    assert "Variable Blast Radius" in panels
    blast_expr = panels["Variable Blast Radius"]["targets"][0]["expr"]
    assert "dashboard_variable_dependency_impact" in blast_expr
    assert "== 1" in blast_expr


# ---------------------------------------------------------------------------
# Alert rules
# ---------------------------------------------------------------------------

def test_alert_rules_valid_yaml(alerts):
    yaml.safe_load(yaml.dump(alerts))


def test_alert_rules_api_version(alerts):
    assert alerts["apiVersion"] == 1


def test_alert_rules_count(alerts):
    rules = alerts["groups"][0]["rules"]
    # 6 panels x 9 probe types + 2 variables + 4 dashboard-level = 60
    assert len(rules) == 60


def test_alert_rules_for_duration(alerts):
    rules = alerts["groups"][0]["rules"]
    for rule in rules:
        assert rule["for"] in ("2m", "5m"), f"Rule '{rule['title']}' has unexpected 'for': {rule['for']}"


def test_alert_rules_have_severity(alerts):
    rules = alerts["groups"][0]["rules"]
    for rule in rules:
        assert "severity" in rule["labels"], f"Rule '{rule['title']}' missing severity label"


def test_alert_rules_have_dashboard_uid(alerts):
    rules = alerts["groups"][0]["rules"]
    for rule in rules:
        assert "dashboard_uid" in rule["labels"]


def test_alert_rules_unique_uids(alerts):
    rules = alerts["groups"][0]["rules"]
    uids = [r["uid"] for r in rules]
    assert len(uids) == len(set(uids))


def test_alert_rules_uid_length(alerts):
    """Grafana enforces a 40-char limit on rule UIDs."""
    rules = alerts["groups"][0]["rules"]
    for rule in rules:
        assert len(rule["uid"]) <= 40, f"UID too long ({len(rule['uid'])}): {rule['uid']}"


def test_alert_rules_group_name(alerts):
    assert alerts["groups"][0]["name"].startswith("dashboard-sre-")


def test_alert_rules_use_concrete_probe_metrics_datasource(alerts):
    rules = alerts["groups"][0]["rules"]
    for rule in rules:
        query_data = next(item for item in rule["data"] if item["refId"] == "B")
        assert query_data["datasourceUid"] == "probe-metrics", (
            f"Rule '{rule['title']}' should point at the provisioned probe-metrics datasource"
        )


def test_variable_alert_rule_covers_empty_and_hard_failures(alerts):
    rules = alerts["groups"][0]["rules"]
    variable_rule = next(rule for rule in rules if "Variable 'pod'" in rule["title"])
    assert "Resolution or Query Failed" in variable_rule["title"]
    assert variable_rule["labels"]["probe_type"] == "variable_resolution"
    assert "empty or failing to query" in variable_rule["annotations"]["description"]


def test_alert_rules_include_variable_dependency_probe(alerts):
    rules = alerts["groups"][0]["rules"]
    dependency_rule = next(rule for rule in rules if "Variable Dependency" in rule["title"])
    assert dependency_rule["labels"]["probe_type"] == "variable_dependency"
    assert "failed dashboard variable" in dependency_rule["annotations"]["description"]


def test_alert_rules_include_browser_render_rules(alerts):
    rules = alerts["groups"][0]["rules"]
    render_rule = next(rule for rule in rules if rule["title"].endswith("Browser Render Degraded"))
    slow_rule = next(rule for rule in rules if rule["title"].endswith("Slow Browser Render"))

    assert render_rule["labels"]["probe_type"] == "browser_render"
    assert render_rule["data"][0]["model"]["expr"] == (
        'dashboard_render_status{dashboard_uid="service-health-01"}'
    )
    assert slow_rule["labels"]["probe_type"] == "slow_render"
    assert slow_rule["data"][0]["model"]["expr"] == (
        'dashboard_render_time_seconds{dashboard_uid="service-health-01"}'
    )


def test_alert_rules_do_not_include_empty_expression_nodes(alerts):
    rules = alerts["groups"][0]["rules"]
    for rule in rules:
        for item in rule["data"]:
            model = item.get("model", {})
            assert model.get("expression", None) != "", (
                f"Rule '{rule['title']}' contains an empty Grafana expression node"
            )


def test_alert_rules_use_classic_conditions_on_query_b(alerts):
    rules = alerts["groups"][0]["rules"]
    for rule in rules:
        condition = next(item for item in rule["data"] if item["refId"] == "C")
        model = condition["model"]
        assert model["type"] == "classic_conditions"
        assert model["conditions"][0]["query"]["params"] == ["B"]


def test_meta_dashboard_active_issues_uses_canonical_issue_metric(meta):
    active_issues = next(panel for panel in meta["panels"] if panel.get("title") == "Active Issues")
    assert active_issues["targets"][0]["expr"] == (
        'dashboard_issue_count{dashboard_uid="service-health-01"}'
    )


def test_meta_dashboard_recent_errors_panel_matches_query(meta):
    recent_errors = next(
        panel for panel in meta["panels"] if panel.get("title") == "Recent Issue Events"
    )
    expr = recent_errors["targets"][0]["expr"]
    assert "dashboard_issue_event_timestamp_seconds" in expr
    assert expr.endswith(" * 1000")
    assert "unit" not in recent_errors["fieldConfig"]["defaults"]
    event_time_override = recent_errors["fieldConfig"]["overrides"][0]
    assert event_time_override["matcher"] == {"id": "byName", "options": "Event Time"}
    assert event_time_override["properties"] == [{"id": "unit", "value": "dateTimeAsIso"}]
    organize = next(t for t in recent_errors["transformations"] if t["id"] == "organize")
    assert organize["options"]["excludeByName"]["Time"] is True
    assert organize["options"]["excludeByName"]["__name__"] is True
    assert organize["options"]["excludeByName"]["instance"] is True
    assert organize["options"]["excludeByName"]["job"] is True
    assert organize["options"]["renameByName"]["Value"] == "Event Time"
    assert organize["options"]["renameByName"]["probe_type"] == "Path"
    assert organize["options"]["renameByName"]["error_type"] == "Type"
    assert organize["options"]["indexByName"]["probe_type"] == 2


def test_mongodb_meta_dashboard_uid_and_title(mongodb_meta):
    assert mongodb_meta["uid"] == "sre-mongodb-ops-01"
    assert mongodb_meta["title"] == "[SRE] MongoDB Operations"


def test_mongodb_meta_dashboard_filters_by_dashboard_uid(mongodb_meta):
    health = next(panel for panel in mongodb_meta["panels"] if panel.get("title") == "Health Score")
    assert health["targets"][0]["expr"] == (
        'dashboard_health_score{dashboard_uid="mongodb-ops-01"}'
    )


def test_mongodb_meta_dashboard_defaults_to_probe_metrics_datasource(mongodb_meta):
    datasource = next(v for v in mongodb_meta["templating"]["list"] if v["name"] == "sre_datasource")
    assert datasource["current"]["text"] == "Probe Metrics"
    assert datasource["current"]["value"] == "probe-metrics"


def test_mongodb_alert_rules_count(mongodb_alerts):
    rules = mongodb_alerts["groups"][0]["rules"]
    # 6 panels x 9 probe types + 2 variables + 4 dashboard-level = 60
    assert len(rules) == 60


def test_mongodb_alert_rules_unique_uids(mongodb_alerts):
    rules = mongodb_alerts["groups"][0]["rules"]
    uids = [r["uid"] for r in rules]
    assert len(uids) == len(set(uids))


def test_mongodb_alert_rules_filter_by_dashboard_uid(mongodb_alerts):
    rules = mongodb_alerts["groups"][0]["rules"]
    assert all(rule["labels"]["dashboard_uid"] == "mongodb-ops-01" for rule in rules)
