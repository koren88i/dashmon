"""End-to-end fault matrix tests.

Starts mock backend + probe engine as subprocesses (via session fixtures).
Each test injects a fault, polls /health until the engine detects it,
then verifies the response. Probe interval is 3s so detection ≤ ~11s.
"""

import time

import httpx
import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.usefixtures("e2e_isolate")]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _health(engine_url: str) -> dict:
    return httpx.get(f"{engine_url}/health", timeout=5.0).json()


def _wait_degraded(engine_url: str, timeout: float = 20.0) -> dict:
    """Poll /health until health_score < 1.0 or timeout."""
    deadline = time.monotonic() + timeout
    data: dict = {}
    while time.monotonic() < deadline:
        data = _health(engine_url)
        if data.get("health_score", 1.0) < 1.0:
            return data
        time.sleep(0.5)
    return data


def _wait_healthy(engine_url: str, timeout: float = 20.0) -> dict:
    """Poll /health until health_score == 1.0 or timeout."""
    deadline = time.monotonic() + timeout
    data: dict = {}
    while time.monotonic() < deadline:
        data = _health(engine_url)
        if data.get("health_score", 0.0) == 1.0:
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


# ---------------------------------------------------------------------------
# Tests — e2e_isolate ensures health_score=1.0 at the start of each test
# ---------------------------------------------------------------------------

def test_baseline_healthy(e2e_isolate):
    _, engine_url = e2e_isolate
    data = _health(engine_url)
    assert data["health_score"] == 1.0
    assert data["total_panels"] == 6
    assert all(p["status"] == "healthy" for p in data["panels"])


def test_no_data_detected(e2e_isolate):
    mock_url, engine_url = e2e_isolate
    _inject(mock_url, "no_data", "http_requests_total")
    data = _wait_degraded(engine_url)
    assert data["health_score"] < 1.0
    degraded = [p for p in data["panels"] if p["status"] == "degraded"]
    assert len(degraded) >= 1
    assert any(p["error_type"] == "no_data" for p in degraded)


def test_stale_data_detected(e2e_isolate):
    mock_url, engine_url = e2e_isolate
    _inject(mock_url, "stale_data", "http_requests_total")
    data = _wait_degraded(engine_url)
    assert data["health_score"] < 1.0
    degraded = [p for p in data["panels"] if p["status"] == "degraded"]
    assert len(degraded) >= 1
    assert any(p["error_type"] == "stale_data" for p in degraded)


def test_slow_query_detected(e2e_isolate):
    """slow_query makes the mock sleep 8s; probe detects SLOW_QUERY (threshold 5s)."""
    mock_url, engine_url = e2e_isolate
    _inject(mock_url, "slow_query", "http_requests_total")
    # Give extra time: probe cycle takes up to 8s + probe_interval 3s = 11s
    data = _wait_degraded(engine_url, timeout=25.0)
    assert data["health_score"] < 1.0
    degraded = [p for p in data["panels"] if p["status"] == "degraded"]
    assert len(degraded) >= 1
    assert any(p["error_type"] in ("slow_query", "query_timeout") for p in degraded)


def test_var_resolution_fail_detected(e2e_isolate):
    """var_resolution_fail for 'instance' label makes $pod variable fail."""
    mock_url, engine_url = e2e_isolate
    # The 'pod' variable queries label_values(up, instance) → target="instance"
    _inject(mock_url, "var_resolution_fail", "instance")
    deadline = time.monotonic() + 20.0
    data: dict = {}
    while time.monotonic() < deadline:
        data = _health(engine_url)
        if any(v["status"] == "degraded" for v in data.get("variables", [])):
            break
        time.sleep(0.5)
    variables = data.get("variables", [])
    assert any(v["status"] == "degraded" for v in variables), (
        f"No variable degraded after 20s. Variables: {variables}"
    )
    assert data["health_score"] < 1.0
    assert data["issue_count"] >= 1


def test_metric_rename_detected(e2e_isolate):
    mock_url, engine_url = e2e_isolate
    _inject(mock_url, "metric_rename", "http_requests_total")
    data = _wait_degraded(engine_url)
    assert data["health_score"] < 1.0
    degraded = [p for p in data["panels"] if p["status"] == "degraded"]
    assert degraded
    assert any(p["error_type"] == "no_data" for p in degraded)


def test_var_resolution_fail_recovers_with_single_open_and_close_event(e2e_isolate):
    mock_url, engine_url = e2e_isolate
    started = time.time()

    _inject(mock_url, "var_resolution_fail", "instance")

    deadline = time.monotonic() + 20.0
    degraded: dict = {}
    while time.monotonic() < deadline:
        degraded = _health(engine_url)
        if degraded.get("health_score", 1.0) < 1.0:
            break
        time.sleep(0.5)

    assert degraded.get("health_score", 1.0) < 1.0, "Variable fault did not impact dashboard health"

    _clear(mock_url)
    recovered = _wait_healthy(engine_url, timeout=20.0)
    assert recovered["health_score"] == 1.0

    pod_events = [
        issue for issue in recovered.get("issues", [])
        if issue["panel_title"] == "$pod" and issue["timestamp"] >= started
    ]
    assert len([issue for issue in pod_events if issue["error_type"] == "var_resolution_fail"]) == 1
    assert len([issue for issue in pod_events if issue["error_type"] == "recovered"]) == 1


def test_cardinality_spike_detected(e2e_isolate):
    """Baseline established on engine startup; spike is 10× → ratio 10 > 1.5."""
    mock_url, engine_url = e2e_isolate
    _inject(mock_url, "cardinality_spike", "http_requests_total")
    data = _wait_degraded(engine_url)
    assert data["health_score"] < 1.0
    degraded = [p for p in data["panels"] if p["status"] == "degraded"]
    assert len(degraded) >= 1
    assert any(p["error_type"] == "cardinality_spike" for p in degraded)


def test_recovery_after_clear(e2e_isolate):
    """Inject fault, confirm degraded, clear, confirm recovered."""
    mock_url, engine_url = e2e_isolate
    _inject(mock_url, "no_data", "http_requests_total")
    degraded = _wait_degraded(engine_url)
    assert degraded["health_score"] < 1.0, "Fault was not detected"

    _clear(mock_url)
    recovered = _wait_healthy(engine_url, timeout=20.0)
    assert recovered["health_score"] == 1.0, (
        f"Engine did not recover after fault cleared. Last score: {recovered.get('health_score')}"
    )
