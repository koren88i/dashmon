"""Fault controller delegation and safety contract tests."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
import yaml

REPO_ROOT = Path(__file__).parent.parent.parent
pytestmark = [pytest.mark.integration]


@pytest.fixture()
def fault_controller_url(tmp_path, unused_tcp_port, mock_backend_url, fault_proxy_url):
    registry = yaml.safe_load((REPO_ROOT / "dashboard_targets.yaml").read_text(encoding="utf-8"))
    for target in registry["targets"]:
        for group in target.get("fault_groups", []):
            if group["kind"] == "mock":
                for field in ("docker_url", "local_url", "browser_url"):
                    group["controller"][field] = mock_backend_url
            if target["key"] == "mongodb_live" and group["kind"] == "proxy":
                for field in ("docker_url", "local_url", "browser_url"):
                    group["controller"][field] = fault_proxy_url
    registry_path = tmp_path / "dashboard_targets.yaml"
    registry_path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")

    env = {
        **os.environ,
        "DASHBOARD_TARGETS_PATH": str(registry_path),
        "FAULT_CONTROLLER_URL_MODE": "local",
    }
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "fault_controller.api:app",
            "--port", str(unused_tcp_port),
            "--log-level", "error",
        ],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://localhost:{unused_tcp_port}"
    try:
        for _ in range(60):
            try:
                if httpx.get(f"{url}/-/healthy", timeout=0.5).status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(0.5)
        else:
            pytest.fail("fault controller did not become healthy")
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_controller_lists_grouped_targets(fault_controller_url):
    body = httpx.get(f"{fault_controller_url}/targets", timeout=5.0).json()

    targets = {target["key"]: target for target in body["targets"]}
    assert "mongodb_live" in targets
    live_groups = {group["key"]: group for group in targets["mongodb_live"]["fault_groups"]}
    assert live_groups["proxy"]["enabled"] is True
    assert live_groups["infra"]["enabled"] is False


def test_controller_delegates_mock_faults(fault_controller_url, mock_backend_url):
    httpx.post(f"{mock_backend_url}/faults/clear", json={"target": "all"}, timeout=5.0)

    resp = httpx.post(
        f"{fault_controller_url}/faults/inject",
        json={
            "target_key": "service",
            "group_key": "mock",
            "type": "no_data",
            "target": "http_requests_total",
            "duration_seconds": 60,
        },
        timeout=5.0,
    )
    active = httpx.get(
        f"{fault_controller_url}/faults/active",
        params={"target_key": "service"},
        timeout=5.0,
    ).json()

    assert resp.status_code == 200
    assert active["faults"][0]["group_key"] == "mock"
    assert active["faults"][0]["type"] == "no_data"
    httpx.post(
        f"{fault_controller_url}/faults/clear",
        json={"target_key": "service", "target": "all"},
        timeout=5.0,
    )


def test_controller_delegates_proxy_faults(fault_controller_url, fault_proxy_url):
    httpx.post(f"{fault_proxy_url}/faults/clear", json={"target": "all"}, timeout=5.0)

    resp = httpx.post(
        f"{fault_controller_url}/faults/inject",
        json={
            "target_key": "mongodb_live",
            "group_key": "proxy",
            "type": "no_data",
            "target": "mongodb_op_counters_total",
            "duration_seconds": 60,
        },
        timeout=5.0,
    )
    active = httpx.get(
        f"{fault_controller_url}/faults/active",
        params={"target_key": "mongodb_live"},
        timeout=5.0,
    ).json()

    assert resp.status_code == 200
    assert active["faults"][0]["group_key"] == "proxy"
    assert active["faults"][0]["kind"] == "proxy"
    httpx.post(
        f"{fault_controller_url}/faults/clear",
        json={"target_key": "mongodb_live", "target": "all"},
        timeout=5.0,
    )


def test_controller_rejects_disabled_infra_group(fault_controller_url):
    resp = httpx.post(
        f"{fault_controller_url}/faults/inject",
        json={
            "target_key": "mongodb_live",
            "group_key": "infra",
            "type": "stop_exporter",
            "target": "mongodb-exporter",
        },
        timeout=5.0,
    )

    assert resp.status_code == 409
    assert resp.json()["detail"]["status"] == "disabled"


def test_controller_rejects_unknown_target(fault_controller_url):
    resp = httpx.get(
        f"{fault_controller_url}/faults/active",
        params={"target_key": "does-not-exist"},
        timeout=5.0,
    )

    assert resp.status_code == 404
