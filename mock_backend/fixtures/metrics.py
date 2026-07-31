"""Synthetic metric families for the mock Prometheus backend.

Generates sinusoidal + noise time series for the demo dashboards.
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Metric family definitions
# ---------------------------------------------------------------------------

@dataclass
class MetricFamily:
    name: str
    help_text: str
    metric_type: str  # "counter", "gauge", "histogram"
    label_sets: list[dict[str, str]]
    base_value: float
    amplitude: float
    period: float = 300.0  # seconds per sinusoidal cycle


_ATLAS_LABEL_SETS = [
    {
        "job": "atlas-prometheus",
        "group_id": "demo-group",
        "org_id": "demo-org",
        "cl_name": "demo-cluster",
        "rs_nm": "rs0",
        "instance": "atlas-mongo-a.mongodb.net:27017",
        "process_port": "27017",
        "process_type": "mongod",
        "replica_state_name": "PRIMARY",
        "replica_state": "1",
    },
    {
        "job": "atlas-prometheus",
        "group_id": "demo-group",
        "org_id": "demo-org",
        "cl_name": "demo-cluster",
        "rs_nm": "rs0",
        "instance": "atlas-mongo-b.mongodb.net:27017",
        "process_port": "27017",
        "process_type": "mongod",
        "replica_state_name": "SECONDARY",
        "replica_state": "2",
    },
    {
        "job": "atlas-prometheus",
        "group_id": "demo-group",
        "org_id": "demo-org",
        "cl_name": "demo-cluster",
        "rs_nm": "rs0",
        "instance": "atlas-mongo-c.mongodb.net:27017",
        "process_port": "27017",
        "process_type": "mongod",
        "replica_state_name": "SECONDARY",
        "replica_state": "2",
    },
]


def _atlas_family(
    name: str,
    *,
    base_value: float = 100.0,
    amplitude: float = 15.0,
    metric_type: str = "gauge",
    period: float = 600.0,
) -> MetricFamily:
    return MetricFamily(
        name=name,
        help_text=f"Synthetic MongoDB Atlas metric {name}",
        metric_type=metric_type,
        label_sets=_ATLAS_LABEL_SETS,
        base_value=base_value,
        amplitude=amplitude,
        period=period,
    )


def _atlas_metric_families() -> list[MetricFamily]:
    return [
        _atlas_family("mongodb_info", base_value=1.0, amplitude=0.0),
        _atlas_family("mongodb_mem_resident", base_value=6200.0, amplitude=380.0),
        _atlas_family("mongodb_mem_virtual", base_value=9100.0, amplitude=420.0),
        _atlas_family("mongodb_asserts_regular", base_value=1200.0, amplitude=90.0, metric_type="counter"),
        _atlas_family("mongodb_asserts_warning", base_value=40.0, amplitude=5.0, metric_type="counter"),
        _atlas_family("mongodb_asserts_msg", base_value=20.0, amplitude=4.0, metric_type="counter"),
        _atlas_family("mongodb_asserts_user", base_value=12.0, amplitude=3.0, metric_type="counter"),
        _atlas_family("mongodb_wiredTiger_cache_bytes_read_into_cache", base_value=7_000_000.0, amplitude=700_000.0, metric_type="counter"),
        _atlas_family("mongodb_wiredTiger_cache_bytes_written_from_cache", base_value=5_000_000.0, amplitude=500_000.0, metric_type="counter"),
        _atlas_family("mongodb_wiredTiger_cache_bytes_currently_in_the_cache", base_value=3_400_000_000.0, amplitude=160_000_000.0),
        _atlas_family("mongodb_wiredTiger_cache_tracked_dirty_bytes_in_the_cache", base_value=180_000_000.0, amplitude=30_000_000.0),
        _atlas_family("mongodb_connections_current", base_value=260.0, amplitude=30.0),
        _atlas_family("mongodb_metrics_cursor_open_total", base_value=36.0, amplitude=8.0),
        _atlas_family("mongodb_metrics_cursor_timedOut", base_value=4.0, amplitude=1.0, metric_type="counter"),
        _atlas_family("mongodb_metrics_document_returned", base_value=75_000.0, amplitude=9000.0, metric_type="counter"),
        _atlas_family("mongodb_metrics_document_inserted", base_value=18_000.0, amplitude=2500.0, metric_type="counter"),
        _atlas_family("mongodb_metrics_document_updated", base_value=14_000.0, amplitude=2000.0, metric_type="counter"),
        _atlas_family("mongodb_metrics_document_deleted", base_value=3200.0, amplitude=400.0, metric_type="counter"),
        _atlas_family("mongodb_network_numRequests", base_value=90_000.0, amplitude=12_000.0, metric_type="counter"),
        _atlas_family("mongodb_network_bytesIn", base_value=110_000_000.0, amplitude=12_000_000.0, metric_type="counter"),
        _atlas_family("mongodb_network_bytesOut", base_value=180_000_000.0, amplitude=18_000_000.0, metric_type="counter"),
        _atlas_family("mongodb_opcounters_command", base_value=40_000.0, amplitude=5200.0, metric_type="counter"),
        _atlas_family("mongodb_opcounters_query", base_value=55_000.0, amplitude=6500.0, metric_type="counter"),
        _atlas_family("mongodb_opcounters_update", base_value=13_000.0, amplitude=1800.0, metric_type="counter"),
        _atlas_family("mongodb_opcounters_delete", base_value=4200.0, amplitude=600.0, metric_type="counter"),
        _atlas_family("mongodb_opcounters_getmore", base_value=12_000.0, amplitude=1500.0, metric_type="counter"),
        _atlas_family("mongodb_opcounters_insert", base_value=19_000.0, amplitude=2400.0, metric_type="counter"),
        _atlas_family("mongodb_opLatencies_reads_latency", base_value=120_000.0, amplitude=14_000.0, metric_type="counter"),
        _atlas_family("mongodb_opLatencies_writes_latency", base_value=95_000.0, amplitude=11_000.0, metric_type="counter"),
        _atlas_family("mongodb_opLatencies_commands_latency", base_value=70_000.0, amplitude=9000.0, metric_type="counter"),
        _atlas_family("mongodb_extra_info_page_faults", base_value=90.0, amplitude=10.0, metric_type="counter"),
        _atlas_family("mongodb_metrics_queryExecutor_scanned", base_value=38_000.0, amplitude=4000.0, metric_type="counter"),
        _atlas_family("mongodb_metrics_queryExecutor_scannedObjects", base_value=42_000.0, amplitude=4500.0, metric_type="counter"),
        _atlas_family("mongodb_globalLock_currentQueue_total", base_value=2.0, amplitude=1.0),
        _atlas_family("mongodb_globalLock_currentQueue_readers", base_value=1.0, amplitude=0.5),
        _atlas_family("mongodb_globalLock_currentQueue_writers", base_value=1.0, amplitude=0.5),
        _atlas_family("mongodb_metrics_operation_scanAndOrder", base_value=600.0, amplitude=80.0, metric_type="counter"),
        _atlas_family("mongodb_wiredTiger_concurrentTransactions_read_available", base_value=120.0, amplitude=10.0),
        _atlas_family("mongodb_wiredTiger_concurrentTransactions_write_available", base_value=110.0, amplitude=9.0),
    ]


METRIC_FAMILIES: list[MetricFamily] = [
    MetricFamily(
        name="http_requests_total",
        help_text="Total HTTP requests",
        metric_type="counter",
        label_sets=[
            {"method": "GET", "status": "200", "service": "api"},
            {"method": "GET", "status": "500", "service": "api"},
            {"method": "POST", "status": "200", "service": "api"},
            {"method": "POST", "status": "500", "service": "api"},
        ],
        base_value=1000.0,
        amplitude=200.0,
    ),
    MetricFamily(
        name="http_request_duration_seconds",
        help_text="HTTP request duration in seconds",
        metric_type="histogram",
        label_sets=[
            {"method": "GET", "service": "api"},
            {"method": "POST", "service": "api"},
        ],
        base_value=0.15,
        amplitude=0.05,
        period=600.0,
    ),
    MetricFamily(
        name="process_resident_memory_bytes",
        help_text="Resident memory size in bytes",
        metric_type="gauge",
        label_sets=[
            {"pod": "api-server-abc123", "namespace": "default"},
            {"pod": "api-server-def456", "namespace": "default"},
            {"pod": "worker-ghi789", "namespace": "batch"},
        ],
        base_value=500_000_000.0,
        amplitude=50_000_000.0,
        period=900.0,
    ),
    MetricFamily(
        name="kube_pod_status_ready",
        help_text="Pod readiness status",
        metric_type="gauge",
        label_sets=[
            {"pod": "api-server-abc123", "namespace": "default"},
            {"pod": "api-server-def456", "namespace": "default"},
            {"pod": "worker-ghi789", "namespace": "batch"},
        ],
        base_value=1.0,
        amplitude=0.0,
    ),
    MetricFamily(
        name="up",
        help_text="Target up status",
        metric_type="gauge",
        label_sets=[
            {"job": "prometheus", "instance": "localhost:9090"},
            {"job": "api-server", "instance": "api-server:8080"},
            {"job": "node", "instance": "node-1:9100"},
        ],
        base_value=1.0,
        amplitude=0.0,
    ),
    MetricFamily(
        name="mongodb_up",
        help_text="MongoDB exporter target health",
        metric_type="gauge",
        label_sets=[
            {"instance": "mongo-a:27017", "replset": "rs0", "role": "primary"},
            {"instance": "mongo-b:27017", "replset": "rs0", "role": "secondary"},
            {"instance": "mongo-c:27017", "replset": "rs0", "role": "secondary"},
            *_ATLAS_LABEL_SETS,
        ],
        base_value=1.0,
        amplitude=0.0,
    ),
    MetricFamily(
        name="mongodb_op_counters_total",
        help_text="MongoDB operation counters",
        metric_type="counter",
        label_sets=[
            {"instance": "mongo-a:27017", "replset": "rs0", "type": "query"},
            {"instance": "mongo-a:27017", "replset": "rs0", "type": "insert"},
            {"instance": "mongo-a:27017", "replset": "rs0", "type": "update"},
            {"instance": "mongo-b:27017", "replset": "rs0", "type": "query"},
            {"instance": "mongo-c:27017", "replset": "rs0", "type": "query"},
        ],
        base_value=25_000.0,
        amplitude=3_500.0,
        period=420.0,
    ),
    MetricFamily(
        name="mongodb_connections",
        help_text="MongoDB connection counts",
        metric_type="gauge",
        label_sets=[
            {"instance": "mongo-a:27017", "replset": "rs0", "state": "current"},
            {"instance": "mongo-a:27017", "replset": "rs0", "state": "available"},
            {"instance": "mongo-b:27017", "replset": "rs0", "state": "current"},
            {"instance": "mongo-b:27017", "replset": "rs0", "state": "available"},
            {"instance": "mongo-c:27017", "replset": "rs0", "state": "current"},
            {"instance": "mongo-c:27017", "replset": "rs0", "state": "available"},
        ],
        base_value=240.0,
        amplitude=25.0,
        period=600.0,
    ),
    MetricFamily(
        name="mongodb_memory_resident_bytes",
        help_text="MongoDB resident memory",
        metric_type="gauge",
        label_sets=[
            {"instance": "mongo-a:27017", "replset": "rs0"},
            {"instance": "mongo-b:27017", "replset": "rs0"},
            {"instance": "mongo-c:27017", "replset": "rs0"},
        ],
        base_value=3_200_000_000.0,
        amplitude=260_000_000.0,
        period=900.0,
    ),
    MetricFamily(
        name="mongodb_mongod_replset_member_replication_lag",
        help_text="MongoDB replica set replication lag in seconds",
        metric_type="gauge",
        label_sets=[
            {"instance": "mongo-b:27017", "replset": "rs0", "member_state": "secondary"},
            {"instance": "mongo-c:27017", "replset": "rs0", "member_state": "secondary"},
        ],
        base_value=1.2,
        amplitude=0.8,
        period=300.0,
    ),
    MetricFamily(
        name="mongodb_mongod_replset_member_health",
        help_text="MongoDB replica set member health",
        metric_type="gauge",
        label_sets=[
            {"instance": "mongo-a:27017", "replset": "rs0", "member_state": "primary"},
            {"instance": "mongo-b:27017", "replset": "rs0", "member_state": "secondary"},
            {"instance": "mongo-c:27017", "replset": "rs0", "member_state": "secondary"},
        ],
        base_value=1.0,
        amplitude=0.0,
    ),
    MetricFamily(
        name="mongodb_ss_connections",
        help_text="MongoDB serverStatus connection counts",
        metric_type="gauge",
        label_sets=[
            {"instance": "mongo-live:27017", "conn_type": "current"},
            {"instance": "mongo-live:27017", "conn_type": "available"},
            {"instance": "mongo-live:27017", "conn_type": "active"},
        ],
        base_value=120.0,
        amplitude=20.0,
        period=600.0,
    ),
    MetricFamily(
        name="mongodb_memory",
        help_text="MongoDB memory gauges in megabytes",
        metric_type="gauge",
        label_sets=[
            {"instance": "mongo-live:27017", "type": "resident"},
            {"instance": "mongo-live:27017", "type": "virtual"},
        ],
        base_value=512.0,
        amplitude=80.0,
        period=900.0,
    ),
    MetricFamily(
        name="mongodb_mongod_op_latencies_latency_total",
        help_text="MongoDB operation latency counter",
        metric_type="counter",
        label_sets=[
            {"instance": "mongo-live:27017", "type": "reads"},
            {"instance": "mongo-live:27017", "type": "writes"},
            {"instance": "mongo-live:27017", "type": "commands"},
        ],
        base_value=50_000.0,
        amplitude=6_000.0,
        period=420.0,
    ),
    MetricFamily(
        name="mongodb_mongod_op_latencies_ops_total",
        help_text="MongoDB operation count counter for latency",
        metric_type="counter",
        label_sets=[
            {"instance": "mongo-live:27017", "type": "reads"},
            {"instance": "mongo-live:27017", "type": "writes"},
            {"instance": "mongo-live:27017", "type": "commands"},
        ],
        base_value=20_000.0,
        amplitude=2_000.0,
        period=420.0,
    ),
    MetricFamily(
        name="mongodb_extra_info_page_faults_total",
        help_text="MongoDB page fault counter",
        metric_type="counter",
        label_sets=[
            {"instance": "mongo-live:27017"},
        ],
        base_value=1000.0,
        amplitude=120.0,
        period=600.0,
    ),
    *_atlas_metric_families(),
]

# Build an index for O(1) lookup by name (including histogram suffixes).
_FAMILY_BY_NAME: dict[str, MetricFamily] = {}
for _fam in METRIC_FAMILIES:
    _FAMILY_BY_NAME[_fam.name] = _fam
    if _fam.metric_type == "histogram":
        for _sfx in ("_bucket", "_count", "_sum"):
            _FAMILY_BY_NAME[_fam.name + _sfx] = _fam

# ---------------------------------------------------------------------------
# PromQL metric-name extraction (simple regex, not a real parser)
# ---------------------------------------------------------------------------

_PROMQL_KEYWORDS = frozenset({
    "rate", "irate", "increase", "delta", "sum", "avg", "min", "max",
    "count", "histogram_quantile", "topk", "bottomk", "quantile",
    "absent", "absent_over_time", "ceil", "floor", "round",
    "label_replace", "label_join", "sort", "sort_desc", "time",
    "vector", "scalar", "clamp", "clamp_min", "clamp_max",
    "by", "without", "on", "ignoring", "group_left", "group_right",
    "bool", "offset", "inf", "nan",
})

_IDENT_RE = re.compile(r"[a-zA-Z_:][a-zA-Z0-9_:]*")


def extract_metric_name(promql: str) -> str | None:
    """Return the first identifier in *promql* that looks like a metric name."""
    for m in _IDENT_RE.finditer(promql):
        token = m.group()
        if token not in _PROMQL_KEYWORDS and not token.startswith("$"):
            return token
    return None


def find_metric_family(metric_name: str) -> MetricFamily | None:
    return _FAMILY_BY_NAME.get(metric_name)


# ---------------------------------------------------------------------------
# Value generation
# ---------------------------------------------------------------------------

def _label_hash(labels: dict[str, str]) -> float:
    """Deterministic offset in [0, 1) to vary phase per label set."""
    h = hash(tuple(sorted(labels.items())))
    return (h % 1000) / 1000.0


def generate_value(family: MetricFamily, timestamp: float, labels: dict[str, str]) -> float:
    offset = _label_hash(labels)
    phase = ((timestamp / family.period) + offset) * 2 * math.pi
    value = family.base_value + family.amplitude * math.sin(phase)
    # Small deterministic jitter based on timestamp
    jitter = math.sin(timestamp * 7.3 + offset * 100) * family.amplitude * 0.05
    return max(0.0, value + jitter)


# ---------------------------------------------------------------------------
# Prometheus response builders
# ---------------------------------------------------------------------------

def get_instant_query_result(promql: str) -> list[dict]:
    """Build a Prometheus instant-vector result for *promql*."""
    name = extract_metric_name(promql)
    if name is None:
        return []
    family = find_metric_family(name)
    if family is None:
        return []

    now = time.time()
    results = []
    for labels in family.label_sets:
        value = generate_value(family, now, labels)
        results.append({
            "metric": {"__name__": family.name, **labels},
            "value": [now, f"{value:.6f}"],
        })
    return results


def get_range_query_result(
    promql: str,
    start: float,
    end: float,
    step: float,
) -> list[dict]:
    """Build a Prometheus range-matrix result for *promql*."""
    name = extract_metric_name(promql)
    if name is None:
        return []
    family = find_metric_family(name)
    if family is None:
        return []

    results = []
    for labels in family.label_sets:
        values: list[list] = []
        t = start
        while t <= end:
            v = generate_value(family, t, labels)
            values.append([t, f"{v:.6f}"])
            t += step
        results.append({
            "metric": {"__name__": family.name, **labels},
            "values": values,
        })
    return results


def get_series(match_metric: str) -> list[dict]:
    """Return all series label sets for the metric matched by *match_metric*."""
    name = extract_metric_name(match_metric)
    if name is None:
        return []
    family = find_metric_family(name)
    if family is None:
        return []
    return [{"__name__": family.name, **labels} for labels in family.label_sets]


def get_label_values(label_name: str) -> list[str]:
    """Return all unique values for *label_name* across all metric families."""
    values: set[str] = set()
    for family in METRIC_FAMILIES:
        if label_name == "__name__":
            values.add(family.name)
            continue
        for labels in family.label_sets:
            if label_name in labels:
                values.add(labels[label_name])
    return sorted(values)
