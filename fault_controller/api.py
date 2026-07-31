"""Browser-facing fault controller.

The simulator calls this API instead of talking directly to mocks, proxies, or
Docker. In this MVP, mock/proxy groups are delegated to their service APIs and
infra groups are explicitly modeled as disabled.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from generator.dashboard_targets import DEFAULT_REGISTRY_PATH, load_dashboard_targets
from mock_backend.fault_injector import FAULT_INFO, FaultType

REGISTRY_PATH = Path(os.environ.get("DASHBOARD_TARGETS_PATH", DEFAULT_REGISTRY_PATH))
URL_MODE = os.environ.get("FAULT_CONTROLLER_URL_MODE", "docker")

app = FastAPI(title="Dashboard Fault Controller")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class FaultAction(BaseModel):
    target_key: str
    group_key: str | None = None
    type: str | None = None
    target: str = "all"
    duration_seconds: int = 0


@app.get("/-/healthy")
async def healthy():
    return "Dashboard Fault Controller is Healthy.\n"


@app.get("/targets")
async def targets():
    registry = _registry()
    return {
        "targets": [
            {
                "key": target["key"],
                "label": target["title"],
                "dashboard_uid": target["dashboard_uid"],
                "fault_groups": _public_groups(target),
            }
            for target in registry["targets"]
        ]
    }


@app.get("/faults/types")
async def fault_types():
    return {
        ft.value: FAULT_INFO[ft]
        for ft in FaultType
    }


@app.get("/faults/active")
async def active_faults(target_key: str = Query(...)):
    target = _target(target_key)
    faults: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for group in target.get("fault_groups", []):
        if not group.get("enabled", False):
            continue
        endpoint = _delegate_url(group)
        if not endpoint:
            continue
        try:
            body = await _request_json("GET", f"{endpoint}/faults/active")
        except httpx.HTTPError as exc:
            errors.append({"group_key": group["key"], "error": str(exc)})
            continue
        for fault in body.get("faults", []):
            faults.append({
                **fault,
                "target_key": target["key"],
                "group_key": group["key"],
                "kind": group["kind"],
            })
    return {"faults": faults, "errors": errors}


@app.post("/faults/inject")
async def inject_fault(action: FaultAction):
    target = _target(action.target_key)
    group = _group(target, action.group_key)
    _ensure_enabled(group)
    _ensure_fault_allowed(group, action.type, action.target)
    endpoint = _require_delegate_url(group)
    body = await _request_json(
        "POST",
        f"{endpoint}/faults/inject",
        json={
            "type": action.type,
            "target": action.target,
            "duration_seconds": action.duration_seconds,
        },
    )
    return {
        "status": "delegated",
        "target_key": target["key"],
        "group_key": group["key"],
        "kind": group["kind"],
        "delegate": body,
    }


@app.post("/faults/clear")
async def clear_faults(action: FaultAction):
    target = _target(action.target_key)
    groups = [_group(target, action.group_key)] if action.group_key else [
        group for group in target.get("fault_groups", []) if group.get("enabled", False)
    ]
    results = []
    for group in groups:
        _ensure_enabled(group)
        endpoint = _require_delegate_url(group)
        body = await _request_json(
            "POST",
            f"{endpoint}/faults/clear",
            json={"target": action.target},
        )
        results.append({
            "group_key": group["key"],
            "kind": group["kind"],
            "delegate": body,
        })
    return {
        "status": "cleared",
        "target_key": target["key"],
        "results": results,
    }


def _registry() -> dict[str, Any]:
    return load_dashboard_targets(REGISTRY_PATH)


def _target(target_key: str) -> dict[str, Any]:
    for target in _registry()["targets"]:
        if target["key"] == target_key:
            return target
    raise HTTPException(status_code=404, detail=f"unknown target_key: {target_key}")


def _group(target: dict[str, Any], group_key: str | None) -> dict[str, Any]:
    if not group_key:
        raise HTTPException(status_code=400, detail="group_key is required")
    for group in target.get("fault_groups", []):
        if group["key"] == group_key:
            return group
    raise HTTPException(status_code=404, detail=f"unknown group_key: {group_key}")


def _ensure_enabled(group: dict[str, Any]) -> None:
    if group.get("enabled", False):
        return
    detail = {
        "status": "disabled",
        "group_key": group["key"],
        "kind": group.get("kind"),
        "reason": group.get("disabled_reason", "Fault group is disabled"),
    }
    raise HTTPException(status_code=409, detail=detail)


def _ensure_fault_allowed(group: dict[str, Any], fault_type: str | None, target: str) -> None:
    if not fault_type:
        raise HTTPException(status_code=400, detail="type is required")
    for fault in group.get("faults", []):
        if fault["type"] == fault_type and fault["target"] == target:
            return
    raise HTTPException(
        status_code=400,
        detail=f"fault {fault_type}:{target} is not declared for group {group['key']}",
    )


def _delegate_url(group: dict[str, Any]) -> str | None:
    controller = group.get("controller", {})
    url = controller.get(f"{URL_MODE}_url") or controller.get("docker_url") or controller.get("local_url")
    return url.rstrip("/") if isinstance(url, str) and url else None


def _require_delegate_url(group: dict[str, Any]) -> str:
    endpoint = _delegate_url(group)
    if endpoint:
        return endpoint
    raise HTTPException(status_code=400, detail=f"group {group['key']} has no delegate endpoint")


async def _request_json(method: str, url: str, **kwargs: Any) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
        response = await client.request(method, url, **kwargs)
        response.raise_for_status()
        return response.json()


def _public_groups(target: dict[str, Any]) -> list[dict[str, Any]]:
    groups = []
    for group in target.get("fault_groups", []):
        groups.append({
            "key": group["key"],
            "label": group["label"],
            "kind": group["kind"],
            "enabled": group.get("enabled", False),
            "description": group.get("description", ""),
            "disabled_reason": group.get("disabled_reason"),
            "faults": group.get("faults", []),
        })
    return groups

