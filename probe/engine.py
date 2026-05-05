"""Probe engine — periodic probe loop with /metrics and /health endpoints.

Loads a Grafana dashboard JSON, parses it, and probes all panels
concurrently on a configurable interval.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import generate_latest

from probe.config import (
    ErrorType,
    PanelProbeSpec,
    ProbeConfig,
    ProbeResult,
    ProbeStatus,
    VariableProbeSpec,
)
from probe.metrics import (
    HEALTH_SCORE,
    ISSUE_COUNT,
    ISSUE_EVENT_TIMESTAMP,
    LAST_PROBE_TIMESTAMP,
    LOAD_TIME,
    PANEL_ERROR_TOTAL,
    PANEL_QUERY_DURATION,
    PANEL_LAST_DATAPOINT_AGE,
    PANEL_SERIES_COUNT,
    PANEL_STATUS,
    REGISTRY,
    VARIABLE_QUERY_DURATION,
    VARIABLE_DEPENDENCY_IMPACT,
    VARIABLE_ERROR_TOTAL,
    VARIABLE_STATUS,
)
from probe.parser import parse_dashboard
from probe.probes.cardinality_probe import CardinalityProbe
from probe.probes.grafana_panel_path_probe import GrafanaPanelPathProbe
from probe.probes.query_probe import QueryProbe
from probe.probes.staleness_probe import StalenessProbe
from probe.probes.variable_probe import VariableProbe

# ---------------------------------------------------------------------------
# Engine state
# ---------------------------------------------------------------------------

@dataclass
class IssueRecord:
    event_id: int
    timestamp: float
    panel_id: int | None
    panel_title: str
    probe_type: str
    error_type: str
    message: str


@dataclass(frozen=True)
class IssueSignature:
    status: ProbeStatus
    probe_type: str
    error_type: str


@dataclass
class EngineState:
    dashboard_uid: str = ""
    dashboard_title: str = ""
    config: ProbeConfig = field(default_factory=ProbeConfig.defaults)
    panel_specs: list[PanelProbeSpec] = field(default_factory=list)
    variable_specs: list[VariableProbeSpec] = field(default_factory=list)
    last_results: list[ProbeResult] = field(default_factory=list)
    last_layer_results: dict[int, list[ProbeResult]] = field(default_factory=dict)
    last_variable_results: list[dict] = field(default_factory=list)
    last_probe_time: float = 0.0
    issues: list[IssueRecord] = field(default_factory=list)
    _previous_panel_signature: dict[int, IssueSignature] = field(default_factory=dict)
    _previous_variable_signature: dict[str, IssueSignature] = field(default_factory=dict)
    _previous_dashboard_signature: IssueSignature | None = None
    _next_issue_id: int = 0
    _issue_metric_labels: set[tuple[str, str, str, str, str, str, str]] = field(default_factory=set)
    _variable_impact_metric_labels: set[tuple[str, str, str, str, str]] = field(default_factory=set)


state = EngineState()

# Probe instances
query_probe = QueryProbe()
grafana_panel_path_probe = GrafanaPanelPathProbe()
staleness_probe = StalenessProbe()
cardinality_probe = CardinalityProbe()
variable_probe = VariableProbe()

# Max issues to keep in the log.
MAX_ISSUES = 50
RECOVERY_MESSAGE = "Recovered - now healthy"
PANEL_STATUS_PROBE_TYPES = (
    "datasource_api",
    "grafana_panel_path",
    "query",
    "no_data",
    "stale_data",
    "metric_rename",
    "query_timeout",
    "slow_query",
    "cardinality_spike",
    "panel_error",
    "variable_dependency",
    "blocked_by_variable",
)

# ---------------------------------------------------------------------------
# Lifespan: load config + start probe loop
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_config()
    task = asyncio.create_task(_probe_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def _load_config() -> None:
    # Config file
    config_path = os.environ.get("CONFIG_PATH", "config.yaml")
    if Path(config_path).exists():
        with open(config_path) as f:
            state.config = ProbeConfig.from_dict(yaml.safe_load(f))

    # Dashboard JSON
    dash_path = os.environ.get("DASHBOARD_PATH", "demo/example_dashboard.json")
    with open(dash_path) as f:
        dashboard = json.load(f)

    state.dashboard_uid = dashboard.get("uid", "unknown")
    state.dashboard_title = dashboard.get("title", "Unknown Dashboard")
    state.panel_specs, state.variable_specs = parse_dashboard(dashboard)


# ---------------------------------------------------------------------------
# Probe loop
# ---------------------------------------------------------------------------

async def _probe_loop() -> None:
    # Run immediately on startup, then every interval.
    while True:
        await _run_probes()
        await asyncio.sleep(state.config.probe_interval_seconds)


async def _run_probes() -> None:
    """Execute all probes concurrently (bounded by max_concurrency) and update metrics."""
    uid = state.dashboard_uid

    # One semaphore per cycle caps total concurrent Prometheus requests.
    sem = asyncio.Semaphore(state.config.max_concurrency)

    async def _bounded(coro):
        async with sem:
            return await coro

    # Probe all panels concurrently.
    panel_tasks = []
    panel_task_specs: list[PanelProbeSpec] = []
    for spec in state.panel_specs:
        ds_url = state.config.url_for_datasource(spec.datasource_uid)
        if ds_url is None:
            continue
        panel_task_specs.append(spec)
        panel_tasks.append(_bounded(_probe_panel(spec, ds_url)))

    # Probe all variables concurrently.
    var_tasks = []
    for vspec in state.variable_specs:
        ds_url = state.config.url_for_datasource(vspec.datasource_uid)
        if ds_url is None:
            continue
        var_tasks.append(_bounded(_probe_variable(vspec, ds_url)))

    results = await asyncio.gather(*panel_tasks, return_exceptions=True)
    var_results = await asyncio.gather(*var_tasks, return_exceptions=True)

    # Process variable results.
    processed_vars: list[dict] = []
    for vr in var_results:
        if isinstance(vr, dict):
            processed_vars.append(vr)
            is_healthy = vr.get("status") == ProbeStatus.HEALTHY.value
            var_status = 1.0 if is_healthy else 0.0
            VARIABLE_STATUS.labels(uid, vr["name"]).set(var_status)
            VARIABLE_QUERY_DURATION.labels(uid, vr["name"]).observe(vr.get("duration", 0))

            current = ProbeStatus.HEALTHY if is_healthy else ProbeStatus.DEGRADED
            enum_error = _variable_error_type(vr)
            current_signature = _variable_issue_signature(current, enum_error)
            prev_signature = state._previous_variable_signature.get(vr["name"])
            emitted = _record_issue_transition(
                prev_signature,
                current_signature,
                None,
                f'${vr["name"]}',
                _variable_issue_message(vr),
            )
            if emitted and current == ProbeStatus.DEGRADED:
                VARIABLE_ERROR_TOTAL.labels(uid, vr["name"], enum_error.value).inc()
            state._previous_variable_signature[vr["name"]] = current_signature

    variable_failures = _variable_failures(processed_vars)

    # Process panel results after variables so dependency impact can be attached
    # without changing the raw datasource/Grafana probe results.
    probe_results: list[ProbeResult] = []
    layer_results: dict[int, list[ProbeResult]] = {}
    variable_impact_labels: set[tuple[str, str, str, str, str]] = set()
    max_duration = 0.0

    for spec, r in zip(panel_task_specs, results):
        if isinstance(r, Exception):
            continue
        summary, panel_layers = r
        dependency_result = _variable_dependency_result(spec, variable_failures, summary)
        if dependency_result is not None:
            panel_layers.append(dependency_result)
            if summary.status == ProbeStatus.HEALTHY or _probe_priority(dependency_result) < _probe_priority(summary):
                summary = dependency_result
            variable_impact_labels.update(_variable_impact_labels(uid, spec, variable_failures))

        probe_results.append(summary)
        layer_results[summary.panel_id] = panel_layers
        pid = str(summary.panel_id)

        # Update Prometheus metrics.
        for candidate in PANEL_STATUS_PROBE_TYPES:
            PANEL_STATUS.labels(uid, pid, summary.panel_title, candidate).set(1.0)
        for layer in panel_layers:
            if layer.status != ProbeStatus.UNKNOWN:
                PANEL_STATUS.labels(uid, pid, summary.panel_title, layer.probe_type).set(
                    1.0 if layer.status == ProbeStatus.HEALTHY else 0.0
                )
            if layer.status == ProbeStatus.DEGRADED and layer.error_type is not None:
                PANEL_STATUS.labels(uid, pid, summary.panel_title, layer.error_type.value).set(0.0)
        PANEL_QUERY_DURATION.labels(uid, pid, summary.panel_title).observe(summary.duration_seconds)
        PANEL_SERIES_COUNT.labels(uid, pid, summary.panel_title).set(summary.series_count)

        if summary.max_timestamp is not None:
            age = time.time() - summary.max_timestamp
            PANEL_LAST_DATAPOINT_AGE.labels(uid, pid, summary.panel_title).set(age)

        max_duration = max(max_duration, summary.duration_seconds)
        # Detect diagnosis transitions for issue log.
        current_signature = _panel_issue_signature(summary)
        prev_signature = state._previous_panel_signature.get(summary.panel_id)
        emitted = _record_issue_transition(
            prev_signature,
            current_signature,
            summary.panel_id,
            summary.panel_title,
            summary.message,
        )
        if emitted and current_signature.status == ProbeStatus.DEGRADED and summary.error_type is not None:
            PANEL_ERROR_TOTAL.labels(uid, pid, summary.panel_title, summary.error_type.value).inc()
        state._previous_panel_signature[summary.panel_id] = current_signature

    _sync_variable_dependency_impact_metrics(variable_impact_labels)

    # Dashboard-level metrics.
    summary = _health_summary(probe_results, processed_vars)
    HEALTH_SCORE.labels(uid).set(summary["health_score"])
    ISSUE_COUNT.labels(uid).set(summary["issue_count"])
    LOAD_TIME.labels(uid).set(max_duration)
    LAST_PROBE_TIMESTAMP.labels(uid).set(time.time())

    # Check slow dashboard.
    dashboard_signature = _dashboard_issue_signature(max_duration)
    dashboard_message = (
        f"Dashboard load time {max_duration:.1f}s exceeds {state.config.slow_dashboard_seconds}s"
    )
    _record_issue_transition(
        state._previous_dashboard_signature,
        dashboard_signature,
        None,
        state.dashboard_title,
        dashboard_message,
    )
    state._previous_dashboard_signature = dashboard_signature

    state.last_results = probe_results
    state.last_layer_results = layer_results
    state.last_variable_results = processed_vars
    state.last_probe_time = time.time()


async def _probe_panel(spec: PanelProbeSpec, ds_url: str) -> tuple[ProbeResult, list[ProbeResult]]:
    """Run panel probes and return (summary, layer/diagnostic results)."""
    try:
        tasks = [
            query_probe.probe(spec, ds_url, state.config),
            staleness_probe.probe(spec, ds_url, state.config),
            cardinality_probe.probe(spec, ds_url, state.config),
        ]
        if state.config.grafana.enabled:
            tasks.append(grafana_panel_path_probe.probe(spec, ds_url, state.config))

        gathered = await asyncio.gather(*tasks, return_exceptions=True)
        panel_results = [
            r for r in gathered
            if not isinstance(r, Exception)
        ]
        usable = [r for r in panel_results if r.status != ProbeStatus.UNKNOWN]
        if usable:
            degraded = [r for r in usable if r.status == ProbeStatus.DEGRADED]
            if degraded:
                summary = min(degraded, key=_probe_priority)
            else:
                summary = next((r for r in usable if r.probe_type == "datasource_api"), usable[0])
            return summary, panel_results

        summary = gathered[0] if gathered and not isinstance(gathered[0], Exception) else ProbeResult(
            panel_id=spec.panel_id,
            panel_title=spec.panel_title,
            status=ProbeStatus.DEGRADED,
            probe_type="datasource_api",
            error_type=ErrorType.PANEL_ERROR,
            message="All probes failed",
        )
        return summary, panel_results or [summary]
    except Exception as exc:
        summary = ProbeResult(
            panel_id=spec.panel_id,
            panel_title=spec.panel_title,
            status=ProbeStatus.DEGRADED,
            probe_type="datasource_api",
            error_type=ErrorType.PANEL_ERROR,
            message=str(exc),
        )
        return summary, [summary]


async def _probe_variable(vspec: VariableProbeSpec, ds_url: str) -> dict:
    """Probe a template variable using the dedicated VariableProbe."""
    try:
        result = await variable_probe.probe(vspec, ds_url, state.config)
        return result.to_dict()
    except Exception as exc:
        return {"name": vspec.name, "status": "degraded",
                "error": str(exc), "duration": 0, "values_count": 0}


def _variable_failures(variable_results: list[dict]) -> dict[str, dict]:
    return {
        vr["name"]: vr
        for vr in variable_results
        if vr.get("status") == ProbeStatus.DEGRADED.value
    }


def _variable_dependency_result(
    spec: PanelProbeSpec,
    variable_failures: dict[str, dict],
    base_result: ProbeResult,
) -> ProbeResult | None:
    failed_dependencies = [
        name for name in spec.variable_dependencies
        if name in variable_failures
    ]
    if not failed_dependencies:
        return None

    details = ", ".join(
        f"${name}={_variable_error_type(variable_failures[name]).value}"
        for name in failed_dependencies
    )
    return ProbeResult(
        panel_id=spec.panel_id,
        panel_title=spec.panel_title,
        status=ProbeStatus.DEGRADED,
        probe_type="variable_dependency",
        error_type=ErrorType.BLOCKED_BY_VARIABLE,
        message=f"Panel depends on failed variable(s): {details}",
        duration_seconds=base_result.duration_seconds,
        series_count=base_result.series_count,
        max_timestamp=base_result.max_timestamp,
    )


def _variable_impact_labels(
    dashboard_uid: str,
    spec: PanelProbeSpec,
    variable_failures: dict[str, dict],
) -> set[tuple[str, str, str, str, str]]:
    labels = set()
    for name in spec.variable_dependencies:
        failure = variable_failures.get(name)
        if failure is None:
            continue
        labels.add((
            dashboard_uid,
            name,
            str(spec.panel_id),
            spec.panel_title,
            _variable_error_type(failure).value,
        ))
    return labels


def _healthy_issue_signature() -> IssueSignature:
    return IssueSignature(ProbeStatus.HEALTHY, "recovery", "recovered")


def _panel_issue_signature(result: ProbeResult) -> IssueSignature:
    if result.status == ProbeStatus.DEGRADED:
        return IssueSignature(
            ProbeStatus.DEGRADED,
            result.probe_type,
            _error_type_value(result.error_type),
        )
    return _healthy_issue_signature()


def _variable_issue_signature(status: ProbeStatus, error_type: ErrorType) -> IssueSignature:
    if status == ProbeStatus.DEGRADED:
        return IssueSignature(ProbeStatus.DEGRADED, "variable_resolution", error_type.value)
    return _healthy_issue_signature()


def _dashboard_issue_signature(max_duration: float) -> IssueSignature:
    if max_duration > state.config.slow_dashboard_seconds:
        return IssueSignature(ProbeStatus.DEGRADED, "dashboard", ErrorType.SLOW_DASHBOARD.value)
    return _healthy_issue_signature()


def _variable_error_type(vr: dict) -> ErrorType:
    error_type = vr.get("error")
    return (
        ErrorType(error_type)
        if error_type in ErrorType._value2member_map_
        else ErrorType.VAR_RESOLUTION_FAIL
    )


def _error_type_value(error_type: ErrorType | None) -> str:
    return error_type.value if error_type else "unknown"


def _should_emit_issue(
    previous: IssueSignature | None,
    current: IssueSignature,
) -> bool:
    if previous == current:
        return False
    if current.status == ProbeStatus.DEGRADED:
        return True
    return previous is not None and previous.status == ProbeStatus.DEGRADED


def _record_issue_transition(
    previous: IssueSignature | None,
    current: IssueSignature,
    panel_id: int | None,
    panel_title: str,
    message: str,
) -> bool:
    if not _should_emit_issue(previous, current):
        return False
    if current.status == ProbeStatus.HEALTHY:
        _add_issue(panel_id, panel_title, current.probe_type, None, RECOVERY_MESSAGE)
    else:
        _add_issue(panel_id, panel_title, current.probe_type, current.error_type, message)
    return True


def _add_issue(
    panel_id: int | None,
    panel_title: str,
    probe_type: str,
    error_type: ErrorType | str | None,
    message: str,
) -> None:
    state._next_issue_id += 1
    state.issues.append(IssueRecord(
        event_id=state._next_issue_id,
        timestamp=time.time(),
        panel_id=panel_id,
        panel_title=panel_title,
        probe_type=probe_type,
        error_type=_error_type_value(error_type) if isinstance(error_type, ErrorType) else (error_type or "recovered"),
        message=message,
    ))
    # Trim old issues.
    if len(state.issues) > MAX_ISSUES:
        state.issues = state.issues[-MAX_ISSUES:]
    _sync_issue_event_metrics()


def _sync_issue_event_metrics() -> None:
    current_labels: set[tuple[str, str, str, str, str, str, str]] = set()
    for issue in state.issues:
        labels = (
            state.dashboard_uid,
            str(issue.event_id),
            "" if issue.panel_id is None else str(issue.panel_id),
            issue.panel_title,
            issue.probe_type,
            issue.error_type,
            issue.message,
        )
        ISSUE_EVENT_TIMESTAMP.labels(*labels).set(issue.timestamp)
        current_labels.add(labels)

    for labels in state._issue_metric_labels - current_labels:
        ISSUE_EVENT_TIMESTAMP.remove(*labels)

    state._issue_metric_labels = current_labels


def _sync_variable_dependency_impact_metrics(
    current_labels: set[tuple[str, str, str, str, str]],
) -> None:
    for labels in current_labels:
        VARIABLE_DEPENDENCY_IMPACT.labels(*labels).set(1.0)

    for labels in state._variable_impact_metric_labels - current_labels:
        VARIABLE_DEPENDENCY_IMPACT.remove(*labels)

    state._variable_impact_metric_labels = current_labels


def _probe_priority(result: ProbeResult) -> int:
    if result.error_type in (ErrorType.QUERY_TIMEOUT, ErrorType.PANEL_ERROR):
        return 0
    if result.error_type == ErrorType.BLOCKED_BY_VARIABLE:
        return 1
    if result.error_type == ErrorType.STALE_DATA:
        return 2
    if result.error_type == ErrorType.SLOW_QUERY:
        return 3
    if result.error_type == ErrorType.CARDINALITY_SPIKE:
        return 4
    if result.error_type == ErrorType.NO_DATA:
        return 5
    if result.error_type == ErrorType.METRIC_RENAME:
        return 6
    return 99


def _variable_issue_message(vr: dict) -> str:
    if vr.get("error") == ErrorType.VAR_RESOLUTION_FAIL.value:
        return f'Variable ${vr["name"]} returned empty values'
    return vr.get("message") or vr.get("error") or f'Variable ${vr["name"]} degraded'


def _health_summary(panel_results: list[ProbeResult], variable_results: list[dict]) -> dict[str, int | float]:
    healthy_panels = sum(1 for r in panel_results if r.status == ProbeStatus.HEALTHY)
    healthy_variables = sum(
        1 for vr in variable_results
        if vr.get("status") == ProbeStatus.HEALTHY.value
    )
    total_panels = len(panel_results)
    total_variables = len(variable_results)
    total_checks = total_panels + total_variables
    healthy_checks = healthy_panels + healthy_variables
    issue_count = total_checks - healthy_checks
    return {
        "healthy_panels": healthy_panels,
        "healthy_variables": healthy_variables,
        "total_panels": total_panels,
        "total_variables": total_variables,
        "health_score": (healthy_checks / total_checks) if total_checks > 0 else 1.0,
        "issue_count": issue_count,
    }


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="Dashboard SRE Probe Engine", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/metrics")
async def metrics():
    return Response(
        content=generate_latest(REGISTRY),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@app.get("/health")
async def health():
    uid = state.dashboard_uid
    summary = _health_summary(state.last_results, state.last_variable_results)
    specs_by_id = {spec.panel_id: spec for spec in state.panel_specs}

    panels = []
    for r in state.last_results:
        spec = specs_by_id.get(r.panel_id)
        panels.append({
            "panel_id": r.panel_id,
            "panel_title": r.panel_title,
            "status": r.status.value,
            "probe_type": r.probe_type,
            "error_type": r.error_type.value if r.error_type else None,
            "message": r.message,
            "duration_seconds": round(r.duration_seconds, 3),
            "series_count": r.series_count,
            "variable_dependencies": spec.variable_dependencies if spec else [],
            "layers": [
                {
                    "probe_type": layer.probe_type,
                    "status": layer.status.value,
                    "error_type": layer.error_type.value if layer.error_type else None,
                    "message": layer.message,
                    "duration_seconds": round(layer.duration_seconds, 3),
                    "series_count": layer.series_count,
                }
                for layer in state.last_layer_results.get(r.panel_id, [])
            ],
        })

    variables = []
    for vr in state.last_variable_results:
        variables.append({
            "name": vr["name"],
            "status": vr.get("status", "unknown"),
            "error": vr.get("error"),
            "message": vr.get("message", ""),
            "duration_seconds": round(vr.get("duration", 0), 3),
            "values_count": vr.get("values_count", 0),
        })

    issues = []
    for issue in reversed(state.issues[-20:]):
        issues.append({
            "event_id": issue.event_id,
            "timestamp": issue.timestamp,
            "panel_id": issue.panel_id,
            "panel_title": issue.panel_title,
            "probe_type": issue.probe_type,
            "error_type": issue.error_type,
            "message": issue.message,
        })

    return {
        "dashboard_uid": uid,
        "dashboard_title": state.dashboard_title,
        "health_score": round(summary["health_score"], 4),
        "issue_count": summary["issue_count"],
        "total_panels": summary["total_panels"],
        "healthy_panels": summary["healthy_panels"],
        "total_variables": summary["total_variables"],
        "healthy_variables": summary["healthy_variables"],
        "load_time_seconds": round(max((r.duration_seconds for r in state.last_results), default=0), 3),
        "last_probe_time": state.last_probe_time,
        "panels": panels,
        "variables": variables,
        "issues": issues,
    }
