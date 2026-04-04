# Test Plan

## Goal

Codify the already-verified behaviors as automated, regression-proof tests. These tests validate the system against its external spec (the brief), not just against implementation intent.

## What we are NOT trying to do

- Find new bugs in logic we haven't thought about (that requires a fresh reviewer)
- Achieve high line coverage for its own sake
- Test Grafana's behavior or Docker itself

## Test tool choice

**pytest + httpx + pytest-asyncio** for all layers. No mocking of the mock backend — the mock backend *is* the test double for Prometheus.

- Unit/integration tests: spin up the mock backend as a subprocess fixture, probe directly
- E2E tests: use the already-running Docker stack (skipped if Docker not up), OR spin it up via `subprocess` in a session fixture

---

## Test layers

### Layer 1 — Unit tests (no network, no subprocess)

Fast, zero-infrastructure. These test pure logic.

#### `tests/unit/test_parser.py`

| Test | Asserts |
|---|---|
| `test_panel_count` | `parse_dashboard(example_dashboard)` → 6 panels |
| `test_variable_count` | → 2 variables |
| `test_variable_chaining` | `$pod` is chained, `$namespace` is not |
| `test_panel_queries_present` | every panel has ≥1 query |
| `test_variable_substitution` | `$pod` replaced with `.*` in queries |
| `test_panel_datasource_uid` | all panels map to `"prometheus-main"` |
| `test_empty_panels_skipped` | dashboard with no panel targets → 0 panel specs |
| `test_non_prometheus_panels_skipped` | panel with unknown datasource type → excluded |

#### `tests/unit/test_config.py`

| Test | Asserts |
|---|---|
| `test_from_dict_thresholds` | `ProbeConfig.from_dict(yaml_dict)` populates all thresholds correctly |
| `test_url_for_datasource_found` | returns correct URL for known uid |
| `test_url_for_datasource_missing` | returns `None` for unknown uid |
| `test_defaults` | `ProbeConfig.defaults()` has a datasource pointing to `localhost:9090` |

#### `tests/unit/test_generators.py`

| Test | Asserts |
|---|---|
| `test_meta_dashboard_valid_json` | output parses as JSON, has `schemaVersion`, `panels`, `uid` |
| `test_meta_dashboard_uid_prefix` | uid starts with `sre-` |
| `test_meta_dashboard_panel_count` | has ≥1 panel per row (6 rows → ≥6 panels) |
| `test_meta_dashboard_datasource_variable` | uses `${datasource}` not a hardcoded uid |
| `test_alert_rules_valid_structure` | has `apiVersion`, `groups[0].rules` |
| `test_alert_rules_count` | 6 panels × 6 probe types + 2 vars + 2 dashboard = 40 rules |
| `test_alert_rules_for_duration` | every rule has `"for": "2m"` |
| `test_alert_rules_labels` | every rule has `severity` and `dashboard_uid` labels |
| `test_alert_rules_unique_uids` | all rule UIDs are distinct |

---

### Layer 2 — Integration tests (mock backend as subprocess)

Spin up `uvicorn mock_backend.prometheus_api:app --port 9091` once per session via a pytest fixture. Probe classes called directly (no engine, no FastAPI).

Port 9091 avoids colliding with a running Docker stack on 9090.

#### `tests/integration/test_query_probe.py`

| Test | Fault injected | Asserts |
|---|---|---|
| `test_healthy` | none | `status=HEALTHY`, `series_count > 0`, `error_type=None` |
| `test_no_data` | `no_data` on target metric | `status=DEGRADED`, `error_type=NO_DATA`, `series_count=0` |
| `test_slow_query` | `slow_query` | `status=DEGRADED`, `error_type=SLOW_QUERY`, `duration > threshold` |
| `test_panel_error` | backend killed / wrong URL | `status=DEGRADED`, `error_type=PANEL_ERROR` |
| `test_timeout` | `slow_query` with very short timeout config | `status=DEGRADED`, `error_type=QUERY_TIMEOUT` |

#### `tests/integration/test_staleness_probe.py`

| Test | Fault injected | Asserts |
|---|---|---|
| `test_healthy` | none | `status=HEALTHY`, `max_timestamp` close to now() |
| `test_stale_data` | `stale_data` | `status=DEGRADED`, `error_type=STALE_DATA` |
| `test_no_data_returns_unknown` | `no_data` | `status=UNKNOWN` (query_probe handles NO_DATA, not staleness) |

#### `tests/integration/test_variable_probe.py`

| Test | Fault injected | Asserts |
|---|---|---|
| `test_healthy` | none | `status=HEALTHY`, `values_count > 0` |
| `test_var_resolution_fail` | `var_resolution_fail` | `status=DEGRADED`, `error_type=VAR_RESOLUTION_FAIL` |

#### `tests/integration/test_cardinality_probe.py`

| Test | Fault injected | Asserts |
|---|---|---|
| `test_healthy_baseline_learned` | none (2 probes) | second probe returns `status=HEALTHY` with baseline set |
| `test_cardinality_spike` | `cardinality_spike` after baseline established | `status=DEGRADED`, `error_type=CARDINALITY_SPIKE` |
| `test_metric_rename` | `metric_rename` | `status=DEGRADED`, `error_type=METRIC_RENAME` |

---

### Layer 3 — E2E tests (full engine via HTTP)

Spin up both mock backend and probe engine as subprocesses. Wait for `/health` to return `health_score=1.0`. Then run the fault matrix.

These are the automated equivalent of the PLAN.md Step 5 verification script.

#### `tests/e2e/test_fault_matrix.py`

Session fixture: start mock backend on :9091, start probe engine pointed at :9091 on :8001. Wait up to 30s for `health_score=1.0`.

| Test | Action | Asserts |
|---|---|---|
| `test_baseline_healthy` | no fault | `health_score=1.0`, all 6 panels healthy |
| `test_no_data_detected` | inject `no_data`, wait one probe cycle | `health_score < 1.0`, at least one panel degraded, issue in log |
| `test_stale_data_detected` | inject `stale_data`, wait | panel degraded |
| `test_slow_query_detected` | inject `slow_query`, wait | panel degraded with `error_type=slow_query` or `query_timeout` |
| `test_var_resolution_fail_detected` | inject `var_resolution_fail`, wait | variable status degraded in `/health` response |
| `test_metric_rename_detected` | inject `metric_rename`, wait | panel degraded |
| `test_cardinality_spike_detected` | establish baseline first, inject `cardinality_spike`, wait | panel degraded |
| `test_recovery_after_clear` | inject `no_data`, wait for detection, clear, wait | `health_score=1.0` restored |

**Timing:** probe interval set to 5s in test config (not 15s) to keep test suite fast. Total E2E suite runtime target: <90s.

---

## File structure

```
tests/
├── conftest.py               shared fixtures: mock backend subprocess, probe engine subprocess
├── fixtures/
│   └── mini_dashboard.json   minimal 1-panel dashboard for unit tests (no external deps)
├── unit/
│   ├── test_parser.py
│   ├── test_config.py
│   └── test_generators.py
├── integration/
│   ├── test_query_probe.py
│   ├── test_staleness_probe.py
│   ├── test_variable_probe.py
│   └── test_cardinality_probe.py
└── e2e/
    └── test_fault_matrix.py
```

---

## Pytest configuration

```ini
# pytest.ini
[pytest]
asyncio_mode = auto
testpaths = tests
markers =
    unit: no network, no subprocess
    integration: requires mock backend subprocess
    e2e: requires both mock backend and probe engine subprocesses
```

Run selectively:
```bash
pytest -m unit                  # fast, always run
pytest -m integration           # needs nothing running
pytest -m e2e                   # slowest, full stack
pytest                          # all
```

---

## Dependencies to add

```
# tests/requirements.txt
pytest>=8.0,<9
pytest-asyncio>=0.23,<1
httpx>=0.27,<1
```

No new prod dependencies.

---

## What these tests will NOT catch

- Grafana actually importing the generated JSON (no real Grafana in CI)
- Visual rendering in the simulator (manual only)
- Fault detection timing under load (Docker health checks cover basic liveness)
- Parser correctness for dashboard JSON shapes we haven't seen (only one fixture)
- Slow query detection reliability (sleep-based fault + asyncio timeout is environment-sensitive)

These are known gaps, not oversights.
