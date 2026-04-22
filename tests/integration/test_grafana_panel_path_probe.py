"""Integration-style tests for Grafana panel-path probing."""

from __future__ import annotations

import httpx
import pytest

from probe.config import (
    ErrorType,
    GrafanaProbeConfig,
    PanelProbeSpec,
    ProbeConfig,
    ProbeStatus,
)
from probe.probes.grafana_panel_path_probe import GrafanaPanelPathProbe

pytestmark = pytest.mark.integration


_SPEC = PanelProbeSpec(
    panel_id=2,
    panel_title="Operation Rate",
    datasource_uid="prometheus-mongo-live",
    datasource_type="prometheus",
    queries=['sum(rate(mongodb_op_counters_total{instance=~".*"}[5m])) by (type)'],
)


def _config() -> ProbeConfig:
    return ProbeConfig(
        query_timeout_seconds=5.0,
        grafana=GrafanaProbeConfig(
            enabled=True,
            url="http://grafana.test",
            query_range_seconds=1800,
            step_seconds=30,
            max_data_points=600,
        ),
    )


def _client(status_code: int, body, content_type: str = "application/json") -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/ds/query"
        if isinstance(body, (dict, list)):
            return httpx.Response(status_code, json=body)
        return httpx.Response(status_code, text=body, headers={"content-type": content_type})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _grafana_body(values=None) -> dict:
    values = values if values is not None else [[1, 2], [10, 11]]
    return {
        "results": {
            "A": {
                "status": 200,
                "frames": [
                    {
                        "schema": {"fields": []},
                        "data": {"values": values},
                    }
                ],
            }
        }
    }


async def test_grafana_panel_path_probe_healthy():
    async with _client(200, _grafana_body()) as client:
        result = await GrafanaPanelPathProbe().probe(_SPEC, "unused", _config(), client=client)

    assert result.status == ProbeStatus.HEALTHY
    assert result.probe_type == "grafana_panel_path"
    assert result.series_count == 1


async def test_grafana_panel_path_probe_http_500_plain_text():
    async with _client(500, "Internal Server Error", "text/plain") as client:
        result = await GrafanaPanelPathProbe().probe(_SPEC, "unused", _config(), client=client)

    assert result.status == ProbeStatus.DEGRADED
    assert result.error_type == ErrorType.PANEL_ERROR
    assert "HTTP 500" in result.message


async def test_grafana_panel_path_probe_malformed_json():
    async with _client(200, "Internal Server Error", "text/plain") as client:
        result = await GrafanaPanelPathProbe().probe(_SPEC, "unused", _config(), client=client)

    assert result.status == ProbeStatus.DEGRADED
    assert result.error_type == ErrorType.PANEL_ERROR


@pytest.mark.parametrize(
    "body",
    [
        {"results": {"A": {"status": 200, "frames": []}}},
        _grafana_body(values=[[1, 2], [None, None]]),
    ],
)
async def test_grafana_panel_path_probe_no_data(body):
    async with _client(200, body) as client:
        result = await GrafanaPanelPathProbe().probe(_SPEC, "unused", _config(), client=client)

    assert result.status == ProbeStatus.DEGRADED
    assert result.error_type == ErrorType.NO_DATA
