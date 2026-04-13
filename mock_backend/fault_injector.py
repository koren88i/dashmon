"""In-memory fault injection state machine.

Faults are stored as {target: FaultRecord} and automatically expire.
The mock Prometheus API consults this before generating responses.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class FaultType(str, Enum):
    NO_DATA = "no_data"
    STALE_DATA = "stale_data"
    SLOW_QUERY = "slow_query"
    METRIC_RENAME = "metric_rename"
    CARDINALITY_SPIKE = "cardinality_spike"
    VAR_RESOLUTION_FAIL = "var_resolution_fail"


# Descriptions and expected demo behavior for each fault type.
# Single source of truth --served via GET /faults/types.
FAULT_INFO: dict[str, dict[str, str]] = {
    FaultType.NO_DATA: {
        "description": "Makes the target metric return zero results, as if the exporter stopped emitting it.",
        "expect": "The selected Grafana source dashboard shows blank/failed panels. SRE view turns the affected panels red and health score drops.",
    },
    FaultType.STALE_DATA: {
        "description": "Returns data with timestamps 10 minutes in the past, simulating a frozen exporter.",
        "expect": "Selected Grafana source panels stop refreshing. SRE view detects STALE_DATA --the numbers look normal but have not updated.",
    },
    FaultType.SLOW_QUERY: {
        "description": "Adds an 8-second delay before responding, simulating an overloaded datasource.",
        "expect": "Selected Grafana source panels take noticeably longer to load. SRE view detects SLOW_QUERY or QUERY_TIMEOUT depending on duration.",
    },
    FaultType.METRIC_RENAME: {
        "description": "Returns zero series for the target metric, as if it was renamed upstream without updating the dashboard.",
        "expect": "Affected panels go blank silently. In this demo, the probe surfaces it as NO_DATA because an empty Prometheus result is indistinguishable from a missing metric.",
    },
    FaultType.CARDINALITY_SPIKE: {
        "description": "Returns 10x the normal number of time series, simulating a label explosion.",
        "expect": "Grafana Service Health panels may look plausible but be wrong (over-aggregated). SRE view detects CARDINALITY_SPIKE.",
    },
    FaultType.VAR_RESOLUTION_FAIL: {
        "description": "Makes the label_values endpoint return an empty list, breaking template variable dropdowns.",
        "expect": "SRE view shows the affected variable badge as red and dashboard health drops. Check the real Grafana dashboard to inspect variable-dependent breakage.",
    },
}


@dataclass
class FaultRecord:
    fault_type: FaultType
    target: str
    expires_at: float | None  # None = until manually cleared

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and time.time() > self.expires_at

    def to_dict(self) -> dict:
        remaining = None
        if self.expires_at is not None:
            remaining = max(0.0, self.expires_at - time.time())
        return {
            "type": self.fault_type.value,
            "target": self.target,
            "remaining_seconds": remaining,
        }


class FaultInjector:
    """Thread-safe (single-process async) fault store."""

    def __init__(self) -> None:
        self._faults: dict[str, FaultRecord] = {}

    def inject(self, fault_type: FaultType, target: str, duration_seconds: int) -> FaultRecord:
        expires_at = None
        if duration_seconds > 0:
            expires_at = time.time() + duration_seconds
        record = FaultRecord(fault_type=fault_type, target=target, expires_at=expires_at)
        self._faults[target] = record
        return record

    def clear(self, target: str) -> int:
        """Clear faults. Returns number of faults removed."""
        if target == "all":
            count = len(self._faults)
            self._faults.clear()
            return count
        if target in self._faults:
            del self._faults[target]
            return 1
        return 0

    def get_active(self) -> list[dict]:
        self._expire()
        return [r.to_dict() for r in self._faults.values()]

    def get_fault_for_metric(self, metric_name: str) -> FaultRecord | None:
        """Return the active fault affecting *metric_name*, if any.

        Checks exact target match first, then the wildcard "all" target.
        """
        self._expire()
        record = self._faults.get(metric_name)
        if record is not None:
            return record
        return self._faults.get("all")

    def get_fault_for_label(self, label_name: str) -> FaultRecord | None:
        """Return var_resolution_fail fault targeting this label query."""
        self._expire()
        # Check for faults targeting any variable / label name
        record = self._faults.get(label_name)
        if record is not None and record.fault_type == FaultType.VAR_RESOLUTION_FAIL:
            return record
        record = self._faults.get("all")
        if record is not None and record.fault_type == FaultType.VAR_RESOLUTION_FAIL:
            return record
        return None

    def _expire(self) -> None:
        self._faults = {k: v for k, v in self._faults.items() if not v.is_expired}
