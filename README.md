# Dashboard SRE

Monitor the user experience of a Grafana dashboard. Given a dashboard JSON, this service:

1. **Probe engine** — actively checks every panel for NO_DATA, STALE_DATA, SLOW_QUERY, PANEL_ERROR, VAR_RESOLUTION_FAIL, CARDINALITY_SPIKE, and more.
2. **Meta-dashboard** — a Grafana JSON you can import to see the health of your dashboard at a glance.
3. **Alert rules** — Grafana Alerting YAML you can provision directly.

---

## Documentation

Use these docs as the current source of truth:

- `README.md` — setup, demo flow, and day-to-day usage
- `ARCHITECTURE.md` — system design and data flow
- `CLAUDE.md` — repository workflow guidance for coding agents

These files are kept only as historical context:

- `DASHBOARD_SRE_BRIEF.md` — original product brief

If an archival doc disagrees with the code or the active docs, trust the code and the active docs.

---

## Quick start

```bash
docker compose up --build
```

Then open **http://localhost:8080/simulator.html** in your browser.

| Service | URL | Purpose |
|---|---|---|
| **Grafana** | http://localhost:3000 | Real Grafana with provisioned dashboards + alerts |
| Demo UI | http://localhost:8080/simulator.html | Dashboard selector + fault injection |
| Service probe engine | http://localhost:8000/health | Service Health JSON health summary |
| MongoDB probe engine | http://localhost:8002/health | MongoDB Operations JSON health summary |
| Service mock Prometheus | http://localhost:9090/-/healthy | Service metric backend + scoped fault state |
| MongoDB mock Prometheus | http://localhost:9093/-/healthy | MongoDB metric backend + scoped fault state |
| Prometheus | http://localhost:9091 | Real Prometheus scraping both probe engines |

---

## Demo walkthrough

The demo UI has three sections:

- **Target dashboard** - choose Service Health or MongoDB Operations. The selector switches both the SRE health endpoint and the fault backend.
- **SRE view** — polls the selected probe engine every 5s. Shows health score, canonical issue count, per-panel badges, variable badges, and a scrolling issue log.
- **Fault injection** — buttons to inject each failure mode, each with an info icon ("i") explaining the fault and expected behavior. The selected probe engine detects faults within ~20s.

**Try it:**
1. Click a fault button (e.g. "No Data").
2. Watch the SRE health score drop within 30s.
3. Open the selected source dashboard in Grafana to inspect the real Grafana dashboard degradation.
4. Click "Clear All" — everything returns to green within 30s.

### Grafana (real dashboards)

Open **http://localhost:3000** (no login required). Four dashboards are pre-provisioned:

- **Service Health** — the real Grafana dashboard with live panels powered by the mock Prometheus
- **[SRE] Service Health** — the meta-dashboard showing probe results from real Prometheus
- **MongoDB Operations** — a MongoDB operational dashboard powered by an isolated mock Prometheus
- **[SRE] MongoDB Operations** — the meta-dashboard generated from the MongoDB source dashboard

Each source dashboard has its own 40-rule alert group. Inject a fault in the simulator, then check the selected meta-dashboard and Alerting page in Grafana to see the matching rules fire.

---

## Fault injection via curl

```bash
# Inject a fault
curl -s -X POST http://localhost:9090/faults/inject \
  -H "Content-Type: application/json" \
  -d '{"type":"no_data","target":"http_requests_total","duration_seconds":60}'

# Check active faults
curl -s http://localhost:9090/faults/active

# List fault types with descriptions
curl -s http://localhost:9090/faults/types

# Clear all faults
curl -s -X POST http://localhost:9090/faults/clear \
  -H "Content-Type: application/json" \
  -d '{"target":"all"}'

# MongoDB path: same API, isolated backend
curl -s -X POST http://localhost:9093/faults/inject \
  -H "Content-Type: application/json" \
  -d '{"type":"no_data","target":"mongodb_op_counters_total","duration_seconds":60}'
```

Supported fault types: `no_data`, `stale_data`, `slow_query`, `metric_rename`, `cardinality_spike`, `var_resolution_fail`.

Notes on demo behavior:
- `metric_rename` currently surfaces as `no_data` in `/health` and probe metrics because both conditions produce the same empty Prometheus result in this demo stack.
- The demo UI is SRE/fault-injection only. Use Grafana **Service Health** or **MongoDB Operations** for the real dashboard experience.

---

## Running without Docker (development)

**Terminal 1 — mock backend:**
```bash
cd mock_backend
pip install -r requirements.txt
uvicorn prometheus_api:app --port 9090
```

**Terminal 2 — probe engine:**
```bash
pip install -r probe/requirements.txt
DASHBOARD_PATH=demo/example_dashboard.json uvicorn probe.engine:app --port 8000
```

**Browser:** open `demo/simulator.html` directly as a file, or serve it:
```bash
python -m http.server 8080 --directory demo
```

---

## Port overrides

Copy `.env.example` to `.env` and edit:

```bash
MOCK_BACKEND_PORT=9090
MOCK_MONGO_PORT=9093
PROBE_ENGINE_PORT=8000
PROBE_ENGINE_MONGO_PORT=8002
SIMULATOR_PORT=8080
```

---

## Generating outputs for your own dashboard

```python
import json
from probe.parser import parse_dashboard
from generator.meta_dashboard import generate_meta_dashboard
from generator.alert_rules import generate_alert_rules

with open("your_dashboard.json") as f:
    dashboard = json.load(f)

panels, variables = parse_dashboard(dashboard)
meta = generate_meta_dashboard(dashboard, panels, variables)
alerts = generate_alert_rules(dashboard, panels, variables)

with open("meta_dashboard.json", "w") as f:
    json.dump(meta, f, indent=2)

import yaml
with open("alert_rules.yaml", "w") as f:
    yaml.dump(alerts, f)
```

Import `meta_dashboard.json` into Grafana via **Dashboards → Import**.
Place `alert_rules.yaml` in your Grafana provisioning directory (`/etc/grafana/provisioning/alerting/`).

---

## Architecture

```
Grafana Dashboard JSON
        │
        ▼
   parser.py ──→ PanelProbeSpec / VariableProbeSpec
        │
        ├──→ engine.py  (probe loop, 15s interval, concurrent)
        │       ├──→ query_probe.py      NO_DATA, QUERY_TIMEOUT, SLOW_QUERY, PANEL_ERROR
        │       ├──→ staleness_probe.py  STALE_DATA
        │       ├──→ variable_probe.py   VAR_RESOLUTION_FAIL
        │       └──→ cardinality_probe.py CARDINALITY_SPIKE, METRIC_RENAME
        │       └──→ metrics.py  →  /metrics (Prometheus) + /health (JSON)
        │
        ├──→ generator/meta_dashboard.py  →  Grafana dashboard JSON
        └──→ generator/alert_rules.py     →  Grafana alerting YAML
```

**mock_backend/** — FastAPI app mimicking the Prometheus HTTP API with fault injection. The probe engine talks to it exactly as it would a real Prometheus instance.
