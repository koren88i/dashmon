# Architecture

Dashboard SRE monitors the **user experience** of a Grafana dashboard — detecting what a user would see when opening it: blank panels, stale data, slow loads, broken variables. It does not monitor the Grafana stack itself.

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
        │       ├──→ query_probe.py       NO_DATA, QUERY_TIMEOUT, SLOW_QUERY, PANEL_ERROR
        │       ├──→ staleness_probe.py   STALE_DATA
        │       ├──→ variable_probe.py    VAR_RESOLUTION_FAIL
        │       └──→ cardinality_probe.py CARDINALITY_SPIKE, METRIC_RENAME
        │       │
        │       └──→ metrics.py ──→ /metrics (Prometheus exposition)
        │                      ──→ /health  (JSON summary for UI)
        │
        ├──→ generator/meta_dashboard.py ──→ Grafana dashboard JSON (importable)
        └──→ generator/alert_rules.py    ──→ Grafana alerting YAML (provisionable)

mock_backend/
        └──→ prometheus_api.py  (Prometheus HTTP API shape)
        └──→ fault_injector.py  (in-memory fault state, auto-expiry)

demo/
        └──→ simulator.html     (self-contained UI, no build step)
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
2. Each panel's worst-case status across all probe types wins (e.g. if query is healthy but staleness is degraded, the panel is degraded).
3. Results update Prometheus metrics and the in-memory issue log.
4. Loop sleeps for `probe_interval_seconds` (default 15s) then repeats.

Endpoints:
- `GET /metrics` — Prometheus exposition format, scraped by Prometheus.
- `GET /health` — JSON summary: health score, per-panel statuses, per-variable statuses, recent issues. Polled by the demo UI every 5s.

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
| `dashboard_variable_query_duration_seconds` | Histogram | Variable label query round-trip time |
| `dashboard_issue_count` | Gauge | Number of currently degraded panels and variables |
| `dashboard_issue_event_timestamp_seconds` | Gauge | Unix timestamp in seconds for recent issue state transitions |

### Probe types

| Probe | File | Failure modes |
|---|---|---|
| Query | `query_probe.py` | `NO_DATA` — empty result set; `QUERY_TIMEOUT` — request exceeded timeout; `SLOW_QUERY` — response exceeded slow threshold; `PANEL_ERROR` — HTTP error from datasource |
| Staleness | `staleness_probe.py` | `STALE_DATA` — most recent datapoint timestamp is older than `stale_data_multiplier × scrape_interval` |
| Variable | `variable_probe.py` | `VAR_RESOLUTION_FAIL` — label values query returns zero results |
| Cardinality | `cardinality_probe.py` | `CARDINALITY_SPIKE` — series count exceeds baseline × `cardinality_spike_ratio`; `METRIC_RENAME` — series count dropped to zero after previously being non-zero |

Engine-level detection:
- `SLOW_DASHBOARD` — max panel query duration exceeds `slow_dashboard_seconds` threshold.

### `generator/meta_dashboard.py`

Generates a Grafana dashboard JSON for the meta-dashboard. The output has six rows:

1. **Overview** — health score, active issue count, estimated load time, time since last probe.
2. **Panel health grid** — one stat panel per target panel, green/red.
3. **Query performance** — p50/p95 timeseries + heatmap.
4. **Variable health** — per-variable status badges + query duration timeseries.
5. **Issue log** — table of recent error increments.
6. **Alerts** — alertlist panel filtered to this dashboard's rules.

The output is importable into any Grafana instance pointed at a Prometheus that scrapes the probe engine's `/metrics`.

Meta-dashboard panels use a datasource variable named `sre_datasource`, defaulting to the `probe-metrics` datasource. Avoid the generic `datasource` variable name here because source-dashboard URLs can carry stale `var-datasource=...` overrides into SRE dashboards.

The **Recent Issue Events** table treats the metric sample value as the event time. `dashboard_issue_event_timestamp_seconds` is emitted in Unix seconds, so the Grafana panel query multiplies it by `1000` before applying the `dateTimeAsIso` field override to `Event Time`. The table hides Grafana's instant-query `Time` field because that is the query evaluation time and will be identical for all rows in a refresh.

### `generator/alert_rules.py`

Generates Grafana Alerting provisioning YAML. Rule count: `panels × 6 probe types + variables + 2 dashboard-level rules`. For 6 panels and 2 variables: 40 rules total.

Each rule fires after 2 minutes of continuous degradation (`for: 2m`) to suppress transient blips.

### `mock_backend/`

FastAPI app with two concerns:

**Prometheus API** (`prometheus_api.py`) — implements the subset of the Prometheus HTTP API used by the probe engine:
- `GET /api/v1/query` — instant query
- `GET /api/v1/query_range` — range query
- `GET /api/v1/label/{label}/values` — label values (for variable probes)
- `GET /-/healthy`
- `GET /faults/types` — fault type metadata (descriptions and expected behavior)

Fixtures generate synthetic time series (sinusoidal + noise) for the Service Health and MongoDB Operations demo dashboards, including HTTP/service metrics and MongoDB exporter-style metrics such as `mongodb_up`, `mongodb_op_counters_total`, and `mongodb_mongod_replset_member_health`.

**Fault injector** (`fault_injector.py`) — in-memory fault dict with auto-expiry. `FAULT_INFO` dict provides human-readable descriptions for each fault type, served via `GET /faults/types`. Each fault targets a metric name and applies one of:

| Fault type | Effect on Prometheus response |
|---|---|
| `no_data` | Returns empty result array |
| `stale_data` | Returns timestamps far in the past |
| `slow_query` | Sleeps 8s before responding |
| `metric_rename` | Returns zero series |
| `cardinality_spike` | Returns 10× the normal series count |
| `var_resolution_fail` | Returns empty label values |

### `demo/simulator.html`

Single self-contained HTML file. No build step, works opened directly as a file or served from any static server.

Three sections:
- **Target dashboard** — selector for Service Health or MongoDB Operations. The selection controls the probe health endpoint and mock fault backend.
- **SRE view** — polls the selected `/health` every 5s. Shows health score, per-panel badges, per-variable badges, scrolling issue log.
- **Fault injection** — one button per selected-dashboard fault type + "Clear All". Each button has an info icon ("i") that shows a tooltip explaining the fault and what to expect; descriptions are fetched from `GET /faults/types`.

---

## Data flow: fault detection

```
User clicks "No Data" in simulator
        │
        ▼
POST /faults/inject → mock_backend stores fault (target=http_requests_total)
        │
        ▼ (up to 15s)
probe engine fires query_probe for "Request Rate" panel
        │
        └──→ GET /api/v1/query?query=rate(http_requests_total[5m])
             mock_backend returns empty result (fault active)
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

---

## Configuration

`config.yaml` (local) / `config.docker.yaml` (Docker) define the Service Health path. `config.mongo.docker.yaml` defines the isolated MongoDB Operations path:

```yaml
probe_interval_seconds: 15
thresholds:
  slow_query_seconds: 5.0
  slow_dashboard_seconds: 15.0
  stale_data_multiplier: 3.0    # fault if age > 3× expected scrape interval
  cardinality_spike_ratio: 1.5  # fault if series > 1.5× baseline
  query_timeout_seconds: 25.0
datasources:
  - uid: "prometheus-main"
    url: "http://localhost:9090"  # or http://mock-prometheus:9090 in Docker
    type: prometheus
```

Environment variables consumed by `engine.py`:
- `CONFIG_PATH` — path to config YAML (default: `config.yaml`)
- `DASHBOARD_PATH` — path to dashboard JSON (default: `demo/example_dashboard.json`)

---

## Docker Compose topology

The current demo intentionally uses two isolated source-dashboard paths before generalizing to one multi-dashboard engine:

- Service Health: `mock-prometheus` -> `probe-engine` -> `dashboard_uid="service-health-01"`
- MongoDB Operations: `mock-mongo-prometheus` -> `probe-engine-mongo` -> `dashboard_uid="mongodb-ops-01"`

Both probe engines expose the same metric names, scoped by `dashboard_uid`. Real Prometheus scrapes both targets, and Grafana uses those scraped metrics for both SRE dashboards.

```
┌──────────────────────────────────────────────┐
│  Host                                        │
│  :9090 ──→ mock-prometheus                   │
│  :8000 ──→ probe-engine                      │
│  :9093 ──→ mock-mongo-prometheus             │
│  :8002 ──→ probe-engine-mongo                │
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
│  │                  (3 datasources,     │    │
│  │                   4 dashboards,      │    │
│  │                   2 alert groups)    │    │
│  │                                      │    │
│  │  demo-ui:80                          │    │
│  └──────────────────────────────────────┘    │
└──────────────────────────────────────────────┘
```

Services start in dependency order: the two mock Prometheus backends become healthy, the two probe engines become healthy, real Prometheus starts scraping both, and then Grafana + `demo-ui` start.

Grafana connects to three datasources:
- **Mock Prometheus** (`prometheus-main`) — powers the target "Service Health" dashboard
- **MongoDB Mock Prometheus** (`prometheus-mongo`) — powers the target "MongoDB Operations" dashboard
- **Probe Metrics** (`probe-metrics`) — real Prometheus scraping both probe engines; powers both SRE meta-dashboards

The browser talks directly to `localhost:9090`/`localhost:8000` for Service Health and `localhost:9093`/`localhost:8002` for MongoDB Operations. These calls are not proxied through nginx.

---

## Adding a new datasource type

1. Add a new probe class in `probe/probes/` implementing `async def probe(spec, url, config) -> ProbeResult`.
2. Register it in `engine.py` alongside the existing probes.
3. Update `probe/parser.py` to emit specs for the new datasource type.
4. Add a mock backend handler in `mock_backend/` if needed for demo purposes.

No changes to `metrics.py`, `meta_dashboard.py`, or `alert_rules.py` are required.
