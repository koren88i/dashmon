"""Integration tests for StalenessProbe."""

import pytest

from probe.config import ErrorType, PanelProbeSpec, ProbeConfig, ProbeStatus
from probe.probes.staleness_probe import StalenessProbe

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clear_faults")]

_SPEC = PanelProbeSpec(
    panel_id=1,
    panel_title="Request Rate",
    datasource_uid="prometheus-main",
    datasource_type="prometheus",
    queries=["rate(http_requests_total[5m])"],
    expected_min_series=1,
)


async def test_healthy(mock_backend_url):
    """Fresh data from the mock backend should be current."""
    config = ProbeConfig.defaults()
    result = await StalenessProbe().probe(_SPEC, mock_backend_url, config)
    assert result.status == ProbeStatus.HEALTHY
    assert result.max_timestamp is not None


async def test_stale_data(mock_backend_url, inject_fault):
    """stale_data fault makes timestamps 600s old; threshold is 45s."""
    inject_fault("stale_data", "http_requests_total")
    config = ProbeConfig.defaults()  # stale_data_multiplier=3.0, scrape_interval=15s → 45s threshold
    result = await StalenessProbe().probe(_SPEC, mock_backend_url, config)
    assert result.status == ProbeStatus.DEGRADED
    assert result.error_type == ErrorType.STALE_DATA


async def test_no_data_returns_unknown(mock_backend_url, inject_fault):
    """When no series are returned, staleness probe yields UNKNOWN (query_probe handles NO_DATA)."""
    inject_fault("no_data", "http_requests_total")
    config = ProbeConfig.defaults()
    result = await StalenessProbe().probe(_SPEC, mock_backend_url, config)
    assert result.status == ProbeStatus.UNKNOWN
