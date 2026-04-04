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
def parsed(example_dash):
    panels, variables = parse_dashboard(example_dash)
    return example_dash, panels, variables


@pytest.fixture(scope="module")
def meta(parsed):
    dash, panels, variables = parsed
    return generate_meta_dashboard(dash, panels, variables)


@pytest.fixture(scope="module")
def alerts(parsed):
    dash, panels, variables = parsed
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
            assert ds["uid"] in ("${datasource}", "-- Grafana --"), (
                f"Panel '{panel.get('title')}' has hardcoded datasource uid: {ds['uid']}"
            )


def test_meta_dashboard_unique_panel_ids(meta):
    ids = [p["id"] for p in meta["panels"]]
    assert len(ids) == len(set(ids))


def test_meta_dashboard_has_datasource_template_var(meta):
    var_names = [v["name"] for v in meta["templating"]["list"]]
    assert "datasource" in var_names


# ---------------------------------------------------------------------------
# Alert rules
# ---------------------------------------------------------------------------

def test_alert_rules_valid_yaml(alerts):
    yaml.safe_load(yaml.dump(alerts))


def test_alert_rules_api_version(alerts):
    assert alerts["apiVersion"] == 1


def test_alert_rules_count(alerts):
    rules = alerts["groups"][0]["rules"]
    # 6 panels × 6 probe types + 2 variables + 2 dashboard-level = 40
    assert len(rules) == 40


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
