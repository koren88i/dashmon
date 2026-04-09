"""Shared pytest fixtures for all test layers.

Subprocess fixtures start real processes so probes talk to real HTTP
servers — no mocking of the mock backend.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
import yaml

REPO_ROOT = Path(__file__).parent.parent

# Ports that avoid colliding with a running Docker stack
# (9090=mock-prometheus, 8000=probe-engine, 9091=real-prometheus, 3000=grafana).
MOCK_PORT = 9092
ENGINE_PORT = 8001


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _wait_http(url: str, timeout: float = 30.0) -> bool:
    """Poll *url* until it returns HTTP 200 or *timeout* seconds elapse."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if httpx.get(url, timeout=2.0).status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _clear_all_faults(base_url: str) -> None:
    with httpx.Client() as client:
        client.post(
            f"{base_url}/faults/clear",
            json={"target": "all"},
            timeout=5.0,
        )


def _inject(base_url: str, fault_type: str, target: str, duration: int = 60) -> None:
    with httpx.Client() as client:
        client.post(
            f"{base_url}/faults/inject",
            json={"type": fault_type, "target": target, "duration_seconds": duration},
            timeout=5.0,
        )


def _wait_health_score(engine_url: str, predicate, timeout: float = 20.0) -> dict:
    """Poll /health until *predicate(data)* is true or timeout. Returns last data."""
    deadline = time.monotonic() + timeout
    data: dict = {}
    while time.monotonic() < deadline:
        try:
            r = httpx.get(f"{engine_url}/health", timeout=2.0)
            if r.status_code == 200:
                data = r.json()
                if predicate(data):
                    return data
        except Exception:
            pass
        time.sleep(0.5)
    return data


# ---------------------------------------------------------------------------
# Session fixtures — subprocess lifecycle
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def mock_backend_url():
    """Start the mock Prometheus backend on port 9091 for the test session."""
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "mock_backend.prometheus_api:app",
            "--port", str(MOCK_PORT),
            "--log-level", "error",
        ],
        cwd=str(REPO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://localhost:{MOCK_PORT}"
    if not _wait_http(f"{url}/-/healthy"):
        proc.terminate()
        pytest.fail(f"Mock backend did not become healthy within 30s on port {MOCK_PORT}")
    yield url
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="session")
def probe_engine_url(mock_backend_url, tmp_path_factory):
    """Start the probe engine on port 8001, pointed at the test mock backend."""
    # Fast probe interval so E2E tests don't have to wait long.
    cfg = {
        "probe_interval_seconds": 3,
        "max_concurrency": 10,
        "thresholds": {
            "slow_query_seconds": 5.0,
            "slow_dashboard_seconds": 15.0,
            "stale_data_multiplier": 3.0,
            "cardinality_spike_ratio": 1.5,
            "query_timeout_seconds": 25.0,
        },
        "datasources": [
            {"uid": "prometheus-main", "url": mock_backend_url, "type": "prometheus"},
        ],
    }
    tmp = tmp_path_factory.mktemp("engine_cfg")
    cfg_path = tmp / "config.yaml"
    cfg_path.write_text(yaml.dump(cfg))

    env = {
        **os.environ,
        "CONFIG_PATH": str(cfg_path),
        "DASHBOARD_PATH": str(REPO_ROOT / "demo" / "example_dashboard.json"),
    }
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "probe.engine:app",
            "--port", str(ENGINE_PORT),
            "--log-level", "error",
        ],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://localhost:{ENGINE_PORT}"
    if not _wait_http(f"{url}/health"):
        proc.terminate()
        pytest.fail(f"Probe engine did not start within 30s on port {ENGINE_PORT}")

    # Wait for first complete probe cycle (health_score = 1.0 means all panels healthy).
    result = _wait_health_score(url, lambda d: d.get("health_score", 0) == 1.0, timeout=30.0)
    if result.get("health_score", 0) != 1.0:
        proc.terminate()
        pytest.fail("Probe engine did not reach health_score=1.0 within 30s")

    yield url
    proc.terminate()
    proc.wait(timeout=10)


# ---------------------------------------------------------------------------
# Per-test fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def clear_faults(mock_backend_url):
    """Clear all faults before and after each test."""
    _clear_all_faults(mock_backend_url)
    yield
    _clear_all_faults(mock_backend_url)


@pytest.fixture()
def inject_fault(mock_backend_url):
    """Return a callable that injects a fault into the mock backend."""
    def _do_inject(fault_type: str, target: str, duration: int = 60) -> None:
        _inject(mock_backend_url, fault_type, target, duration)
    return _do_inject


@pytest.fixture()
def e2e_isolate(mock_backend_url, probe_engine_url):
    """Ensure clean, fully-healthy state before each E2E test.

    Clears faults and waits for health_score=1.0 before yielding.
    Clears faults again after the test (no wait — next test's setup handles it).
    """
    _clear_all_faults(mock_backend_url)
    _wait_health_score(probe_engine_url, lambda d: d.get("health_score", 0) == 1.0)
    yield mock_backend_url, probe_engine_url
    _clear_all_faults(mock_backend_url)
