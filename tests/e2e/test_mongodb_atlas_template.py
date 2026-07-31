"""E2E coverage for the MongoDB Atlas upstream Grafana dashboard target."""

import time

import httpx
import pytest

pytestmark = [pytest.mark.e2e]


def _health(engine_url: str) -> dict:
    return httpx.get(f"{engine_url}/health", timeout=5.0).json()


def _wait_degraded(engine_url: str, timeout: float = 35.0) -> dict:
    deadline = time.monotonic() + timeout
    data: dict = {}
    while time.monotonic() < deadline:
        data = _health(engine_url)
        if data.get("health_score", 1.0) < 1.0:
            return data
        time.sleep(0.5)
    return data


def _wait_healthy(engine_url: str, timeout: float = 45.0) -> dict:
    deadline = time.monotonic() + timeout
    data: dict = {}
    while time.monotonic() < deadline:
        data = _health(engine_url)
        if data.get("health_score", 0.0) == 1.0:
            return data
        time.sleep(0.5)
    return data


def _wait_variable_degraded(engine_url: str, timeout: float = 35.0) -> dict:
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


def test_mongodb_atlas_template_starts_healthy(e2e_mongo_atlas_isolate):
    _, engine_url = e2e_mongo_atlas_isolate

    data = _health(engine_url)

    assert data["dashboard_uid"] == "mongodb-atlas-system-metrics"
    assert data["dashboard_title"] == "MongoDB Atlas System Metrics"
    assert data["total_panels"] == 39
    assert data["total_variables"] == 6
    assert data["health_score"] == 1.0


@pytest.mark.parametrize(
    ("fault_type", "target", "expected_errors"),
    [
        ("no_data", "mongodb_opcounters_query", {"no_data"}),
        ("stale_data", "mongodb_opcounters_query", {"stale_data"}),
        ("slow_query", "mongodb_opcounters_query", {"slow_query", "query_timeout"}),
        ("metric_rename", "mongodb_mem_virtual", {"no_data"}),
        ("cardinality_spike", "mongodb_opcounters_query", {"cardinality_spike"}),
    ],
)
def test_mongodb_atlas_panel_fault_matrix(e2e_mongo_atlas_isolate, fault_type, target, expected_errors):
    mock_url, engine_url = e2e_mongo_atlas_isolate

    _inject(mock_url, fault_type, target)
    data = _wait_degraded(engine_url, timeout=40.0 if fault_type == "slow_query" else 35.0)

    assert data["dashboard_uid"] == "mongodb-atlas-system-metrics"
    assert data["health_score"] < 1.0
    degraded = [p for p in data["panels"] if p["status"] == "degraded"]
    assert degraded
    assert any(p["error_type"] in expected_errors for p in degraded)

    _clear(mock_url)
    assert _wait_healthy(engine_url)["health_score"] == 1.0


def test_mongodb_atlas_variable_fault_detected_and_recovers(e2e_mongo_atlas_isolate):
    mock_url, engine_url = e2e_mongo_atlas_isolate

    _inject(mock_url, "var_resolution_fail", "group_id")
    data = _wait_variable_degraded(engine_url)

    assert data["dashboard_uid"] == "mongodb-atlas-system-metrics"
    assert data["health_score"] < 1.0
    assert any(
        v["name"] == "group_id"
        and v["status"] == "degraded"
        and v["error"] == "var_resolution_fail"
        for v in data.get("variables", [])
    )

    _clear(mock_url)
    assert _wait_healthy(engine_url)["health_score"] == 1.0
