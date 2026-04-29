# Dashboard SRE

Monitor the user experience of a Grafana dashboard. Given a dashboard JSON, this service:

1. **Probe engine** — actively checks every panel for NO_DATA, STALE_DATA, SLOW_QUERY, PANEL_ERROR, VAR_RESOLUTION_FAIL, CARDINALITY_SPIKE, and more.
2. **Meta-dashboard** — a Grafana JSON you can import to see the health of your dashboard at a glance.
3. **Alert rules** — Grafana Alerting YAML you can provision directly.

---

## Quick start

```bash
docker compose up --build
```

Then open **http://localhost:8080/simulator.html** in your browser.

| Service | URL | Purpose |
|---|---|---|
| Demo UI | http://localhost:8080/simulator.html | Visual simulator + fault injection |
| Probe engine | http://localhost:8000/health | JSON health summary |
| Probe metrics | http://localhost:8000/metrics | Prometheus exposition |
| Mock Prometheus | http://localhost:9090/-/healthy | Mock backend status |

---

## Static demo

The screenshots below show the end-to-end flow: a real Grafana source dashboard, the generated SRE dashboard for that dashboard, and the simulator used to inject faults and inspect the resulting diagnosis.

### Source dashboard in Grafana

![MongoDB Live source dashboard](readme/mongo-live.jpg)

### Generated SRE dashboard in Grafana

![MongoDB Live SRE dashboard](readme/mongo-live-SRE.jpg)

### Simulator with fault injection and issue log

![Dashboard SRE simulator](readme/fault_simulator.jpg)

---

## Demo walkthrough

The simulator has three sections:

- **Target dashboard** — live sparklines for each panel. Degrades visually when a fault is active.
- **SRE view** — polls `/health` every 5s. Shows health score, per-panel badges, variable badges, and a scrolling issue log.
- **Fault injection** — buttons to inject each failure mode, each with an info icon ("i") explaining the fault and expected behavior. The probe engine detects faults within ~20s.

**Try it:**
1. Click a fault button (e.g. "No Data").
2. Watch the panel go red and the health score drop within 30s.
3. Click "Clear All" — everything returns to green within 30s.

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
```

Supported fault types: `no_data`, `stale_data`, `slow_query`, `metric_rename`, `cardinality_spike`, `var_resolution_fail`.

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
PROBE_ENGINE_PORT=8000
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
