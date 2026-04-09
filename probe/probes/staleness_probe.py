"""Staleness probe — detects frozen/stale data in panel queries.

Checks the max timestamp in query results against now(). If the data
is older than stale_data_multiplier × scrape_interval, marks STALE_DATA.
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

class StalenessProbe:
    """Check whether panel data is stale (timestamps too old)."""

    async def probe(
        self,
        spec: PanelProbeSpec,
        datasource_url: str,
        config: ProbeConfig,
    ) -> ProbeResult:
        start = time.monotonic()
        max_ts: float | None = None

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
                    for item in body.get("data", {}).get("result", []):
                        ts = item.get("value", [0])[0]
                        if isinstance(ts, (int, float)):
                            if max_ts is None or ts > max_ts:
                                max_ts = ts
        except Exception:
            # Staleness probe doesn't report connection errors — query_probe handles those.
            return ProbeResult(
                panel_id=spec.panel_id,
                panel_title=spec.panel_title,
                status=ProbeStatus.UNKNOWN,
                duration_seconds=time.monotonic() - start,
            )

        duration = time.monotonic() - start

        if max_ts is None:
            # No timestamps found — query_probe will catch NO_DATA.
            return ProbeResult(
                panel_id=spec.panel_id,
                panel_title=spec.panel_title,
                status=ProbeStatus.UNKNOWN,
                duration_seconds=duration,
            )

        age = time.time() - max_ts
        threshold = config.scrape_interval_seconds * config.stale_data_multiplier

        if age > threshold:
            return ProbeResult(
                panel_id=spec.panel_id,
                panel_title=spec.panel_title,
                status=ProbeStatus.DEGRADED,
                error_type=ErrorType.STALE_DATA,
                message=f"Data is {age:.0f}s old (threshold: {threshold:.0f}s)",
                duration_seconds=duration,
                max_timestamp=max_ts,
            )

        return ProbeResult(
            panel_id=spec.panel_id,
            panel_title=spec.panel_title,
            status=ProbeStatus.HEALTHY,
            duration_seconds=duration,
            max_timestamp=max_ts,
        )
