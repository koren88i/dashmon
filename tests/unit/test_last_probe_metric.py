"""Test that the 'Last Probe Run' meta-dashboard panel uses a real timestamp metric.

The panel originally used time() - dashboard_health_score, which subtracted
a 0-1 fraction from epoch time, producing ~56 years. The correct approach
is a dedicated gauge that records the epoch of the last probe run, so
time() - that_gauge gives seconds-since-last-probe.
"""

import json
import pytest

from probe.parser import parse_dashboard
from generator.meta_dashboard import generate_meta_dashboard


@pytest.fixture()
def meta_dashboard():
    with open("demo/example_dashboard.json") as f:
        dash = json.load(f)
    panels, variables = parse_dashboard(dash)
    return generate_meta_dashboard(dash, panels, variables)


def test_last_probe_panel_uses_timestamp_metric(meta_dashboard):
    """The 'Last Probe Run' panel must query a timestamp gauge, not health_score.

    Subtracting a 0-1 value from time() gives epoch seconds (~56 years).
    The query must subtract an epoch-valued gauge so the result is
    meaningful seconds-since-last-probe.
    """
    last_probe_panels = [
        p for p in meta_dashboard["panels"]
        if p.get("title") == "Last Probe Run"
    ]
    assert len(last_probe_panels) == 1, "Expected exactly one 'Last Probe Run' panel"

    expr = last_probe_panels[0]["targets"][0]["expr"]
    assert "health_score" not in expr, (
        f"Panel query subtracts health_score (a 0-1 fraction) from time(), "
        f"producing ~56 years. Must use a timestamp gauge instead. Got: {expr}"
    )
    assert "last_probe_timestamp" in expr, (
        f"Panel query must use dashboard_last_probe_timestamp. Got: {expr}"
    )
