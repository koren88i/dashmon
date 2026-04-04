"""Query probe — executes panel PromQL and checks for failures.

Detects: NO_DATA, QUERY_TIMEOUT, SLOW_QUERY, PANEL_ERROR.
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


class QueryProbe:
    """Probe that executes a panel's PromQL queries against Prometheus."""

    async def probe(
        self,
        spec: PanelProbeSpec,
        datasource_url: str,
        config: ProbeConfig,
    ) -> ProbeResult:
        total_series = 0
        start = time.monotonic()

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(config.query_timeout_seconds),
            ) as client:
                for query in spec.queries:
                    result = await self._execute_query(client, datasource_url, query)
                    total_series += len(result)

        except httpx.TimeoutException:
            return ProbeResult(
                panel_id=spec.panel_id,
                panel_title=spec.panel_title,
                status=ProbeStatus.DEGRADED,
                error_type=ErrorType.QUERY_TIMEOUT,
                message=f"Query timed out after {config.query_timeout_seconds}s",
                duration_seconds=time.monotonic() - start,
            )
        except httpx.HTTPError as exc:
            return ProbeResult(
                panel_id=spec.panel_id,
                panel_title=spec.panel_title,
                status=ProbeStatus.DEGRADED,
                error_type=ErrorType.PANEL_ERROR,
                message=f"HTTP error: {exc}",
                duration_seconds=time.monotonic() - start,
            )

        duration = time.monotonic() - start

        # Check: no data returned
        if total_series == 0:
            return ProbeResult(
                panel_id=spec.panel_id,
                panel_title=spec.panel_title,
                status=ProbeStatus.DEGRADED,
                error_type=ErrorType.NO_DATA,
                message="Query returned 0 series",
                duration_seconds=duration,
                series_count=0,
            )

        # Check: slow query
        if duration > config.slow_query_seconds:
            return ProbeResult(
                panel_id=spec.panel_id,
                panel_title=spec.panel_title,
                status=ProbeStatus.DEGRADED,
                error_type=ErrorType.SLOW_QUERY,
                message=f"Query took {duration:.1f}s (threshold: {config.slow_query_seconds}s)",
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

    async def _execute_query(
        self,
        client: httpx.AsyncClient,
        url: str,
        query: str,
    ) -> list[dict]:
        """Execute an instant query and return the result list."""
        resp = await client.get(
            f"{url}/api/v1/query",
            params={"query": query},
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("status") != "success":
            raise httpx.HTTPError(f"Prometheus error: {body}")
        return body.get("data", {}).get("result", [])
