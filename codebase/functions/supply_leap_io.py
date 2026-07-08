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
from typing import Iterable, Mapping

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
from codebase.functions.leap_expressions import build_data_expression_from_row
from codebase.utilities.output_paths import BALANCE_TABLES_ROOT, INTEGRATED_LEAP_EXPORTS_ROOT
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
from codebase.functions.supply_export_rows import coerce_value_by_year
from codebase.functions.transformation_record_builder import _is_excluded_transformation_record
from codebase.functions.baseline_seed_validation import (
    BaselineSeedValidationError,
    SOURCE_FILE_COLUMN,
    SOURCE_WORKFLOW_COLUMN,
    build_validation_issue_groups,
    complete_canonical_share_groups,
    prepare_seed_rows_for_write,
)
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

ECONOMIES = list(workflow_cfg.SUPPLY_NOTEBOOK_ECONOMIES)
SCENARIOS = list(workflow_cfg.SUPPLY_NOTEBOOK_SCENARIOS)
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

def _build_supply_measures_for_trade_mode() -> list[dict[str, object]]:
    """Return supply export measure definitions for the active trade mode."""
    measures = [dict(item) for item in supply_data_pipeline.SUPPLY_MEASURES]
    if not _use_capacity_unmet_iterative_any_mode():
        return measures
    # In results_update passes, leave Imports unchanged in LEAP by omitting
    # import rows from workbook exports entirely.
    if _resolve_capacity_unmet_pass_mode() == "results_update":
        measures = [
            measure
            for measure in measures
            if str(measure.get("name") or "").strip().lower() != "imports"
        ]
    measures.extend(
        [
            {
                "name": "Maximum Production",
                "flow_key": "max_production",
                "units": "Petajoule",
                "per": "",
                "branch_root": "primary",
            },
        ]
    )
    return measures


def _build_transformation_target_multiplier_table(
    reconciliation_table: pd.DataFrame,
    process_target_rows: pd.DataFrame,
    scenario: str,
) -> pd.DataFrame:
    """Return per-product/year multipliers to scale process target rows."""
    if reconciliation_table.empty or process_target_rows.empty:
        return pd.DataFrame(
            columns=["economy", "esto_product", "year", "direction", "multiplier"]
        )
    scenario_key = _resolve_reconciliation_scenario_key(reconciliation_table, scenario)
    scenario_table = reconciliation_table[
        reconciliation_table["scenario"].astype(str).str.strip().str.lower() == scenario_key
    ].copy()
    if scenario_table.empty:
        return pd.DataFrame(
            columns=["economy", "esto_product", "year", "direction", "multiplier"]
        )
    desired_imports = scenario_table[
        ["economy", "esto_product", "year", "transformation_import_target"]
    ].rename(columns={"transformation_import_target": "desired_value"})
    desired_imports["direction"] = "import"
    desired_exports = scenario_table[
        ["economy", "esto_product", "year", "transformation_export_target"]
    ].rename(columns={"transformation_export_target": "desired_value"})
    desired_exports["direction"] = "export"
    desired = pd.concat([desired_imports, desired_exports], ignore_index=True)

    baseline = (
        process_target_rows.groupby(
            ["economy", "esto_product", "year", "direction"],
            dropna=False,
            as_index=False,
        )["value"]
        .sum(min_count=1)
        .rename(columns={"value": "baseline_value"})
    )
    merged = desired.merge(
        baseline,
        on=["economy", "esto_product", "year", "direction"],
        how="left",
    )
    merged["desired_value"] = pd.to_numeric(merged["desired_value"], errors="coerce").fillna(0.0).clip(lower=0.0)
    merged["baseline_value"] = pd.to_numeric(merged["baseline_value"], errors="coerce").fillna(0.0).clip(lower=0.0)
    merged["multiplier"] = (
        merged["desired_value"] / merged["baseline_value"].where(merged["baseline_value"] > 0.0, pd.NA)
    ).fillna(0.0)
    return merged[["economy", "esto_product", "year", "direction", "multiplier"]]


def _resolve_reconciliation_scenario_key(
    reconciliation_table: pd.DataFrame,
    scenario: str,
) -> str:
    """Return the best scenario key available in reconciliation rows."""
    requested_key = str(scenario or "").strip().lower()
    if reconciliation_table.empty or "scenario" not in reconciliation_table.columns:
        return requested_key
    available_keys = {
        str(value).strip().lower()
        for value in reconciliation_table["scenario"].dropna().astype(str).tolist()
        if str(value).strip()
    }
    if requested_key in available_keys:
        return requested_key
    if requested_key in {"current accounts", "current account"}:
        for fallback_key in ("reference", "target"):
            if fallback_key in available_keys:
                return fallback_key
        if len(available_keys) == 1:
            return next(iter(available_keys))
    if "reference" in available_keys:
        return "reference"
    return requested_key


def apply_transformation_target_overrides_for_scenario(
    process_records: list[dict],
    process_target_rows: pd.DataFrame,
    reconciliation_table: pd.DataFrame,
    scenario: str,
) -> list[dict]:
    """Scale process-level transformation import/export targets for one scenario."""
    if not process_records:
        return []
    records = copy.deepcopy(process_records)
    label_to_product = _build_label_to_esto_product_lookup()
    use_legacy_split = _use_legacy_trade_split_mode()
    scaled = pd.DataFrame(
        columns=[
            "record_index",
            "economy",
            "sector_title",
            "process_name",
            "direction",
            "label",
            "esto_product",
            "year",
            "value",
            "multiplier",
            "scaled_value",
        ]
    )
    if use_legacy_split and isinstance(process_target_rows, pd.DataFrame) and not process_target_rows.empty:
        multipliers = _build_transformation_target_multiplier_table(
            reconciliation_table,
            process_target_rows,
            scenario,
        )
        if not multipliers.empty:
            scaled = process_target_rows.merge(
                multipliers,
                on=["economy", "esto_product", "year", "direction"],
                how="left",
            )
            scaled["multiplier"] = pd.to_numeric(scaled["multiplier"], errors="coerce").fillna(0.0)
            scaled["scaled_value"] = (
                pd.to_numeric(scaled["value"], errors="coerce").fillna(0.0).clip(lower=0.0) * scaled["multiplier"]
            )

    for record in records:
        record["output_import_targets"] = {}
        record["output_export_targets"] = {}
        record["process_share_by_year"] = {}
        record.pop("exogenous_capacity_by_year", None)
        record.pop("endogenous_capacity_by_year", None)
        record.pop("maximum_availability_by_year", None)
        record.pop("capacity_credit_by_year", None)
        record.pop("historical_production_by_year", None)

    grouped = (
        scaled.groupby(
            ["record_index", "direction", "label", "year"],
            dropna=False,
            as_index=False,
        )["scaled_value"]
        .sum(min_count=1)
    )
    for _, row in grouped.iterrows():
        index = int(row["record_index"])
        if index < 0 or index >= len(records):
            continue
        direction = str(row["direction"])
        label = str(row["label"])
        year = int(row["year"])
        value = max(float(row["scaled_value"]), 0.0)
        key = "output_import_targets" if direction == "import" else "output_export_targets"
        target_map = records[index].setdefault(key, {})
        label_map = target_map.setdefault(label, {})
        label_map[year] = value

    # Process Share policy:
    # - single-process module: always 100%
    # - multi-process module: split by per-year activity
    #   (scaled trade targets first when available, otherwise output values)
    target_activity_by_record: dict[int, dict[int, float]] = {}
    if use_legacy_split and not scaled.empty:
        target_activity = (
            scaled.groupby(
                ["record_index", "year"],
                dropna=False,
                as_index=False,
            )["scaled_value"]
            .sum(min_count=1)
        )
        for _, row in target_activity.iterrows():
            index = int(row["record_index"])
            if index < 0 or index >= len(records):
                continue
            year = int(row["year"])
            value = max(float(row["scaled_value"]), 0.0)
            target_activity_by_record.setdefault(index, {})[year] = value

    output_activity_by_record: dict[int, dict[int, float]] = {}
    for index, record in enumerate(records):
        output_values = record.get("output_values")
        if not isinstance(output_values, dict) or not output_values:
            continue
        for label, raw_value in output_values.items():
            product = label_to_product.get(str(label)) or label_to_product.get(str(label).lower())
            if not product:
                continue
            year_map = coerce_value_by_year(raw_value, BASE_YEAR, FINAL_YEAR)
            for year, value in year_map.items():
                year_int = int(year)
                output_value = max(float(value), 0.0)
                if output_value <= 0.0:
                    continue
                output_activity_by_record.setdefault(index, {})
                output_activity_by_record[index][year_int] = (
                    output_activity_by_record[index].get(year_int, 0.0) + output_value
                )

    module_to_indices: dict[tuple[str, str], list[int]] = {}
    for index, record in enumerate(records):
        economy = str(record.get("economy") or "").strip()
        sector_title = str(record.get("sector_title") or "").strip()
        if not economy or not sector_title:
            module_key = (f"__record_{index}", "")
        else:
            module_key = (economy, sector_title)
        module_to_indices.setdefault(module_key, []).append(index)

    all_years = tuple(range(BASE_YEAR, FINAL_YEAR + 1))
    for _, indices in module_to_indices.items():
        if not indices:
            continue
        if len(indices) == 1:
            records[indices[0]]["process_share_by_year"] = {year: 100.0 for year in all_years}
            continue

        for year in all_years:
            has_target_activity = any(
                target_activity_by_record.get(index, {}).get(year, 0.0) > 0.0 for index in indices
            )
            activity_lookup = target_activity_by_record if has_target_activity else output_activity_by_record
            total_activity = sum(activity_lookup.get(index, {}).get(year, 0.0) for index in indices)
            if total_activity > 0.0:
                for index in indices:
                    share_value = (activity_lookup.get(index, {}).get(year, 0.0) / total_activity) * 100.0
                    records[index].setdefault("process_share_by_year", {})[year] = max(0.0, min(share_value, 100.0))
            else:
                equal_share = 100.0 / float(len(indices))
                for index in indices:
                    records[index].setdefault("process_share_by_year", {})[year] = equal_share

    if _use_capacity_like_mode():
        # Late import — these reset-scope helpers live in supply_preflight; a
        # top-level import risks a circular import via supply_preflight's own
        # supply module imports.
        from codebase.functions.supply_preflight import (
            _configured_reset_module_names,
            _configured_reset_output_fuel_labels_by_module,
        )

        reset_modules = _configured_reset_module_names()
        reset_output_fuels_by_module = _configured_reset_output_fuel_labels_by_module(
            reset_modules
        )
        scenario_key_for_capacity = _state_token(
            _resolve_reconciliation_scenario_key(reconciliation_table, scenario)
        )
        instance_counter: dict[tuple[str, str, str], int] = {}
        missing_output_scope_modules: set[str] = set()
        for record in records:
            economy_name = str(record.get("economy") or "").strip()
            module_name = str(record.get("sector_title") or "").strip() or "__unknown_module__"
            process_name = str(record.get("process_name") or "").strip() or "__unknown_process__"
            counter_key = (
                _state_token(economy_name),
                _state_token(module_name),
                _state_token(process_name),
            )
            instance_counter[counter_key] = int(instance_counter.get(counter_key, 0)) + 1
            instance = int(instance_counter[counter_key])
            output_total_by_year: dict[int, float] = {int(year): 0.0 for year in all_years}
            output_values = record.get("output_values") or {}
            output_labels: set[str] = set()
            for label in output_values.keys():
                canonical_label = _canonical_transformation_fuel_label(label)
                if canonical_label:
                    output_labels.add(canonical_label)
            for label, raw_value in output_values.items():
                if not str(label or "").strip():
                    continue
                year_map = coerce_value_by_year(raw_value, BASE_YEAR, FINAL_YEAR)
                for year, value in year_map.items():
                    year_int = int(year)
                    if year_int < BASE_YEAR or year_int > FINAL_YEAR:
                        continue
                    output_total_by_year[year_int] = output_total_by_year.get(year_int, 0.0) + max(float(value), 0.0)
            capacity_additions_by_year = _lookup_runtime_capacity_additions_for_record(
                economy=economy_name,
                scenario=scenario_key_for_capacity,
                module=module_name,
                process=process_name,
                instance=instance,
            )
            for year, add_value in capacity_additions_by_year.items():
                if year < BASE_YEAR or year > FINAL_YEAR:
                    continue
                output_total_by_year[int(year)] = output_total_by_year.get(int(year), 0.0) + max(float(add_value), 0.0)

            if CAPACITY_CLEAR_OUTPUT_TRADE_TARGETS:
                sector_name = str(record.get("sector_title") or "").strip().lower()
                zero_map = {int(year): 0.0 for year in all_years}
                target_labels = set(output_labels)
                if reset_modules and sector_name in reset_modules:
                    module_reset_fuels = reset_output_fuels_by_module.get(
                        sector_name, []
                    )
                    if not module_reset_fuels and RESET_SCOPE_USE_FULL_MODEL_EXPORT:
                        missing_output_scope_modules.add(
                            str(record.get("sector_title") or "").strip()
                        )
                    for label in module_reset_fuels:
                        canonical_label = _canonical_transformation_fuel_label(label)
                        if canonical_label:
                            target_labels.add(canonical_label)
                record["output_import_targets"] = {label: dict(zero_map) for label in sorted(target_labels)}
                record["output_export_targets"] = {label: dict(zero_map) for label in sorted(target_labels)}

            record["exogenous_capacity_by_year"] = {
                int(year): max(float(value), 0.0) * float(CAPACITY_CONSTRAINT_FACTOR)
                for year, value in output_total_by_year.items()
            }
            record["capacity_units"] = str(CAPACITY_CONSTRAINT_UNITS)
            record["capacity_scale"] = str(CAPACITY_CONSTRAINT_SCALE)
            record["historical_production_by_year"] = {
                int(year): max(float(value), 0.0)
                for year, value in output_total_by_year.items()
            }
        if missing_output_scope_modules:
            missing_preview = ", ".join(sorted({item for item in missing_output_scope_modules if item}))
            print(
                "[WARN] Missing module-specific 'Output Fuels' scope from full model export "
                "for transformation module(s): "
                f"{missing_preview}. "
                "Only observed output labels from process records were reset for these modules."
            )
    return records


def save_transformation_exports_with_split_targets(
    reconciliation_table: pd.DataFrame,
    process_target_rows: pd.DataFrame,
    process_records: list[dict],
    scenarios: Iterable[str],
    output_dir: Path | str = TRANSFORMATION_EXPORT_OUTPUT_DIR,
    filename_template: str = TRANSFORMATION_EXPORT_FILENAME_TEMPLATE,
    full_branch_catalog_df: pd.DataFrame | None = None,
    records_by_scenario_out: dict[str, list[dict]] | None = None,
) -> list[Path]:
    """Save scenario-specific transformation LEAP workbooks with split import/export targets."""
    if not process_records:
        return []
    if reconciliation_table.empty:
        print("[INFO] save_transformation_exports: reconciliation_table is empty (baseline seed); "
              "exporting transformation rows without supply-link overrides.")
    output_path = _resolve(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    scenario_list = [str(item) for item in scenarios if str(item).strip()]
    saved_paths: list[Path] = []

    def _projection_scenario_for_export(scenario_name: str) -> str:
        text = str(scenario_name or "").strip().lower()
        if text == "target":
            return "target"
        return "reference"

    base_economies = sorted(
        {
            str(record.get("economy")).strip()
            for record in process_records
            if str(record.get("economy") or "").strip()
        }
    )
    # Collect scenario-specific records for all economies once per scenario, then
    # split by economy so each export file only contains one economy's records.
    # Without this per-economy split, multiple economies that share the same sector
    # name (e.g. "BKB and PB plants") emit identical Branch_Path rows that are
    # summed in finalise_export_df, producing Output Share > 100%.
    # All scenarios are collected before writing so zero-skeleton records can
    # borrow inert technology measures from a scenario with genuine data.
    records_by_scenario: dict[str, list[dict]] = {}
    targets_by_scenario: dict[str, object] = {}
    for scenario in scenario_list:
        projection_scenario = _projection_scenario_for_export(scenario)
        all_scenario_records = process_records
        all_scenario_targets = process_target_rows
        try:
            all_scenario_records = transformation_workflow.collect_transformation_rows(
                economies=base_economies or None,
                projection_scenario=projection_scenario,
            )
            all_scenario_targets, all_scenario_records = build_transformation_trade_target_rows(
                economies=base_economies or None,
                process_records=all_scenario_records,
            )
        except Exception as exc:
            print(
                f"[WARN] Failed to build scenario-specific transformation baseline for "
                f"{scenario} (projection={projection_scenario}); falling back to default baseline: {exc}"
            )
        records_by_scenario[scenario] = all_scenario_records
        targets_by_scenario[scenario] = all_scenario_targets

    transformation_workflow.core.borrow_zero_skeleton_measures(records_by_scenario)

    # Zero skeletons are only meaningful for processes that exist as canonical
    # LEAP branches. A config-enabled process with zero data everywhere and no
    # branch in the full-model export (e.g. SMR without CCS in models that only
    # carry Electrolysers + SMR with CCS) must not emit rows: they would have no
    # IDs (SEED-003/011) and pollute share groups (SEED-007).
    if full_branch_catalog_df is not None and not full_branch_catalog_df.empty:
        catalog_paths = [
            str(value).strip().lower()
            for value in full_branch_catalog_df.get("branch_path", pd.Series(dtype=str)).tolist()
            if str(value).strip()
        ]
        _code_map = transformation_workflow.core.code_to_name_mapping

        def _skeleton_process_in_catalog(record) -> bool:
            sector = str(
                transformation_workflow.core.map_code_label(record.get("sector_title"), _code_map) or ""
            ).strip()
            process = str(
                transformation_workflow.core.map_code_label(record.get("process_name"), _code_map) or ""
            ).strip()
            if not sector or not process:
                return False
            prefix = f"transformation\\{sector}\\processes\\{process}".lower()
            return any(
                path == prefix or path.startswith(prefix + "\\") for path in catalog_paths
            )

        dropped_skeletons = 0
        for _scenario in list(records_by_scenario):
            kept_records = []
            for record in records_by_scenario[_scenario] or []:
                if record.get("is_zero_skeleton") and (
                    _is_excluded_transformation_record(record)
                    or not _skeleton_process_in_catalog(record)
                ):
                    dropped_skeletons += 1
                    continue
                kept_records.append(record)
            records_by_scenario[_scenario] = kept_records
        if dropped_skeletons:
            print(
                f"[INFO] Dropped {dropped_skeletons} zero-skeleton record(s) whose process "
                "branch is absent from the full-model catalog."
            )

    if records_by_scenario_out is not None:
        for scenario, scenario_records in records_by_scenario.items():
            records_by_scenario_out.setdefault(str(scenario), []).extend(scenario_records)

    for scenario in scenario_list:
        all_scenario_records = records_by_scenario[scenario]
        all_scenario_targets = targets_by_scenario[scenario]
        for economy in (base_economies or [transformation_workflow._infer_primary_economy(all_scenario_records)]):
            economy_records = [r for r in all_scenario_records if str(r.get("economy") or "").strip() == economy]
            economy_targets = (
                all_scenario_targets[all_scenario_targets["economy"].astype(str).str.strip() == economy].copy()
                if not (isinstance(all_scenario_targets, pd.DataFrame) and all_scenario_targets.empty)
                and isinstance(all_scenario_targets, pd.DataFrame)
                else all_scenario_targets
            )
            if not economy_records:
                continue
            scenario_records = apply_transformation_target_overrides_for_scenario(
                economy_records,
                economy_targets,
                reconciliation_table,
                scenario,
            )
            transformation_workflow.core.consolidate_transformation_output_rows(
                scenario_records,
                include_output_series=transformation_workflow.core.INCLUDE_OUTPUT_SERIES_IN_LEAP_EXPORT,
                use_output_targets=bool(
                    transformation_workflow.core.TRANSFORMATION_OUTPUT_VARIABLES.get("output_import_target")
                    or transformation_workflow.core.TRANSFORMATION_OUTPUT_VARIABLES.get("output_export_target")
                ),
            )
            export_filename = transformation_workflow.format_export_filename(
                economy,
                [scenario],
                filename_template,
            )
            export_path = transformation_workflow.core.save_transformation_export(
                scenario_records,
                transformation_workflow.core.EXPORT_REGION,
                transformation_workflow.core.EXPORT_BASE_YEAR,
                transformation_workflow.core.EXPORT_FINAL_YEAR,
                transformation_workflow.core.code_to_name_mapping,
                str(output_path),
                export_filename,
                transformation_workflow.core.EXPORT_MODEL_NAME,
                [scenario],
                full_branch_catalog_df=full_branch_catalog_df,
                # Producer ownership: transfer-adjacent modules belong to the
                # transfers workbook only, so exclude them from this producer's
                # tier-2 zero-fill scope (they would otherwise duplicate keys).
                in_scope_sector_titles=(
                    transformation_workflow.core.get_analyzed_sector_titles()
                    - transfers_workflow.get_transfer_sector_titles()
                ),
            )
            if export_path:
                export_file = Path(export_path)
                saved_paths.append(export_file)
    return saved_paths


def save_transfer_exports_with_supply_overrides(
    reconciliation_table: pd.DataFrame,
    economies: Iterable[str],
    scenarios: Iterable[str],
    output_dir: Path | str = TRANSFORMATION_EXPORT_OUTPUT_DIR,
    filename_template: str = transfers_workflow.EXPORT_FILENAME_TEMPLATE,
    full_branch_catalog_df=None,
) -> list[Path]:
    """Save scenario-specific transfer workbooks with supply-linked Process Share overrides."""
    output_path = _resolve(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    scenario_list = [str(item) for item in scenarios if str(item).strip()]
    economy_list = [str(item) for item in economies if str(item).strip()]
    if not scenario_list or not economy_list:
        return []

    base_transfer_records_by_economy: dict[str, list[dict]] = {}
    for economy in economy_list:
        economy_records = transfers_workflow.build_transfer_rows(
            economy=economy,
            use_output_targets=False,
        )
        base_transfer_records_by_economy[str(economy)] = (
            transfers_workflow.merge_transfer_rows(economy_records)
            if economy_records
            else []
        )

    empty_target_rows = pd.DataFrame(
        columns=[
            "record_index",
            "economy",
            "sector_title",
            "process_name",
            "direction",
            "label",
            "esto_product",
            "year",
            "value",
        ]
    )
    saved_paths: list[Path] = []
    for scenario in scenario_list:
        for economy, economy_records in base_transfer_records_by_economy.items():
            scenario_records = apply_transformation_target_overrides_for_scenario(
                economy_records,
                empty_target_rows,
                reconciliation_table,
                scenario,
            )
            economy_label = str(economy).strip() or transfers_workflow._infer_primary_economy(scenario_records)
            export_filename = transfers_workflow.format_export_filename(
                economy_label,
                [scenario],
                filename_template,
            )
            export_path = transformation_workflow.core.save_transformation_export(
                scenario_records,
                transformation_workflow.core.EXPORT_REGION,
                transformation_workflow.core.EXPORT_BASE_YEAR,
                transformation_workflow.core.EXPORT_FINAL_YEAR,
                transformation_workflow.core.code_to_name_mapping,
                str(output_path),
                export_filename,
                transformation_workflow.core.EXPORT_MODEL_NAME,
                [scenario],
                full_branch_catalog_df=full_branch_catalog_df,
                # Producer ownership: the transfers workbook zero-fills only the
                # transfer-adjacent modules it owns; all other transformation
                # modules are owned by the transformation/refining producers.
                in_scope_sector_titles=transfers_workflow.get_transfer_sector_titles(),
            )
            if export_path:
                export_file = Path(export_path)
                legacy_paths = _find_legacy_transfer_branch_paths(export_file)
                if legacy_paths:
                    sample = "; ".join(legacy_paths[:3])
                    raise ValueError(
                        "Transfer export still contains legacy generic transfer branches "
                        f"in {export_file.name}: {sample}"
                    )
                saved_paths.append(export_file)
    return saved_paths


def _read_workbook_sheet_with_header_detection(
    workbook_path: Path | str,
    sheet_name: str,
) -> tuple[pd.DataFrame, pd.DataFrame, list]:
    """Return (preamble_rows, data_rows, header_values) for a LEAP-style sheet."""
    path = _resolve(workbook_path)
    raw = pd.read_excel(path, sheet_name=sheet_name, header=None)
    header_row = None
    for idx in range(len(raw.index)):
        values = {_normalize_template_header_value(item).lower() for item in raw.iloc[idx].tolist()}
        if "branch path" in values and "variable" in values:
            header_row = int(idx)
            break
    if header_row is None:
        raise ValueError(f"Could not locate LEAP sheet header in {path.name}::{sheet_name}")
    header_values = raw.iloc[header_row].tolist()
    preamble = raw.iloc[:header_row].copy()
    data = raw.iloc[header_row + 1 :].copy()
    data.columns = header_values
    data = data.dropna(how="all").reset_index(drop=True)
    return preamble, data, header_values


def _merge_workbook_sheets(
    workbook_paths: Iterable[Path | str],
    sheet_name: str,
    source_workflow_by_path: Mapping[str, str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Merge multiple LEAP-style sheets into one standardized table."""
    source_paths = [Path(item) for item in workbook_paths if item and Path(item).exists()]
    if not source_paths:
        return pd.DataFrame(), pd.DataFrame()
    preamble, first_data, first_header = _read_workbook_sheet_with_header_detection(
        source_paths[0],
        sheet_name=sheet_name,
    )
    first_path = source_paths[0]
    first_data[SOURCE_FILE_COLUMN] = str(first_path)
    first_data[SOURCE_WORKFLOW_COLUMN] = (source_workflow_by_path or {}).get(
        str(first_path.resolve()), "unattributed"
    )
    ordered_columns = list(first_data.columns)
    merged = [first_data]
    for path in source_paths[1:]:
        _, data, _ = _read_workbook_sheet_with_header_detection(path, sheet_name=sheet_name)
        data[SOURCE_FILE_COLUMN] = str(path)
        data[SOURCE_WORKFLOW_COLUMN] = (source_workflow_by_path or {}).get(
            str(path.resolve()), "unattributed"
        )
        for col in data.columns:
            if col not in ordered_columns:
                ordered_columns.append(col)
        merged.append(data)
    normalized = [frame.reindex(columns=ordered_columns) for frame in merged]
    merged_data = pd.concat(normalized, ignore_index=True, sort=False)
    if "Branch Path" in merged_data.columns and "Variable" in merged_data.columns:
        merged_data = merged_data.sort_values(["Branch Path", "Variable"]).reset_index(drop=True)
    return preamble, merged_data


def _drop_wide_year_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy without wide year columns such as 2022/2022.0."""
    if df.empty:
        return df.copy()
    year_like = re.compile(r"^\d{4}(?:\.0)?$")
    keep_columns = [col for col in df.columns if not year_like.match(str(col).strip())]
    return df.loc[:, keep_columns].copy()


def _find_legacy_transfer_branch_paths(workbook_path: Path | str) -> list[str]:
    """Return any branch paths that still use the legacy generic Transfers root."""
    path = _resolve(workbook_path)
    if not path.exists():
        return []
    try:
        _, leap_data, _ = _read_workbook_sheet_with_header_detection(path, "LEAP")
    except Exception:
        return []
    if leap_data.empty or "Branch Path" not in leap_data.columns:
        return []
    branch_paths = leap_data["Branch Path"].dropna().astype(str).map(str.strip)
    return sorted(
        {
            value
            for value in branch_paths
            if value.startswith("Transformation\\Transfers\\")
        }
    )


def save_combined_supply_transformation_export(
    *,
    supply_export_paths: Iterable[Path],
    transformation_export_paths: Iterable[Path],
    transfer_export_paths: Iterable[Path],
    output_dir: Path | str = EXPORT_OUTPUT_DIR,
    filename_template: str = COMBINED_EXPORT_FILENAME_TEMPLATE,
    economy_label: str = "economy",
    scenarios: Iterable[str] | None = None,
) -> Path | None:
    """Save a single workbook that combines supply + transformation + transfers rows."""
    supply_paths = [Path(item) for item in supply_export_paths if Path(item).exists()]
    transformation_paths = [
        Path(item) for item in transformation_export_paths if Path(item).exists()
    ]
    transfer_paths = [Path(item) for item in transfer_export_paths if Path(item).exists()]
    paths = [*supply_paths, *transformation_paths, *transfer_paths]
    if not paths:
        return None
    source_workflow_by_path = {
        **{str(path.resolve()): "supply_workflow" for path in supply_paths},
        **{str(path.resolve()): (
            "electricity_heat_interim_workflow"
            if "electricity_heat_interim" in path.name.lower()
            else "transformation_workflow"
        ) for path in transformation_paths},
        **{str(path.resolve()): "transfers_workflow" for path in transfer_paths},
    }
    leap_preamble, leap_data = _merge_workbook_sheets(paths, "LEAP")
    if leap_data.empty:
        return None
    leap_data = _drop_wide_year_columns(leap_data)
    viewing_preamble, viewing_data = _merge_workbook_sheets(
        paths,
        "FOR_VIEWING",
        source_workflow_by_path=source_workflow_by_path,
    )
    if viewing_data.empty:
        viewing_preamble = leap_preamble.copy()
        viewing_data = leap_data.copy()

    scenario_list = [str(item) for item in (scenarios or []) if str(item).strip()]
    scenario_token = workflow_common.format_filename_segment("_".join(scenario_list)) or "scenario"
    economy_token = workflow_common.format_filename_segment(economy_label) or "economy"
    filename = filename_template.format(economy=economy_token, scenario=scenario_token)
    output_path = _resolve(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    combined_path = output_path / filename

    # Re-read LEAP with producer attribution because it is used by blocking
    # diagnostics and must not depend on filename/order inference later.
    leap_preamble, leap_data = _merge_workbook_sheets(
        paths,
        "LEAP",
        source_workflow_by_path=source_workflow_by_path,
    )
    leap_data = _drop_wide_year_columns(leap_data)
    branch_paths = leap_data["Branch Path"].fillna("").astype(str)
    documented_exclusion_mask = branch_paths.map(
        lambda path: path.split("\\")[-1] in patch_baseline_seeds.VALIDATION_IGNORE_FUEL_NAMES
        or any(
            path.startswith(prefix)
            for prefix in patch_baseline_seeds.VALIDATION_IGNORE_PREFIXES
        )
    )
    diagnostics_dir = output_path / "supporting_files" / "baseline_seed_validation"
    diagnostic_stem = combined_path.stem
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    leap_data[documented_exclusion_mask].to_csv(
        diagnostics_dir / f"{diagnostic_stem}_documented_exclusions.csv",
        index=False,
    )
    leap_data = leap_data[~documented_exclusion_mask].copy()

    required_years_by_scenario: dict[str, list[int]] = {}
    scenario_list = [str(item) for item in (scenarios or []) if str(item).strip()]
    for scenario in scenario_list:
        scenario_config = transformation_workflow.core.get_scenario_export_config(
            scenario,
            default_base_year=transformation_workflow.core.EXPORT_BASE_YEAR,
            default_final_year=transformation_workflow.core.EXPORT_FINAL_YEAR,
        )
        start_year, end_year = transformation_workflow.core.resolve_scenario_year_range(
            transformation_workflow.core.EXPORT_BASE_YEAR,
            transformation_workflow.core.EXPORT_FINAL_YEAR,
            scenario_config,
        )
        if scenario.strip().lower() not in {"current account", "current accounts"}:
            start_year = max(int(start_year), int(supply_data_pipeline.PROJECTION_START_YEAR))
        required_years_by_scenario[scenario] = list(range(int(start_year), int(end_year) + 1))
    required_scenarios_by_source = {
        source: scenario_list
        for source in set(source_workflow_by_path.values())
        if scenario_list
    }
    validation = prepare_seed_rows_for_write(
        leap_data,
        template_path=_resolve(RESULTS_VERIFICATION_EXPORT_PATH),
        diagnostics_dir=diagnostics_dir,
        diagnostic_stem=diagnostic_stem,
        required_years_by_scenario=required_years_by_scenario,
        required_scenarios_by_source=required_scenarios_by_source,
    )
    leap_data = validation.resolved_rows.drop(
        columns=[SOURCE_WORKFLOW_COLUMN, SOURCE_FILE_COLUMN, "source_excel_row"],
        errors="ignore",
    )
    # The import-shaped LEAP sheet is authoritative. Mirroring it here keeps
    # FOR_VIEWING free of physical duplicates and invalid IDs as well.
    viewing_data = leap_data.copy()
    viewing_preamble = leap_preamble.copy()

    with pd.ExcelWriter(combined_path, engine="openpyxl", mode="w") as writer:
        leap_preamble.to_excel(writer, sheet_name="LEAP", index=False, header=False)
        pd.DataFrame([list(leap_data.columns)]).to_excel(
            writer,
            sheet_name="LEAP",
            index=False,
            header=False,
            startrow=len(leap_preamble),
        )
        leap_data.to_excel(
            writer,
            sheet_name="LEAP",
            index=False,
            header=False,
            startrow=len(leap_preamble) + 1,
        )
        viewing_preamble.to_excel(writer, sheet_name="FOR_VIEWING", index=False, header=False)
        pd.DataFrame([list(viewing_data.columns)]).to_excel(
            writer,
            sheet_name="FOR_VIEWING",
            index=False,
            header=False,
            startrow=len(viewing_preamble),
        )
        viewing_data.to_excel(
            writer,
            sheet_name="FOR_VIEWING",
            index=False,
            header=False,
            startrow=len(viewing_preamble) + 1,
        )
    print(f"Saved combined supply+transformation workbook to {combined_path}")
    return combined_path


def _resolve_other_loss_own_use_proxy_activity_source_mode(
    *,
    proxy_stage: str | None = None,
    iteration_run_mode: str | None = None,
) -> str:
    """Resolve other loss/own-use proxy activity source from the run stage."""
    stage = str(proxy_stage or OTHER_LOSS_OWN_USE_PROXY_STAGE or "auto").strip().lower()
    if stage in {"first", "first_run", "first_clean", "baseline", "baseline_seed"}:
        return "esto_ninth"
    if stage in {"second", "second_run", "consecutive", "leap_balance", "results_update"}:
        return "leap_balance"
    if stage != "auto":
        raise ValueError(
            "Invalid OTHER_LOSS_OWN_USE_PROXY_STAGE="
            f"{proxy_stage!r}. Valid values are 'auto', 'first', and 'second'."
        )

    mode = _resolve_capacity_unmet_pass_mode(iteration_run_mode)
    if mode == "baseline_seed":
        return "esto_ninth"
    if mode == "results_update":
        return "leap_balance"
    raise ValueError(
        "Cannot auto-resolve other loss/own-use proxy stage from "
        f"CAPACITY_UNMET_PASS_MODE={iteration_run_mode!r}. "
        "Use OTHER_LOSS_OWN_USE_PROXY_STAGE='first' or 'second'."
    )


def _resolve_other_loss_own_use_leap_balance_workbook_path(
    *,
    economy: str,
    activity_source_mode: str,
    workbook_path: Path | str | None = None,
    scenario: str | None = None,
    date_id: str | None = None,
) -> Path | None:
    """Resolve the LEAP balance workbook only when the second-stage proxy needs it."""
    if str(activity_source_mode or "").strip().lower() != "leap_balance":
        return None
    try:
        return other_loss_own_use_proxy_workflow.resolve_leap_balance_workbook_path(
            economy=economy,
            scenario=scenario or OTHER_LOSS_OWN_USE_LEAP_BALANCE_SCENARIO,
            date_id=date_id if date_id is not None else OTHER_LOSS_OWN_USE_LEAP_BALANCE_DATE_ID,
            workbook_path=(
                workbook_path
                if workbook_path is not None
                else OTHER_LOSS_OWN_USE_LEAP_BALANCE_WORKBOOK_PATH
            ),
        )
    except Exception as exc:
        raise FileNotFoundError(
            "Other loss/own-use proxy second-stage mode needs a LEAP balance "
            f"workbook for economy={economy!r}, "
            f"scenario={scenario or OTHER_LOSS_OWN_USE_LEAP_BALANCE_SCENARIO!r}. "
            "Set OTHER_LOSS_OWN_USE_LEAP_BALANCE_WORKBOOK_PATH explicitly or "
            "check data/leap balances exports."
        ) from exc


def build_other_loss_own_use_proxy_workbooks_for_results_supply(
    *,
    economies: Iterable[str],
    scenarios: Iterable[str],
    import_scenarios: Iterable[str] | str | None,
    proxy_stage: str | None = None,
    iteration_run_mode: str | None = None,
    output_fuel_scope: str | None = None,
    leap_balance_workbook_path: Path | str | None = None,
    leap_balance_scenario: str | None = None,
    leap_balance_date_id: str | None = None,
) -> list[Path]:
    """Build one other loss/own-use proxy workbook per economy for this run."""
    economy_list = workflow_common.normalize_economies(economies)
    scenario_list = workflow_common.normalize_workflow_scenarios(scenarios, SCENARIOS)
    activity_source_mode = _resolve_other_loss_own_use_proxy_activity_source_mode(
        proxy_stage=proxy_stage,
        iteration_run_mode=iteration_run_mode,
    )
    paths: list[Path] = []
    for economy in economy_list:
        resolved_balance_workbook = _resolve_other_loss_own_use_leap_balance_workbook_path(
            economy=str(economy),
            activity_source_mode=activity_source_mode,
            workbook_path=leap_balance_workbook_path,
            scenario=leap_balance_scenario,
            date_id=leap_balance_date_id,
        )
        print(
            "[INFO] Building other loss/own-use proxy workbook: "
            f"economy={economy}, activity_source_mode={activity_source_mode}, "
            f"output_fuel_scope={output_fuel_scope or OTHER_LOSS_OWN_USE_OUTPUT_FUEL_SCOPE}"
        )
        output_path = other_loss_own_use_proxy_workflow.assemble_proxy_workbook(
            economy=str(economy),
            scenarios=scenario_list,
            import_scenario=import_scenarios,
            include_leap_import=False,
            activity_source_mode=activity_source_mode,
            leap_balance_workbook_path=resolved_balance_workbook,
            leap_balance_scenario=leap_balance_scenario or OTHER_LOSS_OWN_USE_LEAP_BALANCE_SCENARIO,
            leap_balance_date_id=leap_balance_date_id,
            output_fuel_scope=output_fuel_scope or OTHER_LOSS_OWN_USE_OUTPUT_FUEL_SCOPE,
        )
        paths.append(Path(output_path))
    return paths


def run_other_loss_own_use_proxy_leap_import(
    workbook_paths: Iterable[Path],
    *,
    scenarios: Iterable[str],
    import_scenarios: Iterable[str] | str | None = None,
    region: str = LEAP_IMPORT_REGION,
    fill_branches: bool = LEAP_IMPORT_FILL_BRANCHES,
    include_current_accounts: bool = LEAP_IMPORT_INCLUDE_CURRENT_ACCOUNTS,
) -> list[Path]:
    """Import other loss/own-use proxy workbooks into LEAP from LEAP_WITH_IDS."""
    paths = [Path(item) for item in workbook_paths if item and Path(item).exists()]
    if not paths:
        return []
    if not bool(OTHER_LOSS_OWN_USE_INCLUDE_IN_LEAP_IMPORT):
        print(
            "[INFO] Skipping other loss/own-use LEAP import; workbook(s) were "
            "still generated for manual LEAP import."
        )
        return []
    if get_analysis_input_write_mode() == "api" and not leap_api.is_available():
        print("[INFO] LEAP API unavailable; skipping other loss/own-use LEAP import.")
        return []
    if not bool(fill_branches):
        print("[INFO] Skipping other loss/own-use LEAP import because fill_branches=False.")
        return []

    scenario_choices = workflow_common.resolve_import_scenarios(
        [str(item) for item in scenarios if str(item).strip()],
        import_scenarios,
    )
    if not scenario_choices:
        return []

    from codebase.functions.leap_core import connect_to_leap, fill_branches_from_export_file

    leap_app = connect_to_leap()
    imported: list[Path] = []
    for workbook_path in paths:
        for index, scenario in enumerate(scenario_choices):
            try:
                fill_branches_from_export_file(
                    leap_app,
                    workbook_path,
                    sheet_name="LEAP_WITH_IDS",
                    scenario=scenario,
                    region=region,
                    RAISE_ERROR_ON_FAILED_SET=True,
                    HANDLE_CURRENT_ACCOUNTS_TOO=include_current_accounts and index == 0,
                    RUN_FUEL_CATALOG_PREFLIGHT=False,
                )
                imported.append(workbook_path)
            except Exception as exc:
                print(
                    "[WARN] Other loss/own-use LEAP import failed for "
                    f"{workbook_path.name} ({scenario}): {exc}"
                )
    return imported


def build_electricity_heat_interim_workbooks_for_results_supply(
    *,
    economies: Iterable[str],
    scenarios: Iterable[str],
    output_dir: Path | str | None = None,
) -> list[Path]:
    """Build electricity+heat interim workbooks to accompany the supply/transformation exports.

    Called when RUN_ELECTRICITY_HEAT_INTERIM is True.  Returns a list of written
    workbook paths (one per economy, though the current implementation writes one
    combined file when a single economy is passed).
    """
    economy_list = list(economies)
    scenario_list = list(scenarios)
    if not economy_list:
        return []
    output_path = Path(output_dir or EXPORT_OUTPUT_DIR)
    output_path.mkdir(parents=True, exist_ok=True)
    return electricity_heat_interim_workflow.assemble_electricity_heat_interim_workbook(
        economies=economy_list,
        scenarios=scenario_list,
        export_output_dir=output_path,
    )


def RUN_ELECTRICITY_HEAT_INTERIM_leap_import(
    workbook_paths: Iterable[Path],
    *,
    scenarios: Iterable[str],
    import_scenarios: Iterable[str] | str | None = None,
    region: str = LEAP_IMPORT_REGION,
    create_branches: bool = LEAP_IMPORT_CREATE_BRANCHES,
    fill_branches: bool = LEAP_IMPORT_FILL_BRANCHES,
    include_current_accounts: bool = LEAP_IMPORT_INCLUDE_CURRENT_ACCOUNTS,
) -> list[Path]:
    """Import electricity+heat interim workbooks into LEAP via the API."""
    paths = [Path(item) for item in workbook_paths if item and Path(item).exists()]
    if not paths:
        return []
    if get_analysis_input_write_mode() == "api" and not leap_api.is_available():
        print("[INFO] LEAP API unavailable; skipping electricity+heat interim LEAP import.")
        return []
    if not bool(fill_branches):
        print(
            "[INFO] Skipping electricity+heat interim LEAP import because fill_branches=False."
        )
        return []

    scenario_choices = workflow_common.resolve_import_scenarios(
        [str(item) for item in scenarios if str(item).strip()],
        import_scenarios,
    )
    if not scenario_choices:
        return []

    imported: list[Path] = []
    for workbook_path in paths:
        try:
            available = electricity_heat_interim_workflow.list_export_scenarios(workbook_path)
        except Exception:
            available = []
        target_scenarios = [s for s in scenario_choices if s in available] or available
        for index, scenario in enumerate(target_scenarios):
            try:
                electricity_heat_interim_workflow.import_electricity_heat_interim_workbook_to_leap(
                    export_directory=workbook_path.parent,
                    filename=workbook_path.name,
                    scenario_to_run=scenario,
                    region=region,
                    include_current_accounts=include_current_accounts and index == 0,
                    create_branches=create_branches and index == 0,
                    fill_branches=fill_branches,
                    raise_on_missing_branch=False,
                )
                imported.append(workbook_path)
            except Exception as exc:
                print(
                    f"[WARN] electricity+heat interim LEAP import failed for "
                    f"{workbook_path.name} ({scenario}): {exc}"
                )
    return imported


def build_aggregated_demand_workbooks_for_results_supply(
    *,
    economies: Iterable[str],
    scenarios: Iterable[str],
    output_dir: Path | str = EXPORT_OUTPUT_DIR,
    region: str = LEAP_IMPORT_REGION,
    excluded_sectors: list[str] | None = None,
    use_sector_branches: bool = False,
) -> list[Path]:
    """
    Write Demand\\All demand aggregated\\{fuel} LEAP import workbooks for each economy.

    Called when USE_AGGREGATED_DEMAND_AS_DUMMY and WRITE_AGGREGATED_DEMAND_WORKBOOK
    are both True so that the aggregated demand branches are actually written to LEAP
    (not just used internally for reconciliation).
    Returns a list of written workbook paths.

    excluded_sectors is a list of sector or sub1sector codes to omit from the
    aggregation (e.g. ["14_industry_sector"] or ["16_01_buildings"]).  The exclusion
    is reflected in the output filename so that combine_supply_and_aggregated_demand
    workbooks can locate the correct file.
    """
    from codebase.aggregated_demand_workflow import (
        save_aggregated_demand_as_leap_workbook,
        _sector_exclusion_suffix,
        LEAP_SCENARIOS,
        ESTO_BASE_DATA_PATH,
        PROJECTION_DATA_PATH,
        FUEL_MAPPINGS_PATH,
        BASE_YEAR,
        PROJECTION_END_YEAR,
    )

    economy_list = workflow_common.normalize_economies(economies)
    scenario_list = workflow_common.normalize_workflow_scenarios(scenarios, SCENARIOS)
    out_dir = _resolve(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    exclusion_suffix = _sector_exclusion_suffix(excluded_sectors)
    sector_suffix = "_by_sector" if use_sector_branches else ""
    paths: list[Path] = []
    for economy in economy_list:
        econ_token = workflow_common.format_filename_segment(economy) or "economy"
        scenario_token = "_".join(
            "".join(c for c in s if c.isalnum()) for s in scenario_list
        )
        out_path = out_dir / f"aggregated_demand_{econ_token}_{scenario_token}{exclusion_suffix}{sector_suffix}.xlsx"
        print(f"[INFO] Building aggregated demand workbook for LEAP: economy={economy}")
        if excluded_sectors:
            print(f"[INFO] Excluded sectors: {excluded_sectors}")
        if use_sector_branches:
            print(f"[INFO] Sector-branch mode: branches will include sector sub-level.")
        result = save_aggregated_demand_as_leap_workbook(
            economy=economy,
            output_path=out_path,
            scenarios=scenario_list,
            region=region,
            base_year=BASE_YEAR,
            final_year=PROJECTION_END_YEAR,
            data_path=PROJECTION_DATA_PATH,
            esto_data_path=ESTO_BASE_DATA_PATH,
            fuel_mappings_path=FUEL_MAPPINGS_PATH,
            exclude_own_use_td_losses=bool(AGGREGATED_DEMAND_EXCLUDE_OWN_USE_TD_LOSSES),
            id_lookup_path=AGGREGATED_DEMAND_ID_LOOKUP_PATH,
            excluded_sectors=excluded_sectors,
            use_sector_branches=use_sector_branches,
        )
        if result is not None:
            paths.append(result)
    return paths


def _normalize_ref_text(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip().lower()


def _normalize_ref_metadata(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if text.lower() in {"", "nan", "none", "null", "<na>", "na"}:
        return ""
    return text


def _split_resource_branch(path_value: object) -> tuple[str, str]:
    parts = [p.strip() for p in str(path_value or "").split("\\") if p.strip()]
    if len(parts) < 3 or parts[0].strip().lower() != "resources":
        return "", ""
    root = parts[1].strip().title()
    if root not in {"Primary", "Secondary"}:
        return "", ""
    return f"Resources\\{root}", parts[2].strip()


def _branch_leaf_tokens(label: object) -> set[str]:
    text = _normalize_ref_text(label)
    if not text:
        return set()
    ignored = {"and", "of", "which", "the", "nonspecified", "non", "specified"}
    return {t for t in re.findall(r"[a-z0-9]+", text) if t and t not in ignored}


def _load_reference_export_data() -> pd.DataFrame:
    """Load the full-model reference export used for branch path remapping and metadata backfill."""
    if not USE_RESULTS_VERIFICATION_EXPORT_SOURCE:
        return pd.DataFrame()
    ref_path = _resolve(RESULTS_VERIFICATION_EXPORT_PATH)
    if not ref_path.exists():
        print(f"[WARN] Reference export not found, skipping remap/backfill: {ref_path}")
        return pd.DataFrame()
    try:
        _, ref_data, _ = _read_workbook_sheet_with_header_detection(
            ref_path, RESULTS_VERIFICATION_EXPORT_SHEET
        )
        print(f"[INFO] Loaded reference export: {ref_path.name} ({len(ref_data)} rows)")
        return ref_data
    except Exception as exc:
        print(f"[WARN] Failed reading reference export {ref_path.name}: {exc}")
        return pd.DataFrame()


def _remap_resource_branch_paths(df: pd.DataFrame, reference_df: pd.DataFrame) -> pd.DataFrame:
    """Remap resource branch paths to canonical reference paths where unambiguous."""
    key_cols = ["Branch Path", "Variable", "Scenario", "Region"]
    if reference_df is None or reference_df.empty:
        return df.copy()
    if any(col not in reference_df.columns for col in key_cols):
        return df.copy()
    if any(col not in df.columns for col in key_cols):
        return df.copy()

    out = df.copy()
    for col in key_cols:
        out[f"__k_{col}"] = out[col].map(_normalize_ref_text)

    source = reference_df[key_cols].copy()
    for col in key_cols:
        source[f"__k_{col}"] = source[col].map(_normalize_ref_text)
    source = source.drop_duplicates(subset=[f"__k_{col}" for col in key_cols], keep="first").copy()
    source["__root"], source["__leaf"] = zip(*source["Branch Path"].map(_split_resource_branch))
    source = source[source["__root"] != ""].copy()
    if source.empty:
        return out.drop(columns=[f"__k_{col}" for col in key_cols], errors="ignore")

    source["__k_root"] = source["__root"].map(_normalize_ref_text)
    source["__k_leaf"] = source["__leaf"].map(_normalize_ref_text)
    source["__leaf_tokens"] = source["__leaf"].map(_branch_leaf_tokens)

    source_exact_keys = {
        tuple(row[f"__k_{col}"] for col in key_cols)
        for _, row in source.iterrows()
    }
    scope_groups: dict[tuple, list[dict]] = {}
    for _, row in source.iterrows():
        sk = (str(row["__k_Variable"]), str(row["__k_Scenario"]),
              str(row["__k_Region"]), str(row["__k_root"]))
        scope_groups.setdefault(sk, []).append({
            "branch_path": str(row["Branch Path"]),
            "k_leaf": str(row["__k_leaf"]),
            "leaf_tokens": set(row["__leaf_tokens"]),
        })

    remapped = 0
    for idx, row in out.iterrows():
        root, leaf = _split_resource_branch(row.get("Branch Path", ""))
        if not root:
            continue
        key_tuple = tuple(str(row.get(f"__k_{col}") or "") for col in key_cols)
        if key_tuple in source_exact_keys:
            continue
        sk = (str(row.get("__k_Variable") or ""), str(row.get("__k_Scenario") or ""),
              str(row.get("__k_Region") or ""), _normalize_ref_text(root))
        candidates = scope_groups.get(sk, [])
        if not candidates:
            continue
        leaf_norm = _normalize_ref_text(leaf)
        exact = [c for c in candidates if c["k_leaf"] == leaf_norm and leaf_norm]
        if len(exact) == 1:
            out.at[idx, "Branch Path"] = exact[0]["branch_path"]
            remapped += 1
            continue
        if len(exact) != 0:
            continue
        leaf_toks = _branch_leaf_tokens(leaf)
        fuzzy = [c for c in candidates if leaf_toks and c["leaf_tokens"] and
                 (leaf_toks.issubset(c["leaf_tokens"]) or c["leaf_tokens"].issubset(leaf_toks))]
        if len(fuzzy) == 1:
            out.at[idx, "Branch Path"] = fuzzy[0]["branch_path"]
            remapped += 1

    out = out.drop(columns=[f"__k_{col}" for col in key_cols], errors="ignore")
    if remapped:
        print(f"[INFO] Remapped {remapped} resource branch path(s) to canonical reference paths.")
    return out


def _backfill_metadata_from_reference(df: pd.DataFrame, reference_df: pd.DataFrame) -> pd.DataFrame:
    """Backfill empty Scale/Units/Per.../Method from reference export where generated value is blank."""
    key_cols = ["Branch Path", "Variable", "Scenario", "Region"]
    ref_fields = ["Scale", "Units", "Per...", "Method"]
    if reference_df is None or reference_df.empty:
        return df.copy()
    available = [f for f in ref_fields if f in reference_df.columns]
    if not available or any(col not in reference_df.columns for col in key_cols):
        return df.copy()

    out = df.copy()
    src = reference_df[key_cols + available].copy()
    for col in key_cols:
        src[f"__k_{col}"] = src[col].map(_normalize_ref_text)
        out[f"__k_{col}"] = out[col].map(_normalize_ref_text)
    join_cols = [f"__k_{col}" for col in key_cols]
    src = src.drop_duplicates(subset=join_cols, keep="first")
    merged = out.merge(
        src[join_cols + available].rename(columns={f: f"__ref_{f}" for f in available}),
        on=join_cols, how="left",
    )
    filled = 0
    for field in available:
        ref_col = f"__ref_{field}"
        if ref_col not in merged.columns:
            continue
        if field not in merged.columns:
            merged[field] = ""
        current = merged[field].map(_normalize_ref_metadata)
        ref_vals = merged[ref_col].map(_normalize_ref_metadata)
        mask = current.eq("") & ref_vals.ne("")
        if mask.any():
            merged.loc[mask, field] = ref_vals[mask]
            filled += mask.sum()
    merged = merged.drop(columns=join_cols + [f"__ref_{f}" for f in available], errors="ignore")
    if filled:
        print(f"[INFO] Backfilled {filled} metadata cell(s) from reference export.")
    return merged


def write_per_economy_combined_workbooks(
    *,
    economies: Iterable[str],
    supply_workbook_dir: Path | str = EXPORT_OUTPUT_DIR,
    aggregated_demand_dir: Path | str = EXPORT_OUTPUT_DIR,
    output_dir: Path | str = OUTPUT_DIR,
    id_lookup_path: Path | str | None = None,
    excluded_sectors: list[str] | None = None,
    use_sector_branches: bool = False,
    source_workbooks_by_workflow: Mapping[str, Iterable[Path | str]] | None = None,
    required_years_by_scenario: Mapping[str, Iterable[int]] | None = None,
    required_scenarios_by_source: Mapping[str, Iterable[str]] | None = None,
    validation_base_year: int = workflow_cfg.BASELINE_SEED_VALIDATION_BASE_YEAR,
    validation_final_year: int = workflow_cfg.BASELINE_SEED_VALIDATION_FINAL_YEAR,
    validation_exceptions: Iterable[dict[str, object]] | None = None,
    enforce_validation: bool = True,
) -> list[Path]:
    """
    For each economy, combine supply_leap_imports_{econ}_*.xlsx and
    aggregated_demand_{econ}.xlsx into a single per-economy LEAP import workbook
    (leap_import_{econ}.xlsx) in output_dir.

    Final IDs and branch existence are resolved from ``id_lookup_path`` and
    validated before any workbook is written unless ``enforce_validation`` is
    set to False. When current-run source paths are supplied, stale directory
    matches are not read.

    excluded_sectors must match the value passed to
    build_aggregated_demand_workbooks_for_results_supply so that the filename
    suffix aligns and the aggregated demand workbook can be found.
    """
    from codebase.functions.supply_data_pipeline import get_region_for_economy, APEC_ECONOMY_REGION_MAP
    from codebase.aggregated_demand_workflow import _build_id_lookups, _sector_exclusion_suffix

    supply_dir = _resolve(supply_workbook_dir)
    agg_dir = _resolve(aggregated_demand_dir)
    out_dir = _resolve(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    coverage_start = int(validation_base_year)
    coverage_end = int(validation_final_year)
    if coverage_end < coverage_start:
        raise ValueError(
            f"Baseline-seed validation_final_year ({coverage_end}) precedes "
            f"validation_base_year ({coverage_start})."
        )
    configured_exceptions = list(validation_exceptions or [])
    blocking_findings_are_warnings = bool(
        getattr(workflow_cfg, "BASELINE_SEED_VALIDATION_BLOCKING_FINDINGS_ARE_WARNINGS", False)
    )

    id_lookup_resolved = Path(id_lookup_path) if id_lookup_path is not None else None
    if id_lookup_resolved is None:
        id_lookup_resolved = _resolve(RESULTS_VERIFICATION_EXPORT_PATH)
    branch_to_id: dict[str, int] = {}
    variable_to_id: dict[str, int] = {}
    scenario_to_id: dict[str, int] = {}
    if id_lookup_resolved is not None and id_lookup_resolved.exists():
        branch_to_id, variable_to_id, scenario_to_id = _build_id_lookups(id_lookup_resolved)
    elif id_lookup_resolved is not None:
        print(f"[WARN] ID lookup path not found, IDs will be -1: {id_lookup_resolved}")

    def _read_leap_data(path: Path) -> tuple[pd.DataFrame, list]:
        raw = pd.read_excel(path, sheet_name="LEAP", header=None)
        for idx in range(min(6, len(raw))):
            vals = [str(v).strip().lower() for v in raw.iloc[idx].tolist() if str(v) not in ("nan", "")]
            if "branch path" in vals and "variable" in vals:
                header = raw.iloc[idx].tolist()
                data = raw.iloc[idx + 1:].copy()
                data.columns = header
                data = data.dropna(how="all").reset_index(drop=True)
                return data, header
        raise ValueError(f"Could not find LEAP header in {path.name}")

    def _ensure_ids(data: pd.DataFrame, region: str) -> pd.DataFrame:
        data = data.copy()
        if "Region" in data.columns:
            data["Region"] = region
        if "BranchID" not in data.columns:
            data.insert(0, "BranchID", data["Branch Path"].map(
                lambda x: branch_to_id.get(str(x).strip(), -1)))
            data.insert(1, "VariableID", data["Variable"].map(
                lambda x: variable_to_id.get(str(x).strip(), -1)))
            data.insert(2, "ScenarioID", data["Scenario"].map(
                lambda x: scenario_to_id.get(str(x).strip(), -1)))
            data.insert(3, "RegionID", 1)
        else:
            data["RegionID"] = 1
        return data

    economy_list = workflow_common.normalize_economies(economies)
    run_stamp = datetime.now().strftime("%Y%m%d")
    written: list[Path] = []
    prepared_workbooks: list[tuple[str, pd.DataFrame, Path]] = []
    validation_results: list[tuple[str, object]] = []
    producer_coverage_findings: list[dict[str, object]] = []
    reference_df = _load_reference_export_data()

    def _producer_for_row(configured_source: str, branch_path: object) -> str:
        path = str(branch_path or "").strip().lower()
        if configured_source == "transformation_workflow" and path.startswith(
            "transformation\\oil refin"
        ):
            return "refining_workflow"
        return configured_source

    def _current_source_frames(econ_token: str) -> tuple[list[pd.DataFrame], set[str]]:
        current_frames: list[pd.DataFrame] = []
        found_sources: set[str] = set()
        for source_workflow, configured_paths in (source_workbooks_by_workflow or {}).items():
            for configured_path in configured_paths:
                path = Path(configured_path)
                is_global_source = str(source_workflow) == "demand_zeroing_workflow"
                if not path.exists() or (
                    not is_global_source and econ_token.lower() not in path.name.lower()
                ):
                    continue
                try:
                    data, _ = _read_leap_data(path)
                except Exception as exc:
                    print(f"[WARN] Failed reading {path.name}: {exc}")
                    continue
                data[SOURCE_WORKFLOW_COLUMN] = data["Branch Path"].map(
                    lambda branch: _producer_for_row(str(source_workflow), branch)
                )
                data[SOURCE_FILE_COLUMN] = str(path)
                current_frames.append(data)
                found_sources.add(str(source_workflow))
        return current_frames, found_sources

    def _format_blocking_summary(*, blocking: pd.DataFrame, issue_groups: pd.DataFrame) -> str:
        grouped_bits: list[str] = []
        if not issue_groups.empty and "issue_group_type" in issue_groups.columns:
            issue_group_counts = issue_groups.groupby("issue_group_type", dropna=False).size().sort_index()
            grouped_bits = [f"{issue_type}={count}" for issue_type, count in issue_group_counts.items()]
        rule_bits: list[str] = []
        if not blocking.empty and "rule_id" in blocking.columns:
            rule_counts = blocking["rule_id"].value_counts().sort_index()
            rule_bits = [f"{rule_id}={count}" for rule_id, count in rule_counts.items()]
        if grouped_bits and rule_bits:
            return f"groups: {', '.join(grouped_bits)}; raw rules: {', '.join(rule_bits)}"
        if grouped_bits:
            return f"groups: {', '.join(grouped_bits)}"
        if rule_bits:
            return f"raw rules: {', '.join(rule_bits)}"
        return "no grouped blocking findings"

    for economy in economy_list:
        econ_token = workflow_common.format_filename_segment(economy) or economy
        region = get_region_for_economy(economy)
        frames, found_sources = _current_source_frames(econ_token)

        if source_workbooks_by_workflow is not None:
            missing_sources = sorted(set(source_workbooks_by_workflow) - found_sources)
            for source_workflow in missing_sources:
                producer_coverage_findings.append({
                    "economy": econ_token,
                    "rule_id": "SEED-012",
                    "description": "Every configured producer supplies rows for each requested economy.",
                    "severity": "error",
                    "blocking": True,
                    "status": "fail",
                    "message": "Configured producer has no readable source workbook for this economy.",
                    "evidence": source_workflow,
                    SOURCE_WORKFLOW_COLUMN: source_workflow,
                    SOURCE_FILE_COLUMN: "",
                })

        if source_workbooks_by_workflow is None:
            # Compatibility fallback for notebook callers that have not supplied
            # current-run paths. Select only the newest combined workbook and
            # newest aggregated-demand workbook, rather than stacking stale runs.
            combined_st_files = sorted(
                supply_dir.glob(f"combined_supply_transformation_leap_imports_{econ_token}_*.xlsx"),
                key=lambda path: (path.stat().st_mtime_ns, path.name),
            )
            if combined_st_files:
                for sf in combined_st_files[-1:]:
                    try:
                        data, _ = _read_leap_data(sf)
                        data[SOURCE_WORKFLOW_COLUMN] = data["Branch Path"].map(
                            lambda branch: _producer_for_row(
                                "supply_workflow"
                                if str(branch).lower().startswith("resources\\")
                                else "transformation_workflow",
                                branch,
                            )
                        )
                        data[SOURCE_FILE_COLUMN] = str(sf)
                        frames.append(data)
                    except Exception as exc:
                        print(f"[WARN] Failed reading {sf.name}: {exc}")
            exclusion_suffix = _sector_exclusion_suffix(excluded_sectors)
            sector_suffix = "_by_sector" if use_sector_branches else ""
            agg_candidates = sorted(
                agg_dir.glob(f"aggregated_demand_{econ_token}*{exclusion_suffix}{sector_suffix}.xlsx"),
                key=lambda path: (path.stat().st_mtime_ns, path.name),
            )
            for agg_path in agg_candidates[-1:]:
                try:
                    data, _ = _read_leap_data(agg_path)
                    data[SOURCE_WORKFLOW_COLUMN] = "aggregated_demand_workflow"
                    data[SOURCE_FILE_COLUMN] = str(agg_path)
                    frames.append(data)
                except Exception as exc:
                    print(f"[WARN] Failed reading {agg_path.name}: {exc}")

        if not frames:
            print(f"[INFO] No data to combine for economy={economy}, skipping.")
            continue

        combined = pd.concat(frames, ignore_index=True, sort=False)
        combined = _remap_resource_branch_paths(combined, reference_df)
        combined = _backfill_metadata_from_reference(combined, reference_df)
        if enforce_validation:
            # Preserve non-branch IDs through validation. Canonical rows will be
            # re-enriched from the full-model export, while reviewed aggregate-demand
            # placeholder branches can retain their valid Variable/Scenario/Region IDs
            # even though the BranchID stays unresolved by design.
            combined = combined.drop(columns=["BranchID"], errors="ignore")
        if "Region" in combined.columns:
            combined["Region"] = region

        branch_paths = combined["Branch Path"].fillna("").astype(str)
        aggregate_fuel_mask = branch_paths.map(
            lambda path: path.split("\\")[-1] in patch_baseline_seeds.VALIDATION_IGNORE_FUEL_NAMES
        )
        absent_prefix_mask = branch_paths.map(
            lambda path: any(
                path.startswith(prefix)
                for prefix in patch_baseline_seeds.VALIDATION_IGNORE_PREFIXES
            )
        )
        excluded_rows = combined[aggregate_fuel_mask | absent_prefix_mask].copy()
        diagnostics_dir = out_dir / "supporting_files" / "baseline_seed_validation"
        diagnostics_dir.mkdir(parents=True, exist_ok=True)
        diagnostic_stem = f"baseline_seed_{econ_token}_{run_stamp}"
        excluded_rows.to_csv(
            diagnostics_dir / f"{diagnostic_stem}_documented_exclusions.csv",
            index=False,
        )
        combined = combined[~(aggregate_fuel_mask | absent_prefix_mask)].copy()

        if enforce_validation:
            present_scenarios = sorted({
                str(value).strip()
                for value in combined.get("Scenario", pd.Series(dtype=object))
                if str(value).strip()
            })
            coverage_years_by_scenario = workflow_cfg.get_baseline_seed_validation_years(
                present_scenarios,
                base_year=coverage_start,
                final_year=coverage_end,
            )
            if required_years_by_scenario is not None:
                coverage_years_by_scenario.update({
                    str(scenario): sorted({int(year) for year in years})
                    for scenario, years in required_years_by_scenario.items()
                })

            validation = prepare_seed_rows_for_write(
                combined,
                template_path=id_lookup_resolved,
                diagnostics_dir=diagnostics_dir,
                diagnostic_stem=diagnostic_stem,
                required_years_by_scenario=coverage_years_by_scenario,
                required_scenarios_by_source=required_scenarios_by_source,
                exceptions=configured_exceptions,
                blocking_findings_are_warnings=blocking_findings_are_warnings,
                raise_on_blocking=False,
            )
            validation_results.append((econ_token, validation))
            combined = validation.resolved_rows.drop(
                columns=[SOURCE_WORKFLOW_COLUMN, SOURCE_FILE_COLUMN, "source_excel_row"],
                errors="ignore",
            )
            if blocking_findings_are_warnings and not validation.blocking_findings.empty:
                rule_counts = validation.blocking_findings["rule_id"].value_counts().sort_index()
                summary = ", ".join(f"{rule_id}={count}" for rule_id, count in rule_counts.items())
                print(
                    f"[WARN] Baseline-seed validation findings were downgraded to warnings "
                    f"for {econ_token} ({summary})."
                )
        else:
            # Merge-only mode skips baseline-seed validation, but two writer
            # behaviors are still required for a LEAP-importable workbook:
            #   1. canonical share-group completion, so an inactive plant receives
            #      a valid 100% profile (first-fuel synthetic anchor for an
            #      explicitly zero-capacity group, or a borrowed sibling-scenario
            #      profile) instead of an invalid all-zero share group; and
            #   2. LEAP ID resolution, since the per-workflow producers ship the
            #      ID columns empty on purpose for the combine step to fill.
            # Share completion runs first so any synthesized zero/anchor sibling
            # rows also get IDs resolved below.
            if id_lookup_resolved is not None and id_lookup_resolved.exists():
                present_scenarios = sorted({
                    str(value).strip()
                    for value in combined.get("Scenario", pd.Series(dtype=object))
                    if str(value).strip()
                })
                share_years_by_scenario = workflow_cfg.get_baseline_seed_validation_years(
                    present_scenarios,
                    base_year=coverage_start,
                    final_year=coverage_end,
                )
                if required_years_by_scenario is not None:
                    share_years_by_scenario.update({
                        str(scenario): sorted({int(year) for year in years})
                        for scenario, years in required_years_by_scenario.items()
                    })
                try:
                    combined, _share_findings = complete_canonical_share_groups(
                        combined,
                        template_path=id_lookup_resolved,
                        required_years_by_scenario=share_years_by_scenario,
                    )
                except Exception as exc:
                    print(
                        f"[WARN] [{econ_token}] canonical share-group completion "
                        f"skipped: {exc!r}"
                    )

            combined = combined.drop(
                columns=[SOURCE_WORKFLOW_COLUMN, SOURCE_FILE_COLUMN, "source_excel_row"],
                errors="ignore",
            )
            # Resolve LEAP IDs from the same label lookups the validated path uses;
            # unresolved labels fall back to the -1 sentinel that the warning loop
            # below surfaces.
            if "Branch Path" in combined.columns:
                combined["BranchID"] = combined["Branch Path"].map(
                    lambda x: branch_to_id.get(str(x).strip(), -1))
            if "Variable" in combined.columns:
                combined["VariableID"] = combined["Variable"].map(
                    lambda x: variable_to_id.get(str(x).strip(), -1))
            if "Scenario" in combined.columns:
                combined["ScenarioID"] = combined["Scenario"].map(
                    lambda x: scenario_to_id.get(str(x).strip(), -1))
            combined["RegionID"] = 1

        # Surface unresolved -1 sentinel IDs loudly. These never raise on their
        # own (the row is still written), so without this warning an economy can
        # silently ship rows LEAP cannot resolve. Count per ID column so the log
        # tells you whether it's a branch, variable, or scenario lookup miss.
        for _id_col in ("BranchID", "VariableID", "ScenarioID"):
            if _id_col not in combined.columns:
                continue
            _sentinel = pd.to_numeric(combined[_id_col], errors="coerce") == -1
            _n_sentinel = int(_sentinel.sum())
            if _n_sentinel:
                _sample_branches = (
                    combined.loc[_sentinel, "Branch Path"].astype(str).head(5).tolist()
                    if "Branch Path" in combined.columns
                    else []
                )
                print(
                    f"[WARN] [{econ_token}] {_n_sentinel} row(s) have unresolved {_id_col}=-1 "
                    f"(label not found in ID lookup); these will import into LEAP as -1. "
                    f"Sample branches: {_sample_branches}"
                )

        # Collapse the wide year columns into a single LEAP Data(...) Expression
        # for any row that does not already carry one (rows with an existing
        # Expression are left untouched). The workbook is then split across two
        # sheets: LEAP carries only the Expression (what LEAP imports), while
        # FOR_VIEWING keeps the wide year columns for human review. A blank spacer
        # column separates the value block from the Level columns on both sheets.
        _meta = ["BranchID", "VariableID", "ScenarioID", "RegionID",
                 "Branch Path", "Variable", "Scenario", "Region",
                 "Scale", "Units", "Per...", "Expression"]
        _year_cols = sorted(
            [c for c in combined.columns if isinstance(c, (int, float)) and 500 < float(c) < 2200],
            key=float,
        )
        if "Expression" not in combined.columns:
            combined["Expression"] = pd.NA
        if _year_cols:
            base_year = int(min(_year_cols))
            ca_labels = {"current accounts", "current account"}
            def _resolve_expression(row):
                existing = row.get("Expression")
                if existing is not None and not (
                    isinstance(existing, float) and pd.isna(existing)
                ) and str(existing).strip():
                    return str(existing)
                if not any(pd.notna(row.get(year)) for year in _year_cols):
                    return existing
                scenario = str(row.get("Scenario", "")).strip().lower()
                if scenario in ca_labels:
                    # Current Accounts holds a single historical base-year value;
                    # emit only that year rather than forward-filling zeros across
                    # the projection horizon.
                    return build_data_expression_from_row(row, [base_year])
                return build_data_expression_from_row(row, _year_cols)
            combined["Expression"] = combined.apply(_resolve_expression, axis=1)

        _meta_cols = [c for c in _meta if c in combined.columns]
        _level_cols = [c for c in combined.columns if str(c).startswith("Level")]
        _other = [c for c in combined.columns
                  if c not in _meta_cols and c not in _year_cols and c not in _level_cols]

        BLANK_SPACER = "__BLANK_SPACER__"
        leap_ordered = _meta_cols + [BLANK_SPACER] + _level_cols + _other
        viewing_ordered = _meta_cols + _year_cols + [BLANK_SPACER] + _level_cols + _other

        def _assemble_sheet(ordered_cols):
            frame = combined.reindex(columns=ordered_cols)
            # The header row is written as data (header=False), so the spacer's
            # displayed label is blank while its column name stays unique.
            display_cols = ["" if c == BLANK_SPACER else c for c in ordered_cols]
            preamble_row = {c: pd.NA for c in ordered_cols}
            preamble_row["Branch Path"] = "Area:"
            preamble_row["Scenario"] = "Ver:"
            preamble_row["Region"] = "2"
            blank_row = {c: pd.NA for c in ordered_cols}
            return pd.concat([
                pd.DataFrame([preamble_row]),
                pd.DataFrame([blank_row]),
                pd.DataFrame([display_cols], columns=ordered_cols),
                frame,
            ], ignore_index=True)

        leap_df = _assemble_sheet(leap_ordered)
        viewing_df = _assemble_sheet(viewing_ordered)

        out_path = out_dir / f"leap_import_baseline_seed_{econ_token}_{run_stamp}.xlsx"
        prepared_workbooks.append((econ_token, leap_df, viewing_df, out_path))

    if enforce_validation:
        diagnostics_dir = out_dir / "supporting_files" / "baseline_seed_validation"
        diagnostics_dir.mkdir(parents=True, exist_ok=True)
        consolidated_frames: list[pd.DataFrame] = []
        if producer_coverage_findings:
            consolidated_frames.append(pd.DataFrame(producer_coverage_findings))
        for econ_token, validation in validation_results:
            if validation.findings.empty:
                continue
            frame = validation.findings.copy()
            frame.insert(0, "economy", econ_token)
            consolidated_frames.append(frame)
        consolidated = (
            pd.concat(consolidated_frames, ignore_index=True, sort=False)
            if consolidated_frames
            else pd.DataFrame()
        )
        consolidated_path = diagnostics_dir / f"baseline_seed_{run_stamp}_consolidated_rule_findings.csv"
        consolidated.to_csv(consolidated_path, index=False)
        consolidated_issue_groups_path = diagnostics_dir / f"baseline_seed_{run_stamp}_consolidated_issue_groups.csv"
        build_validation_issue_groups(consolidated).to_csv(consolidated_issue_groups_path, index=False)
        blocking = consolidated[
            consolidated.get("blocking", pd.Series(False, index=consolidated.index)).fillna(False)
        ] if not consolidated.empty else pd.DataFrame()
        issue_groups = build_validation_issue_groups(blocking)

        if not blocking.empty and not workflow_common.THROW_ERROR_AFTER_RUN:
            summary = _format_blocking_summary(blocking=blocking, issue_groups=issue_groups)
            raise BaselineSeedValidationError(
                "No baseline-seed workbooks were written because consolidated "
                f"blocking findings remain ({summary}). Diagnostics: {consolidated_path}; "
                f"issue groups: {consolidated_issue_groups_path}"
            )

        # In deferred-error mode, write the prepared workbooks for diagnosis and
        # register the blocking error for the workflow's final summary.
        for econ_token, leap_df, viewing_df, out_path in prepared_workbooks:
            for existing in out_dir.glob(f"leap_import_baseline_seed_{econ_token}_*.xlsx"):
                archive_dir = out_dir / "archive"
                archive_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(existing), str(archive_dir / existing.name))
            with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
                leap_df.to_excel(writer, sheet_name="LEAP", index=False, header=False)
                viewing_df.to_excel(writer, sheet_name="FOR_VIEWING", index=False, header=False)
            print(f"[INFO] Wrote baseline seed for economy={econ_token} -> {out_path.name} (stamp={run_stamp})")
            written.append(out_path)

        if not blocking.empty:
            summary = _format_blocking_summary(blocking=blocking, issue_groups=issue_groups)
            blocked_economies = sorted({str(e) for e in blocking["economy"].tolist()})
            print(
                f"[WARN] Baseline-seed workbooks were written for {len(written)} economy/economies, "
                f"but consolidated blocking findings remain for {blocked_economies} ({summary}). "
                f"These economies' workbooks may contain unresolved -1 BranchID/VariableID/"
                f"ScenarioID rows or other blocking issues -- review before LEAP import. "
                f"Diagnostics: {consolidated_path}; issue groups: {consolidated_issue_groups_path}"
            )
            workflow_common.defer_or_raise(
                BaselineSeedValidationError(
                    "Consolidated blocking findings remain after writing baseline-seed "
                    f"workbooks ({summary}). Diagnostics: {consolidated_path}; "
                    f"issue groups: {consolidated_issue_groups_path}"
                ),
                context=f"write_per_economy_combined_workbooks:{blocked_economies}",
            )
    else:
        for econ_token, leap_df, viewing_df, out_path in prepared_workbooks:
            if out_path.exists():
                out_path.unlink()
            with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
                leap_df.to_excel(writer, sheet_name="LEAP", index=False, header=False)
                viewing_df.to_excel(writer, sheet_name="FOR_VIEWING", index=False, header=False)
            print(f"[INFO] Wrote combined workbook for economy={econ_token} -> {out_path.name} (stamp={run_stamp})")
            written.append(out_path)

    return written


def run_aggregated_demand_leap_import(
    workbook_paths: Iterable[Path],
    *,
    scenarios: Iterable[str],
    import_scenarios: Iterable[str] | str | None = None,
    region: str = LEAP_IMPORT_REGION,
    fill_branches: bool = LEAP_IMPORT_FILL_BRANCHES,
    include_current_accounts: bool = LEAP_IMPORT_INCLUDE_CURRENT_ACCOUNTS,
) -> list[Path]:
    """Import aggregated-demand workbooks into LEAP via the API."""
    paths = [Path(item) for item in workbook_paths if item and Path(item).exists()]
    if not paths:
        return []
    if not bool(AGGREGATED_DEMAND_INCLUDE_IN_LEAP_IMPORT):
        print(
            "[INFO] Skipping aggregated-demand LEAP import; workbook(s) still written "
            "for manual LEAP import."
        )
        return []
    if get_analysis_input_write_mode() == "api" and not leap_api.is_available():
        print("[INFO] LEAP API unavailable; skipping aggregated-demand LEAP import.")
        return []
    if not bool(fill_branches):
        print("[INFO] Skipping aggregated-demand LEAP import because fill_branches=False.")
        return []

    scenario_choices = workflow_common.resolve_import_scenarios(
        [str(item) for item in scenarios if str(item).strip()],
        import_scenarios,
    )
    if not scenario_choices:
        return []

    from codebase.functions.leap_core import connect_to_leap, fill_branches_from_export_file

    leap_app = connect_to_leap()
    imported: list[Path] = []
    for workbook_path in paths:
        for index, scenario in enumerate(scenario_choices):
            try:
                fill_branches_from_export_file(
                    leap_app,
                    workbook_path,
                    sheet_name="LEAP",
                    scenario=scenario,
                    region=region,
                    RAISE_ERROR_ON_FAILED_SET=True,
                    HANDLE_CURRENT_ACCOUNTS_TOO=include_current_accounts and index == 0,
                    RUN_FUEL_CATALOG_PREFLIGHT=False,
                )
                imported.append(workbook_path)
            except Exception as exc:
                print(
                    f"[WARN] Aggregated-demand LEAP import failed for "
                    f"{workbook_path.name} ({scenario}): {exc}"
                )
    return imported


def build_other_demand_zeroing_workbooks(
    *,
    scenarios: Iterable[str],
    output_dir: Path | str = EXPORT_OUTPUT_DIR,
    region: str = LEAP_IMPORT_REGION,
    source_path: Path | str | None = None,
    source_sheet: str = "Export",
) -> list[Path]:
    """
    Generate a LEAP import workbook that zeros all non-share demand branches.

    Reads (Branch Path, Variable, Scenario) rows from source_path (defaults to
    RESULTS_VERIFICATION_EXPORT_PATH) and produces a workbook with Expression="0"
    for every row except Demand\\All demand aggregated\\... and share variables.
    Returns a list containing the output path, or empty if nothing was written.
    """
    from codebase.aggregated_demand_workflow import save_demand_zeroing_workbook

    scenario_list = workflow_common.normalize_workflow_scenarios(scenarios, SCENARIOS)
    resolved_source = Path(source_path) if source_path else _resolve(RESULTS_VERIFICATION_EXPORT_PATH)
    out_dir = _resolve(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    econ_token = workflow_common.format_filename_segment(
        ECONOMIES[0] if ECONOMIES else "economy"
    ) or "economy"
    out_path = out_dir / f"demand_zeroing_{econ_token}.xlsx"

    from codebase.aggregated_demand_workflow import DEMAND_OTHER_LOSS_OWN_USE_BRANCH_PREFIX

    exclude_prefixes: list[str] = []
    if ZERO_OTHER_DEMAND_EXCLUDE_OWN_USE_PROXY_BRANCHES:
        exclude_prefixes.append(DEMAND_OTHER_LOSS_OWN_USE_BRANCH_PREFIX)

    result = save_demand_zeroing_workbook(
        output_path=out_path,
        source_path=resolved_source,
        sheet_name=source_sheet,
        scenarios=scenario_list,
        region=region,
        exclude_branch_prefixes=exclude_prefixes if exclude_prefixes else None,
    )
    return [result] if result is not None else []


def run_other_demand_zeroing_leap_import(
    workbook_paths: Iterable[Path],
    *,
    scenarios: Iterable[str],
    import_scenarios: Iterable[str] | str | None = None,
    region: str = LEAP_IMPORT_REGION,
    fill_branches: bool = LEAP_IMPORT_FILL_BRANCHES,
    include_current_accounts: bool = LEAP_IMPORT_INCLUDE_CURRENT_ACCOUNTS,
) -> list[Path]:
    """Import demand-zeroing workbooks into LEAP via the API."""
    paths = [Path(item) for item in workbook_paths if item and Path(item).exists()]
    if not paths:
        return []
    if not bool(ZERO_OTHER_DEMAND_INCLUDE_IN_LEAP_IMPORT):
        print(
            "[INFO] Skipping demand-zeroing LEAP import; workbook(s) still written "
            "for manual LEAP import."
        )
        return []
    if get_analysis_input_write_mode() == "api" and not leap_api.is_available():
        print("[INFO] LEAP API unavailable; skipping demand-zeroing LEAP import.")
        return []
    if not bool(fill_branches):
        print("[INFO] Skipping demand-zeroing LEAP import because fill_branches=False.")
        return []

    scenario_choices = workflow_common.resolve_import_scenarios(
        [str(item) for item in scenarios if str(item).strip()],
        import_scenarios,
    )
    if not scenario_choices:
        return []

    from codebase.functions.leap_core import connect_to_leap, fill_branches_from_export_file

    leap_app = connect_to_leap()
    imported: list[Path] = []
    for workbook_path in paths:
        for index, scenario in enumerate(scenario_choices):
            try:
                fill_branches_from_export_file(
                    leap_app,
                    workbook_path,
                    sheet_name="LEAP",
                    scenario=scenario,
                    region=region,
                    RAISE_ERROR_ON_FAILED_SET=True,
                    HANDLE_CURRENT_ACCOUNTS_TOO=include_current_accounts and index == 0,
                    RUN_FUEL_CATALOG_PREFLIGHT=False,
                )
                imported.append(workbook_path)
            except Exception as exc:
                print(
                    f"[WARN] Demand-zeroing LEAP import failed for "
                    f"{workbook_path.name} ({scenario}): {exc}"
                )
    return imported


def run_results_linked_leap_import(
    supply_export_paths: Iterable[Path],
    transformation_export_paths: Iterable[Path],
    scenarios: Iterable[str],
    transfer_export_paths: Iterable[Path] | None = None,
    import_scenarios: Iterable[str] | str | None = None,
    region: str = LEAP_IMPORT_REGION,
    create_branches: bool = LEAP_IMPORT_CREATE_BRANCHES,
    fill_branches: bool = LEAP_IMPORT_FILL_BRANCHES,
    include_current_accounts: bool = LEAP_IMPORT_INCLUDE_CURRENT_ACCOUNTS,
    import_supply_to_leap: bool = LEAP_IMPORT_SUPPLY_TO_LEAP,
    import_transformation_to_leap: bool = LEAP_IMPORT_TRANSFORMATION_TO_LEAP,
    import_transfers_to_leap: bool = LEAP_IMPORT_TRANSFERS_TO_LEAP,
) -> dict[str, list[Path]]:
    """Import the generated supply + transformation workbooks into LEAP via API."""
    if RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT and not include_current_accounts:
        print(
            "[INFO] Enabling Current Accounts fill pass for LEAP import because "
            "RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT=True."
        )
        include_current_accounts = True
    print(
        "[INFO] LEAP import toggles: "
        f"supply={import_supply_to_leap}, "
        f"transformation={import_transformation_to_leap}, "
        f"transfers={import_transfers_to_leap}, "
        f"include_current_accounts={include_current_accounts}"
    )
    if get_analysis_input_write_mode() == "api" and not leap_api.is_available():
        print("[INFO] LEAP API unavailable in this environment; skipping LEAP import.")
        return {"supply_imported": [], "transformation_imported": [], "transfer_imported": []}

    scenario_choices = workflow_common.resolve_import_scenarios(
        [str(item) for item in scenarios if str(item).strip()],
        import_scenarios,
    )
    if not scenario_choices:
        return {"supply_imported": [], "transformation_imported": [], "transfer_imported": []}

    supply_imported: list[Path] = []
    transformation_imported: list[Path] = []
    transfer_imported: list[Path] = []

    if import_supply_to_leap:
        for export_path in [Path(item) for item in supply_export_paths]:
            if not export_path.exists():
                continue
            for index, scenario in enumerate(scenario_choices):
                try:
                    supply_data_pipeline.run_supply_leap_import(
                        export_directory=export_path.parent,
                        filename=export_path.name,
                        scenario_to_run=scenario,
                        region=region,
                        handle_current_accounts=include_current_accounts and index == 0,
                        fill_branches=fill_branches,
                    )
                    supply_imported.append(export_path)
                except Exception as exc:
                    print(
                        f"[WARN] Supply LEAP import failed for {export_path.name} ({scenario}): {exc}"
                    )
    elif supply_export_paths:
        print(
            "[INFO] Skipping supply LEAP import; workbook(s) were still generated "
            "for manual LEAP import."
        )

    if import_transformation_to_leap:
        for export_path in [Path(item) for item in transformation_export_paths]:
            if not export_path.exists():
                continue
            try:
                available = transformation_workflow.list_export_scenarios(export_path)
            except Exception:
                available = []
            target_scenarios = [item for item in scenario_choices if item in available] or available
            for index, scenario in enumerate(target_scenarios):
                try:
                    transformation_workflow.import_transformation_workbook_to_leap(
                        export_directory=export_path.parent,
                        filename=export_path.name,
                        scenario_to_run=scenario,
                        region=region,
                        include_current_accounts=include_current_accounts and index == 0,
                        create_branches=create_branches and index == 0,
                        fill_branches=fill_branches,
                        raise_on_missing_branch=False,
                    )
                    transformation_imported.append(export_path)
                except Exception as exc:
                    print(
                        f"[WARN] Transformation LEAP import failed for {export_path.name} ({scenario}): {exc}"
                    )
    elif transformation_export_paths:
        print(
            "[INFO] Skipping transformation LEAP import; workbook(s) were still generated "
            "for manual LEAP import."
        )

    if import_transfers_to_leap:
        for export_path in [Path(item) for item in (transfer_export_paths or [])]:
            if not export_path.exists():
                continue
            legacy_paths = _find_legacy_transfer_branch_paths(export_path)
            if legacy_paths:
                sample = "; ".join(legacy_paths[:3])
                print(
                    "[WARN] Skipping transfer LEAP import for "
                    f"{export_path.name}: legacy generic transfer branches detected ({sample})."
                )
                continue
            try:
                available = transfers_workflow.list_export_scenarios(export_path)
            except Exception:
                available = []
            target_scenarios = [item for item in scenario_choices if item in available] or available
            for index, scenario in enumerate(target_scenarios):
                try:
                    transfers_workflow.import_transfer_workbook_to_leap(
                        export_directory=export_path.parent,
                        filename=export_path.name,
                        scenario_to_run=scenario,
                        region=region,
                        include_current_accounts=include_current_accounts and index == 0,
                        create_branches=create_branches and index == 0,
                        fill_branches=fill_branches,
                        raise_on_missing_branch=False,
                    )
                    transfer_imported.append(export_path)
                except Exception as exc:
                    print(
                        f"[WARN] Transfer LEAP import failed for {export_path.name} ({scenario}): {exc}"
                    )
    elif transfer_export_paths:
        print(
            "[INFO] Skipping transfer LEAP import; workbook(s) were still generated "
            "for manual LEAP import."
        )

    return {
        "supply_imported": supply_imported,
        "transformation_imported": transformation_imported,
        "transfer_imported": transfer_imported,
    }


