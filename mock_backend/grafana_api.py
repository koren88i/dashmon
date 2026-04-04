"""Grafana API stub — placeholder for future datasource proxy support.

Currently unused. The probe engine talks directly to Prometheus.
This module exists so the project structure matches the brief.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="Mock Grafana API (stub)")


@app.get("/api/health")
async def health():
    return {"commit": "stub", "database": "ok", "version": "10.0.0"}
