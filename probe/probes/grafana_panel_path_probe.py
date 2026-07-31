"""Grafana panel-path probe.

This probe exercises Grafana's datasource plugin path instead of the raw
Prometheus API. It catches failures where Prometheus itself is healthy but
Grafana panels would render "No data" or a datasource error.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from probe.config import (
    ErrorType,
    PanelProbeSpec,
    ProbeConfig,
    ProbeResult,
    ProbeStatus,
)


class GrafanaPanelPathProbe:
    """Probe panel queries through Grafana's /api/ds/query endpoint."""

    async def probe(
        self,
        spec: PanelProbeSpec,
        datasource_url: str,
        config: ProbeConfig,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> ProbeResult:
        start = time.monotonic()
        total_frames = 0

        try:
            if client is not None:
                for query in spec.queries:
                    total_frames += await self._execute_query(client, spec, query, config)
            else:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(config.query_timeout_seconds),
                ) as managed_client:
                    for query in spec.queries:
                        total_frames += await self._execute_query(managed_client, spec, query, config)
        except httpx.TimeoutException:
            return ProbeResult(
                panel_id=spec.panel_id,
                panel_title=spec.panel_title,
                status=ProbeStatus.DEGRADED,
                probe_type="grafana_panel_path",
                error_type=ErrorType.QUERY_TIMEOUT,
                message=f"Grafana panel query timed out after {config.query_timeout_seconds}s",
                duration_seconds=time.monotonic() - start,
            )
        except httpx.HTTPStatusError as exc:
            return ProbeResult(
                panel_id=spec.panel_id,
                panel_title=spec.panel_title,
                status=ProbeStatus.DEGRADED,
                probe_type="grafana_panel_path",
                error_type=ErrorType.PANEL_ERROR,
                message=f"Grafana datasource HTTP {exc.response.status_code}: {_short_body(exc.response)}",
                duration_seconds=time.monotonic() - start,
            )
        except (ValueError, TypeError) as exc:
            return ProbeResult(
                panel_id=spec.panel_id,
                panel_title=spec.panel_title,
                status=ProbeStatus.DEGRADED,
                probe_type="grafana_panel_path",
                error_type=ErrorType.PANEL_ERROR,
                message=f"Grafana datasource response error: {exc}",
                duration_seconds=time.monotonic() - start,
            )
        except httpx.HTTPError as exc:
            return ProbeResult(
                panel_id=spec.panel_id,
                panel_title=spec.panel_title,
                status=ProbeStatus.DEGRADED,
                probe_type="grafana_panel_path",
                error_type=ErrorType.PANEL_ERROR,
                message=f"Grafana datasource transport error: {exc}",
                duration_seconds=time.monotonic() - start,
            )

        duration = time.monotonic() - start
        if total_frames == 0:
            return ProbeResult(
                panel_id=spec.panel_id,
                panel_title=spec.panel_title,
                status=ProbeStatus.DEGRADED,
                probe_type="grafana_panel_path",
                error_type=ErrorType.NO_DATA,
                message="Grafana panel path returned empty data frames",
                duration_seconds=duration,
                series_count=0,
            )

        if duration > config.slow_query_seconds:
            return ProbeResult(
                panel_id=spec.panel_id,
                panel_title=spec.panel_title,
                status=ProbeStatus.DEGRADED,
                probe_type="grafana_panel_path",
                error_type=ErrorType.SLOW_QUERY,
                message=f"Grafana panel query took {duration:.1f}s (threshold: {config.slow_query_seconds}s)",
                duration_seconds=duration,
                series_count=total_frames,
            )

        return ProbeResult(
            panel_id=spec.panel_id,
            panel_title=spec.panel_title,
            status=ProbeStatus.HEALTHY,
            probe_type="grafana_panel_path",
            duration_seconds=duration,
            series_count=total_frames,
        )

    async def _execute_query(
        self,
        client: httpx.AsyncClient,
        spec: PanelProbeSpec,
        query: str,
        config: ProbeConfig,
    ) -> int:
        now_ms = int(time.time() * 1000)
        from_ms = now_ms - int(config.grafana.query_range_seconds * 1000)
        step_seconds = max(config.grafana.step_seconds, 1.0)
        payload = {
            "from": str(from_ms),
            "to": str(now_ms),
            "queries": [
                {
                    "refId": "A",
                    "datasource": {
                        "uid": spec.datasource_uid,
                        "type": spec.datasource_type,
                    },
                    "expr": query,
                    "range": True,
                    "instant": False,
                    "format": "time_series",
                    "interval": f"{int(step_seconds)}s",
                    "intervalMs": int(step_seconds * 1000),
                    "maxDataPoints": config.grafana.max_data_points,
                }
            ],
        }
        response = await client.post(
            f"{config.grafana.url.rstrip('/')}/api/ds/query",
            json=payload,
        )
        response.raise_for_status()
        body = response.json()
        return _count_non_empty_frames(body)


def _count_non_empty_frames(body: dict[str, Any]) -> int:
    results = body.get("results")
    if not isinstance(results, dict) or not results:
        return 0

    count = 0
    for result in results.values():
        if not isinstance(result, dict):
            continue
        status = result.get("status", 200)
        if isinstance(status, int) and status >= 400:
            raise ValueError(f"Grafana query result status {status}")
        frames = result.get("frames", [])
        if not isinstance(frames, list):
            raise ValueError("Grafana query result frames must be a list")
        count += sum(1 for frame in frames if _frame_has_values(frame))
    return count


def _frame_has_values(frame: dict[str, Any]) -> bool:
    values = frame.get("data", {}).get("values", [])
    if not isinstance(values, list) or not values:
        return False

    # Grafana frames store one list per field. Field 0 is usually time, so a
    # value field must contain at least one non-null point to be panel data.
    value_fields = values[1:] if len(values) > 1 else values
    return any(
        isinstance(field_values, list) and any(value is not None for value in field_values)
        for field_values in value_fields
    )


def _short_body(response: httpx.Response) -> str:
    text = response.text.strip()
    return text[:200] if text else response.reason_phrase
