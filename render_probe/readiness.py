"""DOM readiness classification for Grafana browser render probes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


RENDER_TIMEOUT = "render_timeout"
RENDER_NAVIGATION_ERROR = "render_navigation_error"
RENDER_PANEL_ERROR = "render_panel_error"
RENDER_NO_DATA = "render_no_data"
RENDER_BLANK = "render_blank"

ReadinessState = Literal["ready", "pending", "degraded"]


@dataclass(frozen=True)
class DashboardDomSnapshot:
    document_ready: bool
    dashboard_seen: bool
    panel_count: int
    panel_body_count: int
    loading_count: int
    panel_error_count: int
    no_data_count: int
    url: str = ""


@dataclass(frozen=True)
class RenderReadiness:
    state: ReadinessState
    error_type: str | None = None
    message: str = ""

    @property
    def ready(self) -> bool:
        return self.state == "ready"


def classify_snapshot(snapshot: DashboardDomSnapshot) -> RenderReadiness:
    """Classify a browser DOM snapshot as ready, pending, or degraded."""
    if snapshot.panel_error_count > 0:
        return RenderReadiness(
            "degraded",
            RENDER_PANEL_ERROR,
            f"Grafana shows {snapshot.panel_error_count} panel error element(s)",
        )
    if snapshot.no_data_count > 0:
        return RenderReadiness(
            "degraded",
            RENDER_NO_DATA,
            f"Grafana shows {snapshot.no_data_count} no-data panel state(s)",
        )
    if not snapshot.document_ready or not snapshot.dashboard_seen:
        return RenderReadiness("pending", message="Grafana dashboard is still loading")
    if snapshot.loading_count > 0:
        return RenderReadiness(
            "pending",
            message=f"Grafana still shows {snapshot.loading_count} loading indicator(s)",
        )
    if snapshot.panel_count == 0 or snapshot.panel_body_count == 0:
        return RenderReadiness(
            "degraded",
            RENDER_BLANK,
            "Grafana dashboard rendered without visible panel content",
        )
    return RenderReadiness("ready", message="Grafana dashboard rendered")

