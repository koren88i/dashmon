"""Tests that the mock Prometheus API matches the real Prometheus HTTP contract.

These exist because our own probe engine only uses GET, but real consumers
like Grafana use POST with form-encoded body. If the mock only implements
the subset our code uses, external consumers silently break.
"""

import pytest
import httpx

pytestmark = [pytest.mark.integration]


async def test_post_instant_query_supported(mock_backend_url):
    """Grafana sends instant queries via POST with form body, not GET query params.

    The mock originally only handled GET, causing all Grafana dashboard panels
    to show 'No data'. This test ensures POST remains supported.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{mock_backend_url}/api/v1/query",
            data={"query": "up"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert len(body["data"]["result"]) > 0


async def test_post_range_query_supported(mock_backend_url):
    """Grafana sends range queries via POST with form body.

    Same root cause as test_post_instant_query_supported — the mock must
    support both GET and POST for all Prometheus query endpoints.
    """
    import time
    now = time.time()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{mock_backend_url}/api/v1/query_range",
            data={"query": "up", "start": now - 300, "end": now, "step": 15},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert len(body["data"]["result"]) > 0
    assert len(body["data"]["result"][0]["values"]) > 0


async def test_post_label_values_supported(mock_backend_url):
    """Grafana resolves template variables via POST to /api/v1/label/{name}/values.

    The mock originally only had a GET handler, so the $pod dropdown in
    Grafana's Service Health dashboard was always empty — even without
    any fault injected.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{mock_backend_url}/api/v1/label/instance/values",
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert len(body["data"]) > 0, "Expected at least one label value for 'instance'"


async def test_get_series_supported(mock_backend_url):
    """Grafana resolves label_values(metric, label) via /api/v1/series?match[]=metric.

    It fetches all series matching the metric, then extracts the desired label
    values client-side. Without this endpoint, template variable dropdowns
    are empty in Grafana even though /api/v1/label/.../values works fine.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{mock_backend_url}/api/v1/series",
            params={"match[]": "up"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert len(body["data"]) > 0, "Expected at least one series for 'up'"
    # Each series should have __name__ and label keys.
    assert "__name__" in body["data"][0]


async def test_mongodb_metrics_supported(mock_backend_url):
    """The second dashboard's MongoDB metric surface should return data."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{mock_backend_url}/api/v1/query",
            params={"query": "mongodb_up"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert len(body["data"]["result"]) > 0
    assert body["data"]["result"][0]["metric"]["__name__"] == "mongodb_up"


async def test_post_series_supported(mock_backend_url):
    """POST variant of /api/v1/series — Grafana may use either method."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{mock_backend_url}/api/v1/series",
            data={"match[]": "up"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert len(body["data"]) > 0
