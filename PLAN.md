# Dashboard SRE — Implementation Plan

## Context
Building a service that monitors the user experience of Grafana dashboards. The repo is empty. The brief (`DASHBOARD_SRE_BRIEF.md`) defines the full spec. This plan follows the brief's implementation order exactly, with each step independently testable via curl or browser.

**Key design decision:** No throwaway verify.html. Steps 1–6 verify via curl commands. Step 7 introduces `simulator.html` as the permanent visual verification UI.

---

## Step 1: Mock Backend (`mock_backend/`)

### 1A: Mock Prometheus API
**Files:** `mock_backend/__init__.py`, `mock_backend/requirements.txt`, `mock_backend/fixtures/__init__.py`, `mock_backend/fixtures/metrics.py`, `mock_backend/prometheus_api.py`

- FastAPI app mimicking Prometheus HTTP API (`/api/v1/query`, `/api/v1/query_range`, `/api/v1/label/{label}/values`, `/-/healthy`)
- Fixtures generate synthetic time series (sinusoidal + noise) for 5 metric families
- Extract base metric name from PromQL via regex (not a real parser)

**Verify:**
```bash
cd mock_backend && pip install -r requirements.txt && uvicorn prometheus_api:app --port 9090 &
curl -s "http://localhost:9090/api/v1/query?query=up" | python -m json.tool
# EXPECT: {"status":"success","data":{"resultType":"vector","result":[<non-empty>]}}
curl -s "http://localhost:9090/api/v1/label/__name__/values" | python -m json.tool
# EXPECT: list of metric names
```

### 1B: Fault Injection
**Files:** `mock_backend/fault_injector.py` (+ modify `prometheus_api.py`)

- `FaultInjector` class: in-memory dict, auto-expiry
- Endpoints: `POST /faults/inject`, `POST /faults/clear`, `GET /faults/active`
- Fault effects: no_data→empty result, stale_data→old timestamps, slow_query→sleep(8s), metric_rename→0 series, cardinality_spike→10x series, var_resolution_fail→empty label values

**Verify:**
```bash
curl -s -X POST http://localhost:9090/faults/inject -H "Content-Type: application/json" \
  -d '{"type":"no_data","target":"http_requests_total","duration_seconds":60}'
curl -s "http://localhost:9090/api/v1/query?query=http_requests_total"
# EXPECT: empty result array
curl -s -X POST http://localhost:9090/faults/clear -H "Content-Type: application/json" -d '{"target":"all"}'
```

### 1C: Grafana API stub
**Files:** `mock_backend/grafana_api.py` (placeholder only)

---

## Step 2: Parser + Example Dashboard

### 2A: Example Dashboard
**Files:** `demo/example_dashboard.json`

- Valid Grafana JSON, 6 panels, 2 template variables ($pod, $namespace with chaining)

### 2B: Parser
**Files:** `probe/__init__.py`, `probe/config.py`, `probe/parser.py`, `config.yaml`

- `parse_dashboard(json) → (list[PanelProbeSpec], list[VariableProbeSpec])`
- Replace `$variable` with `.*`, detect chaining

**Verify:**
```bash
python -c "
import json; from probe.parser import parse_dashboard
with open('demo/example_dashboard.json') as f: dash = json.load(f)
p, v = parse_dashboard(dash)
print(f'{len(p)} panels, {len(v)} variables')
for x in p: print(f'  Panel {x.panel_id}: {x.panel_title}')
for x in v: print(f'  Var {x.name}: chained={x.is_chained}')
"
# EXPECT: 6 panels, 2 variables
```

---

## Step 3: Query Probe
**Files:** `probe/probes/__init__.py`, `probe/probes/query_probe.py`, `probe/requirements.txt`

- `QueryProbe.probe(spec, url, config) → ProbeResult`
- Detects: NO_DATA, QUERY_TIMEOUT, SLOW_QUERY, PANEL_ERROR

**Verify:**
```bash
# With mock backend running:
python -c "
import asyncio; from probe.probes.query_probe import QueryProbe; from probe.config import *
spec = PanelProbeSpec(1,'Request rate','prometheus-main','prometheus',['rate(http_requests_total[5m])'],1)
r = asyncio.run(QueryProbe().probe(spec, 'http://localhost:9090', ProbeConfig.defaults()))
print(f'{r.status}, error={r.error_type}, series={r.series_count}')
"
# EXPECT: healthy, error=None, series>0

# Inject fault, re-run → EXPECT: degraded, error=no_data
```

---

## Step 4: Engine + Metrics

### 4A: Metrics Module
**Files:** `probe/metrics.py`

- All Prometheus metrics from the brief spec
- Uses `prometheus_client` library

### 4B: Engine Loop
**Files:** `probe/engine.py` (FastAPI app)

- Loads config + dashboard, runs parser, probes concurrently every 30s
- `GET /metrics` (Prometheus format), `GET /health` (JSON summary with issues log)

**Verify (core pipeline — most important):**
```bash
# Terminal 1: uvicorn mock_backend... --port 9090
# Terminal 2: DASHBOARD_PATH=demo/example_dashboard.json uvicorn probe.engine:app --port 8000
# Wait 35s, then:
curl -s http://localhost:8000/health | python -m json.tool
# EXPECT: health_score=1.0, all panels healthy

# Inject fault, wait 35s, check /health again → panel degraded
# Clear, wait 35s → all green again
```

---

## Step 5: Remaining Probes

### 5A: Staleness Probe (`probe/probes/staleness_probe.py`)
- Checks max timestamp vs now(). Fault: stale_data

### 5B: Variable Probe (`probe/probes/variable_probe.py`)
- Checks label_values query returns results. Fault: var_resolution_fail

### 5C: Cardinality Probe (`probe/probes/cardinality_probe.py`)
- Counts series vs baseline. Faults: cardinality_spike, metric_rename

### 5D: Integration — register all probes, add SLOW_DASHBOARD detection

**Verify (full matrix):**
```bash
for fault in no_data stale_data slow_query var_resolution_fail metric_rename cardinality_spike; do
  curl -s -X POST localhost:9090/faults/inject -H "Content-Type: application/json" \
    -d "{\"type\":\"$fault\",\"target\":\"http_requests_total\",\"duration_seconds\":50}"
  sleep 35
  curl -s localhost:8000/health | python -c "import sys,json; h=json.load(sys.stdin); print(f'{\"$fault\"}: score={h[\"health_score\"]}')"
  curl -s -X POST localhost:9090/faults/clear -H "Content-Type: application/json" -d '{"target":"all"}'
  sleep 35
done
```

---

## Step 6: Generators

### 6A: Meta-Dashboard (`generator/meta_dashboard.py`)
- `generate_meta_dashboard(dash, panels, vars) → dict` (importable Grafana JSON)
- 6 rows per brief: overview, panel grid, query performance, variable health, issue log, alerts

### 6B: Alert Rules (`generator/alert_rules.py`)
- `generate_alert_rules(dash, panels, vars) → dict` (Grafana Alerting YAML)
- One rule per panel×failure_type + dashboard-level rules. Expect ≥20 rules.

**Verify:**
```bash
python -c "import json; json.load(open('examples/generated_meta_dashboard.json')); print('Valid JSON')"
python -c "import yaml; yaml.safe_load(open('examples/generated_alert_rules.yaml')); print('Valid YAML')"
```

---

## Step 7: Demo UI Simulator (`demo/simulator.html`)

Single self-contained HTML file (Chart.js from CDN). Three sections:
- **Top:** Target dashboard panels with sparklines, visual degradation on fault
- **Middle:** SRE view polling `/health` every 5s — health score, panel badges, variable badges
- **Bottom:** Fault injection buttons + scrolling issue log

**Verify (manual checklist):**
- All 6 panels show live data
- Click each fault button → panel degrades visually within 30s
- Meta-dashboard updates within 30s (red badge, health drops)
- Issue log shows timestamped entries
- "Clear All" → everything green within 30s

---

## Step 8: Docker Compose + README

**Files:** `mock_backend/Dockerfile`, `Dockerfile.probe`, `docker-compose.yml`, `README.md`

Three services: mock-prometheus (:9090), probe-engine (:8000), demo-ui (:8080)

**Verify:**
```bash
docker compose up --build -d
curl -s http://localhost:9090/-/healthy       # 200
curl -s http://localhost:8000/health          # valid JSON
curl -s http://localhost:8080/simulator.html  # 200
# Open browser, run fault injection demo
```

---

## Step 9: Example Outputs
Run generators, save to `examples/`. Validate JSON + YAML.

## Step 10: ARCHITECTURE.md
Document the system as built.

## Step 11: Update CLAUDE.md
Final commands, ports, gotchas.

---

## Risk mitigations
- **Demo timing:** Use 15s probe interval + 5s UI poll = worst-case ~20s detection (well within 30s)
- **Mock query matching:** Simple regex to extract metric name from PromQL — 5 lines, not a parser
- **Docker networking:** Browser uses `localhost:PORT`, probe engine uses `mock-prometheus:9090` (Docker DNS)
- **Grafana JSON validity:** Use real export structure as template, validate schemaVersion + panel ID uniqueness
