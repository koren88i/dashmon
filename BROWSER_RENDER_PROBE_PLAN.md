# Browser Render Probe Plan

## Summary

Add an optional Playwright-based browser render probe that measures the real Grafana dashboard page path separately from the existing query-side `dashboard_load_time_seconds`.

The current metric remains the query critical-path estimate. The new probe reports browser-observed readiness for each dashboard target so the SRE meta-dashboard can answer: "Would a user open this dashboard and see it fully rendered in time?"

## Key Changes

- Add a separate `browser-render-probe` service using Playwright, not inside the existing probe engine.
- Load `dashboard_targets.yaml`, derive dashboard identity from each target, and probe Grafana URLs by dashboard UID.
- Use the Docker Grafana URL by default: `http://grafana:3000/d/<dashboard_uid>/<slug>?orgId=1&from=now-1h&to=now&kiosk`. Do not pass `refresh=off`; Grafana 10.4 treats that as an invalid interval and can leave dashboards stuck loading.
- Treat "rendered" as: dashboard page loaded, panels scrolled through to trigger lazy rendering, no visible loading spinners, no Grafana panel errors, no visible "No data" states, and at least one panel body observed.
- Keep render timing separate from query timing:
  - `dashboard_load_time_seconds`: existing max panel query duration.
  - `dashboard_render_time_seconds`: browser-observed full dashboard readiness time.
- Expose new Prometheus metrics:
  - `dashboard_render_status{dashboard_uid}`: `1` healthy, `0` degraded.
  - `dashboard_render_time_seconds{dashboard_uid}`: last render attempt duration.
  - `dashboard_render_last_probe_timestamp{dashboard_uid}`: epoch timestamp of last completed render probe.
  - `dashboard_render_error_total{dashboard_uid,error_type}`: cumulative render failures.
- Use v1 render error types:
  - `render_timeout`
  - `render_navigation_error`
  - `render_panel_error`
  - `render_no_data`
  - `render_blank`
- Add a `/health` endpoint on the browser render probe for operator debugging, returning one status object per dashboard UID.
- Add render probe config defaults:
  - `enabled: true` in Docker.
  - `interval_seconds: 15`.
  - `timeout_seconds: 15`.
  - `slow_render_seconds: 10`.
  - `max_concurrency: 2`.
- Add the service to Docker Compose and Prometheus scrape config. Keep it optional and isolated so normal probe-engine containers stay lightweight.

## Simulator Faults

- Existing simulator faults are enough for v1 render-probe validation because they create Grafana-visible blank, no-data, slow, or panel-error states.
- Do not add pure render-origin faults in v1. The simulator will not yet fake frontend JS failures, CSS/layout breakage, browser CPU slowdown, or blank panels while datasource/API probes stay healthy.
- Update simulator fault metadata so faults that should affect the rendered dashboard include `browser_render` in `affected_layers` and the relevant render signal in `expected_sre_signals`.
- Keep `panel_query_http_500` as the clearest existing Grafana-visible panel-error scenario.
- Add true render-layer fault injection as a future v2, likely via a Grafana-facing proxy or test-only browser probe mode.

## Meta-Dashboard And Alerts

- Update generated SRE meta-dashboards with a new overview stat: Browser Render Time.
- Add a render status panel near the existing Datasource API and Grafana Panel Path checks.
- Add Grafana alert rules:
  - Browser render degraded when `dashboard_render_status == 0` for `2m`.
  - Slow browser render when `dashboard_render_time_seconds > 10` for `5m`.
- Keep alert rule UIDs derived from dashboard UID and under Grafana's 40-character limit.
- Do not include render timing in `dashboard_health_score` for v1; show and alert it separately to avoid changing existing health semantics unexpectedly.

## Test Plan

- Unit tests:
  - Render config defaults and parsing.
  - Grafana dashboard URL construction from `dashboard_targets.yaml`.
  - Readiness classifier for loaded, loading, no-data, panel-error, blank, and timeout states.
  - Metric updates for success and failure.
  - Simulator metadata includes `browser_render` for render-visible faults.
  - Meta-dashboard generator includes browser render panels.
  - Alert generator includes render rules with valid UIDs and no `$` in titles.
- Integration tests:
  - Use a small fake Grafana page to verify Playwright measures a successful render.
  - Verify timeout and visible panel-error states produce degraded render status.
  - Verify `/metrics` exposes all render metrics with `dashboard_uid` labels.
- Docker verification:
  - `docker compose up --build -d browser-render-probe prometheus grafana`
  - `curl http://localhost:<render_probe_port>/health`
  - `curl http://localhost:<render_probe_port>/metrics`
  - Confirm Prometheus scrapes `dashboard_render_time_seconds`.
  - Confirm the generated SRE dashboard imports and shows the browser render panels.
- E2E scenario:
  - Start the full demo stack.
  - Observe baseline render status `1`.
  - Inject an existing simulator fault that causes Grafana-visible panel failure or no data.
  - Confirm render status turns red.
  - Clear faults and confirm render status recovers.

## Assumptions

- The v1 implementation measures Docker/Grafana demo dashboards first.
- Grafana anonymous auth remains enabled as it is today.
- Browser render probing is supplementary in v1 and does not replace datasource or Grafana panel-path probes.
- The repo-root plan file is preferred because current durable project docs already live at the root.
