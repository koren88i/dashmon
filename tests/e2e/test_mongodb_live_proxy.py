"""End-to-end tests for the live Mongo dashboard through a faultable proxy."""

from __future__ import annotations

import time

import httpx
import pytest

pytestmark = pytest.mark.e2e


def _health(engine_url: str) -> dict:
    return httpx.get(f"{engine_url}/health", timeout=5.0).json()


def _wait(engine_url: str, predicate, timeout: float = 40.0) -> dict:
    deadline = time.monotonic() + timeout
    last = {}
    while time.monotonic() < deadline:
        last = _health(engine_url)
        if predicate(last):
            return last
        time.sleep(1.0)
    return last


def _inject(proxy_url: str, fault_type: str, target: str, duration: int = 120) -> None:
    httpx.post(
        f"{proxy_url}/faults/inject",
        json={"type": fault_type, "target": target, "duration_seconds": duration},
        timeout=5.0,
    )


def _clear(proxy_url: str) -> None:
    httpx.post(f"{proxy_url}/faults/clear", json={"target": "all"}, timeout=5.0)


def test_mongodb_live_proxy_starts_healthy(e2e_mongo_live_isolate):
    _, engine_url = e2e_mongo_live_isolate

    data = _health(engine_url)

    assert data["dashboard_uid"] == "mongodb-live-ops-01"
    assert data["health_score"] == 1.0


@pytest.mark.parametrize(
    ("fault_type", "target", "expected_errors"),
    [
        ("no_data", "mongodb_op_counters_total", {"no_data"}),
        ("stale_data", "mongodb_op_counters_total", {"stale_data"}),
        ("slow_query", "mongodb_op_counters_total", {"slow_query", "query_timeout"}),
        ("metric_rename", "mongodb_memory", {"no_data"}),
        ("cardinality_spike", "mongodb_op_counters_total", {"cardinality_spike"}),
    ],
)
def test_mongodb_live_proxy_panel_fault_matrix(e2e_mongo_live_isolate, fault_type, target, expected_errors):
    proxy_url, engine_url = e2e_mongo_live_isolate

    _inject(proxy_url, fault_type, target)
    data = _wait(
        engine_url,
        lambda d: d.get("health_score", 1.0) < 1.0,
        timeout=45.0 if fault_type == "slow_query" else 35.0,
    )

    errors = {panel.get("error_type") for panel in data.get("panels", []) if panel.get("status") == "degraded"}
    assert data["dashboard_uid"] == "mongodb-live-ops-01"
    assert data["health_score"] < 1.0
    assert errors & expected_errors

    _clear(proxy_url)
    recovered = _wait(engine_url, lambda d: d.get("health_score") == 1.0, timeout=45.0)
    assert recovered["health_score"] == 1.0


@pytest.mark.parametrize(
    ("fault_type", "expected_error"),
    [
        ("var_resolution_fail", "var_resolution_fail"),
        ("variable_query_error", "variable_query_error"),
    ],
)
def test_mongodb_live_proxy_variable_fault_detected_and_recovers(
    e2e_mongo_live_isolate,
    fault_type,
    expected_error,
):
    proxy_url, engine_url = e2e_mongo_live_isolate

    _inject(proxy_url, fault_type, "instance")
    data = _wait(engine_url, lambda d: d.get("healthy_variables", 1) < d.get("total_variables", 0))

    assert data["dashboard_uid"] == "mongodb-live-ops-01"
    assert data["health_score"] == 0.0
    assert any(
        v["name"] == "instance"
        and v["status"] == "degraded"
        and v["error"] == expected_error
        for v in data["variables"]
    )
    blocked_panels = [
        panel for panel in data["panels"]
        if panel["error_type"] == "blocked_by_variable"
    ]
    assert len(blocked_panels) == data["total_panels"]
    for panel in blocked_panels:
        layers = {layer["probe_type"]: layer for layer in panel["layers"]}
        assert layers["datasource_api"]["status"] == "healthy"
        assert layers["variable_dependency"]["status"] == "degraded"
        assert layers["variable_dependency"]["error_type"] == "blocked_by_variable"
        assert panel["variable_dependencies"] == ["instance"]
    if fault_type == "variable_query_error":
        discovery = httpx.get(
            f"{proxy_url}/api/v1/series",
            params={"match[]": "mongodb_up"},
            timeout=5.0,
        )
        assert discovery.status_code == 500

    _clear(proxy_url)
    recovered = _wait(engine_url, lambda d: d.get("health_score") == 1.0, timeout=45.0)
    assert recovered["health_score"] == 1.0


def test_mongodb_live_grafana_panel_path_failure_detected(e2e_mongo_live_isolate):
    proxy_url, engine_url = e2e_mongo_live_isolate

    _inject(proxy_url, "panel_query_http_500", "mongodb_op_counters_total")
    data = _wait(engine_url, lambda d: d.get("health_score", 1.0) < 1.0, timeout=45.0)

    op_rate = next(panel for panel in data["panels"] if panel["panel_title"] == "Operation Rate")
    layers = {layer["probe_type"]: layer for layer in op_rate["layers"]}
    assert layers["datasource_api"]["status"] == "healthy"
    assert layers["grafana_panel_path"]["status"] == "degraded"
    assert layers["grafana_panel_path"]["error_type"] == "panel_error"

    raw = httpx.get(
        f"{proxy_url}/api/v1/query",
        params={"query": "mongodb_op_counters_total"},
        timeout=5.0,
    )
    assert raw.status_code == 200
    assert raw.json()["status"] == "success"

    end = time.time()
    panel_path = httpx.post(
        f"{proxy_url}/api/v1/query_range",
        data={
            "query": 'sum(rate(mongodb_op_counters_total{instance=~".*"}[5m])) by (type)',
            "start": end - 300,
            "end": end,
            "step": 15,
        },
        timeout=5.0,
    )
    assert panel_path.status_code == 500

    _clear(proxy_url)
    recovered = _wait(engine_url, lambda d: d.get("health_score") == 1.0, timeout=45.0)
    assert recovered["health_score"] == 1.0


def test_mongodb_live_proxy_faults_do_not_cross_mock_service(e2e_mongo_live_isolate, e2e_isolate):
    proxy_url, live_engine_url = e2e_mongo_live_isolate
    _, service_engine_url = e2e_isolate

    _inject(proxy_url, "no_data", "mongodb_op_counters_total")
    live = _wait(live_engine_url, lambda d: d.get("health_score", 1.0) < 1.0)
    service = _wait(service_engine_url, lambda d: d.get("health_score") == 1.0)

    assert live["dashboard_uid"] == "mongodb-live-ops-01"
    assert live["health_score"] < 1.0
    assert service["dashboard_uid"] == "service-health-01"
    assert service["health_score"] == 1.0
    _clear(proxy_url)
