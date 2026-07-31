# Dashboard SRE — Claude Code Brief

Archived reference: this is the original product brief that guided the initial build.

It is useful for intent and scope, but it is not the living source of truth for the current repository state. For current behavior, use `README.md`, `ARCHITECTURE.md`, and the code/tests.

## Mission

Build a service that takes a Grafana dashboard JSON as input and produces:
1. A **probe engine** that actively monitors that specific dashboard's health
2. A **meta-dashboard** (Grafana JSON) — the "dashboard for the dashboard"
3. **Alert rules** (YAML) for each detectable failure mode

The key framing: we are NOT monitoring the Grafana stack (that's someone else's job). We are monitoring the **user experience of one specific dashboard** — detecting when a customer would open it and see something wrong, before they do.

The repo also ships a **self-contained demo** — this is a development and sales artifact, not a service output. It consists of a mock Prometheus backend with fault injection and a UI simulator that shows the service catching injected failures in real time. The demo exists once in the repo; it is not generated per dashboard.

---

## Problem taxonomy (what we detect)

These are the failures we must catch, ranked by stealth (most dangerous first):

| ID | Name | What the user sees | Detection method |
|----|------|--------------------|-----------------|
| `NO_DATA` | Blank panel | Panel shows "No data" or is empty | Execute the panel's PromQL; check if result set is empty |
| `STALE_DATA` | Frozen numbers | Values haven't changed in >2× scrape interval | Check max timestamp in query result vs `now()` |
| `METRIC_RENAME` | Silently missing metric | Panel shows blank; no error shown | Query returns 0 series despite no error |
| `QUERY_TIMEOUT` | Panel stuck loading / blank | Panel spinner or blank after timeout | Probe times out or returns HTTP 5xx/504 |
| `VAR_RESOLUTION_FAIL` | Broken dropdown | Variable dropdown is empty; all panels break | Execute variable's query; check for empty/error response |
| `SLOW_QUERY` | Slow panel load | Individual panel takes >N seconds | Measure per-query execution time |
| `SLOW_DASHBOARD` | Slow total load | Dashboard takes >N seconds end-to-end | Sum of all parallel query durations (critical path) |
| `CARDINALITY_SPIKE` | Wrong aggregated value | Number looks plausible but is wrong | Result series count > baseline by >50% |
| `PANEL_ERROR` | Red error badge | Panel shows exclamation mark | Datasource returns non-200 or error body |

---

## Architecture decisions (already made — do not re-litigate)

**Language:** Python 3.11+  
**Web framework:** FastAPI (for mock backends + probe metrics endpoint)  
**Frontend:** Single-file HTML/JS (no build step) for the UI simulator  
**Config:** YAML for probe configuration; JSON for dashboard input/output  
**Containerization:** Docker Compose (one command to run everything)  
**Metrics format:** Prometheus exposition format (probe engine exposes `/metrics`)  
**Alert format:** Grafana Alerting YAML (compatible with Grafana 9+ provisioning)

No external databases. No heavy frameworks. Everything must run locally with `docker compose up`.

---

## Project structure

```
dashboard-sre/
├── CLAUDE.md                    # Claude Code context (generate this)
├── ARCHITECTURE.md              # System design doc (generate this)
├── docker-compose.yml           # Wires everything together
│
├── probe/                       # Core probe engine
│   ├── engine.py                # Main probe loop
│   ├── parser.py                # Dashboard JSON → probe specs
│   ├── probes/
│   │   ├── query_probe.py       # Executes PromQL, checks empty/error/slow
│   │   ├── staleness_probe.py   # Checks data freshness
│   │   ├── variable_probe.py    # Executes variable queries
│   │   └── cardinality_probe.py # Checks series count drift
│   ├── metrics.py               # Prometheus metrics exposition
│   └── config.py                # Probe thresholds + config
│
├── generator/                   # Output generators
│   ├── meta_dashboard.py        # Generates meta-dashboard Grafana JSON
│   └── alert_rules.py           # Generates alert rules YAML
│
├── mock_backend/                # Fake Prometheus + Grafana APIs for demo
│   ├── prometheus_api.py        # FastAPI app mimicking Prometheus HTTP API
│   ├── grafana_api.py           # FastAPI app mimicking Grafana datasource API
│   ├── fault_injector.py        # State machine for fault injection
│   └── fixtures/
│       └── metrics.py           # Simulated metric time series
│
├── demo/
│   ├── simulator.html           # Self-contained UI simulator (single file)
│   └── example_dashboard.json   # The example "Service Health" dashboard
│
└── examples/
    ├── input_dashboard.json     # Example input dashboard
    ├── generated_meta_dashboard.json  # Example output
    └── generated_alert_rules.yaml    # Example output
```

---

## Component specs

### 1. Parser (`probe/parser.py`)

Input: Grafana dashboard JSON  
Output: A list of `ProbeSpec` objects

```python
@dataclass
class PanelProbeSpec:
    panel_id: int
    panel_title: str
    datasource_uid: str
    datasource_type: str  # "prometheus" | "loki" | etc.
    queries: list[str]    # raw PromQL / LogQL expressions
    expected_min_series: int  # baseline, 0 = unknown
    
@dataclass  
class VariableProbeSpec:
    name: str
    datasource_uid: str
    query: str
    is_chained: bool      # depends on another variable
    chain_depth: int      # how deep in the chain
```

The parser must handle:
- Template variable substitution — replace `$variable` with a sentinel value like `.*` for probing
- Multi-query panels (panel with multiple PromQL expressions)
- Mixed datasource dashboards (different panels hitting different datasources)
- Library panels (resolve them via the dashboard JSON if embedded)

### 2. Probe Engine (`probe/engine.py`)

Runs a configurable loop (default: every 30s) that:
1. For each `PanelProbeSpec`, executes all queries against the datasource
2. Records results as Prometheus metrics (see metrics spec below)
3. Exposes `/metrics` endpoint for scraping
4. Also exposes `/health` (JSON summary of last probe run) for the UI simulator to poll

The probe engine must handle concurrent probing (all panels probed in parallel, not sequentially).

**Probe config** (`config.yaml`):
```yaml
probe_interval_seconds: 30
thresholds:
  slow_query_seconds: 5.0
  slow_dashboard_seconds: 15.0
  stale_data_multiplier: 3.0   # stale if age > 3x scrape_interval
  cardinality_spike_ratio: 1.5  # alert if series count > 1.5x baseline
  query_timeout_seconds: 25.0
datasources:
  - uid: "prometheus-main"
    url: "http://mock-prometheus:9090"
    type: prometheus
```

### 3. Metrics exposition (`probe/metrics.py`)

Expose these Prometheus metrics from the probe engine:

```
# Panel-level metrics
dashboard_panel_status{dashboard_uid, panel_id, panel_title, probe_type}
  # 1 = healthy, 0 = degraded

dashboard_panel_query_duration_seconds{dashboard_uid, panel_id, panel_title}
  # histogram: query execution time

dashboard_panel_series_count{dashboard_uid, panel_id, panel_title}
  # gauge: number of time series returned

dashboard_panel_last_datapoint_age_seconds{dashboard_uid, panel_id, panel_title}
  # gauge: seconds since most recent data point

dashboard_panel_error_total{dashboard_uid, panel_id, panel_title, error_type}
  # counter: errors by type (no_data, timeout, http_error, stale)

# Variable-level metrics  
dashboard_variable_status{dashboard_uid, variable_name}
  # 1 = populated, 0 = empty/failed

dashboard_variable_query_duration_seconds{dashboard_uid, variable_name}
  # histogram

# Dashboard-level metrics
dashboard_health_score{dashboard_uid}
  # gauge: 0-1 fraction of panels currently healthy

dashboard_load_time_seconds{dashboard_uid}
  # gauge: estimated total load time (critical path of parallel queries)
```

### 4. Meta-dashboard generator (`generator/meta_dashboard.py`)

Takes the probe specs + dashboard metadata and generates a Grafana dashboard JSON.

**Required panels in the meta-dashboard:**

Row 1 — Overview
- `Health score` — stat panel, gauge 0–100%, green/red threshold at 100%
- `Active issues` — stat panel, count of currently failing probes
- `Estimated load time` — stat panel with threshold (green <5s, yellow <15s, red >15s)
- `Last probe run` — stat panel showing seconds since last successful probe

Row 2 — Panel health grid
- One stat panel per panel in the target dashboard
- Green = all probes passing, Red = any probe failing
- Click → drilldown shows which probe failed and why
- Use Grafana's repeat-by-variable feature to generate dynamically

Row 3 — Query performance
- Timeseries panel: `dashboard_panel_query_duration_seconds` p50/p95 per panel
- Heatmap: query duration distribution over time

Row 4 — Variable health
- Stat panels per variable showing status + last resolution time
- Timeseries: variable query duration over time

Row 5 — Issue log
- Table panel: last 20 state transitions (panel went red, variable failed, etc.)
- Derived from `dashboard_panel_error_total` increase events

Row 6 — Alerts
- Alert list panel filtered to this dashboard's alert rules

### 5. Alert rules generator (`generator/alert_rules.py`)

Generates a Grafana Alerting YAML with one alert rule per failure mode:

```yaml
# Example structure (generate this per dashboard)
apiVersion: 1
groups:
  - name: dashboard-sre-{dashboard_uid}
    rules:
      - uid: auto-gen-{dashboard_uid}-no-data-{panel_id}
        title: "[{dashboard_title}] Panel '{panel_title}' — No Data"
        condition: C
        data:
          - refId: A
            queryType: ''
            relativeTimeRange: {from: 300, to: 0}
            model:
              expr: dashboard_panel_status{dashboard_uid="{uid}", panel_id="{id}", probe_type="no_data"}
          - refId: C
            model:
              type: threshold
              conditions: [{evaluator: {params: [1], type: lt}}]
        noDataState: Alerting
        execErrState: Alerting
        for: 2m
        annotations:
          summary: "Panel '{{panel_title}}' in dashboard '{{dashboard_title}}' has no data"
          description: "This panel has been returning empty results for >2 minutes. The source metric may have disappeared or the exporter may be down."
        labels:
          severity: warning
          dashboard_uid: "{uid}"
          probe_type: no_data
```

Generate one rule per: `panel × failure_type`, plus dashboard-level rules for slow load and overall health score drop.

### 6. Mock backend (`mock_backend/`)

A FastAPI app that mimics the Prometheus HTTP API (`/api/v1/query`, `/api/v1/query_range`, `/api/v1/label_values`) with configurable fault injection.

**Fault injection API** (used by the UI simulator):
```
POST /faults/inject
Body: {
  "type": "no_data" | "stale_data" | "slow_query" | "var_resolution_fail" | "metric_rename" | "cardinality_spike",
  "target": "panel_id" | "variable_name" | "all",
  "duration_seconds": 60   # 0 = until cleared
}

POST /faults/clear
Body: {"target": "all" | specific_id}

GET /faults/active   # returns list of active faults
```

The mock backend must serve realistic Prometheus response shapes so the probe engine doesn't need special-casing. It should generate synthetic time series data (sinusoidal + noise) for the example dashboard metrics.

**Simulated metrics for the example dashboard:**
- `http_requests_total` (labels: method, status, service)
- `http_request_duration_seconds` (histogram)
- `process_resident_memory_bytes` (labels: pod, namespace)
- `kube_pod_status_ready` (labels: pod, namespace)
- `up` (labels: job, instance)

---

## Demo — Example dashboard + UI simulator

### Example dashboard (`demo/example_dashboard.json`)

A "Service Health" dashboard with these panels:

1. **Request rate** — `rate(http_requests_total[5m])` — timeseries
2. **Error rate %** — `rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m])` — stat with threshold
3. **P99 latency** — `histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))` — gauge
4. **Memory usage** — `process_resident_memory_bytes` — timeseries
5. **Pod readiness** — `kube_pod_status_ready` — table
6. **Active instances** (variable-driven) — uses template var `$pod` populated from `label_values(up, instance)`

Template variables:
- `$pod` — query: `label_values(up, instance)` — dropdown
- `$namespace` — query: `label_values(kube_pod_status_ready, namespace)` — dropdown, chained on `$pod`

### UI Simulator (`demo/simulator.html`)

A **single self-contained HTML file** (no external dependencies beyond a CDN fetch for a charting lib) that:

**Layout:**
```
┌─────────────────────────────────────────────────────┐
│  [Target Dashboard — Service Health]   [live badge] │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐            │
│  │ Req rate │ │ Err rate │ │ P99 lat  │            │
│  └──────────┘ └──────────┘ └──────────┘            │
│  ┌──────────────────┐ ┌──────────────────┐          │
│  │ Memory           │ │ Pod readiness    │          │
│  └──────────────────┘ └──────────────────┘          │
├─────────────────────────────────────────────────────┤
│  [Meta-dashboard — SRE View]                        │
│  Health: 100% ● 0 issues ● Load: 2.1s              │
│  [Panel 1 ✓] [Panel 2 ✓] [Panel 3 ✓] [Panel 4 ✓] │
│  [Panel 5 ✓] [Var: $pod ✓] [Var: $namespace ✓]    │
├─────────────────────────────────────────────────────┤
│  [Inject fault]                                     │
│  [No Data] [Stale] [Slow Query] [Var Fail]         │
│  [Metric Rename] [Cardinality Spike] [Clear All]   │
│                                                     │
│  Issue log: ────────────────────────────────────── │
│  13:42:01  Panel "Error rate" → NO_DATA detected   │
│  13:42:31  Alert: [Dashboard] Panel 'Error...' ...  │
└─────────────────────────────────────────────────────┘
```

**Behavior:**
- Top section: simplified target dashboard. Panels show live synthetic data (animated sparklines). When a fault is injected, the affected panel visually degrades (goes blank, shows error badge, shows frozen timestamp).
- Middle section: meta-dashboard. Polls `GET /health` on the probe engine every 5s. Updates health score, panel status badges, issue count in real time. When a panel goes red, show which probe triggered and why.
- Bottom section: fault injection buttons. Each button calls `POST /faults/inject` on the mock backend. Probe engine detects the injected fault within one probe interval (≤30s). Issue log streams events as they are detected.
- **The probe engine must visibly catch each injected fault** — this is the demo's core value proposition.

**Timing expectation:**
- Fault injected → probe detects → meta-dashboard updates: ≤30 seconds
- Clear all faults → meta-dashboard goes back to all-green: ≤30 seconds

The simulator must work without any external authentication. All calls go to `localhost`.

---

## Deliverables checklist

Claude Code must produce all of the following:

- [ ] `CLAUDE.md` — context file for future sessions
- [ ] `ARCHITECTURE.md` — system design with component interactions
- [ ] `docker-compose.yml` — all services, one-command startup
- [ ] `probe/` — complete, runnable probe engine
- [ ] `mock_backend/` — complete FastAPI mock with fault injection
- [ ] `generator/` — meta-dashboard + alert rules generators
- [ ] `demo/simulator.html` — self-contained UI simulator
- [ ] `demo/example_dashboard.json` — the example target dashboard
- [ ] `examples/` — pre-generated sample outputs
- [ ] `README.md` — setup, run, and usage instructions

---

## Quality constraints

- **No real Grafana required** — the demo runs entirely against mock backends
- **Probe engine is datasource-agnostic** — it speaks the Prometheus HTTP API; other datasource types are out of scope for now but the architecture should allow adding them
- **The meta-dashboard JSON must be importable** into a real Grafana instance (not just theoretical)
- **Alert rules YAML must be valid** Grafana Alerting provisioning format
- **The UI simulator must work in a modern browser** with no build step
- **Docker Compose must work on Mac and Linux** with no platform-specific hacks
- **Probe engine must handle errors gracefully** — if one panel probe fails, others continue; engine never crashes

---

## What success looks like

A developer can:
1. Run `docker compose up`
2. Open `http://localhost:8080` — see the UI simulator
3. Click "No Data" — within 30s the meta-dashboard shows a red panel and a new alert
4. Click "Clear All" — within 30s everything goes green
5. Take `demo/example_dashboard.json`, import it into a real Grafana, point the probe engine at real Prometheus, and have a real meta-dashboard watching it

---

## Start here

Implement in this order. Do not write `ARCHITECTURE.md` or `CLAUDE.md` upfront — they document reality, not intent, so they are written last.

1. `mock_backend/` — no dependencies, everything else tests against this. Get the Prometheus API mock and fault injection endpoints working first.
2. `probe/parser.py` — parse a hardcoded example dashboard JSON into probe specs. Validate against the mock backend.
3. `probe/probes/query_probe.py` — single probe type first, end-to-end: parser → probe → metric emitted.
4. `probe/engine.py` + `probe/metrics.py` — probe loop + `/metrics` exposition. At this point the core detection pipeline is complete.
5. Remaining probes — `staleness_probe.py`, `variable_probe.py`, `cardinality_probe.py`. Each one should be testable in isolation against the mock backend's fault injection.
6. `generator/meta_dashboard.py` + `generator/alert_rules.py` — generate outputs from real probe specs, not hypothetical ones.
7. `demo/simulator.html` — build against the now-real probe engine `/health` endpoint and mock backend fault API.
8. `docker-compose.yml` + `README.md` — wire everything, verify one-command startup.
9. `examples/` — run the generators on the example dashboard and commit the real outputs.
10. `ARCHITECTURE.md` — now document what was actually built: component interactions, data flow, key decisions made during implementation.
11. `CLAUDE.md` — context for future sessions: what the project is, where things live, what's intentionally out of scope.

Do not skip the example outputs in `examples/` — they are the fastest way to validate the generators produce valid JSON/YAML.
