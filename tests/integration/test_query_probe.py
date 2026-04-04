"""Integration tests for QueryProbe.

Requires the mock backend subprocess (mock_backend_url fixture).
Probes are called directly — no engine, no FastAPI overhead.
"""

import pytest

from probe.config import ErrorType, PanelProbeSpec, ProbeConfig, ProbeStatus
from probe.probes.query_probe import QueryProbe

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clear_faults")]

# Panel spec targeting http_requests_total — served by the mock backend.
_SPEC = PanelProbeSpec(
    panel_id=1,
    panel_title="Request Rate",
    datasource_uid="prometheus-main",
    datasource_type="prometheus",
    queries=["rate(http_requests_total[5m])"],
    expected_min_series=1,
)


def _config(**overrides) -> ProbeConfig:
    cfg = ProbeConfig.defaults()
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


async def test_healthy(mock_backend_url):
    result = await QueryProbe().probe(_SPEC, mock_backend_url, _config())
    assert result.status == ProbeStatus.HEALTHY
    assert result.error_type is None
    assert result.series_count > 0
    assert result.duration_seconds >= 0


async def test_no_data(mock_backend_url, inject_fault):
    inject_fault("no_data", "http_requests_total")
    result = await QueryProbe().probe(_SPEC, mock_backend_url, _config())
    assert result.status == ProbeStatus.DEGRADED
    assert result.error_type == ErrorType.NO_DATA
    assert result.series_count == 0


async def test_slow_query(mock_backend_url, inject_fault):
    inject_fault("slow_query", "http_requests_total")
    # threshold=5s; mock sleeps 8s → SLOW_QUERY
    result = await QueryProbe().probe(_SPEC, mock_backend_url, _config(slow_query_seconds=5.0))
    assert result.status == ProbeStatus.DEGRADED
    assert result.error_type == ErrorType.SLOW_QUERY
    assert result.duration_seconds > 5.0


async def test_timeout(mock_backend_url, inject_fault):
    inject_fault("slow_query", "http_requests_total")
    # timeout=2s; mock sleeps 8s → QUERY_TIMEOUT
    result = await QueryProbe().probe(_SPEC, mock_backend_url, _config(query_timeout_seconds=2.0))
    assert result.status == ProbeStatus.DEGRADED
    assert result.error_type == ErrorType.QUERY_TIMEOUT


async def test_panel_error():
    """Unreachable URL produces PANEL_ERROR."""
    result = await QueryProbe().probe(_SPEC, "http://localhost:19999", _config())
    assert result.status == ProbeStatus.DEGRADED
    assert result.error_type == ErrorType.PANEL_ERROR
