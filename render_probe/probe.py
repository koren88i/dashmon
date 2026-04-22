"""Playwright-based browser render probing."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from render_probe.config import RenderProbeSettings, RenderTarget
from render_probe.readiness import (
    RENDER_NAVIGATION_ERROR,
    RENDER_TIMEOUT,
    DashboardDomSnapshot,
    RenderReadiness,
    classify_snapshot,
)


@dataclass(frozen=True)
class RenderProbeResult:
    dashboard_uid: str
    dashboard_title: str
    target_key: str
    url: str
    status: str
    duration_seconds: float
    error_type: str | None = None
    message: str = ""
    timestamp: float = 0.0


class BrowserRenderProbe:
    """Runs Grafana dashboards through a real browser and classifies readiness."""

    def __init__(self, settings: RenderProbeSettings):
        self.settings = settings
        self._playwright: Any | None = None
        self._browser: Any | None = None

    async def start(self) -> None:
        if self._browser is not None:
            return
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)

    async def stop(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    async def probe(self, target: RenderTarget) -> RenderProbeResult:
        await self.start()
        assert self._browser is not None

        start = time.monotonic()
        timestamp = time.time()
        page = await self._browser.new_page(viewport={"width": 1440, "height": 1000})
        try:
            await page.goto(
                target.url,
                wait_until="domcontentloaded",
                timeout=self.settings.timeout_seconds * 1000,
            )
            readiness = await wait_for_dashboard_ready(page, self.settings.timeout_seconds)
            duration = time.monotonic() - start
            if readiness.ready:
                return _result(target, "healthy", duration, readiness.message, timestamp=timestamp)
            return _result(
                target,
                "degraded",
                duration,
                readiness.message,
                error_type=readiness.error_type or RENDER_TIMEOUT,
                timestamp=timestamp,
            )
        except Exception as exc:
            is_timeout = exc.__class__.__name__ == "TimeoutError"
            return _result(
                target,
                "degraded",
                time.monotonic() - start,
                (
                    f"Timed out after {self.settings.timeout_seconds}s"
                    if is_timeout
                    else f"Browser navigation failed: {exc}"
                ),
                error_type=RENDER_TIMEOUT if is_timeout else RENDER_NAVIGATION_ERROR,
                timestamp=timestamp,
            )
        finally:
            await page.close()


async def wait_for_dashboard_ready(page: Any, timeout_seconds: float) -> RenderReadiness:
    """Scroll the dashboard to trigger lazy panels, then wait for a stable state."""
    deadline = time.monotonic() + timeout_seconds
    last = RenderReadiness("pending", message="No browser snapshot collected")
    position = 0

    while time.monotonic() < deadline:
        await page.evaluate("(y) => window.scrollTo(0, y)", position)
        await page.wait_for_timeout(250)
        snapshot = await collect_snapshot(page)
        last = classify_snapshot(snapshot)
        if last.state == "degraded":
            return last
        if last.ready:
            body_height = await _body_height(page)
            viewport_height = await _viewport_height(page)
            if position + viewport_height >= body_height:
                return last
            position += max(int(viewport_height * 0.8), 400)
        else:
            position = 0

    return RenderReadiness(
        "degraded",
        RENDER_TIMEOUT,
        last.message or f"Timed out after {timeout_seconds}s",
    )


async def collect_snapshot(page: Any) -> DashboardDomSnapshot:
    data = await page.evaluate(
        """() => {
          const visible = (el) => {
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.display !== 'none' &&
              style.visibility !== 'hidden' &&
              rect.width > 0 &&
              rect.height > 0;
          };
          const all = (selector) => Array.from(document.querySelectorAll(selector)).filter(visible);
          const text = document.body ? document.body.innerText : '';
          const panelSelectors = [
            '[data-testid="data-testid Panel header"]',
            '[data-testid="data-testid Panel container"]',
            '[data-panelid]',
            '.panel-container',
            '.react-grid-item'
          ].join(',');
          const panelBodySelectors = [
            '[data-testid="data-testid Panel content"]',
            '[data-panelid] canvas',
            '[data-panelid] svg',
            '[data-panelid] table',
            '.panel-content',
            '.flot-base',
            'canvas'
          ].join(',');
          const loadingSelectors = [
            '[aria-label*="Loading"]',
            '[data-testid*="loading"]',
            '.panel-loading',
            '.loading-placeholder'
          ].join(',');
          const panelErrorPatterns = [
            /Panel plugin not found/i,
            /Datasource error/i,
            /Query error/i,
            /An error occurred/i,
            /Error loading/i,
            /Plugin unavailable/i
          ];
          const noDataPatterns = [
            /No data/i,
            /No data to show/i
          ];
          return {
            documentReady: document.readyState === 'interactive' || document.readyState === 'complete',
            dashboardSeen: Boolean(document.querySelector('[data-testid="dashboard-container"], .dashboard-container, .react-grid-layout, [aria-label="Dashboard"]')) || /Dashboard/i.test(text),
            panelCount: all(panelSelectors).length,
            panelBodyCount: all(panelBodySelectors).length,
            loadingCount: all(loadingSelectors).length + (/Loading/i.test(text) ? 1 : 0),
            panelErrorCount: panelErrorPatterns.filter((pattern) => pattern.test(text)).length,
            noDataCount: noDataPatterns.filter((pattern) => pattern.test(text)).length,
            url: window.location.href
          };
        }"""
    )
    return DashboardDomSnapshot(
        document_ready=bool(data.get("documentReady")),
        dashboard_seen=bool(data.get("dashboardSeen")),
        panel_count=int(data.get("panelCount") or 0),
        panel_body_count=int(data.get("panelBodyCount") or 0),
        loading_count=int(data.get("loadingCount") or 0),
        panel_error_count=int(data.get("panelErrorCount") or 0),
        no_data_count=int(data.get("noDataCount") or 0),
        url=str(data.get("url") or ""),
    )


async def _body_height(page: Any) -> int:
    return int(await page.evaluate("() => document.body ? document.body.scrollHeight : 0") or 0)


async def _viewport_height(page: Any) -> int:
    size = page.viewport_size or {"height": 1000}
    return int(size.get("height") or 1000)


def _result(
    target: RenderTarget,
    status: str,
    duration: float,
    message: str,
    *,
    error_type: str | None = None,
    timestamp: float,
) -> RenderProbeResult:
    return RenderProbeResult(
        dashboard_uid=target.dashboard_uid,
        dashboard_title=target.title,
        target_key=target.key,
        url=target.url,
        status=status,
        duration_seconds=round(duration, 3),
        error_type=error_type,
        message=message,
        timestamp=timestamp,
    )
