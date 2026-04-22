"""Integration tests for VariableProbe."""

import pytest

from probe.config import ErrorType, ProbeConfig, ProbeStatus, VariableProbeSpec
from probe.probes.variable_probe import VariableProbe

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clear_faults")]

# The mock backend serves the `job` label with values: api-server, node, prometheus.
_SPEC = VariableProbeSpec(
    name="env",
    datasource_uid="prometheus-main",
    query="label_values(up, job)",
    is_chained=False,
    chain_depth=0,
)


async def test_healthy(mock_backend_url):
    config = ProbeConfig.defaults()
    result = await VariableProbe().probe(_SPEC, mock_backend_url, config)
    assert result.status == ProbeStatus.HEALTHY
    assert result.values_count > 0
    assert result.error_type is None


async def test_var_resolution_fail(mock_backend_url, inject_fault):
    """var_resolution_fail targeting the label name makes values empty."""
    inject_fault("var_resolution_fail", "job")
    config = ProbeConfig.defaults()
    result = await VariableProbe().probe(_SPEC, mock_backend_url, config)
    assert result.status == ProbeStatus.DEGRADED
    assert result.error_type == ErrorType.VAR_RESOLUTION_FAIL
    assert result.values_count == 0


async def test_variable_query_error(mock_backend_url, inject_fault):
    """A hard variable endpoint failure is distinct from an empty dropdown."""
    inject_fault("variable_query_error", "job")
    config = ProbeConfig.defaults()
    result = await VariableProbe().probe(_SPEC, mock_backend_url, config)

    assert result.status == ProbeStatus.DEGRADED
    assert result.error_type == ErrorType.VARIABLE_QUERY_ERROR
    assert result.values_count == 0
    assert "query failed" in result.message
    assert result.to_dict()["message"] == result.message
