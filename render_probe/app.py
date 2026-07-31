"""FastAPI service exposing browser render probe health and metrics."""

from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field

from fastapi import FastAPI, Response
from prometheus_client import generate_latest

from generator.dashboard_targets import load_dashboard_targets
from render_probe.config import RenderProbeSettings, settings_from_registry
from render_probe.metrics import REGISTRY, record_result
from render_probe.probe import BrowserRenderProbe, RenderProbeResult


@dataclass
class RenderProbeState:
    settings: RenderProbeSettings = field(default_factory=RenderProbeSettings)
    results: dict[str, RenderProbeResult] = field(default_factory=dict)
    last_cycle_time: float = 0.0
    ready: bool = False
    error: str = ""
    runner: BrowserRenderProbe | None = None


state = RenderProbeState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    registry_path = os.environ.get("DASHBOARD_TARGETS_PATH", "dashboard_targets.yaml")
    registry = load_dashboard_targets(registry_path)
    state.settings = settings_from_registry(registry)
    state.ready = True
    task: asyncio.Task | None = None

    if state.settings.enabled:
        state.runner = BrowserRenderProbe(state.settings)
        task = asyncio.create_task(_probe_loop())

    yield

    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    if state.runner is not None:
        await state.runner.stop()


app = FastAPI(title="Dashboard SRE Browser Render Probe", lifespan=lifespan)


@app.get("/health")
async def health():
    return {
        "enabled": state.settings.enabled,
        "ready": state.ready,
        "error": state.error,
        "last_cycle_time": state.last_cycle_time,
        "target_count": len(state.settings.targets),
        "targets": [
            asdict(result)
            for result in sorted(state.results.values(), key=lambda item: item.target_key)
        ],
    }


@app.get("/metrics")
async def metrics():
    return Response(generate_latest(REGISTRY), media_type="text/plain; version=0.0.4")


async def _probe_loop() -> None:
    while True:
        await _run_cycle()
        await asyncio.sleep(state.settings.interval_seconds)


async def _run_cycle() -> None:
    if state.runner is None:
        return
    semaphore = asyncio.Semaphore(state.settings.max_concurrency)

    async def probe_target(target):
        async with semaphore:
            return await state.runner.probe(target)

    try:
        results = await asyncio.gather(
            *(probe_target(target) for target in state.settings.targets),
            return_exceptions=True,
        )
        now = time.time()
        for target, result in zip(state.settings.targets, results):
            if isinstance(result, Exception):
                result = RenderProbeResult(
                    dashboard_uid=target.dashboard_uid,
                    dashboard_title=target.title,
                    target_key=target.key,
                    url=target.url,
                    status="degraded",
                    duration_seconds=0.0,
                    error_type="render_navigation_error",
                    message=str(result),
                    timestamp=now,
                )
            state.results[target.dashboard_uid] = result
            record_result(result)
        state.last_cycle_time = now
        state.error = ""
    except Exception as exc:
        state.error = str(exc)

