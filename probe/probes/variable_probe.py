"""Variable probe — checks that template variable queries return values.

Detects: VAR_RESOLUTION_FAIL when a variable's label_values query returns
an empty list (the dropdown in the dashboard would be blank).
"""

from __future__ import annotations

import re
import time

import httpx

from probe.config import (
    ErrorType,
    ProbeConfig,
    ProbeStatus,
    VariableProbeSpec,
)


class VariableProbeResult:
    __slots__ = ("name", "status", "error_type", "message", "duration_seconds", "values_count")

    def __init__(
        self,
        name: str,
        status: ProbeStatus,
        error_type: ErrorType | None = None,
        message: str = "",
        duration_seconds: float = 0.0,
        values_count: int = 0,
    ):
        self.name = name
        self.status = status
        self.error_type = error_type
        self.message = message
        self.duration_seconds = duration_seconds
        self.values_count = values_count

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status.value,
            "error": self.error_type.value if self.error_type else None,
            "duration": self.duration_seconds,
            "values_count": self.values_count,
        }


class VariableProbe:
    """Probe that checks template variable resolution."""

    async def probe(
        self,
        spec: VariableProbeSpec,
        datasource_url: str,
        config: ProbeConfig,
    ) -> VariableProbeResult:
        start = time.monotonic()
        label_name = _extract_label_name(spec.query)

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{datasource_url}/api/v1/label/{label_name}/values",
                )
                resp.raise_for_status()
                body = resp.json()
                values = body.get("data", [])
        except Exception as exc:
            return VariableProbeResult(
                name=spec.name,
                status=ProbeStatus.DEGRADED,
                error_type=ErrorType.VAR_RESOLUTION_FAIL,
                message=str(exc),
                duration_seconds=time.monotonic() - start,
            )

        duration = time.monotonic() - start

        if not values:
            return VariableProbeResult(
                name=spec.name,
                status=ProbeStatus.DEGRADED,
                error_type=ErrorType.VAR_RESOLUTION_FAIL,
                message=f"Variable ${spec.name} returned empty values",
                duration_seconds=duration,
            )

        return VariableProbeResult(
            name=spec.name,
            status=ProbeStatus.HEALTHY,
            duration_seconds=duration,
            values_count=len(values),
        )


def _extract_label_name(query: str) -> str:
    """Extract label name from label_values(metric, label) or label_values(label)."""
    if "," in query:
        return query.rsplit(",", 1)[1].strip().rstrip(")")
    inner = query.replace("label_values(", "").rstrip(")")
    return inner.strip()
