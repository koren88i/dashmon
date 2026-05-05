"""Dashboard target registry and generated artifact checks.

The registry keeps each isolated dashboard path explicit while making the
cross-file contracts testable before adding a third dashboard.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from generator.alert_rules import generate_alert_rules
from generator.meta_dashboard import generate_meta_dashboard
from probe.parser import parse_dashboard

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REGISTRY_PATH = REPO_ROOT / "dashboard_targets.yaml"
SIMULATOR_TARGETS_PATH = REPO_ROOT / "demo" / "dashboard_targets.js"
PROMETHEUS_CONFIG_PATH = REPO_ROOT / "prometheus" / "prometheus.yml"
GRAFANA_DATASOURCES_PATH = REPO_ROOT / "grafana" / "provisioning" / "datasources" / "datasources.yaml"
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"

FAULT_LAYER_DEFAULTS: dict[str, dict[str, list[str]]] = {
    "no_data": {
        "affected_layers": ["datasource_api", "grafana_panel_path", "browser_render"],
        "expected_sre_signals": ["no_data", "render_no_data"],
    },
    "metric_rename": {
        "affected_layers": ["datasource_api", "grafana_panel_path", "browser_render"],
        "expected_sre_signals": ["no_data", "metric_rename", "render_no_data"],
    },
    "slow_query": {
        "affected_layers": ["datasource_api", "grafana_panel_path", "browser_render"],
        "expected_sre_signals": ["slow_query", "query_timeout", "render_timeout"],
    },
    "stale_data": {
        "affected_layers": ["stale_data"],
        "expected_sre_signals": ["stale_data"],
    },
    "cardinality_spike": {
        "affected_layers": ["cardinality_spike"],
        "expected_sre_signals": ["cardinality_spike"],
    },
    "var_resolution_fail": {
        "affected_layers": ["variable_resolution", "variable_dependency", "browser_render"],
        "expected_sre_signals": ["var_resolution_fail", "blocked_by_variable", "render_no_data"],
    },
    "variable_query_error": {
        "affected_layers": ["variable_resolution", "variable_dependency", "browser_render"],
        "expected_sre_signals": ["variable_query_error", "blocked_by_variable", "render_panel_error"],
    },
    "panel_query_http_500": {
        "affected_layers": ["grafana_panel_path", "browser_render"],
        "expected_sre_signals": ["panel_error", "render_panel_error"],
    },
}


class DashboardTargetError(ValueError):
    """Raised when the target registry or generated artifacts are invalid."""


def load_dashboard_targets(path: str | Path = DEFAULT_REGISTRY_PATH) -> dict[str, Any]:
    """Load and validate the dashboard target registry."""
    registry_path = _repo_path(path)
    data = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise DashboardTargetError(f"{registry_path} must contain a mapping")
    _validate_registry(data)
    return data


def generated_artifacts(registry: dict[str, Any]) -> dict[Path, str]:
    """Return generated artifact content keyed by absolute path."""
    artifacts: dict[Path, str] = {}
    probe_defaults = registry["probe_defaults"]

    for target in registry["targets"]:
        dashboard = _load_json(target["source_dashboard_path"])
        panels, variables = parse_dashboard(dashboard)

        artifacts[_repo_path(target["sre_dashboard_path"])] = _json_text(
            generate_meta_dashboard(dashboard, panels, variables)
        )
        artifacts[_repo_path(target["alert_rules_path"])] = _yaml_text(
            generate_alert_rules(dashboard, panels, variables)
        )
        artifacts[_repo_path(target["probe_config_path"])] = _yaml_text(
            _probe_config(probe_defaults, target, "docker_url")
        )
        if target.get("local_probe_config_path"):
            artifacts[_repo_path(target["local_probe_config_path"])] = _yaml_text(
                _probe_config(probe_defaults, target, "local_url")
            )
        if target.get("live_prometheus_config_path"):
            artifacts[_repo_path(target["live_prometheus_config_path"])] = _yaml_text(
                _live_prometheus_config(target)
            )

    artifacts[GRAFANA_DATASOURCES_PATH] = _yaml_text(_grafana_datasources(registry))
    artifacts[PROMETHEUS_CONFIG_PATH] = _yaml_text(_prometheus_config(registry))
    artifacts[SIMULATOR_TARGETS_PATH] = _simulator_targets_js(registry)
    return artifacts


def check_generated_artifacts(registry: dict[str, Any]) -> list[str]:
    """Return human-readable mismatches for generated files and Compose wiring."""
    errors = []
    for path, expected in generated_artifacts(registry).items():
        if not path.exists():
            errors.append(f"missing generated artifact: {_display_path(path)}")
            continue
        actual = path.read_text(encoding="utf-8")
        if _normalize_newlines(actual) != _normalize_newlines(expected):
            errors.append(f"generated artifact is stale: {_display_path(path)}")

    errors.extend(check_compose_consistency(registry))
    return errors


def write_generated_artifacts(registry: dict[str, Any]) -> None:
    """Write all generated artifacts derived from the registry."""
    for path, content in generated_artifacts(registry).items():
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_text(path, content)


def check_compose_consistency(registry: dict[str, Any]) -> list[str]:
    """Validate explicit Docker Compose services against the registry."""
    if not COMPOSE_PATH.exists():
        return [f"missing Docker Compose file: {_display_path(COMPOSE_PATH)}"]

    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    services = compose.get("services", {}) if isinstance(compose, dict) else {}
    errors: list[str] = []

    for target in registry["targets"]:
        probe = target["probe"]
        probe_name = probe["service"]

        if probe_name not in services:
            errors.append(f"Compose missing probe service {probe_name!r} for target {target['key']!r}")
            continue

        for section in ("mock", "proxy", "live_prometheus", "exporter"):
            if section in target:
                errors.extend(_check_compose_service_port(target[section], services, section, target["key"]))

        probe_port = f"${{{probe['host_port_env']}:-{probe['host_port']}}}:{probe['container_port']}"
        if probe_port not in services[probe_name].get("ports", []):
            errors.append(f"Compose probe service {probe_name!r} missing port {probe_port!r}")

        env = services[probe_name].get("environment", {})
        config_path = f"/app/{Path(target['probe_config_path']).name}"
        dashboard_path = f"/app/{target['source_dashboard_path']}"
        if env.get("CONFIG_PATH") != config_path:
            errors.append(f"Compose probe service {probe_name!r} CONFIG_PATH should be {config_path!r}")
        if env.get("DASHBOARD_PATH") != dashboard_path:
            errors.append(f"Compose probe service {probe_name!r} DASHBOARD_PATH should be {dashboard_path!r}")

        probe_depends = services[probe_name].get("depends_on", {})
        dependency = _probe_dependency(target)
        if dependency and dependency not in probe_depends:
            errors.append(f"Compose probe service {probe_name!r} should depend on {dependency!r}")

        if "proxy" in target:
            proxy_env = services.get(target["proxy"]["service"], {}).get("environment", {})
            upstream = target.get("live_prometheus", {}).get("service")
            if upstream and proxy_env.get("UPSTREAM_PROMETHEUS_URL") != f"http://{upstream}:9090":
                errors.append(
                    f"Compose proxy service {target['proxy']['service']!r} has wrong UPSTREAM_PROMETHEUS_URL"
                )

    errors.extend(_check_compose_grafana_volumes(registry, services))
    errors.extend(_check_compose_dependency_set(registry, services, "prometheus", "probe"))
    errors.extend(_check_compose_datasource_dependencies(registry, services, "grafana"))
    errors.extend(_check_compose_dependency_set(registry, services, "demo-ui", "probe"))
    errors.extend(_check_fault_controller_consistency(registry, services))
    errors.extend(_check_render_probe_consistency(registry, services))
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate or write dashboard target artifacts.")
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY_PATH), help="Path to dashboard_targets.yaml")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Check generated artifacts and Compose consistency")
    mode.add_argument("--write", action="store_true", help="Write generated artifacts from the registry")
    args = parser.parse_args(argv)

    registry = load_dashboard_targets(args.registry)
    if args.write:
        write_generated_artifacts(registry)
        print("Wrote dashboard target artifacts.")
        return 0

    errors = check_generated_artifacts(registry)
    if errors:
        for error in errors:
            print(error)
        return 1
    print("Dashboard target artifacts are up to date.")
    return 0


def _validate_registry(registry: dict[str, Any]) -> None:
    targets = registry.get("targets")
    if not isinstance(targets, list) or not targets:
        raise DashboardTargetError("dashboard_targets.yaml must define at least one target")

    _require_mapping(registry, "probe_defaults")
    _require_mapping(registry, "render_probe_defaults")
    _require_mapping(registry, "probe_metrics_datasource")
    _require_mapping(registry, "fault_controller")
    _require_mapping(registry, "render_probe")

    unique_fields: dict[str, set[Any]] = {
        "key": set(),
        "dashboard_uid": set(),
        "datasource.uid": set(),
        "probe.service": set(),
        "probe.host_port": set(),
        "fault_group.key": set(),
        "service": set(),
        "host_port": set(),
    }

    for target in targets:
        if not isinstance(target, dict):
            raise DashboardTargetError("each target must be a mapping")
        _validate_target_shape(target)
        _validate_dashboard_metadata(target)
        _remember_unique(unique_fields["key"], target["key"], "target key")
        _remember_unique(unique_fields["dashboard_uid"], target["dashboard_uid"], "dashboard_uid")
        _remember_unique(unique_fields["datasource.uid"], target["datasource"]["uid"], "datasource uid")
        _remember_unique(unique_fields["probe.service"], target["probe"]["service"], "probe service")
        _remember_unique(unique_fields["probe.host_port"], target["probe"]["host_port"], "probe host port")
        _remember_unique(unique_fields["service"], target["probe"]["service"], "service")
        _remember_unique(unique_fields["host_port"], target["probe"]["host_port"], "host port")
        _validate_optional_service_section(target, "mock", unique_fields)
        _validate_optional_service_section(target, "proxy", unique_fields)
        _validate_optional_service_section(target, "live_prometheus", unique_fields)
        _validate_optional_service_section(target, "exporter", unique_fields)
        _validate_fault_groups(target)
        if target.get("live_prometheus"):
            _validate_live_prometheus(target)

    controller = registry["fault_controller"]
    _validate_service_section(controller, "fault_controller")
    _remember_unique(unique_fields["service"], controller["service"], "service")
    _remember_unique(unique_fields["host_port"], controller["host_port"], "host port")
    render_probe = registry["render_probe"]
    _validate_service_section(render_probe, "render_probe")
    _remember_unique(unique_fields["service"], render_probe["service"], "service")
    _remember_unique(unique_fields["host_port"], render_probe["host_port"], "host port")


def _validate_target_shape(target: dict[str, Any]) -> None:
    for key in (
        "key",
        "title",
        "dashboard_uid",
        "source_dashboard_path",
        "grafana_source_dashboard_path",
        "sre_dashboard_path",
        "alert_rules_path",
        "probe_config_path",
        "datasource",
        "probe",
        "fault_groups",
        "surfaces",
    ):
        if key not in target:
            raise DashboardTargetError(f"target missing required field: {key}")
    _require_mapping(target, "datasource")
    _require_mapping(target, "probe")
    for section, fields in {
        "datasource": ("name", "type", "uid", "docker_url", "local_url", "grafana_url"),
        "probe": ("service", "host_port_env", "host_port", "container_port", "browser_url"),
    }.items():
        for field in fields:
            if field not in target[section]:
                raise DashboardTargetError(f"target {target.get('key', '<unknown>')} missing {section}.{field}")
    if not isinstance(target["surfaces"], dict) or not target["surfaces"]:
        raise DashboardTargetError(f"target {target['key']} must define surfaces")


def _validate_dashboard_metadata(target: dict[str, Any]) -> None:
    for field in ("source_dashboard_path", "grafana_source_dashboard_path"):
        dashboard = _load_json(target[field])
        if dashboard.get("uid") != target["dashboard_uid"]:
            raise DashboardTargetError(
                f"{target[field]} uid {dashboard.get('uid')!r} does not match registry "
                f"{target['dashboard_uid']!r}"
            )
        if dashboard.get("title") != target["title"]:
            raise DashboardTargetError(
                f"{target[field]} title {dashboard.get('title')!r} does not match registry "
                f"{target['title']!r}"
            )


def _validate_optional_service_section(
    target: dict[str, Any],
    section: str,
    unique_fields: dict[str, set[Any]],
) -> None:
    if section not in target:
        return
    _validate_service_section(target[section], f"{target['key']}.{section}")
    _remember_unique(unique_fields["service"], target[section]["service"], "service")
    _remember_unique(unique_fields["host_port"], target[section]["host_port"], "host port")


def _validate_service_section(data: dict[str, Any], label: str) -> None:
    for field in ("service", "host_port_env", "host_port", "container_port", "browser_url"):
        if field not in data:
            raise DashboardTargetError(f"{label} missing {field}")


def _validate_fault_groups(target: dict[str, Any]) -> None:
    groups = target.get("fault_groups")
    if not isinstance(groups, list) or not groups:
        raise DashboardTargetError(f"target {target['key']} must define fault_groups")
    seen_group_keys: set[str] = set()
    for group in groups:
        for field in ("key", "label", "kind", "enabled", "faults"):
            if field not in group:
                raise DashboardTargetError(f"target {target['key']} fault_group missing {field}")
        _remember_unique(seen_group_keys, group["key"], "fault group key")
        if group["kind"] not in {"mock", "proxy", "infra"}:
            raise DashboardTargetError(f"target {target['key']} has unknown fault group kind {group['kind']!r}")
        if group.get("enabled", False):
            _require_mapping(group, "controller")
            for field in ("docker_url", "local_url", "browser_url"):
                if field not in group["controller"]:
                    raise DashboardTargetError(
                        f"target {target['key']} group {group['key']} missing controller.{field}"
                    )
        elif group["kind"] == "infra" and not group.get("disabled_reason"):
            raise DashboardTargetError(f"target {target['key']} disabled infra group needs disabled_reason")
        if not isinstance(group["faults"], list) or not group["faults"]:
            raise DashboardTargetError(f"target {target['key']} group {group['key']} must define faults")
        seen_faults: set[str] = set()
        for fault in group["faults"]:
            for field in ("type", "label", "target"):
                if field not in fault:
                    raise DashboardTargetError(
                        f"target {target['key']} group {group['key']} fault missing {field}"
                    )
            _remember_unique(seen_faults, f"{fault['type']}:{fault['target']}", "fault")


def _validate_live_prometheus(target: dict[str, Any]) -> None:
    if "exporter" not in target:
        raise DashboardTargetError(f"target {target['key']} has live_prometheus but no exporter section")
    _validate_service_section(target["exporter"], f"{target['key']}.exporter")
    if "live_prometheus_config_path" not in target:
        raise DashboardTargetError(f"target {target['key']} missing live_prometheus_config_path")


def _probe_config(probe_defaults: dict[str, Any], target: dict[str, Any], url_field: str) -> dict[str, Any]:
    grafana = probe_defaults.get("grafana", {})
    grafana_is_docker = url_field == "docker_url"
    return {
        "probe_interval_seconds": probe_defaults["probe_interval_seconds"],
        "max_concurrency": probe_defaults["max_concurrency"],
        "thresholds": probe_defaults["thresholds"],
        "grafana": {
            "enabled": (
                grafana.get("enabled_in_docker", True)
                if grafana_is_docker
                else grafana.get("enabled_locally", False)
            ),
            "url": grafana.get("docker_url" if grafana_is_docker else "local_url", "http://localhost:3000"),
            "query_range_seconds": grafana.get("query_range_seconds", 3600),
            "step_seconds": grafana.get("step_seconds", 30),
            "max_data_points": grafana.get("max_data_points", 1200),
        },
        "datasources": [
            {
                "uid": target["datasource"]["uid"],
                "url": target["datasource"][url_field],
                "type": target["datasource"]["type"],
            }
        ],
    }


def _grafana_datasources(registry: dict[str, Any]) -> dict[str, Any]:
    datasources = []
    for target in registry["targets"]:
        ds = target["datasource"]
        datasources.append(
            {
                "name": ds["name"],
                "type": ds["type"],
                "uid": ds["uid"],
                "url": ds["grafana_url"],
                "access": "proxy",
                "isDefault": False,
            }
        )
    probe_ds = registry["probe_metrics_datasource"]
    datasources.append(
        {
            "name": probe_ds["name"],
            "type": probe_ds["type"],
            "uid": probe_ds["uid"],
            "url": probe_ds["url"],
            "access": "proxy",
            "isDefault": True,
        }
    )
    return {"apiVersion": 1, "datasources": datasources}


def _prometheus_config(registry: dict[str, Any]) -> dict[str, Any]:
    scrape_configs = [
        {
            "job_name": target["probe"]["service"],
            "metrics_path": "/metrics",
            "static_configs": [
                {"targets": [f"{target['probe']['service']}:{target['probe']['container_port']}"]}
            ],
        }
        for target in registry["targets"]
    ]
    render_probe = registry["render_probe"]
    scrape_configs.append(
        {
            "job_name": render_probe["service"],
            "metrics_path": "/metrics",
            "static_configs": [
                {"targets": [f"{render_probe['service']}:{render_probe['container_port']}"]}
            ],
        }
    )
    return {
        "global": {"scrape_interval": "15s", "evaluation_interval": "15s"},
        "scrape_configs": scrape_configs,
    }


def _live_prometheus_config(target: dict[str, Any]) -> dict[str, Any]:
    prometheus = target["live_prometheus"]
    exporter = target["exporter"]
    return {
        "global": {
            "scrape_interval": prometheus.get("scrape_interval", "5s"),
            "evaluation_interval": prometheus.get("evaluation_interval", "5s"),
        },
        "scrape_configs": [
            {
                "job_name": exporter["service"],
                "metrics_path": exporter.get("metrics_path", "/metrics"),
                "static_configs": [
                    {"targets": [f"{exporter['service']}:{exporter['container_port']}"]}
                ],
            }
        ],
    }


def _simulator_targets_js(registry: dict[str, Any]) -> str:
    targets: dict[str, Any] = {}
    controller = registry["fault_controller"]
    render_probe = registry["render_probe"]
    for target in registry["targets"]:
        targets[target["key"]] = {
            "label": target["title"],
            "dashboardUid": target["dashboard_uid"],
            "controllerUrl": controller["browser_url"],
            "probeUrl": target["probe"]["browser_url"],
            "renderProbeUrl": render_probe["browser_url"],
            "grafanaSource": target["title"],
            "grafanaSre": f"[SRE] {target['title']}",
            "faultGroups": _simulator_fault_groups(target),
            "surfaces": target["surfaces"],
        }
    return "window.DASHBOARD_TARGETS = " + json.dumps(targets, indent=2) + ";\n"


def _simulator_fault_groups(target: dict[str, Any]) -> list[dict[str, Any]]:
    groups = []
    for group in target["fault_groups"]:
        groups.append(
            {
                "key": group["key"],
                "label": group["label"],
                "kind": group["kind"],
                "enabled": group.get("enabled", False),
                "description": group.get("description", ""),
                "disabledReason": group.get("disabled_reason"),
                "faults": [_simulator_fault(fault) for fault in group.get("faults", [])],
            }
        )
    return groups


def _simulator_fault(fault: dict[str, Any]) -> dict[str, Any]:
    default = FAULT_LAYER_DEFAULTS.get(fault["type"], {})
    return {
        **fault,
        "affected_layers": fault.get("affected_layers", default.get("affected_layers", [])),
        "expected_sre_signals": fault.get(
            "expected_sre_signals",
            default.get("expected_sre_signals", []),
        ),
    }


def _check_compose_grafana_volumes(registry: dict[str, Any], services: dict[str, Any]) -> list[str]:
    grafana = services.get("grafana", {})
    volumes = grafana.get("volumes", [])
    errors = []
    for target in registry["targets"]:
        for field in ("grafana_source_dashboard_path", "sre_dashboard_path"):
            host_path = "./" + target[field]
            if not any(str(volume).startswith(host_path + ":") for volume in volumes):
                errors.append(f"Compose grafana service missing volume for {target[field]}")
    return errors


def _check_compose_service_port(
    service_def: dict[str, Any],
    services: dict[str, Any],
    section: str,
    target_key: str,
) -> list[str]:
    service_name = service_def["service"]
    if service_name not in services:
        return [f"Compose missing {section} service {service_name!r} for target {target_key!r}"]
    expected_port = f"${{{service_def['host_port_env']}:-{service_def['host_port']}}}:{service_def['container_port']}"
    if expected_port not in services[service_name].get("ports", []):
        return [f"Compose {section} service {service_name!r} missing port {expected_port!r}"]
    return []


def _probe_dependency(target: dict[str, Any]) -> str | None:
    if "probe_depends_on" in target["probe"]:
        return target["probe"]["probe_depends_on"]
    if "proxy" in target:
        return target["proxy"]["service"]
    if "mock" in target:
        return target["mock"]["service"]
    return None


def _check_compose_dependency_set(
    registry: dict[str, Any],
    services: dict[str, Any],
    service_name: str,
    target_section: str,
) -> list[str]:
    service = services.get(service_name, {})
    depends_on = service.get("depends_on", {})
    errors = []
    for target in registry["targets"]:
        if target_section not in target:
            continue
        dependency = target[target_section]["service"]
        if dependency not in depends_on:
            errors.append(f"Compose {service_name!r} should depend on {dependency!r}")
    return errors


def _check_compose_datasource_dependencies(
    registry: dict[str, Any],
    services: dict[str, Any],
    service_name: str,
) -> list[str]:
    service = services.get(service_name, {})
    depends_on = service.get("depends_on", {})
    errors = []
    for target in registry["targets"]:
        dependency = _probe_dependency(target)
        if dependency and dependency not in depends_on:
            errors.append(f"Compose {service_name!r} should depend on {dependency!r}")
    return errors


def _check_fault_controller_consistency(registry: dict[str, Any], services: dict[str, Any]) -> list[str]:
    controller = registry["fault_controller"]
    errors = _check_compose_service_port(controller, services, "fault_controller", "global")
    service = services.get(controller["service"], {})
    env = service.get("environment", {})
    if env.get("DASHBOARD_TARGETS_PATH") != "/app/dashboard_targets.yaml":
        errors.append("Compose fault-controller should set DASHBOARD_TARGETS_PATH to '/app/dashboard_targets.yaml'")
    demo_depends = services.get("demo-ui", {}).get("depends_on", {})
    if controller["service"] not in demo_depends:
        errors.append(f"Compose 'demo-ui' should depend on {controller['service']!r}")
    return errors


def _check_render_probe_consistency(registry: dict[str, Any], services: dict[str, Any]) -> list[str]:
    render_probe = registry["render_probe"]
    errors = _check_compose_service_port(render_probe, services, "render_probe", "global")
    service = services.get(render_probe["service"], {})
    env = service.get("environment", {})
    if env.get("DASHBOARD_TARGETS_PATH") != "/app/dashboard_targets.yaml":
        errors.append("Compose browser render probe should set DASHBOARD_TARGETS_PATH to '/app/dashboard_targets.yaml'")
    if env.get("RENDER_PROBE_URL_MODE") != "docker":
        errors.append("Compose browser render probe should set RENDER_PROBE_URL_MODE to 'docker'")
    depends_on = service.get("depends_on", {})
    if "grafana" not in depends_on:
        errors.append("Compose browser render probe should depend on 'grafana'")
    return errors


def _require_mapping(data: dict[str, Any], key: str) -> None:
    if not isinstance(data.get(key), dict):
        raise DashboardTargetError(f"{key} must be a mapping")


def _remember_unique(values: set[Any], value: Any, label: str) -> None:
    if value in values:
        raise DashboardTargetError(f"duplicate {label}: {value!r}")
    values.add(value)


def _load_json(path: str | Path) -> dict[str, Any]:
    repo_path = _repo_path(path)
    if not repo_path.exists():
        raise DashboardTargetError(f"dashboard file does not exist: {_display_path(repo_path)}")
    return json.loads(repo_path.read_text(encoding="utf-8"))


def _repo_path(path: str | Path) -> Path:
    p = Path(path)
    if p.is_absolute():
        return p
    return REPO_ROOT / p


def _json_text(data: Any) -> str:
    return json.dumps(data, indent=2) + "\n"


def _yaml_text(data: Any) -> str:
    return yaml.safe_dump(data, sort_keys=False)


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n")


def _write_text(path: Path, content: str) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write(content)


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
