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
