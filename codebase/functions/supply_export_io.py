"""Workbook read and validation helpers for supply LEAP exports."""
from __future__ import annotations

import re
from pathlib import Path

from codebase.configuration.config import scenario_dict
from codebase.configuration import workflow_config as workflow_cfg
from codebase.functions.analysis_input_write_dispatcher import (
    dispatch_analysis_input_write,
)
from codebase.functions.esto_data_utils import try_debug_breakpoint
from codebase.functions.leap_core import (
    connect_to_leap,
    ensure_fuel_exists,
    fill_branches_from_export_file,
)
from codebase.utilities import fuel_catalog_preflight
from codebase.utilities.master_config import read_config_table

EXPORT_DIR = workflow_cfg.SUPPLY_EXPORT_DIR
EXPORT_FILE_NAME = workflow_cfg.SUPPLY_EXPORT_FILE_NAME
SCENARIO_TO_RUN = workflow_cfg.SUPPLY_SCENARIO_TO_RUN
FILL_BRANCHES_FROM_EXPORT_FILE = workflow_cfg.SUPPLY_FILL_BRANCHES_FROM_EXPORT_FILE
HANDLE_CURRENT_ACCOUNTS_TOO = workflow_cfg.SUPPLY_HANDLE_CURRENT_ACCOUNTS_TOO
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


def run_branch_fill(
    L,
    export_path: Path,
    scenario: str,
    region: str,
    handle_current_accounts: bool,
    raise_on_missing_branch: bool = True,
) -> None:
    """Load data into supply branches from the export workbook."""
    try:
        outcome = fill_branches_from_export_file(
            L,
            export_path,
            sheet_name=SHEET_NAME,
            scenario=scenario,
            region=region,
            RAISE_ERROR_ON_FAILED_SET=raise_on_missing_branch,
            SET_UNITS=True,
            HANDLE_CURRENT_ACCOUNTS_TOO=handle_current_accounts,
            RUN_FUEL_CATALOG_PREFLIGHT=False,
        )
        print(f"[INFO] Supply branch fill result: {outcome}")
        _print_supply_missing_both_primary_secondary_summary(outcome)
    except Exception as exc:
        print(f"[ERROR] Supply branch fill failed: {exc}")
        try_debug_breakpoint()
        raise


def _print_supply_missing_both_primary_secondary_summary(outcome: dict | None) -> None:
    """Print fuels that failed in all attempted Resources roots during branch fill."""
    if not isinstance(outcome, dict):
        return

    def _extract_root_and_fuel(branch_path: str | None) -> tuple[str | None, str | None]:
        parts = [part.strip() for part in str(branch_path or "").split("\\") if part and str(part).strip()]
        if len(parts) < 3:
            return None, None
        if parts[0].lower() != "resources":
            return None, None
        root = parts[1].strip()
        if root.lower() not in {"primary", "secondary"}:
            return None, None
        fuel = parts[2].strip()
        if not fuel:
            return None, None
        return root.title(), fuel

    success_roots_by_fuel: dict[str, set[str]] = {}
    failed_roots_by_fuel: dict[str, set[str]] = {}

    for branch_path, variable in outcome.get("success", []) or []:
        var_name = str(variable or "").strip().lower()
        if var_name not in {"imports", "exports"}:
            continue
        root, fuel = _extract_root_and_fuel(branch_path)
        if not root or not fuel:
            continue
        success_roots_by_fuel.setdefault(fuel, set()).add(root)

    for branch_path, variable in outcome.get("failed", []) or []:
        var_name = str(variable or "").strip().lower()
        if var_name not in {"imports", "exports"}:
            continue
        root, fuel = _extract_root_and_fuel(branch_path)
        if not root or not fuel:
            continue
        failed_roots_by_fuel.setdefault(fuel, set()).add(root)

    fuels_missing_all_attempted: list[str] = []
    for fuel, failed_roots in sorted(failed_roots_by_fuel.items()):
        if success_roots_by_fuel.get(fuel):
            continue
        if failed_roots:
            fuels_missing_all_attempted.append(
                f"{fuel} (attempted: {', '.join(sorted(failed_roots))})"
            )

    if fuels_missing_all_attempted:
        print(
            "[WARN] Supply fuels not found in attempted Resources root(s) "
            f"({len(fuels_missing_all_attempted)}): {', '.join(fuels_missing_all_attempted)}"
        )
    else:
        print(
            "[INFO] Supply branch lookup summary: no fuels were missing in their "
            "attempted Resources root(s)."
        )


def run_supply_leap_import(
    export_directory: Path = EXPORT_DIR,
    filename: str | None = EXPORT_FILE_NAME,
    scenario_to_run: str = SCENARIO_TO_RUN,
    region: str = workflow_cfg.GLOBAL_REGION,
    handle_current_accounts: bool = HANDLE_CURRENT_ACCOUNTS_TOO,
    fill_branches: bool = FILL_BRANCHES_FROM_EXPORT_FILE,
) -> Path:
    """Locate the supply export and optionally fill the matching LEAP branches."""
    export_path = locate_supply_export(export_directory, filename)
    declared_scenarios = extract_export_metadata(export_path)
    available_scenarios = get_available_scenarios(export_path)
    print(
        f"[INFO] Preparing supply import from '{export_path.name}', declared scenarios "
        f"{declared_scenarios}, available scenarios {available_scenarios}."
    )
    if scenario_to_run not in available_scenarios:
        raise ValueError(
            f"Desired scenario '{scenario_to_run}' not present; available: {available_scenarios}"
        )
    ensure_region_in_export(export_path, region)

    dispatch_result = dispatch_analysis_input_write(
        export_path=export_path,
        sheet_name=SHEET_NAME,
        scenario=scenario_to_run,
        region=region,
        context_label="supply_data_pipeline.run_supply_leap_import",
    )
    if dispatch_result.get("mode") == "workbook":
        return export_path

    L = connect_to_leap()
    if L is None:
        raise RuntimeError("Failed to connect to LEAP.")
    fuel_catalog_preflight.run_fuel_catalog_preflight(
        export_path=export_path,
        sheet_name=SHEET_NAME,
        scenario=scenario_to_run,
        context="supply_data_pipeline.run_supply_leap_import",
        leap_app=L,
    )

    if fill_branches:
        print(
            "[INFO] Supply branches under Resources auto-create when their fuels "
            "are first used in Transformation/Demand and can be skipped until LEAP "
            "creates them."
        )
        ensure_supply_fuels_from_export(L, export_path)
        run_branch_fill(
            L,
            export_path,
            scenario_to_run,
            region,
            handle_current_accounts,
            raise_on_missing_branch=False,
        )
    return export_path
