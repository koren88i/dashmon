"""Unit tests for browser render probe helpers."""

from __future__ import annotations

from prometheus_client import generate_latest

from generator.dashboard_targets import load_dashboard_targets
from render_probe.config import dashboard_url, settings_from_registry, slugify
from render_probe.metrics import REGISTRY, record_result
from render_probe.probe import RenderProbeResult
from render_probe.readiness import (
    RENDER_BLANK,
    RENDER_NO_DATA,
    RENDER_PANEL_ERROR,
    DashboardDomSnapshot,
    classify_snapshot,
)


def test_slugify_dashboard_title():
    assert slugify("MongoDB Live Operations") == "mongodb-live-operations"
    assert slugify("!!!") == "dashboard"


def test_dashboard_url_uses_uid_and_slug():
    assert dashboard_url("http://grafana:3000/", "service-health-01", "Service Health") == (
        "http://grafana:3000/d/service-health-01/service-health"
        "?orgId=1&from=now-1h&to=now&refresh=off&kiosk"
    )


def test_settings_from_registry_defaults():
    settings = settings_from_registry(load_dashboard_targets(), env={})

    assert settings.enabled is True
    assert settings.interval_seconds == 15
    assert settings.timeout_seconds == 15
    assert settings.slow_render_seconds == 10
    assert settings.max_concurrency == 2
    assert settings.grafana_url == "http://grafana:3000"
    assert {target.dashboard_uid for target in settings.targets} == {
        "service-health-01",
        "mongodb-ops-01",
        "mongodb-atlas-system-metrics",
        "mongodb-live-ops-01",
    }


def test_settings_from_registry_env_overrides():
    settings = settings_from_registry(
        load_dashboard_targets(),
        env={
            "RENDER_PROBE_ENABLED": "false",
            "RENDER_PROBE_URL_MODE": "local",
            "RENDER_PROBE_GRAFANA_URL": "http://grafana.local",
            "RENDER_PROBE_INTERVAL_SECONDS": "30",
            "RENDER_PROBE_TIMEOUT_SECONDS": "12",
            "RENDER_PROBE_SLOW_SECONDS": "8",
            "RENDER_PROBE_MAX_CONCURRENCY": "1",
        },
    )

    assert settings.enabled is False
    assert settings.url_mode == "local"
    assert settings.grafana_url == "http://grafana.local"
    assert settings.interval_seconds == 30
    assert settings.timeout_seconds == 12
    assert settings.slow_render_seconds == 8
    assert settings.max_concurrency == 1


def test_classify_ready_snapshot():
    result = classify_snapshot(
        DashboardDomSnapshot(
            document_ready=True,
            dashboard_seen=True,
            panel_count=2,
            panel_body_count=2,
            loading_count=0,
            panel_error_count=0,
            no_data_count=0,
        )
    )

    assert result.ready is True


def test_classify_pending_snapshot():
    result = classify_snapshot(
        DashboardDomSnapshot(
            document_ready=True,
            dashboard_seen=True,
            panel_count=2,
            panel_body_count=1,
            loading_count=1,
            panel_error_count=0,
            no_data_count=0,
        )
    )

    assert result.state == "pending"


def test_classify_panel_error_snapshot():
    result = classify_snapshot(
        DashboardDomSnapshot(
            document_ready=True,
            dashboard_seen=True,
            panel_count=2,
            panel_body_count=1,
            loading_count=0,
            panel_error_count=1,
            no_data_count=0,
        )
    )

    assert result.state == "degraded"
    assert result.error_type == RENDER_PANEL_ERROR


def test_classify_no_data_snapshot():
    result = classify_snapshot(
        DashboardDomSnapshot(
            document_ready=True,
            dashboard_seen=True,
            panel_count=2,
            panel_body_count=1,
            loading_count=0,
            panel_error_count=0,
            no_data_count=1,
        )
    )

    assert result.state == "degraded"
    assert result.error_type == RENDER_NO_DATA


def test_classify_blank_snapshot():
    result = classify_snapshot(
        DashboardDomSnapshot(
            document_ready=True,
            dashboard_seen=True,
            panel_count=0,
            panel_body_count=0,
            loading_count=0,
            panel_error_count=0,
            no_data_count=0,
        )
    )

    assert result.state == "degraded"
    assert result.error_type == RENDER_BLANK


def test_record_result_exports_render_metrics():
    result = RenderProbeResult(
        dashboard_uid="unit-render-dashboard",
        dashboard_title="Unit Render Dashboard",
        target_key="unit",
        url="http://grafana/d/unit",
        status="degraded",
        duration_seconds=1.25,
        error_type=RENDER_NO_DATA,
        message="No data",
        timestamp=12345,
    )

    record_result(result)
    text = generate_latest(REGISTRY).decode("utf-8")

    assert 'dashboard_render_status{dashboard_uid="unit-render-dashboard"} 0.0' in text
    assert 'dashboard_render_time_seconds{dashboard_uid="unit-render-dashboard"} 1.25' in text
    assert 'dashboard_render_last_probe_timestamp{dashboard_uid="unit-render-dashboard"} 12345.0' in text
    assert 'dashboard_render_error_total{dashboard_uid="unit-render-dashboard",error_type="render_no_data"}' in text

