from __future__ import annotations

import copy
import importlib
import json
import os
import re
import shutil
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import pandas as pd
from openpyxl.styles import Font, PatternFill

from codebase.supply_reconciliation_config import *  # noqa: F401,F403
from codebase.supply_reconciliation_config import (
    _ModuleCapRule,
    _resolve_module_cap_rule,
    _use_legacy_trade_split_mode,
    _use_output_share_supply_exports_mode,
    _use_capacity_unmet_iterative_mode,
    _use_capacity_unmet_iterative_balanced_mode,
    _use_capacity_unmet_iterative_any_mode,
    _use_capacity_constrained_mode,
    _use_capacity_like_mode,
)
from codebase.utilities.workflow_utils import _resolve
from codebase.utilities import workflow_common
from codebase.utilities.output_paths import BALANCE_TABLES_ROOT, INTEGRATED_LEAP_EXPORTS_ROOT
from codebase.utilities.master_config import config_table_exists, read_config_table
from codebase.configuration import workflow_config as workflow_cfg
from codebase.configuration.all_products_and_flows import ESTO_PRODUCT_LIST, ESTO_SECTORS
from codebase.configuration.known_leap_label_exceptions import KNOWN_LEAP_LABEL_EXCEPTIONS
from codebase.mappings.canonical_mapping import (
    DEFAULT_BACKUP_LEAP_MAPPINGS,
    DEFAULT_CODEBOOK,
    DEFAULT_NINTH_TO_ESTO,
    DEFAULT_SHEET_MAP,
    build_sector_to_esto_flow_lookup,
    load_canonical_pairs,
    load_fuel_aliases,
    load_sheet_map,
)
from codebase.mappings.canonical_loaders import load_leap_display_names
from codebase.functions import supply_data_pipeline, leap_api, patch_baseline_seeds
from codebase.functions.analysis_input_write_dispatcher import get_analysis_input_write_mode
from codebase import (
    electricity_heat_interim_workflow,
    other_loss_own_use_proxy_workflow,
    transformation_workflow,
    transfers_workflow,
)
from codebase.utilities.leap_results_dashboard_balance import (
    DEFAULT_BACKUP_MAPPINGS_PATH as DEFAULT_BALANCE_BACKUP_MAPPINGS_PATH,
    DEFAULT_BASE_TABLE_PATH as DEFAULT_BALANCE_BASE_TABLE_PATH,
    DEFAULT_CODEBOOK_PATH as DEFAULT_BALANCE_CODEBOOK_PATH,
    DEFAULT_EXPLICIT_MAPPINGS_PATH as DEFAULT_BALANCE_EXPLICIT_MAPPINGS_PATH,
    DEFAULT_EXPLICIT_REASSIGNMENTS_PATH as DEFAULT_BALANCE_EXPLICIT_REASSIGNMENTS_PATH,
    DEFAULT_MAPPING_PAIRS_PATH as DEFAULT_BALANCE_MAPPING_PAIRS_PATH,
    DEFAULT_PROJECTION_TABLE_PATH as DEFAULT_BALANCE_PROJECTION_TABLE_PATH,
    DEFAULT_REF_WORKBOOK_PATH as DEFAULT_BALANCE_REF_WORKBOOK_PATH,
    DEFAULT_SHEET_MAP_PATH as DEFAULT_BALANCE_SHEET_MAP_PATH,
    DEFAULT_SYNTHETIC_REFERENCE_ROWS_PATH as DEFAULT_BALANCE_SYNTHETIC_REFERENCE_ROWS_PATH,
    DEFAULT_TGT_WORKBOOK_PATH as DEFAULT_BALANCE_TGT_WORKBOOK_PATH,
    build_balance_comparison_esto_axis,
    build_esto_axis_structure_from_dashboard_template,
    convert_leap_balances_to_esto_long_table,
)
from codebase.utilities.leap_balance_export_resolver import resolve_balance_export_workbook
from codebase.utilities.leap_results_dashboard_utils import (
    DEFAULT_EXPLICIT_LEAP_MAPPINGS,
    DEFAULT_EXPLICIT_LEAP_REASSIGNMENTS,
    apply_explicit_sector_reassignments,
    build_comparisons,
    load_explicit_sector_fuel_mappings,
    load_explicit_sector_reassignments,
    load_leap_workbook,
    map_fuel_label,
)
from codebase.scrapbook.utilities import load_augmented_reference_tables
from codebase.utilities.workflow_common import archive_config_dir_once_per_day
from codebase.supply_reconciliation_utils import (
    _canonical_transformation_fuel_label,
    _load_code_to_name_table,
    _normalize_label_for_lookup,
    _normalize_esto_product_for_match,
    _build_label_to_esto_product_lookup,
    _iter_year_value_items,
    _sort_output_frame_for_csv,
    _normalize_template_header_value,
)
from codebase.supply_reconciliation_history import (
    _state_token,
    _capacity_addition_state_key,
    _output_addition_state_key,
    _results_signature_state_key,
    _capacity_unmet_default_state,
    _resolve_capacity_unmet_pass_mode,
    _is_capacity_unmet_baseline_seed_pass,
    _read_capacity_unmet_state,
    _write_capacity_unmet_state,
    _build_results_signature,
    _lookup_runtime_capacity_additions_for_record,
    _lookup_runtime_primary_addition,
    _lookup_runtime_export_adjustment,
)
from codebase.supply_reconciliation_results import (
    _parse_year_column_token,
    _find_supply_results_header_row,
    _read_supply_results_trade_sheet,
    _read_supply_results_import_sheet,
    _read_supply_results_export_sheet,
    _balance_table_csv_candidates,
    _collect_observed_trade_from_balance_tables,
    _select_supply_results_workbook,
    _scenario_filename_candidates,
    _abbreviate_scenario,
    _resolve_refinery_results_workbook,
    _resolve_transformation_results_workbook,
)
from codebase.supply_reconciliation_balance_tables import (
    build_year_balance_table,
    save_year_balance_tables,
    build_conventional_balance_matrix,
    build_reference_conventional_balance_matrix,
    build_conventional_balance_diff_matrix,
    save_conventional_balance_tables,
    _get_refinery_fallback_rows_for_balance,
    _split_sector_codes,
    _sector_code_sequence,
    _select_primary_sector_code,
    _safe_filename_token,
    _filter_balance_scenarios,
    _ensure_current_accounts_scenario,
    _zero_small_numeric_values,
)
import codebase.supply_reconciliation_allocation as _sra

# Default economy scope used as the fallback when a caller passes no economies
# (see the `economies or ECONOMIES` guards below).  Mirrors the sibling supply
# modules (supply_leap_io, supply_results_saver); without it those references
# raise NameError.
ECONOMIES = list(workflow_cfg.SUPPLY_NOTEBOOK_ECONOMIES)


def _normalize_sector_match_key(value: object) -> str:
    """Return a forgiving sector key for cross-source name matching."""
    text = str(value or "").strip().lower()
    return "".join(ch for ch in text if ch.isalnum())


def _sector_match_keys(value: object) -> list[str]:
    """Return candidate normalized keys for matching coded and display sector names."""
    raw = str(value or "").strip().lower()
    if not raw:
        return []
    keys: list[str] = []
    direct = _normalize_sector_match_key(raw)
    if direct:
        keys.append(direct)
    # Handle coded sector names like `09_13_hydrogen_transformation`.
    stripped = re.sub(r"^\d+(?:[_.]\d+)*(?:[ _.-]+)?", "", raw).strip()
    stripped_key = _normalize_sector_match_key(stripped)
    if stripped_key and stripped_key not in keys:
        keys.append(stripped_key)
    return keys


@lru_cache(maxsize=32)
def _load_transformation_template_variable_sets(
    economy: str,
    scenario: str,
) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, str]]:
    """
    Load transformation template variables by sector from results workbook.

    The LEAP Results API refresh path has been retired for this workbook-first
    workflow. This helper is kept only to produce a clear error if an old toggle
    tries to enter that path.
    """
    raise RuntimeError(
        "Transformation Results template refresh is disabled. "
        "Keep REFRESH_TRANSFORMATION_MEASURES_FROM_LEAP_RESULTS=False and use "
        "LEAP balance export workbooks for results_update runs."
    )


def _pick_preferred_source(
    row: pd.Series,
    source_priority: tuple[str, ...],
) -> tuple[float | None, str | None]:
    """Return the first non-null source value using the configured precedence."""
    for source in source_priority:
        if source not in row.index:
            continue
        value = pd.to_numeric(row[source], errors="coerce")
        if pd.notna(value):
            return float(value), source
    return None, None


def _is_demand_sector_mapping(sector_code_text: object) -> bool:
    """Return True when any mapped 9th sector code belongs to demand/bunkers groups."""
    for code in _split_sector_codes(sector_code_text):
        token = str(code or "").strip().lower()
        if any(token.startswith(prefix) for prefix in DEMAND_SECTOR_PREFIXES):
            return True
    return False


def _is_non_actionable_demand_fuel(fuel_text: object) -> bool:
    """Return True when a demand fuel label is explicitly marked as non-actionable."""
    token = str(fuel_text or "").strip().lower()
    if not token:
        return False
    if token in DEMAND_NON_ACTIONABLE_FUEL_EXACT_MATCHES:
        return True
    return any(phrase in token for phrase in DEMAND_NON_ACTIONABLE_FUEL_PHRASES)


def _build_esto_parent_product_lookup() -> dict[str, str]:
    """Map each ESTO product label to its top-level parent label when available."""
    top_level_by_code: dict[str, str] = {}
    for item in ESTO_PRODUCT_LIST:
        text = str(item or "").strip()
        if not text:
            continue
        code = text.split(" ", 1)[0]
        if "." in code:
            continue
        top_level_by_code[code] = text

    lookup: dict[str, str] = {}
    for item in ESTO_PRODUCT_LIST:
        text = str(item or "").strip()
        if not text:
            continue
        code = text.split(" ", 1)[0]
        top_code = code.split(".", 1)[0]
        lookup[text] = top_level_by_code.get(top_code, text)
    return lookup


def _get_sector_to_esto_flow_lookup() -> dict[str, str]:
    """Load the shared 9th-sector -> ESTO flow lookup used by the dashboard mapping."""
    try:
        return build_sector_to_esto_flow_lookup()
    except Exception:
        return {}


SECTOR_TO_ESTO_FLOW_LOOKUP = _get_sector_to_esto_flow_lookup()
ESTO_PARENT_PRODUCT_LOOKUP = _build_esto_parent_product_lookup()


def _run_leap_results_template_scrape() -> dict[str, object]:
    """Disabled legacy LEAP Results API template scrape."""
    raise RuntimeError(
        "SCRAPE_LEAP_RESULTS is disabled in supply_reconciliation_workflow. "
        "Keep SCRAPE_LEAP_RESULTS=False and use exported LEAP balance workbooks."
    )


def _economy_tokens_for_workbook_match(economy: str) -> set[str]:
    """Build filename match tokens from an economy label such as 20_USA."""
    text = str(economy or "").strip()
    if not text:
        return set()
    tokens = {text.lower(), text.replace("_", "").lower()}
    match = re.match(r"^\s*\d{2}_([A-Za-z]{3})\s*$", text)
    if match:
        tokens.add(match.group(1).lower())
    return {token for token in tokens if token}


def _discover_direct_demand_workbooks(
    workbook_dir: Path | str,
    economies: Iterable[str],
    scenarios: Iterable[str],
) -> list[Path]:
    """Find LEAP results-table workbooks for the requested economy/scenario set."""
    root = _resolve(workbook_dir)
    if not root.exists():
        raise FileNotFoundError(f"LEAP results tables directory not found: {root}")

    economy_tokens: set[str] = set()
    for economy in economies:
        economy_tokens.update(_economy_tokens_for_workbook_match(str(economy)))
    scenario_tokens = {str(scenario or "").strip().lower() for scenario in scenarios if str(scenario or "").strip()}

    candidates = sorted(root.glob("*.xls*"))
    matched: list[Path] = []
    for path in candidates:
        name = path.name.lower()
        if economy_tokens and not any(token in name for token in economy_tokens):
            continue
        if scenario_tokens and not any(token in name for token in scenario_tokens):
            continue
        matched.append(path)
    if not matched:
        raise FileNotFoundError(
            f"No LEAP workbooks found in {root} for economies {sorted(economy_tokens)} "
            f"and scenarios {sorted(scenario_tokens)}."
        )
    return matched


def _infer_economy_from_workbook_name(path: Path) -> str:
    """Infer economy code from workbook filename tokens."""
    stem = str(path.stem)
    match = re.search(r"_(\d{2}_[A-Z]{3})_", stem, flags=re.IGNORECASE)
    if match:
        token = match.group(1).upper()
        return token[:2] + "_" + token[3:]
    match = re.search(r"_(\d{2}[A-Z]{3})_", stem, flags=re.IGNORECASE)
    if match:
        token = match.group(1).upper()
        return token[:2] + "_" + token[2:]
    return ""


def _truthy_flag(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def _load_active_direct_demand_mapping_sheet(sheet_name: str) -> pd.DataFrame:
    frame = read_config_table(DIRECT_DEMAND_MAPPING_WORKBOOK, sheet_name=sheet_name).fillna("").copy()
    if "remove_row" not in frame.columns:
        frame["remove_row"] = False
    if "duplicate_to_remove" not in frame.columns:
        frame["duplicate_to_remove"] = False
    active_mask = ~frame["remove_row"].map(_truthy_flag) & ~frame["duplicate_to_remove"].map(_truthy_flag)
    return frame.loc[active_mask].copy()


def _read_config_table_ref(table_ref, **kwargs) -> pd.DataFrame:
    """Read either a path or a (path, sheet_name) config table reference."""
    if isinstance(table_ref, tuple) and len(table_ref) == 2:
        return read_config_table(table_ref[0], sheet_name=table_ref[1], **kwargs)
    return read_config_table(table_ref, **kwargs)


def _build_augmented_balance_demand_mapping_workbook() -> Path:
    """
    Write a runtime mapping workbook with inferred demand ESTO mappings.

    LEAP balance conversion intentionally uses explicit LEAP path mappings. Some
    direct-demand rows have explicit LEAP->9th mappings but no authored
    LEAP->ESTO row. For those rows, infer the ESTO pair through the canonical
    9th->ESTO bridge so demand-side rows are not dropped from supply linking.
    """
    raw_esto = read_config_table(
        DIRECT_DEMAND_MAPPING_WORKBOOK,
        sheet_name=DIRECT_DEMAND_ESTO_MAPPING_SHEET,
        dtype=str,
    ).fillna("")
    raw_ninth = read_config_table(
        DIRECT_DEMAND_MAPPING_WORKBOOK,
        sheet_name=DIRECT_DEMAND_NINTH_MAPPING_SHEET,
        dtype=str,
    ).fillna("")
    canonical = _read_config_table_ref(BALANCE_DEMAND_NINTH_TO_ESTO_MAPPING, dtype=str).fillna("")

    required_esto = ["leap_sector_name_full_path", "raw_leap_fuel_name", "esto_flow", "esto_product"]
    required_ninth = ["leap_sector_name_full_path", "raw_leap_fuel_name", "ninth_sector", "ninth_fuel"]
    required_canonical = ["9th_sector", "9th_fuel", "esto_flow", "esto_product"]
    missing_esto = [col for col in required_esto if col not in raw_esto.columns]
    missing_ninth = [col for col in required_ninth if col not in raw_ninth.columns]
    missing_canonical = [col for col in required_canonical if col not in canonical.columns]
    if missing_esto or missing_ninth or missing_canonical:
        raise KeyError(
            "Cannot build augmented balance-demand mappings because required columns are missing: "
            f"esto={missing_esto}, ninth={missing_ninth}, canonical={missing_canonical}"
        )

    active_esto = raw_esto.copy()
    active_ninth = raw_ninth.copy()
    for frame in [active_esto, active_ninth]:
        if "remove_row" not in frame.columns:
            frame["remove_row"] = False
        if "duplicate_to_remove" not in frame.columns:
            frame["duplicate_to_remove"] = False
    active_esto = active_esto[
        ~active_esto["remove_row"].map(_truthy_flag)
        & ~active_esto["duplicate_to_remove"].map(_truthy_flag)
    ].copy()
    active_ninth = active_ninth[
        ~active_ninth["remove_row"].map(_truthy_flag)
        & ~active_ninth["duplicate_to_remove"].map(_truthy_flag)
    ].copy()

    for col in required_esto:
        active_esto[col] = active_esto[col].fillna("").astype(str).str.strip()
    for col in required_ninth:
        active_ninth[col] = active_ninth[col].fillna("").astype(str).str.strip()
    for col in required_canonical:
        canonical[col] = canonical[col].fillna("").astype(str).str.strip()

    existing_keys = set(
        active_esto.loc[
            active_esto["leap_sector_name_full_path"].ne("")
            & active_esto["raw_leap_fuel_name"].ne("")
            & active_esto["esto_flow"].ne("")
            & active_esto["esto_product"].ne(""),
            ["leap_sector_name_full_path", "raw_leap_fuel_name"],
        ].itertuples(index=False, name=None)
    )

    candidates = active_ninth[
        active_ninth["leap_sector_name_full_path"].ne("")
        & active_ninth["raw_leap_fuel_name"].ne("")
        & active_ninth["ninth_sector"].ne("")
        & active_ninth["ninth_fuel"].ne("")
        & active_ninth["ninth_sector"].map(_is_demand_sector_mapping)
    ].copy()
    if "leap_is_subtotal" in candidates.columns:
        candidates = candidates[~candidates["leap_is_subtotal"].map(_truthy_flag)].copy()
    if "ninth_pair_is_subtotal" in candidates.columns:
        candidates = candidates[~candidates["ninth_pair_is_subtotal"].map(_truthy_flag)].copy()
    if candidates.empty:
        augmented_path = _resolve(RESULTS_CHECKS_DIR) / "supply_reconciliation_augmented_balance_demand_mappings.xlsx"
        augmented_path.parent.mkdir(parents=True, exist_ok=True)
        with pd.ExcelWriter(augmented_path) as writer:
            raw_esto.to_excel(writer, sheet_name=DIRECT_DEMAND_ESTO_MAPPING_SHEET, index=False)
            raw_ninth.to_excel(writer, sheet_name=DIRECT_DEMAND_NINTH_MAPPING_SHEET, index=False)
        return augmented_path

    candidates["_source_key"] = list(
        candidates[["leap_sector_name_full_path", "raw_leap_fuel_name"]].itertuples(index=False, name=None)
    )
    candidates = candidates[~candidates["_source_key"].isin(existing_keys)].copy()
    inferred = candidates.merge(
        canonical[required_canonical].drop_duplicates(),
        left_on=["ninth_sector", "ninth_fuel"],
        right_on=["9th_sector", "9th_fuel"],
        how="left",
        suffixes=("", "_canonical"),
    )
    inferred = inferred[
        inferred["esto_flow"].fillna("").astype(str).str.strip().ne("")
        & inferred["esto_product"].fillna("").astype(str).str.strip().ne("")
    ].copy()
    inferred = inferred.drop_duplicates(
        subset=["leap_sector_name_full_path", "raw_leap_fuel_name", "esto_flow", "esto_product"]
    )

    inferred_rows = _build_inferred_esto_rows(
        inferred[["leap_sector_name_full_path", "raw_leap_fuel_name", "esto_flow", "esto_product"]],
        raw_esto.columns,
        default_note=(
            "Runtime inferred for supply_reconciliation from leap_combined_ninth "
            "+ ninth_pairs_to_esto_pairs."
        ),
    )

    # For demand rows the canonical 9th->ESTO bridge could not resolve (e.g. the
    # Freight road/Passenger road leaves, which have leap_combined_ninth rows but
    # no leap_combined_esto rows at any level), fall back to the maintained rollup
    # rules: roll the LEAP identity to a pre-built rollup target (e.g. "Road") and
    # look up that target's ESTO pair. General over all three rollup sheets, not
    # Road-specific — see _resolve_demand_esto_pairs_via_rollups.
    resolved_keys = set(
        inferred[["leap_sector_name_full_path", "raw_leap_fuel_name"]]
        .itertuples(index=False, name=None)
    )
    unresolved = candidates[~candidates["_source_key"].isin(resolved_keys)].copy()
    rollup_pairs = _resolve_demand_esto_pairs_via_rollups(
        unresolved,
        esto_reference=active_esto,
        canonical=canonical,
    )
    rollup_rows = _build_inferred_esto_rows(rollup_pairs, raw_esto.columns, default_note="")
    if not rollup_pairs.empty:
        still_missing = unresolved[
            ~unresolved["_source_key"].isin(
                set(rollup_pairs[["leap_sector_name_full_path", "raw_leap_fuel_name"]].itertuples(index=False, name=None))
            )
        ]
    else:
        still_missing = unresolved
    if not still_missing.empty:
        sample = (
            still_missing[["leap_sector_name_full_path", "raw_leap_fuel_name"]]
            .drop_duplicates()
            .head(10)
            .itertuples(index=False, name=None)
        )
        print(
            "[WARN] "
            f"{still_missing[['leap_sector_name_full_path', 'raw_leap_fuel_name']].drop_duplicates().shape[0]} "
            "demand LEAP sector/fuel key(s) have no direct ESTO pair, no canonical "
            "9th->ESTO bridge, and no active rollup rule with a pre-built rolled "
            f"target. Examples: {list(sample)}"
        )

    augmented_esto = pd.concat([raw_esto, inferred_rows, rollup_rows], ignore_index=True, sort=False)
    for cardinality_col in ["pair_mapping_cardinality", "fuel_mapping_cardinality", "sector_mapping_cardinality"]:
        if cardinality_col in augmented_esto.columns:
            augmented_esto[cardinality_col] = ""
    augmented_path = _resolve(RESULTS_CHECKS_DIR) / "supply_reconciliation_augmented_balance_demand_mappings.xlsx"
    augmented_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(augmented_path) as writer:
        augmented_esto.to_excel(writer, sheet_name=DIRECT_DEMAND_ESTO_MAPPING_SHEET, index=False)
        raw_ninth.to_excel(writer, sheet_name=DIRECT_DEMAND_NINTH_MAPPING_SHEET, index=False)
    if not inferred_rows.empty or not rollup_rows.empty:
        print(
            "[INFO] Added "
            f"{len(inferred_rows)} canonical-bridge and {len(rollup_rows)} rollup-resolved "
            "runtime-inferred demand LEAP->ESTO mapping row(s) for balance-demand "
            f"conversion. See {augmented_path}."
        )
    return augmented_path


def _build_inferred_esto_rows(
    pairs: pd.DataFrame,
    template_columns,
    *,
    default_note: str,
) -> pd.DataFrame:
    """Shape resolved (leap_sector, leap_fuel, esto_flow, esto_product) pairs as ESTO sheet rows."""
    template_columns = list(template_columns)
    if pairs is None or pairs.empty:
        return pd.DataFrame(columns=template_columns)
    pairs = pairs.reset_index(drop=True)
    rows = pd.DataFrame("", index=range(len(pairs)), columns=template_columns)
    for col in template_columns:
        if col in pairs.columns:
            rows[col] = pairs[col].values
    if "leap_sector_name_original" in rows.columns:
        rows["leap_sector_name_original"] = pairs["leap_sector_name_full_path"].values
    for flag_col in ["leap_is_subtotal", "esto_pair_is_subtotal", "subtotal_mismatch_is_ok", "remove_row"]:
        if flag_col in rows.columns:
            rows[flag_col] = False
    if "Note" in rows.columns:
        rows["Note"] = pairs["Note"].values if "Note" in pairs.columns else default_note
    return rows


def _resolve_demand_esto_pairs_via_rollups(
    unresolved: pd.DataFrame,
    *,
    esto_reference: pd.DataFrame,
    canonical: pd.DataFrame,
) -> pd.DataFrame:
    """Resolve missing demand ESTO pairs through the maintained rollup rules.

    General resolver over every active row in ``leap_rollup_rules`` /
    ``ninth_rollup_rules`` / ``esto_rollup_rules`` (gated only by each row's own
    ``include``/``rollup_context`` fields, using mapping_rollups semantics — no
    separate allowlist). For a LEAP demand ``(sector, fuel)`` with no direct
    leaf-level ESTO pair, roll the LEAP identity to a maintained rollup target
    (e.g. ``Freight road`` -> ``Road``, keeping the original fuel) and look up
    that target's pre-built combined-sheet ESTO pair. If the LEAP axis does not
    resolve, fall back to rolling the 9th identity via ``ninth_rollup_rules`` and
    bridging through ``ninth_pairs_to_esto_pairs``; failing that, roll the direct
    9th->ESTO leaf pair to a maintained parent via ``esto_rollup_rules`` when that
    parent is a real combined-sheet ESTO target. All three rollup sheets are thus
    consulted. Proven by the Road transport case but not scoped to it.

    Rows that cannot be resolved are omitted; the caller reports them.
    """
    from codebase.mapping_tools import mapping_rollups as mr

    columns = ["leap_sector_name_full_path", "raw_leap_fuel_name", "esto_flow", "esto_product", "Note"]
    if unresolved is None or unresolved.empty:
        return pd.DataFrame(columns=columns)

    # Read rollup sheets directly (never mr.read_rollup_rules, which may save the
    # master workbook — outlook_mappings_master.xlsx must not be modified here).
    def _read_rollup_sheet(sheet_name: str) -> pd.DataFrame:
        expected = mr.ROLLUP_SHEET_COLUMNS[sheet_name]
        try:
            frame = read_config_table(DIRECT_DEMAND_MAPPING_WORKBOOK, sheet_name=sheet_name, dtype=object).fillna("")
        except Exception:
            return pd.DataFrame(columns=expected)
        for column in expected:
            if column not in frame.columns:
                frame[column] = ""
        return frame

    leap_rules = mr.active_rollup_rules(_read_rollup_sheet("leap_rollup_rules"), "leap_to_esto")
    ninth_rules = mr.active_rollup_rules(_read_rollup_sheet("ninth_rollup_rules"), "ninth_to_esto")
    esto_rules = mr.active_rollup_rules(_read_rollup_sheet("esto_rollup_rules"), "ninth_to_esto")

    # Pre-built combined-sheet ESTO targets: (leap_sector, leap_fuel) -> (flow, product).
    esto_ref = esto_reference.copy()
    for col in ["leap_sector_name_full_path", "raw_leap_fuel_name", "esto_flow", "esto_product"]:
        esto_ref[col] = esto_ref[col].fillna("").astype(str).str.strip()
    for subtotal_col in ["leap_is_subtotal", "esto_pair_is_subtotal"]:
        if subtotal_col in esto_ref.columns:
            esto_ref = esto_ref[~esto_ref[subtotal_col].map(_truthy_flag)]
    esto_ref = esto_ref[esto_ref["esto_flow"].ne("") & esto_ref["esto_product"].ne("")]
    esto_lookup: dict[tuple[str, str], tuple[str, str]] = {}
    real_esto_pairs: set[tuple[str, str]] = set()
    for row in esto_ref.itertuples(index=False):
        key = (mr.normalise_key(row.leap_sector_name_full_path), mr.normalise_key(row.raw_leap_fuel_name))
        esto_lookup.setdefault(key, (row.esto_flow, row.esto_product))
        real_esto_pairs.add((mr.normalise_key(row.esto_flow), mr.normalise_key(row.esto_product)))

    # 9th -> ESTO canonical bridge for the ninth-axis fallback.
    canon = canonical.copy()
    for col in ["9th_sector", "9th_fuel", "esto_flow", "esto_product"]:
        canon[col] = canon[col].fillna("").astype(str).str.strip()
    canon = canon[canon["esto_flow"].ne("") & canon["esto_product"].ne("")]
    ninth_esto_lookup: dict[tuple[str, str], tuple[str, str]] = {}
    for sec, fuel, flow, product in zip(canon["9th_sector"], canon["9th_fuel"], canon["esto_flow"], canon["esto_product"]):
        ninth_esto_lookup.setdefault((mr.normalise_key(sec), mr.normalise_key(fuel)), (flow, product))

    def _roll_identity(flow_value: str, product_value: str, rules_df: pd.DataFrame, sheet_name: str) -> list[tuple[str, str, str]]:
        """Return best-first [(rolled_flow, rolled_product, note)] for exact-or-descendant flow matches."""
        if rules_df.empty:
            return []
        cols = mr.rollup_columns_for_sheet(sheet_name)
        flow_norm = mr.normalise_key(flow_value)
        ranked: list[tuple[float, int, int, str, str, str]] = []
        for _, rule in rules_df.iterrows():
            input_flow = mr.normalise_key(rule.get(cols["input_flow"], ""))
            if input_flow in {"", "*", "all"}:
                flow_spec = 3
            elif flow_norm == input_flow:
                flow_spec = 1
            elif flow_norm.startswith(input_flow + "/"):
                flow_spec = 2
            else:
                continue
            if not mr.value_matches(rule.get(cols["input_product"], ""), product_value):
                continue
            product_spec = 1 if mr.normalise_key(rule.get(cols["input_product"], "")) not in {"", "*", "all"} else 2
            rolled_flow = mr.clean_text(rule.get(cols["rolled_flow"], "")) or mr.clean_text(flow_value)
            rolled_product = mr.clean_text(rule.get(cols["rolled_product"], "")) or mr.clean_text(product_value)
            note = f"{mr.clean_text(rule.get(cols['input_flow'], '')) or '*'} -> {rolled_flow}"
            ranked.append((mr.parse_priority(rule.get("priority", "")), flow_spec, product_spec, rolled_flow, rolled_product, note))
        ranked.sort(key=lambda item: (item[0], item[1], item[2]))
        return [(item[3], item[4], item[5]) for item in ranked]

    resolved_rows: list[dict[str, str]] = []
    cache: dict[tuple[str, str, str, str], tuple[str, str, str] | None] = {}
    key_cols = {name: idx for idx, name in enumerate(unresolved.columns)}
    for row in unresolved.itertuples(index=False, name=None):
        sector = str(row[key_cols["leap_sector_name_full_path"]]).strip()
        fuel = str(row[key_cols["raw_leap_fuel_name"]]).strip()
        ninth_sector = str(row[key_cols.get("ninth_sector", -1)]).strip() if "ninth_sector" in key_cols else ""
        ninth_fuel = str(row[key_cols.get("ninth_fuel", -1)]).strip() if "ninth_fuel" in key_cols else ""
        cache_key = (sector, fuel, ninth_sector, ninth_fuel)
        if cache_key not in cache:
            resolved: tuple[str, str, str] | None = None
            for rolled_sector, rolled_fuel, note in _roll_identity(sector, fuel, leap_rules, "leap_rollup_rules"):
                pair = esto_lookup.get((mr.normalise_key(rolled_sector), mr.normalise_key(rolled_fuel)))
                if pair:
                    resolved = (pair[0], pair[1], f"leap_rollup:{note}")
                    break
            if resolved is None and ninth_sector:
                for rolled_sector, rolled_fuel, note in _roll_identity(ninth_sector, ninth_fuel, ninth_rules, "ninth_rollup_rules"):
                    pair = ninth_esto_lookup.get((mr.normalise_key(rolled_sector), mr.normalise_key(rolled_fuel)))
                    if pair:
                        resolved = (pair[0], pair[1], f"ninth_rollup:{note}")
                        break
            if resolved is None and ninth_sector:
                # ESTO axis: a direct (unrolled) 9th->ESTO bridge can yield a leaf
                # ESTO pair that is not itself a combined-sheet target; roll it via
                # esto_rollup_rules to the maintained parent target and accept it
                # only if that parent exists as a real combined ESTO pair.
                direct = ninth_esto_lookup.get((mr.normalise_key(ninth_sector), mr.normalise_key(ninth_fuel)))
                if direct:
                    esto_candidates = [(direct[0], direct[1], "")] + _roll_identity(
                        direct[0], direct[1], esto_rules, "esto_rollup_rules"
                    )
                    for cand_flow, cand_product, note in esto_candidates:
                        if (mr.normalise_key(cand_flow), mr.normalise_key(cand_product)) in real_esto_pairs:
                            resolved = (cand_flow, cand_product, f"esto_rollup:{note}" if note else "esto_direct_bridge")
                            break
            cache[cache_key] = resolved
        resolved = cache[cache_key]
        if resolved:
            resolved_rows.append(
                {
                    "leap_sector_name_full_path": sector,
                    "raw_leap_fuel_name": fuel,
                    "esto_flow": resolved[0],
                    "esto_product": resolved[1],
                    "Note": (
                        "Runtime inferred for supply_reconciliation via rollup rule "
                        f"({resolved[2]})."
                    ),
                }
            )
    if not resolved_rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(resolved_rows, columns=columns).drop_duplicates(
        subset=["leap_sector_name_full_path", "raw_leap_fuel_name", "esto_flow", "esto_product"]
    )


def _annotate_balance_demand_issue_scope(balance_demand_issues: pd.DataFrame) -> pd.DataFrame:
    """Mark which balance-demand mapping issues can affect demand-side inputs."""
    if balance_demand_issues is None or balance_demand_issues.empty:
        return balance_demand_issues.copy()

    issues = balance_demand_issues.copy()
    issues["mapping_key_sector"] = issues.get("mapping_key_sector", "").fillna("").astype(str).str.strip()
    issues["mapping_key_fuel"] = issues.get("mapping_key_fuel", "").fillna("").astype(str).str.strip()
    issues["leap_sector_name_full_path"] = (
        issues.get("leap_sector_name_full_path", "").fillna("").astype(str).str.strip()
    )
    issues["leap_product_name"] = issues.get("leap_product_name", "").fillna("").astype(str).str.strip()
    issues["issue_sector_key"] = issues["mapping_key_sector"].where(
        issues["mapping_key_sector"].ne(""),
        issues["leap_sector_name_full_path"],
    )
    issues["issue_fuel_key"] = issues["mapping_key_fuel"].where(
        issues["mapping_key_fuel"].ne(""),
        issues["leap_product_name"],
    )
    issues["issue_fuel_is_non_actionable"] = issues["issue_fuel_key"].map(_is_non_actionable_demand_fuel)

    try:
        active_ninth = _load_active_direct_demand_mapping_sheet(DIRECT_DEMAND_NINTH_MAPPING_SHEET)
    except Exception as exc:
        issues["demand_relevant"] = True
        issues.loc[issues["issue_fuel_is_non_actionable"], "demand_relevant"] = False
        issues["demand_relevance_basis"] = f"fallback_keep_all:{type(exc).__name__}"
        issues.loc[issues["issue_fuel_is_non_actionable"], "demand_relevance_basis"] = (
            "excluded_non_actionable_fuel"
        )
        return issues

    required_cols = ["leap_sector_name_full_path", "raw_leap_fuel_name", "ninth_sector"]
    missing_cols = [col for col in required_cols if col not in active_ninth.columns]
    if missing_cols:
        issues["demand_relevant"] = True
        issues.loc[issues["issue_fuel_is_non_actionable"], "demand_relevant"] = False
        issues["demand_relevance_basis"] = "fallback_keep_all:missing_ninth_columns"
        issues.loc[issues["issue_fuel_is_non_actionable"], "demand_relevance_basis"] = (
            "excluded_non_actionable_fuel"
        )
        return issues

    ninth_scope = active_ninth[required_cols].copy()
    for col in required_cols:
        ninth_scope[col] = ninth_scope[col].fillna("").astype(str).str.strip()
    ninth_scope["ninth_sector_is_demand"] = ninth_scope["ninth_sector"].map(_is_demand_sector_mapping)

    pair_scope = (
        ninth_scope.groupby(["leap_sector_name_full_path", "raw_leap_fuel_name"], dropna=False, as_index=False)[
            "ninth_sector_is_demand"
        ]
        .max()
        .rename(
            columns={
                "leap_sector_name_full_path": "issue_sector_key",
                "raw_leap_fuel_name": "issue_fuel_key",
                "ninth_sector_is_demand": "pair_is_demand",
            }
        )
    )
    sector_scope = (
        ninth_scope.groupby("leap_sector_name_full_path", dropna=False, as_index=False)["ninth_sector_is_demand"]
        .max()
        .rename(
            columns={
                "leap_sector_name_full_path": "issue_sector_key",
                "ninth_sector_is_demand": "sector_is_demand",
            }
        )
    )

    issues = issues.merge(pair_scope, on=["issue_sector_key", "issue_fuel_key"], how="left")
    issues = issues.merge(sector_scope, on="issue_sector_key", how="left")
    issues["pair_scope_matched"] = issues["pair_is_demand"].notna()
    issues["sector_scope_matched"] = issues["sector_is_demand"].notna()
    issues["pair_is_demand"] = issues["pair_is_demand"].fillna(False).astype(bool)
    issues["sector_is_demand"] = issues["sector_is_demand"].fillna(False).astype(bool)

    issues["demand_relevant"] = False
    issues.loc[issues["pair_scope_matched"], "demand_relevant"] = issues.loc[
        issues["pair_scope_matched"], "pair_is_demand"
    ]
    sector_only_mask = ~issues["pair_scope_matched"] & issues["sector_scope_matched"]
    issues.loc[sector_only_mask, "demand_relevant"] = issues.loc[sector_only_mask, "sector_is_demand"]

    issues["demand_relevance_basis"] = "unclassified_non_demand"
    issues.loc[issues["pair_scope_matched"] & issues["pair_is_demand"], "demand_relevance_basis"] = (
        "pair_match_demand_sector"
    )
    issues.loc[issues["pair_scope_matched"] & ~issues["pair_is_demand"], "demand_relevance_basis"] = (
        "pair_match_non_demand_sector"
    )
    issues.loc[sector_only_mask & issues["sector_is_demand"], "demand_relevance_basis"] = (
        "sector_match_demand_sector"
    )
    issues.loc[sector_only_mask & ~issues["sector_is_demand"], "demand_relevance_basis"] = (
        "sector_match_non_demand_sector"
    )

    issues.loc[issues["issue_fuel_is_non_actionable"], "demand_relevant"] = False
    issues.loc[issues["issue_fuel_is_non_actionable"], "demand_relevance_basis"] = (
        "excluded_non_actionable_fuel"
    )
    return issues


def _mapping_priority_rank(full_path: object) -> tuple[int, int, str]:
    text = str(full_path or "").strip()
    return (text.count("/"), len(text), text.lower())


def _pick_single_mapping_value(values: pd.Series, *, preferred: object = "") -> str:
    unique_values = sorted({str(value or "").strip() for value in values if str(value or "").strip()})
    if not unique_values:
        return ""
    preferred_text = str(preferred or "").strip()
    if preferred_text and preferred_text in unique_values:
        return preferred_text
    return unique_values[0]


def _build_codebook_name_to_esto_flow_lookup(codebook_path: Path | str) -> dict[str, str]:
    del codebook_path
    try:
        codebook = load_leap_display_names().fillna("")
    except Exception:
        return {}
    lookup: dict[str, str] = {}
    for _, row in codebook.iterrows():
        if str(row.get("code_type", "")).strip().lower() != "esto_flow":
            continue
        esto_label = str(row.get("code", "")).strip()
        name = str(row.get("leap_display_name", "") or row.get("auto_name", "")).strip()
        if name and esto_label:
            lookup[name.lower()] = esto_label
    return lookup


def _build_direct_demand_mapping_status(
    *,
    sheet_map: pd.DataFrame,
    leap_long: pd.DataFrame,
) -> pd.DataFrame:
    """Build a minimal mapping-status table from leap_combined_ninth/esto."""
    active_esto = _load_active_direct_demand_mapping_sheet(DIRECT_DEMAND_ESTO_MAPPING_SHEET)
    active_ninth = _load_active_direct_demand_mapping_sheet(DIRECT_DEMAND_NINTH_MAPPING_SHEET)

    required_esto = ["leap_sector_name_full_path", "raw_leap_fuel_name", "esto_flow", "esto_product"]
    required_ninth = ["leap_sector_name_full_path", "raw_leap_fuel_name", "ninth_sector", "ninth_fuel"]
    missing_esto = [col for col in required_esto if col not in active_esto.columns]
    missing_ninth = [col for col in required_ninth if col not in active_ninth.columns]
    if missing_esto:
        raise KeyError(
            f"{DIRECT_DEMAND_ESTO_MAPPING_SHEET} is missing required columns for supply_reconciliation: {missing_esto}"
        )
    if missing_ninth:
        raise KeyError(
            f"{DIRECT_DEMAND_NINTH_MAPPING_SHEET} is missing required columns for supply_reconciliation: {missing_ninth}"
        )

    join_cols = ["leap_sector_name_full_path", "raw_leap_fuel_name"]
    merged = active_ninth[required_ninth].merge(
        active_esto[required_esto],
        on=join_cols,
        how="inner",
    ).drop_duplicates()
    if merged.empty:
        raise RuntimeError(
            "Direct demand mapping join between leap_combined_ninth and leap_combined_esto returned no active rows."
        )

    leap_sheet_fuels = leap_long[["sheet_name", "fuel_label"]].drop_duplicates().copy()
    leap_sheet_fuels["sheet_name"] = leap_sheet_fuels["sheet_name"].astype(str).str.strip()
    leap_sheet_fuels["fuel_label"] = leap_sheet_fuels["fuel_label"].astype(str).str.strip()
    # Rewrite known LEAP-model spelling gaps to the mapping-sheet spelling before
    # the string-key join against leap_combined_ninth/leap_combined_esto. Safe to
    # apply eagerly: an entry only rewrites a LEAP label that would not otherwise
    # match (a correctly spelled label is not a KNOWN_LEAP_LABEL_EXCEPTIONS key).
    leap_sheet_fuels["fuel_label"] = leap_sheet_fuels["fuel_label"].replace(
        KNOWN_LEAP_LABEL_EXCEPTIONS
    )

    demand_sheet_map = sheet_map.copy()
    demand_sheet_map["sheet_name"] = demand_sheet_map["sheet_name"].astype(str).str.strip()
    demand_sheet_map["sector_code_9th"] = demand_sheet_map["sector_code_9th"].astype(str).str.strip()
    if "sector_name" not in demand_sheet_map.columns:
        demand_sheet_map["sector_name"] = ""
    demand_sheet_map["sector_name"] = demand_sheet_map["sector_name"].astype(str).str.strip()
    demand_sheet_map = demand_sheet_map[
        demand_sheet_map["sector_code_9th"].map(_is_demand_sector_mapping)
    ][["sheet_name", "sector_code_9th", "sector_name"]].drop_duplicates()

    leap_sheet_fuels = leap_sheet_fuels.merge(demand_sheet_map, on="sheet_name", how="inner")
    if leap_sheet_fuels.empty:
        return pd.DataFrame(
            columns=[
                "sheet",
                "fuel_label",
                "sector_code_9th",
                "ninth_fuel_code",
                "esto_flow",
                "esto_product",
                "mapping_source",
                "mapping_note",
            ]
        )

    fuel_aliases = load_fuel_aliases(
        _resolve(DEFAULT_BACKUP_LEAP_MAPPINGS) if DEFAULT_BACKUP_LEAP_MAPPINGS else None,
        _resolve(DEFAULT_CODEBOOK),
    )
    sector_flow_lookup = build_sector_to_esto_flow_lookup(_resolve(DEFAULT_CODEBOOK))
    name_to_flow_lookup = _build_codebook_name_to_esto_flow_lookup(_resolve(DEFAULT_CODEBOOK))

    merged["raw_leap_fuel_name"] = merged["raw_leap_fuel_name"].astype(str).str.strip()
    merged["ninth_sector"] = merged["ninth_sector"].astype(str).str.strip()
    merged["ninth_fuel"] = merged["ninth_fuel"].astype(str).str.strip()
    merged["esto_flow"] = merged["esto_flow"].astype(str).str.strip()
    merged["esto_product"] = merged["esto_product"].astype(str).str.strip()
    merged["leap_sector_name_full_path"] = merged["leap_sector_name_full_path"].astype(str).str.strip()
    active_ninth["raw_leap_fuel_name"] = active_ninth["raw_leap_fuel_name"].astype(str).str.strip()
    active_ninth["ninth_sector"] = active_ninth["ninth_sector"].astype(str).str.strip()
    active_ninth["ninth_fuel"] = active_ninth["ninth_fuel"].astype(str).str.strip()
    active_esto["raw_leap_fuel_name"] = active_esto["raw_leap_fuel_name"].astype(str).str.strip()
    active_esto["esto_flow"] = active_esto["esto_flow"].astype(str).str.strip()
    active_esto["esto_product"] = active_esto["esto_product"].astype(str).str.strip()

    sector_flow_fallbacks = (
        merged[["ninth_sector", "esto_flow"]]
        .drop_duplicates()
        .groupby("ninth_sector", dropna=False)["esto_flow"]
        .apply(list)
        .to_dict()
    )
    fuel_product_fallbacks = (
        active_esto[["raw_leap_fuel_name", "esto_product"]]
        .drop_duplicates()
        .groupby("raw_leap_fuel_name", dropna=False)["esto_product"]
        .apply(list)
        .to_dict()
    )

    rows: list[dict[str, object]] = []
    for row in leap_sheet_fuels.itertuples(index=False):
        sector_codes = _split_sector_codes(row.sector_code_9th)
        if not sector_codes:
            sector_codes = [str(row.sector_code_9th)]

        exact_ninth = active_ninth[
            active_ninth["ninth_sector"].isin(sector_codes)
            & active_ninth["raw_leap_fuel_name"].eq(str(row.fuel_label))
        ].copy()
        matched = merged[
            merged["ninth_sector"].isin(sector_codes)
            & merged["raw_leap_fuel_name"].eq(str(row.fuel_label))
        ].copy()
        if exact_ninth.empty and matched.empty:
            rows.append(
                {
                    "sheet": str(row.sheet_name),
                    "fuel_label": str(row.fuel_label),
                    "sector_code_9th": str(row.sector_code_9th),
                    "ninth_fuel_code": "",
                    "esto_flow": "",
                    "esto_product": "",
                    "mapping_source": "",
                    "mapping_note": "no active leap_combined_ninth/leap_combined_esto match for sheet fuel",
                }
            )
            continue

        if not matched.empty:
            matched = matched.sort_values(
                by="leap_sector_name_full_path",
                key=lambda series: series.map(_mapping_priority_rank),
            )
        preferred_flow = ""
        if not matched.empty and matched["esto_flow"].nunique(dropna=True) > 1:
            preferred_flow = next(
                (
                    str(sector_flow_lookup.get(str(code).strip().lower(), "")).strip()
                    for code in sector_codes
                    if str(sector_flow_lookup.get(str(code).strip().lower(), "")).strip()
                ),
                "",
            )

        chosen_ninth_fuel = _pick_single_mapping_value(
            exact_ninth["ninth_fuel"] if not exact_ninth.empty else matched["ninth_fuel"]
        )
        if not chosen_ninth_fuel and str(row.fuel_label).strip().lower() == "total":
            chosen_ninth_fuel = "19_total"
        chosen_esto_product = _pick_single_mapping_value(matched["esto_product"])
        if not chosen_esto_product:
            chosen_esto_product = _pick_single_mapping_value(
                pd.Series(fuel_product_fallbacks.get(str(row.fuel_label), []), dtype="object")
            )
        if not chosen_esto_product:
            chosen_esto_product = str(
                map_fuel_label(str(row.fuel_label), fuel_aliases).get("esto_product", "")
            ).strip()
        if not chosen_esto_product and str(row.fuel_label).strip().lower() == "total":
            chosen_esto_product = "19 Total"

        chosen_esto_flow = _pick_single_mapping_value(
            matched["esto_flow"] if "esto_flow" in matched.columns else pd.Series(dtype="object"),
            preferred=preferred_flow,
        )
        if not chosen_esto_flow:
            fallback_flow_candidates: list[str] = []
            for code in sector_codes:
                fallback_flow_candidates.extend(
                    [str(item).strip() for item in sector_flow_fallbacks.get(str(code), []) if str(item).strip()]
                )
                codebook_flow = str(sector_flow_lookup.get(str(code).strip().lower(), "")).strip()
                if codebook_flow:
                    fallback_flow_candidates.append(codebook_flow)
            for name_candidate in [str(row.sheet_name).strip(), str(getattr(row, "sector_name", "")).strip()]:
                if name_candidate:
                    named_flow = str(name_to_flow_lookup.get(name_candidate.lower(), "")).strip()
                    if named_flow:
                        fallback_flow_candidates.append(named_flow)
            chosen_esto_flow = _pick_single_mapping_value(pd.Series(fallback_flow_candidates, dtype="object"))

        note_parts: list[str] = []
        if not matched.empty and matched["leap_sector_name_full_path"].nunique(dropna=True) > 1:
            note_parts.append(
                f"{int(matched['leap_sector_name_full_path'].nunique())} active LEAP paths share this demand sector/fuel mapping"
            )
        if not exact_ninth.empty and exact_ninth["ninth_fuel"].nunique(dropna=True) > 1:
            note_parts.append(
                "multiple ninth_fuel targets present; first stable active target selected"
            )
        if not matched.empty and matched["esto_flow"].nunique(dropna=True) > 1:
            note_parts.append(
                "multiple esto_flow targets present; first stable active target selected"
            )
        if not matched.empty and matched["esto_product"].nunique(dropna=True) > 1:
            note_parts.append(
                "multiple esto_product targets present; first stable active target selected"
            )
        if not exact_ninth.empty and matched.empty:
            note_parts.append("esto side fell back beyond direct leap_combined overlap")

        rows.append(
            {
                "sheet": str(row.sheet_name),
                "fuel_label": str(row.fuel_label),
                "sector_code_9th": str(row.sector_code_9th),
                "ninth_fuel_code": chosen_ninth_fuel,
                "esto_flow": chosen_esto_flow,
                "esto_product": chosen_esto_product,
                "mapping_source": "leap_combined_join",
                "mapping_note": "; ".join(note_parts),
            }
        )

    out = pd.DataFrame(rows).drop_duplicates(subset=["sheet", "fuel_label"], keep="first")
    return out.reset_index(drop=True)


def _load_direct_demand_reference_tables() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load ESTO and 9th reference tables without reusing old direct-demand mappings."""
    base_df, ninth_df = load_augmented_reference_tables(
        esto_path=_resolve(DIRECT_DEMAND_BASE_TABLE_PATH),
        ninth_path=_resolve(DIRECT_DEMAND_PROJECTION_TABLE_PATH),
        cache_dir=DIRECT_DEMAND_REFERENCE_CACHE_DIR,
        apply_esto_subtotal_map=False,
        filter_esto_subtotals_flag=False,
        filter_ninth_subtotals_flag=False,
    )
    return base_df, ninth_df


def _load_projection_only_ninth_table() -> pd.DataFrame:
    """Load only the 9th columns needed for projection-only demand fallback."""
    projection_path = _resolve(BALANCE_DEMAND_PROJECTION_TABLE_PATH)
    stable_cols = [
        "economy",
        "scenarios",
        "sectors",
        "sub1sectors",
        "sub2sectors",
        "sub3sectors",
        "sub4sectors",
        "fuels",
        "subfuels",
        "subtotal_results",
    ]
    year_cols = [str(year) for year in DIRECT_DEMAND_PROJECTION_YEARS if year <= FINAL_YEAR]
    header = pd.read_csv(projection_path, nrows=0)
    usecols = [col for col in [*stable_cols, *year_cols] if col in header.columns]
    return pd.read_csv(projection_path, usecols=usecols, low_memory=False)


def _build_projection_rows_from_ninth(
    mapping_status: pd.DataFrame,
    *,
    ninth_df: pd.DataFrame,
    scenarios: Iterable[str],
    projection_economy: str = DIRECT_DEMAND_PROJECTION_ECONOMY,
) -> pd.DataFrame:
    if mapping_status.empty or ninth_df.empty:
        return pd.DataFrame(columns=["economy", "scenario", "sheet", "fuel_label", "year", "value", "source"])

    scenario_map = {str(k).strip().lower(): str(v).strip() for k, v in DIRECT_DEMAND_SCENARIO_MAP.items()}
    scenario_labels_by_projection: dict[str, str] = {}
    for item in scenarios:
        label = str(item).strip()
        if not label:
            continue
        projection_label = scenario_map.get(label.lower(), label.lower()).strip().lower()
        if projection_label:
            scenario_labels_by_projection[projection_label] = label

    ninth = ninth_df.copy()
    ninth["economy"] = ninth["economy"].astype(str).str.strip()
    ninth["scenarios"] = ninth["scenarios"].astype(str).str.strip().str.lower()
    sector_cols = ["sectors", "sub1sectors", "sub2sectors", "sub3sectors", "sub4sectors"]
    fuel_cols = ["fuels", "subfuels"]
    for col in [*sector_cols, *fuel_cols]:
        ninth[col] = ninth[col].fillna("").astype(str).str.strip()

    def _resolve_deepest(tokens: pd.Series) -> str:
        values = [str(value).strip() for value in tokens.tolist() if str(value).strip() and str(value).strip().lower() != "x"]
        return values[-1] if values else ""

    ninth["ninth_sector"] = ninth[sector_cols].apply(_resolve_deepest, axis=1)
    ninth["ninth_fuel"] = ninth[fuel_cols].apply(_resolve_deepest, axis=1)
    if "subtotal_results" in ninth.columns:
        subtotal_mask = ninth["subtotal_results"].astype(str).str.strip().str.lower().isin({"true", "1", "yes"})
        ninth = ninth.loc[~subtotal_mask].copy()

    year_cols = [str(year) for year in DIRECT_DEMAND_PROJECTION_YEARS if str(year) in ninth.columns]
    if not year_cols:
        return pd.DataFrame(columns=["economy", "scenario", "sheet", "fuel_label", "year", "value", "source"])

    ninth_long = ninth[
        ["economy", "scenarios", "ninth_sector", "ninth_fuel", *year_cols]
    ].melt(
        id_vars=["economy", "scenarios", "ninth_sector", "ninth_fuel"],
        value_vars=year_cols,
        var_name="year",
        value_name="value",
    )
    ninth_long["year"] = pd.to_numeric(ninth_long["year"], errors="coerce").astype("Int64")
    ninth_long["value"] = pd.to_numeric(ninth_long["value"], errors="coerce")
    ninth_long = ninth_long[
        (ninth_long["economy"] == str(projection_economy).strip())
        & ninth_long["scenarios"].isin(scenario_labels_by_projection.keys())
        & ninth_long["year"].notna()
    ].copy()
    if ninth_long.empty:
        return pd.DataFrame(columns=["economy", "scenario", "sheet", "fuel_label", "year", "value", "source"])
    ninth_long["scenario"] = ninth_long["scenarios"].map(scenario_labels_by_projection)

    mapping_subset = mapping_status[
        ["sheet", "fuel_label", "sector_code_9th", "ninth_fuel_code"]
    ].copy()
    mapping_subset["sheet"] = mapping_subset["sheet"].astype(str).str.strip()
    mapping_subset["fuel_label"] = mapping_subset["fuel_label"].astype(str).str.strip()
    mapping_subset["sector_code_9th"] = mapping_subset["sector_code_9th"].astype(str).str.strip()
    mapping_subset["ninth_fuel_code"] = mapping_subset["ninth_fuel_code"].astype(str).str.strip()
    mapping_subset = mapping_subset[
        mapping_subset["sector_code_9th"].ne("")
        & mapping_subset["ninth_fuel_code"].ne("")
    ].drop_duplicates()
    if mapping_subset.empty:
        return pd.DataFrame(columns=["economy", "scenario", "sheet", "fuel_label", "year", "value", "source"])

    projection_rows = mapping_subset.merge(
        ninth_long,
        left_on=["sector_code_9th", "ninth_fuel_code"],
        right_on=["ninth_sector", "ninth_fuel"],
        how="inner",
    )
    if projection_rows.empty:
        return pd.DataFrame(columns=["economy", "scenario", "sheet", "fuel_label", "year", "value", "source"])

    projection_rows = projection_rows.rename(columns={"value": "value"})
    projection_rows["source"] = "projection"
    projection_rows = projection_rows[
        ["economy", "scenario", "sheet", "fuel_label", "year", "value", "source"]
    ].copy()
    return projection_rows.reset_index(drop=True)


def _collect_direct_demand_mapping_gaps(mapping_status: pd.DataFrame) -> pd.DataFrame:
    """Return unresolved direct-demand mapping rows that should fail after outputs are written."""
    base_columns = [
        "sheet",
        "fuel_label",
        "sector_code_9th",
        "ninth_fuel_code",
        "esto_flow",
        "esto_product",
        "mapping_source",
        "mapping_note",
        "gap_reason",
    ]
    if mapping_status is None or mapping_status.empty:
        return pd.DataFrame(columns=base_columns)

    work = mapping_status.copy()
    for col in base_columns[:-1]:
        if col not in work.columns:
            work[col] = ""
        work[col] = work[col].fillna("").astype(str).str.strip()

    work["mapping_note_lower"] = work["mapping_note"].str.lower()
    reasons: list[pd.Series] = []
    reasons.append(pd.Series("", index=work.index, dtype="object"))
    reasons[-1] = reasons[-1].mask(work["ninth_fuel_code"].eq(""), "missing_ninth_mapping")
    reasons[-1] = reasons[-1].mask(
        work["esto_flow"].eq(""),
        reasons[-1].where(reasons[-1].eq(""), reasons[-1] + "; ") + "missing_esto_flow_mapping",
    )
    reasons[-1] = reasons[-1].mask(
        work["esto_product"].eq(""),
        reasons[-1].where(reasons[-1].eq(""), reasons[-1] + "; ") + "missing_esto_product_mapping",
    )
    fallback_mask = work["mapping_note_lower"].str.contains(
        "fell back beyond direct leap_combined overlap",
        na=False,
    )
    reasons[-1] = reasons[-1].mask(
        fallback_mask,
        reasons[-1].where(reasons[-1].eq(""), reasons[-1] + "; ")
        + "exact_child_path_missing_in_leap_combined_esto",
    )
    work["gap_reason"] = reasons[-1].fillna("").astype(str).str.strip("; ").str.strip()
    gaps = work[work["gap_reason"].ne("")].copy()
    if gaps.empty:
        return pd.DataFrame(columns=base_columns)
    gaps = gaps[base_columns].drop_duplicates()
    gaps = gaps.sort_values(
        ["sheet", "fuel_label", "sector_code_9th", "gap_reason"],
        ascending=[True, True, True, True],
    ).reset_index(drop=True)
    return gaps


def _load_optional_json_dict(path: Path | str) -> dict[str, object]:
    """Load an optional JSON object config file, returning {} when absent."""
    resolved = _resolve(path)
    if not resolved.exists():
        return {}
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {resolved}, found {type(payload).__name__}.")
    return payload


def _build_balance_demand_scenario_map(scenarios: Iterable[str]) -> dict[str, str]:
    """Map workflow scenario labels to the lowercase balance projection labels."""
    scenario_map: dict[str, str] = {}
    for value in scenarios:
        label = str(value or "").strip()
        if not label:
            continue
        lowered = label.lower()
        if lowered in {"reference", "target"}:
            scenario_map[label] = lowered
    return scenario_map


def _compact_economy_code(economy: str) -> str:
    """Return the compact ESTO economy code used by the base-year table."""
    return str(economy or "").strip().replace("_", "")


def _resolve_balance_demand_workbooks_for_economy(economy: str) -> tuple[Path, Path]:
    """Return REF/TGT LEAP balance export workbooks for one economy."""
    economy_text = str(economy or "").strip()
    if not economy_text:
        raise ValueError("Balance-export economy cannot be blank.")
    if economy_text == DIRECT_DEMAND_PROJECTION_ECONOMY:
        return _resolve(BALANCE_DEMAND_REF_WORKBOOK_PATH), _resolve(BALANCE_DEMAND_TGT_WORKBOOK_PATH)
    ref_workbook = resolve_balance_export_workbook(
        economy=economy_text,
        scenario="REF",
        date_id=BALANCE_DEMAND_REF_BALANCE_EXPORT_DATE_ID,
        exports_root=BALANCE_DEMAND_EXPORTS_ROOT,
    )
    tgt_workbook = resolve_balance_export_workbook(
        economy=economy_text,
        scenario="TGT",
        date_id=BALANCE_DEMAND_TGT_BALANCE_EXPORT_DATE_ID,
        exports_root=BALANCE_DEMAND_EXPORTS_ROOT,
    )
    return ref_workbook, tgt_workbook


def _build_projection_only_mapping_status(balance_mapping_workbook: Path | str) -> pd.DataFrame:
    """Build demand mapping metadata directly from the augmented mapping workbook."""
    workbook = _resolve(balance_mapping_workbook)
    ninth = pd.read_excel(workbook, sheet_name=DIRECT_DEMAND_NINTH_MAPPING_SHEET).fillna("")
    esto = pd.read_excel(workbook, sheet_name=DIRECT_DEMAND_ESTO_MAPPING_SHEET).fillna("")
    required_ninth = ["leap_sector_name_full_path", "raw_leap_fuel_name", "ninth_sector", "ninth_fuel"]
    required_esto = ["leap_sector_name_full_path", "raw_leap_fuel_name", "esto_flow", "esto_product"]
    missing_ninth = [col for col in required_ninth if col not in ninth.columns]
    missing_esto = [col for col in required_esto if col not in esto.columns]
    if missing_ninth or missing_esto:
        raise KeyError(
            "Cannot build projection-only demand mappings. "
            f"Missing ninth columns={missing_ninth}; missing ESTO columns={missing_esto}."
        )

    for frame in (ninth, esto):
        if "remove_row" in frame.columns:
            frame["_remove_row_bool"] = frame["remove_row"].fillna(False).astype(str).str.strip().str.lower().isin(
                {"true", "1", "yes"}
            )
            frame.drop(frame[frame["_remove_row_bool"]].index, inplace=True)
            frame.drop(columns=["_remove_row_bool"], inplace=True)
        if "duplicate_to_remove" in frame.columns:
            frame["_duplicate_to_remove_bool"] = frame["duplicate_to_remove"].fillna(False).astype(str).str.strip().str.lower().isin(
                {"true", "1", "yes"}
            )
            frame.drop(frame[frame["_duplicate_to_remove_bool"]].index, inplace=True)
            frame.drop(columns=["_duplicate_to_remove_bool"], inplace=True)

    joined = ninth[required_ninth].merge(
        esto[required_esto],
        on=["leap_sector_name_full_path", "raw_leap_fuel_name"],
        how="inner",
    )
    if joined.empty:
        return pd.DataFrame(
            columns=["sheet", "fuel_label", "sector_code_9th", "ninth_fuel_code", "esto_flow", "esto_product"]
        )
    for col in joined.columns:
        joined[col] = joined[col].fillna("").astype(str).str.strip()
    joined = joined[
        joined["ninth_sector"].ne("")
        & joined["ninth_fuel"].ne("")
        & joined["esto_flow"].ne("")
        & joined["esto_product"].ne("")
    ].copy()
    out = pd.DataFrame(
        {
            "sector_code_9th": joined["ninth_sector"],
            "ninth_fuel_code": joined["ninth_fuel"],
            "esto_flow": joined["esto_flow"],
            "esto_product": joined["esto_product"],
            "mapping_source": "projection_only_mapping_workbook",
            "mapping_note": "",
        }
    )
    out = out.drop_duplicates(
        subset=["sector_code_9th", "ninth_fuel_code", "esto_flow", "esto_product"]
    ).reset_index(drop=True)
    out["sheet"] = out["esto_flow"]
    out["fuel_label"] = out["esto_product"]
    out["measure"] = "Energy balance (PJ)"
    return out[
        [
            "sheet",
            "fuel_label",
            "sector_code_9th",
            "ninth_fuel_code",
            "esto_flow",
            "esto_product",
            "measure",
            "mapping_source",
            "mapping_note",
        ]
    ]


def load_balance_demand_inputs(
    *,
    economies: Iterable[str],
    scenarios: Iterable[str],
    workbook_dir: Path | str = LEAP_RESULTS_TABLES_DIR,
    allow_projection_only_without_balance_exports: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build comparison_long + mapping_status in-memory from LEAP balance exports.

    When ``allow_projection_only_without_balance_exports`` is True (the
    baseline_seed pass), demand is always sourced from the 9th projection-only
    table for every economy, regardless of whether that economy already has
    LEAP balance export workbooks. LEAP's own exports are only compared
    against during the results_update pass.
    """
    economy_list = workflow_common.normalize_economies(economies or ECONOMIES)
    balance_scenarios = _filter_balance_scenarios(scenarios)
    scenario_map = _build_balance_demand_scenario_map(balance_scenarios)
    if not scenario_map:
        raise RuntimeError(
            "No balance-export demand scenarios remain after filtering non-balance "
            f"entries from {list(scenarios)}."
        )

    structure_config = build_esto_axis_structure_from_dashboard_template(BALANCE_DEMAND_CHART_NAVIGATION_GUIDE_PATH)
    known_issues = _load_optional_json_dict(BALANCE_DEMAND_KNOWN_ISSUES_CONFIG_PATH)
    balance_mapping_workbook = _build_augmented_balance_demand_mapping_workbook()

    scenario_set = {str(item).strip().lower() for item in balance_scenarios if str(item).strip()}
    comparison_long_parts: list[pd.DataFrame] = []
    mapping_status_parts: list[pd.DataFrame] = []
    issue_parts: list[pd.DataFrame] = []
    matching_diagnostics_parts: list[pd.DataFrame] = []
    projection_only_mapping_status: pd.DataFrame | None = None
    projection_ninth_df: pd.DataFrame | None = None

    def _projection_only_mapping_status() -> pd.DataFrame:
        nonlocal projection_only_mapping_status
        if projection_only_mapping_status is None:
            projection_only_mapping_status = _build_projection_only_mapping_status(balance_mapping_workbook)
        return projection_only_mapping_status.copy()

    def _projection_ninth_table() -> pd.DataFrame:
        nonlocal projection_ninth_df
        if projection_ninth_df is None:
            projection_ninth_df = _load_projection_only_ninth_table()
        return projection_ninth_df.copy()

    def _build_economy_demand(
        economy_text: str,
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        if allow_projection_only_without_balance_exports:
            # baseline_seed always sizes supply off the 9th projection-only demand,
            # never off a specific LEAP run's own balance export, even when one
            # exists for this economy. Comparing against a real LEAP export is the
            # results_update pass's job.
            mapping_status = _projection_only_mapping_status()
            comparison_long = _build_projection_rows_from_ninth(
                mapping_status,
                ninth_df=_projection_ninth_table(),
                scenarios=balance_scenarios,
                projection_economy=economy_text,
            )
            issues = pd.DataFrame()
            matching_diagnostics = pd.DataFrame()
            print(
                "[INFO] baseline_seed pass: using 9th projection-only demand for "
                f"{economy_text} (LEAP balance exports, if any, are ignored for this pass)."
            )
            return comparison_long, mapping_status, issues, matching_diagnostics

        ref_workbook_path, tgt_workbook_path = _resolve_balance_demand_workbooks_for_economy(economy_text)
        base_economy = (
            DIRECT_DEMAND_BASE_ECONOMY
            if economy_text == DIRECT_DEMAND_PROJECTION_ECONOMY
            else _compact_economy_code(economy_text)
        )

        conversion = convert_leap_balances_to_esto_long_table(
            ref_workbook_path=ref_workbook_path,
            tgt_workbook_path=tgt_workbook_path,
            template_sheet=BALANCE_DEMAND_TEMPLATE_SHEET,
            mapping_pairs_path=balance_mapping_workbook,
            codebook_path=BALANCE_DEMAND_CODEBOOK_PATH,
            structure_config=structure_config,
            known_issues=known_issues,
            projection_economy=economy_text,
            max_output_year=FINAL_YEAR,
            explicit_pair_mappings_only=True,
            allow_descendant_mapping_expansion=False,
        )
        comparison = build_balance_comparison_esto_axis(
            leap_long=conversion["leap_long"],
            mapping_status=conversion["mapping_status"],
            base_year=DIRECT_DEMAND_BASE_YEAR,
            projection_years=tuple(year for year in DIRECT_DEMAND_PROJECTION_YEARS if year <= FINAL_YEAR),
            base_economy=base_economy,
            projection_economy=economy_text,
            scenario_map=scenario_map,
            sheet_map_path=BALANCE_DEMAND_SHEET_MAP_PATH,
            backup_mappings_path=BALANCE_DEMAND_BACKUP_MAPPINGS_PATH,
            codebook_path=BALANCE_DEMAND_CODEBOOK_PATH,
            canonical_pairs_path=BALANCE_DEMAND_NINTH_TO_ESTO_MAPPING,
            explicit_mappings_path=BALANCE_DEMAND_EXPLICIT_MAPPINGS_PATH,
            explicit_reassignments_path=BALANCE_DEMAND_EXPLICIT_REASSIGNMENTS_PATH,
            synthetic_reference_rows_path=BALANCE_DEMAND_SYNTHETIC_REFERENCE_ROWS_PATH,
            esto_table_path=BALANCE_DEMAND_BASE_TABLE_PATH,
            projection_table_path=BALANCE_DEMAND_PROJECTION_TABLE_PATH,
            chart_navigation_guide_path=None,
            known_issues=known_issues,
        )

        issues = conversion["issues"].copy()
        matching_diagnostics = conversion.get("matching_diagnostics", pd.DataFrame()).copy()
        comparison_long = comparison["comparison_long"].copy()
        mapping_status = comparison["mapping_status"].copy()
        for frame in (comparison_long, mapping_status, issues, matching_diagnostics):
            if "economy" not in frame.columns:
                frame["economy"] = economy_text
        if scenario_set:
            comparison_long = comparison_long[
                comparison_long["scenario"].astype(str).str.strip().str.lower().isin(scenario_set)
            ].copy()
            if "scenario" in mapping_status.columns:
                mapping_status = mapping_status[
                    mapping_status["scenario"].astype(str).str.strip().str.lower().isin(scenario_set)
                ].copy()
            if "scenario" in issues.columns:
                issues = issues[
                    issues["scenario"].astype(str).str.strip().str.lower().isin(scenario_set)
                ].copy()
            if "scenario" in matching_diagnostics.columns:
                matching_diagnostics = matching_diagnostics[
                    matching_diagnostics["scenario"].astype(str).str.strip().str.lower().isin(scenario_set)
                ].copy()
        return comparison_long, mapping_status, issues, matching_diagnostics

    # Per-economy resilience: one economy's demand-mapping failure must not abort
    # the whole run's mapping load (which happens once, before the per-economy
    # export loop, so a raise here would kill output for every economy). With
    # THROW_ERROR_AFTER_RUN enabled, defer the error and skip that economy — it
    # simply contributes no demand rows, leaving its reconciliation degenerate,
    # while the other economies still build. With the flag off, this raises
    # immediately as before.
    for economy in economy_list:
        economy_text = str(economy or "").strip()
        try:
            economy_comparison_long, economy_mapping_status, economy_issues, economy_matching_diagnostics = (
                _build_economy_demand(economy_text)
            )
        except Exception as exc:
            workflow_common.defer_or_raise(
                exc, context=f"load_balance_demand_inputs:{economy_text}"
            )
            print(
                f"[WARN] load_balance_demand_inputs: skipping economy {economy_text} "
                "due to deferred error — it will contribute no demand rows, so its "
                "reconciliation output will be degenerate. Review before trusting it."
            )
            continue
        comparison_long_parts.append(economy_comparison_long)
        mapping_status_parts.append(economy_mapping_status)
        issue_parts.append(economy_issues)
        matching_diagnostics_parts.append(economy_matching_diagnostics)

    comparison_long = pd.concat(comparison_long_parts, ignore_index=True) if comparison_long_parts else pd.DataFrame()
    mapping_status = pd.concat(mapping_status_parts, ignore_index=True) if mapping_status_parts else pd.DataFrame()
    issues = pd.concat(issue_parts, ignore_index=True) if issue_parts else pd.DataFrame()
    matching_diagnostics = (
        pd.concat(matching_diagnostics_parts, ignore_index=True)
        if matching_diagnostics_parts
        else pd.DataFrame()
    )

    if "year" not in comparison_long.columns:
        comparison_long["year"] = pd.Series(dtype="Int64")
    if "value" not in comparison_long.columns:
        comparison_long["value"] = pd.Series(dtype="float")
    comparison_long["year"] = pd.to_numeric(comparison_long["year"], errors="coerce").astype("Int64")
    comparison_long["value"] = pd.to_numeric(comparison_long["value"], errors="coerce")
    return (
        comparison_long.reset_index(drop=True),
        mapping_status.reset_index(drop=True),
        issues.reset_index(drop=True),
        matching_diagnostics.reset_index(drop=True),
    )


def load_direct_leap_demand_inputs(
    *,
    economies: Iterable[str],
    scenarios: Iterable[str],
    workbook_dir: Path | str = LEAP_RESULTS_TABLES_DIR,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Backward-compatible alias for the balance-export demand loader."""
    comparison_long, mapping_status, _, _ = load_balance_demand_inputs(
        economies=economies,
        scenarios=scenarios,
        workbook_dir=workbook_dir,
    )
    return comparison_long, mapping_status


