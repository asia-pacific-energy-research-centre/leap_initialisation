from __future__ import annotations

import concurrent.futures
import copy
import importlib
import json
import os
import re
import shutil
import sys
import time
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterable

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
from codebase.functions import supply_data_pipeline, leap_api, patch_baseline_seeds
from codebase.functions.analysis_input_write_dispatcher import get_analysis_input_write_mode
from codebase.functions.baseline_seed_validation import (
    apply_template_ids,
    build_template_id_lookup,
)
from codebase import (
    electricity_heat_interim_workflow,
    other_loss_own_use_proxy_workflow,
    transformation_workflow,
    transfers_workflow,
)

ECONOMIES = list(workflow_cfg.SUPPLY_NOTEBOOK_ECONOMIES)
SCENARIOS = list(workflow_cfg.SUPPLY_NOTEBOOK_SCENARIOS)
SKIP_ECONOMIES_WITH_EXISTING_EXPORTS = False
TRANSFORMATION_SUPPLY_CACHE_ENABLED = False
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

from codebase.functions.supply_preflight import (
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
)
from codebase.functions.supply_demand_mapping import (
    _normalize_sector_match_key,
    _sector_match_keys,
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
    _build_projection_only_mapping_status,
    load_balance_demand_inputs,
    load_direct_leap_demand_inputs,
)
from codebase.functions.supply_reconciliation_tables import (
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
    resolve_effective_aggregated_demand_exclusions,
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
from codebase.functions.balance_demand_conservation import (
    build_balance_demand_conservation_breakdown,
    build_balance_demand_conservation_diagnostics,
    build_balance_demand_conservation_lineage,
    build_raw_demand_conservation_reference,
    prepare_reconciliation_demand_totals,
    prepare_reconciliation_sector_demand_totals,
    write_balance_demand_conservation_diagnostics,
    write_balance_demand_conservation_table,
)
from codebase.functions.supply_conservation import (
    build_baseline_supply_conservation_artifacts,
    build_results_update_closure_diagnostics,
    find_exported_supply_products,
    write_supply_diagnostic,
)
from codebase.functions.transformation_conservation import (
    build_raw_transformation_output_reference,
    build_transformation_output_conservation,
)
from codebase.functions.supply_leap_io import (
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

def _resolve_existing_results_supply_export_paths(
    *,
    economies: Iterable[str],
    scenarios: Iterable[str],
    export_dir: Path | str = EXPORT_OUTPUT_DIR,
) -> tuple[list[Path], list[Path], list[Path]]:
    """Resolve expected supply/transformation/transfer export workbooks from disk."""
    economy_list = workflow_common.normalize_economies(economies or ECONOMIES)
    scenario_list = workflow_common.normalize_workflow_scenarios(scenarios, SCENARIOS)
    scenario_filename = supply_data_pipeline.format_scenario_label_for_filename(scenario_list)
    root = _resolve(export_dir)

    supply_paths: list[Path] = []
    transformation_paths: list[Path] = []
    transfer_paths: list[Path] = []
    missing: list[str] = []

    def _norm_token(text: str) -> str:
        return "".join(ch.lower() for ch in str(text or "") if ch.isalnum())

    def _pick_existing_workbook(
        *,
        prefix: str,
        economy: str,
        scenario_tokens: list[str],
    ) -> Path | None:
        econ_key = _norm_token(economy)
        token_keys = [_norm_token(token) for token in scenario_tokens if _norm_token(token)]
        candidates = sorted(root.glob(f"{prefix}_*.xlsx"))
        scored: list[tuple[int, Path]] = []
        for path in candidates:
            stem_key = _norm_token(path.stem)
            if econ_key and econ_key not in stem_key:
                continue
            token_hits = sum(1 for token in token_keys if token in stem_key)
            # Require at least one scenario token hit when scenarios were requested.
            if token_keys and token_hits == 0:
                continue
            scored.append((token_hits, path))
        if not scored:
            return None
        scored.sort(key=lambda item: (item[0], str(item[1]).lower()))
        return scored[-1][1]

    for economy in economy_list:
        supply_name = EXPORT_FILENAME_TEMPLATE.format(
            economy=str(economy),
            scenarios=scenario_filename,
        )
        transformation_name = transformation_workflow.format_export_filename(
            str(economy),
            scenario_list,
            TRANSFORMATION_EXPORT_FILENAME_TEMPLATE,
        )
        transfer_name = transfers_workflow.format_export_filename(
            str(economy),
            scenario_list,
            transfers_workflow.EXPORT_FILENAME_TEMPLATE,
        )

        supply_path = root / supply_name
        transformation_path = root / transformation_name
        transfer_path = root / transfer_name

        resolved_supply = supply_path if supply_path.exists() else _pick_existing_workbook(
            prefix="supply_leap_imports",
            economy=str(economy),
            scenario_tokens=scenario_list,
        )
        resolved_transformation = (
            transformation_path
            if transformation_path.exists()
            else _pick_existing_workbook(
                prefix="transformation_leap_imports",
                economy=str(economy),
                scenario_tokens=scenario_list,
            )
        )
        resolved_transfer = transfer_path if transfer_path.exists() else _pick_existing_workbook(
            prefix="transfer_leap_imports",
            economy=str(economy),
            scenario_tokens=scenario_list,
        )

        if resolved_supply is not None:
            supply_paths.append(resolved_supply)
        else:
            missing.append(str(supply_path))
        if resolved_transformation is not None:
            transformation_paths.append(resolved_transformation)
        else:
            missing.append(str(transformation_path))
        if resolved_transfer is not None:
            transfer_paths.append(resolved_transfer)
        else:
            missing.append(str(transfer_path))

    if missing:
        preview = "\n".join(missing[:12])
        raise FileNotFoundError(
            "Resume import could not find required export workbook(s). "
            f"First missing paths:\n{preview}"
        )
    return supply_paths, transformation_paths, transfer_paths


def resume_results_linked_leap_import_from_existing_exports(
    *,
    economies: Iterable[str] | None = None,
    scenarios: Iterable[str] | None = None,
    import_scenarios: Iterable[str] | str | None = LEAP_IMPORT_SCENARIOS,
    export_dir: Path | str = EXPORT_OUTPUT_DIR,
    region: str = LEAP_IMPORT_REGION,
    create_branches: bool = LEAP_IMPORT_CREATE_BRANCHES,
    fill_branches: bool = LEAP_IMPORT_FILL_BRANCHES,
    include_current_accounts: bool = LEAP_IMPORT_INCLUDE_CURRENT_ACCOUNTS,
    import_supply_to_leap: bool = LEAP_IMPORT_SUPPLY_TO_LEAP,
    import_transformation_to_leap: bool = LEAP_IMPORT_TRANSFORMATION_TO_LEAP,
    import_transfers_to_leap: bool = LEAP_IMPORT_TRANSFERS_TO_LEAP,
) -> dict[str, object]:
    """
    Resume only the LEAP import step using already-generated export workbooks.

    Use this after a prior workflow run reached export generation but failed or
    was interrupted during LEAP import.
    """
    os.environ["LEAP_IMPORT_LOG_LEVEL"] = str(LEAP_IMPORT_LOG_LEVEL).strip()
    os.environ["LEAP_IMPORT_WARNING_PRINT_LIMIT"] = str(LEAP_IMPORT_WARNING_PRINT_LIMIT)
    if RUN_LEAP_FUEL_BRANCH_PROBE_AT_START:
        refresh_fuel_branch_catalog_from_leap(output_path=LEAP_FUEL_BRANCH_PROBE_OUTPUT_PATH)

    economy_list = workflow_common.normalize_economies(economies or ECONOMIES)
    scenario_list = workflow_common.normalize_workflow_scenarios(scenarios, SCENARIOS)
    supply_paths, transformation_paths, transfer_paths = _resolve_existing_results_supply_export_paths(
        economies=economy_list,
        scenarios=scenario_list,
        export_dir=export_dir,
    )
    print(
        "[INFO] Resuming LEAP import from existing exports: "
        f"supply={len(supply_paths)}, transformation={len(transformation_paths)}, transfers={len(transfer_paths)}"
    )
    leap_import_result = run_results_linked_leap_import(
        supply_paths,
        transformation_paths,
        transfer_export_paths=transfer_paths,
        scenarios=scenario_list,
        import_scenarios=import_scenarios,
        region=region,
        create_branches=create_branches,
        fill_branches=fill_branches,
        include_current_accounts=include_current_accounts,
        import_supply_to_leap=import_supply_to_leap,
        import_transformation_to_leap=import_transformation_to_leap,
        import_transfers_to_leap=import_transfers_to_leap,
    )
    return {
        "supply_export_paths": supply_paths,
        "transformation_export_paths": transformation_paths,
        "transfer_export_paths": transfer_paths,
        "leap_import_result": leap_import_result,
    }


def _filter_transformation_workbook_to_trade_targets(
    workbook_path: Path | str,
    allowed_variables: tuple[str, ...] = ("Import Target", "Export Target"),
) -> None:
    """Keep only trade-target rows in transformation LEAP export sheets."""
    path = _resolve(workbook_path)
    if not path.exists():
        return
    xl = pd.ExcelFile(path)
    allowed = {str(item).strip().lower() for item in allowed_variables if str(item).strip()}
    output_sheets: dict[str, pd.DataFrame] = {}

    def _find_header_row(raw: pd.DataFrame) -> int | None:
        for idx in range(len(raw.index)):
            values = {_normalize_template_header_value(item).lower() for item in raw.iloc[idx].tolist()}
            if "branch path" in values and "variable" in values:
                return int(idx)
        return None

    for sheet_name in xl.sheet_names:
        raw = pd.read_excel(path, sheet_name=sheet_name, header=None)
        if sheet_name not in {"LEAP", "FOR_VIEWING"}:
            output_sheets[sheet_name] = raw
            continue
        header_row = _find_header_row(raw)
        if header_row is None:
            output_sheets[sheet_name] = raw
            continue
        header_values = raw.iloc[header_row].tolist()
        preamble = raw.iloc[: header_row + 1].copy()
        data = raw.iloc[header_row + 1 :].copy()
        data.columns = header_values

        variable_col = None
        for col in data.columns:
            if _normalize_template_header_value(col).lower() == "variable":
                variable_col = col
                break
        if variable_col is None:
            output_sheets[sheet_name] = raw
            continue
        keep_mask = data[variable_col].astype(str).str.strip().str.lower().isin(allowed)
        filtered_data = data.loc[keep_mask].copy()
        if filtered_data.empty:
            output_sheets[sheet_name] = preamble.reset_index(drop=True)
        else:
            filtered_data = filtered_data.reindex(columns=header_values)
            filtered_data.columns = list(range(len(filtered_data.columns)))
            preamble.columns = list(range(len(preamble.columns)))
            output_sheets[sheet_name] = pd.concat([preamble, filtered_data], ignore_index=True)

    with pd.ExcelWriter(path, engine="openpyxl", mode="w") as writer:
        for sheet_name in xl.sheet_names:
            output_sheets[sheet_name].to_excel(writer, sheet_name=sheet_name, index=False, header=False)


def _read_leap_sheet_data_rows(workbook_path: Path | str, sheet_name: str = "LEAP") -> pd.DataFrame:
    """Read data rows from a LEAP-format export workbook sheet."""
    path = _resolve(workbook_path)
    if not path.exists():
        return pd.DataFrame()
    raw = pd.read_excel(path, sheet_name=sheet_name, header=None)
    header_row = None
    for idx in range(len(raw.index)):
        values = {_normalize_template_header_value(item).lower() for item in raw.iloc[idx].tolist()}
        if "branch path" in values and "variable" in values:
            header_row = int(idx)
            break
    if header_row is None:
        return pd.DataFrame()
    data = raw.iloc[header_row + 1 :].copy()
    data.columns = raw.iloc[header_row].tolist()
    if "Branch Path" not in data.columns:
        return pd.DataFrame()
    data = data[data["Branch Path"].notna()].copy()
    return data


def _read_branch_variable_rows(
    source_path: Path | str,
    sheet_name: str = "Export",
) -> pd.DataFrame:
    """Read a generic branch-variable table (xlsx/csv) with a discoverable header row."""
    path = _resolve(source_path)
    if not path.exists():
        return pd.DataFrame()

    suffix = path.suffix.lower()
    if suffix == ".csv":
        df = pd.read_csv(path)
        if {"Branch Path", "Variable"}.issubset(df.columns):
            return df.copy()
        return pd.DataFrame()

    raw = pd.read_excel(path, sheet_name=sheet_name, header=None)
    header_row = None
    for idx in range(len(raw.index)):
        values = {_normalize_template_header_value(item).lower() for item in raw.iloc[idx].tolist()}
        if "branch path" in values and "variable" in values:
            header_row = int(idx)
            break
    if header_row is None:
        return pd.DataFrame()
    data = raw.iloc[header_row + 1 :].copy()
    data.columns = raw.iloc[header_row].tolist()
    if "Branch Path" not in data.columns:
        return pd.DataFrame()
    data = data[data["Branch Path"].notna()].copy()
    return data


def _extract_catalog_rows_from_full_model_export(
    source_path: Path | str = FULL_MODEL_EXPORT_CATALOG_PATH,
    sheet_name: str = FULL_MODEL_EXPORT_CATALOG_SHEET,
) -> list[dict[str, object]]:
    """Parse full-model export into transformation/supply fuel catalog rows."""
    path = _resolve(source_path)
    if not path.exists():
        return []
    try:
        data = _read_branch_variable_rows(path, sheet_name=sheet_name)
    except Exception as exc:
        print(f"[WARN] Failed reading full model export catalog source {path}: {exc}")
        return []
    if data.empty:
        return []

    rows: list[dict[str, object]] = []

    def _parts(path_value: str) -> list[str]:
        return [part.strip() for part in str(path_value or "").split("\\") if str(part or "").strip()]

    for _, row in data.iterrows():
        branch_path = str(row.get("Branch Path") or "").strip()
        if not branch_path:
            continue
        variable = str(row.get("Variable") or "")
        scenario = str(row.get("Scenario") or "")
        parts = _parts(branch_path)
        if len(parts) < 2:
            continue

        if parts[0].lower() == "transformation":
            module = parts[1]
            fuel_group = ""
            fuel_name = ""
            for marker in ("Output Fuels", "Feedstock Fuels", "Auxiliary Fuels"):
                if marker in parts:
                    marker_index = parts.index(marker)
                    if marker_index + 1 < len(parts):
                        fuel_group = marker
                        fuel_name = parts[marker_index + 1]
                    break
            if fuel_name:
                rows.append(
                    {
                        "catalog_type": "transformation",
                        "source_workbook": path.name,
                        "scenario": scenario,
                        "module_or_root": module,
                        "fuel_group": fuel_group,
                        "fuel_name": fuel_name,
                        "branch_path": branch_path,
                        "variable": variable,
                        "catalog_source": "full_model_export",
                        "probe_status": "",
                    }
                )
            continue

        if parts[0].lower() == "resources" and len(parts) >= 3:
            root = parts[1]
            if root.lower() not in {"primary", "secondary"}:
                continue
            fuel_name = parts[2]
            rows.append(
                {
                    "catalog_type": "supply",
                    "source_workbook": path.name,
                    "scenario": scenario,
                    "module_or_root": root.title(),
                    "fuel_group": "",
                    "fuel_name": fuel_name,
                    "branch_path": branch_path,
                    "variable": variable,
                    "catalog_source": "full_model_export",
                    "probe_status": "",
                }
            )

    return rows


def _safe_leap_branch(app, path: str):
    """Return a LEAP branch object or None without raising."""
    branch_path = str(path or "").strip()
    if not branch_path:
        return None
    try:
        branches = app.Branches
        if not branches.Exists(branch_path):
            return None
        return branches.Item(branch_path)
    except Exception:
        return None


def _list_leap_child_branches(parent_branch) -> list[tuple[str, str]]:
    """List child branches as (name, full_path)."""
    rows: list[tuple[str, str]] = []
    if parent_branch is None:
        return rows
    try:
        children = parent_branch.Children
        count = int(children.Count)
    except Exception:
        return rows
    for idx in range(1, count + 1):
        try:
            child = children.Item(idx)
        except Exception:
            continue
        try:
            name = str(child.Name).strip()
        except Exception:
            name = ""
        try:
            full_name = str(child.FullName).strip()
        except Exception:
            full_name = ""
        if not name and full_name and "\\" in full_name:
            name = full_name.rsplit("\\", 1)[-1].strip()
        if name:
            rows.append((name, full_name or name))
    return rows


def _probe_branch_variable_expression(branch_obj, variable_candidates: Iterable[str]) -> tuple[str, str]:
    """Try candidate variables and read expression/value-like field to touch the branch."""
    for var_name in variable_candidates:
        candidate = str(var_name or "").strip()
        if not candidate:
            continue
        try:
            variable = branch_obj.Variable(candidate)
            if variable is None:
                continue
            # Touch one read path to validate branch-variable extraction.
            try:
                _ = str(variable.Expression)
            except Exception:
                _ = ""
            return candidate, "ok"
        except Exception:
            continue
    return "", "variable_not_found"


def refresh_fuel_branch_catalog_from_leap(
    output_path: Path | str = LEAP_FUEL_BRANCH_PROBE_OUTPUT_PATH,
) -> Path | None:
    """Touch transformation/supply fuel branches in LEAP and write a live probe CSV."""
    if get_analysis_input_write_mode() == "workbook":
        print(
            "[WORKBOOK MODE] Skipping live fuel-branch probe because it reads "
            "Analysis-view branches via LEAP API."
        )
        return None
    if not leap_api.is_available():
        print("[INFO] LEAP API unavailable; skipping live fuel-branch probe.")
        return None

    app = leap_api.connect()
    if app is None:
        print("[WARN] Failed to connect to LEAP for fuel-branch probe.")
        return None

    rows: list[dict[str, object]] = []
    try:
        active_scenario = str(getattr(app, "ActiveScenario", "") or "")
    except Exception:
        active_scenario = ""

    # Transformation module fuel branches.
    transformation_root = _safe_leap_branch(app, "Transformation")
    for module_name, module_full in _list_leap_child_branches(transformation_root):
        module_path = module_full or f"Transformation\\{module_name}"
        for fuel_group, probe_vars in (
            ("Output Fuels", ("Import Target", "Export Target", "Output Share", "Output")),
            ("Feedstock Fuels", ("Feedstock Fuel Share", "Inputs", "Output")),
            ("Auxiliary Fuels", ("Auxiliary Fuel Use", "Inputs", "Output")),
        ):
            group_path = f"{module_path}\\{fuel_group}"
            group_branch = _safe_leap_branch(app, group_path)
            if group_branch is None:
                continue
            for fuel_name, fuel_full in _list_leap_child_branches(group_branch):
                fuel_path = fuel_full or f"{group_path}\\{fuel_name}"
                fuel_branch = _safe_leap_branch(app, fuel_path)
                if fuel_branch is None:
                    continue
                variable_used, status = _probe_branch_variable_expression(fuel_branch, probe_vars)
                rows.append(
                    {
                        "catalog_type": "transformation",
                        "source_workbook": "__leap_probe__",
                        "scenario": active_scenario,
                        "module_or_root": module_name,
                        "fuel_group": fuel_group,
                        "fuel_name": fuel_name,
                        "branch_path": fuel_path,
                        "variable": variable_used,
                        "catalog_source": "leap_probe",
                        "probe_status": status,
                    }
                )

    # Supply fuel branches.
    for root_name in ("Primary", "Secondary"):
        root_path = f"Resources\\{root_name}"
        root_branch = _safe_leap_branch(app, root_path)
        if root_branch is None:
            continue
        for fuel_name, fuel_full in _list_leap_child_branches(root_branch):
            fuel_path = fuel_full or f"{root_path}\\{fuel_name}"
            fuel_branch = _safe_leap_branch(app, fuel_path)
            if fuel_branch is None:
                continue
            variable_used, status = _probe_branch_variable_expression(
                fuel_branch,
                ("Imports", "Exports", "Indigenous Production", "Unmet Requirements"),
            )
            rows.append(
                {
                    "catalog_type": "supply",
                    "source_workbook": "__leap_probe__",
                    "scenario": active_scenario,
                    "module_or_root": root_name,
                    "fuel_group": "",
                    "fuel_name": fuel_name,
                    "branch_path": fuel_path,
                    "variable": variable_used,
                    "catalog_source": "leap_probe",
                    "probe_status": status,
                }
            )

    out = _resolve(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    probe_df = pd.DataFrame(rows)
    if not probe_df.empty:
        probe_df = (
            probe_df.drop_duplicates(
                subset=[
                    "catalog_type",
                    "module_or_root",
                    "fuel_group",
                    "fuel_name",
                    "branch_path",
                ]
            )
            .sort_values(["catalog_type", "module_or_root", "fuel_group", "fuel_name"])
            .reset_index(drop=True)
        )
    probe_df.to_csv(out, index=False)
    print(f"[INFO] Wrote live LEAP fuel-branch probe catalog to {out}")
    return out


def _build_transformation_supply_fuel_catalog_df(
    *,
    transformation_export_paths: Iterable[Path],
    supply_export_paths: Iterable[Path],
    include_print_summary: bool = True,
) -> pd.DataFrame:
    """Build a transformation/supply fuel catalog dataframe."""
    rows: list[dict[str, object]] = []

    if USE_FULL_MODEL_EXPORT_CATALOG_SOURCE:
        full_model_rows = _extract_catalog_rows_from_full_model_export(
            source_path=FULL_MODEL_EXPORT_CATALOG_PATH,
            sheet_name=FULL_MODEL_EXPORT_CATALOG_SHEET,
        )
        if full_model_rows:
            rows.extend(full_model_rows)
            print(
                f"[INFO] Added {len(full_model_rows)} row(s) from full model export catalog source: "
                f"{_resolve(FULL_MODEL_EXPORT_CATALOG_PATH)}"
            )

    probe_path = _resolve(LEAP_FUEL_BRANCH_PROBE_OUTPUT_PATH)
    if probe_path.exists():
        try:
            probe_df = pd.read_csv(probe_path)
            if not probe_df.empty:
                for _, row in probe_df.iterrows():
                    rows.append(
                        {
                            "catalog_type": str(row.get("catalog_type") or ""),
                            "source_workbook": str(row.get("source_workbook") or "__leap_probe__"),
                            "scenario": str(row.get("scenario") or ""),
                            "module_or_root": str(row.get("module_or_root") or ""),
                            "fuel_group": str(row.get("fuel_group") or ""),
                            "fuel_name": str(row.get("fuel_name") or ""),
                            "branch_path": str(row.get("branch_path") or ""),
                            "variable": str(row.get("variable") or ""),
                            "catalog_source": str(row.get("catalog_source") or "leap_probe"),
                            "probe_status": str(row.get("probe_status") or ""),
                        }
                    )
        except Exception as exc:
            print(f"[WARN] Failed reading probe catalog {probe_path}: {exc}")

    def _parts(path_value: str) -> list[str]:
        return [part.strip() for part in str(path_value or "").split("\\") if str(part or "").strip()]

    for workbook in [Path(item) for item in transformation_export_paths]:
        if not workbook.exists():
            continue
        data = _read_leap_sheet_data_rows(workbook)
        if data.empty:
            continue
        for _, row in data.iterrows():
            branch_path = str(row.get("Branch Path") or "").strip()
            if not branch_path:
                continue
            parts = _parts(branch_path)
            if len(parts) < 4 or parts[0] != "Transformation":
                continue
            group_name = ""
            fuel_name = ""
            for marker in ("Output Fuels", "Feedstock Fuels", "Auxiliary Fuels"):
                if marker in parts:
                    marker_index = parts.index(marker)
                    if marker_index + 1 < len(parts):
                        group_name = marker
                        fuel_name = parts[marker_index + 1]
                    break
            if not fuel_name:
                continue
            rows.append(
                {
                    "catalog_type": "transformation",
                    "source_workbook": workbook.name,
                    "scenario": str(row.get("Scenario") or ""),
                    "module_or_root": parts[1],
                    "fuel_group": group_name,
                    "fuel_name": fuel_name,
                    "branch_path": branch_path,
                    "variable": str(row.get("Variable") or ""),
                    "catalog_source": "export",
                    "probe_status": "",
                }
            )

    for workbook in [Path(item) for item in supply_export_paths]:
        if not workbook.exists():
            continue
        data = _read_leap_sheet_data_rows(workbook)
        if data.empty:
            continue
        for _, row in data.iterrows():
            branch_path = str(row.get("Branch Path") or "").strip()
            if not branch_path:
                continue
            parts = _parts(branch_path)
            if len(parts) < 3 or parts[0] != "Resources":
                continue
            root_name = parts[1]
            if root_name not in {"Primary", "Secondary"}:
                continue
            rows.append(
                {
                    "catalog_type": "supply",
                    "source_workbook": workbook.name,
                    "scenario": str(row.get("Scenario") or ""),
                    "module_or_root": root_name,
                    "fuel_group": "",
                    "fuel_name": parts[2],
                    "branch_path": branch_path,
                    "variable": str(row.get("Variable") or ""),
                    "catalog_source": "export",
                    "probe_status": "",
                }
            )

    catalog_df = pd.DataFrame(rows)
    if catalog_df.empty:
        catalog_df = pd.DataFrame(
            columns=[
                "catalog_type",
                "source_workbook",
                "scenario",
                "module_or_root",
                "fuel_group",
                "fuel_name",
                "branch_path",
                "variable",
                "catalog_source",
                "probe_status",
            ]
        )
    else:
        catalog_df = (
            catalog_df.drop_duplicates(
                subset=[
                    "catalog_type",
                    "source_workbook",
                    "scenario",
                    "module_or_root",
                    "fuel_group",
                    "fuel_name",
                    "branch_path",
                    "variable",
                    "catalog_source",
                    "probe_status",
                ]
            )
            .sort_values(
                by=[
                    "catalog_type",
                    "catalog_source",
                    "module_or_root",
                    "fuel_group",
                    "fuel_name",
                    "branch_path",
                    "variable",
                ]
            )
            .reset_index(drop=True)
        )
    transformation_subset = catalog_df[catalog_df["catalog_type"] == "transformation"].copy()
    if include_print_summary and not transformation_subset.empty:
        print("\n=== Transformation Fuels By Module (catalog) ===")
        summary = (
            transformation_subset.groupby(["module_or_root", "fuel_group"], dropna=False)["fuel_name"]
            .nunique()
            .reset_index(name="unique_fuels")
        )
        for _, row in summary.sort_values(["module_or_root", "fuel_group"]).iterrows():
            print(
                f" - {row['module_or_root']} | {row['fuel_group']}: "
                f"{int(row['unique_fuels'])} fuel(s)"
            )

    supply_subset = catalog_df[catalog_df["catalog_type"] == "supply"].copy()
    if include_print_summary and not supply_subset.empty:
        print("\n=== Supply Fuels By Branch Root (catalog) ===")
        summary = (
            supply_subset.groupby(["module_or_root"], dropna=False)["fuel_name"]
            .nunique()
            .reset_index(name="unique_fuels")
        )
        for _, row in summary.sort_values(["module_or_root"]).iterrows():
            print(f" - {row['module_or_root']}: {int(row['unique_fuels'])} fuel(s)")

    return catalog_df


def _build_transformation_supply_fuel_catalog(
    *,
    transformation_export_paths: Iterable[Path],
    supply_export_paths: Iterable[Path],
    output_dir: Path | str = RESULTS_CHECKS_DIR,
) -> Path:
    """Build and save a CSV catalog of transformation/supply fuels by branch root."""
    output_path = _resolve(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    catalog_path = output_path / "transformation_supply_fuel_branch_catalog.csv"
    catalog_df = _build_transformation_supply_fuel_catalog_df(
        transformation_export_paths=transformation_export_paths,
        supply_export_paths=supply_export_paths,
        include_print_summary=True,
    )
    catalog_df.to_csv(catalog_path, index=False)
    print(f"[INFO] Wrote transformation/supply fuel catalog to {catalog_path}")
    return catalog_path


def _resolve_results_single_file_name(
    base_name: str,
    *,
    trade_mode: str,
    iteration_run_mode: str,
    economies: list[str] | None = None,
    scenarios: list[str] | None = None,
) -> str:
    """Return single-workbook filename with iterative mode, economy, and scenario suffixes."""
    raw_name = str(base_name or "").strip() or "supply_reconciliation_run_test.xlsx"
    path = Path(raw_name)
    stem = path.stem
    suffix = path.suffix or ".xlsx"
    trade_token = str(trade_mode or "").strip().lower()
    mode_token = str(iteration_run_mode or "").strip().lower()
    if trade_token == "capacity_unmet_iterative_balanced" and mode_token:
        safe_mode = re.sub(r"[^a-z0-9_-]+", "_", mode_token).strip("_")
        if safe_mode and not stem.lower().endswith(f"_{safe_mode}".lower()):
            stem = f"{stem}_{safe_mode}"
    if economies:
        economy_token = workflow_common.compact_filename_segment(
            "-".join(re.sub(r"[^A-Za-z0-9_]+", "", str(e)) for e in economies if str(e).strip()),
            max_length=32,
        )
        if economy_token:
            stem = f"{stem}_{economy_token}"
    if scenarios:
        scenario_token = "_".join(_abbreviate_scenario(s) for s in scenarios)
        if scenario_token:
            stem = f"{stem}_{scenario_token}"
    return f"{stem}{suffix}"


def _archive_existing_results_file_if_needed(
    workbook_path: Path | str,
    *,
    archive_dir: Path | str,
    min_hours: int | None,
) -> Path | None:
    """Archive an existing results workbook before overwrite when old enough."""
    source_path = Path(workbook_path)
    if not source_path.exists():
        return None
    min_age_hours = 0 if min_hours is None else float(min_hours)
    age_hours = (time.time() - source_path.stat().st_mtime) / 3600
    if age_hours < min_age_hours:
        return None
    archive_path = _resolve(archive_dir)
    archive_path.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target_path = archive_path / f"{source_path.stem}_{timestamp}{source_path.suffix}"
    shutil.copy2(source_path, target_path)
    print(f"[INFO] Archived existing results workbook to {target_path}")
    return target_path


def _archive_results_file_snapshot(
    workbook_path: Path | str,
    *,
    archive_dir: Path | str,
) -> Path | None:
    """Save an archive snapshot of the newly written results workbook."""
    source_path = Path(workbook_path)
    if not source_path.exists():
        return None
    archive_path = _resolve(archive_dir)
    archive_path.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target_path = archive_path / f"{source_path.stem}_{timestamp}{source_path.suffix}"
    shutil.copy2(source_path, target_path)
    print(f"[INFO] Archived results workbook snapshot to {target_path}")
    return target_path



def _write_diagnostic_report(
    rows: pd.DataFrame,
    path: Path,
    *,
    header: str,
    count_label: str,
    row_formatter: Callable[[pd.Series], str],
    more_label: str,
    preview_limit: int = 30,
) -> bool:
    """Write a sorted diagnostic CSV and print the standard WARN preview block.

    Shared reporting boilerplate for the reference-mismatch diagnostics:
    skip entirely when ``rows`` is empty, otherwise mkdir + sorted CSV write,
    a header line, a count line naming the saved path, an up-to-
    ``preview_limit`` row preview, and a "... plus N more" tail. Returns True
    when a report was written.
    """
    if not isinstance(rows, pd.DataFrame) or rows.empty:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    _sort_output_frame_for_csv(rows).to_csv(path, index=False)
    print(header)
    print(f"[WARN] {count_label}: {len(rows)} (details saved to {path})")
    for _, row in rows.head(preview_limit).iterrows():
        print(f"  - {row_formatter(row)}")
    if len(rows) > preview_limit:
        print(f"  ... plus {len(rows) - preview_limit} {more_label}")
    return True


def _resolve_ids_and_filter_unmatched_export_rows(
    df: pd.DataFrame,
    source_data: pd.DataFrame,
    source_path: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Stamp canonical LEAP IDs and filter unmatched aggregate-demand rows.

    ID resolution is delegated to the baseline-seed validator's canonical
    template lookup (``build_template_id_lookup``/``apply_template_ids``) so
    this writer and the final seed writer agree on what counts as a canonical
    match. The aggregate-demand retain/drop rule (CROSS-001): a row under
    ``Demand\\All demand aggregated\\`` with no canonical branch is dropped
    when its source Activity Level is zero in every year, and retained with
    ``BranchID=-1`` when nonzero, keeping the missing LEAP branch visible.
    Returns the resolved frame and the unmatched-ID report
    (Branch Path/Variable/Scenario/Region/reason).
    """

    def _norm(value: object) -> str:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return ""
        return str(value).strip().lower()

    id_cols = ["BranchID", "VariableID", "ScenarioID", "RegionID"]
    if source_data is None or source_data.empty:
        out = df.copy()
        for col in id_cols:
            out[col] = -1
        unmatched = out[["Branch Path", "Variable", "Scenario", "Region"]].copy()
        unmatched["reason"] = (
            "verification_export_missing"
            if not source_path.exists()
            else "verification_export_empty"
        )
        return out, unmatched

    required_source_cols = [*id_cols, "Branch Path", "Variable", "Scenario", "Region"]
    missing_source = [col for col in required_source_cols if col not in source_data.columns]
    if missing_source:
        print(
            "[WARN] Verification export missing expected ID/key columns; using fallback -1 IDs: "
            f"{missing_source}"
        )
        out = df.copy()
        for col in id_cols:
            out[col] = -1
        unmatched = out[["Branch Path", "Variable", "Scenario", "Region"]].copy()
        unmatched["reason"] = "verification_export_missing_required_columns"
        return out, unmatched

    out = df.copy().reset_index(drop=True)
    # Drop pre-existing ID columns so upstream values never leak through; the
    # canonical lookup below is the sole source of IDs in this workbook.
    out = out.drop(columns=[col for col in id_cols if col in out.columns], errors="ignore")
    lookup = build_template_id_lookup(source_data[required_source_cols])
    out = apply_template_ids(out, lookup)
    total = int(len(out))
    matched = int(out["BranchID"].ne(-1).sum())
    print(
        "[INFO] Resolved IDs from verification export via the canonical template lookup: "
        f"matched {matched}/{total}, unmatched {total - matched}."
    )

    # A nonzero aggregate-demand source with no canonical LEAP branch is
    # intentionally retained with BranchID=-1. It cannot import, but its
    # presence makes the missing model branch visible to the modeller.
    # Zero-only scaffolding is removed so it does not create false gaps.
    # Reviewed spelling aliases are excluded from the drop; the alias rescue
    # inside apply_template_ids already matched them where the template allows.
    reviewed_mapping_labels = {
        _norm(value) for value in KNOWN_LEAP_LABEL_EXCEPTIONS.values()
    }
    branch_text = out["Branch Path"].fillna("").astype(str)
    aggregate_missing_mask = (
        out["BranchID"].eq(-1)
        & branch_text.str.lower().str.startswith("demand\\all demand aggregated\\")
        & ~branch_text.str.rsplit("\\", n=1).str[-1].map(_norm).isin(reviewed_mapping_labels)
    )
    year_cols = [column for column in out.columns if _is_year_header(column)]
    activity_mask = out["Variable"].fillna("").astype(str).str.casefold().eq("activity level")
    nonzero_activity_paths: set[str] = set()
    if year_cols:
        activity_values = out.loc[activity_mask, year_cols].apply(
            pd.to_numeric,
            errors="coerce",
        ).fillna(0.0)
        nonzero_activity_rows = activity_values.abs().gt(1e-9).any(axis=1)
        nonzero_activity_paths = set(
            branch_text.loc[activity_values.index[nonzero_activity_rows]]
        )
    retain_missing_mask = aggregate_missing_mask & branch_text.isin(nonzero_activity_paths)
    drop_zero_placeholder_mask = aggregate_missing_mask & ~branch_text.isin(nonzero_activity_paths)
    if retain_missing_mask.any():
        retained_paths = sorted(set(branch_text[retain_missing_mask]))
        print(
            "[WARN] Retained "
            f"{int(retain_missing_mask.sum())} aggregate-demand row(s) with BranchID=-1 "
            "because their source Activity Level is nonzero. These rows expose LEAP "
            f"branches that need to be added or mapped: {retained_paths}"
        )
    if drop_zero_placeholder_mask.any():
        dropped_paths = sorted(set(branch_text[drop_zero_placeholder_mask]))
        print(
            "[INFO] Dropped "
            f"{int(drop_zero_placeholder_mask.sum())} zero-only aggregate-demand "
            "placeholder row(s) with no LEAP branch. "
            f"Branches: {dropped_paths}"
        )
        out = out.loc[~drop_zero_placeholder_mask].copy()

    unmatched = out[out["BranchID"].eq(-1)][
        ["Branch Path", "Variable", "Scenario", "Region"]
    ].copy()
    if not unmatched.empty:
        unmatched["reason"] = "no_verification_export_id_match"
        unmatched = unmatched.drop_duplicates().reset_index(drop=True)
    return out, unmatched


def save_results_linked_single_workbook(
    *,
    reconciliation_table: pd.DataFrame,
    sector_demand_table: pd.DataFrame,
    demand_table: pd.DataFrame,
    transformation_table: pd.DataFrame,
    transformation_sector_table: pd.DataFrame,
    supply_projection_table: pd.DataFrame,
    supply_primary_table: pd.DataFrame,
    transformation_target_rows: pd.DataFrame,
    fuel_branch_catalog_df: pd.DataFrame,
    base_df: pd.DataFrame,
    years: Iterable[int],
    economies: Iterable[str],
    scenarios: Iterable[str],
    export_paths: Iterable[Path],
    transformation_export_paths: Iterable[Path],
    transfer_export_paths: Iterable[Path],
    combined_export_path: Path | None,
    other_loss_own_use_proxy_paths: Iterable[Path] | None,
    aggregated_demand_workbook_paths: Iterable[Path] | None,
    probe_catalog_path: Path | None,
    leap_import_result: dict[str, object],
    output_dir: Path | str = OUTPUT_DIR,
    file_name: str = RESULTS_SINGLE_FILE_NAME,
    archive_dir: Path | str = RESULTS_SINGLE_FILE_ARCHIVE_DIR,
    archive_min_hours: int | None = None,
    archive_every_run: bool = RESULTS_SINGLE_FILE_ARCHIVE_EVERY_RUN,
) -> Path:
    """
    Write one LEAP-style Export workbook matching the full-model template structure.

    Output format intentionally mirrors `data/full model export.xlsx`:
    - single sheet: `Export`
    - preamble row with `Area:` / `Ver:`
    - header columns:
      BranchID, VariableID, ScenarioID, RegionID, Branch Path, Variable, Scenario,
      Region, Scale, Units, Per..., Method, <year columns...>
    """
    _ = (
        reconciliation_table,
        sector_demand_table,
        demand_table,
        transformation_table,
        transformation_sector_table,
        supply_projection_table,
        supply_primary_table,
        transformation_target_rows,
        fuel_branch_catalog_df,
        base_df,
        years,
        economies,
        scenarios,
        export_paths,
        transformation_export_paths,
        transfer_export_paths,
        other_loss_own_use_proxy_paths,
        probe_catalog_path,
        leap_import_result,
    )
    if combined_export_path is None or not Path(combined_export_path).exists():
        raise FileNotFoundError(
            "Combined supply/transformation workbook is required for single-file output "
            "but was not found."
        )
    if archive_min_hours is None:
        archive_min_hours = int(RESULTS_SINGLE_FILE_ARCHIVE_MIN_HOURS)

    def _infer_method_from_expression(expression: object) -> str:
        text = str(expression or "").strip()
        if not text:
            return "Interp"
        lowered = text.lower()
        for token in ("data", "interp", "step", "growth", "ramp"):
            if lowered.startswith(f"{token}("):
                if token == "data":
                    # LEAP import expects Method=Interp for imported Data(...) series.
                    return "Interp"
                return token.capitalize()
        if re.fullmatch(r"[-+]?\d+(\.\d+)?", text):
            return "Interp"
        return "Interp"

    def _normalize_merge_text(value: object) -> str:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return ""
        return str(value).strip().lower()

    def _normalize_metadata_text(value: object) -> str:
        """Normalize metadata cell values, treating NaN/None-like tokens as empty."""
        if value is None:
            return ""
        if pd.isna(value):
            return ""
        text = str(value).strip()
        if text.lower() in {"", "nan", "none", "null", "<na>", "na"}:
            return ""
        return text

    def _split_resource_branch_path(path_value: object) -> tuple[str, str]:
        """Return (`Resources\\<Root>`, leaf) for resource branch paths, else ('', '')."""
        parts = [part.strip() for part in str(path_value or "").split("\\") if part.strip()]
        if len(parts) < 3:
            return "", ""
        if parts[0].strip().lower() != "resources":
            return "", ""
        root = parts[1].strip().title()
        if root not in {"Primary", "Secondary"}:
            return "", ""
        return f"Resources\\{root}", parts[2].strip()

    def _branch_leaf_tokens(label: object) -> set[str]:
        """Tokenize branch leaf labels for safe fuzzy matching."""
        text = _normalize_merge_text(label)
        if not text:
            return set()
        tokens = re.findall(r"[a-z0-9]+", text)
        ignored = {
            "and",
            "of",
            "which",
            "the",
            "nonspecified",
            "non",
            "specified",
        }
        return {tok for tok in tokens if tok and tok not in ignored}

    def _remap_resource_branch_paths_from_reference(
        df: pd.DataFrame,
        source_data: pd.DataFrame,
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """
        Remap resource branch paths to canonical reference paths when confidently resolvable.

        Matching order:
        1) exact key match (no remap)
        2) unique same-scope leaf exact match
        3) unique same-scope token-subset match
        """
        out = df.copy()
        key_cols = ["Branch Path", "Variable", "Scenario", "Region"]
        remap_cols = ["Branch Path", "Variable", "Scenario", "Region", "reference_branch_path", "match_type"]
        unresolved_cols = ["Branch Path", "Variable", "Scenario", "Region", "issue", "candidate_branch_paths"]
        empty_remap = pd.DataFrame(columns=remap_cols)
        empty_unresolved = pd.DataFrame(columns=unresolved_cols)
        if source_data is None or source_data.empty:
            return out, empty_remap, empty_unresolved
        if any(col not in source_data.columns for col in key_cols):
            return out, empty_remap, empty_unresolved
        if any(col not in out.columns for col in key_cols):
            return out, empty_remap, empty_unresolved

        source = source_data[key_cols].copy()
        for col in key_cols:
            source[f"__k_{col}"] = source[col].map(_normalize_merge_text)
            out[f"__k_{col}"] = out[col].map(_normalize_merge_text)

        source = source.drop_duplicates(
            subset=[f"__k_{col}" for col in key_cols],
            keep="first",
        ).copy()
        source["__root"], source["__leaf"] = zip(
            *source["Branch Path"].map(_split_resource_branch_path)
        )
        source = source[source["__root"] != ""].copy()
        if source.empty:
            out = out.drop(columns=[f"__k_{col}" for col in key_cols], errors="ignore")
            return out, empty_remap, empty_unresolved
        source["__k_root"] = source["__root"].map(_normalize_merge_text)
        source["__k_leaf"] = source["__leaf"].map(_normalize_merge_text)
        source["__leaf_tokens"] = source["__leaf"].map(_branch_leaf_tokens)

        source_exact_keys = {
            tuple(row[f"__k_{col}"] for col in key_cols)
            for _, row in source.iterrows()
        }
        source_scope_groups: dict[tuple[str, str, str, str], list[dict[str, object]]] = {}
        for _, row in source.iterrows():
            scope_key = (
                str(row["__k_Variable"]),
                str(row["__k_Scenario"]),
                str(row["__k_Region"]),
                str(row["__k_root"]),
            )
            source_scope_groups.setdefault(scope_key, []).append(
                {
                    "branch_path": str(row["Branch Path"]),
                    "k_leaf": str(row["__k_leaf"]),
                    "leaf_tokens": set(row["__leaf_tokens"]),
                }
            )

        remap_rows: list[dict[str, object]] = []
        unresolved_rows: list[dict[str, object]] = []
        for idx, row in out.iterrows():
            branch_path = str(row.get("Branch Path") or "")
            root, leaf = _split_resource_branch_path(branch_path)
            if not root:
                continue
            key_tuple = tuple(str(row.get(f"__k_{col}") or "") for col in key_cols)
            if key_tuple in source_exact_keys:
                continue
            scope_key = (
                str(row.get("__k_Variable") or ""),
                str(row.get("__k_Scenario") or ""),
                str(row.get("__k_Region") or ""),
                _normalize_merge_text(root),
            )
            candidates = source_scope_groups.get(scope_key, [])
            if not candidates:
                unresolved_rows.append(
                    {
                        "Branch Path": branch_path,
                        "Variable": row.get("Variable", ""),
                        "Scenario": row.get("Scenario", ""),
                        "Region": row.get("Region", ""),
                        "issue": "no_reference_candidates_in_scope",
                        "candidate_branch_paths": "",
                    }
                )
                continue
            leaf_norm = _normalize_merge_text(leaf)
            exact_leaf = [item for item in candidates if item.get("k_leaf") == leaf_norm and leaf_norm]
            if len(exact_leaf) == 1:
                new_path = str(exact_leaf[0]["branch_path"])
                out.at[idx, "Branch Path"] = new_path
                remap_rows.append(
                    {
                        "Branch Path": branch_path,
                        "Variable": row.get("Variable", ""),
                        "Scenario": row.get("Scenario", ""),
                        "Region": row.get("Region", ""),
                        "reference_branch_path": new_path,
                        "match_type": "leaf_exact_in_scope",
                    }
                )
                continue
            if len(exact_leaf) > 1:
                unresolved_rows.append(
                    {
                        "Branch Path": branch_path,
                        "Variable": row.get("Variable", ""),
                        "Scenario": row.get("Scenario", ""),
                        "Region": row.get("Region", ""),
                        "issue": "ambiguous_leaf_exact_candidates",
                        "candidate_branch_paths": " | ".join(
                            sorted(str(item["branch_path"]) for item in exact_leaf)
                        ),
                    }
                )
                continue

            leaf_tokens = _branch_leaf_tokens(leaf)
            fuzzy = [
                item
                for item in candidates
                if leaf_tokens
                and item.get("leaf_tokens")
                and (
                    leaf_tokens.issubset(set(item["leaf_tokens"]))
                    or set(item["leaf_tokens"]).issubset(leaf_tokens)
                )
            ]
            if len(fuzzy) == 1:
                new_path = str(fuzzy[0]["branch_path"])
                out.at[idx, "Branch Path"] = new_path
                remap_rows.append(
                    {
                        "Branch Path": branch_path,
                        "Variable": row.get("Variable", ""),
                        "Scenario": row.get("Scenario", ""),
                        "Region": row.get("Region", ""),
                        "reference_branch_path": new_path,
                        "match_type": "leaf_token_subset_in_scope",
                    }
                )
                continue

            issue = "no_confident_leaf_match"
            if len(fuzzy) > 1:
                issue = "ambiguous_leaf_token_subset_candidates"
            unresolved_rows.append(
                {
                    "Branch Path": branch_path,
                    "Variable": row.get("Variable", ""),
                    "Scenario": row.get("Scenario", ""),
                    "Region": row.get("Region", ""),
                    "issue": issue,
                    "candidate_branch_paths": " | ".join(
                        sorted(str(item["branch_path"]) for item in (fuzzy or candidates))
                    ),
                }
            )

        out = out.drop(columns=[f"__k_{col}" for col in key_cols], errors="ignore")
        remap_df = (
            pd.DataFrame(remap_rows, columns=remap_cols)
            .drop_duplicates()
            .reset_index(drop=True)
            if remap_rows
            else empty_remap
        )
        unresolved_df = (
            pd.DataFrame(unresolved_rows, columns=unresolved_cols)
            .drop_duplicates()
            .reset_index(drop=True)
            if unresolved_rows
            else empty_unresolved
        )
        return out, remap_df, unresolved_df

    def _merge_levels_from_reference_data(
        df: pd.DataFrame,
        reference_df: pd.DataFrame,
    ) -> pd.DataFrame:
        out = df.copy()
        if reference_df is None or reference_df.empty:
            reference_df = pd.DataFrame()
        key_cols = ["Branch Path", "Variable", "Scenario", "Region"]
        detected_level_cols = []
        for col in reference_df.columns:
            match = re.fullmatch(r"Level\s+(\d+)", str(col).strip(), flags=re.IGNORECASE)
            if match:
                detected_level_cols.append((int(match.group(1)), f"Level {int(match.group(1))}"))
        detected_level_cols = sorted({item for item in detected_level_cols}, key=lambda item: item[0])
        base_level_cols = [f"Level {idx}" for idx in range(1, 9)]
        merged_level_cols = []
        seen = set()
        for _, name in detected_level_cols:
            if name not in seen:
                seen.add(name)
                merged_level_cols.append(name)
        for name in base_level_cols:
            if name not in seen:
                seen.add(name)
                merged_level_cols.append(name)

        if all(col in reference_df.columns for col in key_cols):
            lookup_cols = key_cols + [col for col in merged_level_cols if col in reference_df.columns]
            level_lookup = reference_df[lookup_cols].copy()
            for col in key_cols:
                level_lookup[f"__k_{col}"] = level_lookup[col].map(_normalize_merge_text)
                out[f"__k_{col}"] = out[col].map(_normalize_merge_text)
            level_lookup = level_lookup.drop_duplicates(
                subset=[f"__k_{col}" for col in key_cols],
                keep="first",
            )
            merge_cols = [f"__k_{col}" for col in key_cols]
            value_cols = [col for col in merged_level_cols if col in level_lookup.columns]
            out = out.merge(
                level_lookup[merge_cols + value_cols],
                on=merge_cols,
                how="left",
            )
            out = out.drop(columns=merge_cols, errors="ignore")

        for col in merged_level_cols:
            if col not in out.columns:
                out[col] = ""

        # Fallback: derive levels from branch path when lookup rows were missing.
        parts_series = out["Branch Path"].fillna("").astype(str).map(
            lambda text: [part.strip() for part in text.split("\\") if part.strip()]
        )
        for idx, col in enumerate(merged_level_cols, start=1):
            existing = out[col].fillna("").astype(str)
            missing_mask = existing.str.strip().eq("")
            if missing_mask.any():
                fill_values = parts_series.map(
                    lambda parts: parts[idx - 1] if idx - 1 < len(parts) else ""
                )
                out.loc[missing_mask, col] = fill_values[missing_mask]
        return out

    def _filter_unmatched_zero_supply_rows_against_reference(
        df: pd.DataFrame,
        source_data: pd.DataFrame,
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """
        Drop all-zero Resources rows not present in reference export keys.

        Returns:
        - filtered dataframe
        - dropped unmatched-zero rows report
        - unmatched-nonzero rows report (kept in output, requires review)
        """
        key_cols = ["Branch Path", "Variable", "Scenario", "Region"]
        empty_report = pd.DataFrame(columns=key_cols + ["year_abs_sum", "reason"])
        if source_data is None or source_data.empty:
            return df.copy(), empty_report, empty_report
        if any(col not in source_data.columns for col in key_cols):
            return df.copy(), empty_report, empty_report
        out = df.copy()
        if any(col not in out.columns for col in key_cols):
            return out, empty_report, empty_report

        source = source_data.copy()
        source_resource = source[
            source["Branch Path"].fillna("").astype(str).str.startswith("Resources\\")
        ].copy()
        if source_resource.empty:
            return out, empty_report, empty_report

        for col in key_cols:
            source_resource[f"__k_{col}"] = source_resource[col].map(_normalize_merge_text)
            out[f"__k_{col}"] = out[col].map(_normalize_merge_text)

        source_key_set = {
            tuple(row[f"__k_{col}"] for col in key_cols)
            for _, row in source_resource.drop_duplicates(
                subset=[f"__k_{col}" for col in key_cols],
                keep="first",
            ).iterrows()
        }

        resource_mask = out["Branch Path"].fillna("").astype(str).str.startswith("Resources\\")
        out["__resource_key"] = out.apply(
            lambda row: tuple(row[f"__k_{col}"] for col in key_cols),
            axis=1,
        )
        unmatched_resource_mask = resource_mask & ~out["__resource_key"].isin(source_key_set)
        if not unmatched_resource_mask.any():
            out = out.drop(
                columns=[*["__k_" + col for col in key_cols], "__resource_key"],
                errors="ignore",
            )
            return out, empty_report, empty_report

        year_cols = [col for col in out.columns if _is_year_header(col)]
        if year_cols:
            year_abs_sum = (
                out[year_cols].apply(pd.to_numeric, errors="coerce").fillna(0.0).abs().sum(axis=1)
            )
        else:
            year_abs_sum = pd.Series(0.0, index=out.index)
        out["__year_abs_sum"] = year_abs_sum

        drop_mask = unmatched_resource_mask & (out["__year_abs_sum"] <= 0.0)
        keep_nonzero_mask = unmatched_resource_mask & (out["__year_abs_sum"] > 0.0)

        dropped_report = out.loc[drop_mask, key_cols + ["__year_abs_sum"]].copy()
        kept_nonzero_report = out.loc[keep_nonzero_mask, key_cols + ["__year_abs_sum"]].copy()
        if not dropped_report.empty:
            dropped_report = dropped_report.rename(columns={"__year_abs_sum": "year_abs_sum"})
            dropped_report["reason"] = "unmatched_resource_key_all_zero_row_dropped"
            dropped_report = dropped_report.drop_duplicates().reset_index(drop=True)
        if not kept_nonzero_report.empty:
            kept_nonzero_report = kept_nonzero_report.rename(columns={"__year_abs_sum": "year_abs_sum"})
            kept_nonzero_report["reason"] = "unmatched_resource_key_nonzero_row_kept"
            kept_nonzero_report = kept_nonzero_report.drop_duplicates().reset_index(drop=True)

        out = out.loc[~drop_mask].copy()
        out = out.drop(
            columns=[*["__k_" + col for col in key_cols], "__resource_key", "__year_abs_sum"],
            errors="ignore",
        )
        return out, dropped_report, kept_nonzero_report

    def _load_results_verification_data() -> tuple[pd.DataFrame, Path, str]:
        source_path = _resolve(RESULTS_VERIFICATION_EXPORT_PATH)
        source_sheet = RESULTS_VERIFICATION_EXPORT_SHEET
        if not USE_RESULTS_VERIFICATION_EXPORT_SOURCE:
            return pd.DataFrame(), source_path, source_sheet
        if not source_path.exists():
            print(f"[WARN] Verification export file not found: {source_path}")
            return pd.DataFrame(), source_path, source_sheet
        try:
            _, source_data, _ = _read_workbook_sheet_with_header_detection(
                source_path,
                source_sheet,
            )
            if source_data.empty:
                print(
                    f"[WARN] Verification export is empty: {source_path} (sheet={source_sheet})"
                )
            else:
                print(
                    "[INFO] Loaded verification export source from data/: "
                    f"{source_path} (sheet={source_sheet}, rows={len(source_data)})"
                )
            return source_data, source_path, source_sheet
        except Exception as exc:
            print(
                f"[WARN] Failed reading verification export source {source_path} "
                f"(sheet={source_sheet}): {exc}"
            )
            return pd.DataFrame(), source_path, source_sheet

    def _collect_metadata_mismatches_against_reference(
        df: pd.DataFrame,
        source_data: pd.DataFrame,
    ) -> pd.DataFrame:
        if source_data is None or source_data.empty:
            return pd.DataFrame(
                columns=[
                    "Branch Path",
                    "Variable",
                    "Scenario",
                    "Region",
                    "column",
                    "generated_value",
                    "reference_value",
                ]
            )
        key_cols = ["Branch Path", "Variable", "Scenario", "Region"]
        compare_cols = ["Scale", "Units", "Per..."]
        required = key_cols + compare_cols
        if any(col not in source_data.columns for col in required):
            return pd.DataFrame(
                columns=[
                    "Branch Path",
                    "Variable",
                    "Scenario",
                    "Region",
                    "column",
                    "generated_value",
                    "reference_value",
                ]
            )
        src = source_data[required].copy()
        for col in key_cols:
            src[f"__k_{col}"] = src[col].map(_normalize_merge_text)
        src = src.drop_duplicates(
            subset=[f"__k_{col}" for col in key_cols],
            keep="first",
        )
        out = df.copy()
        for col in key_cols:
            out[f"__k_{col}"] = out[col].map(_normalize_merge_text)
        merged = out.merge(
            src[
                [f"__k_{col}" for col in key_cols]
                + [f"{col}" for col in compare_cols]
            ].rename(columns={col: f"ref_{col}" for col in compare_cols}),
            on=[f"__k_{col}" for col in key_cols],
            how="left",
        )
        mismatches: list[dict[str, object]] = []
        for _, row in merged.iterrows():
            for col in compare_cols:
                left = _normalize_metadata_text(row.get(col))
                right = _normalize_metadata_text(row.get(f"ref_{col}"))
                if not right:
                    continue
                if left == right:
                    continue
                mismatches.append(
                    {
                        "Branch Path": row.get("Branch Path"),
                        "Variable": row.get("Variable"),
                        "Scenario": row.get("Scenario"),
                        "Region": row.get("Region"),
                        "column": col,
                        "generated_value": left,
                        "reference_value": right,
                    }
                )
        if not mismatches:
            return pd.DataFrame(
                columns=[
                    "Branch Path",
                    "Variable",
                    "Scenario",
                    "Region",
                    "column",
                    "generated_value",
                    "reference_value",
                ]
            )
        mismatch_df = pd.DataFrame(mismatches).drop_duplicates().reset_index(drop=True)
        return mismatch_df

    def _apply_reference_non_value_metadata(
        df: pd.DataFrame,
        source_data: pd.DataFrame,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Use canonical export metadata wherever the reference supplies it."""
        key_cols = ["Branch Path", "Variable", "Scenario", "Region"]
        if source_data is None or source_data.empty:
            return df.copy(), pd.DataFrame(
                columns=key_cols + ["column", "filled_value"]
            )
        reference_fields = ["Scale", "Units", "Per...", "Method"]
        available_ref_fields = [col for col in reference_fields if col in source_data.columns]
        if not available_ref_fields or any(col not in source_data.columns for col in key_cols):
            return df.copy(), pd.DataFrame(
                columns=key_cols + ["column", "filled_value"]
            )

        out = df.copy()
        src = source_data[key_cols + available_ref_fields].copy()
        for col in key_cols:
            src[f"__k_{col}"] = src[col].map(_normalize_merge_text)
            out[f"__k_{col}"] = out[col].map(_normalize_merge_text)
        key_join_cols = [f"__k_{col}" for col in key_cols]
        src = src.drop_duplicates(subset=key_join_cols, keep="first")
        merged = out.merge(
            src[key_join_cols + available_ref_fields].rename(
                columns={col: f"ref_{col}" for col in available_ref_fields}
            ),
            on=key_join_cols,
            how="left",
        )

        filled_rows: list[dict[str, object]] = []
        for col in available_ref_fields:
            if col not in merged.columns:
                merged[col] = ""
            current_values = merged[col].map(_normalize_metadata_text)
            reference_values = merged[f"ref_{col}"].map(_normalize_metadata_text)
            # The full-model export is authoritative for import metadata. This
            # intentionally replaces explicit generated values such as PJ when
            # the corresponding model branch is configured as GJ.
            apply_mask = reference_values.ne("") & current_values.ne(reference_values)
            if not apply_mask.any():
                continue
            merged.loc[apply_mask, col] = reference_values[apply_mask]
            for _, row in merged.loc[apply_mask, key_cols + [col]].iterrows():
                filled_rows.append(
                    {
                        "Branch Path": row.get("Branch Path"),
                        "Variable": row.get("Variable"),
                        "Scenario": row.get("Scenario"),
                        "Region": row.get("Region"),
                        "column": col,
                        "filled_value": row.get(col),
                    }
                )

        merged = merged.drop(columns=key_join_cols + [f"ref_{col}" for col in available_ref_fields], errors="ignore")
        fill_df = (
            pd.DataFrame(filled_rows).drop_duplicates().reset_index(drop=True)
            if filled_rows
            else pd.DataFrame(columns=key_cols + ["column", "filled_value"])
        )
        return merged, fill_df

    def _collect_gigajoule_template_rows(
        df: pd.DataFrame,
        source_data: pd.DataFrame,
    ) -> pd.DataFrame:
        """List generated rows whose canonical template unit is Gigajoule."""
        columns = [
            "Branch Path", "Variable", "Scenario", "Region",
            "generated_units", "template_units",
        ]
        key_cols = ["Branch Path", "Variable", "Scenario", "Region"]
        if (
            df is None or df.empty or source_data is None or source_data.empty
            or any(col not in source_data.columns for col in [*key_cols, "Units"])
        ):
            return pd.DataFrame(columns=columns)
        generated = df[key_cols + (["Units"] if "Units" in df.columns else [])].copy()
        if "Units" not in generated.columns:
            generated["Units"] = ""
        template = source_data[key_cols + ["Units"]].copy()
        for col in key_cols:
            generated[f"__k_{col}"] = generated[col].map(_normalize_merge_text)
            template[f"__k_{col}"] = template[col].map(_normalize_merge_text)
        join_cols = [f"__k_{col}" for col in key_cols]
        template = template.drop_duplicates(subset=join_cols, keep="first")
        merged = generated.merge(
            template[join_cols + ["Units"]].rename(columns={"Units": "template_units"}),
            on=join_cols,
            how="left",
        )
        merged["generated_units"] = merged["Units"].map(_normalize_metadata_text)
        merged["template_units"] = merged["template_units"].map(_normalize_metadata_text)
        result = merged[merged["template_units"].str.casefold().eq("gigajoule")].copy()
        return result[columns].drop_duplicates().reset_index(drop=True)

    def _load_field_mapping_table_for_validation() -> pd.DataFrame:
        """Load configured analysis-input mapping workbook used for metadata checks."""
        path = Path(
            str(
                getattr(
                    workflow_cfg,
                    "ANALYSIS_INPUT_FIELD_MAPPING_PATH",
                    REPO_ROOT / "config" / "leap_export_workbook_mappings.xlsx",
                )
            ).replace("\\", "/")
        )
        if not path.is_absolute():
            path = REPO_ROOT / path
        sheet = str(
            getattr(
                workflow_cfg,
                "ANALYSIS_INPUT_FIELD_MAPPING_SHEET",
                "field_mappings",
            )
        ).strip() or "field_mappings"
        if not config_table_exists(path, sheet):
            return pd.DataFrame()
        try:
            table = read_config_table(path, sheet_name=sheet)
        except Exception as exc:
            print(
                "[WARN] Failed reading analysis-input field mapping workbook for validation: "
                f"{path} (sheet={sheet}) -> {exc}"
            )
            return pd.DataFrame()
        table.columns = [str(col).strip().lower() for col in table.columns]
        required = {
            "enabled",
            "match_scope",
            "branch_path",
            "variable",
            "units",
            "scale",
            "per",
            "confidence",
            "notes",
        }
        missing = sorted(required.difference(table.columns))
        if missing:
            print(
                "[WARN] Field mapping workbook missing required columns for validation: "
                f"{missing}"
            )
            return pd.DataFrame()
        return table

    def _collect_mapping_config_mismatches_against_reference(
        mapping_table: pd.DataFrame,
        source_data: pd.DataFrame,
    ) -> pd.DataFrame:
        """Compare enabled config mapping metadata values against reference export metadata."""
        if mapping_table is None or mapping_table.empty or source_data is None or source_data.empty:
            return pd.DataFrame(
                columns=[
                    "match_scope",
                    "branch_path",
                    "variable",
                    "field",
                    "config_value",
                    "reference_values",
                    "issue",
                ]
            )
        key_cols = ["Branch Path", "Variable"]
        compare_cols = {"units": "Units", "scale": "Scale", "per": "Per..."}
        required_source = ["Branch Path", "Variable", "Scale", "Units", "Per..."]
        if any(col not in source_data.columns for col in required_source):
            return pd.DataFrame(
                columns=[
                    "match_scope",
                    "branch_path",
                    "variable",
                    "field",
                    "config_value",
                    "reference_values",
                    "issue",
                ]
            )
        source = source_data[required_source].copy()
        source["__k_branch"] = source["Branch Path"].map(_normalize_merge_text)
        source["__k_variable"] = source["Variable"].map(_normalize_merge_text)

        def _is_enabled(value: object) -> bool:
            token = str(value or "").strip().lower()
            return token in {"1", "true", "yes", "y", "on"}

        mismatches: list[dict[str, object]] = []
        enabled_rows = mapping_table[mapping_table["enabled"].map(_is_enabled)].copy()
        for _, row in enabled_rows.iterrows():
            scope = str(row.get("match_scope") or "").strip().lower()
            branch = str(row.get("branch_path") or "").strip()
            variable = str(row.get("variable") or "").strip()
            if scope not in {"branch_variable", "variable", "branch"}:
                continue
            scoped = source
            if scope == "branch_variable":
                if not branch or not variable:
                    continue
                scoped = scoped[
                    (scoped["__k_branch"] == _normalize_merge_text(branch))
                    & (scoped["__k_variable"] == _normalize_merge_text(variable))
                ]
            elif scope == "variable":
                if not variable:
                    continue
                scoped = scoped[scoped["__k_variable"] == _normalize_merge_text(variable)]
            else:
                if not branch:
                    continue
                scoped = scoped[scoped["__k_branch"] == _normalize_merge_text(branch)]

            if scoped.empty:
                for cfg_field in compare_cols.keys():
                    cfg_value = _normalize_metadata_text(row.get(cfg_field))
                    if cfg_value:
                        mismatches.append(
                            {
                                "match_scope": scope,
                                "branch_path": branch,
                                "variable": variable,
                                "field": cfg_field,
                                "config_value": cfg_value,
                                "reference_values": "",
                                "issue": "no_reference_match",
                            }
                        )
                continue

            for cfg_field, ref_col in compare_cols.items():
                cfg_value = _normalize_metadata_text(row.get(cfg_field))
                if not cfg_value:
                    continue
                ref_values = sorted(
                    {
                        _normalize_metadata_text(value)
                        for value in scoped[ref_col].tolist()
                        if _normalize_metadata_text(value)
                    }
                )
                if not ref_values:
                    mismatches.append(
                        {
                            "match_scope": scope,
                            "branch_path": branch,
                            "variable": variable,
                            "field": cfg_field,
                            "config_value": cfg_value,
                            "reference_values": "",
                            "issue": "reference_value_missing",
                        }
                    )
                    continue
                if cfg_value not in ref_values:
                    mismatches.append(
                        {
                            "match_scope": scope,
                            "branch_path": branch,
                            "variable": variable,
                            "field": cfg_field,
                            "config_value": cfg_value,
                            "reference_values": " | ".join(ref_values[:10]),
                            "issue": "config_reference_mismatch",
                        }
                    )
        if not mismatches:
            return pd.DataFrame(
                columns=[
                    "match_scope",
                    "branch_path",
                    "variable",
                    "field",
                    "config_value",
                    "reference_values",
                    "issue",
                ]
            )
        return pd.DataFrame(mismatches).drop_duplicates().reset_index(drop=True)

    def _extract_area_and_version(*preambles: pd.DataFrame) -> tuple[str, object]:
        default_area = "supply_reconciliation_run"
        default_version: object = 2
        resolved_area: str | None = None
        resolved_version: object | None = None
        for preamble in preambles:
            if preamble is None or preamble.empty:
                continue
            for row_idx in range(len(preamble.index)):
                row = [
                    _normalize_template_header_value(item)
                    for item in preamble.iloc[row_idx].tolist()
                ]
                for idx, value in enumerate(row):
                    token = str(value).strip().lower()
                    if token == "area:" and idx + 1 < len(row) and resolved_area is None:
                        candidate = _normalize_template_header_value(row[idx + 1])
                        if candidate:
                            resolved_area = candidate
                    if token == "ver:" and idx + 1 < len(row) and resolved_version is None:
                        candidate = row[idx + 1]
                        if candidate is not None and str(candidate).strip() != "":
                            resolved_version = candidate
        return (
            resolved_area if resolved_area is not None else default_area,
            resolved_version if resolved_version is not None else default_version,
        )

    combined_path = _resolve(combined_export_path)
    viewing_preamble, viewing_data, _ = _read_workbook_sheet_with_header_detection(
        combined_path,
        "FOR_VIEWING",
    )
    leap_preamble, leap_data, _ = _read_workbook_sheet_with_header_detection(
        combined_path,
        "LEAP",
    )
    if viewing_data.empty:
        raise ValueError(
            f"Combined workbook '{combined_path.name}' has no FOR_VIEWING data rows."
        )

    required = ["Branch Path", "Variable", "Scenario", "Region", "Scale", "Units", "Per..."]
    missing = [col for col in required if col not in viewing_data.columns]
    if missing:
        raise ValueError(
            f"Combined workbook '{combined_path.name}' is missing required columns for Export sheet: {missing}"
        )

    method_by_key: dict[tuple[str, str, str, str], str] = {}
    if not leap_data.empty and "Expression" in leap_data.columns:
        key_cols = ["Branch Path", "Variable", "Scenario", "Region"]
        if all(col in leap_data.columns for col in key_cols):
            for _, row in leap_data.iterrows():
                key = tuple(str(row.get(col) or "").strip() for col in key_cols)
                if not all(key):
                    continue
                method_by_key[key] = _infer_method_from_expression(row.get("Expression"))

    # Merge other-loss / own-use proxy data into the export.
    proxy_viewing_frames: list[pd.DataFrame] = []
    for proxy_path_item in other_loss_own_use_proxy_paths or []:
        proxy_path = Path(proxy_path_item)
        if not proxy_path.exists():
            print(f"[WARN] other_loss_own_use proxy workbook not found, skipping: {proxy_path}")
            continue
        try:
            _, proxy_viewing, _ = _read_workbook_sheet_with_header_detection(proxy_path, "FOR_VIEWING")
            _, proxy_leap, _ = _read_workbook_sheet_with_header_detection(proxy_path, "LEAP")
        except Exception as exc:
            print(f"[WARN] Failed reading other_loss_own_use proxy workbook {proxy_path.name}: {exc}")
            continue
        if not proxy_viewing.empty:
            proxy_viewing_frames.append(proxy_viewing)
        if not proxy_leap.empty and "Expression" in proxy_leap.columns:
            key_cols_proxy = ["Branch Path", "Variable", "Scenario", "Region"]
            if all(col in proxy_leap.columns for col in key_cols_proxy):
                for _, row in proxy_leap.iterrows():
                    key = tuple(str(row.get(col) or "").strip() for col in key_cols_proxy)
                    if not all(key):
                        continue
                    method_by_key.setdefault(key, _infer_method_from_expression(row.get("Expression")))

    if proxy_viewing_frames:
        combined_viewing = pd.concat([viewing_data] + proxy_viewing_frames, ignore_index=True)
        print(
            f"[INFO] Merged {sum(len(f) for f in proxy_viewing_frames)} other_loss_own_use proxy rows "
            f"into Export sheet ({len(proxy_viewing_frames)} workbook(s))."
        )
    else:
        combined_viewing = viewing_data

    # Merge aggregated demand workbook data into the export.
    agg_demand_viewing_frames: list[pd.DataFrame] = []
    for agg_path_item in aggregated_demand_workbook_paths or []:
        agg_path = Path(agg_path_item)
        if not agg_path.exists():
            print(f"[WARN] aggregated demand workbook not found, skipping: {agg_path}")
            continue
        try:
            _, agg_viewing, _ = _read_workbook_sheet_with_header_detection(agg_path, "FOR_VIEWING")
            _, agg_leap, _ = _read_workbook_sheet_with_header_detection(agg_path, "LEAP")
        except Exception as exc:
            print(f"[WARN] Failed reading aggregated demand workbook {agg_path.name}: {exc}")
            continue
        if not agg_viewing.empty:
            agg_demand_viewing_frames.append(agg_viewing)
        if not agg_leap.empty and "Expression" in agg_leap.columns:
            key_cols_agg = ["Branch Path", "Variable", "Scenario", "Region"]
            if all(col in agg_leap.columns for col in key_cols_agg):
                for _, row in agg_leap.iterrows():
                    key = tuple(str(row.get(col) or "").strip() for col in key_cols_agg)
                    if not all(key):
                        continue
                    method_by_key.setdefault(key, _infer_method_from_expression(row.get("Expression")))

    if agg_demand_viewing_frames:
        combined_viewing = pd.concat([combined_viewing] + agg_demand_viewing_frames, ignore_index=True)
        print(
            f"[INFO] Merged {sum(len(f) for f in agg_demand_viewing_frames)} aggregated demand rows "
            f"into Export sheet ({len(agg_demand_viewing_frames)} workbook(s))."
        )

    export_df = combined_viewing.copy()
    key_cols = ["Branch Path", "Variable", "Scenario", "Region"]
    export_df["Method"] = [
        method_by_key.get(
            tuple(str(row.get(col) or "").strip() for col in key_cols),
            "Interp",
        )
        for _, row in export_df.iterrows()
    ]
    verification_data, verification_path, _verification_sheet = _load_results_verification_data()
    verification_preamble = pd.DataFrame()
    if verification_path.exists():
        try:
            verification_preamble, _, _ = _read_workbook_sheet_with_header_detection(
                verification_path,
                _verification_sheet,
            )
        except Exception as exc:
            print(
                "[WARN] Failed reading verification export preamble for Area/Ver: "
                f"{verification_path} (sheet={_verification_sheet}) -> {exc}"
            )
    (
        export_df,
        dropped_unmatched_zero_supply_rows,
        unmatched_nonzero_supply_rows,
    ) = _filter_unmatched_zero_supply_rows_against_reference(
        export_df,
        source_data=verification_data,
    )
    (
        export_df,
        remapped_resource_branch_rows,
        unresolved_resource_branch_rows,
    ) = _remap_resource_branch_paths_from_reference(
        export_df,
        source_data=verification_data,
    )
    level_source_df = verification_data if not verification_data.empty else leap_data
    export_df = _merge_levels_from_reference_data(export_df, level_source_df)
    metadata_mismatch_rows = _collect_metadata_mismatches_against_reference(
        export_df,
        source_data=verification_data,
    )
    gigajoule_template_rows = _collect_gigajoule_template_rows(
        export_df,
        source_data=verification_data,
    )
    export_df, metadata_backfill_rows = _apply_reference_non_value_metadata(
        export_df,
        source_data=verification_data,
    )
    export_df, unmatched_id_rows = _resolve_ids_and_filter_unmatched_export_rows(
        export_df,
        source_data=verification_data,
        source_path=verification_path,
    )
    nonzero_missing_id_rows: pd.DataFrame = pd.DataFrame()
    mapping_table = _load_field_mapping_table_for_validation()
    mapping_config_mismatch_rows = _collect_mapping_config_mismatches_against_reference(
        mapping_table,
        source_data=verification_data,
    )
    if not mapping_config_mismatch_rows.empty:
        mapping_config_unmatched_rows = mapping_config_mismatch_rows[
            mapping_config_mismatch_rows["issue"].eq("no_reference_match")
        ].copy()
        mapping_config_mismatch_rows = mapping_config_mismatch_rows[
            ~mapping_config_mismatch_rows["issue"].eq("no_reference_match")
        ].copy()
    else:
        mapping_config_unmatched_rows = pd.DataFrame()

    year_columns = [col for col in export_df.columns if _is_year_header(col)]
    level_columns = [f"Level {idx}" for idx in range(1, 9)]
    level_spacer_column = ""
    non_year_order = [
        "BranchID",
        "VariableID",
        "ScenarioID",
        "RegionID",
        "Branch Path",
        "Variable",
        "Scenario",
        "Region",
        "Scale",
        "Units",
        "Per...",
        "Method",
    ]
    # Keep LEAP-import numeric year columns contiguous immediately after Method.
    # Keep one blank spacer column between the final year and Level 1.
    # Put Level hierarchy columns at the far right to avoid LEAP interpreting them
    # as year/value cells during import.
    export_columns = non_year_order + year_columns + [level_spacer_column] + level_columns
    export_df = export_df.reindex(columns=export_columns).copy()

    output_root = _resolve(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    workbook_path = output_root / str(file_name).strip()
    _archive_existing_results_file_if_needed(
        workbook_path,
        archive_dir=archive_dir,
        min_hours=archive_min_hours,
    )
    area_name, version_value = _extract_area_and_version(
        verification_preamble,
        viewing_preamble,
        leap_preamble,
    )
    width = len(export_columns)
    row0 = [""] * width
    row1 = [""] * width
    if width >= 8:
        row0[4] = "Area:"
        row0[5] = area_name
        row0[6] = "Ver:"
        row0[7] = version_value
    preamble = pd.DataFrame([row0, row1])

    with pd.ExcelWriter(workbook_path, engine="openpyxl", mode="w") as writer:
        preamble.to_excel(writer, sheet_name="Export", index=False, header=False)
        pd.DataFrame([export_columns]).to_excel(
            writer,
            sheet_name="Export",
            index=False,
            header=False,
            startrow=len(preamble),
        )
        export_df.to_excel(
            writer,
            sheet_name="Export",
            index=False,
            header=False,
            startrow=len(preamble) + 1,
        )
        manifest_rows = []
        for workbook_type, paths in (
            ("supply", export_paths),
            ("transformation", transformation_export_paths),
            ("transfer", transfer_export_paths),
            ("other_loss_own_use_proxy", other_loss_own_use_proxy_paths or []),
        ):
            for path in [Path(item) for item in paths if item]:
                manifest_rows.append(
                    {
                        "workbook_type": workbook_type,
                        "path": str(path),
                        "exists": bool(path.exists()),
                    }
                )
        if combined_export_path is not None:
            combined_manifest_path = Path(combined_export_path)
            manifest_rows.append(
                {
                    "workbook_type": "combined_supply_transformation_transfer",
                    "path": str(combined_manifest_path),
                    "exists": bool(combined_manifest_path.exists()),
                }
            )
        if probe_catalog_path is not None:
            probe_manifest_path = Path(probe_catalog_path)
            manifest_rows.append(
                {
                    "workbook_type": "fuel_branch_probe",
                    "path": str(probe_manifest_path),
                    "exists": bool(probe_manifest_path.exists()),
                }
            )
        if manifest_rows:
            pd.DataFrame(manifest_rows).to_excel(
                writer,
                sheet_name="RUN_MANIFEST",
                index=False,
            )
    if bool(archive_every_run):
        _archive_results_file_snapshot(
            workbook_path,
            archive_dir=archive_dir,
        )

    if (
        isinstance(dropped_unmatched_zero_supply_rows, pd.DataFrame)
        and not dropped_unmatched_zero_supply_rows.empty
    ):
        dropped_supply_report_path = (
            _resolve(RESULTS_CHECKS_DIR) / RESULTS_DROPPED_UNMATCHED_ZERO_SUPPLY_ROWS_FILENAME
        )
        dropped_supply_report_path.parent.mkdir(parents=True, exist_ok=True)
        _sort_output_frame_for_csv(dropped_unmatched_zero_supply_rows).to_csv(
            dropped_supply_report_path,
            index=False,
        )
        print(
            "[INFO] Dropped unmatched all-zero Resources rows not present in "
            f"verification export: {len(dropped_unmatched_zero_supply_rows)} "
            f"(details saved to {dropped_supply_report_path})."
        )

    if (
        isinstance(unmatched_nonzero_supply_rows, pd.DataFrame)
        and not unmatched_nonzero_supply_rows.empty
    ):
        print(
            "\n[WARN] Found nonzero Resources rows not present in verification export; "
            "kept in output for review."
        )
        print(f"[WARN] Nonzero unmatched Resources rows: {len(unmatched_nonzero_supply_rows)}")
        for _, row in unmatched_nonzero_supply_rows.head(30).iterrows():
            print(
                "  - Branch Path='{bp}' | Variable='{var}' | Scenario='{sc}' | Region='{rg}' | "
                "year_abs_sum={ys}".format(
                    bp=str(row.get("Branch Path") or "").strip(),
                    var=str(row.get("Variable") or "").strip(),
                    sc=str(row.get("Scenario") or "").strip(),
                    rg=str(row.get("Region") or "").strip(),
                    ys=float(pd.to_numeric(row.get("year_abs_sum"), errors="coerce") or 0.0),
                )
            )
        if len(unmatched_nonzero_supply_rows) > 30:
            print(
                f"  ... plus {len(unmatched_nonzero_supply_rows) - 30} more nonzero unmatched Resources rows"
            )

    if (
        isinstance(remapped_resource_branch_rows, pd.DataFrame)
        and not remapped_resource_branch_rows.empty
    ):
        print(
            "[INFO] Remapped Resources branch paths to canonical verification-export paths for "
            f"{len(remapped_resource_branch_rows)} row(s)."
        )
        for _, row in remapped_resource_branch_rows.head(20).iterrows():
            print(
                "  - Branch Path='{old}' -> '{new}' | Variable='{var}' | Scenario='{sc}' | "
                "Region='{rg}' | match_type='{mt}'".format(
                    old=str(row.get("Branch Path") or "").strip(),
                    new=str(row.get("reference_branch_path") or "").strip(),
                    var=str(row.get("Variable") or "").strip(),
                    sc=str(row.get("Scenario") or "").strip(),
                    rg=str(row.get("Region") or "").strip(),
                    mt=str(row.get("match_type") or "").strip(),
                )
            )
        if len(remapped_resource_branch_rows) > 20:
            print(
                f"  ... plus {len(remapped_resource_branch_rows) - 20} more remapped Resources rows"
            )

    if (
        isinstance(unresolved_resource_branch_rows, pd.DataFrame)
        and not unresolved_resource_branch_rows.empty
    ):
        print(
            "\n[WARN] Unresolved Resources branch-path mappings against verification export; "
            "these rows may still receive -1 IDs and need explicit LEAP mapping confirmation."
        )
        print(
            f"[WARN] Unresolved resource branch mappings: {len(unresolved_resource_branch_rows)}"
        )
        for _, row in unresolved_resource_branch_rows.head(30).iterrows():
            print(
                "  - Branch Path='{bp}' | Variable='{var}' | Scenario='{sc}' | Region='{rg}' | "
                "issue='{issue}' | candidates='{cand}'".format(
                    bp=str(row.get("Branch Path") or "").strip(),
                    var=str(row.get("Variable") or "").strip(),
                    sc=str(row.get("Scenario") or "").strip(),
                    rg=str(row.get("Region") or "").strip(),
                    issue=str(row.get("issue") or "").strip(),
                    cand=str(row.get("candidate_branch_paths") or "").strip(),
                )
            )
        if len(unresolved_resource_branch_rows) > 30:
            print(
                f"  ... plus {len(unresolved_resource_branch_rows) - 30} more unresolved mapping rows"
            )

    unmatched_report_path = _resolve(RESULTS_CHECKS_DIR) / RESULTS_UNMATCHED_ID_REPORT_FILENAME
    unmatched_report_path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(unmatched_id_rows, pd.DataFrame) and not unmatched_id_rows.empty:
        _sort_output_frame_for_csv(unmatched_id_rows).to_csv(unmatched_report_path, index=False)
        print("\n[WARN] Unmatched verification-export IDs detected; these rows need LEAP alignment fixes.")
        print(
            f"[WARN] Unmatched rows: {len(unmatched_id_rows)} "
            f"(details saved to {unmatched_report_path})"
        )
        for _, row in unmatched_id_rows.head(30).iterrows():
            print(
                "  - Branch Path='{bp}' | Variable='{var}' | Scenario='{sc}' | Region='{rg}' | reason='{rsn}'".format(
                    bp=str(row.get("Branch Path") or "").strip(),
                    var=str(row.get("Variable") or "").strip(),
                    sc=str(row.get("Scenario") or "").strip(),
                    rg=str(row.get("Region") or "").strip(),
                    rsn=str(row.get("reason") or "").strip(),
                )
            )
        if len(unmatched_id_rows) > 30:
            print(f"  ... plus {len(unmatched_id_rows) - 30} more unmatched rows")

        # Identify unmatched rows that carry non-zero values — these will be silently
        # skipped by LEAP on import (LEAP matches by BranchID; -1 rows are ignored),
        # causing feedstock/process shares or other variables to sum to less than 100%.
        # Collected here and surfaced at the end of the workflow so all outputs are
        # already saved before the error is presented to the user.
        year_cols_in_export = [c for c in export_df.columns if _is_year_header(c)]
        if year_cols_in_export:
            unmatched_key_cols = ["Branch Path", "Variable", "Scenario", "Region"]
            unmatched_keys = set(
                tuple(str(r.get(c) or "").strip() for c in unmatched_key_cols)
                for _, r in unmatched_id_rows.iterrows()
            )
            nonzero_missing_id_rows = export_df[
                export_df.apply(
                    lambda r: (
                        tuple(str(r.get(c) or "").strip() for c in unmatched_key_cols)
                        in unmatched_keys
                    ),
                    axis=1,
                )
                & export_df[year_cols_in_export].apply(
                    lambda r: any(
                        abs(float(v)) > 1e-9
                        for v in r
                        if v is not None and not (isinstance(v, float) and pd.isna(v))
                    ),
                    axis=1,
                )
            ][unmatched_key_cols + year_cols_in_export[:1]].copy()
        else:
            nonzero_missing_id_rows = pd.DataFrame()
    else:
        if unmatched_report_path.exists():
            try:
                unmatched_report_path.unlink()
                print(
                    "[INFO] Cleared stale unmatched-ID report from previous run: "
                    f"{unmatched_report_path}"
                )
            except Exception as exc:
                print(
                    "[WARN] Could not remove stale unmatched-ID report "
                    f"{unmatched_report_path}: {exc}"
                )

    if isinstance(metadata_backfill_rows, pd.DataFrame) and not metadata_backfill_rows.empty:
        print(
            "[INFO] Backfilled non-year metadata from verification export for "
            f"{len(metadata_backfill_rows)} field(s)."
        )
        by_column = (
            metadata_backfill_rows.groupby("column", dropna=False).size().reset_index(name="count")
        )
        for _, row in by_column.iterrows():
            print(f"  - {row['column']}: {int(row['count'])} fill(s)")

    def _format_metadata_mismatch_row(row: pd.Series) -> str:
        return (
            "Branch Path='{bp}' | Variable='{var}' | Scenario='{sc}' | Region='{rg}' | "
            "column='{col}' | generated='{gen}' | reference='{ref}'".format(
                bp=str(row.get("Branch Path") or "").strip(),
                var=str(row.get("Variable") or "").strip(),
                sc=str(row.get("Scenario") or "").strip(),
                rg=str(row.get("Region") or "").strip(),
                col=str(row.get("column") or "").strip(),
                gen=str(row.get("generated_value") or "").strip(),
                ref=str(row.get("reference_value") or "").strip(),
            )
        )

    _write_diagnostic_report(
        metadata_mismatch_rows,
        _resolve(RESULTS_CHECKS_DIR) / RESULTS_METADATA_MISMATCH_REPORT_FILENAME,
        header=(
            "\n[WARN] Verification-export metadata mismatches detected "
            "(Scale/Units/Per...)."
        ),
        count_label="Metadata mismatches",
        row_formatter=_format_metadata_mismatch_row,
        more_label="more metadata mismatches",
    )

    unit_review_report_path = (
        _resolve(RESULTS_CHECKS_DIR)
        / "supply_reconciliation_unit_review.csv"
    )
    unit_mismatch_rows = (
        metadata_mismatch_rows[metadata_mismatch_rows["column"].eq("Units")].copy()
        if isinstance(metadata_mismatch_rows, pd.DataFrame)
        and not metadata_mismatch_rows.empty
        else pd.DataFrame()
    )
    unit_review_frames: list[pd.DataFrame] = []
    if not unit_mismatch_rows.empty:
        mismatch_review = unit_mismatch_rows.rename(columns={
            "generated_value": "generated_units",
            "reference_value": "template_units",
        })[
            ["Branch Path", "Variable", "Scenario", "Region", "generated_units", "template_units"]
        ].copy()
        mismatch_review["review_reason"] = "unit_mismatch"
        unit_review_frames.append(mismatch_review)
    if isinstance(gigajoule_template_rows, pd.DataFrame) and not gigajoule_template_rows.empty:
        gigajoule_review = gigajoule_template_rows.copy()
        gigajoule_review["review_reason"] = "template_uses_gigajoule"
        unit_review_frames.append(gigajoule_review)

    if unit_review_frames:
        unit_review_rows = pd.concat(unit_review_frames, ignore_index=True)
        group_cols = [
            "Branch Path", "Variable", "Scenario", "Region",
            "generated_units", "template_units",
        ]
        unit_review_rows = (
            unit_review_rows.groupby(group_cols, dropna=False, as_index=False)["review_reason"]
            .agg(lambda values: "|".join(sorted(set(values))))
        )
        unit_review_report_path.parent.mkdir(parents=True, exist_ok=True)
        _sort_output_frame_for_csv(unit_review_rows).to_csv(
            unit_review_report_path,
            index=False,
        )
        print(
            "[WARN] Unit review contains generated/template mismatches and all "
            f"template Gigajoule rows ({len(unit_review_rows)} row(s)). Template "
            "values were applied, but the correct long-term unit may require a "
            f"LEAP model change. Review: {unit_review_report_path}"
        )
    elif unit_review_report_path.exists():
        unit_review_report_path.unlink()

    # Remove obsolete split reports from earlier versions of this diagnostic.
    for obsolete_name in (
        "supply_reconciliation_unit_mismatches.csv",
        "supply_reconciliation_template_gigajoule_rows.csv",
    ):
        obsolete_path = _resolve(RESULTS_CHECKS_DIR) / obsolete_name
        if obsolete_path.exists():
            obsolete_path.unlink()

    def _format_mapping_mismatch_row(row: pd.Series) -> str:
        return (
            "scope='{scope}' | branch='{branch}' | variable='{var}' | "
            "field='{field}' | config='{cfg}' | reference='{ref}' | issue='{issue}'".format(
                scope=str(row.get("match_scope") or "").strip(),
                branch=str(row.get("branch_path") or "").strip(),
                var=str(row.get("variable") or "").strip(),
                field=str(row.get("field") or "").strip(),
                cfg=str(row.get("config_value") or "").strip(),
                ref=str(row.get("reference_values") or "").strip(),
                issue=str(row.get("issue") or "").strip(),
            )
        )

    _write_diagnostic_report(
        mapping_config_mismatch_rows,
        _resolve(RESULTS_CHECKS_DIR) / RESULTS_CONFIG_MAPPING_MISMATCH_REPORT_FILENAME,
        header=(
            "\n[WARN] Analysis-input config mapping mismatches detected against "
            "full model export metadata."
        ),
        count_label="Mapping mismatches",
        row_formatter=_format_mapping_mismatch_row,
        more_label="more mapping mismatches",
    )

    config_unmatched_path = (
        _resolve(RESULTS_CHECKS_DIR)
        / "supply_reconciliation_config_rows_without_template_match.csv"
    )
    if isinstance(mapping_config_unmatched_rows, pd.DataFrame) and not mapping_config_unmatched_rows.empty:
        config_unmatched_path.parent.mkdir(parents=True, exist_ok=True)
        _sort_output_frame_for_csv(mapping_config_unmatched_rows).to_csv(
            config_unmatched_path,
            index=False,
        )
        print(
            "[INFO] Configuration rows without a literal full-model template match: "
            f"{len(mapping_config_unmatched_rows)}. Review: {config_unmatched_path}"
        )
    elif config_unmatched_path.exists():
        config_unmatched_path.unlink()

    print(
        "[INFO] Saved single-file results workbook in full-model Export structure to "
        f"{workbook_path}"
    )
    return workbook_path, nonzero_missing_id_rows



def run_results_linked_transformation_supply_workflow(
    economies: Iterable[str] | None = None,
    scenario_names: list[str] | None = None,
    export_dataset_key: str = EXPORT_DATASET_KEY,
    include_leap_import: bool | None = None,
    import_scenarios: Iterable[str] | str | None = LEAP_IMPORT_SCENARIOS,
    use_direct_leap_results_for_demand: bool | None = None,
    scrape_leap_results: bool | None = None,
) -> dict[str, object]:
    """Build reconciled transformation + supply exports driven by LEAP balance demand results."""
    timer = workflow_common.WorkflowTimer("supply_reconciliation", enabled=ENABLE_WORKFLOW_TIMING)
    timing_path = _resolve(RESULTS_RUNTIME_DIR) / WORKFLOW_TIMING_FILENAME
    _sra._CAPACITY_UNMET_RUNTIME_CAPACITY_ADDITIONS = {}
    _sra._CAPACITY_UNMET_RUNTIME_PRIMARY_ADDITIONS = {}
    _sra._CAPACITY_UNMET_RUNTIME_EXPORT_ADJUSTMENTS = {}
    _sra._CAPACITY_UNMET_RUNTIME_PASS_SUMMARY = None
    requested_include_leap_import = include_leap_import
    analysis_write_mode = get_analysis_input_write_mode()
    include_leap_import = analysis_write_mode == "api"
    if requested_include_leap_import is not None and bool(requested_include_leap_import) != include_leap_import:
        print(
            "[INFO] include_leap_import argument is ignored in this workflow. "
            "LEAP import execution is derived from ANALYSIS_INPUT_WRITE_MODE "
            f"('{analysis_write_mode}')."
        )
    if use_direct_leap_results_for_demand is not None and not bool(use_direct_leap_results_for_demand):
        print(
            "[INFO] use_direct_leap_results_for_demand=False is deprecated and ignored. "
            "Demand inputs are always loaded from LEAP balance exports."
        )
    # Balance-export demand sourcing is now always enabled in this workflow.
    use_direct_leap_results_for_demand = True
    if scrape_leap_results is None:
        scrape_leap_results = bool(SCRAPE_LEAP_RESULTS)
    if _use_capacity_unmet_iterative_any_mode() and get_analysis_input_write_mode() != "workbook":
        raise ValueError(
            "The balanced iterative supply-link method requires "
            "ANALYSIS_INPUT_WRITE_MODE='workbook' so Analysis-view writes stay manual-import only."
        )
    if _use_capacity_unmet_iterative_any_mode() and scrape_leap_results:
        print(
            "[INFO] capacity_unmet iterative mode will refresh LEAP results templates "
            "via LEAP Results API reads before downstream reconciliation steps."
        )
    should_pin_leap_session = bool(
        scrape_leap_results
        or REFRESH_TRANSFORMATION_MEASURES_FROM_LEAP_RESULTS
        or include_leap_import
    )
    if should_pin_leap_session and leap_api.is_available():
        try:
            pinned_app = leap_api.connect(force_rebuild=False)
            active_area = str(getattr(pinned_app, "ActiveArea", "") or "").strip()
            if active_area:
                print(f"[INFO] Pinned LEAP session for this run (Active area: {active_area}).")
            else:
                print("[INFO] Pinned LEAP session for this run.")
        except Exception as exc:
            print(f"[WARN] Failed to pin LEAP session at run start: {exc}")
    archive_config_dir_once_per_day()
    os.environ["LEAP_IMPORT_LOG_LEVEL"] = str(LEAP_IMPORT_LOG_LEVEL).strip()
    os.environ["LEAP_IMPORT_WARNING_PRINT_LIMIT"] = str(LEAP_IMPORT_WARNING_PRINT_LIMIT)
    scenario_list = workflow_common.normalize_workflow_scenarios(
        scenario_names,
        SCENARIOS,
    )
    export_scenario_list = list(scenario_list)
    if RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT:
        expanded = _ensure_current_accounts_scenario(export_scenario_list)
        if len(expanded) != len(export_scenario_list):
            print(
                "[INFO] Reset mode: appending 'Current Accounts' to export scenarios "
                "so zero-reset values are also written for Current Accounts."
            )
        export_scenario_list = expanded
    balance_scenario_list = _filter_balance_scenarios(scenario_list)
    economy_list = workflow_common.normalize_economies(economies or ECONOMIES)
    timer.set_metadata(economies=economy_list, scenarios=export_scenario_list)
    _print_reset_mode_reminder(
        run_economies=economy_list,
        run_scenarios=export_scenario_list,
    )
    timer.lap("setup")
    _bd_cache_hit = False
    if TRANSFORMATION_SUPPLY_CACHE_ENABLED:
        import hashlib as _hashlib, json as _json, pickle as _pickle
        _bd_cache_dir = _resolve(RESULTS_RUNTIME_DIR) / "balance_demand_cache"
        _bd_cache_dir.mkdir(parents=True, exist_ok=True)
        _leap_results_dir = _resolve(LEAP_RESULTS_TABLES_DIR)
        _leap_results_mtime = max(
            (f.stat().st_mtime for f in _leap_results_dir.glob("**/*") if f.is_file()),
            default=0.0,
        ) if _leap_results_dir.exists() else 0.0
        _config_dir2 = REPO_ROOT / "config"
        _config_mtimes2 = {
            f.name: f.stat().st_mtime
            for f in sorted(_config_dir2.glob("*"))
            if f.is_file()
        } if _config_dir2.exists() else {}
        _bd_key_payload = _json.dumps({
            "economies": sorted(economy_list),
            "scenarios": sorted(balance_scenario_list),
            "pass_mode": str(CAPACITY_UNMET_PASS_MODE),
            "leap_results_mtime": _leap_results_mtime,
            "config_mtimes": _config_mtimes2,
        }, sort_keys=True)
        _bd_cache_key = _hashlib.md5(_bd_key_payload.encode()).hexdigest()[:16]
        _bd_cache_file = _bd_cache_dir / f"{_bd_cache_key}.pkl"
        if _bd_cache_file.exists():
            try:
                with open(_bd_cache_file, "rb") as _f:
                    _bd = _pickle.load(_f)
                comparison_long_df = _bd["comparison_long_df"]
                mapping_status_df = _bd["mapping_status_df"]
                balance_demand_issues = _bd["balance_demand_issues"]
                balance_matching_diagnostics = _bd["balance_matching_diagnostics"]
                sector_demand_table = _bd["sector_demand_table"]
                demand_table = _bd["demand_table"]
                _bd_cache_hit = True
                print(f"[INFO] Loaded balance demand inputs from cache (key={_bd_cache_key}).")
            except Exception as _bd_exc:
                print(f"[WARN] Could not load balance demand cache: {_bd_exc}. Recomputing.")
    if not _bd_cache_hit:
        comparison_long_df, mapping_status_df, balance_demand_issues, balance_matching_diagnostics = load_balance_demand_inputs(
            economies=economy_list,
            scenarios=balance_scenario_list,
            workbook_dir=LEAP_RESULTS_TABLES_DIR,
            allow_projection_only_without_balance_exports=_is_capacity_unmet_baseline_seed_pass(),
        )
        balance_demand_issues = _annotate_balance_demand_issue_scope(balance_demand_issues)
        sector_demand_table = load_results_sector_demand_table(
            source_priority=DEMAND_SOURCE_PRIORITY,
            comparison_long_df=comparison_long_df,
            mapping_status_df=mapping_status_df,
        )
        demand_table = load_results_demand_table(
            source_priority=DEMAND_SOURCE_PRIORITY,
            comparison_long_df=comparison_long_df,
            mapping_status_df=mapping_status_df,
            economies=economy_list,
        )
        if TRANSFORMATION_SUPPLY_CACHE_ENABLED:
            try:
                with open(_bd_cache_file, "wb") as _f:
                    _pickle.dump({
                        "comparison_long_df": comparison_long_df,
                        "mapping_status_df": mapping_status_df,
                        "balance_demand_issues": balance_demand_issues,
                        "balance_matching_diagnostics": balance_matching_diagnostics,
                        "sector_demand_table": sector_demand_table,
                        "demand_table": demand_table,
                    }, _f, protocol=_pickle.HIGHEST_PROTOCOL)
                print(f"[INFO] Saved balance demand cache (key={_bd_cache_key}).")
            except Exception as _bd_exc:
                print(f"[WARN] Could not write balance demand cache: {_bd_exc}.")
    timer.lap("load balance demand inputs")
    if economy_list:
        sector_demand_table = sector_demand_table[
            sector_demand_table["economy"].isin(economy_list)
        ].copy()
        demand_table = demand_table[demand_table["economy"].isin(economy_list)].copy()
    from codebase.aggregated_demand_workflow import (
        ESTO_BASE_DATA_PATH,
        PROJECTION_DATA_PATH,
        build_aggregated_demand_as_dummy,
    )

    # The compressed results-update preflight overrides FINAL_YEAR to BASE_YEAR+1,
    # a signed-sum synthetic projection year. Flag it as a compressed projection
    # so its total is never mistaken for a real annual balance in the outputs.
    conservation_compressed_years = (
        {int(BASE_YEAR) + 1} if int(FINAL_YEAR) == int(BASE_YEAR) + 1 else None
    )

    # Names shared by the diagnostic and the breakdown/lineage drill-down. The
    # "actual" side of this conservation check is the demand THIS repository
    # builds and hands to LEAP (the aggregated-demand dummy plus any detailed
    # sector rows the workflow itself generates) -- identical in baseline_seed
    # and results_update, and never sourced from the LEAP balance readback.
    raw_demand_reference = pd.DataFrame()
    source_scope_audit = pd.DataFrame()
    produced_demand = pd.DataFrame()
    produced_demand_provenance = pd.DataFrame()
    conservation_exclusions = None
    conservation_scenarios: list[str] = []

    try:
        conservation_exclusions = resolve_effective_aggregated_demand_exclusions(
            sector_demand_table
        )
        conservation_scenarios = sorted(
            demand_table.get("scenario", pd.Series(dtype=str))
            .dropna().astype(str).str.strip().loc[lambda values: values.ne("")].unique().tolist()
        )
        raw_reference_with_scope = [
            build_raw_demand_conservation_reference(
                economy=economy,
                scenarios=conservation_scenarios,
                base_year=BASE_YEAR,
                final_year=FINAL_YEAR,
                data_path=PROJECTION_DATA_PATH,
                esto_data_path=ESTO_BASE_DATA_PATH,
                exclude_own_use_td_losses=bool(AGGREGATED_DEMAND_EXCLUDE_OWN_USE_TD_LOSSES),
                excluded_sectors=conservation_exclusions,
                return_scope_audit=True,
            )
            for economy in economy_list
        ]
        raw_demand_reference = (
            pd.concat([item[0] for item in raw_reference_with_scope], ignore_index=True)
            if raw_reference_with_scope
            else pd.DataFrame()
        )
        source_scope_audit = (
            pd.concat([item[1] for item in raw_reference_with_scope], ignore_index=True)
            if raw_reference_with_scope
            else pd.DataFrame()
        )
        # Produced-demand "actual" side: same builder the LEAP import workbook is
        # generated from, so the check compares our produced demand against the
        # ESTO/9th target. The identical ``excluded_sectors`` are applied to both
        # sides so the "already modelled" detailed sectors drop symmetrically.
        produced_demand_with_provenance = [
            build_aggregated_demand_as_dummy(
                economy=economy,
                scenarios=conservation_scenarios,
                base_year=BASE_YEAR,
                final_year=FINAL_YEAR,
                data_path=PROJECTION_DATA_PATH,
                esto_data_path=ESTO_BASE_DATA_PATH,
                exclude_own_use_td_losses=bool(AGGREGATED_DEMAND_EXCLUDE_OWN_USE_TD_LOSSES),
                excluded_sectors=conservation_exclusions,
                use_sector_branches=False,
                return_provenance=True,
            )
            for economy in economy_list
        ]
        produced_demand = (
            pd.concat([item[0] for item in produced_demand_with_provenance], ignore_index=True)
            if produced_demand_with_provenance
            else pd.DataFrame()
        )
        produced_demand_provenance = (
            pd.concat([item[1] for item in produced_demand_with_provenance], ignore_index=True)
            if produced_demand_with_provenance
            else pd.DataFrame()
        )
        produced_demand_totals = prepare_reconciliation_demand_totals(
            produced_demand,
            collapse_products=True,
        )
        balance_demand_conservation = build_balance_demand_conservation_diagnostics(
            raw_demand_reference,
            produced_demand_totals,
            compressed_projection_years=conservation_compressed_years,
        )
    except Exception as exc:
        print(f"[WARN] Balance-demand conservation diagnostic could not run: {exc}")
        balance_demand_conservation = pd.DataFrame(
            [{"status": "diagnostic_error", "is_mismatch": True, "diagnostic_error": str(exc)}]
        )
    balance_demand_conservation_path = write_balance_demand_conservation_diagnostics(
        balance_demand_conservation,
        _resolve(RESULTS_CHECKS_DIR) / "supply_reconciliation_balance_demand_conservation.csv",
    )
    mismatch_count = int(balance_demand_conservation["is_mismatch"].sum())
    print(
        "[INFO] Wrote diagnostic-only balance-demand conservation check: "
        f"{balance_demand_conservation_path} ({mismatch_count} mismatch row(s))."
    )
    print(
        "[INFO] Conservation 'actual' side is this repo's produced demand "
        "(aggregated-demand dummy + detailed sector rows); it does NOT involve "
        "the LEAP balance readback. Reference is the independent ESTO/9th target."
    )
    balance_demand_breakdown_path = None
    balance_demand_lineage_path = None
    try:
        # Actual side per product = the same produced demand, decomposed by
        # esto_product. Both the "expected" and "actual/resolved" sides of the
        # drill-down are our produced demand; there is no LEAP readback stage.
        resolved_demand_by_product = prepare_reconciliation_demand_totals(
            produced_demand,
            collapse_products=False,
        )
        balance_demand_breakdown = build_balance_demand_conservation_breakdown(
            reference_rows=raw_demand_reference,
            expected_mapped_rows=produced_demand,
            resolved_rows=resolved_demand_by_product,
            expected_provenance=produced_demand_provenance,
            resolved_provenance=produced_demand_provenance,
            source_scope_audit=source_scope_audit,
            resolved_scope_audit=None,
            compressed_projection_years=conservation_compressed_years,
        )
        balance_demand_lineage = build_balance_demand_conservation_lineage(
            reference_rows=raw_demand_reference,
            expected_mapped_rows=produced_demand,
            resolved_rows=resolved_demand_by_product,
            expected_provenance=produced_demand_provenance,
            resolved_provenance=produced_demand_provenance,
            source_scope_audit=source_scope_audit,
            resolved_scope_audit=None,
            compressed_projection_years=conservation_compressed_years,
        )
        checks_dir = _resolve(RESULTS_CHECKS_DIR)
        balance_demand_breakdown_path = write_balance_demand_conservation_table(
            balance_demand_breakdown,
            checks_dir / "supply_reconciliation_balance_demand_conservation_breakdown.csv",
        )
        balance_demand_lineage_path = write_balance_demand_conservation_table(
            balance_demand_lineage,
            checks_dir / "supply_reconciliation_balance_demand_conservation_lineage.csv",
        )
        print(
            "[INFO] Wrote balance-demand breakdown and lineage prototypes: "
            f"{balance_demand_breakdown_path}, {balance_demand_lineage_path}."
        )
    except Exception as exc:
        print(f"[WARN] Balance-demand breakdown/lineage prototype could not run: {exc}")
    _ts_cache_hit = False
    if TRANSFORMATION_SUPPLY_CACHE_ENABLED:
        import hashlib as _hashlib, json as _json, pickle as _pickle
        _ts_cache_dir = _resolve(RESULTS_RUNTIME_DIR) / "transform_supply_cache"
        _ts_cache_dir.mkdir(parents=True, exist_ok=True)
        _config_dir = REPO_ROOT / "config"
        _config_mtimes = {
            f.name: f.stat().st_mtime
            for f in sorted(_config_dir.glob("*"))
            if f.is_file()
        } if _config_dir.exists() else {}
        _ts_key_payload = _json.dumps({
            "economies": sorted(economy_list),
            "dataset_key": str(export_dataset_key),
            "config_mtimes": _config_mtimes,
        }, sort_keys=True)
        _ts_cache_key = _hashlib.md5(_ts_key_payload.encode()).hexdigest()[:16]
        _ts_cache_file = _ts_cache_dir / f"{_ts_cache_key}.pkl"
        if _ts_cache_file.exists():
            try:
                with open(_ts_cache_file, "rb") as _f:
                    _ts = _pickle.load(_f)
                transformation_table = _ts["transformation_table"]
                transformation_sector_table = _ts["transformation_sector_table"]
                transformation_target_rows = _ts["transformation_target_rows"]
                transformation_process_records = _ts["transformation_process_records"]
                supply_projection_table = _ts["supply_projection_table"]
                supply_primary_table = _ts["supply_primary_table"]
                assets = _ts["assets"]
                supply_constraints = _ts["supply_constraints"]
                transformation_constraints = _ts["transformation_constraints"]
                _ts_cache_hit = True
                print(f"[INFO] Loaded transformation/supply inputs from cache (key={_ts_cache_key}).")
            except Exception as _cache_exc:
                print(f"[WARN] Could not load transformation/supply cache: {_cache_exc}. Recomputing.")
    if not _ts_cache_hit:
        transformation_table = build_transformation_balance_table(economies=economy_list)
        transformation_sector_table = build_transformation_sector_table(economies=economy_list)
        transformation_target_rows, transformation_process_records = build_transformation_trade_target_rows(
            economies=economy_list,
        )
        supply_projection_table, assets = prepare_projected_supply_table(
            economies=economy_list,
            dataset_key=export_dataset_key,
        )
        supply_primary_table = prepare_supply_primary_table(
            assets,
            economies=economy_list,
            dataset_key=export_dataset_key,
        )
        supply_constraints, transformation_constraints = load_leap_constraint_tables(
            template_paths=CONSTRAINT_TEMPLATE_PATHS,
            sheet_names=CONSTRAINT_TEMPLATE_SHEETS,
            economies=economy_list,
        )
        if TRANSFORMATION_SUPPLY_CACHE_ENABLED:
            try:
                with open(_ts_cache_file, "wb") as _f:
                    _pickle.dump({
                        "transformation_table": transformation_table,
                        "transformation_sector_table": transformation_sector_table,
                        "transformation_target_rows": transformation_target_rows,
                        "transformation_process_records": transformation_process_records,
                        "supply_projection_table": supply_projection_table,
                        "supply_primary_table": supply_primary_table,
                        "assets": assets,
                        "supply_constraints": supply_constraints,
                        "transformation_constraints": transformation_constraints,
                    }, _f, protocol=_pickle.HIGHEST_PROTOCOL)
                print(f"[INFO] Saved transformation/supply cache (key={_ts_cache_key}).")
            except Exception as _cache_exc:
                print(f"[WARN] Could not write transformation/supply cache: {_cache_exc}.")
    timer.lap("build transformation and supply inputs")
    baseline_supply_preservation_path: Path | None = None
    baseline_supply_preservation_breakdown_path: Path | None = None
    baseline_supply_preservation_lineage_path: Path | None = None
    transformation_output_conservation_path: Path | None = None
    transformation_output_conservation_breakdown_path: Path | None = None
    transformation_output_conservation_lineage_path: Path | None = None
    results_update_closure_path: Path | None = None
    reconciliation_table = build_reconciliation_table(
        demand_table,
        transformation_table,
        supply_projection_table,
        supply_primary_table=supply_primary_table,
        supply_constraints=supply_constraints,
        transformation_constraints=transformation_constraints,
    )
    reconciliation_table = apply_trade_split_between_transformation_and_supply(
        reconciliation_table,
        transformation_target_rows=(
            transformation_target_rows if _use_legacy_trade_split_mode() else None
        ),
    )
    if not _is_capacity_unmet_baseline_seed_pass():
        try:
            results_update_closure = build_results_update_closure_diagnostics(
                reconciliation_table
            )
            results_update_closure_path = write_supply_diagnostic(
                results_update_closure,
                _resolve(RESULTS_CHECKS_DIR)
                / "supply_reconciliation_results_update_closure.csv",
            )
            mismatch_count = int(results_update_closure["is_mismatch"].sum())
            print(
                "[INFO] Wrote diagnostic-only results-update reconciliation closure check: "
                f"{results_update_closure_path} ({mismatch_count} mismatch row(s))."
            )
        except Exception as exc:
            print(f"[WARN] Results-update closure diagnostic could not run: {exc}")
    if RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT:
        reset_economies = RESET_SCOPE_ECONOMIES if RESET_SCOPE_ECONOMIES is not None else economy_list
        reset_scenarios = RESET_SCOPE_SCENARIOS if RESET_SCOPE_SCENARIOS is not None else export_scenario_list
        reset_scenarios = _ensure_current_accounts_scenario(reset_scenarios)
        reconciliation_table, updated_process_records = (
            reset_supply_and_transformation_import_export_to_zero(
                reconciliation_table=reconciliation_table,
                transformation_process_records=transformation_process_records,
                economies=reset_economies,
                scenarios=reset_scenarios,
                sector_titles=RESET_SCOPE_SECTOR_TITLES,
                esto_products=RESET_SCOPE_ESTO_PRODUCTS,
                years=RESET_SCOPE_YEARS,
            )
        )
        if updated_process_records is not None:
            transformation_process_records = updated_process_records
    timer.lap("build reconciliation and apply trade rules")

    balance_paths = save_year_balance_tables(
        reconciliation_table,
        years=BALANCE_EXPORT_YEARS,
        economies=economy_list,
        scenarios=balance_scenario_list,
    )
    balance_csv_paths = [path for path in balance_paths if Path(path).suffix.lower() == ".csv"]
    timer.lap("write yearly balance tables")

    if _use_capacity_unmet_iterative_mode():
        _sra._CAPACITY_UNMET_RUNTIME_PASS_SUMMARY = _sra._run_capacity_unmet_iterative_pass(
            reconciliation_table=reconciliation_table,
            process_records=transformation_process_records,
            economies=economy_list,
            scenarios=export_scenario_list,
            resolve_scenario_key=_resolve_reconciliation_scenario_key,
            results_dir=balance_csv_paths,
            state_path=CAPACITY_UNMET_STATE_PATH,
            allow_same_results_reuse=bool(CAPACITY_UNMET_ALLOW_SAME_RESULTS_REUSE),
        )
    elif _use_capacity_unmet_iterative_balanced_mode():
        if _is_capacity_unmet_baseline_seed_pass():
            seeded_state = _read_capacity_unmet_state(
                state_path=CAPACITY_UNMET_STATE_PATH,
                run_mode="baseline_seed",
            )
            seeded_state_path = _write_capacity_unmet_state(
                seeded_state, state_path=CAPACITY_UNMET_STATE_PATH
            )
            _sra._CAPACITY_UNMET_RUNTIME_PASS_SUMMARY = {
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "mode": "capacity_unmet_iterative_balanced",
                "pass_mode": "baseline_seed",
                "state_path": str(_resolve(CAPACITY_UNMET_STATE_PATH)),
                "state_seeded_path": str(seeded_state_path),
                "seed_action": (
                    "Baseline-only first pass: wrote imports=0 with baseline exports+capacity "
                    "with no residual allocation from existing LEAP results tables."
                ),
                "next_manual_step": (
                    "Import generated workbook into LEAP, recalculate, refresh results tables, "
                    "set CAPACITY_UNMET_PASS_MODE='results_update', rerun."
                ),
            }
            print(
                "[CAPACITY_UNMET_ITERATIVE_BALANCED] baseline_seed pass: "
                "skipping residual allocation and using imports=0 with baseline exports/capacity."
            )
        else:
            _sra._CAPACITY_UNMET_RUNTIME_PASS_SUMMARY = _sra._run_capacity_unmet_iterative_balanced_pass(
                reconciliation_table=reconciliation_table,
                process_records=transformation_process_records,
                economies=economy_list,
                scenarios=balance_scenario_list,
                resolve_scenario_key=_resolve_reconciliation_scenario_key,
                results_dir=balance_csv_paths,
                state_path=CAPACITY_UNMET_STATE_PATH,
                allow_same_results_reuse=bool(CAPACITY_UNMET_ALLOW_SAME_RESULTS_REUSE),
            )
    if _use_capacity_unmet_iterative_any_mode():
        timer.lap("capacity unmet handling")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    balance_demand_issue_path: Path | None = None
    reconciliation_path: Path | None = None
    conventional_balance_paths: list[Path] = []
    if RESULTS_WRITE_LEGACY_SIDECAR_FILES:
        reconciliation_path = OUTPUT_DIR / RECONCILIATION_FILENAME
        reconciliation_table.to_csv(reconciliation_path, index=False)
        print(f"Saved reconciliation table to {reconciliation_path}")
        conventional_balance_paths = save_conventional_balance_tables(
            reconciliation_table,
            sector_demand_table,
            transformation_sector_table,
            supply_primary_table,
            assets[4],
            years=BALANCE_EXPORT_YEARS,
            economies=economy_list,
            scenarios=balance_scenario_list,
        )
        timer.lap("write legacy sidecar outputs")

    overrides = build_supply_overrides(reconciliation_table)
    dataset_map, sector_config, code_to_name_mapping, _, _ = assets
    supply_measures = _build_supply_measures_for_trade_mode()
    # Build catalog from static sources (LEAP probe + full-model export) so aux-fuel
    # branches not covered by the current run can be explicitly zeroed in LEAP.
    pre_run_catalog_df = _build_transformation_supply_fuel_catalog_df(
        transformation_export_paths=[],
        supply_export_paths=[],
        include_print_summary=False,
    )
    # Per-economy export generation — sequential or parallel depending on PARALLEL_ECONOMY_WORKERS.
    # Each economy writes independent files so completed economies survive cancellation.
    export_paths: list[tuple[str, Path]] = []
    transformation_export_paths: list[Path] = []
    transfer_export_paths: list[Path] = []
    other_loss_own_use_proxy_paths: list[Path] = []
    electricity_heat_interim_paths: list[Path] = []
    aggregated_demand_workbook_paths: list[Path] = []
    combined_export_path: Path | None = None
    transformation_records_by_scenario: dict[str, list[dict]] = {}
    _economy_export_errors: list[tuple[str, Exception]] = []

    # Compute the effective excluded sectors once: manually configured exclusions merged
    # with ESTO sectors implied by active detailed demand branches.  The same list is
    # used for both the aggregated demand workbook filename (so write and combine steps
    # agree on the path) and the internal dummy demand table in load_results_demand_table.
    from codebase.aggregated_demand_workflow import resolve_active_branch_excluded_sectors as _resolve_excl
    _effective_agg_demand_excluded: list[str] | None = _resolve_excl(
        active_branches=DETAILED_DEMAND_BRANCHES_ACTIVE,
        sector_map=LEAP_DEMAND_GROUP_ESTO_SECTOR_MAP,
        base_excluded=AGGREGATED_DEMAND_EXCLUDED_SECTORS,
    )

    def _run_one_economy(economy: str) -> dict:
        """Generate all export workbooks for one economy and return collected paths."""
        if SKIP_ECONOMIES_WITH_EXISTING_EXPORTS:
            _skip_combined = next(iter(sorted(
                _resolve(EXPORT_OUTPUT_DIR).glob(
                    f"combined_supply_transformation*{economy}*.xlsx"
                )
            )), None)
            if _skip_combined is not None and _skip_combined.exists():
                print(f"[INFO] [{economy}] combined workbook already exists, skipping export generation.")
                _skip_supply = sorted(_resolve(EXPORT_OUTPUT_DIR).glob(f"supply_leap_imports_{economy}*.xlsx"))
                _skip_trans = sorted(_resolve(EXPORT_OUTPUT_DIR).glob(f"transformation_leap_imports_{economy}*.xlsx"))
                _skip_transfer = sorted(_resolve(EXPORT_OUTPUT_DIR).glob(f"transfer_leap_imports_{economy}*.xlsx"))
                _skip_elec_heat = sorted(_resolve(EXPORT_OUTPUT_DIR).glob(f"electricity_heat_interim_{economy}*.xlsx"))
                _skip_proxy_dir = _resolve(INTEGRATED_LEAP_EXPORTS_ROOT.parent / "standalone")
                _skip_proxy = sorted(_skip_proxy_dir.glob(f"other_loss_own_use_proxy_{economy}*.xlsx"))
                _skip_agg_demand = sorted(_resolve(EXPORT_OUTPUT_DIR).glob(f"aggregated_demand_{economy}*.xlsx"))
                print(f"[INFO] [{economy}] skipped (existing exports reused).")
                return {
                    "economy": economy,
                    "skipped": True,
                    "combined": _skip_combined,
                    "supply": list(("", Path(p)) for p in _skip_supply),
                    "transformation": list(_skip_trans),
                    "transfer": list(_skip_transfer),
                    "electricity_heat": list(_skip_elec_heat),
                    "other_loss": list(_skip_proxy),
                    "agg_demand": list(_skip_agg_demand),
                }
        econ_supply_paths = supply_data_pipeline.generate_supply_exports(
            dataset_map,
            sector_config,
            code_to_name_mapping,
            projection_lookup=supply_data_pipeline.SUPPLY_PROJECTION_LOOKUP,
            projection_years=supply_data_pipeline.PROJECTION_YEAR_RANGE,
            dataset_key=export_dataset_key,
            economies=[economy],
            scenario_names=export_scenario_list,
            base_year=BASE_YEAR,
            final_year=FINAL_YEAR,
            export_output_dir=EXPORT_OUTPUT_DIR,
            filename_template=EXPORT_FILENAME_TEMPLATE,
            flow_value_overrides_by_economy=overrides,
            supply_measures=supply_measures,
            keep_all_zero_rows=bool(KEEP_ALL_ZERO_SUPPLY_ROWS),
        )
        econ_process_records = [
            r for r in transformation_process_records
            if str(r.get("economy") or "").strip() == economy
        ]
        econ_transformation_paths = save_transformation_exports_with_split_targets(
            reconciliation_table,
            transformation_target_rows,
            econ_process_records,
            scenarios=export_scenario_list,
            output_dir=TRANSFORMATION_EXPORT_OUTPUT_DIR,
            filename_template=TRANSFORMATION_EXPORT_FILENAME_TEMPLATE,
            full_branch_catalog_df=pre_run_catalog_df if not pre_run_catalog_df.empty else None,
            records_by_scenario_out=transformation_records_by_scenario,
        )
        econ_transfer_paths = save_transfer_exports_with_supply_overrides(
            reconciliation_table,
            economies=[economy],
            scenarios=export_scenario_list,
            output_dir=TRANSFORMATION_EXPORT_OUTPUT_DIR,
            filename_template=transfers_workflow.EXPORT_FILENAME_TEMPLATE,
            full_branch_catalog_df=pre_run_catalog_df if not pre_run_catalog_df.empty else None,
        )
        econ_dummy: list[Path] = []
        if RUN_ELECTRICITY_HEAT_INTERIM:
            interim_records = electricity_heat_interim_workflow.build_electricity_heat_interim_rows(
                economies=[economy]
            )
            for scenario in export_scenario_list:
                transformation_records_by_scenario.setdefault(str(scenario), []).extend(
                    copy.deepcopy(interim_records)
                )
            econ_dummy = build_electricity_heat_interim_workbooks_for_results_supply(
                economies=[economy],
                scenarios=export_scenario_list,
                output_dir=EXPORT_OUTPUT_DIR,
            )
        econ_combined_path = save_combined_supply_transformation_export(
            supply_export_paths=[path for _, path in econ_supply_paths],
            transformation_export_paths=econ_transformation_paths + econ_dummy,
            transfer_export_paths=econ_transfer_paths,
            output_dir=EXPORT_OUTPUT_DIR,
            filename_template=COMBINED_EXPORT_FILENAME_TEMPLATE,
            economy_label=economy,
            scenarios=export_scenario_list,
        )
        econ_other_loss: list[Path] = []
        if RUN_OTHER_LOSS_OWN_USE_PROXY:
            econ_other_loss = build_other_loss_own_use_proxy_workbooks_for_results_supply(
                economies=[economy],
                scenarios=export_scenario_list,
                import_scenarios=import_scenarios,
                proxy_stage=OTHER_LOSS_OWN_USE_PROXY_STAGE,
                iteration_run_mode=CAPACITY_UNMET_PASS_MODE,
                output_fuel_scope=OTHER_LOSS_OWN_USE_OUTPUT_FUEL_SCOPE,
                leap_balance_workbook_path=OTHER_LOSS_OWN_USE_LEAP_BALANCE_WORKBOOK_PATH,
                leap_balance_scenario=OTHER_LOSS_OWN_USE_LEAP_BALANCE_SCENARIO,
                leap_balance_date_id=OTHER_LOSS_OWN_USE_LEAP_BALANCE_DATE_ID,
            )
        econ_agg_demand: list[Path] = []
        if WRITE_AGGREGATED_DEMAND_WORKBOOK and USE_AGGREGATED_DEMAND_AS_DUMMY:
            # The combined supply/transformation workbook for this economy is
            # already written to disk above. The aggregated-demand workbook is a
            # separate LEAP-import artifact, so a failure building it (e.g. a
            # missing ESTO column or an economy absent from the projection data)
            # should not discard this economy's core export. Defer it so the
            # economy keeps its main output and, under THROW_ERROR_AFTER_RUN, the
            # whole run continues; with the flag off it raises immediately as before.
            try:
                econ_agg_demand = build_aggregated_demand_workbooks_for_results_supply(
                    economies=[economy],
                    scenarios=export_scenario_list,
                    output_dir=EXPORT_OUTPUT_DIR,
                    region=LEAP_IMPORT_REGION,
                    excluded_sectors=_effective_agg_demand_excluded,
                    use_sector_branches=bool(AGGREGATED_DEMAND_USE_SECTOR_BRANCHES),
                )
            except Exception as _agg_exc:
                print(
                    f"[WARN] [{economy}] aggregated-demand workbook failed to build; "
                    f"the economy's combined supply/transformation export is unaffected. "
                    f"Error: {_agg_exc!r}"
                )
                workflow_common.defer_or_raise(
                    _agg_exc, context=f"aggregated_demand:{economy}"
                )
        print(f"[INFO] [{economy}] all exports complete.")
        return {
            "economy": economy,
            "skipped": False,
            "combined": econ_combined_path,
            "supply": list(econ_supply_paths),
            "transformation": list(econ_transformation_paths),
            "transfer": list(econ_transfer_paths),
            "electricity_heat": list(econ_dummy),
            "other_loss": list(econ_other_loss),
            "agg_demand": list(econ_agg_demand),
        }

    def _collect_economy_result(result: dict) -> None:
        """Merge one economy's result into the shared path lists (called in main thread)."""
        nonlocal combined_export_path
        export_paths.extend(result["supply"])
        transformation_export_paths.extend(result["transformation"])
        transfer_export_paths.extend(result["transfer"])
        electricity_heat_interim_paths.extend(result["electricity_heat"])
        other_loss_own_use_proxy_paths.extend(result["other_loss"])
        aggregated_demand_workbook_paths.extend(result["agg_demand"])
        if result["combined"] is not None:
            combined_export_path = result["combined"]

    _n_workers = int(PARALLEL_ECONOMY_WORKERS) if isinstance(PARALLEL_ECONOMY_WORKERS, int) else 0
    if _n_workers > 1 and len(economy_list) > 1:
        print(f"[INFO] Running per-economy export generation in parallel (max_workers={_n_workers}).")
        with concurrent.futures.ThreadPoolExecutor(max_workers=_n_workers) as _executor:
            _futures = {_executor.submit(_run_one_economy, econ): econ for econ in economy_list}
            for _future in concurrent.futures.as_completed(_futures):
                _econ = _futures[_future]
                try:
                    _collect_economy_result(_future.result())
                except Exception as _econ_exc:
                    import traceback as _tb
                    print(f"[ERROR] [{_econ}] export failed — {_econ_exc!r}. Continuing.")
                    _tb.print_exc()
                    _economy_export_errors.append((_econ, _econ_exc))
    else:
        for economy in economy_list:
            try:
                _collect_economy_result(_run_one_economy(economy))
            except Exception as _econ_exc:
                import traceback as _tb
                print(f"[ERROR] Economy {economy}: export failed — {_econ_exc!r}. Continuing to next economy.")
                _tb.print_exc()
                _economy_export_errors.append((economy, _econ_exc))

    if _economy_export_errors:
        _failed_labels = ", ".join(econ for econ, _ in _economy_export_errors)
        print(
            f"[WARN] Export errors in {len(_economy_export_errors)} economy/economies: {_failed_labels}. "
            "Re-run with just these economies to retry."
        )
    if _is_capacity_unmet_baseline_seed_pass():
        try:
            supply_scope_paths = [path for _, path in export_paths]
            if not supply_scope_paths:
                for economy in economy_list:
                    supply_scope_paths.extend(
                        sorted(
                            _resolve(EXPORT_OUTPUT_DIR).glob(
                                f"supply_leap_imports_{economy}*.xlsx"
                            )
                        )
                    )
            exported_supply_products = find_exported_supply_products(
                supply_scope_paths,
                assets[1],
            )
            baseline_supply_preservation, supply_breakdown, supply_lineage = (
                build_baseline_supply_conservation_artifacts(
                assets=assets,
                supply_projection_table=supply_projection_table,
                supply_primary_table=supply_primary_table,
                economies=economy_list,
                base_year=BASE_YEAR,
                final_year=FINAL_YEAR,
                included_esto_products=exported_supply_products,
                )
            )
            baseline_supply_preservation_path = write_supply_diagnostic(
                baseline_supply_preservation,
                _resolve(RESULTS_CHECKS_DIR)
                / "supply_reconciliation_baseline_supply_source_preservation.csv",
            )
            baseline_supply_preservation_breakdown_path = write_supply_diagnostic(
                supply_breakdown,
                _resolve(RESULTS_CHECKS_DIR)
                / "supply_reconciliation_baseline_supply_source_preservation_breakdown.csv",
            )
            baseline_supply_preservation_lineage_path = write_supply_diagnostic(
                supply_lineage,
                _resolve(RESULTS_CHECKS_DIR)
                / "supply_reconciliation_baseline_supply_source_preservation_lineage.csv",
            )
            mismatch_count = int(baseline_supply_preservation["is_mismatch"].sum())
            print(
                "[INFO] Wrote diagnostic-only baseline supply source preservation check: "
                f"{baseline_supply_preservation_path} ({mismatch_count} mismatch row(s))."
            )
        except Exception as exc:
            print(f"[WARN] Baseline supply source preservation diagnostic could not run: {exc}")
        try:
            raw_esto, _ = supply_data_pipeline.resolve_dataset(assets[0], "esto")
            raw_ninth = transformation_workflow.core.ninth_data_raw.copy()
            raw_ninth_years = [
                column for column in raw_ninth.columns if str(column).isdigit()
            ]
            if "00_APEC" in economy_list and not raw_ninth["economy"].astype(str).eq("00_APEC").any():
                raw_ninth = transformation_workflow.core.add_all_economy_total(
                    raw_ninth,
                    raw_ninth_years,
                    "00_APEC",
                )
            transformation_reference = build_raw_transformation_output_reference(
                esto=raw_esto,
                ninth=raw_ninth,
                economies=economy_list,
                scenarios=export_scenario_list,
                base_year=BASE_YEAR,
                final_year=FINAL_YEAR,
                include_power_outputs=bool(RUN_ELECTRICITY_HEAT_INTERIM),
            )
            transformation_totals, transformation_breakdown, transformation_lineage = (
                build_transformation_output_conservation(
                    reference_rows=transformation_reference,
                    process_records_by_scenario=transformation_records_by_scenario,
                )
            )
            transformation_output_conservation_path = write_supply_diagnostic(
                transformation_totals,
                _resolve(RESULTS_CHECKS_DIR)
                / "supply_reconciliation_transformation_output_conservation.csv",
            )
            transformation_output_conservation_breakdown_path = write_supply_diagnostic(
                transformation_breakdown,
                _resolve(RESULTS_CHECKS_DIR)
                / "supply_reconciliation_transformation_output_conservation_breakdown.csv",
            )
            transformation_output_conservation_lineage_path = write_supply_diagnostic(
                transformation_lineage,
                _resolve(RESULTS_CHECKS_DIR)
                / "supply_reconciliation_transformation_output_conservation_lineage.csv",
            )
            mismatch_count = int(transformation_totals["is_mismatch"].sum())
            print(
                "[INFO] Wrote diagnostic-only transformation output conservation check: "
                f"{transformation_output_conservation_path} ({mismatch_count} mismatch row(s))."
            )
        except Exception as exc:
            print(f"[WARN] Transformation output conservation diagnostic could not run: {exc}")
    demand_zeroing_paths: list[Path] = []
    if ZERO_OTHER_DEMAND_BRANCHES_FROM_EXPORT and USE_AGGREGATED_DEMAND_AS_DUMMY:
        demand_zeroing_paths = build_other_demand_zeroing_workbooks(
            scenarios=export_scenario_list,
            output_dir=EXPORT_OUTPUT_DIR,
            region=LEAP_IMPORT_REGION,
        )
    fuel_branch_catalog_df = _build_transformation_supply_fuel_catalog_df(
        transformation_export_paths=transformation_export_paths,
        supply_export_paths=[path for _, path in export_paths],
        include_print_summary=True,
    )
    timer.lap("generate LEAP import workbooks")
    fuel_branch_catalog_path: Path | None = None
    if RESULTS_WRITE_LEGACY_SIDECAR_FILES:
        fuel_branch_catalog_path = _build_transformation_supply_fuel_catalog(
            transformation_export_paths=transformation_export_paths,
            supply_export_paths=[path for _, path in export_paths],
            output_dir=OUTPUT_DIR,
        )
    probe_catalog_path: Path | None = None
    leap_import_result = {
        "supply_imported": [],
        "transformation_imported": [],
        "transfer_imported": [],
        "other_loss_own_use_imported": [],
        "electricity_heat_interim_imported": [],
        "aggregated_demand_imported": [],
        "demand_zeroing_imported": [],
    }
    if include_leap_import:
        leap_import_result = run_results_linked_leap_import(
            [path for _, path in export_paths],
            transformation_export_paths,
            transfer_export_paths=transfer_export_paths,
            scenarios=export_scenario_list,
            import_scenarios=import_scenarios,
            region=LEAP_IMPORT_REGION,
            create_branches=LEAP_IMPORT_CREATE_BRANCHES,
            fill_branches=LEAP_IMPORT_FILL_BRANCHES,
            include_current_accounts=(
                LEAP_IMPORT_INCLUDE_CURRENT_ACCOUNTS
                or RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT
            ),
            import_supply_to_leap=LEAP_IMPORT_SUPPLY_TO_LEAP,
            import_transformation_to_leap=LEAP_IMPORT_TRANSFORMATION_TO_LEAP,
            import_transfers_to_leap=LEAP_IMPORT_TRANSFERS_TO_LEAP,
        )
        leap_import_result["other_loss_own_use_imported"] = run_other_loss_own_use_proxy_leap_import(
            other_loss_own_use_proxy_paths,
            scenarios=export_scenario_list,
            import_scenarios=import_scenarios,
            region=LEAP_IMPORT_REGION,
            fill_branches=LEAP_IMPORT_FILL_BRANCHES,
            include_current_accounts=(
                LEAP_IMPORT_INCLUDE_CURRENT_ACCOUNTS
                or RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT
            ),
        )
        leap_import_result["electricity_heat_interim_imported"] = RUN_ELECTRICITY_HEAT_INTERIM_leap_import(
            electricity_heat_interim_paths,
            scenarios=export_scenario_list,
            import_scenarios=import_scenarios,
            region=LEAP_IMPORT_REGION,
            create_branches=LEAP_IMPORT_CREATE_BRANCHES,
            fill_branches=LEAP_IMPORT_FILL_BRANCHES,
            include_current_accounts=(
                LEAP_IMPORT_INCLUDE_CURRENT_ACCOUNTS
                or RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT
            ),
        )
        leap_import_result["aggregated_demand_imported"] = run_aggregated_demand_leap_import(
            aggregated_demand_workbook_paths,
            scenarios=export_scenario_list,
            import_scenarios=import_scenarios,
            region=LEAP_IMPORT_REGION,
            fill_branches=LEAP_IMPORT_FILL_BRANCHES,
            include_current_accounts=(
                LEAP_IMPORT_INCLUDE_CURRENT_ACCOUNTS
                or RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT
            ),
        )
        leap_import_result["demand_zeroing_imported"] = run_other_demand_zeroing_leap_import(
            demand_zeroing_paths,
            scenarios=export_scenario_list,
            import_scenarios=import_scenarios,
            region=LEAP_IMPORT_REGION,
            fill_branches=LEAP_IMPORT_FILL_BRANCHES,
            include_current_accounts=(
                LEAP_IMPORT_INCLUDE_CURRENT_ACCOUNTS
                or RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT
            ),
        )
        timer.lap("run LEAP import")

    baseline_seed_years_by_scenario = workflow_cfg.get_baseline_seed_validation_years(
        export_scenario_list
    )

    baseline_seed_sources = {
        "supply_workflow": [path for _, path in export_paths],
        "transformation_workflow": transformation_export_paths,
        "transfers_workflow": transfer_export_paths,
        "electricity_heat_interim_workflow": electricity_heat_interim_paths,
        "other_loss_own_use_proxy_workflow": other_loss_own_use_proxy_paths,
        "aggregated_demand_workflow": aggregated_demand_workbook_paths,
        "demand_zeroing_workflow": demand_zeroing_paths,
    }
    baseline_seed_sources = {
        source: paths for source, paths in baseline_seed_sources.items() if paths
    }
    baseline_seed_required_scenarios = {
        source: list(export_scenario_list) for source in baseline_seed_sources
    }

    write_per_economy_combined_workbooks(
        economies=economy_list,
        supply_workbook_dir=EXPORT_OUTPUT_DIR,
        aggregated_demand_dir=EXPORT_OUTPUT_DIR,
        output_dir=OUTPUT_DIR,
        id_lookup_path=AGGREGATED_DEMAND_ID_LOOKUP_PATH,
        excluded_sectors=_effective_agg_demand_excluded,
        use_sector_branches=bool(AGGREGATED_DEMAND_USE_SECTOR_BRANCHES),
        source_workbooks_by_workflow=baseline_seed_sources,
        required_years_by_scenario=baseline_seed_years_by_scenario,
        required_scenarios_by_source=baseline_seed_required_scenarios,
    )
    timer.lap("write per-economy combined workbooks")

    results_workbook_path: Path | None = None
    _nonzero_missing_id_rows: pd.DataFrame = pd.DataFrame()
    if RESULTS_SINGLE_FILE_OUTPUT:
        if combined_export_path is None:
            combined_export_path = save_combined_supply_transformation_export(
                supply_export_paths=[path for _, path in export_paths],
                transformation_export_paths=transformation_export_paths + electricity_heat_interim_paths,
                transfer_export_paths=transfer_export_paths,
                output_dir=EXPORT_OUTPUT_DIR,
                filename_template=COMBINED_EXPORT_FILENAME_TEMPLATE,
                economy_label="-".join(economy_list) if economy_list else "economy",
                scenarios=export_scenario_list,
            )
        if combined_export_path is None or not Path(combined_export_path).exists():
            if _economy_export_errors:
                failed_details = "; ".join(
                    f"{economy}: {type(exc).__name__}: {exc}"
                    for economy, exc in _economy_export_errors
                )
                first_error = _economy_export_errors[0][1]
                raise RuntimeError(
                    "Single-file output could not be written because no combined "
                    "supply/transformation workbook was created. One or more economy "
                    f"exports failed first: {failed_details}"
                ) from first_error
            raise FileNotFoundError(
                "Single-file output could not be written because no combined "
                "supply/transformation workbook was created from the generated "
                "supply/transformation/transfer export workbooks."
            )
        resolved_single_file_name = _resolve_results_single_file_name(
            RESULTS_SINGLE_FILE_NAME,
            trade_mode=ACTIVE_SUPPLY_LINK_METHOD,
            iteration_run_mode=CAPACITY_UNMET_PASS_MODE,
            economies=economy_list,
            scenarios=export_scenario_list,
        )
        results_workbook_path, _nonzero_missing_id_rows = save_results_linked_single_workbook(
            reconciliation_table=reconciliation_table,
            sector_demand_table=sector_demand_table,
            demand_table=demand_table,
            transformation_table=transformation_table,
            transformation_sector_table=transformation_sector_table,
            supply_projection_table=supply_projection_table,
            supply_primary_table=supply_primary_table,
            transformation_target_rows=transformation_target_rows,
            fuel_branch_catalog_df=fuel_branch_catalog_df,
            base_df=assets[4],
            years=BALANCE_EXPORT_YEARS,
            economies=economy_list,
            scenarios=balance_scenario_list,
            export_paths=[path for _, path in export_paths],
            transformation_export_paths=transformation_export_paths,
            transfer_export_paths=transfer_export_paths,
            combined_export_path=combined_export_path,
            other_loss_own_use_proxy_paths=other_loss_own_use_proxy_paths,
            aggregated_demand_workbook_paths=aggregated_demand_workbook_paths,
            probe_catalog_path=probe_catalog_path,
            leap_import_result=leap_import_result,
            output_dir=OUTPUT_DIR,
            file_name=resolved_single_file_name,
            archive_dir=RESULTS_SINGLE_FILE_ARCHIVE_DIR,
            archive_min_hours=RESULTS_SINGLE_FILE_ARCHIVE_MIN_HOURS,
            archive_every_run=RESULTS_SINGLE_FILE_ARCHIVE_EVERY_RUN,
        )
        timer.lap("write consolidated run workbook")

    balance_matching_diagnostics_path = _resolve(RESULTS_CHECKS_DIR) / RESULTS_BALANCE_MATCHING_DIAGNOSTICS_FILENAME
    balance_matching_diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
    _sort_output_frame_for_csv(
        balance_matching_diagnostics,
        exclude_sort_columns=("source_workbook", "source_sheet"),
    ).to_csv(balance_matching_diagnostics_path, index=False)
    timer.lap("write balance matching diagnostics")

    actionable_balance_demand_issues = pd.DataFrame()
    counts_text = ""
    if not balance_demand_issues.empty:
        balance_demand_issue_path = _resolve(RESULTS_CHECKS_DIR) / RESULTS_BALANCE_DEMAND_ISSUES_FILENAME
        balance_demand_issue_path.parent.mkdir(parents=True, exist_ok=True)
        _sort_output_frame_for_csv(
            balance_demand_issues,
            exclude_sort_columns=("source", "source_sheet"),
        ).to_csv(balance_demand_issue_path, index=False)
        actionable_balance_demand_issues = balance_demand_issues[
            balance_demand_issues.get("demand_relevant", False).fillna(False).astype(bool)
        ].copy()
        reason_counts = (
            actionable_balance_demand_issues.groupby("reason", dropna=False)
            .size()
            .reset_index(name="row_count")
            .sort_values(["row_count", "reason"], ascending=[False, True])
        )
        counts_text = ", ".join(
            f"{row.reason}: {int(row.row_count)}" for row in reason_counts.itertuples(index=False)
        )
        timer.lap("write balance-demand issue report")
        ignored_issue_count = int(len(balance_demand_issues) - len(actionable_balance_demand_issues))
        if (
            ignored_issue_count > 0
            and actionable_balance_demand_issues.empty
        ):
            print(
                "[INFO] Ignoring non-demand balance mapping issues that do not affect "
                f"supply_reconciliation demand inputs. See {balance_demand_issue_path}. "
                f"Ignored rows: {ignored_issue_count}"
            )
        elif ignored_issue_count > 0:
            print(
                "[INFO] Ignoring balance mapping issues outside demand-side inputs. "
                f"Actionable rows: {len(actionable_balance_demand_issues)}. "
                f"Ignored rows: {ignored_issue_count}. See {balance_demand_issue_path}."
            )
        if not BALANCE_DEMAND_FAIL_ON_MAPPING_ISSUES and not actionable_balance_demand_issues.empty:
            print(
            "[WARN] Balance-demand mapping issues remain unresolved, but "
            "BALANCE_DEMAND_FAIL_ON_MAPPING_ISSUES=False so the workflow is continuing. "
            f"See {balance_demand_issue_path}. Counts: {counts_text}"
            )
    else:
        balance_demand_issue_path = None

    source_diagnostics = _build_source_diagnostics(
        balance_demand_issues=balance_demand_issues,
        nonzero_missing_id_rows=_nonzero_missing_id_rows,
    )
    source_diagnostics_path = _write_source_diagnostics(source_diagnostics)
    timer.lap("write source diagnostics")

    if BALANCE_DEMAND_FAIL_ON_MAPPING_ISSUES and not actionable_balance_demand_issues.empty:
        timer.finish(status="failed")
        if WRITE_WORKFLOW_TIMING_CSV:
            timer.write_csv(timing_path)
        raise RuntimeError(
            "Demand-relevant balance-demand mapping issues remain unresolved after writing "
            "supply_reconciliation outputs. "
            f"See {balance_demand_issue_path}. Counts: {counts_text}"
        )
    if SUPPLY_RECONCILIATION_FAIL_ON_SOURCE_DIAGNOSTICS and not source_diagnostics.empty:
        timer.finish(status="failed")
        if WRITE_WORKFLOW_TIMING_CSV:
            timer.write_csv(timing_path)
        raise RuntimeError(
            "Source diagnostics remain unresolved after writing supply_reconciliation outputs. "
            f"See {source_diagnostics_path}."
        )
    if RESULTS_SINGLE_FILE_OUTPUT and not _nonzero_missing_id_rows.empty:
        print(
            f"\n{'='*70}\n"
            f"[ERROR] {len(_nonzero_missing_id_rows)} rows have BranchID=-1 AND non-zero values.\n"
            f"        LEAP silently skips these on import — feedstock/process shares will\n"
            f"        sum to less than 100%. All outputs above have been saved.\n"
            f"        Fix: export a fresh 'full model export.xlsx' from LEAP that includes\n"
            f"        all active branches, then re-run.\n"
            f"{'='*70}"
        )
        unmatched_key_cols = ["Branch Path", "Variable", "Scenario", "Region"]
        for _, row in _nonzero_missing_id_rows.head(30).iterrows():
            print(
                "  [ERROR] BranchID=-1 | non-zero | "
                + " | ".join(
                    f"{c}='{str(row.get(c) or '').strip()}'" for c in unmatched_key_cols
                )
            )
        if len(_nonzero_missing_id_rows) > 30:
            print(f"  ... plus {len(_nonzero_missing_id_rows) - 30} more")
        print()
        timer.finish(status="failed")
        if WRITE_WORKFLOW_TIMING_CSV:
            timer.write_csv(timing_path)
        raise RuntimeError(
            f"{len(_nonzero_missing_id_rows)} output row(s) have BranchID=-1 with non-zero values. "
            "All requested outputs were written, but these rows must be fixed before LEAP import "
            "because LEAP will skip unknown branch IDs. "
            f"Results workbook: {results_workbook_path}. "
            f"Diagnostics: {source_diagnostics_path}."
        )

    timer.finish()
    if WRITE_WORKFLOW_TIMING_CSV:
        timer.write_csv(timing_path)
    return {
        "results_workbook_path": results_workbook_path,
        "reconciliation_csv": reconciliation_path,
        "balance_table_paths": balance_paths,
        "conventional_balance_paths": conventional_balance_paths,
        "export_paths": [path for _, path in export_paths],
        "transformation_export_paths": transformation_export_paths,
        "transfer_export_paths": transfer_export_paths,
        "combined_export_path": combined_export_path,
        "other_loss_own_use_proxy_paths": other_loss_own_use_proxy_paths,
        "fuel_branch_probe_path": probe_catalog_path,
        "fuel_branch_catalog_path": fuel_branch_catalog_path,
        "demand_mapping_issues_csv": balance_demand_issue_path,
        "direct_demand_mapping_gaps_csv": balance_demand_issue_path,
        "balance_matching_diagnostics_csv": balance_matching_diagnostics_path,
        "balance_demand_conservation_csv": balance_demand_conservation_path,
        "balance_demand_conservation_breakdown_csv": balance_demand_breakdown_path,
        "balance_demand_conservation_lineage_csv": balance_demand_lineage_path,
        "baseline_supply_source_preservation_csv": baseline_supply_preservation_path,
        "baseline_supply_source_preservation_breakdown_csv": baseline_supply_preservation_breakdown_path,
        "baseline_supply_source_preservation_lineage_csv": baseline_supply_preservation_lineage_path,
        "transformation_output_conservation_csv": transformation_output_conservation_path,
        "transformation_output_conservation_breakdown_csv": transformation_output_conservation_breakdown_path,
        "transformation_output_conservation_lineage_csv": transformation_output_conservation_lineage_path,
        "results_update_closure_csv": results_update_closure_path,
        "source_diagnostics_csv": source_diagnostics_path,
        "leap_import_result": leap_import_result,
        "capacity_unmet_iterative_summary": _sra._CAPACITY_UNMET_RUNTIME_PASS_SUMMARY,
        "workflow_stage_timings_csv": str(timing_path),
        "row_count": int(len(reconciliation_table)),
    }


def run_results_linked_supply_workflow(
    economies: Iterable[str] | None = None,
    scenario_names: list[str] | None = None,
    export_dataset_key: str = EXPORT_DATASET_KEY,
    include_leap_import: bool | None = None,
    import_scenarios: Iterable[str] | str | None = LEAP_IMPORT_SCENARIOS,
    use_direct_leap_results_for_demand: bool | None = None,
    scrape_leap_results: bool | None = None,
) -> dict[str, object]:
    """Backward-compatible alias for the transformation+supply runner."""
    return run_results_linked_transformation_supply_workflow(
        economies=economies,
        scenario_names=scenario_names,
        export_dataset_key=export_dataset_key,
        include_leap_import=include_leap_import,
        import_scenarios=import_scenarios,
        use_direct_leap_results_for_demand=use_direct_leap_results_for_demand,
        scrape_leap_results=scrape_leap_results,
    )

