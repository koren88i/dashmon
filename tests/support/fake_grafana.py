"""Small Grafana /api/ds/query test double.

It forwards Grafana-style query payloads to a Prometheus-compatible upstream
using POST /api/v1/query_range, then wraps the result as Grafana data frames.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import FastAPI, Request, Response

UPSTREAM_PROMETHEUS_URL = os.environ.get("FAKE_GRAFANA_PROMETHEUS_URL", "http://localhost:9090").rstrip("/")

app = FastAPI(title="Fake Grafana")


@app.get("/api/health")
async def health():
    return {"database": "ok"}


@app.post("/api/ds/query")
async def datasource_query(request: Request):
    body = await request.json()
    start = float(body.get("from", 0)) / 1000
    end = float(body.get("to", 0)) / 1000
    results: dict[str, Any] = {}

    async with httpx.AsyncClient(timeout=10.0) as client:
        for query in body.get("queries", []):
            ref_id = query.get("refId", "A")
            step = max(float(query.get("intervalMs", 15000)) / 1000, 1.0)
            response = await client.post(
                f"{UPSTREAM_PROMETHEUS_URL}/api/v1/query_range",
                data={
                    "query": query.get("expr", ""),
                    "start": start,
                    "end": end,
                    "step": step,
                },
            )
            if response.status_code >= 400:
                return Response(
                    response.text,
                    status_code=response.status_code,
                    media_type=response.headers.get("content-type", "text/plain"),
                )
            prometheus_body = response.json()
            results[ref_id] = {
                "status": 200,
                "frames": _frames(prometheus_body),
            }

    return {"results": results}


def _frames(prometheus_body: dict[str, Any]) -> list[dict[str, Any]]:
    frames = []
    for item in prometheus_body.get("data", {}).get("result", []):
        values = item.get("values", [])
        if not values:
            continue
        frames.append(
            {
                "schema": {
                    "fields": [
                        {"name": "Time", "type": "time"},
                        {"name": "Value", "type": "number", "labels": item.get("metric", {})},
                    ]
                },
                "data": {
                    "values": [
                        [int(point[0] * 1000) for point in values],
                        [float(point[1]) for point in values],
                    ]
                },
            }
        )
    return frames
