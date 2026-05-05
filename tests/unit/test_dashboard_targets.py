"""Unit tests for the dashboard target registry."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml

from generator.dashboard_targets import (
    DashboardTargetError,
    SIMULATOR_TARGETS_PATH,
    check_compose_consistency,
    check_generated_artifacts,
    generated_artifacts,
    load_dashboard_targets,
    main,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).parent.parent.parent


@pytest.fixture(scope="module")
def registry():
    return load_dashboard_targets()


def test_registry_loads_current_dashboard_targets(registry):
    targets = {target["key"]: target for target in registry["targets"]}

    assert set(targets) == {"service", "mongodb", "mongodb_atlas", "mongodb_live"}
    assert targets["service"]["dashboard_uid"] == "service-health-01"
    assert targets["mongodb"]["dashboard_uid"] == "mongodb-ops-01"
    assert targets["mongodb_atlas"]["dashboard_uid"] == "mongodb-atlas-system-metrics"
    assert targets["mongodb_live"]["dashboard_uid"] == "mongodb-live-ops-01"


def test_registry_declares_unique_contract_fields(registry):
    for field_path in (
        ("key",),
        ("dashboard_uid",),
        ("datasource", "uid"),
        ("probe", "service"),
        ("probe", "host_port"),
    ):
        values = [_field(target, field_path) for target in registry["targets"]]
        assert len(values) == len(set(values)), f"registry has duplicate {'.'.join(field_path)}"

    services = []
    host_ports = []
    for target in registry["targets"]:
        for section in ("mock", "proxy", "live_prometheus", "exporter", "probe"):
            if section in target:
                services.append(target[section]["service"])
                host_ports.append(target[section]["host_port"])
    services.append(registry["fault_controller"]["service"])
    host_ports.append(registry["fault_controller"]["host_port"])
    services.append(registry["render_probe"]["service"])
    host_ports.append(registry["render_probe"]["host_port"])
    assert len(services) == len(set(services))
    assert len(host_ports) == len(set(host_ports))


def test_registry_declares_fault_groups_by_class(registry):
    targets = {target["key"]: target for target in registry["targets"]}

    for key in ("service", "mongodb", "mongodb_atlas"):
        groups = {group["key"]: group for group in targets[key]["fault_groups"]}
        assert set(groups) == {"mock"}
        assert groups["mock"]["kind"] == "mock"
        assert groups["mock"]["enabled"] is True

    live_groups = {group["key"]: group for group in targets["mongodb_live"]["fault_groups"]}
    assert set(live_groups) == {"proxy", "infra"}
    assert live_groups["proxy"]["kind"] == "proxy"
    assert live_groups["proxy"]["enabled"] is True
    assert live_groups["infra"]["kind"] == "infra"
    assert live_groups["infra"]["enabled"] is False
    assert live_groups["infra"]["disabled_reason"]


def test_registry_dashboard_metadata_matches_source_json(registry):
    for target in registry["targets"]:
        for field in ("source_dashboard_path", "grafana_source_dashboard_path"):
            dashboard = json.loads((REPO_ROOT / target[field]).read_text(encoding="utf-8"))
            assert dashboard["uid"] == target["dashboard_uid"]
            assert dashboard["title"] == target["title"]


def test_registry_rejects_dashboard_metadata_mismatch(tmp_path):
    data = yaml.safe_load((REPO_ROOT / "dashboard_targets.yaml").read_text(encoding="utf-8"))
    data["targets"][0]["title"] = "Not The Real Dashboard"
    registry_path = tmp_path / "dashboard_targets.yaml"
    registry_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    with pytest.raises(DashboardTargetError, match="title"):
        load_dashboard_targets(registry_path)


def test_registry_rejects_duplicate_service_names(tmp_path):
    data = yaml.safe_load((REPO_ROOT / "dashboard_targets.yaml").read_text(encoding="utf-8"))
    data["targets"][1]["probe"]["service"] = data["targets"][0]["probe"]["service"]
    registry_path = tmp_path / "dashboard_targets.yaml"
    registry_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    with pytest.raises(DashboardTargetError, match="duplicate probe service"):
        load_dashboard_targets(registry_path)


def test_generated_artifacts_are_up_to_date(registry):
    assert check_generated_artifacts(registry) == []


def test_generated_probe_configs_enable_grafana_only_for_docker(registry):
    artifacts = generated_artifacts(registry)

    docker_cfg = yaml.safe_load(artifacts[REPO_ROOT / "config.mongo-live.docker.yaml"])
    local_cfg = yaml.safe_load(artifacts[REPO_ROOT / "config.yaml"])

    assert docker_cfg["grafana"]["enabled"] is True
    assert docker_cfg["grafana"]["url"] == "http://grafana:3000"
    assert local_cfg["grafana"]["enabled"] is False
    assert local_cfg["grafana"]["url"] == "http://localhost:3000"


def test_render_probe_defaults(registry):
    defaults = registry["render_probe_defaults"]
    render_probe = registry["render_probe"]

    assert defaults["enabled"] is True
    assert defaults["interval_seconds"] == 15
    assert defaults["timeout_seconds"] == 15
    assert defaults["slow_render_seconds"] == 10
    assert defaults["max_concurrency"] == 2
    assert defaults["grafana"]["docker_url"] == "http://grafana:3000"
    assert render_probe["service"] == "browser-render-probe"
    assert render_probe["host_port"] == 8012


def test_check_cli_returns_success(capsys):
    assert main(["--check"]) == 0
    assert "up to date" in capsys.readouterr().out


def test_compose_is_consistent_with_registry(registry):
    assert check_compose_consistency(registry) == []


def test_simulator_targets_js_contains_current_targets(registry):
    content = generated_artifacts(registry)[SIMULATOR_TARGETS_PATH]
    payload = content.removeprefix("window.DASHBOARD_TARGETS = ").removesuffix(";\n")
    data = json.loads(payload)

    assert set(data) == {"service", "mongodb", "mongodb_atlas", "mongodb_live"}
    assert data["service"]["probeUrl"] == "http://localhost:8000"
    assert data["service"]["renderProbeUrl"] == "http://localhost:8012"
    assert data["mongodb_atlas"]["probeUrl"] == "http://localhost:8004"
    assert data["mongodb_live"]["probeUrl"] == "http://localhost:8006"
    assert data["mongodb"]["controllerUrl"] == "http://localhost:8010"
    assert "faults" not in data["mongodb"]
    assert data["mongodb"]["faultGroups"][0]["kind"] == "mock"
    assert any(fault["target"] == "mongodb_op_counters_total" for fault in data["mongodb"]["faultGroups"][0]["faults"])
    assert any(fault["target"] == "mongodb_opcounters_query" for fault in data["mongodb_atlas"]["faultGroups"][0]["faults"])
    live_groups = {group["key"]: group for group in data["mongodb_live"]["faultGroups"]}
    assert live_groups["proxy"]["enabled"] is True
    assert live_groups["infra"]["enabled"] is False
    panel_fault = next(
        fault
        for fault in live_groups["proxy"]["faults"]
        if fault["type"] == "panel_query_http_500"
    )
    assert panel_fault["affected_layers"] == ["grafana_panel_path", "browser_render"]
    assert panel_fault["expected_sre_signals"] == ["panel_error", "render_panel_error"]
    variable_error_fault = next(
        fault
        for fault in live_groups["proxy"]["faults"]
        if fault["type"] == "variable_query_error"
    )
    assert variable_error_fault["affected_layers"] == ["variable_resolution", "variable_dependency", "browser_render"]
    assert variable_error_fault["expected_sre_signals"] == [
        "variable_query_error",
        "blocked_by_variable",
        "render_panel_error",
    ]

    no_data_fault = next(
        fault
        for fault in data["service"]["faultGroups"][0]["faults"]
        if fault["type"] == "no_data"
    )
    assert "browser_render" in no_data_fault["affected_layers"]
    assert "render_no_data" in no_data_fault["expected_sre_signals"]

    for target in data.values():
        executable_groups = [group for group in target["faultGroups"] if group["enabled"]]
        assert any(
            fault["type"] == "variable_query_error"
            for group in executable_groups
            for fault in group["faults"]
        )


def test_registry_copy_is_not_mutated_by_artifact_generation(registry):
    before = copy.deepcopy(registry)
    generated_artifacts(registry)
    assert registry == before


def _field(data: dict, path: tuple[str, ...]):
    current = data
    for key in path:
        current = current[key]
    return current
