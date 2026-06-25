"""Reusable row-construction helpers for supply LEAP exports."""
from __future__ import annotations

import pandas as pd

from codebase.functions.esto_data_utils import try_debug_breakpoint
from codebase.functions.leap_core import sanitize_leap_name


def sanitize_leap_label(value):
    """Make fuel/branch labels safe for LEAP imports."""
    try:
        if value is None:
            return value
        return sanitize_leap_name(str(value))
    except Exception as exc:
        print(f"Failed to sanitize label {value}: {exc}")
        try_debug_breakpoint()
        raise


def build_branch_path(parts):
    """Return a LEAP branch path from a list of parts."""
    try:
        return "\\".join([str(part) for part in parts if part])
    except Exception as exc:
        print(f"Failed to build branch path from {parts}: {exc}")
        try_debug_breakpoint()
        raise


def coerce_value_by_year(value, base_year, final_year):
    """Convert a scalar, dict, or Series into a year->value dict."""
    try:
        if isinstance(value, dict):
            return {int(year): float(val) for year, val in value.items()}
        if isinstance(value, pd.Series):
            return {int(year): float(val) for year, val in value.items()}
        return {
            int(year): float(value if value not in (None, "") else 0.0)
            for year in range(base_year, final_year + 1)
        }
    except Exception as exc:
        print(f"Failed to coerce value to year mapping: {exc}")
        try_debug_breakpoint()
        raise


def build_year_rows(
    branch_path,
    measure,
    scenario,
    value_by_year,
    units,
    scale,
    per_value,
):
    """Return log-style rows for a LEAP import file."""
    try:
        rows = []
        for year, value in sorted(value_by_year.items()):
            safe_value = 0.0 if value is None else float(value)
            rows.append(
                {
                    "Branch_Path": branch_path,
                    "Scenario": scenario,
                    "Measure": measure,
                    "Units": units,
                    "Scale": scale,
                    "Per...": per_value,
                    "Date": int(year),
                    "Value": safe_value,
                }
            )
        return rows
    except Exception as exc:
        print(f"Failed to build year rows for {branch_path}: {exc}")
        try_debug_breakpoint()
        raise


def _normalize_override_year_map(
    value_by_year,
    base_year,
    final_year,
):
    """Return a clipped year->float mapping from an override payload."""
    if value_by_year is None:
        return None
    normalized = coerce_value_by_year(value_by_year, base_year, final_year)
    return {
        int(year): float(normalized.get(year, 0.0))
        for year in range(base_year, final_year + 1)
    }


def _resolve_supply_override(
    flow_value_overrides,
    scenario,
    fuel_key,
    fuel_entry,
    flow_key,
    base_year,
    final_year,
):
    """Return an override year map for a scenario/fuel/flow when present."""
    if not isinstance(flow_value_overrides, dict):
        return None
    scenario_payload = flow_value_overrides.get(scenario)
    if not isinstance(scenario_payload, dict):
        scenario_payload = flow_value_overrides.get(str(scenario))
    scenario_key = str(scenario or "").strip().lower()
    lower_payloads = {
        str(key).strip().lower(): value
        for key, value in flow_value_overrides.items()
        if isinstance(value, dict)
    }
    if not isinstance(scenario_payload, dict) and scenario_key:
        scenario_payload = lower_payloads.get(scenario_key)
    if (
        not isinstance(scenario_payload, dict)
        and scenario_key in {"current accounts", "current account"}
    ):
        # Keep Current Accounts aligned with reset behavior by falling back
        # to Reference overrides when no explicit CA payload exists.
        scenario_payload = lower_payloads.get("reference")
    if not isinstance(scenario_payload, dict):
        return None

    candidate_keys = [
        fuel_key,
        fuel_entry.get("fuel_label_esto"),
        fuel_entry.get("fuel_name"),
    ]
    fuel_payload = None
    for candidate in candidate_keys:
        if candidate in scenario_payload and isinstance(scenario_payload[candidate], dict):
            fuel_payload = scenario_payload[candidate]
            break
    if not isinstance(fuel_payload, dict):
        return None
    return _normalize_override_year_map(
        fuel_payload.get(flow_key),
        base_year,
        final_year,
    )
