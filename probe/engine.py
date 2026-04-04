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
    LAST_PROBE_TIMESTAMP,
    LOAD_TIME,
    PANEL_ERROR_TOTAL,
    PANEL_QUERY_DURATION,
    PANEL_LAST_DATAPOINT_AGE,
    PANEL_SERIES_COUNT,
    PANEL_STATUS,
    REGISTRY,
    VARIABLE_QUERY_DURATION,
    VARIABLE_STATUS,
)
from probe.parser import parse_dashboard
from probe.probes.cardinality_probe import CardinalityProbe
from probe.probes.query_probe import QueryProbe
from probe.probes.staleness_probe import StalenessProbe
from probe.probes.variable_probe import VariableProbe

# ---------------------------------------------------------------------------
# Engine state
# ---------------------------------------------------------------------------

@dataclass
class IssueRecord:
    timestamp: float
    panel_id: int | None
    panel_title: str
    error_type: str
    message: str


@dataclass
class EngineState:
    dashboard_uid: str = ""
    dashboard_title: str = ""
    config: ProbeConfig = field(default_factory=ProbeConfig.defaults)
    panel_specs: list[PanelProbeSpec] = field(default_factory=list)
    variable_specs: list[VariableProbeSpec] = field(default_factory=list)
    last_results: list[ProbeResult] = field(default_factory=list)
    last_variable_results: list[dict] = field(default_factory=list)
    last_probe_time: float = 0.0
    issues: list[IssueRecord] = field(default_factory=list)
    _previous_status: dict[int, ProbeStatus] = field(default_factory=dict)
    _seen_probe_types: dict[int, set[str]] = field(default_factory=dict)


state = EngineState()

# Probe instances
query_probe = QueryProbe()
staleness_probe = StalenessProbe()
cardinality_probe = CardinalityProbe()
variable_probe = VariableProbe()

# Max issues to keep in the log.
MAX_ISSUES = 50

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
    """Execute all probes concurrently and update metrics."""
    uid = state.dashboard_uid

    # Probe all panels concurrently.
    panel_tasks = []
    for spec in state.panel_specs:
        ds_url = state.config.url_for_datasource(spec.datasource_uid)
        if ds_url is None:
            continue
        panel_tasks.append(_probe_panel(spec, ds_url))

    # Probe all variables concurrently.
    var_tasks = []
    for vspec in state.variable_specs:
        ds_url = state.config.url_for_datasource(vspec.datasource_uid)
        if ds_url is None:
            continue
        var_tasks.append(_probe_variable(vspec, ds_url))

    results = await asyncio.gather(*panel_tasks, return_exceptions=True)
    var_results = await asyncio.gather(*var_tasks, return_exceptions=True)

    # Process panel results.
    probe_results: list[ProbeResult] = []
    max_duration = 0.0
    healthy_count = 0

    for r in results:
        if isinstance(r, Exception):
            continue
        probe_results.append(r)
        pid = str(r.panel_id)

        # Update Prometheus metrics.
        status_val = 1.0 if r.status == ProbeStatus.HEALTHY else 0.0
        probe_type = r.error_type.value if r.error_type else "query"
        PANEL_STATUS.labels(uid, pid, r.panel_title, probe_type).set(status_val)

        # Track probe_type labels we've emitted for this panel.
        seen = state._seen_probe_types.setdefault(r.panel_id, set())
        seen.add(probe_type)

        # On recovery, reset all previously-seen degraded probe_type series
        # back to 1.0 so Prometheus doesn't retain stale zeros.
        if r.status == ProbeStatus.HEALTHY:
            for old_type in seen:
                if old_type != probe_type:
                    PANEL_STATUS.labels(uid, pid, r.panel_title, old_type).set(1.0)
        PANEL_QUERY_DURATION.labels(uid, pid, r.panel_title).observe(r.duration_seconds)
        PANEL_SERIES_COUNT.labels(uid, pid, r.panel_title).set(r.series_count)

        if r.max_timestamp is not None:
            age = time.time() - r.max_timestamp
            PANEL_LAST_DATAPOINT_AGE.labels(uid, pid, r.panel_title).set(age)

        if r.error_type is not None:
            PANEL_ERROR_TOTAL.labels(uid, pid, r.panel_title, r.error_type.value).inc()

        max_duration = max(max_duration, r.duration_seconds)
        if r.status == ProbeStatus.HEALTHY:
            healthy_count += 1

        # Detect state transitions for issue log.
        prev = state._previous_status.get(r.panel_id)
        if r.status == ProbeStatus.DEGRADED and prev != ProbeStatus.DEGRADED:
            _add_issue(r.panel_id, r.panel_title, r.error_type, r.message)
        elif r.status == ProbeStatus.HEALTHY and prev == ProbeStatus.DEGRADED:
            _add_issue(r.panel_id, r.panel_title, None, "Recovered — now healthy")
        state._previous_status[r.panel_id] = r.status

    # Process variable results.
    processed_vars: list[dict] = []
    for vr in var_results:
        if isinstance(vr, dict):
            processed_vars.append(vr)
            var_status = 1.0 if vr.get("status") == "healthy" else 0.0
            VARIABLE_STATUS.labels(uid, vr["name"]).set(var_status)
            VARIABLE_QUERY_DURATION.labels(uid, vr["name"]).observe(vr.get("duration", 0))

    # Dashboard-level metrics.
    total = len(probe_results)
    score = healthy_count / total if total > 0 else 1.0
    HEALTH_SCORE.labels(uid).set(score)
    LOAD_TIME.labels(uid).set(max_duration)
    LAST_PROBE_TIMESTAMP.labels(uid).set(time.time())

    # Check slow dashboard.
    if max_duration > state.config.slow_dashboard_seconds:
        _add_issue(None, state.dashboard_title, ErrorType.SLOW_DASHBOARD,
                   f"Dashboard load time {max_duration:.1f}s exceeds {state.config.slow_dashboard_seconds}s")

    state.last_results = probe_results
    state.last_variable_results = processed_vars
    state.last_probe_time = time.time()


async def _probe_panel(spec: PanelProbeSpec, ds_url: str) -> ProbeResult:
    """Run query, staleness, and cardinality probes; return worst result."""
    try:
        results = await asyncio.gather(
            query_probe.probe(spec, ds_url, state.config),
            staleness_probe.probe(spec, ds_url, state.config),
            cardinality_probe.probe(spec, ds_url, state.config),
            return_exceptions=True,
        )
        # Pick the worst non-exception result (degraded > unknown > healthy).
        worst: ProbeResult | None = None
        for r in results:
            if isinstance(r, Exception):
                continue
            if r.status == ProbeStatus.UNKNOWN:
                continue
            if worst is None or r.status == ProbeStatus.DEGRADED:
                worst = r
                if r.status == ProbeStatus.DEGRADED:
                    break  # degraded is the worst; stop early.
        if worst is not None:
            return worst
        # Fallback: return query_probe result or error.
        return results[0] if not isinstance(results[0], Exception) else ProbeResult(
            panel_id=spec.panel_id,
            panel_title=spec.panel_title,
            status=ProbeStatus.DEGRADED,
            error_type=ErrorType.PANEL_ERROR,
            message="All probes failed",
        )
    except Exception as exc:
        return ProbeResult(
            panel_id=spec.panel_id,
            panel_title=spec.panel_title,
            status=ProbeStatus.DEGRADED,
            error_type=ErrorType.PANEL_ERROR,
            message=str(exc),
        )


async def _probe_variable(vspec: VariableProbeSpec, ds_url: str) -> dict:
    """Probe a template variable using the dedicated VariableProbe."""
    try:
        result = await variable_probe.probe(vspec, ds_url, state.config)
        if result.status == ProbeStatus.DEGRADED:
            _add_issue(None, f"${vspec.name}", result.error_type, result.message)
        return result.to_dict()
    except Exception as exc:
        return {"name": vspec.name, "status": "degraded",
                "error": str(exc), "duration": 0, "values_count": 0}


def _add_issue(
    panel_id: int | None,
    panel_title: str,
    error_type: ErrorType | None,
    message: str,
) -> None:
    state.issues.append(IssueRecord(
        timestamp=time.time(),
        panel_id=panel_id,
        panel_title=panel_title,
        error_type=error_type.value if error_type else "recovered",
        message=message,
    ))
    # Trim old issues.
    if len(state.issues) > MAX_ISSUES:
        state.issues = state.issues[-MAX_ISSUES:]


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
    total = len(state.last_results)
    healthy = sum(1 for r in state.last_results if r.status == ProbeStatus.HEALTHY)
    score = healthy / total if total > 0 else 1.0

    panels = []
    for r in state.last_results:
        panels.append({
            "panel_id": r.panel_id,
            "panel_title": r.panel_title,
            "status": r.status.value,
            "error_type": r.error_type.value if r.error_type else None,
            "message": r.message,
            "duration_seconds": round(r.duration_seconds, 3),
            "series_count": r.series_count,
        })

    variables = []
    for vr in state.last_variable_results:
        variables.append({
            "name": vr["name"],
            "status": vr.get("status", "unknown"),
            "error": vr.get("error"),
            "duration_seconds": round(vr.get("duration", 0), 3),
            "values_count": vr.get("values_count", 0),
        })

    issues = []
    for issue in reversed(state.issues[-20:]):
        issues.append({
            "timestamp": issue.timestamp,
            "panel_id": issue.panel_id,
            "panel_title": issue.panel_title,
            "error_type": issue.error_type,
            "message": issue.message,
        })

    return {
        "dashboard_uid": uid,
        "dashboard_title": state.dashboard_title,
        "health_score": round(score, 4),
        "total_panels": total,
        "healthy_panels": healthy,
        "load_time_seconds": round(max((r.duration_seconds for r in state.last_results), default=0), 3),
        "last_probe_time": state.last_probe_time,
        "panels": panels,
        "variables": variables,
        "issues": issues,
    }
