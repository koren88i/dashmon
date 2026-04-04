"""Cardinality probe — detects series count anomalies.

Detects:
- CARDINALITY_SPIKE: series count > baseline × cardinality_spike_ratio
- METRIC_RENAME: query returns 0 series despite no error (silently missing)
"""

from __future__ import annotations

import time

import httpx

from probe.config import (
    ErrorType,
    PanelProbeSpec,
    ProbeConfig,
    ProbeResult,
    ProbeStatus,
)


class CardinalityProbe:
    """Track series counts and detect spikes or silent metric renames."""

    def __init__(self) -> None:
        # Baseline series counts per panel_id, learned from first healthy probe.
        self._baselines: dict[int, int] = {}

    async def probe(
        self,
        spec: PanelProbeSpec,
        datasource_url: str,
        config: ProbeConfig,
    ) -> ProbeResult:
        start = time.monotonic()
        total_series = 0

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(config.query_timeout_seconds),
            ) as client:
                for query in spec.queries:
                    resp = await client.get(
                        f"{datasource_url}/api/v1/query",
                        params={"query": query},
                    )
                    resp.raise_for_status()
                    body = resp.json()
                    total_series += len(body.get("data", {}).get("result", []))
        except Exception:
            # Connection errors handled by query_probe.
            return ProbeResult(
                panel_id=spec.panel_id,
                panel_title=spec.panel_title,
                status=ProbeStatus.UNKNOWN,
                duration_seconds=time.monotonic() - start,
            )

        duration = time.monotonic() - start

        # METRIC_RENAME: 0 series with no error suggests the metric was renamed.
        if total_series == 0 and spec.expected_min_series > 0:
            return ProbeResult(
                panel_id=spec.panel_id,
                panel_title=spec.panel_title,
                status=ProbeStatus.DEGRADED,
                error_type=ErrorType.METRIC_RENAME,
                message="Query returned 0 series — metric may have been renamed",
                duration_seconds=duration,
                series_count=0,
            )

        # Learn baseline on first successful probe.
        baseline = self._baselines.get(spec.panel_id)
        if baseline is None and total_series > 0:
            self._baselines[spec.panel_id] = total_series

        # CARDINALITY_SPIKE: series count significantly above baseline.
        if baseline is not None and baseline > 0:
            ratio = total_series / baseline
            if ratio > config.cardinality_spike_ratio:
                return ProbeResult(
                    panel_id=spec.panel_id,
                    panel_title=spec.panel_title,
                    status=ProbeStatus.DEGRADED,
                    error_type=ErrorType.CARDINALITY_SPIKE,
                    message=f"Series count {total_series} is {ratio:.1f}x baseline ({baseline})",
                    duration_seconds=duration,
                    series_count=total_series,
                )

        return ProbeResult(
            panel_id=spec.panel_id,
            panel_title=spec.panel_title,
            status=ProbeStatus.HEALTHY,
            duration_seconds=duration,
            series_count=total_series,
        )
