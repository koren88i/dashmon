"""Unit tests for probe/config.py."""

import pytest

from probe.config import DatasourceConfig, ProbeConfig

pytestmark = pytest.mark.unit


@pytest.fixture
def yaml_dict():
    return {
        "probe_interval_seconds": 10,
        "thresholds": {
            "slow_query_seconds": 3.0,
            "slow_dashboard_seconds": 12.0,
            "stale_data_multiplier": 4.0,
            "cardinality_spike_ratio": 2.0,
            "query_timeout_seconds": 20.0,
        },
        "datasources": [
            {"uid": "prom-a", "url": "http://prom-a:9090", "type": "prometheus"},
            {"uid": "prom-b", "url": "http://prom-b:9090", "type": "prometheus"},
        ],
    }


def test_from_dict_interval(yaml_dict):
    cfg = ProbeConfig.from_dict(yaml_dict)
    assert cfg.probe_interval_seconds == 10


def test_from_dict_thresholds(yaml_dict):
    cfg = ProbeConfig.from_dict(yaml_dict)
    assert cfg.slow_query_seconds == 3.0
    assert cfg.slow_dashboard_seconds == 12.0
    assert cfg.stale_data_multiplier == 4.0
    assert cfg.cardinality_spike_ratio == 2.0
    assert cfg.query_timeout_seconds == 20.0


def test_from_dict_datasources(yaml_dict):
    cfg = ProbeConfig.from_dict(yaml_dict)
    assert len(cfg.datasources) == 2
    assert cfg.datasources[0].uid == "prom-a"
    assert cfg.datasources[1].url == "http://prom-b:9090"


def test_url_for_datasource_found(yaml_dict):
    cfg = ProbeConfig.from_dict(yaml_dict)
    assert cfg.url_for_datasource("prom-a") == "http://prom-a:9090"


def test_url_for_datasource_missing(yaml_dict):
    cfg = ProbeConfig.from_dict(yaml_dict)
    assert cfg.url_for_datasource("does-not-exist") is None


def test_defaults_has_datasource():
    cfg = ProbeConfig.defaults()
    assert len(cfg.datasources) >= 1
    assert cfg.url_for_datasource("prometheus-main") == "http://localhost:9090"


def test_from_dict_missing_keys():
    """Empty dict should fall back to defaults without raising."""
    cfg = ProbeConfig.from_dict({})
    assert cfg.probe_interval_seconds == 15.0
    assert len(cfg.datasources) == 0
