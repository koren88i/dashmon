# Architecture

Dashboard SRE monitors the **user experience** of a Grafana dashboard — detecting what a user would see when opening it: blank panels, stale data, slow loads, broken variables. It is not a general Grafana-stack monitor, but Docker probe configs do exercise Grafana's datasource plugin path so the SRE dashboard can catch panel failures that raw datasource probes miss.

---

## System overview

```
Grafana Dashboard JSON
        │
        ▼
   parser.py ──→ PanelProbeSpec / VariableProbeSpec
        │
        ├──→ engine.py  (probe loop, 15s interval, concurrent asyncio tasks)
        │       │
        │       ├──→ query_probe.py              datasource_api layer
        │       ├──→ grafana_panel_path_probe.py Grafana /api/ds/query layer
        │       ├──→ staleness_probe.py          STALE_DATA
        │       ├──→ variable_probe.py           VAR_RESOLUTION_FAIL, VARIABLE_QUERY_ERROR
        │       └──→ cardinality_probe.py        CARDINALITY_SPIKE, METRIC_RENAME
        │       │
        │       └──→ metrics.py ──→ /metrics (Prometheus exposition)
        │                      ──→ /health  (JSON summary for UI)
        │
        ├──→ generator/meta_dashboard.py ──→ Grafana dashboard JSON (importable)
        ├──→ generator/alert_rules.py    ──→ Grafana alerting YAML (provisionable)
        └──→ generator/dashboard_targets.py ──→ registry-driven demo artifacts

mock_backend/
        └──→ prometheus_api.py  (Prometheus HTTP API shape)
        └──→ fault_injector.py  (in-memory fault state, auto-expiry)

fault_proxy/
        -> prometheus_proxy.py (Prometheus API passthrough + response faults)

fault_controller/
        -> api.py (browser-facing target/group fault delegation)

render_probe/
        -> app.py       (FastAPI /health + /metrics)
        -> probe.py     (Playwright browser render checks)

demo/
        ├──→ simulator.html     (no-build UI)
        └──→ dashboard_targets.js (generated selector/fault targets)
```

---

## Components

### `probe/parser.py`

Reads a Grafana dashboard JSON and emits two lists of probe specs:

- **`PanelProbeSpec`** — one per panel: `panel_id`, `panel_title`, `datasource_uid`, `datasource_type`, `queries` (raw PromQL strings), `expected_min_series`.
- **`VariableProbeSpec`** — one per template variable: `name`, `datasource_uid`, `query`, `is_chained`, `chain_depth`.

Template variable references (`$pod`, `${namespace}`) are replaced with `.*` so the probe can fire the query against real data without knowing the current variable value.

### `probe/engine.py`

FastAPI app. On startup it loads `config.yaml` and the dashboard JSON, then runs a probe loop:

1. All panel probes fire concurrently (`asyncio.gather`).
2. The raw `datasource_api` layer calls Prometheus `GET /api/v1/query`; the optional `grafana_panel_path` layer calls Grafana `POST /api/ds/query`.
3. Each panel's worst-case status across enabled layers and diagnostic probes wins, so dashboard health is green only when the required user-facing path is healthy.
4. Results update Prometheus metrics and the in-memory issue log.
5. Loop sleeps for `probe_interval_seconds` (default 15s) then repeats.

Issue events are diagnosis-aware. The engine logs a new event when a check goes healthy -> degraded, degraded -> healthy, or degraded -> degraded with a different `(probe_type, error_type)` signature. It does not log every probe cycle while the same diagnosis remains active.

Endpoints:
- `GET /metrics` — Prometheus exposition format, scraped by Prometheus.
- `GET /health` — JSON summary: health score, per-panel statuses, per-panel `layers`, per-variable statuses, recent issues. Polled by the demo UI every 5s.

### `probe/metrics.py`

All Prometheus metrics live here, registered on a dedicated `CollectorRegistry` to avoid conflicts with the default registry when running tests.

| Metric | Type | Description |
|---|---|---|
| `dashboard_health_score` | Gauge | 0.0–1.0, fraction of healthy panels |
| `dashboard_load_time_seconds` | Gauge | Estimated worst-case load time (max panel query duration) |
| `dashboard_panel_status` | Gauge | 1=healthy, 0=degraded, per panel × probe type |
| `dashboard_panel_query_duration_seconds` | Histogram | Query round-trip time per panel |
| `dashboard_panel_last_datapoint_age_seconds` | Gauge | Age of most recent datapoint per panel |
| `dashboard_panel_series_count` | Gauge | Number of time series returned per panel |
| `dashboard_panel_error_total` | Counter | Cumulative errors per panel × error type |
| `dashboard_variable_status` | Gauge | 1=healthy, 0=degraded, per variable |
| `dashboard_variable_error_total` | Counter | Cumulative variable errors by variable and error type |
| `dashboard_variable_dependency_impact` | Gauge | Panels currently blocked by failed variables, labeled by variable, panel, and variable error type |
| `dashboard_variable_query_duration_seconds` | Histogram | Variable label query round-trip time |
| `dashboard_issue_count` | Gauge | Number of currently degraded panels and variables |
| `dashboard_issue_event_timestamp_seconds` | Gauge | Unix timestamp in seconds for recent issue diagnosis transitions, labeled by panel, probe path, error type, and message |

### Probe types

| Probe | File | Failure modes |
|---|---|---|
| Query | `query_probe.py` | `datasource_api` layer. Uses raw Prometheus `GET /api/v1/query` and reports `NO_DATA`, `QUERY_TIMEOUT`, `SLOW_QUERY`, or `PANEL_ERROR` |
| Grafana Panel Path | `grafana_panel_path_probe.py` | `grafana_panel_path` layer. Uses Grafana `POST /api/ds/query` and reports `PANEL_ERROR` for transport/plugin failures or `NO_DATA` for empty/valueless frames |
| Variable Dependency | `engine.py` | `variable_dependency` layer. Maps failed dashboard variables back to panels that reference them and reports `BLOCKED_BY_VARIABLE` |
| Staleness | `staleness_probe.py` | `STALE_DATA` — most recent datapoint timestamp is older than `stale_data_multiplier × scrape_interval` |
| Variable | `variable_probe.py` | `VAR_RESOLUTION_FAIL` when label values return zero results; `VARIABLE_QUERY_ERROR` when the variable endpoint itself fails |
| Cardinality | `cardinality_probe.py` | `CARDINALITY_SPIKE` — series count exceeds baseline × `cardinality_spike_ratio`; `METRIC_RENAME` — series count dropped to zero after previously being non-zero |

Variable probing distinguishes empty successful discovery from hard endpoint failure:
`VAR_RESOLUTION_FAIL` means the variable query returned zero values, while
`VARIABLE_QUERY_ERROR` means the variable discovery endpoint itself failed.
Panel queries keep both raw Grafana expressions and normalized probe expressions:
raw expressions identify variable dependencies, while normalized expressions
replace variables with safe sentinels such as `.*` so datasource health can
still be tested independently. If a failed variable is referenced by a panel,
the panel is marked `blocked_by_variable` through the `variable_dependency`
layer rather than misreported as `no_data`.

Engine-level detection:
- `SLOW_DASHBOARD` — max panel query duration exceeds `slow_dashboard_seconds` threshold.

### `render_probe/`

FastAPI app that runs separately from the probe engines. It loads
`dashboard_targets.yaml`, derives each Grafana dashboard URL from the target
`dashboard_uid`, opens the real Grafana page with Playwright, scrolls through
the dashboard to trigger lazy panels, and classifies the page as healthy only
when visible panels finish rendering without loading, no-data, blank, or
panel-error states.

Browser render metrics are supplementary and do not change
`dashboard_health_score` in v1.

| Metric | Type | Description |
|---|---|---|
| `dashboard_render_status` | Gauge | 1=browser render healthy, 0=degraded |
| `dashboard_render_time_seconds` | Gauge | Browser-observed time to render the full dashboard |
| `dashboard_render_last_probe_timestamp` | Gauge | Unix epoch of the most recent browser render probe |
| `dashboard_render_error_total` | Counter | Cumulative render failures by dashboard and error type |

Render error types are `render_timeout`, `render_navigation_error`,
`render_panel_error`, `render_no_data`, and `render_blank`.

### `generator/meta_dashboard.py`

Generates a Grafana dashboard JSON for the meta-dashboard. The output has seven rows:

1. **Overview** — health score, active issue count, estimated load time, browser render time, time since last probe, and time since last render probe.
2. **Panel health grid** — one stat panel per target panel, green/red.
3. **Probe Layers** — compact raw datasource, Grafana panel-path, variable-dependency, and browser-render breakdown.
4. **Query performance** — p50/p95 timeseries + heatmap.
5. **Variable health** — per-variable status badges, query duration timeseries, recent variable error types, and variable blast radius.
6. **Issue log** — table of recent error increments.
7. **Alerts** — alertlist panel filtered to this dashboard's rules.

The output is importable into any Grafana instance pointed at a Prometheus that scrapes the probe engine's `/metrics`.

Meta-dashboard panels use a datasource variable named `sre_datasource`, defaulting to the `probe-metrics` datasource. Avoid the generic `datasource` variable name here because source-dashboard URLs can carry stale `var-datasource=...` overrides into SRE dashboards.

The **Recent Issue Events** table treats the metric sample value as the event time. `dashboard_issue_event_timestamp_seconds` is emitted in Unix seconds, so the Grafana panel query multiplies it by `1000` before applying the `dateTimeAsIso` field override to `Event Time`. The table hides Grafana's instant-query `Time` field because that is the query evaluation time and will be identical for all rows in a refresh. The table also shows `probe_type` as `Path`, so an operator can distinguish direct datasource, Grafana panel-path, variable, and dashboard-level diagnoses.

The variable row also includes recent variable error types so empty results
and hard query failures can be distinguished.

### `generator/alert_rules.py`

Generates Grafana Alerting provisioning YAML. Rule count: `panels × 9 probe types + variables + 4 dashboard-level rules`. For 6 panels and 2 variables: 60 rules total.

Each rule fires after 2 minutes of continuous degradation (`for: 2m`) to suppress transient blips.

### `dashboard_targets.yaml` and `generator/dashboard_targets.py`

`dashboard_targets.yaml` is the canonical registry for provisioned demo targets. Each target declares the source dashboard JSON, source datasource, isolated service path, host ports, probe config path, generated SRE dashboard path, generated alert rules path, grouped fault classes, controller delegate endpoints, and affected Grafana surfaces.

`python -m generator.dashboard_targets --write` regenerates:
- probe config YAMLs
- SRE dashboard JSONs
- Grafana alert rule YAMLs
- Grafana datasource provisioning
- Prometheus scrape configs
- `demo/dashboard_targets.js`

`python -m generator.dashboard_targets --check` verifies generated artifacts and validates that explicit `docker-compose.yml` services match the registry. Compose is intentionally not generated; the isolated mock, proxy, live Mongo, and probe paths remain visible as named services.

Fault groups are part of the registry contract:
- `mock` groups delegate to mock Prometheus backends.
- `proxy` groups delegate to a faultable Prometheus API proxy in front of a real Prometheus.
- `infra` groups model whitelisted infrastructure actions. They are disabled in this MVP and return a stable disabled response through the controller.

Fault entries also include generated simulator metadata:
- `affected_layers` describes where the dashboard failure should appear (`datasource_api`, `grafana_panel_path`, `browser_render`, `variable_resolution`, `variable_dependency`, `stale_data`, or `cardinality_spike`).
- `expected_sre_signals` names the SRE error types the operator should see.

### MongoDB target variants

The MongoDB targets intentionally model three different levels of realism:

| Target key | Source dashboard | Datasource under test | Why it exists |
|---|---|---|---|
| `mongodb` | `demo/mongodb_dashboard.json` | `prometheus-mongo` -> `mock-mongo-prometheus` | Small deterministic Mongo dashboard for fast end-to-end validation. |
| `mongodb_atlas` | `demo/mongodb_atlas_system_metrics_dashboard.json` | `prometheus-mongo-atlas` -> `mock-mongo-atlas-prometheus` | Atlas-style dashboard shape with imported-dashboard conventions and richer variable coverage. |
| `mongodb_live` | `demo/mongodb_live_dashboard.json` | `prometheus-mongo-live` -> `fault-proxy-mongo-live` -> `prometheus-mongo-live` service | Real local MongoDB/exporter/Prometheus path with safe response-level fault injection. |

The first two use isolated mock Prometheus services. They are intentionally synthetic because they make panel, variable, cardinality, staleness, and recovery behavior deterministic. They are the best targets for quick regression testing and demo reliability.

The live target uses real metrics:

```text
mongo-live
  -> mongodb-exporter
  -> prometheus-mongo-live
  -> fault-proxy-mongo-live
  -> Grafana target dashboard + probe-engine-mongo-live
```

The fault proxy is a Python FastAPI gateway that presents a Prometheus-compatible API. In the healthy path it forwards requests unchanged to `prometheus-mongo-live`. When a fault is active, it mutates only the matching Prometheus JSON response: empty result for `no_data`, old timestamps for `stale_data`, delayed response for `slow_query`, duplicated series for `cardinality_spike`, and so on. The `panel_query_http_500` fault is deliberately narrower: it returns plain-text HTTP 500 only for `POST /api/v1/query_range`, which is the Grafana-style panel path, while raw `GET /api/v1/query` remains healthy. This lets the demo reproduce user-visible dashboard failures without stopping MongoDB, the exporter, or Prometheus.

All three Mongo targets produce SRE data through the same contract:

```text
target dashboard JSON
  -> target-specific probe engine
  -> /metrics
  -> shared Prometheus (`probe-metrics`)
  -> generated SRE dashboard + alert rules
```

### `mock_backend/`

FastAPI app with two concerns:

**Prometheus API** (`prometheus_api.py`) — implements the subset of the Prometheus HTTP API used by the probe engine:
- `GET /api/v1/query` — instant query
- `POST /api/v1/query` — instant query for Grafana compatibility
- `GET`/`POST /api/v1/query_range` — range query
- `GET`/`POST /api/v1/label/{label}/values` — label values (for variable probes)
- `GET`/`POST /api/v1/series` — Grafana variable helper path
- `GET /-/healthy`
- `GET /faults/types` — fault type metadata (descriptions and expected behavior)

Fixtures generate synthetic time series (sinusoidal + noise) for the Service Health, MongoDB Operations, MongoDB Atlas System Metrics, and test-only live Mongo metric surfaces, including HTTP/service metrics, MongoDB exporter-style metrics, and Atlas-style metrics such as `mongodb_opcounters_query`.

**Fault injector** (`fault_injector.py`) — in-memory fault dict with auto-expiry. `FAULT_INFO` dict provides human-readable descriptions for each fault type, served via `GET /faults/types`. Each fault targets a metric name and applies one of:

| Fault type | Effect on Prometheus response |
|---|---|
| `no_data` | Returns empty result array |
| `stale_data` | Returns timestamps far in the past |
| `slow_query` | Sleeps 8s before responding |
| `metric_rename` | Returns zero series |
| `cardinality_spike` | Returns 10× the normal series count |
| `var_resolution_fail` | Returns empty label values and empty `/api/v1/series` results so Grafana `label_values(...)` dropdowns visibly lose their options |
| `variable_query_error` | Returns HTTP 500 for label values and `/api/v1/series` so Grafana variable refreshes surface a hard query error |
| `panel_query_http_500` | For proxy targets, returns plain-text HTTP 500 only on `POST /api/v1/query_range` |

### `fault_proxy/`

`fault_proxy.prometheus_proxy` is a Prometheus-compatible FastAPI proxy. It forwards `/api/v1/query`, `/api/v1/query_range`, `/api/v1/label/.../values`, `/api/v1/series`, and other Prometheus endpoints to an upstream Prometheus. When a fault is active, it mutates the returned Prometheus JSON rather than replacing the real datasource. `var_resolution_fail` empties `/api/v1/series`, and `variable_query_error` returns HTTP 500 from the same variable-discovery surfaces, because Grafana commonly resolves `label_values(metric, label)` by fetching matching series and extracting labels client-side. The `panel_query_http_500` fault is the regression guard for the layered probe model: raw instant queries stay green, Grafana panel range queries fail, and the SRE dashboard reports `grafana_panel_path`/`panel_error`.

The live Mongo path uses it as:

```
mongo-live -> mongodb-exporter -> prometheus-mongo-live -> fault-proxy-mongo-live -> Grafana/probe-engine-mongo-live
```

### `fault_controller/`

`fault_controller.api` is the only mutation API the browser calls. It loads `dashboard_targets.yaml`, validates `target_key` + `group_key`, and delegates enabled `mock`/`proxy` groups to their backend `/faults/*` APIs. Disabled `infra` groups return HTTP 409 with a stable `status=disabled` payload and do not touch Docker.

### `demo/simulator.html`

No-build UI made of `simulator.html` plus generated `dashboard_targets.js`. It works opened directly as a file or served from any static server.

Three sections:
- **Target dashboard** — selector for Service Health, MongoDB Operations, MongoDB Atlas System Metrics, or MongoDB Live Operations. The selection controls the probe health endpoint and available fault groups.
- **SRE view** — polls the selected `/health` every 5s. Shows health score, per-panel badges, per-variable badges, scrolling issue log.
- **Fault injection** — grouped Mock, API Proxy, and Infrastructure classes. Each button has an info icon ("i") that shows the fault origin separately from expected SRE detection (`affected_layers` and `expected_sre_signals`); descriptions are fetched from the controller.

---

## Data flow: fault detection

```
User clicks "No Data" in simulator
        │
        ▼
POST /faults/inject -> fault_controller validates target/group
        |
        v
mock_backend or fault_proxy stores fault (target=http_requests_total)
        │
        ▼ (up to 15s)
probe engine fires query_probe for "Request Rate" panel
        │
        └──→ GET /api/v1/query?query=rate(http_requests_total[5m])
             selected backend/proxy returns empty result (fault active)
        │
        ▼
QueryProbe returns ProbeResult(status=DEGRADED, error_type=NO_DATA)
        │
        ▼
engine updates dashboard_panel_status{panel_id="1", probe_type="no_data"} = 0
engine updates dashboard_health_score = 0.833 (5/6 panels healthy)
engine appends to issues log
        │
        ▼ (up to 5s)
simulator polls /health → panel badge turns red, health score updates
        │
Total worst-case: 15s probe interval + 5s UI poll = 20s  (within 30s budget)
```

For the panel-path regression, the flow is intentionally different:

```text
User injects panel_query_http_500 on mongodb_live
        |
        v
fault-proxy-mongo-live stores fault for mongodb_op_counters_total
        |
        +--> QueryProbe uses GET /api/v1/query and stays healthy
        |
        +--> GrafanaPanelPathProbe asks Grafana /api/ds/query
              Grafana's Prometheus datasource calls POST /api/v1/query_range
              fault proxy returns plain-text HTTP 500
        |
        v
engine reports datasource_api=healthy, grafana_panel_path=degraded, error_type=panel_error
```

---

## Configuration

`dashboard_targets.yaml` generates the demo probe config files. `config.yaml` (local) / `config.docker.yaml` (Docker) define the Service Health path. `config.mongo.docker.yaml` defines the isolated MongoDB Operations path. `config.mongo-atlas.docker.yaml` defines the isolated MongoDB Atlas System Metrics path. `config.mongo-live.docker.yaml` defines the live local MongoDB path through the faultable proxy:

```yaml
probe_interval_seconds: 15
thresholds:
  slow_query_seconds: 5.0
  slow_dashboard_seconds: 15.0
  stale_data_multiplier: 3.0    # fault if age > 3× expected scrape interval
  cardinality_spike_ratio: 1.5  # fault if series > 1.5× baseline
  query_timeout_seconds: 25.0
grafana:
  enabled: true                 # generated Docker configs; local defaults stay disabled
  url: "http://grafana:3000"
  query_range_seconds: 3600
  step_seconds: 30
  max_data_points: 1200
datasources:
  - uid: "prometheus-main"
    url: "http://localhost:9090"  # or http://mock-prometheus:9090 in Docker
    type: prometheus
```

The `grafana` block is disabled by default in local/unit fixtures so tests and one-off scripts can run without a Grafana process. Registry-generated Docker configs enable it with `http://grafana:3000`.

Environment variables consumed by `engine.py`:
- `CONFIG_PATH` — path to config YAML (default: `config.yaml`)
- `DASHBOARD_PATH` — path to dashboard JSON (default: `demo/example_dashboard.json`)

---

## Docker Compose topology

The current demo intentionally uses a registry plus isolated source-dashboard paths before generalizing to one multi-dashboard engine:

- Service Health: `mock-prometheus` -> `probe-engine` -> `dashboard_uid="service-health-01"`
- MongoDB Operations: `mock-mongo-prometheus` -> `probe-engine-mongo` -> `dashboard_uid="mongodb-ops-01"`
- MongoDB Atlas System Metrics: `mock-mongo-atlas-prometheus` -> `probe-engine-mongo-atlas` -> `dashboard_uid="mongodb-atlas-system-metrics"`
- MongoDB Live Operations: `mongo-live` -> `mongodb-exporter` -> `prometheus-mongo-live` -> `fault-proxy-mongo-live` -> `probe-engine-mongo-live` -> `dashboard_uid="mongodb-live-ops-01"`

All probe engines expose the same SRE metric names, scoped by `dashboard_uid`. The browser render probe exposes dashboard-level render metrics with the same `dashboard_uid` label. Real Prometheus scrapes every probe target, and Grafana uses those scraped metrics for all SRE dashboards.

```
┌──────────────────────────────────────────────┐
│  Host                                        │
│  :9090 ──→ mock-prometheus                   │
│  :8000 ──→ probe-engine                      │
│  :9093 ──→ mock-mongo-prometheus             │
│  :8002 ──→ probe-engine-mongo                │
│  :9095 ──→ mock-mongo-atlas-prometheus       │
│  :8004 ──→ probe-engine-mongo-atlas          │
│  :9091 ──→ prometheus (real)                 │
│  :3000 ──→ grafana                           │
│  :8080 ──→ demo-ui (nginx)                   │
│                                              │
│  ┌──────────────────────────────────────┐    │
│  │  dashmon_default network             │    │
│  │                                      │    │
│  │  mock-prometheus:9090                │    │
│  │         ▲              ▲             │    │
│  │         │ HTTP         │ datasource  │    │
│  │  probe-engine:8000     │             │    │
│  │         ▲              │             │    │
│  │         │ scrape /metrics            │    │
│  │  prometheus:9090───────│─────┐       │    │
│  │                        │     │       │    │
│  │                    grafana:3000      │    │
│  │                  (5 datasources,     │    │
│  │                   8 dashboards,      │    │
│  │                   4 alert groups)    │    │
│  │                                      │    │
│  │  demo-ui:80                          │    │
│  └──────────────────────────────────────┘    │
└──────────────────────────────────────────────┘
```

Services start in dependency order: mock backends and the live Mongo/exporter path become available, probe engines become healthy, real Prometheus starts scraping them, and then Grafana + `demo-ui` start.

Grafana connects to five datasources:
- **Mock Prometheus** (`prometheus-main`) — powers the target "Service Health" dashboard
- **MongoDB Mock Prometheus** (`prometheus-mongo`) — powers the target "MongoDB Operations" dashboard
- **MongoDB Atlas Mock Prometheus** (`prometheus-mongo-atlas`) — powers the target "MongoDB Atlas System Metrics" dashboard
- **MongoDB Live Proxy Prometheus** (`prometheus-mongo-live`) — powers the target "MongoDB Live Operations" dashboard through the faultable proxy
- **Probe Metrics** (`probe-metrics`) — real Prometheus scraping all probe engines; powers all SRE meta-dashboards

The browser polls probe health endpoints directly, but all fault mutations go through `fault-controller` on `localhost:8010`. These calls are not proxied through nginx.

---

## Adding a new datasource type

1. Add a new probe class in `probe/probes/` implementing `async def probe(spec, url, config) -> ProbeResult`.
2. Register it in `engine.py` alongside the existing probes.
3. Update `probe/parser.py` to emit specs for the new datasource type.
4. Add a mock backend handler in `mock_backend/` if needed for demo purposes.

No changes to `metrics.py`, `meta_dashboard.py`, or `alert_rules.py` are required.
