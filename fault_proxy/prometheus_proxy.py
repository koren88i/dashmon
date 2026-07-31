"""Prometheus-compatible proxy with deterministic fault injection.

The proxy sits between Grafana/probe-engine and a real Prometheus instance.
It forwards Prometheus API traffic unchanged until a fault is injected, then
mutates the Prometheus JSON response in the same way the mock backend does.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any
from urllib.parse import parse_qs, urljoin

import httpx
from fastapi import FastAPI, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from mock_backend.fault_injector import FAULT_INFO, FaultInjector, FaultType
from mock_backend.fixtures.metrics import extract_metric_name

UPSTREAM_PROMETHEUS_URL = os.environ.get("UPSTREAM_PROMETHEUS_URL", "http://prometheus:9090").rstrip("/")
SLOW_QUERY_DELAY_SECONDS = float(os.environ.get("FAULT_PROXY_SLOW_QUERY_SECONDS", "8.0"))
STALE_DATA_AGE_SECONDS = float(os.environ.get("FAULT_PROXY_STALE_DATA_AGE_SECONDS", "600.0"))
CARDINALITY_MULTIPLIER = int(os.environ.get("FAULT_PROXY_CARDINALITY_MULTIPLIER", "10"))

app = FastAPI(title="Faultable Prometheus Proxy")
injector = FaultInjector()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class InjectRequest(BaseModel):
    type: FaultType
    target: str
    duration_seconds: int = 0


class ClearRequest(BaseModel):
    target: str = "all"


@app.get("/-/healthy")
async def healthy():
    return "Faultable Prometheus Proxy is Healthy.\n"


@app.get("/faults/types")
async def fault_types():
    return {ft.value: FAULT_INFO[ft] for ft in FaultType}


@app.get("/faults/active")
async def active_faults():
    return {"faults": injector.get_active()}


@app.post("/faults/inject")
async def inject_fault(req: InjectRequest):
    record = injector.inject(req.type, req.target, req.duration_seconds)
    return {"status": "injected", "fault": record.to_dict()}


@app.post("/faults/clear")
async def clear_faults(req: ClearRequest):
    removed = injector.clear(req.target)
    return {"status": "cleared", "removed": removed}


@app.get("/api/v1/query")
async def instant_query_get(request: Request, query: str = Query(...)):
    return await _prometheus_query("GET", "/api/v1/query", request, query=query)


@app.post("/api/v1/query")
async def instant_query_post(request: Request):
    return await _prometheus_query("POST", "/api/v1/query", request)


@app.get("/api/v1/query_range")
async def range_query_get(request: Request, query: str = Query(...)):
    return await _prometheus_query("GET", "/api/v1/query_range", request, query=query)


@app.post("/api/v1/query_range")
async def range_query_post(request: Request):
    return await _prometheus_query("POST", "/api/v1/query_range", request)


@app.get("/api/v1/label/{label_name}/values")
async def label_values_get(label_name: str, request: Request):
    fault = injector.get_fault_for_label(label_name)
    if fault is not None:
        if fault.fault_type == FaultType.VARIABLE_QUERY_ERROR:
            return _variable_query_error_response()
        return {"status": "success", "data": []}
    return await _forward_json("GET", f"/api/v1/label/{label_name}/values", request)


@app.post("/api/v1/label/{label_name}/values")
async def label_values_post(label_name: str, request: Request):
    fault = injector.get_fault_for_label(label_name)
    if fault is not None:
        if fault.fault_type == FaultType.VARIABLE_QUERY_ERROR:
            return _variable_query_error_response()
        return {"status": "success", "data": []}
    return await _forward_json("POST", f"/api/v1/label/{label_name}/values", request)


@app.get("/api/v1/series")
async def series_get(request: Request):
    fault = injector.get_variable_discovery_fault()
    if fault is not None:
        if fault.fault_type == FaultType.VARIABLE_QUERY_ERROR:
            return _variable_query_error_response()
        return {"status": "success", "data": []}
    return await _forward_json("GET", "/api/v1/series", request)


@app.post("/api/v1/series")
async def series_post(request: Request):
    fault = injector.get_variable_discovery_fault()
    if fault is not None:
        if fault.fault_type == FaultType.VARIABLE_QUERY_ERROR:
            return _variable_query_error_response()
        return {"status": "success", "data": []}
    return await _forward_json("POST", "/api/v1/series", request)


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def passthrough(path: str, request: Request):
    """Forward non-fault Prometheus endpoints without special handling."""
    response = await _forward_response(request.method, f"/{path}", request)
    return Response(
        content=response.content,
        status_code=response.status_code,
        media_type=response.headers.get("content-type"),
    )


async def _prometheus_query(
    method: str,
    path: str,
    request: Request,
    *,
    query: str | None = None,
) -> dict[str, Any] | Response:
    content = await request.body() if method.upper() != "GET" else None
    query = query if query is not None else _extract_query(request, content)
    metric_name = extract_metric_name(query)
    fault = injector.get_fault_for_metric(metric_name) if metric_name else None
    if (
        fault is not None
        and fault.fault_type == FaultType.PANEL_QUERY_HTTP_500
        and method.upper() == "POST"
        and path == "/api/v1/query_range"
    ):
        return Response("Internal Server Error", status_code=500, media_type="text/plain")
    if fault is not None and fault.fault_type == FaultType.SLOW_QUERY:
        await asyncio.sleep(SLOW_QUERY_DELAY_SECONDS)

    body = await _forward_json(method, path, request, content=content)
    if fault is None:
        return body
    return _apply_query_fault(body, fault.fault_type)


async def _forward_json(
    method: str,
    path: str,
    request: Request,
    *,
    content: bytes | None = None,
) -> dict[str, Any]:
    response = await _forward_response(method, path, request, content=content)
    response.raise_for_status()
    return response.json()


async def _forward_response(
    method: str,
    path: str,
    request: Request,
    *,
    content: bytes | None = None,
) -> httpx.Response:
    url = urljoin(UPSTREAM_PROMETHEUS_URL + "/", path.lstrip("/"))
    params = list(request.query_params.multi_items())
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in {"host", "content-length"}
    }
    if content is None:
        content = await request.body()
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        return await client.request(
            method,
            url,
            params=params,
            content=content,
            headers=headers,
        )


def _extract_query(request: Request, content: bytes | None) -> str:
    query = request.query_params.get("query")
    if query is not None:
        return query

    if not content:
        return ""

    content_type = request.headers.get("content-type", "")
    if "application/x-www-form-urlencoded" not in content_type:
        return ""

    parsed = parse_qs(content.decode("utf-8"), keep_blank_values=True)
    return parsed.get("query", [""])[0]


def _apply_query_fault(body: dict[str, Any], fault_type: FaultType) -> dict[str, Any]:
    if fault_type in (FaultType.NO_DATA, FaultType.METRIC_RENAME):
        mutated = dict(body)
        data = dict(mutated.get("data", {}))
        data["result"] = []
        mutated["data"] = data
        return mutated

    if fault_type == FaultType.STALE_DATA:
        return _with_stale_timestamps(body)

    if fault_type == FaultType.CARDINALITY_SPIKE:
        return _with_cardinality_spike(body)

    return body


def _variable_query_error_response() -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "errorType": "execution",
            "error": "simulated variable query failure",
        },
    )


def _with_stale_timestamps(body: dict[str, Any]) -> dict[str, Any]:
    mutated = _deepish_copy(body)
    stale_ts = time.time() - STALE_DATA_AGE_SECONDS
    for item in mutated.get("data", {}).get("result", []):
        if "value" in item and item["value"]:
            item["value"][0] = stale_ts
        if "values" in item and item["values"]:
            first_value = item["values"][0][1]
            item["values"] = [[stale_ts, first_value]]
    return mutated


def _with_cardinality_spike(body: dict[str, Any]) -> dict[str, Any]:
    mutated = _deepish_copy(body)
    result = mutated.get("data", {}).get("result")
    if not isinstance(result, list) or not result:
        return mutated

    extra = []
    now = time.time()
    for i in range(1, CARDINALITY_MULTIPLIER):
        for item in result:
            clone = _deepish_copy(item)
            metric = clone.setdefault("metric", {})
            if isinstance(metric, dict):
                metric["spike_id"] = str(i)
            if "value" in clone and clone["value"]:
                clone["value"][0] = now
            extra.append(clone)
    result.extend(extra)
    return mutated


def _deepish_copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _deepish_copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_deepish_copy(v) for v in value]
    return value
