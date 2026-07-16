#%%
"""
Link LEAP balance-demand results, transformation outputs, and supply trade branches.

This workflow uses LEAP balance exports plus transformation outputs to derive
supply imports, exports, and production targets that keep the model balanced. It
is the integrated supply path to use when demand/transformation results should
drive supply trade updates rather than running the standalone supply workflow
alone.

How to think about the whole workflow
-------------------------------------
1. Read LEAP's current story:
   The workflow starts by reading LEAP balance results and translating them into
   the same ESTO fuel language used by the 9th/ESTO supply data.
2. Add the transformation story:
   It adds what transformation modules are expected to consume and produce,
   including process outputs, feedstocks, losses, and transfer activity.
3. Add the supply story:
   It brings in baseline production, imports, exports, and stock changes from
   the supply data pipeline.
4. Find the gap:
   For every economy, scenario, fuel, and year, it asks whether supply plus
   transformation output is enough to meet demand, transformation input needs,
   and losses.
5. Choose where the fix belongs:
   In the balanced iterative approach, imports are left for LEAP to reveal,
   exports stay anchored, and any remaining gaps can be routed to transformation
   capacity, primary production, or additional exports on later passes.
6. Write LEAP-ready inputs:
   The workflow packages the answers into supply, transformation, transfer, and
   loss/own-use proxy workbooks, then combines them into a LEAP import workbook.
7. Loop if needed:
   Import the workbook into LEAP, recalculate, refresh/export LEAP balance
   results, and rerun so the next pass can respond to the remaining gaps.
"""
from __future__ import annotations

import importlib
import hashlib
from contextlib import contextmanager
from functools import lru_cache
from datetime import datetime, timezone
import json
import os
import re
import sys
import copy
import shutil
import time
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
try:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
except Exception as exc:
    print(f"Failed to add repo root to sys.path: {exc}")

# Sentinel types, _resolve_module_cap_rule, and all workflow config constants
# are defined in supply_reconciliation_config.py.  Import everything from there
# so call sites in this file remain unchanged.
import codebase.supply_reconciliation_config as _supply_reconciliation_config
from codebase.supply_reconciliation_config import *  # noqa: F401,F403
from codebase.supply_reconciliation_config import (  # private names excluded by *
    _ModuleCapRule,
    _resolve_module_cap_rule,
)

import pandas as pd
from openpyxl.styles import Font, PatternFill

from codebase.configuration import workflow_config as workflow_cfg
from codebase.configuration.all_products_and_flows import ESTO_PRODUCT_LIST, ESTO_SECTORS
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

from codebase.functions import supply_data_pipeline, leap_api, patch_baseline_seeds
from codebase.functions.analysis_input_write_dispatcher import (
    get_analysis_input_write_mode,
)
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
from codebase.utilities import workflow_common
from codebase.utilities.output_paths import BALANCE_TABLES_ROOT, INTEGRATED_LEAP_EXPORTS_ROOT
from codebase.utilities.workflow_utils import _resolve
from codebase.utilities.economy_run_lock import economy_run_locks
from codebase.supply_reconciliation_utils import (
    _canonical_transformation_fuel_label,
    _load_code_to_name_table,
    _normalize_label_for_lookup,
    _normalize_esto_product_for_match,
    _build_label_to_esto_product_lookup,
    _iter_year_value_items,
    _sort_output_frame_for_csv,
)
from codebase.supply_reconciliation_config import (  # noqa: F401
    _use_legacy_trade_split_mode,
    _use_output_share_supply_exports_mode,
    _use_capacity_unmet_iterative_mode,
    _use_capacity_unmet_iterative_balanced_mode,
    _use_capacity_unmet_iterative_any_mode,
    _use_capacity_constrained_mode,
    _use_capacity_like_mode,
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
from codebase.supply_reconciliation_utils import _normalize_template_header_value  # noqa: F401
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
import codebase.functions.supply_reconciliation_tables as _srt
import codebase.functions.supply_demand_mapping as _sdm
import codebase.functions.supply_results_saver as _srs
import codebase.supply_reconciliation_history as _srh



# ---------------------------------------------------------------------------
# Extracted function modules (moved from this file)
# ---------------------------------------------------------------------------
from codebase.functions.supply_preflight import (  # noqa: F401
    _broadcast_config_overrides,
    _keep_windows_pc_awake,
    _emit_completion_beep,
    _format_scope_preview,
    _print_reset_mode_reminder,
    _flatten_reset_scope_values,
    _load_reset_scope_from_full_model_export,
    _configured_reset_module_names,
    _configured_reset_fuel_labels,
    _configured_reset_output_fuel_labels_by_module,
    _is_year_header,
    _build_source_diagnostics,
    _write_source_diagnostics,
    _scenario_to_ninth_label,
    _create_preflight_compressed_source_files,
    _snapshot_preflight_state,
    _restore_preflight_state,
    _apply_preflight_compressed_state,
    run_preflight_compressed_projection,
    run_preflight_compressed_results_update,
)
from codebase.functions.supply_demand_mapping import (  # noqa: F401
    _normalize_sector_match_key,
    _sector_match_keys,
    _load_transformation_template_variable_sets,
    _pick_preferred_source,
    _is_demand_sector_mapping,
    _is_non_actionable_demand_fuel,
    _build_esto_parent_product_lookup,
    _get_sector_to_esto_flow_lookup,
    _run_leap_results_template_scrape,
    _economy_tokens_for_workbook_match,
    _discover_direct_demand_workbooks,
    _infer_economy_from_workbook_name,
    _truthy_flag,
    _load_active_direct_demand_mapping_sheet,
    _read_config_table_ref,
    _build_augmented_balance_demand_mapping_workbook,
    _annotate_balance_demand_issue_scope,
    _mapping_priority_rank,
    _pick_single_mapping_value,
    _build_codebook_name_to_esto_flow_lookup,
    _build_direct_demand_mapping_status,
    _load_direct_demand_reference_tables,
    _load_projection_only_ninth_table,
    _build_projection_rows_from_ninth,
    _collect_direct_demand_mapping_gaps,
    _load_optional_json_dict,
    _build_balance_demand_scenario_map,
    _compact_economy_code,
    _resolve_balance_demand_workbooks_for_economy,
    _workbook_has_level2_detail,
    _build_projection_only_mapping_status,
    load_balance_demand_inputs,
    load_direct_leap_demand_inputs,
)
from codebase.functions.supply_reconciliation_tables import (  # noqa: F401
    _collect_transformation_and_transfer_rows,
    _query_leap_value_series_for_fuels,
    _refresh_transformation_measures_from_leap_results,
    _apply_own_use_ratio_feedback,
    _read_leap_template_sheet,
    _parse_data_expression,
    _infer_constraint_economies,
    _load_constraint_value_table,
    _classify_supply_constraint_variable,
    _classify_transformation_constraint_variable,
    load_leap_constraint_tables,
    load_results_demand_table,
    load_results_sector_demand_table,
    build_transformation_balance_table,
    build_transformation_sector_table,
    prepare_projected_supply_table,
    prepare_supply_primary_table,
    build_reconciliation_table,
    build_transformation_trade_target_rows,
    apply_trade_split_between_transformation_and_supply,
    build_supply_overrides,
    reset_supply_and_transformation_import_export_to_zero,
)
from codebase.functions.supply_leap_io import (  # noqa: F401
    _build_supply_measures_for_trade_mode,
    _build_transformation_target_multiplier_table,
    _resolve_reconciliation_scenario_key,
    apply_transformation_target_overrides_for_scenario,
    save_transformation_exports_with_split_targets,
    save_transfer_exports_with_supply_overrides,
    _read_workbook_sheet_with_header_detection,
    _merge_workbook_sheets,
    _drop_wide_year_columns,
    _find_legacy_transfer_branch_paths,
    save_combined_supply_transformation_export,
    _resolve_other_loss_own_use_proxy_activity_source_mode,
    _resolve_other_loss_own_use_leap_balance_workbook_path,
    build_other_loss_own_use_proxy_workbooks_for_results_supply,
    run_other_loss_own_use_proxy_leap_import,
    build_electricity_heat_interim_workbooks_for_results_supply,
    RUN_ELECTRICITY_HEAT_INTERIM_leap_import,
    build_aggregated_demand_workbooks_for_results_supply,
    _normalize_ref_text,
    _normalize_ref_metadata,
    _split_resource_branch,
    _branch_leaf_tokens,
    _load_reference_export_data,
    _remap_resource_branch_paths,
    _backfill_metadata_from_reference,
    write_per_economy_combined_workbooks,
    run_aggregated_demand_leap_import,
    build_other_demand_zeroing_workbooks,
    run_other_demand_zeroing_leap_import,
    run_results_linked_leap_import,
)
from codebase.functions.supply_results_saver import (  # noqa: F401
    _resolve_existing_results_supply_export_paths,
    resume_results_linked_leap_import_from_existing_exports,
    _filter_transformation_workbook_to_trade_targets,
    _read_leap_sheet_data_rows,
    _read_branch_variable_rows,
    _extract_catalog_rows_from_full_model_export,
    _safe_leap_branch,
    _list_leap_child_branches,
    _probe_branch_variable_expression,
    refresh_fuel_branch_catalog_from_leap,
    _build_transformation_supply_fuel_catalog_df,
    _build_transformation_supply_fuel_catalog,
    _resolve_results_single_file_name,
    _archive_existing_results_file_if_needed,
    _archive_results_file_snapshot,
    save_results_linked_single_workbook,
    run_results_linked_transformation_supply_workflow,
    run_results_linked_supply_workflow,
)


# ---------------------------------------------------------------------------
# Backwards-compatible wrappers for names extracted during the Phase 4 split.
# ---------------------------------------------------------------------------
_CAPACITY_UNMET_RUNTIME_CAPACITY_ADDITIONS = _sra._CAPACITY_UNMET_RUNTIME_CAPACITY_ADDITIONS
_CAPACITY_UNMET_RUNTIME_PRIMARY_ADDITIONS = _sra._CAPACITY_UNMET_RUNTIME_PRIMARY_ADDITIONS
_CAPACITY_UNMET_RUNTIME_EXPORT_ADJUSTMENTS = _sra._CAPACITY_UNMET_RUNTIME_EXPORT_ADJUSTMENTS
_CAPACITY_UNMET_RUNTIME_PASS_SUMMARY = _sra._CAPACITY_UNMET_RUNTIME_PASS_SUMMARY
_SRA_BUILD_CAPACITY_PROCESS_CATALOG = _sra._build_capacity_process_catalog
_SRA_BUILD_LABEL_TO_ESTO_PRODUCT_LOOKUP = _sra._build_label_to_esto_product_lookup
_ORIGINAL_BUILD_CAPACITY_PROCESS_CATALOG = None
_ORIGINAL_BUILD_LABEL_TO_ESTO_PRODUCT_LOOKUP = _build_label_to_esto_product_lookup


def _sync_extracted_runtime_state() -> None:
    """Propagate notebook/test monkeypatches on this wrapper into extracted modules."""
    runtime_names = [
        "_CAPACITY_UNMET_RUNTIME_CAPACITY_ADDITIONS",
        "_CAPACITY_UNMET_RUNTIME_PRIMARY_ADDITIONS",
        "_CAPACITY_UNMET_RUNTIME_EXPORT_ADJUSTMENTS",
        "_CAPACITY_UNMET_RUNTIME_PASS_SUMMARY",
    ]
    for name in runtime_names:
        if name in globals():
            setattr(_sra, name, globals()[name])

    config_names = [
        "CAPACITY_UNMET_PASS_MODE",
        "CAPACITY_UNMET_STATE_PATH",
        "CAPACITY_UNMET_PIN_EXPORTS_TO_9TH_PROJECTIONS",
        "RESULTS_SINGLE_FILE_ARCHIVE_DIR",
        "RESULTS_RUNTIME_DIR",
    ]
    for name in config_names:
        if name in globals():
            value = globals()[name]
            setattr(_srt, name, value)
            setattr(_sra, name, value)
            setattr(_srh, name, value)
            setattr(_srs, name, value)


def _sync_results_saver_overrides() -> None:
    """Forward legacy monkeypatches on this wrapper into supply_results_saver."""
    _sync_extracted_runtime_state()
    names = [
        "archive_config_dir_once_per_day",
        "load_balance_demand_inputs",
        "load_results_sector_demand_table",
        "load_results_demand_table",
        "build_transformation_balance_table",
        "build_transformation_sector_table",
        "build_transformation_trade_target_rows",
        "prepare_projected_supply_table",
        "prepare_supply_primary_table",
        "load_leap_constraint_tables",
        "build_reconciliation_table",
        "apply_trade_split_between_transformation_and_supply",
        "save_year_balance_tables",
        "build_supply_overrides",
        "_build_transformation_supply_fuel_catalog_df",
        "save_transformation_exports_with_split_targets",
        "save_transfer_exports_with_supply_overrides",
        "save_combined_supply_transformation_export",
        "build_other_loss_own_use_proxy_workbooks_for_results_supply",
        "build_aggregated_demand_workbooks_for_results_supply",
        "write_per_economy_combined_workbooks",
        "supply_data_pipeline",
        "RUN_OTHER_LOSS_OWN_USE_PROXY",
        "RUN_ELECTRICITY_HEAT_INTERIM",
        "OTHER_LOSS_OWN_USE_PROXY_STAGE",
        "RESULTS_SINGLE_FILE_OUTPUT",
        "RESULTS_WRITE_LEGACY_SIDECAR_FILES",
        "RUN_LEAP_FUEL_BRANCH_PROBE_AT_START",
        "SCRAPE_LEAP_RESULTS",
        "OUTPUT_DIR",
        "RESULTS_CHECKS_DIR",
        "RESULTS_RUNTIME_DIR",
        "CAPACITY_UNMET_STATE_PATH",
        "TRANSFORMATION_SUPPLY_CACHE_ENABLED",
        "TRANSFORMATION_SUPPLY_CACHE_PATH",
        "SKIP_ECONOMIES_WITH_EXISTING_EXPORTS",
        "SCENARIOS",
    ]
    for name in names:
        if name in globals():
            setattr(_srs, name, globals()[name])


def _refresh_extracted_runtime_state() -> None:
    """Mirror extracted runtime state back onto this wrapper for legacy readers."""
    globals()["_CAPACITY_UNMET_RUNTIME_CAPACITY_ADDITIONS"] = (
        _sra._CAPACITY_UNMET_RUNTIME_CAPACITY_ADDITIONS
    )
    globals()["_CAPACITY_UNMET_RUNTIME_PRIMARY_ADDITIONS"] = (
        _sra._CAPACITY_UNMET_RUNTIME_PRIMARY_ADDITIONS
    )
    globals()["_CAPACITY_UNMET_RUNTIME_EXPORT_ADJUSTMENTS"] = (
        _sra._CAPACITY_UNMET_RUNTIME_EXPORT_ADJUSTMENTS
    )
    globals()["_CAPACITY_UNMET_RUNTIME_PASS_SUMMARY"] = (
        _sra._CAPACITY_UNMET_RUNTIME_PASS_SUMMARY
    )


def build_supply_overrides(reconciliation_table: pd.DataFrame):
    _sync_extracted_runtime_state()
    return _srt.build_supply_overrides(reconciliation_table)


def _build_capacity_process_catalog(process_records: list[dict]):
    return _sra._build_capacity_process_catalog(process_records)


_ORIGINAL_BUILD_CAPACITY_PROCESS_CATALOG = _build_capacity_process_catalog


def _collect_observed_trade_from_supply_results(**kwargs):
    _sync_extracted_runtime_state()
    return _sra._collect_observed_trade_from_supply_results(**kwargs)


def _run_capacity_unmet_iterative_pass(**kwargs):
    _sync_extracted_runtime_state()
    process_catalog_func = globals().get("_build_capacity_process_catalog")
    label_lookup_func = globals().get("_build_label_to_esto_product_lookup")
    _sra._build_capacity_process_catalog = (
        process_catalog_func
        if process_catalog_func is not _ORIGINAL_BUILD_CAPACITY_PROCESS_CATALOG
        else _SRA_BUILD_CAPACITY_PROCESS_CATALOG
    )
    _sra._build_label_to_esto_product_lookup = (
        label_lookup_func
        if label_lookup_func is not _ORIGINAL_BUILD_LABEL_TO_ESTO_PRODUCT_LOOKUP
        else _SRA_BUILD_LABEL_TO_ESTO_PRODUCT_LOOKUP
    )
    kwargs.setdefault("resolve_scenario_key", _resolve_reconciliation_scenario_key)
    result = _sra._run_capacity_unmet_iterative_pass(**kwargs)
    _refresh_extracted_runtime_state()
    return result


def _run_capacity_unmet_iterative_balanced_pass(**kwargs):
    _sync_extracted_runtime_state()
    process_catalog_func = globals().get("_build_capacity_process_catalog")
    label_lookup_func = globals().get("_build_label_to_esto_product_lookup")
    _sra._build_capacity_process_catalog = (
        process_catalog_func
        if process_catalog_func is not _ORIGINAL_BUILD_CAPACITY_PROCESS_CATALOG
        else _SRA_BUILD_CAPACITY_PROCESS_CATALOG
    )
    _sra._build_label_to_esto_product_lookup = (
        label_lookup_func
        if label_lookup_func is not _ORIGINAL_BUILD_LABEL_TO_ESTO_PRODUCT_LOOKUP
        else _SRA_BUILD_LABEL_TO_ESTO_PRODUCT_LOOKUP
    )
    kwargs.setdefault("resolve_scenario_key", _resolve_reconciliation_scenario_key)
    result = _sra._run_capacity_unmet_iterative_balanced_pass(**kwargs)
    _refresh_extracted_runtime_state()
    return result


def _resolve_balance_demand_workbooks_for_economy(economy: str):
    return (
        resolve_balance_export_workbook(
            economy=economy,
            scenario="REF",
            exports_root=BALANCE_DEMAND_EXPORTS_ROOT,
        ),
        resolve_balance_export_workbook(
            economy=economy,
            scenario="TGT",
            exports_root=BALANCE_DEMAND_EXPORTS_ROOT,
        ),
    )


def run_results_linked_transformation_supply_workflow(*args, **kwargs):
    _sync_results_saver_overrides()
    return _srs.run_results_linked_transformation_supply_workflow(*args, **kwargs)


def run_results_linked_supply_workflow(*args, **kwargs):
    _sync_results_saver_overrides()
    return _srs.run_results_linked_supply_workflow(*args, **kwargs)


def _scenario_label_for_run_output(scenario: object) -> str:
    """Return a compact stable scenario token for an automatic run label."""
    normalized = re.sub(r"[^a-z0-9]+", "", str(scenario).lower())
    known_labels = {
        "target": "TGT",
        "reference": "REF",
        "currentaccount": "CA",
        "currentaccounts": "CA",
    }
    return known_labels.get(normalized, re.sub(r"[^A-Za-z0-9]+", "", str(scenario)).upper()[:12] or "UNKNOWN")


def _automatic_run_output_label() -> str | None:
    """Build a concise label such as ``UPDATE_20_USA_TGT_REF_CA``."""
    if str(RUN_MODE).strip().lower() == "patch_baseline_seeds":
        return None
    mode = _resolve_capacity_unmet_pass_mode(CAPACITY_UNMET_PASS_MODE)
    prefix = "SEED" if mode == "baseline_seed" else "UPDATE"
    economies = workflow_common.normalize_economies(ECONOMIES)
    if len(economies) <= 3:
        economy_part = "_".join(str(economy).upper() for economy in economies)
    else:
        economy_scope = "|".join(sorted(str(economy).upper() for economy in economies))
        economy_part = f"{len(economies)}ECON_{hashlib.sha1(economy_scope.encode()).hexdigest()[:6].upper()}"
    scenario_part = "_".join(_scenario_label_for_run_output(scenario) for scenario in SCENARIOS)
    return "_".join(part for part in (prefix, economy_part, scenario_part) if part)


def _resolve_run_output_label() -> str | None:
    """Resolve the notebook's literal or automatic output-label setting."""
    requested = str(RUN_OUTPUT_LABEL or "").strip()
    if requested.lower() == "auto":
        return _automatic_run_output_label()
    return requested or None


def _refresh_output_paths_for_current_pass_mode() -> None:
    """Apply the selected pass mode to this workflow and all imported consumers."""
    refreshed_paths = _supply_reconciliation_config.refresh_output_paths_for_pass_mode(
        CAPACITY_UNMET_PASS_MODE,
        _resolve_run_output_label(),
    )
    globals()["CAPACITY_UNMET_PASS_MODE"] = (
        _supply_reconciliation_config.CAPACITY_UNMET_PASS_MODE
    )
    globals()["ACTIVE_RUN_OUTPUT_LABEL"] = _supply_reconciliation_config.RUN_OUTPUT_LABEL
    for name, value in refreshed_paths.items():
        globals()[name] = value
    _broadcast_config_overrides(
        {
            "CAPACITY_UNMET_PASS_MODE": CAPACITY_UNMET_PASS_MODE,
            **refreshed_paths,
        }
    )


# -----------------------------------------------------------------------------
# Notebook Runtime Variables (single editable block)
# -----------------------------------------------------------------------------
# Edit these values in notebooks before calling `run_with_config()`.
# ECONOMIES = ["20_USA"]
# SCENARIOS = list(workflow_cfg.SUPPLY_NOTEBOOK_SCENARIOS)
# CAPACITY_UNMET_PASS_MODE = "results_update"  # baseline_seed|results_update
# RUN_OUTPUT_LABEL = "auto"  # e.g. UPDATE_20_USA_TGT_REF_CA (default below)
# RUN_OUTPUT_LABEL = "manual_description"  # optional literal override
# Concurrent workbook runs are safe for different economies. Each full run
# gets a labelled output tree and an economy lock; a second writer for the
# same economy is rejected rather than allowed to overwrite its state/files.
# Do not run concurrent LEAP API imports, or a patch and results-update run
# for the same economy. See the workflow guide's “Concurrent runs” section.
# SCRAPE_LEAP_RESULTS = False
# RUN_LEAP_FUEL_BRANCH_PROBE_AT_START = True
# RESULTS_WRITE_LEGACY_SIDECAR_FILES = False
# BALANCE_DEMAND_FAIL_ON_MAPPING_ISSUES = True
# ENABLE_WORKFLOW_TIMING = True
# WRITE_WORKFLOW_TIMING_CSV = True
# ENABLE_COMPLETION_BEEP = True
# # RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT = False
# RUN_OTHER_LOSS_OWN_USE_PROXY = True
# OTHER_LOSS_OWN_USE_PROXY_STAGE = "auto"  # auto|first|second
# OTHER_LOSS_OWN_USE_OUTPUT_FUEL_SCOPE = "economy"  # economy|all_economies
# OTHER_LOSS_OWN_USE_INCLUDE_IN_LEAP_IMPORT = True
# OTHER_LOSS_OWN_USE_LEAP_BALANCE_WORKBOOK_PATH = None
# OTHER_LOSS_OWN_USE_LEAP_BALANCE_SCENARIO = "Target"
# OTHER_LOSS_OWN_USE_LEAP_BALANCE_DATE_ID = None
#%%
# ---------------------------------------------------------------------------
# SCOPE  (change these regularly)
# , "02_BD", "03_CDA", "04_CHL", "05_PRC", "06_HKC", "07_INA", 
# "08_JPN", "09_ROK", "10_MAS", "11_MEX", "12_NZ", "13_PNG", "14_PE", 
# "15_PHL", "16_RUS", "17_SGP", "18_CT", "19_THA", "20_USA", "21_VN"---------------------------------------------------------------------------
ECONOMIES_RUN_ORDER = [
    "21_VN", "20_USA", "19_THA", "05_PRC", "13_PNG", "15_PHL", "12_NZ",
    "11_MEX", "10_MAS", "02_BD",#the rest dont contain actual leap araeas yet
    "03_CDA", "04_CHL", "06_HKC", "07_INA", "08_JPN", "09_ROK",
    "14_PE", "16_RUS", "17_SGP", "18_CT", "01_AUS",
]
ECONOMIES = ECONOMIES_RUN_ORDER
# [, "20_USA"
#     "01_AUS", "02_BD", "05_PRC", "10_MAS", "12_NZ", "15_PHL", "13_PNG", "19_THA", "05_PRC", "21_VN",
# ]
#power imported "21_VN", "13_PNG", "15_PHL","12_NZ","10_MAS", "05_PRC", "01_AUS",   "02_BD","19_THA",  
#error  > data not in tha region. 
# 06_KHC still needs to be run in this script. the area hasnt been prepared yet. do that alongside eveyrhting in here thats not in the power imported list above: , "02_BD", "03_CDA", "04_CHL", "05_PRC", "06_HKC", "07_INA", 
# "08_JPN", "09_ROK", "10_MAS", "11_MEX", "12_NZ", "13_PNG", "14_PE", 
# "15_PHL", "16_RUS", "17_SGP", "18_CT", "19_THA", "20_USA", "21_VN"
SCENARIOS = ["Target", "Reference", "Current Accounts"]
# backedup tha, aus 15_PHL done: MAS prc , bd  12nz  DOING: ,  13_PNG 21_VN
#%%
# ---------------------------------------------------------------------------
# RUN PRESETS
# ---------------------------------------------------------------------------
# Set ACTIVE_PRESET to one of the dicts below, then run the cell.
# ECONOMIES and SCENARIOS above are intentionally kept separate because they
# change every run; the preset only needs to change when the pass type changes.
# Every key in the active preset is unpacked into module scope by
# globals().update(ACTIVE_PRESET) below, so it replaces any existing global of
# the same name imported from supply_reconciliation_config.py. Entries marked
# "overrides config default" do exactly that; unmarked entries are workflow-only.
# Edit a preset for a run-specific setting, and edit config only for its fallback.
#
# BASELINE_SEED  — first initialisation pass. Uses ESTO base-year data to seed
#                  supply/transformation. LEAP results are not yet available,
#                  so own-use proxy uses the "first" activity source.
#
# RESULTS_UPDATE — iterative initialisation pass. LEAP has been recalculated
#                  after the previous import; reads actual LEAP balance
#                  results to close the gap, so own-use proxy uses the
#                  "second" activity source. This is still initialisation
#                  because target energy is still matched.
#
# NOTE — SCRAPE_LEAP_RESULTS is False in both presets and should stay that
# way indefinitely. It depends on LEAP API behaviour that has outstanding
# bugs the LEAP developers need to fix; enabling it is likely to silently
# produce wrong results. Treat True as experimental until further notice.
#
# PREFLIGHT — by default run_with_config() first runs
# preflight_compressed_projection using 00_APEC, the configured ESTO base year,
# and BASE_YEAR+1 as a signed sum of all ninth projection years/scenarios.
# This exercises future-only mappings and branch paths quickly before the
# selected preset runs. Set PREFLIGHT_COMPRESSED_PROJECTION_ONLY=True to stop
# after the preflight.
# ---------------------------------------------------------------------------

_PRESET_BASELINE_SEED = {
    # Set True to run only preflight_compressed_projection for this preset.
    "PREFLIGHT_COMPRESSED_PROJECTION_ONLY": False,
    "RUN_PREFLIGHT_COMPRESSED_PROJECTION": True,
    # --- Pass mode ---
    "CAPACITY_UNMET_PASS_MODE": "baseline_seed",  # overrides config default
    "RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT": True,  # overrides config default
    # Set True when the full power model is not ready; builds three interim
    # power transformation modules (Electricity interim, CHP interim, Heat plant interim).
    "RUN_ELECTRICITY_HEAT_INTERIM": True,  # overrides config default

    # --- Demand source ---
    # When True, use ESTO/ninth aggregated demand (aggregated_demand_workflow)
    # instead of LEAP balance exports. Only works for single-economy runs.
    "USE_AGGREGATED_DEMAND_AS_DUMMY": True,  # overrides config default
    # Optional list of 9th-edition sector or sub1sector codes to omit from the
    # aggregated demand sum.  None means no extra exclusions.
    # Top-level sectors (sectors col):
    #   04_international_marine_bunkers  05_international_aviation_bunkers
    #   10_losses_and_own_use            14_industry_sector
    #   15_transport_sector              16_other_sector   17_nonenergy_use
    # Sub1sectors (sub1sectors col — finer grain, use these to exclude just a slice):
    #   10_01_own_use                    10_02_transmission_and_distribution_losses
    #   14_01_mining_and_quarrying       14_02_construction    14_03_manufacturing
    #   15_01_domestic_air_transport     15_02_road            15_03_rail
    #   15_04_domestic_navigation        15_05_pipeline_transport
    #   15_06_nonspecified_transport     16_01_buildings
    #   16_02_agriculture_and_fishing    16_05_nonspecified_others
    # Example: ["15_transport_sector"]  or  ["15_02_road", "15_03_rail"]
    "AGGREGATED_DEMAND_EXCLUDED_SECTORS": None,  # overrides config default
    
    # Write Demand\All demand aggregated\{fuel} branches to a LEAP import workbook
    # so LEAP receives the aggregated demand values (not just used internally).
    "WRITE_AGGREGATED_DEMAND_WORKBOOK": True,  # overrides config default
    "AGGREGATED_DEMAND_INCLUDE_IN_LEAP_IMPORT": True,  # overrides config default
    # When True, branches are written as Demand\All demand aggregated\{SectorLabel}\{fuel}
    # instead of the flat Demand\All demand aggregated\{fuel}.
    # Enable when LEAP has per-sector sub-branches under the aggregated demand node.
    "AGGREGATED_DEMAND_USE_SECTOR_BRANCHES": False,  # overrides config default
    # When True, also generate a LEAP import workbook that zeros every non-share
    # Demand branch from the full model export, so those branches produce no energy
    # use while the aggregated demand branches provide the actual demand values.
    "ZERO_OTHER_DEMAND_BRANCHES_FROM_EXPORT": True,  # overrides config default
    "ZERO_OTHER_DEMAND_INCLUDE_IN_LEAP_IMPORT": True,  # overrides config default

    # --- Other loss / own-use proxy ---
    # "first" uses ESTO/ninth activity; "second" uses LEAP-balance activity.
    # These are initialisation activity-source choices, not post-initialisation
    # anchored-intensity modes.
    "OTHER_LOSS_OWN_USE_PROXY_STAGE": "first",  # overrides config default

    # Set True to skip per-economy export generation when combined workbooks already
    # exist on disk — useful for resuming a partial run or quickly re-generating the
    # single consolidated file. Reset to False for a normal full run.
    "SKIP_ECONOMIES_WITH_EXISTING_EXPORTS": False,
}

# Audited 2026-07-08. "transfers" is VERIFIED: its regen goes through the same
# save_transfer_exports_with_supply_overrides path as the full run (empty
# reconciliation table = baseline-seed semantics), and a patched seed reproduces
# the full workflow's transfer rows exactly (573/573 rows, zero diffs, checked
# against 01_AUS; 20_USA reallocation applied and verified). Failures now raise
# instead of printing, stale-workbook collection is prevented (fresh regen files
# are threaded through), and "supply"/"losses_own_use" raise NotImplementedError
# when PATCH_RUN_WORKFLOW=True.
#
# Audited 2026-07-10. "power_interim" is FIXED AND SPOT-VERIFIED: temp-copy
# patch checks against current full-run baseline seeds reproduced interim rows
# exactly for 01_AUS (339/339 rows, zero row/expression diffs) and 20_USA
# (339/339 retained rows, zero row/expression diffs after non-template fresh
# rows were filtered by patch scope). The patcher uses exact fresh workbook
# paths from assemble_electricity_heat_interim_workbook(), so stale scenario-
# order workbook variants are not read.
#
# Audited 2026-07-10. "aggregated_demand" is FIXED AND SPOT-VERIFIED: the
# patcher now threads the reconciliation config for own-use/T&D-loss exclusion,
# explicit excluded sectors, and sector-branch output mode into fresh workbook
# generation. Temp-copy patch checks against current full-run baseline seeds
# reproduced aggregated-demand rows exactly for 01_AUS and 20_USA (420/420 rows,
# zero row/expression diffs for both).
#
# Audited 2026-07-14. "supply" is now PATCHABLE through
# supply_workflow.assemble_supply_workbooks(export_output_dir=WORKBOOKS_DIR)
# and was spot-verified for 20_USA end-to-end in the patcher. The seed was
# restored after the check, so this is a workflow wiring verdict rather than a
# persistent seed change.
#
# Audited 2026-07-10. Transformation auto-regen modules are NOT SAFELY
# PATCHABLE and are gated in patch_baseline_seeds.run_patch(). The simplified
# auto path failed for oil_refineries (01_AUS: 60 rows only-before and 57
# expression diffs; 20_USA: 21 rows only-before and 83 expression diffs).
# Routing through the split-target full-workflow helper fixed row presence but
# still changed process-efficiency and auxiliary-fuel expressions (20_USA:
# 7 expression diffs). Refresh these modules through the baseline/full supply
# reconciliation workflow instead of module patching until exact equivalence is
# proven.
#
# Audited 2026-07-15. "losses_own_use" is PATCHABLE through the wired
# other-loss/own-use proxy source workflow. run_patch() strips
# "Demand\Other loss and own use\" and regenerates from fresh
# other_loss_own_use_proxy_{econ} workbooks. The auto stage resolves the
# activity source from the pass config; report that resolved mode per run.
# Verified end-to-end including the Brunei retry. Proxy coverage gaps and
# pre-base-year consistency notices are diagnostics to report, not patch
# failures.
_PRESET_PATCH_BASELINE_SEEDS = {
    # --- Pass mode ---
    # When RUN_MODE == "patch_baseline_seeds", run_with_config() skips the full
    # supply/transformation workflow entirely and just patches existing
    # leap_import_baseline_seed_* files via patch_baseline_seeds.run_patch().
    "RUN_MODE": "patch_baseline_seeds",
    # Module name(s) from patch_baseline_seeds.MODULE_REGISTRY.  Accepts a single
    # string or a list to patch multiple modules in sequence, e.g.:
    #   "oil_refineries" | ["aggregated_demand", "power_interim"]
    # Patchable: "supply", "transfers", "power_interim", "aggregated_demand",
    #            "losses_own_use". The transformation auto-regen sectors
    #            ("oil_refineries", "lng", "hydrogen", "transformation", ...) are
    #            gated: run_patch() raises NotImplementedError for them.
    "PATCH_MODULE": ["losses_own_use"],
    # None = all economies found in the baseline seed directory, or a list of
    # economy tokens to limit scope, e.g. ["20_USA", "01_AUS"].
    "PATCH_ECONOMIES": None,
    # Re-run the upstream source workflow before patching so workbook-based
    # modules (power_interim, transfers, etc.) always patch from fresh data.
    # Set False to patch from whatever workbooks are already on disk.
    "PATCH_RUN_WORKFLOW": True,
}

_PRESET_RESULTS_UPDATE = {
    # Set True to run only preflight_compressed_projection for this preset.
    "PREFLIGHT_COMPRESSED_PROJECTION_ONLY": False,
    "RUN_PREFLIGHT_COMPRESSED_RESULTS_UPDATE": True,

    # --- Pass mode ---
    "CAPACITY_UNMET_PASS_MODE": "results_update",  # overrides config default
    "RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT": False,  # overrides config default
    # Set True when the full power model is not ready.
    "RUN_ELECTRICITY_HEAT_INTERIM": False,  # overrides config default

    # --- Demand sector exclusions ---
    # Optional list of 9th-edition sector or sub1sector codes to omit from the
    # aggregated demand total.  None means no extra exclusions.
    # Top-level sectors (sectors col):
    #   04_international_marine_bunkers  05_international_aviation_bunkers
    #   10_losses_and_own_use            14_industry_sector
    #   15_transport_sector              16_other_sector   17_nonenergy_use
    # Sub1sectors (sub1sectors col — finer grain, use these to exclude just a slice):
    #   10_01_own_use                    10_02_transmission_and_distribution_losses
    #   14_01_mining_and_quarrying       14_02_construction    14_03_manufacturing
    #   15_01_domestic_air_transport     15_02_road            15_03_rail
    #   15_04_domestic_navigation        15_05_pipeline_transport
    #   15_06_nonspecified_transport     16_01_buildings
    #   16_02_agriculture_and_fishing    16_05_nonspecified_others
    # Example: ["15_transport_sector"]  or  ["15_02_road", "15_03_rail"]
    "AGGREGATED_DEMAND_EXCLUDED_SECTORS": None,  # overrides config default
    "USE_AGGREGATED_DEMAND_AS_DUMMY": True,  # overrides config default
    "WRITE_AGGREGATED_DEMAND_WORKBOOK": True,  # overrides config default
    "AGGREGATED_DEMAND_INCLUDE_IN_LEAP_IMPORT": True,  # overrides config default
    # When True, branches are written as Demand\All demand aggregated\{SectorLabel}\{fuel}
    # instead of the flat Demand\All demand aggregated\{fuel}.
    # Enable when LEAP has per-sector sub-branches under the aggregated demand node.
    "AGGREGATED_DEMAND_USE_SECTOR_BRANCHES": False,  # overrides config default
    # Keep stale detailed demand branches from surviving update imports when the
    # aggregated-demand dummy is still the active demand source.
    "ZERO_OTHER_DEMAND_BRANCHES_FROM_EXPORT": True,  # overrides config default
    "ZERO_OTHER_DEMAND_INCLUDE_IN_LEAP_IMPORT": True,  # overrides config default

    # --- Other loss / own-use proxy ---
    # "second" uses LEAP-balance activity after a LEAP run; "first" uses
    # ESTO/ninth activity. Both remain initialisation while target energy is
    # still matched.
    "OTHER_LOSS_OWN_USE_PROXY_STAGE": "second",  # overrides config default

    # Set True to skip per-economy export generation when combined workbooks already
    # exist on disk — useful for resuming a partial run or quickly re-generating the
    # single consolidated file. Reset to False for a normal full run.
    "SKIP_ECONOMIES_WITH_EXISTING_EXPORTS": False,
}

# ← change this to switch presets. _PRESET_PATCH_BASELINE_SEEDS is defined above
# but intentionally not the default: it is verified for "transfers",
# "power_interim", "aggregated_demand", "supply", and "losses_own_use", while the
# transformation auto-regen sectors are gated and refresh via the full workflow
# only. Point ACTIVE_PRESET at it deliberately per patch run; see the notes above it.
ACTIVE_PRESET = _PRESET_BASELINE_SEED

# Default run mode; presets other than _PRESET_PATCH_BASELINE_SEEDS don't set
# RUN_MODE, so reset it here each time before unpacking the active preset.
RUN_MODE = "full"
RUN_OUTPUT_LABEL = "auto"
PATCH_MODULE = []
PATCH_ECONOMIES = None
PATCH_RUN_WORKFLOW = True
# Skip export generation for economies whose combined workbook already exists on disk.
# Useful for resuming a partial run — completed economies are reused, incomplete ones run fresh.
SKIP_ECONOMIES_WITH_EXISTING_EXPORTS = False
# Cache the transformation/supply input tables to disk between runs.
# Saves ~2 hours on re-runs where config/data files haven't changed.
# Set False to force a full recompute (e.g. after updating config or data files).
TRANSFORMATION_SUPPLY_CACHE_ENABLED = True
KEEP_PC_AWAKE_WHILE_RUNNING = True
RUN_PREFLIGHT_COMPRESSED_PROJECTION = True
PREFLIGHT_COMPRESSED_INCLUDE_CURRENT_ACCOUNTS = True
PREFLIGHT_COMPRESSED_PROJECTION_ONLY = False
PREFLIGHT_COMPRESSED_FAIL_FAST = False
# Compressed results-update preflight (complements the projection preflight):
# runs the majority of the results_update path against real 20_USA LEAP balance
# structure compressed to two effective years, with LEAP imports/scraping/caches
# disabled and all outputs isolated. Off by default so it does not lengthen every
# run; enable it (ideally before a full results_update) with RUN_PREFLIGHT_...=True.
# See docs/supply_reconciliation_workflow_guide.md ("Fast preflight checks").
RUN_PREFLIGHT_COMPRESSED_RESULTS_UPDATE = False
PREFLIGHT_COMPRESSED_RESULTS_UPDATE_ONLY = False
PREFLIGHT_COMPRESSED_RESULTS_UPDATE_FAIL_FAST = False
# When True, chokepoints that would otherwise abort the ENTIRE run (all
# economies, all scenarios) instead print a [WARN] and continue, deferring the
# failure to a single aggregated error raised only after every economy and
# scenario has been processed. Use this for long unattended overnight runs
# where partial-but-flawed output is more useful than no output. Leave False
# for interactive runs where you want to stop and fix problems immediately.
# See codebase/utilities/workflow_common.py (defer_or_raise/raise_deferred_errors).
THROW_ERROR_AFTER_RUN = True
# Unpack preset — does not overwrite ECONOMIES/SCENARIOS set above. Presets can
# override the defaults immediately above, including PREFLIGHT_* toggles.
globals().update(ACTIVE_PRESET)
_refresh_output_paths_for_current_pass_mode()

# ---------------------------------------------------------------------------
# Output logging
# ---------------------------------------------------------------------------
def _workflow_log_path() -> Path:
    """Keep full-run logs alongside their isolated runtime outputs."""
    return Path(RESULTS_RUNTIME_DIR) / "supply_reconciliation_workflow.log"


class _TeeWriter:
    def __init__(self, file_obj, stream):
        self._file = file_obj
        self._stream = stream
        self._stream_available = True

    def _disable_unavailable_stream(self, exc):
        if not self._stream_available:
            return
        self._stream_available = False
        self._file.write(
            "\n[WARN] Console output became unavailable; continuing with file logging only: "
            f"{exc!r}\n"
        )
        self._file.flush()

    def write(self, data):
        self._file.write(data)
        if self._stream_available:
            try:
                self._stream.write(data)
            except (OSError, UnicodeError) as exc:
                self._disable_unavailable_stream(exc)
        return len(data)

    def flush(self):
        self._file.flush()
        if self._stream_available:
            try:
                self._stream.flush()
            except (OSError, UnicodeError) as exc:
                self._disable_unavailable_stream(exc)

    def isatty(self):
        return False


@contextmanager
def _log_to_file(log_path: Path):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    original = sys.stdout
    with open(log_path, "w", encoding="utf-8") as f:
        sys.stdout = _TeeWriter(f, original)
        try:
            yield log_path
        finally:
            sys.stdout = original


def _run_leap_display_name_preflight() -> None:
    """Check leap_display_names consistency against the combined mapping sheets.

    Imports check_display_name_issues from the sibling leap_mappings repo and
    prints a warning if orphans or duplicate display names are found.  Failures
    are non-fatal — the workflow continues regardless.
    """
    try:
        from codebase.utilities.master_config import LEAP_MAPPINGS_REPO_ROOT
        module_path = LEAP_MAPPINGS_REPO_ROOT / "codebase" / "mapping_tools" / "update_leap_display_names.py"
        if not module_path.exists():
            print(f"[WARN] leap_display_names preflight skipped: {module_path} not found")
            return
        spec = importlib.util.spec_from_file_location(
            "_codex_update_leap_display_names_preflight",
            module_path,
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load module spec from {module_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        check_display_name_issues = getattr(module, "check_display_name_issues")
        issues = check_display_name_issues()
        orphans = issues.get("orphan_count", 0)
        dups = issues.get("duplicate_count", 0)
        if orphans or dups:
            print(
                f"[WARN] leap_display_names: {orphans} orphan(s), "
                f"{dups} duplicate display name(s) — "
                "run leap_mappings Stage 0 to review display_names_qa.csv"
            )
        else:
            print("[INFO] leap_display_names: OK")
    except Exception as exc:
        print(f"[WARN] leap_display_names preflight skipped: {exc}")


def _run_results_update_readiness_check() -> None:
    """Fail early when a results_update run is missing required balance exports."""
    if _resolve_capacity_unmet_pass_mode(CAPACITY_UNMET_PASS_MODE) != "results_update":
        return

    economy_list = workflow_common.normalize_economies(ECONOMIES)
    if not economy_list:
        return

    issues: list[str] = []
    print(
        "[INFO] results_update readiness: checking LEAP balance export workbooks "
        f"for {len(economy_list)} economy/economies."
    )
    for economy in economy_list:
        try:
            ref_workbook, tgt_workbook = _resolve_balance_demand_workbooks_for_economy(economy)
        except Exception as exc:
            issues.append(f"{economy}: could not resolve REF/TGT balance workbooks ({exc})")
            continue

        missing_paths = [
            path for path in (ref_workbook, tgt_workbook) if not Path(path).exists()
        ]
        if missing_paths:
            missing_text = ", ".join(str(path) for path in missing_paths)
            issues.append(f"{economy}: missing balance workbook(s): {missing_text}")
            continue

        if REQUIRE_LEVEL2_BALANCE_EXPORT_DETAIL:
            missing_detail_paths = [
                path
                for path in (ref_workbook, tgt_workbook)
                if not _workbook_has_level2_detail(path)
            ]
            if missing_detail_paths:
                detail_text = ", ".join(str(path) for path in missing_detail_paths)
                issues.append(
                    f"{economy}: balance workbook(s) were exported at Level 1 detail; "
                    f"re-export with at least Level 2 detail: {detail_text}"
                )

    if issues:
        issue_text = "\n".join(f"- {issue}" for issue in issues)
        raise RuntimeError(
            "results_update readiness check failed. Export fresh LEAP balance "
            "workbooks before running the update pass:\n"
            f"{issue_text}"
        )

    print("[INFO] results_update readiness: OK")


def run_with_config() -> dict[str, object]:
    """Run the notebook-configured workflow while optionally preventing PC sleep."""
    _refresh_output_paths_for_current_pass_mode()
    with _log_to_file(_workflow_log_path()) as log_path:
        print(f"[LOG] Writing output to: {log_path}")
        with _keep_windows_pc_awake(enabled=bool(KEEP_PC_AWAKE_WHILE_RUNNING)):
            return _run_with_config_inner()


def _run_with_config_inner() -> dict[str, object]:
    """Run the notebook-configured results-linked transformation+supply workflow.

    When RUN_MODE == "patch_baseline_seeds" (set via _PRESET_PATCH_BASELINE_SEEDS),
    this skips the full workflow and just patches existing baseline seed files
    via patch_baseline_seeds.run_patch(PATCH_MODULE, PATCH_ECONOMIES).
    """
    _refresh_output_paths_for_current_pass_mode()
    if RUN_MODE == "patch_baseline_seeds":
        _run_workflow = globals().get("PATCH_RUN_WORKFLOW", True)
        _modules = [PATCH_MODULE] if isinstance(PATCH_MODULE, str) else list(PATCH_MODULE)
        print(f"[INFO] run_with_config: RUN_MODE=patch_baseline_seeds, PATCH_MODULE={_modules}, "
              f"PATCH_ECONOMIES={PATCH_ECONOMIES}, PATCH_RUN_WORKFLOW={_run_workflow}")
        for _mod in _modules:
            patch_baseline_seeds.run_patch(_mod, PATCH_ECONOMIES, run_workflow=_run_workflow)
        return {}

    economies_for_lock = workflow_common.normalize_economies(ECONOMIES)
    lock_directory = (
        REPO_ROOT
        / "outputs"
        / "leap_exports"
        / "supply_reconciliation"
        / "supporting_files"
        / "runtime"
        / "economy_locks"
    )
    with economy_run_locks(
        economies_for_lock,
        lock_directory=lock_directory,
        workflow_name="supply_reconciliation",
    ):
        return _run_with_config_locked()


def _run_with_config_locked() -> dict[str, object]:
    """Run the full workflow after economy-specific output locks are acquired."""

    workflow_common.THROW_ERROR_AFTER_RUN = bool(THROW_ERROR_AFTER_RUN)
    workflow_common.clear_deferred_errors()

    _run_leap_display_name_preflight()

    analysis_write_mode = get_analysis_input_write_mode()
    include_leap_import = analysis_write_mode == "api"
    preflight_result: dict[str, object] | None = None
    preflight_error: Exception | None = None
    results_update_preflight_result: dict[str, object] | None = None
    results_update_preflight_error: Exception | None = None
    stop_after_preflight = bool(PREFLIGHT_COMPRESSED_PROJECTION_ONLY) or bool(
        PREFLIGHT_COMPRESSED_RESULTS_UPDATE_ONLY
    )
    if bool(RUN_PREFLIGHT_COMPRESSED_PROJECTION):
        try:
            preflight_result = run_preflight_compressed_projection(
                scenario_names=SCENARIOS,
            )
        except Exception as exc:
            preflight_error = exc
            if stop_after_preflight or bool(PREFLIGHT_COMPRESSED_FAIL_FAST):
                if bool(COMPLETION_BEEP_ON_ERROR):
                    _emit_completion_beep(success=False)
                raise
            print(
                "[WARN] preflight_compressed_projection failed, but "
                "PREFLIGHT_COMPRESSED_FAIL_FAST=False so the full economy run will continue. "
                f"The preflight error will be re-raised after the main run completes: {exc}"
            )

    if bool(RUN_PREFLIGHT_COMPRESSED_RESULTS_UPDATE):
        try:
            results_update_preflight_result = run_preflight_compressed_results_update(
                scenario_names=SCENARIOS,
            )
        except Exception as exc:
            results_update_preflight_error = exc
            if stop_after_preflight or bool(PREFLIGHT_COMPRESSED_RESULTS_UPDATE_FAIL_FAST):
                if bool(COMPLETION_BEEP_ON_ERROR):
                    _emit_completion_beep(success=False)
                raise
            print(
                "[WARN] preflight_compressed_results_update failed, but "
                "PREFLIGHT_COMPRESSED_RESULTS_UPDATE_FAIL_FAST=False so the full economy run "
                "will continue. The preflight error will be re-raised after the main run "
                f"completes: {exc}"
            )

    if stop_after_preflight:
        _emit_completion_beep(success=True, style="chime")
        return {
            "preflight_compressed_projection": preflight_result,
            "preflight_compressed_results_update": results_update_preflight_result,
        }

    _run_results_update_readiness_check()

    if int(supply_data_pipeline.EXPORT_FINAL_YEAR) > int(LEAP_IMPORT_MAX_YEAR):
        print(
            "[WARN] supply_data_pipeline.EXPORT_FINAL_YEAR="
            f"{supply_data_pipeline.EXPORT_FINAL_YEAR} exceeds LEAP max year {LEAP_IMPORT_MAX_YEAR}; "
            f"supply_reconciliation_workflow is clamping FINAL_YEAR to {FINAL_YEAR}."
        )
    print(
        "[INFO] run_with_config toggles: "
        f"ACTIVE_SUPPLY_LINK_METHOD={ACTIVE_SUPPLY_LINK_METHOD}, "
        f"CAPACITY_UNMET_PASS_MODE={CAPACITY_UNMET_PASS_MODE}, "
        "RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT="
        f"{RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT}, "
        f"ANALYSIS_INPUT_WRITE_MODE={analysis_write_mode}, "
        f"LEAP_IMPORT_LOG_LEVEL={LEAP_IMPORT_LOG_LEVEL}, "
        f"RUN_LEAP_FUEL_BRANCH_PROBE_AT_START={RUN_LEAP_FUEL_BRANCH_PROBE_AT_START}, "
        f"INCLUDE_LEAP_IMPORT={include_leap_import} (derived), "
        f"LEAP_IMPORT_SUPPLY_TO_LEAP={LEAP_IMPORT_SUPPLY_TO_LEAP}, "
        f"LEAP_IMPORT_TRANSFORMATION_TO_LEAP={LEAP_IMPORT_TRANSFORMATION_TO_LEAP}, "
        f"LEAP_IMPORT_TRANSFERS_TO_LEAP={LEAP_IMPORT_TRANSFERS_TO_LEAP}, "
        f"LEAP_IMPORT_INCLUDE_CURRENT_ACCOUNTS={LEAP_IMPORT_INCLUDE_CURRENT_ACCOUNTS}, "
        f"SCRAPE_LEAP_RESULTS={SCRAPE_LEAP_RESULTS}, "
        f"RESULTS_WRITE_LEGACY_SIDECAR_FILES={RESULTS_WRITE_LEGACY_SIDECAR_FILES}, "
        f"RUN_OTHER_LOSS_OWN_USE_PROXY={RUN_OTHER_LOSS_OWN_USE_PROXY}, "
        f"OTHER_LOSS_OWN_USE_PROXY_STAGE={OTHER_LOSS_OWN_USE_PROXY_STAGE}, "
        f"OTHER_LOSS_OWN_USE_OUTPUT_FUEL_SCOPE={OTHER_LOSS_OWN_USE_OUTPUT_FUEL_SCOPE}, "
        f"OTHER_LOSS_OWN_USE_INCLUDE_IN_LEAP_IMPORT={OTHER_LOSS_OWN_USE_INCLUDE_IN_LEAP_IMPORT}, "
        f"RUN_ELECTRICITY_HEAT_INTERIM={RUN_ELECTRICITY_HEAT_INTERIM}, "
        f"BALANCE_DEMAND_FAIL_ON_MAPPING_ISSUES={BALANCE_DEMAND_FAIL_ON_MAPPING_ISSUES}, "
        f"RUN_PREFLIGHT_COMPRESSED_PROJECTION={RUN_PREFLIGHT_COMPRESSED_PROJECTION}, "
        f"PREFLIGHT_COMPRESSED_FAIL_FAST={PREFLIGHT_COMPRESSED_FAIL_FAST}, "
        f"RUN_PREFLIGHT_COMPRESSED_RESULTS_UPDATE={RUN_PREFLIGHT_COMPRESSED_RESULTS_UPDATE}, "
        f"PREFLIGHT_COMPRESSED_RESULTS_UPDATE_FAIL_FAST={PREFLIGHT_COMPRESSED_RESULTS_UPDATE_FAIL_FAST}, "
        f"ENABLE_WORKFLOW_TIMING={ENABLE_WORKFLOW_TIMING}, "
        f"WRITE_WORKFLOW_TIMING_CSV={WRITE_WORKFLOW_TIMING_CSV}, "
        f"KEEP_ALL_ZERO_SUPPLY_ROWS={KEEP_ALL_ZERO_SUPPLY_ROWS}, "
        f"KEEP_PC_AWAKE_WHILE_RUNNING={KEEP_PC_AWAKE_WHILE_RUNNING}, "
        f"ENABLE_COMPLETION_BEEP={ENABLE_COMPLETION_BEEP}"
    )
    try:
        output = run_results_linked_transformation_supply_workflow(
            economies=ECONOMIES,
            scenario_names=SCENARIOS,
            export_dataset_key=EXPORT_DATASET_KEY,
            include_leap_import=include_leap_import,
            import_scenarios=LEAP_IMPORT_SCENARIOS,
            scrape_leap_results=SCRAPE_LEAP_RESULTS,
        )
    except Exception:
        if bool(COMPLETION_BEEP_ON_ERROR):
            _emit_completion_beep(success=False)
        raise
    _emit_completion_beep(success=True, style="chime")
    if preflight_result is not None:
        output["preflight_compressed_projection"] = preflight_result
    if results_update_preflight_result is not None:
        output["preflight_compressed_results_update"] = results_update_preflight_result
    if preflight_error is not None:
        output["preflight_compressed_projection_error"] = str(preflight_error)
    if results_update_preflight_error is not None:
        output["preflight_compressed_results_update_error"] = str(results_update_preflight_error)

    # Surface every failure mode that survived a completed run, so nothing is
    # silently dropped: compressed-preflight errors AND THROW_ERROR_AFTER_RUN
    # deferred errors. Attach all of them to output first, then raise once —
    # combining messages if both kinds are present, since only one exception
    # can propagate.
    preflight_deferred = preflight_error or results_update_preflight_error
    _deferred_errors = workflow_common.get_deferred_errors()
    if _deferred_errors:
        output["deferred_errors"] = [
            f"[{context}] {exc!r}" for context, exc in _deferred_errors
        ]

    if preflight_deferred is not None or _deferred_errors:
        if bool(COMPLETION_BEEP_ON_ERROR):
            _emit_completion_beep(success=False)
        if preflight_deferred is not None and _deferred_errors:
            _deferred_summary = "; ".join(
                f"[{context}] {exc!r}" for context, exc in _deferred_errors
            )
            raise RuntimeError(
                "A compressed preflight failed AND "
                f"{len(_deferred_errors)} error(s) were deferred via "
                "THROW_ERROR_AFTER_RUN, but the main economy run completed. "
                "Review the preflight outputs, diagnostics, and affected "
                "economies/scenarios before LEAP import. "
                f"Original preflight error: {preflight_deferred}. "
                f"Deferred errors: {_deferred_summary}"
            ) from preflight_deferred
        if preflight_deferred is not None:
            raise RuntimeError(
                "A compressed preflight failed, but the main economy run completed. "
                "Review the preflight outputs and diagnostics before LEAP import. "
                f"Original preflight error: {preflight_deferred}"
            ) from preflight_deferred
        workflow_common.raise_deferred_errors()
    return output

#%%
# ECONOMIES = ["01_AUS", "02_BD", "03_CDA", "04_CHL", "05_PRC", "06_HKC", "07_INA",
# "08_JPN", "09_ROK", "10_MAS", "11_MEX", "12_NZ", "13_PNG", "14_PE",
# "15_PHL", "16_RUS"]
if __name__ == "__main__":
    run_with_config()
#%%
