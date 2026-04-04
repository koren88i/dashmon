"""Integration tests for CardinalityProbe."""

import pytest

from probe.config import ErrorType, PanelProbeSpec, ProbeConfig, ProbeStatus
from probe.probes.cardinality_probe import CardinalityProbe

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clear_faults")]

_SPEC = PanelProbeSpec(
    panel_id=1,
    panel_title="Request Rate",
    datasource_uid="prometheus-main",
    datasource_type="prometheus",
    queries=["rate(http_requests_total[5m])"],
    expected_min_series=1,
)


async def test_healthy_and_baseline_learned(mock_backend_url):
    """First probe returns HEALTHY and establishes the baseline."""
    probe = CardinalityProbe()
    config = ProbeConfig.defaults()

    result = await probe.probe(_SPEC, mock_backend_url, config)
    assert result.status == ProbeStatus.HEALTHY
    # Baseline should now be set.
    assert probe._baselines.get(_SPEC.panel_id) is not None


async def test_second_probe_stays_healthy(mock_backend_url):
    """Two consecutive healthy probes should both return HEALTHY."""
    probe = CardinalityProbe()
    config = ProbeConfig.defaults()

    await probe.probe(_SPEC, mock_backend_url, config)   # establish baseline
    result = await probe.probe(_SPEC, mock_backend_url, config)  # should be healthy
    assert result.status == ProbeStatus.HEALTHY


async def test_cardinality_spike(mock_backend_url, inject_fault):
    """After baseline is set, cardinality_spike fault triggers CARDINALITY_SPIKE."""
    probe = CardinalityProbe()
    config = ProbeConfig.defaults()  # spike_ratio=1.5; mock multiplies by 10

    await probe.probe(_SPEC, mock_backend_url, config)  # establish baseline (no fault)
    inject_fault("cardinality_spike", "http_requests_total")
    result = await probe.probe(_SPEC, mock_backend_url, config)
    assert result.status == ProbeStatus.DEGRADED
    assert result.error_type == ErrorType.CARDINALITY_SPIKE


async def test_metric_rename(mock_backend_url, inject_fault):
    """metric_rename fault returns 0 series → METRIC_RENAME (distinct from NO_DATA)."""
    inject_fault("metric_rename", "http_requests_total")
    probe = CardinalityProbe()
    config = ProbeConfig.defaults()
    result = await probe.probe(_SPEC, mock_backend_url, config)
    assert result.status == ProbeStatus.DEGRADED
    assert result.error_type == ErrorType.METRIC_RENAME
