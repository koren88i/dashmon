"""Test that stale degraded-probe-type metric series are cleaned up on recovery.

When a panel goes degraded, the engine writes dashboard_panel_status with
probe_type="no_data" (or similar) = 0. When the panel recovers, the engine
must reset ALL probe_type series for that panel back to 1 — not just the
"query" series. Otherwise the "Active Issues" panel in the Grafana meta-dashboard
stays red permanently because Prometheus still has stale series with value 0.
"""

import time
import pytest
import httpx

pytestmark = [pytest.mark.e2e]


async def test_degraded_probe_type_series_cleared_on_recovery(e2e_isolate):
    """After fault clear + recovery, no dashboard_panel_status series should be 0.

    This failed before the fix: probe_type='no_data' series stayed at 0
    after the panel recovered, making 'Active Issues' count permanently wrong.
    """
    mock_url, engine_url = e2e_isolate

    # Inject no_data fault.
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{mock_url}/faults/inject",
            json={"type": "no_data", "target": "http_requests_total", "duration_seconds": 60},
        )

    # Wait for probe to detect the fault.
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        r = httpx.get(f"{engine_url}/health", timeout=2)
        if r.json().get("health_score", 1) < 1.0:
            break
        time.sleep(0.5)

    # Clear and wait for full recovery.
    async with httpx.AsyncClient() as client:
        await client.post(f"{mock_url}/faults/clear", json={"target": "all"})

    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        r = httpx.get(f"{engine_url}/health", timeout=2)
        if r.json().get("health_score", 1) == 1.0:
            break
        time.sleep(0.5)

    # Now check Prometheus: no panel_status series should be 0.
    r = httpx.get(f"{engine_url}/metrics", timeout=5)
    lines = r.text.splitlines()
    stale_zeros = [
        line for line in lines
        if line.startswith("dashboard_panel_status{")
        and line.rstrip().endswith(" 0.0")
    ]
    assert stale_zeros == [], (
        f"Stale degraded series still present after recovery:\n"
        + "\n".join(stale_zeros)
    )
