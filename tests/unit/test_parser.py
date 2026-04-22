"""Unit tests for probe/parser.py.

No network, no subprocess — pure logic against fixture JSON.
"""

import json
from pathlib import Path

import pytest

from probe.parser import parse_dashboard

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).parent.parent / "fixtures"
REPO_ROOT = Path(__file__).parent.parent.parent


@pytest.fixture(scope="module")
def mini_dash():
    return json.loads((FIXTURES / "mini_dashboard.json").read_text())


@pytest.fixture(scope="module")
def example_dash():
    return json.loads((REPO_ROOT / "demo" / "example_dashboard.json").read_text())


@pytest.fixture(scope="module")
def mongodb_dash():
    return json.loads((REPO_ROOT / "demo" / "mongodb_dashboard.json").read_text())


@pytest.fixture(scope="module")
def mongodb_atlas_dash():
    return json.loads((REPO_ROOT / "demo" / "mongodb_atlas_system_metrics_dashboard.json").read_text())


@pytest.fixture(scope="module")
def mongodb_live_dash():
    return json.loads((REPO_ROOT / "demo" / "mongodb_live_dashboard.json").read_text())


# ---------------------------------------------------------------------------
# Panel parsing — mini dashboard
# ---------------------------------------------------------------------------

def test_panel_count_mini(mini_dash):
    panels, _ = parse_dashboard(mini_dash)
    # mini has 1 panel with targets; 1 panel with empty targets (skipped)
    assert len(panels) == 1


def test_panels_without_targets_skipped(mini_dash):
    panels, _ = parse_dashboard(mini_dash)
    panel_ids = [p.panel_id for p in panels]
    assert 2 not in panel_ids  # panel 2 has no targets


def test_panel_queries_present(mini_dash):
    panels, _ = parse_dashboard(mini_dash)
    for panel in panels:
        assert len(panel.queries) >= 1


def test_variable_substitution(mini_dash):
    """$env in a query should be replaced with .* ."""
    panels, _ = parse_dashboard(mini_dash)
    assert panels[0].queries[0] == 'up{job=~".*"}'


def test_panel_preserves_raw_query_and_variable_dependencies(mini_dash):
    panels, _ = parse_dashboard(mini_dash)

    assert panels[0].raw_queries[0] == 'up{job=~"$env"}'
    assert panels[0].variable_dependencies == ["env"]


def test_panel_datasource_uid(mini_dash):
    panels, _ = parse_dashboard(mini_dash)
    assert all(p.datasource_uid == "prometheus-main" for p in panels)


# ---------------------------------------------------------------------------
# Panel parsing — example dashboard
# ---------------------------------------------------------------------------

def test_panel_count_example(example_dash):
    panels, _ = parse_dashboard(example_dash)
    assert len(panels) == 6


def test_all_panels_have_queries(example_dash):
    panels, _ = parse_dashboard(example_dash)
    for p in panels:
        assert len(p.queries) >= 1, f"Panel '{p.panel_title}' has no queries"


def test_all_panels_have_datasource(example_dash):
    panels, _ = parse_dashboard(example_dash)
    for p in panels:
        assert p.datasource_uid == "prometheus-main"


def test_panel_count_mongodb(mongodb_dash):
    panels, _ = parse_dashboard(mongodb_dash)
    assert len(panels) == 6


def test_all_mongodb_panels_have_datasource(mongodb_dash):
    panels, _ = parse_dashboard(mongodb_dash)
    for p in panels:
        assert p.datasource_uid == "prometheus-mongo"


def test_mongodb_variable_substitution(mongodb_dash):
    panels, _ = parse_dashboard(mongodb_dash)
    op_rate = next(p for p in panels if p.panel_title == "Operation Rate")
    assert 'instance=~".*"' in op_rate.queries[0]
    assert 'replset=~".*"' in op_rate.queries[0]


def test_panel_count_mongodb_atlas(mongodb_atlas_dash):
    panels, _ = parse_dashboard(mongodb_atlas_dash)
    assert len(panels) == 39


def test_all_mongodb_atlas_panels_have_datasource(mongodb_atlas_dash):
    panels, _ = parse_dashboard(mongodb_atlas_dash)
    assert {p.datasource_uid for p in panels} == {"prometheus-mongo-atlas"}


def test_mongodb_atlas_queries_have_default_interval(mongodb_atlas_dash):
    panels, _ = parse_dashboard(mongodb_atlas_dash)
    all_queries = [query for panel in panels for query in panel.queries]
    assert not any("$Interval" in query for query in all_queries)
    assert any("[1m]" in query for query in all_queries)


def test_panel_count_mongodb_live(mongodb_live_dash):
    panels, _ = parse_dashboard(mongodb_live_dash)
    assert len(panels) == 6


def test_all_mongodb_live_panels_have_datasource(mongodb_live_dash):
    panels, _ = parse_dashboard(mongodb_live_dash)
    assert {p.datasource_uid for p in panels} == {"prometheus-mongo-live"}
    assert any("mongodb_op_counters_total" in query for p in panels for query in p.queries)


def test_mongodb_live_queries_have_safe_instance_default(mongodb_live_dash):
    source_queries = [
        target["expr"]
        for panel in mongodb_live_dash["panels"]
        for target in panel.get("targets", [])
        if target.get("expr")
    ]
    assert all("${instance:regex}" in query for query in source_queries)

    panels, _ = parse_dashboard(mongodb_live_dash)
    parsed_queries = [query for panel in panels for query in panel.queries]
    assert all('instance=~".*"' in query for query in parsed_queries)
    assert not any(":regex}" in query or "$instance" in query for query in parsed_queries)


def test_mongodb_live_panel_dependencies_are_preserved_before_substitution(mongodb_live_dash):
    panels, _ = parse_dashboard(mongodb_live_dash)

    assert all(panel.variable_dependencies == ["instance"] for panel in panels)
    assert all(
        "${instance:regex}" in raw_query
        for panel in panels
        for raw_query in panel.raw_queries
    )


# ---------------------------------------------------------------------------
# Variable parsing
# ---------------------------------------------------------------------------

def test_variable_count_mini(mini_dash):
    _, variables = parse_dashboard(mini_dash)
    assert len(variables) == 1


def test_variable_count_example(example_dash):
    _, variables = parse_dashboard(example_dash)
    assert len(variables) == 2


def test_variable_count_mongodb(mongodb_dash):
    _, variables = parse_dashboard(mongodb_dash)
    assert len(variables) == 2


def test_variable_count_mongodb_atlas(mongodb_atlas_dash):
    _, variables = parse_dashboard(mongodb_atlas_dash)
    assert len(variables) == 6


def test_variable_count_mongodb_live(mongodb_live_dash):
    _, variables = parse_dashboard(mongodb_live_dash)
    assert len(variables) == 1
    assert variables[0].name == "instance"
    source_var = next(var for var in mongodb_live_dash["templating"]["list"] if var["name"] == "instance")
    assert source_var["allValue"] == ".*"
    assert source_var["current"]["value"] == "$__all"


def test_mongodb_variable_chaining(mongodb_dash):
    _, variables = parse_dashboard(mongodb_dash)
    by_name = {v.name: v for v in variables}
    assert not by_name["instance"].is_chained
    assert by_name["replset"].is_chained


def test_mongodb_atlas_variable_chaining(mongodb_atlas_dash):
    _, variables = parse_dashboard(mongodb_atlas_dash)
    by_name = {v.name: v for v in variables}
    assert not by_name["job"].is_chained
    assert by_name["group_id"].is_chained
    assert by_name["process_port"].is_chained


def test_variable_chaining(example_dash):
    """$namespace references $pod → is_chained=True; $pod does not → False."""
    _, variables = parse_dashboard(example_dash)
    by_name = {v.name: v for v in variables}
    assert not by_name["pod"].is_chained
    assert by_name["namespace"].is_chained


def test_variable_chain_depth(example_dash):
    _, variables = parse_dashboard(example_dash)
    by_name = {v.name: v for v in variables}
    assert by_name["pod"].chain_depth == 0
    assert by_name["namespace"].chain_depth == 1


# ---------------------------------------------------------------------------
# Numeric variable substitution
# ---------------------------------------------------------------------------

def _make_dash(expr: str, *, var_name: str = "", var_names: set[str] | None = None) -> dict:
    """Build a minimal dashboard dict with one panel and one or more query variables."""
    names = var_names if var_names is not None else ({var_name} if var_name else set())
    var_list = [
        {
            "name": n,
            "type": "query",
            "datasource": {"uid": "prom", "type": "prometheus"},
            "query": f"label_values({n})",
        }
        for n in names
    ]
    return {
        "panels": [
            {
                "id": 1,
                "title": "T",
                "type": "graph",
                "datasource": {"uid": "prom", "type": "prometheus"},
                "targets": [{"expr": expr}],
            }
        ],
        "templating": {"list": var_list},
    }


def test_numeric_variable_gt_substitution():
    """$threshold after > should become 0, producing valid PromQL."""
    dash = _make_dash("http_requests_total > $threshold", var_name="threshold")
    panels, _ = parse_dashboard(dash)
    assert panels[0].queries[0] == "http_requests_total > 0"


def test_numeric_variable_gte_substitution():
    """>= operator also triggers numeric substitution."""
    dash = _make_dash("latency_seconds >= $slo", var_name="slo")
    panels, _ = parse_dashboard(dash)
    assert panels[0].queries[0] == "latency_seconds >= 0"


def test_mixed_label_and_numeric_substitution():
    """Label var becomes .* and numeric var becomes 0 in the same expression."""
    dash = _make_dash('up{job=~"$env"} > $threshold', var_names={"env", "threshold"})
    panels, _ = parse_dashboard(dash)
    assert panels[0].queries[0] == 'up{job=~".*"} > 0'


def test_formatted_variable_substitution():
    """Grafana variable formatters should not leak into probe PromQL."""
    dash = _make_dash(
        'up{instance=~"${instance:regex}"} > ${threshold:raw}',
        var_names={"instance", "threshold"},
    )
    panels, _ = parse_dashboard(dash)
    assert panels[0].queries[0] == 'up{instance=~".*"} > 0'


def test_non_query_variables_skipped(example_dash):
    """Variables with type != 'query' should not appear in specs."""
    dash = {
        **example_dash,
        "templating": {
            "list": [
                {"name": "ds", "type": "datasource"},   # should be skipped
                *example_dash["templating"]["list"],
            ]
        },
    }
    _, variables = parse_dashboard(dash)
    names = [v.name for v in variables]
    assert "ds" not in names
