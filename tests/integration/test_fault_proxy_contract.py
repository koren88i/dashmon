"""Faultable Prometheus proxy contract tests."""

from __future__ import annotations

import time

import httpx
import pytest

pytestmark = [pytest.mark.integration]


def _clear(proxy_url: str) -> None:
    httpx.post(f"{proxy_url}/faults/clear", json={"target": "all"}, timeout=5.0)


def _inject(proxy_url: str, fault_type: str, target: str) -> None:
    httpx.post(
        f"{proxy_url}/faults/inject",
        json={"type": fault_type, "target": target, "duration_seconds": 60},
        timeout=5.0,
    )


def test_proxy_pass_through_preserves_prometheus_response(fault_proxy_url):
    _clear(fault_proxy_url)
    resp = httpx.get(
        f"{fault_proxy_url}/api/v1/query",
        params={"query": "up"},
        timeout=5.0,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert len(body["data"]["result"]) > 0


def test_proxy_post_query_range_preserves_form_body(fault_proxy_url):
    _clear(fault_proxy_url)
    end = time.time()
    resp = httpx.post(
        f"{fault_proxy_url}/api/v1/query_range",
        data={
            "query": "up",
            "start": end - 300,
            "end": end,
            "step": 15,
        },
        timeout=5.0,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["data"]["resultType"] == "matrix"
    assert len(body["data"]["result"]) > 0


def test_proxy_panel_query_http_500_only_breaks_post_query_range(fault_proxy_url):
    _clear(fault_proxy_url)
    _inject(fault_proxy_url, "panel_query_http_500", "http_requests_total")

    try:
        instant = httpx.get(
            f"{fault_proxy_url}/api/v1/query",
            params={"query": "http_requests_total"},
            timeout=5.0,
        )
        assert instant.status_code == 200
        assert instant.json()["status"] == "success"

        end = time.time()
        panel_path = httpx.post(
            f"{fault_proxy_url}/api/v1/query_range",
            data={
                "query": "rate(http_requests_total[5m])",
                "start": end - 300,
                "end": end,
                "step": 15,
            },
            timeout=5.0,
        )
        assert panel_path.status_code == 500
        assert panel_path.text == "Internal Server Error"
    finally:
        _clear(fault_proxy_url)

    recovered = httpx.post(
        f"{fault_proxy_url}/api/v1/query_range",
        data={
            "query": "rate(http_requests_total[5m])",
            "start": end - 300,
            "end": end,
            "step": 15,
        },
        timeout=5.0,
    )
    assert recovered.status_code == 200
    assert recovered.json()["status"] == "success"


@pytest.mark.parametrize(
    ("fault_type", "query", "expected_len"),
    [
        ("no_data", "http_requests_total", 0),
        ("metric_rename", "http_requests_total", 0),
    ],
)
def test_proxy_empty_result_faults(fault_proxy_url, fault_type, query, expected_len):
    _clear(fault_proxy_url)
    _inject(fault_proxy_url, fault_type, "http_requests_total")

    resp = httpx.get(
        f"{fault_proxy_url}/api/v1/query",
        params={"query": query},
        timeout=5.0,
    )

    assert len(resp.json()["data"]["result"]) == expected_len
    _clear(fault_proxy_url)


def test_proxy_stale_data_mutates_timestamps(fault_proxy_url):
    _clear(fault_proxy_url)
    _inject(fault_proxy_url, "stale_data", "http_requests_total")

    resp = httpx.get(
        f"{fault_proxy_url}/api/v1/query",
        params={"query": "http_requests_total"},
        timeout=5.0,
    )
    ts = resp.json()["data"]["result"][0]["value"][0]

    assert time.time() - ts > 300
    _clear(fault_proxy_url)


def test_proxy_cardinality_spike_clones_series(fault_proxy_url):
    _clear(fault_proxy_url)
    baseline = httpx.get(
        f"{fault_proxy_url}/api/v1/query",
        params={"query": "http_requests_total"},
        timeout=5.0,
    ).json()
    _inject(fault_proxy_url, "cardinality_spike", "http_requests_total")

    spiked = httpx.get(
        f"{fault_proxy_url}/api/v1/query",
        params={"query": "http_requests_total"},
        timeout=5.0,
    ).json()

    assert len(spiked["data"]["result"]) > len(baseline["data"]["result"])
    assert any("spike_id" in item["metric"] for item in spiked["data"]["result"])
    _clear(fault_proxy_url)


def test_proxy_variable_fault_returns_empty_label_values(fault_proxy_url):
    _clear(fault_proxy_url)
    _inject(fault_proxy_url, "var_resolution_fail", "instance")

    try:
        resp = httpx.get(
            f"{fault_proxy_url}/api/v1/label/instance/values",
            timeout=5.0,
        )

        assert resp.json()["data"] == []
    finally:
        _clear(fault_proxy_url)


def test_proxy_variable_fault_returns_empty_series_for_grafana_dropdowns(fault_proxy_url):
    _clear(fault_proxy_url)
    _inject(fault_proxy_url, "var_resolution_fail", "instance")

    try:
        resp = httpx.get(
            f"{fault_proxy_url}/api/v1/series",
            params={"match[]": "up"},
            timeout=5.0,
        )

        assert resp.status_code == 200
        assert resp.json()["data"] == []
    finally:
        _clear(fault_proxy_url)


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/api/v1/label/instance/values", None),
        ("/api/v1/series", {"match[]": "up"}),
    ],
)
def test_proxy_variable_query_error_returns_prometheus_error(fault_proxy_url, path, params):
    _clear(fault_proxy_url)
    _inject(fault_proxy_url, "variable_query_error", "instance")

    try:
        resp = httpx.get(
            f"{fault_proxy_url}{path}",
            params=params,
            timeout=5.0,
        )

        assert resp.status_code == 500
        assert resp.json()["status"] == "error"
        assert resp.json()["error"] == "simulated variable query failure"
    finally:
        _clear(fault_proxy_url)
