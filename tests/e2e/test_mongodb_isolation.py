"""E2E coverage for the isolated MongoDB dashboard path."""

import time

import httpx
import pytest

pytestmark = [pytest.mark.e2e]


def _health(engine_url: str) -> dict:
    return httpx.get(f"{engine_url}/health", timeout=5.0).json()


def _wait_degraded(engine_url: str, timeout: float = 25.0) -> dict:
    deadline = time.monotonic() + timeout
    data: dict = {}
    while time.monotonic() < deadline:
        data = _health(engine_url)
        if data.get("health_score", 1.0) < 1.0:
            return data
        time.sleep(0.5)
    return data


def _wait_healthy(engine_url: str, timeout: float = 25.0) -> dict:
    deadline = time.monotonic() + timeout
    data: dict = {}
    while time.monotonic() < deadline:
        data = _health(engine_url)
        if data.get("health_score", 0.0) == 1.0:
            return data
        time.sleep(0.5)
    return data


def _wait_variable_degraded(engine_url: str, timeout: float = 25.0) -> dict:
    deadline = time.monotonic() + timeout
    data: dict = {}
    while time.monotonic() < deadline:
        data = _health(engine_url)
        if any(v["status"] == "degraded" for v in data.get("variables", [])):
            return data
        time.sleep(0.5)
    return data


def _inject(mock_url: str, fault_type: str, target: str, duration: int = 120) -> None:
    httpx.post(
        f"{mock_url}/faults/inject",
        json={"type": fault_type, "target": target, "duration_seconds": duration},
        timeout=5.0,
    )


def _clear(mock_url: str) -> None:
    httpx.post(f"{mock_url}/faults/clear", json={"target": "all"}, timeout=5.0)


@pytest.mark.parametrize(
    ("fault_type", "target", "expected_errors"),
    [
        ("no_data", "mongodb_op_counters_total", {"no_data"}),
        ("stale_data", "mongodb_op_counters_total", {"stale_data"}),
        ("slow_query", "mongodb_op_counters_total", {"slow_query", "query_timeout"}),
        ("metric_rename", "mongodb_memory_resident_bytes", {"no_data"}),
        ("cardinality_spike", "mongodb_op_counters_total", {"cardinality_spike"}),
    ],
)
def test_mongodb_panel_fault_matrix(e2e_mongo_isolate, fault_type, target, expected_errors):
    mock_url, engine_url = e2e_mongo_isolate

    baseline = _health(engine_url)
    assert baseline["dashboard_uid"] == "mongodb-ops-01"
    assert baseline["health_score"] == 1.0

    _inject(mock_url, fault_type, target)
    data = _wait_degraded(engine_url, timeout=30.0 if fault_type == "slow_query" else 25.0)

    assert data["dashboard_uid"] == "mongodb-ops-01"
    assert data["health_score"] < 1.0
    degraded = [p for p in data["panels"] if p["status"] == "degraded"]
    assert degraded
    assert any(p["error_type"] in expected_errors for p in degraded)

    _clear(mock_url)
    recovered = _wait_healthy(engine_url)
    assert recovered["health_score"] == 1.0


def test_mongodb_variable_fault_detected_and_recovers(e2e_mongo_isolate):
    mock_url, engine_url = e2e_mongo_isolate

    _inject(mock_url, "var_resolution_fail", "instance")
    data = _wait_variable_degraded(engine_url)

    assert data["dashboard_uid"] == "mongodb-ops-01"
    assert data["health_score"] < 1.0
    assert data["issue_count"] >= 1
    variables = data.get("variables", [])
    assert any(
        v["name"] == "instance"
        and v["status"] == "degraded"
        and v["error"] == "var_resolution_fail"
        for v in variables
    )

    _clear(mock_url)
    recovered = _wait_healthy(engine_url)
    assert recovered["health_score"] == 1.0


def test_faults_do_not_cross_dashboard_paths(e2e_dual_isolate):
    (service_mock_url, service_engine_url), (mongo_mock_url, mongo_engine_url) = e2e_dual_isolate

    _inject(mongo_mock_url, "no_data", "mongodb_op_counters_total")
    mongo_degraded = _wait_degraded(mongo_engine_url)
    service_health = _health(service_engine_url)

    assert mongo_degraded["dashboard_uid"] == "mongodb-ops-01"
    assert mongo_degraded["health_score"] < 1.0
    assert service_health["dashboard_uid"] == "service-health-01"
    assert service_health["health_score"] == 1.0

    _clear(mongo_mock_url)
    assert _wait_healthy(mongo_engine_url)["health_score"] == 1.0

    _inject(service_mock_url, "no_data", "http_requests_total")
    service_degraded = _wait_degraded(service_engine_url)
    mongo_health = _health(mongo_engine_url)

    assert service_degraded["dashboard_uid"] == "service-health-01"
    assert service_degraded["health_score"] < 1.0
    assert mongo_health["dashboard_uid"] == "mongodb-ops-01"
    assert mongo_health["health_score"] == 1.0

    _clear(service_mock_url)
    assert _wait_healthy(service_engine_url)["health_score"] == 1.0
