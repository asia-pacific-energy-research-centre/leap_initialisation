"""Workbook read and validation helpers for supply LEAP exports."""
from __future__ import annotations

import re
from pathlib import Path

from codebase.configuration.config import scenario_dict
from codebase.configuration import workflow_config as workflow_cfg
from codebase.functions.esto_data_utils import try_debug_breakpoint
from codebase.functions.leap_core import ensure_fuel_exists
from codebase.utilities.master_config import read_config_table

SHEET_NAME = workflow_cfg.SUPPLY_SHEET_NAME
EXPORT_FILENAME_REGEX = re.compile(
    r"supply_leap_imports_(?P<economy>[^_]+)_(?P<scenarios>.+)\.xlsx",
    re.IGNORECASE,
)


def _normalize_token(token: str) -> str:
    """Return a lowercase alphanumeric key suitable for scenario matching."""
    return "".join(ch.lower() for ch in token if ch.isalnum())


def _match_scenario_token(token: str) -> str | None:
    """Match a token from the filename to the configured scenario dictionary."""
    token_key = _normalize_token(token)
    for scenario in scenario_dict:
        if token_key == _normalize_token(scenario):
            return scenario
    return None


def locate_supply_export(directory: Path, filename: str | None = None) -> Path:
    """Return the most recent supply export, optionally using an explicit name."""
    try:
        if filename:
            candidate = directory / filename
            if candidate.exists():
                return candidate
            raise FileNotFoundError(f"Expected supply export not found: {candidate}")
        matches = sorted(directory.glob("supply_leap_imports_*.xlsx"))
        if not matches:
            raise FileNotFoundError(
                f"No supply export files detected in {directory}"
            )
        return matches[-1]
    except Exception as exc:
        print(f"[ERROR] Unable to locate supply export: {exc}")
        try_debug_breakpoint()
        raise


def extract_export_metadata(export_path: Path) -> list[str]:
    """Parse the export filename to recover declared scenario tokens."""
    match = EXPORT_FILENAME_REGEX.match(export_path.name)
    if not match:
        raise ValueError(
            f"Supply export filename '{export_path.name}' does not match the expected pattern."
        )
    tokens = [tok for tok in match.group("scenarios").split("_") if tok]
    normalized = []
    for token in tokens:
        label = token.replace("-", " ").strip()
        scenario_name = _match_scenario_token(label)
        normalized.append(scenario_name or label)
    return normalized


def _read_unique_column(
    export_path: Path, column: str, sheet_name: str = SHEET_NAME
) -> list[str]:
    """Read a single column from the export and preserve the order of unique values."""
    try:
        df = read_config_table(export_path, sheet_name=sheet_name, header=2, usecols=[column])
    except Exception as exc:
        print(f"[ERROR] Failed to read column '{column}' from {export_path}: {exc}")
        try_debug_breakpoint()
        raise
    values = df[column].dropna().astype(str).tolist()
    seen = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen


def get_available_scenarios(export_path: Path) -> list[str]:
    """Return the scenario labels present in the export workbook."""
    return _read_unique_column(export_path, "Scenario")


def ensure_region_in_export(export_path: Path, region: str) -> None:
    """Raise if the configured region does not appear in the export file."""
    regions = _read_unique_column(export_path, "Region")
    if region not in regions:
        raise ValueError(
            f"Region '{region}' not found in export file; available values: {regions}"
        )


def _extract_fuel_from_branch_path(branch_path: str) -> str | None:
    """Return the final segment of a branch path when it represents a fuel name."""
    components = [segment.strip() for segment in branch_path.split("\\") if segment.strip()]
    if len(components) < 3:
        return None
    return components[-1]


def get_supply_fuels_from_export(export_path: Path) -> list[str]:
    """Read branch paths from the export to recover fuel names."""
    branch_paths = _read_unique_column(export_path, "Branch Path")
    fuels: list[str] = []
    seen: set[str] = set()
    for branch_path in branch_paths:
        fuel = _extract_fuel_from_branch_path(branch_path)
        if not fuel or fuel in seen:
            continue
        seen.add(fuel)
        fuels.append(fuel)
    return fuels


def ensure_supply_fuel_exists(
    L,
    fuel_name: str,
    copy_from: str | None = None,
    fuel_state: int = 2,
) -> object:
    """Wrapper around LEAP's ensure_fuel_exists so fuels appear before the fill."""
    return ensure_fuel_exists(
        L,
        fuel_name,
        copy_from=copy_from,
        fuel_state=fuel_state,
    )


def ensure_supply_fuels_from_export(L, export_path: Path) -> None:
    """Ensure every fuel referenced in the export exists in LEAP before filling."""
    try:
        fuels = get_supply_fuels_from_export(export_path)
    except Exception as exc:
        print(f"[ERROR] Unable to determine supply fuels from export: {exc}")
        try_debug_breakpoint()
        raise
    if not fuels:
        print("[INFO] No supply fuels detected in export; nothing to ensure.")
        return
    print(f"[INFO] Ensuring {len(fuels)} supply fuel(s) exist before branch fill.")
    for fuel in fuels:
        ensure_supply_fuel_exists(L, fuel_name=fuel)
