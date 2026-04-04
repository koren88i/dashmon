"""Mock Prometheus HTTP API with fault injection.

Serves synthetic time series for the example dashboard's 5 metric families.
Responses match the real Prometheus HTTP API shape so the probe engine needs
no special-casing.

Fault injection endpoints let the demo UI degrade responses on demand.
"""

from __future__ import annotations

import asyncio
import time

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from mock_backend.fault_injector import FaultInjector, FaultType
from mock_backend.fixtures.metrics import (
    extract_metric_name,
    find_metric_family,
    generate_value,
    get_instant_query_result,
    get_label_values,
    get_range_query_result,
)

app = FastAPI(title="Mock Prometheus")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Shared fault state (single-process, no persistence needed).
injector = FaultInjector()

# ---------------------------------------------------------------------------
# Fault-injection config
# ---------------------------------------------------------------------------

SLOW_QUERY_DELAY_SECONDS = 8.0
STALE_DATA_AGE_SECONDS = 600.0  # timestamps 10 minutes in the past
CARDINALITY_MULTIPLIER = 10


# ---------------------------------------------------------------------------
# Prometheus-compatible endpoints
# ---------------------------------------------------------------------------

@app.get("/-/healthy")
async def healthy():
    return "Prometheus Server is Healthy.\n"


@app.get("/api/v1/query")
async def instant_query(query: str = Query(...)):
    metric_name = extract_metric_name(query)
    fault = injector.get_fault_for_metric(metric_name) if metric_name else None

    if fault is not None:
        result = await _apply_fault_instant(fault.fault_type, metric_name, query)
    else:
        result = get_instant_query_result(query)

    return {
        "status": "success",
        "data": {"resultType": "vector", "result": result},
    }


@app.get("/api/v1/query_range")
async def range_query(
    query: str = Query(...),
    start: float = Query(...),
    end: float = Query(...),
    step: float = Query(15),
):
    metric_name = extract_metric_name(query)
    fault = injector.get_fault_for_metric(metric_name) if metric_name else None

    if fault is not None:
        result = await _apply_fault_range(fault.fault_type, metric_name, query, start, end, step)
    else:
        result = get_range_query_result(query, start, end, step)

    return {
        "status": "success",
        "data": {"resultType": "matrix", "result": result},
    }


@app.get("/api/v1/label/{label_name}/values")
async def label_values(label_name: str):
    fault = injector.get_fault_for_label(label_name)
    if fault is not None:
        return {"status": "success", "data": []}

    values = get_label_values(label_name)
    return {"status": "success", "data": values}


# ---------------------------------------------------------------------------
# Fault-injection API
# ---------------------------------------------------------------------------

class InjectRequest(BaseModel):
    type: FaultType
    target: str
    duration_seconds: int = 0


class ClearRequest(BaseModel):
    target: str = "all"


@app.post("/faults/inject")
async def inject_fault(req: InjectRequest):
    record = injector.inject(req.type, req.target, req.duration_seconds)
    return {"status": "injected", "fault": record.to_dict()}


@app.post("/faults/clear")
async def clear_faults(req: ClearRequest):
    removed = injector.clear(req.target)
    return {"status": "cleared", "removed": removed}


@app.get("/faults/active")
async def active_faults():
    return {"faults": injector.get_active()}


# ---------------------------------------------------------------------------
# Fault-effect helpers
# ---------------------------------------------------------------------------

async def _apply_fault_instant(
    fault_type: FaultType,
    metric_name: str,
    query: str,
) -> list[dict]:
    """Return a modified instant-vector result based on the active fault."""

    if fault_type in (FaultType.NO_DATA, FaultType.METRIC_RENAME):
        return []

    if fault_type == FaultType.SLOW_QUERY:
        await asyncio.sleep(SLOW_QUERY_DELAY_SECONDS)
        return get_instant_query_result(query)

    if fault_type == FaultType.STALE_DATA:
        result = get_instant_query_result(query)
        stale_ts = time.time() - STALE_DATA_AGE_SECONDS
        for item in result:
            item["value"][0] = stale_ts
        return result

    if fault_type == FaultType.CARDINALITY_SPIKE:
        return _spike_instant(metric_name, query)

    # VAR_RESOLUTION_FAIL only applies to label_values; pass through here.
    return get_instant_query_result(query)


async def _apply_fault_range(
    fault_type: FaultType,
    metric_name: str,
    query: str,
    start: float,
    end: float,
    step: float,
) -> list[dict]:
    """Return a modified range-matrix result based on the active fault."""

    if fault_type in (FaultType.NO_DATA, FaultType.METRIC_RENAME):
        return []

    if fault_type == FaultType.SLOW_QUERY:
        await asyncio.sleep(SLOW_QUERY_DELAY_SECONDS)
        return get_range_query_result(query, start, end, step)

    if fault_type == FaultType.STALE_DATA:
        result = get_range_query_result(query, start, end, step)
        stale_ts = time.time() - STALE_DATA_AGE_SECONDS
        for item in result:
            # Keep only one old data point to simulate frozen data.
            if item["values"]:
                old_val = item["values"][0][1]
                item["values"] = [[stale_ts, old_val]]
        return result

    if fault_type == FaultType.CARDINALITY_SPIKE:
        return _spike_range(metric_name, query, start, end, step)

    return get_range_query_result(query, start, end, step)


def _spike_instant(metric_name: str, query: str) -> list[dict]:
    """Return CARDINALITY_MULTIPLIER × the normal number of series."""
    base = get_instant_query_result(query)
    family = find_metric_family(metric_name)
    if not family or not base:
        return base
    now = time.time()
    extra: list[dict] = []
    for i in range(1, CARDINALITY_MULTIPLIER):
        for item in base:
            clone = {
                "metric": {**item["metric"], "spike_id": str(i)},
                "value": [now, item["value"][1]],
            }
            extra.append(clone)
    return base + extra


def _spike_range(
    metric_name: str,
    query: str,
    start: float,
    end: float,
    step: float,
) -> list[dict]:
    """Range-query variant of cardinality spike."""
    base = get_range_query_result(query, start, end, step)
    if not base:
        return base
    extra: list[dict] = []
    for i in range(1, CARDINALITY_MULTIPLIER):
        for item in base:
            clone = {
                "metric": {**item["metric"], "spike_id": str(i)},
                "values": list(item["values"]),
            }
            extra.append(clone)
    return base + extra
