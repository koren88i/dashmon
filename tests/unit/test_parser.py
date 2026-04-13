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


def test_mongodb_variable_chaining(mongodb_dash):
    _, variables = parse_dashboard(mongodb_dash)
    by_name = {v.name: v for v in variables}
    assert not by_name["instance"].is_chained
    assert by_name["replset"].is_chained


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
