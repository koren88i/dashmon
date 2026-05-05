"""Unit tests for diagnosis-aware issue event transitions."""

from __future__ import annotations

import pytest

from probe import engine
from probe.config import ErrorType, PanelProbeSpec, ProbeResult, ProbeStatus

pytestmark = pytest.mark.unit


def test_should_emit_issue_for_diagnosis_change_while_degraded():
    previous = engine.IssueSignature(ProbeStatus.DEGRADED, "datasource_api", "no_data")
    current = engine.IssueSignature(ProbeStatus.DEGRADED, "datasource_api", "slow_query")

    assert engine._should_emit_issue(previous, current) is True


def test_should_not_emit_issue_for_same_degraded_diagnosis():
    previous = engine.IssueSignature(ProbeStatus.DEGRADED, "datasource_api", "slow_query")
    current = engine.IssueSignature(ProbeStatus.DEGRADED, "datasource_api", "slow_query")

    assert engine._should_emit_issue(previous, current) is False


def test_should_emit_recovery_after_degraded():
    previous = engine.IssueSignature(ProbeStatus.DEGRADED, "grafana_panel_path", "panel_error")
    current = engine.IssueSignature(ProbeStatus.HEALTHY, "recovery", "recovered")

    assert engine._should_emit_issue(previous, current) is True


def test_record_issue_transition_includes_probe_type():
    original_issues = engine.state.issues
    original_next_issue_id = engine.state._next_issue_id
    original_metric_labels = set(engine.state._issue_metric_labels)
    try:
        engine.state.dashboard_uid = "unit-dashboard"
        engine.state.issues = []
        engine.state._next_issue_id = 0

        previous = engine.IssueSignature(ProbeStatus.DEGRADED, "datasource_api", "no_data")
        current = engine.IssueSignature(ProbeStatus.DEGRADED, "datasource_api", "slow_query")

        emitted = engine._record_issue_transition(
            previous,
            current,
            2,
            "Operation Rate",
            "Query took 8.3s (threshold: 5.0s)",
        )

        assert emitted is True
        assert len(engine.state.issues) == 1
        issue = engine.state.issues[0]
        assert issue.probe_type == "datasource_api"
        assert issue.error_type == "slow_query"
        assert issue.message == "Query took 8.3s (threshold: 5.0s)"
    finally:
        engine.state.issues = original_issues
        engine.state._next_issue_id = original_next_issue_id
        engine._sync_issue_event_metrics()
        engine.state._issue_metric_labels = original_metric_labels


def test_variable_dependency_result_marks_panel_blocked_without_overwriting_raw_probe():
    spec = PanelProbeSpec(
        panel_id=7,
        panel_title="Operation Rate",
        datasource_uid="prometheus-mongo-live",
        datasource_type="prometheus",
        queries=['sum(rate(mongodb_op_counters_total{instance=~".*"}[5m])) by (type)'],
        raw_queries=['sum(rate(mongodb_op_counters_total{instance=~"${instance:regex}"}[5m])) by (type)'],
        variable_dependencies=["instance"],
    )
    raw_result = ProbeResult(
        panel_id=7,
        panel_title="Operation Rate",
        status=ProbeStatus.HEALTHY,
        probe_type="datasource_api",
        series_count=3,
    )
    variable_failures = {
        "instance": {
            "name": "instance",
            "status": "degraded",
            "error": "variable_query_error",
        }
    }

    result = engine._variable_dependency_result(spec, variable_failures, raw_result)

    assert result is not None
    assert result.status == ProbeStatus.DEGRADED
    assert result.probe_type == "variable_dependency"
    assert result.error_type == ErrorType.BLOCKED_BY_VARIABLE
    assert result.series_count == 3
    assert "$instance=variable_query_error" in result.message


def test_health_summary_counts_variable_blocked_panels_as_unhealthy():
    panels = [
        ProbeResult(1, "A", ProbeStatus.DEGRADED, error_type=ErrorType.BLOCKED_BY_VARIABLE),
        ProbeResult(2, "B", ProbeStatus.DEGRADED, error_type=ErrorType.BLOCKED_BY_VARIABLE),
    ]
    variables = [{"name": "instance", "status": "degraded", "error": "variable_query_error"}]

    summary = engine._health_summary(panels, variables)

    assert summary["healthy_panels"] == 0
    assert summary["healthy_variables"] == 0
    assert summary["issue_count"] == 3
    assert summary["health_score"] == 0.0
