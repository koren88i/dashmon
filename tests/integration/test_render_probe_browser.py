"""Integration smoke tests for Playwright render readiness.

These tests skip when Playwright or browser binaries are not installed.
"""

from __future__ import annotations

import pytest

from render_probe.probe import wait_for_dashboard_ready

pytestmark = pytest.mark.integration


async def test_wait_for_dashboard_ready_static_page():
    playwright_mod = pytest.importorskip("playwright.async_api")

    try:
        playwright = await playwright_mod.async_playwright().start()
        browser = await playwright.chromium.launch(headless=True)
    except Exception as exc:
        pytest.skip(f"Playwright browser is not available: {exc}")

    page = await browser.new_page(viewport={"width": 800, "height": 600})
    try:
        await page.set_content(
            """
            <main class="dashboard-container">
              <section class="react-grid-layout">
                <article data-panelid="1">
                  <canvas width="100" height="30"></canvas>
                </article>
              </section>
            </main>
            """
        )
        result = await wait_for_dashboard_ready(page, timeout_seconds=2)
        assert result.ready is True
    finally:
        await page.close()
        await browser.close()
        await playwright.stop()
