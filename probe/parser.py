"""Parse Grafana dashboard JSON into probe specs.

Handles template variable substitution, multi-query panels, and
mixed-datasource dashboards.
"""

from __future__ import annotations

import re
from typing import Any

from probe.config import PanelProbeSpec, VariableProbeSpec

# Replace $variable references with safe sentinels so probes produce valid PromQL.
# Label/string context  → .*  (regex wildcard)
# Numeric context (after >, >=, <, <=) → 0  (valid scalar operand)
_VAR_RE = re.compile(r"\$\{?(\w+)\}?")
_NUMERIC_OP_RE = re.compile(r"((?:>=|<=|>|<)\s*)\$\{?(\w+)\}?")


def parse_dashboard(
    dashboard: dict[str, Any],
) -> tuple[list[PanelProbeSpec], list[VariableProbeSpec]]:
    """Return (panel_specs, variable_specs) from a Grafana dashboard JSON."""
    variables = _parse_variables(dashboard)
    var_names = {v.name for v in variables}
    panels = _parse_panels(dashboard, var_names)
    return panels, variables


def _parse_panels(
    dashboard: dict[str, Any],
    var_names: set[str],
) -> list[PanelProbeSpec]:
    specs: list[PanelProbeSpec] = []
    for panel in dashboard.get("panels", []):
        # Skip row-type panels (they are containers, not data panels).
        if panel.get("type") == "row":
            # Rows can contain nested panels.
            for nested in panel.get("panels", []):
                spec = _panel_to_spec(nested, var_names)
                if spec is not None:
                    specs.append(spec)
            continue
        spec = _panel_to_spec(panel, var_names)
        if spec is not None:
            specs.append(spec)
    return specs


def _panel_to_spec(
    panel: dict[str, Any],
    var_names: set[str],
) -> PanelProbeSpec | None:
    targets = panel.get("targets", [])
    if not targets:
        return None

    ds = panel.get("datasource", {})
    ds_uid = ds.get("uid", "unknown")
    ds_type = ds.get("type", "prometheus")

    queries: list[str] = []
    for target in targets:
        expr = target.get("expr", "")
        if not expr:
            continue
        # Substitute template variables with .* for probing.
        expr = _substitute_variables(expr, var_names)
        queries.append(expr)

    if not queries:
        return None

    return PanelProbeSpec(
        panel_id=panel.get("id", 0),
        panel_title=panel.get("title", "Untitled"),
        datasource_uid=ds_uid,
        datasource_type=ds_type,
        queries=queries,
        expected_min_series=1,
    )


def _parse_variables(
    dashboard: dict[str, Any],
) -> list[VariableProbeSpec]:
    templating = dashboard.get("templating", {})
    var_list = templating.get("list", [])
    # First pass: collect names so we can detect chaining.
    all_names = {v.get("name", "") for v in var_list}

    specs: list[VariableProbeSpec] = []
    for var_def in var_list:
        if var_def.get("type") != "query":
            continue
        name = var_def.get("name", "")
        ds = var_def.get("datasource", {})
        ds_uid = ds.get("uid", "unknown")
        query = var_def.get("query", "")
        # Handle Grafana's query object format.
        if isinstance(query, dict):
            query = query.get("query", "")

        # Detect chaining: does this variable's query reference another variable?
        referenced = set(_VAR_RE.findall(query))
        is_chained = bool(referenced & all_names)
        chain_depth = 1 if is_chained else 0

        specs.append(
            VariableProbeSpec(
                name=name,
                datasource_uid=ds_uid,
                query=query,
                is_chained=is_chained,
                chain_depth=chain_depth,
            )
        )

    # Resolve deeper chain depths via simple BFS.
    _resolve_chain_depths(specs)
    return specs


def _resolve_chain_depths(variables: list[VariableProbeSpec]) -> None:
    """Set chain_depth correctly for multi-level chaining."""
    by_name = {v.name: v for v in variables}
    for var in variables:
        depth = 0
        visited: set[str] = set()
        current = var
        while current.is_chained:
            refs = set(_VAR_RE.findall(current.query))
            parent_names = refs & set(by_name.keys())
            if not parent_names or parent_names & visited:
                break
            visited |= parent_names
            parent_name = next(iter(parent_names))
            current = by_name.get(parent_name, current)
            depth += 1
        var.chain_depth = depth


def _substitute_variables(expr: str, var_names: set[str]) -> str:
    """Replace $variable / ${variable} with safe sentinels in PromQL expressions.

    Numeric comparison context (after >, >=, <, <=): substitute 0 so the
    expression remains valid PromQL (e.g. ``latency > $slo`` → ``latency > 0``).
    All other contexts: substitute .* for label/string matching.
    """
    # Pass 1: numeric comparison contexts → 0
    def numeric_replacer(m: re.Match) -> str:
        if m.group(2) in var_names:
            return m.group(1) + "0"
        return m.group(0)
    expr = _NUMERIC_OP_RE.sub(numeric_replacer, expr)

    # Pass 2: remaining references (label/string contexts) → .*
    def string_replacer(m: re.Match) -> str:
        if m.group(1) in var_names:
            return ".*"
        return m.group(0)
    return _VAR_RE.sub(string_replacer, expr)
