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
from codebase.utilities.master_config import MASTER_CONFIG_PATH, config_table_exists, read_config_table
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

def _collect_transformation_and_transfer_rows(
    economies: Iterable[str] | None = None,
) -> list[dict]:
    """Return combined process records from transformation and transfers workflows."""
    economy_list = workflow_common.normalize_economies(economies or ECONOMIES)
    transformation_rows = transformation_workflow.collect_transformation_rows(economies=economy_list)
    if REFRESH_TRANSFORMATION_MEASURES_FROM_LEAP_RESULTS:
        transformation_rows = _refresh_transformation_measures_from_leap_results(
            transformation_rows,
            scenario=REFRESH_TRANSFORMATION_MEASURE_SCENARIO,
            region=REFRESH_TRANSFORMATION_MEASURE_REGION,
            base_year=BASE_YEAR,
            final_year=FINAL_YEAR,
        )
    transfer_rows: list[dict] = []
    for economy in economy_list:
        try:
            transfer_rows.extend(
                transfers_workflow.build_transfer_process_records(
                    economy=economy,
                    use_output_targets=False,
                )
            )
        except Exception as exc:
            print(f"[WARN] Failed to build transfer process records for {economy}: {exc}")
    return list(transformation_rows) + transfer_rows


def _query_leap_value_series_for_fuels(
    app,
    *,
    branch_candidates: list[str],
    variable_name: str,
    scenario: str,
    region: str,
    years: list[int],
    fuel_labels: list[str],
    filter_dimensions: tuple[str, ...],
    required: bool = False,
) -> dict[str, dict[int, float]]:
    """Disabled legacy LEAP Results API value query."""
    raise RuntimeError(
        "LEAP Results API value queries are disabled in supply_reconciliation_workflow. "
        "Use exported LEAP balance workbooks instead."
    )


def _refresh_transformation_measures_from_leap_results(
    rows: list[dict],
    *,
    scenario: str,
    region: str,
    base_year: int,
    final_year: int,
) -> list[dict]:
    """Disabled legacy LEAP Results API transformation refresh."""
    raise RuntimeError(
        "REFRESH_TRANSFORMATION_MEASURES_FROM_LEAP_RESULTS is disabled in "
        "supply_reconciliation_workflow. Keep it False and use workbook-based "
        "transformation inputs plus LEAP balance exports."
    )


def _apply_own_use_ratio_feedback(record: dict, years: list[int]) -> dict:
    """
    Recalibrate auxiliary_ratios using LEAP-refreshed feedstock_values and the
    ESTO-derived own_use_ratios stored on the record.

    For each fuel F where 0 < own_use_ratio < 1 and F appears in feedstock_values:
      LEAP 'Inputs' reports feedstock-only consumption for F.
      We estimate the own-use portion using the ESTO ratio:
        estimated_own_use(year) = feedstock(year) × ratio / (1 − ratio)
      The new auxiliary ratio (per unit of output) is:
        new_aux_ratio(year) = estimated_own_use(year) / total_output(year)

    Fuels that are purely feedstock (ratio=0) or purely own-use (ratio=1, not in
    feedstock_values) are left unchanged.

    NOTE: LEAP does not expose own-use separately from transformation inputs in its
    energy balance output.  This function therefore cannot cross-check the estimate
    against actual LEAP-reported own-use values — the split is entirely ESTO-derived.
    """
    own_use_ratios = record.get("own_use_ratios", {})
    if not own_use_ratios:
        return record

    feedstock_values = record.get("feedstock_values", {})
    output_values = record.get("output_values", {})
    auxiliary_ratios = dict(record.get("auxiliary_ratios", {}))

    # Sum output across all output fuels per year.
    output_total_by_year: dict[int, float] = {}
    for year_vals in output_values.values():
        for year, val in (year_vals or {}).items():
            yr = int(year)
            output_total_by_year[yr] = output_total_by_year.get(yr, 0.0) + float(val or 0.0)

    updated_count = 0
    for fuel, ratio in own_use_ratios.items():
        if ratio <= 0.0 or ratio >= 1.0:
            continue
        feedstock_by_year = feedstock_values.get(fuel)
        if not feedstock_by_year:
            continue
        new_ratio_by_year: dict[int, float] = {}
        for year in years:
            feedstock_pj = float((feedstock_by_year or {}).get(year, 0.0))
            output_pj = output_total_by_year.get(year, 0.0)
            if output_pj <= 0.0 or feedstock_pj <= 0.0:
                new_ratio_by_year[year] = auxiliary_ratios.get(fuel, {}).get(year, 0.0)
                continue
            est_own_use = feedstock_pj * ratio / (1.0 - ratio)
            new_ratio_by_year[year] = est_own_use / output_pj
        if new_ratio_by_year:
            auxiliary_ratios[fuel] = new_ratio_by_year
            updated_count += 1

    if updated_count:
        economy = record.get("economy", "")
        process = record.get("process_name", "")
        print(
            f"[INFO] Own-use ratio feedback applied: {updated_count} auxiliary ratio(s) "
            f"recalibrated from LEAP feedstock readback ({economy} / {process})."
        )
    out = dict(record)
    out["auxiliary_ratios"] = auxiliary_ratios
    return out


def _read_leap_template_sheet(path: Path | str, sheet_name: str) -> pd.DataFrame:
    """Read a LEAP-style import sheet by locating the Branch Path header row."""
    raw = pd.read_excel(_resolve(path), sheet_name=sheet_name, header=None)
    header_row: int | None = None
    for idx in range(len(raw.index)):
        values = {
            _normalize_template_header_value(value).lower()
            for value in raw.iloc[idx].tolist()
        }
        if "branch path" in values or "branch_path" in values:
            header_row = int(idx)
            break
    if header_row is None:
        raise ValueError(
            f"Could not find a LEAP-style 'Branch Path' header row in {path} ({sheet_name})."
        )
    columns = [_normalize_template_header_value(value) for value in raw.iloc[header_row].tolist()]
    data = raw.iloc[header_row + 1 :].copy()
    data.columns = columns
    data = data.dropna(how="all").reset_index(drop=True)
    return data


def _parse_data_expression(expression: object) -> dict[int, float]:
    """Parse a LEAP Data(...) expression into a year->value mapping."""
    text = str(expression or "").strip()
    if not text:
        return {}
    match = re.match(r"^\s*Data\s*\((.*)\)\s*$", text, flags=re.IGNORECASE)
    if not match:
        return {}
    body = match.group(1).strip()
    if not body:
        return {}
    parts = [part.strip() for part in body.split(",") if str(part).strip()]
    if len(parts) < 2:
        return {}
    values: dict[int, float] = {}
    for idx in range(0, len(parts) - 1, 2):
        year = pd.to_numeric(parts[idx], errors="coerce")
        value = pd.to_numeric(parts[idx + 1], errors="coerce")
        if pd.isna(year) or pd.isna(value):
            continue
        values[int(year)] = float(value)
    return values


def _infer_constraint_economies(
    template_path: Path | str,
    economies: Iterable[str] | None,
) -> list[str]:
    """Infer which economy/economies a constraint workbook should apply to."""
    economy_list = workflow_common.normalize_economies(economies or ECONOMIES)
    if not economy_list:
        return []
    template_token = re.sub(r"[^a-z0-9]+", "", _resolve(template_path).stem.lower())
    exact_matches = []
    for economy in economy_list:
        economy_token = re.sub(r"[^a-z0-9]+", "", str(economy).lower())
        if economy_token and economy_token in template_token:
            exact_matches.append(str(economy))
    if exact_matches:
        return exact_matches
    if len(economy_list) == 1:
        return [str(economy_list[0])]
    print(
        "[WARN] Skipping constraint workbook because its filename does not identify a single target economy: "
        f"{_resolve(template_path).name}"
    )
    return []


def _load_constraint_value_table(
    template_paths: Iterable[Path | str] | None = None,
    sheet_names: Iterable[str] | None = None,
    economies: Iterable[str] | None = None,
) -> pd.DataFrame:
    """Load LEAP-style template values into a long branch/variable/year table."""
    if not template_paths:
        return pd.DataFrame(
            columns=["economy", "scenario", "branch_path", "variable", "year", "value"]
        )

    rows: list[dict[str, object]] = []
    for template_path in template_paths:
        resolved_path = _resolve(template_path)
        if not resolved_path.exists():
            print(f"[WARN] Constraint workbook not found and will be skipped: {resolved_path}")
            continue
        target_economies = _infer_constraint_economies(resolved_path, economies)
        if not target_economies:
            continue
        try:
            workbook = pd.ExcelFile(resolved_path)
        except Exception as exc:
            print(f"[WARN] Failed to open constraint workbook {resolved_path}: {exc}")
            continue
        target_sheets = list(sheet_names) if sheet_names else list(workbook.sheet_names)
        for sheet_name in target_sheets:
            if str(sheet_name).strip().lower() in {"instructions", "for_viewing"}:
                continue
            if sheet_name not in workbook.sheet_names:
                continue
            try:
                sheet = _read_leap_template_sheet(resolved_path, sheet_name)
            except ValueError:
                continue
            except Exception as exc:
                print(
                    f"[WARN] Failed to read constraint sheet {resolved_path.name}::{sheet_name}: {exc}"
                )
                continue

            branch_column = (
                "Branch Path"
                if "Branch Path" in sheet.columns
                else ("Branch_Path" if "Branch_Path" in sheet.columns else None)
            )
            variable_column = "Variable" if "Variable" in sheet.columns else None
            scenario_column = "Scenario" if "Scenario" in sheet.columns else None
            if not branch_column or not variable_column or not scenario_column:
                continue

            year_columns = [
                str(column)
                for column in sheet.columns
                if str(column).isdigit()
            ]
            for _, row in sheet.iterrows():
                branch_path = str(row.get(branch_column) or "").strip()
                variable = str(row.get(variable_column) or "").strip()
                scenario = str(row.get(scenario_column) or "").strip()
                if not branch_path or not variable or not scenario:
                    continue

                year_values: dict[int, float] = {}
                if year_columns:
                    for column in year_columns:
                        numeric = pd.to_numeric(row.get(column), errors="coerce")
                        if pd.isna(numeric):
                            continue
                        year_values[int(column)] = float(numeric)
                elif "Expression" in sheet.columns:
                    year_values = _parse_data_expression(row.get("Expression"))

                if not year_values:
                    continue

                for economy in target_economies:
                    for year, value in year_values.items():
                        if year < BASE_YEAR or year > FINAL_YEAR:
                            continue
                        rows.append(
                            {
                                "economy": str(economy),
                                "scenario": scenario,
                                "branch_path": branch_path,
                                "variable": variable,
                                "year": int(year),
                                "value": float(value),
                            }
                        )

    if not rows:
        return pd.DataFrame(
            columns=["economy", "scenario", "branch_path", "variable", "year", "value"]
        )
    return pd.DataFrame(rows)


def _classify_supply_constraint_variable(variable: object) -> str | None:
    """Map a LEAP supply variable label to a recognized cap field."""
    text = str(variable or "").strip().lower()
    if not text or "unmet" in text:
        return None
    if "import" in text:
        return "max_imports"
    if "export" in text:
        return "max_exports"
    if any(token in text for token in ("production", "availability")):
        return "max_production"
    return None


def _classify_transformation_constraint_variable(
    branch_path: object,
    variable: object,
) -> str | None:
    """Map a LEAP transformation variable label to a recognized cap field."""
    branch_text = str(branch_path or "").strip().lower()
    variable_text = str(variable or "").strip().lower()
    if "\\output fuels\\" not in branch_text:
        return None
    if "import target" in variable_text or "export target" in variable_text:
        return None
    if "output" in variable_text:
        return "max_transformation_output"
    if "max" in variable_text and any(token in variable_text for token in ("production", "availability")):
        return "max_transformation_output"
    return None


def load_leap_constraint_tables(
    template_paths: Iterable[Path | str] | None = None,
    sheet_names: Iterable[str] | None = None,
    economies: Iterable[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load optional supply and transformation caps from LEAP-style template workbooks."""
    value_table = _load_constraint_value_table(
        template_paths=template_paths,
        sheet_names=sheet_names,
        economies=economies,
    )
    empty_supply = pd.DataFrame(
        columns=[
            "economy",
            "scenario",
            "esto_product",
            "year",
            "max_imports",
            "max_exports",
            "max_production",
        ]
    )
    empty_transformation = pd.DataFrame(
        columns=[
            "economy",
            "scenario",
            "esto_product",
            "year",
            "max_transformation_output",
        ]
    )
    if value_table.empty:
        return empty_supply, empty_transformation

    label_to_product = _build_label_to_esto_product_lookup()

    def _lookup_product(label: object) -> str:
        token = str(label or "").strip()
        if not token:
            return ""
        return str(label_to_product.get(token) or label_to_product.get(token.lower()) or "")

    supply_rows: list[dict[str, object]] = []
    transformation_rows: list[dict[str, object]] = []
    for _, row in value_table.iterrows():
        branch_path = str(row.get("branch_path") or "").strip()
        variable = str(row.get("variable") or "").strip()
        branch_bits = [part.strip() for part in branch_path.split("\\") if str(part).strip()]
        if not branch_bits:
            continue
        branch_head = branch_bits[0].lower()
        fuel_label = branch_bits[-1]
        esto_product = _lookup_product(fuel_label)
        if not esto_product:
            continue

        if branch_head == "resources":
            constraint_field = _classify_supply_constraint_variable(variable)
            if constraint_field:
                supply_rows.append(
                    {
                        "economy": str(row["economy"]),
                        "scenario": str(row["scenario"]),
                        "esto_product": esto_product,
                        "year": int(row["year"]),
                        "constraint_field": constraint_field,
                        "value": max(float(row["value"]), 0.0),
                    }
                )
        elif branch_head == "transformation":
            constraint_field = _classify_transformation_constraint_variable(branch_path, variable)
            if constraint_field:
                transformation_rows.append(
                    {
                        "economy": str(row["economy"]),
                        "scenario": str(row["scenario"]),
                        "esto_product": esto_product,
                        "year": int(row["year"]),
                        "constraint_field": constraint_field,
                        "value": max(float(row["value"]), 0.0),
                    }
                )

    if not supply_rows:
        supply_constraints = empty_supply
    else:
        supply_constraints = (
            pd.DataFrame(supply_rows)
            .pivot_table(
                index=["economy", "scenario", "esto_product", "year"],
                columns="constraint_field",
                values="value",
                aggfunc="max",
            )
            .reset_index()
        )
        supply_constraints.columns.name = None
        for column in ["max_imports", "max_exports", "max_production"]:
            if column not in supply_constraints.columns:
                supply_constraints[column] = pd.NA
        supply_constraints = supply_constraints[
            ["economy", "scenario", "esto_product", "year", "max_imports", "max_exports", "max_production"]
        ]

    if not transformation_rows:
        transformation_constraints = empty_transformation
    else:
        transformation_constraints = (
            pd.DataFrame(transformation_rows)
            .pivot_table(
                index=["economy", "scenario", "esto_product", "year"],
                columns="constraint_field",
                values="value",
                aggfunc="max",
            )
            .reset_index()
        )
        transformation_constraints.columns.name = None
        if "max_transformation_output" not in transformation_constraints.columns:
            transformation_constraints["max_transformation_output"] = pd.NA
        transformation_constraints = transformation_constraints[
            ["economy", "scenario", "esto_product", "year", "max_transformation_output"]
        ]

    return supply_constraints, transformation_constraints


def _apply_aggregated_demand_scenario_multipliers(demand: pd.DataFrame) -> pd.DataFrame:
    """Apply AGGREGATED_DEMAND_SCENARIO_MULTIPLIERS to demand_value by scenario/product.

    Config structure: {scenario_name: {esto_product: multiplier, "_all": global_multiplier}}
    "_all" applies a global multiplier to every product in that scenario before
    product-specific multipliers are applied on top.  Matching is case-insensitive
    for both scenario names and esto_product keys.
    """
    multipliers = AGGREGATED_DEMAND_SCENARIO_MULTIPLIERS
    if not isinstance(multipliers, dict) or not multipliers or demand.empty:
        return demand
    out = demand.copy()
    out["_scenario_key"] = out["scenario"].astype(str).str.strip().str.lower()
    for raw_scenario, product_map in multipliers.items():
        if not isinstance(product_map, dict):
            continue
        scenario_key = str(raw_scenario).strip().lower()
        mask_scenario = out["_scenario_key"] == scenario_key
        if not mask_scenario.any():
            continue
        global_mult = pd.to_numeric(product_map.get("_all"), errors="coerce")
        if not pd.isna(global_mult) and float(global_mult) != 1.0:
            out.loc[mask_scenario, "demand_value"] = (
                out.loc[mask_scenario, "demand_value"].astype(float) * float(global_mult)
            )
        for raw_product, mult in product_map.items():
            if str(raw_product).strip() == "_all":
                continue
            numeric_mult = pd.to_numeric(mult, errors="coerce")
            if pd.isna(numeric_mult) or float(numeric_mult) == 1.0:
                continue
            product_key = str(raw_product).strip().lower()
            mask_product = out["esto_product"].astype(str).str.strip().str.lower() == product_key
            out.loc[mask_scenario & mask_product, "demand_value"] = (
                out.loc[mask_scenario & mask_product, "demand_value"].astype(float) * float(numeric_mult)
            )
    out = out.drop(columns=["_scenario_key"])
    return out


def _infer_active_demand_branch_groups(sector_table: pd.DataFrame) -> list[str]:
    """
    Infer which detailed demand branch groups are present from LEAP demand rows.

    This uses the LEAP comparison output as the source of truth for which demand
    branches are currently active.  It intentionally does not inspect detailed
    LEAP result values to derive subtraction amounts; those still come from the
    ESTO / 9th aggregated source data.
    """
    if sector_table is None or sector_table.empty:
        return []
    if "sheet" not in sector_table.columns:
        return []

    aliases = {
        "freight road": "Freight road",
        "passenger road": "Passenger road",
        "transport non-road": "Transport non-road",
        "industry": "Industry",
        "industry sector": "Industry",
        "other sector": "Other sector",
        "buildings": "Buildings",
    }

    active: list[str] = []
    for raw_value in sector_table["sheet"].dropna().astype(str):
        key = str(raw_value).strip()
        if not key:
            continue
        normalized = aliases.get(key.lower(), key)
        if normalized in LEAP_DEMAND_GROUP_ESTO_SECTOR_MAP and normalized not in active:
            active.append(normalized)
    return active


def load_results_demand_table(
    comparison_long_path: Path | str = COMPARISON_LONG_PATH,
    mapping_status_path: Path | str = MAPPING_STATUS_PATH,
    source_priority: tuple[str, ...] = DEMAND_SOURCE_PRIORITY,
    comparison_long_df: pd.DataFrame | None = None,
    mapping_status_df: pd.DataFrame | None = None,
    economies: list[str] | None = None,
) -> pd.DataFrame:
    """Aggregate mapped LEAP demand to ESTO products, with projection fallback.

    When USE_AGGREGATED_DEMAND_AS_DUMMY is True:
      - For single economy or aggregate sentinel (00_APEC): uses ESTO/ninth
        aggregated demand for that economy/aggregate.
      - For multiple individual economies: builds aggregated demand for each
        economy separately (no cross-economy aggregation), then stacks them.

    Useful for baseline_seed passes on new economies with no balance exports.
    """
    if not USE_AGGREGATED_DEMAND_AS_DUMMY or not economies:
        # Normal path: read LEAP balance exports or use projection fallback
        pass
    else:
        # Aggregated demand path
        from codebase.aggregated_demand_workflow import (
            build_aggregated_demand_as_dummy,
            _is_aggregate_economy,
            ESTO_BASE_DATA_PATH,
            PROJECTION_DATA_PATH,
            LEAP_SCENARIOS,
            USE_SECTOR_BRANCHES,
            resolve_active_branch_excluded_sectors,
        )

        sector_table = load_results_sector_demand_table(
            comparison_long_path=comparison_long_path,
            mapping_status_path=mapping_status_path,
            source_priority=source_priority,
            comparison_long_df=comparison_long_df,
            mapping_status_df=mapping_status_df,
        )
        inferred_active_branches = _infer_active_demand_branch_groups(sector_table)
        if inferred_active_branches:
            active_branches = inferred_active_branches
            print(
                "[INFO] Aggregated demand dummy: inferred active demand branches "
                f"from LEAP results = {active_branches}"
            )
        else:
            active_branches = list(DETAILED_DEMAND_BRANCHES_ACTIVE or [])
            if active_branches:
                print(
                    "[INFO] Aggregated demand dummy: using configured active demand "
                    f"branches = {active_branches}"
                )

        effective_excluded = resolve_active_branch_excluded_sectors(
            active_branches=active_branches,
            sector_map=LEAP_DEMAND_GROUP_ESTO_SECTOR_MAP,
            base_excluded=AGGREGATED_DEMAND_EXCLUDED_SECTORS,
        )
        if effective_excluded:
            print(f"[INFO] Aggregated demand dummy: effective excluded sectors = {effective_excluded}")

        is_aggregate = len(economies) == 1 and _is_aggregate_economy(economies[0])
        if is_aggregate:
            # Single aggregate (00_APEC): sum all member economies
            print(f"[INFO] USE_AGGREGATED_DEMAND_AS_DUMMY=True: loading ESTO/ninth aggregated demand for {economies[0]}.")
            dummy = build_aggregated_demand_as_dummy(
                economy=economies[0],
                scenarios=list(LEAP_SCENARIOS),
                base_year=BASE_YEAR,
                final_year=FINAL_YEAR,
                data_path=PROJECTION_DATA_PATH,
                esto_data_path=ESTO_BASE_DATA_PATH,
                exclude_own_use_td_losses=bool(AGGREGATED_DEMAND_EXCLUDE_OWN_USE_TD_LOSSES),
                excluded_sectors=effective_excluded,
                use_sector_branches=USE_SECTOR_BRANCHES,
            )
        else:
            # Multiple individual economies: build each separately (no cross-economy aggregation)
            print(f"[INFO] USE_AGGREGATED_DEMAND_AS_DUMMY=True: loading ESTO/ninth aggregated demand for {len(economies)} economies separately.")
            parts = [
                build_aggregated_demand_as_dummy(
                    economy=econ,
                    scenarios=list(LEAP_SCENARIOS),
                    base_year=BASE_YEAR,
                    final_year=FINAL_YEAR,
                    data_path=PROJECTION_DATA_PATH,
                    esto_data_path=ESTO_BASE_DATA_PATH,
                    exclude_own_use_td_losses=bool(AGGREGATED_DEMAND_EXCLUDE_OWN_USE_TD_LOSSES),
                    excluded_sectors=effective_excluded,
                    use_sector_branches=USE_SECTOR_BRANCHES,
                )
                for econ in economies
            ]
            dummy = pd.concat(parts, ignore_index=True)
        dummy = _apply_aggregated_demand_scenario_multipliers(dummy)
        return dummy

    # Normal LEAP balance export path (fallback when USE_AGGREGATED_DEMAND_AS_DUMMY is False or no economies)
    sector_table = load_results_sector_demand_table(
        comparison_long_path=comparison_long_path,
        mapping_status_path=mapping_status_path,
        source_priority=source_priority,
        comparison_long_df=comparison_long_df,
        mapping_status_df=mapping_status_df,
    )
    if sector_table.empty:
        return pd.DataFrame(
            columns=["economy", "scenario", "esto_product", "year", "demand_value", "demand_source"]
        )
    source_counts = (
        sector_table.groupby(
            ["economy", "scenario", "esto_product", "year"],
            dropna=False,
            as_index=False,
        )["demand_source"]
        .nunique()
        .rename(columns={"demand_source": "source_count"})
    )
    grouped = (
        sector_table.groupby(
            ["economy", "scenario", "esto_product", "year"],
            dropna=False,
            as_index=False,
        )["demand_value"]
        .sum(min_count=1)
    )
    grouped = grouped.merge(
        source_counts,
        on=["economy", "scenario", "esto_product", "year"],
        how="left",
    )
    grouped["demand_source"] = grouped["source_count"].map(
        lambda count: "mixed" if pd.notna(count) and int(count) > 1 else "leap_or_projection"
    )
    return grouped[
        ["economy", "scenario", "esto_product", "year", "demand_value", "demand_source"]
    ].reset_index(drop=True)


def load_results_sector_demand_table(
    comparison_long_path: Path | str = COMPARISON_LONG_PATH,
    mapping_status_path: Path | str = MAPPING_STATUS_PATH,
    source_priority: tuple[str, ...] = DEMAND_SOURCE_PRIORITY,
    comparison_long_df: pd.DataFrame | None = None,
    mapping_status_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Return LEAP demand rows by sheet/sector and mapped ESTO product."""
    if comparison_long_df is None:
        comparison_path = _resolve(comparison_long_path)
        comparison_long = pd.read_csv(comparison_path)
    else:
        comparison_long = comparison_long_df.copy()

    if mapping_status_df is None:
        mapping_path = _resolve(mapping_status_path)
        mapping_status = pd.read_excel(mapping_path, sheet_name="mapping_status")
    else:
        mapping_status = mapping_status_df.copy()

    required_mapping_cols = ["sheet", "fuel_label", "esto_product", "sector_code_9th", "esto_flow"]
    missing_cols = [col for col in required_mapping_cols if col not in mapping_status.columns]
    if missing_cols:
        raise KeyError(f"mapping_status is missing required columns: {missing_cols}")

    merge_cols = ["sheet", "fuel_label"]
    if "measure" in comparison_long.columns and "measure" in mapping_status.columns:
        merge_cols.append("measure")
        required_mapping_cols = ["measure", *required_mapping_cols]

    mapping_subset = mapping_status[required_mapping_cols].copy()
    if "measure" in mapping_subset.columns:
        mapping_subset["measure"] = mapping_subset["measure"].fillna("").astype(str).str.strip()
    mapping_subset["sheet"] = mapping_subset["sheet"].astype(str)
    mapping_subset["fuel_label"] = mapping_subset["fuel_label"].astype(str)
    mapping_subset["esto_product"] = mapping_subset["esto_product"].fillna("").astype(str).str.strip()
    mapping_subset["sector_code_9th"] = mapping_subset["sector_code_9th"].fillna("").astype(str).str.strip()
    mapping_subset["esto_flow"] = mapping_subset["esto_flow"].fillna("").astype(str).str.strip()
    mapping_subset = mapping_subset[
        mapping_subset["sector_code_9th"].map(_is_demand_sector_mapping)
    ].copy()
    if mapping_subset.empty:
        return pd.DataFrame(
            columns=[
                "economy",
                "scenario",
                "sheet",
                "esto_product",
                "sector_code_9th",
                "esto_flow",
                "year",
                "demand_value",
                "demand_source",
            ]
        )
    mapping_subset = mapping_subset.drop_duplicates(
        subset=merge_cols,
        keep="first",
    )

    merged = comparison_long.merge(
        mapping_subset,
        on=merge_cols,
        how="left",
    )
    merged["source"] = merged["source"].astype(str).str.strip().str.lower()
    merged["esto_product"] = merged["esto_product"].fillna("").astype(str).str.strip()
    merged["value"] = pd.to_numeric(merged["value"], errors="coerce")
    merged["year"] = pd.to_numeric(merged["year"], errors="coerce").astype("Int64")
    merged = merged[
        merged["esto_product"].ne("")
        & merged["source"].isin(source_priority)
        & merged["year"].notna()
    ].copy()
    merged = merged[
        (merged["year"] >= BASE_YEAR)
        & (merged["year"] <= FINAL_YEAR)
    ].copy()

    grouped = (
        merged.groupby(
            ["economy", "scenario", "sheet", "esto_product", "sector_code_9th", "esto_flow", "year", "source"],
            dropna=False,
            as_index=False,
        )["value"]
        .sum(min_count=1)
    )
    if grouped.empty:
        return pd.DataFrame(
            columns=[
                "economy",
                "scenario",
                "sheet",
                "esto_product",
                "sector_code_9th",
                "esto_flow",
                "year",
                "demand_value",
                "demand_source",
            ]
        )

    wide = (
        grouped.pivot_table(
            index=["economy", "scenario", "sheet", "esto_product", "sector_code_9th", "esto_flow", "year"],
            columns="source",
            values="value",
            aggfunc="first",
        )
        .reset_index()
    )

    selections = wide.apply(
        lambda row: _pick_preferred_source(row, source_priority),
        axis=1,
        result_type="expand",
    )
    wide["demand_value"] = selections[0]
    wide["demand_source"] = selections[1]
    wide = wide[wide["demand_value"].notna()].copy()
    return wide[
        [
            "economy",
            "scenario",
            "sheet",
            "esto_product",
            "sector_code_9th",
            "esto_flow",
            "year",
            "demand_value",
            "demand_source",
        ]
    ].reset_index(drop=True)


def build_transformation_balance_table(
    economies: Iterable[str] | None = None,
    base_year: int = BASE_YEAR,
    final_year: int = FINAL_YEAR,
) -> pd.DataFrame:
    """Aggregate transformation+transfer output/input/loss values by ESTO product."""
    label_to_product = _build_label_to_esto_product_lookup()
    rows = _collect_transformation_and_transfer_rows(economies=economies)
    buckets: dict[tuple[str, str, int], dict[str, float]] = {}
    unmapped_labels: set[str] = set()

    def _accumulate(economy: str, product: str, year: int, field: str, value: float) -> None:
        key = (economy, product, year)
        bucket = buckets.setdefault(
            key,
            {
                "economy": economy,
                "esto_product": product,
                "year": year,
                "transformation_output": 0.0,
                "transformation_input": 0.0,
                "transformation_losses": 0.0,
            },
        )
        bucket[field] += float(value)

    for record in rows:
        economy = str(record.get("economy") or "").strip()
        if not economy:
            continue
        for label, year, value in _iter_year_value_items(record.get("output_values"), base_year, final_year):
            product = label_to_product.get(label) or label_to_product.get(label.lower())
            if not product:
                unmapped_labels.add(label)
                continue
            _accumulate(economy, product, year, "transformation_output", value)
        for label, year, value in _iter_year_value_items(record.get("feedstock_values"), base_year, final_year):
            product = label_to_product.get(label) or label_to_product.get(label.lower())
            if not product:
                unmapped_labels.add(label)
                continue
            _accumulate(economy, product, year, "transformation_input", abs(value))
        for label, year, value in _iter_year_value_items(record.get("loss_values"), base_year, final_year):
            product = label_to_product.get(label) or label_to_product.get(label.lower())
            if not product:
                unmapped_labels.add(label)
                continue
            _accumulate(economy, product, year, "transformation_losses", abs(value))

    if unmapped_labels:
        preview = ", ".join(sorted(unmapped_labels)[:10])
        print(
            "[WARN] Some transformation labels could not be mapped back to ESTO products "
            f"and were skipped: {preview}"
        )
    if not buckets:
        return pd.DataFrame(
            columns=[
                "economy",
                "esto_product",
                "year",
                "transformation_output",
                "transformation_input",
                "transformation_losses",
            ]
        )
    return pd.DataFrame(buckets.values()).sort_values(
        ["economy", "esto_product", "year"]
    ).reset_index(drop=True)


def build_transformation_sector_table(
    economies: Iterable[str] | None = None,
    base_year: int = BASE_YEAR,
    final_year: int = FINAL_YEAR,
) -> pd.DataFrame:
    """Aggregate transformation+transfer process rows into balance-style sector lines."""
    label_to_product = _build_label_to_esto_product_lookup()
    rows = _collect_transformation_and_transfer_rows(economies=economies)
    buckets: dict[tuple[str, str, int, str], float] = {}

    def _add(economy: str, scenario: str, year: int, product: str, value: float) -> None:
        key = (economy, scenario, year, product)
        buckets[key] = buckets.get(key, 0.0) + float(value)

    for record in rows:
        economy = str(record.get("economy") or "").strip()
        sector_name = _normalize_conventional_sector_name(
            record.get("sector_title") or record.get("process_name") or ""
        )
        if not economy or not sector_name:
            continue
        for label, year, value in _iter_year_value_items(record.get("output_values"), base_year, final_year):
            product = label_to_product.get(label) or label_to_product.get(label.lower())
            if product:
                _add(economy, sector_name, year, product, abs(value))
        for label, year, value in _iter_year_value_items(record.get("feedstock_values"), base_year, final_year):
            product = label_to_product.get(label) or label_to_product.get(label.lower())
            if product:
                _add(economy, sector_name, year, product, -abs(value))
        for label, year, value in _iter_year_value_items(record.get("loss_values"), base_year, final_year):
            product = label_to_product.get(label) or label_to_product.get(label.lower())
            if product:
                _add(economy, sector_name, year, product, -abs(value))

    if not buckets:
        return pd.DataFrame(
            columns=["economy", "sector", "year", "esto_product", "value"]
        )
    output_rows = [
        {
            "economy": economy,
            "sector": sector,
            "year": year,
            "esto_product": product,
            "value": value,
        }
        for (economy, sector, year, product), value in buckets.items()
    ]
    return pd.DataFrame(output_rows).sort_values(
        ["economy", "sector", "year", "esto_product"]
    ).reset_index(drop=True)


def prepare_projected_supply_table(
    economies: Iterable[str] | None = None,
    dataset_key: str = EXPORT_DATASET_KEY,
) -> tuple[pd.DataFrame, tuple]:
    """Build the existing supply projection table by ESTO product/year."""
    output_columns = [
        "economy",
        "esto_product",
        "year",
        "projected_imports",
        "projected_exports",
        "projected_net_imports",
    ]
    assets = supply_data_pipeline.prepare_supply_assets(economies=economies)
    dataset_map, sector_config, code_to_name_mapping, _, _ = assets
    data, year_cols = supply_data_pipeline.resolve_dataset(dataset_map, dataset_key)
    flow_codes = supply_data_pipeline.FLOW_CODES_BY_DATASET.get(dataset_key)
    if not flow_codes:
        raise KeyError(f"Unknown supply dataset key: {dataset_key}")

    economy_list = workflow_common.normalize_economies(
        economies or supply_data_pipeline.ECONOMIES_TO_ANALYZE
    )
    if not economy_list:
        economy_list = supply_data_pipeline.get_economy_list(data, None)

    rows: list[dict[str, object]] = []
    for economy in economy_list:
        for fuel_key, entry in sorted(sector_config.items()):
            imports_by_year = supply_data_pipeline.build_supply_value_by_year(
                data,
                year_cols,
                economy,
                entry,
                "imports",
                flow_codes.get("imports"),
                BASE_YEAR,
                FINAL_YEAR,
                projection_lookup=supply_data_pipeline.SUPPLY_PROJECTION_LOOKUP,
                projection_years=supply_data_pipeline.PROJECTION_YEAR_RANGE,
                code_to_name_mapping=code_to_name_mapping,
            )
            exports_by_year = supply_data_pipeline.build_supply_value_by_year(
                data,
                year_cols,
                economy,
                entry,
                "exports",
                flow_codes.get("exports"),
                BASE_YEAR,
                FINAL_YEAR,
                projection_lookup=supply_data_pipeline.SUPPLY_PROJECTION_LOOKUP,
                projection_years=supply_data_pipeline.PROJECTION_YEAR_RANGE,
                code_to_name_mapping=code_to_name_mapping,
            )
            for year in range(BASE_YEAR, FINAL_YEAR + 1):
                imports_value = float(imports_by_year.get(year, 0.0))
                exports_value = float(exports_by_year.get(year, 0.0))
                rows.append(
                    {
                        "economy": economy,
                        "esto_product": fuel_key,
                        "year": year,
                        "projected_imports": imports_value,
                        "projected_exports": exports_value,
                        "projected_net_imports": imports_value - exports_value,
                    }
                )
    supply_projection = pd.DataFrame(rows, columns=output_columns)
    return supply_projection, assets


def prepare_supply_primary_table(
    assets: tuple,
    economies: Iterable[str] | None = None,
    dataset_key: str = EXPORT_DATASET_KEY,
) -> pd.DataFrame:
    """Build production and stock-change rows by fuel/year from the supply dataset."""
    output_columns = [
        "economy",
        "year",
        "esto_product",
        "production",
        "stock_changes",
    ]
    dataset_map, sector_config, code_to_name_mapping, _, _ = assets
    data, year_cols = supply_data_pipeline.resolve_dataset(dataset_map, dataset_key)
    flow_codes = supply_data_pipeline.FLOW_CODES_BY_DATASET.get(dataset_key)
    if not flow_codes:
        raise KeyError(f"Unknown supply dataset key: {dataset_key}")

    economy_list = workflow_common.normalize_economies(
        economies or supply_data_pipeline.ECONOMIES_TO_ANALYZE
    )
    if not economy_list:
        economy_list = supply_data_pipeline.get_economy_list(data, None)

    rows: list[dict[str, object]] = []
    for economy in economy_list:
        for fuel_key, entry in sorted(sector_config.items()):
            production_by_year = supply_data_pipeline.build_supply_value_by_year(
                data,
                year_cols,
                economy,
                entry,
                "production",
                flow_codes.get("production"),
                BASE_YEAR,
                FINAL_YEAR,
                projection_lookup=supply_data_pipeline.SUPPLY_PROJECTION_LOOKUP,
                projection_years=supply_data_pipeline.PROJECTION_YEAR_RANGE,
                code_to_name_mapping=code_to_name_mapping,
            )
            stock_changes_by_year = supply_data_pipeline.build_supply_value_by_year(
                data,
                year_cols,
                economy,
                entry,
                "stock_changes",
                flow_codes.get("stock_changes"),
                BASE_YEAR,
                FINAL_YEAR,
                projection_lookup=supply_data_pipeline.SUPPLY_PROJECTION_LOOKUP,
                projection_years=supply_data_pipeline.PROJECTION_YEAR_RANGE,
                code_to_name_mapping=code_to_name_mapping,
            )
            for year in range(BASE_YEAR, FINAL_YEAR + 1):
                rows.append(
                    {
                        "economy": economy,
                        "year": year,
                        "esto_product": fuel_key,
                        "production": float(production_by_year.get(year, 0.0)),
                        "stock_changes": float(stock_changes_by_year.get(year, 0.0)),
                    }
                )
    return pd.DataFrame(rows, columns=output_columns)


def build_reconciliation_table(
    demand_table: pd.DataFrame,
    transformation_table: pd.DataFrame,
    supply_projection_table: pd.DataFrame,
    supply_primary_table: pd.DataFrame | None = None,
    supply_constraints: pd.DataFrame | None = None,
    transformation_constraints: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Combine demand, transformation, and supply into a trade-adjustment table."""
    key_columns = ["economy", "scenario", "esto_product", "year"]
    scenario_values: list[str] = []
    if isinstance(demand_table, pd.DataFrame) and not demand_table.empty and "scenario" in demand_table.columns:
        scenario_values.extend(
            str(value).strip()
            for value in demand_table["scenario"].dropna().astype(str).tolist()
            if str(value).strip()
        )
    for constraint_df in (supply_constraints, transformation_constraints):
        if isinstance(constraint_df, pd.DataFrame) and not constraint_df.empty and "scenario" in constraint_df.columns:
            scenario_values.extend(
                str(value).strip()
                for value in constraint_df["scenario"].dropna().astype(str).tolist()
                if str(value).strip()
            )
    scenario_values = sorted(dict.fromkeys(scenario_values))
    if not scenario_values:
        scenario_values = ["Reference"]

    key_frames: list[pd.DataFrame] = []
    if isinstance(demand_table, pd.DataFrame) and not demand_table.empty:
        key_frames.append(
            demand_table[["economy", "scenario", "esto_product", "year"]].copy()
        )

    def _expand_non_scenario_keys(table: pd.DataFrame | None, table_name: str) -> None:
        if not isinstance(table, pd.DataFrame) or table.empty:
            return
        required = ["economy", "esto_product", "year"]
        missing = [column for column in required if column not in table.columns]
        if missing:
            raise KeyError(
                f"{table_name} is missing required reconciliation columns: {missing}"
            )
        base = table[["economy", "esto_product", "year"]].drop_duplicates().copy()
        if base.empty:
            return
        scenario_df = pd.DataFrame({"scenario": scenario_values})
        base["__tmp_key"] = 1
        scenario_df["__tmp_key"] = 1
        expanded = (
            base.merge(scenario_df, on="__tmp_key", how="inner")
            .drop(columns=["__tmp_key"])
            .loc[:, key_columns]
        )
        key_frames.append(expanded)

    _expand_non_scenario_keys(transformation_table, "transformation_table")
    _expand_non_scenario_keys(supply_projection_table, "supply_projection_table")
    _expand_non_scenario_keys(supply_primary_table, "supply_primary_table")

    if not key_frames:
        return pd.DataFrame(columns=key_columns)

    merged = (
        pd.concat(key_frames, ignore_index=True)
        .drop_duplicates(subset=key_columns, keep="first")
        .reset_index(drop=True)
    )
    if isinstance(demand_table, pd.DataFrame) and not demand_table.empty:
        demand_cols = ["economy", "scenario", "esto_product", "year", "demand_value", "demand_source"]
        demand_merge = demand_table.reindex(columns=demand_cols).copy()
    else:
        demand_merge = pd.DataFrame(columns=["economy", "scenario", "esto_product", "year", "demand_value", "demand_source"])
    merged = merged.merge(
        demand_merge,
        on=["economy", "scenario", "esto_product", "year"],
        how="left",
    )
    merged = merged.merge(
        transformation_table,
        on=["economy", "esto_product", "year"],
        how="left",
    ).merge(
        supply_projection_table,
        on=["economy", "esto_product", "year"],
        how="left",
    )
    if isinstance(supply_primary_table, pd.DataFrame) and not supply_primary_table.empty:
        merged = merged.merge(
            supply_primary_table,
            on=["economy", "esto_product", "year"],
            how="left",
        )
    if isinstance(supply_constraints, pd.DataFrame) and not supply_constraints.empty:
        merged = merged.merge(
            supply_constraints,
            on=["economy", "scenario", "esto_product", "year"],
            how="left",
        )
    if isinstance(transformation_constraints, pd.DataFrame) and not transformation_constraints.empty:
        merged = merged.merge(
            transformation_constraints,
            on=["economy", "scenario", "esto_product", "year"],
            how="left",
        )
    if "demand_source" not in merged.columns:
        merged["demand_source"] = "none"
    merged["demand_source"] = merged["demand_source"].fillna("none").astype(str)

    for column in [
        "demand_value",
        "transformation_output",
        "transformation_input",
        "transformation_losses",
        "projected_imports",
        "projected_exports",
        "projected_net_imports",
        "production",
        "stock_changes",
    ]:
        if column not in merged.columns:
            merged[column] = 0.0
        merged[column] = pd.to_numeric(merged[column], errors="coerce").fillna(0.0)
    for column in [
        "max_imports",
        "max_exports",
        "max_production",
        "max_transformation_output",
    ]:
        if column not in merged.columns:
            merged[column] = pd.NA
        merged[column] = pd.to_numeric(merged[column], errors="coerce")

    max_transformation_output = merged["max_transformation_output"].where(
        merged["max_transformation_output"].notna(),
        float("inf"),
    )
    max_production = merged["max_production"].where(
        merged["max_production"].notna(),
        float("inf"),
    )
    merged["constrained_transformation_output"] = merged["transformation_output"].clip(lower=0.0).where(
        merged["transformation_output"] <= max_transformation_output,
        max_transformation_output,
    )
    merged["constrained_production"] = merged["production"].clip(lower=0.0).where(
        merged["production"] <= max_production,
        max_production,
    )

    merged["required_net_imports"] = (
        pd.to_numeric(merged["demand_value"], errors="coerce").fillna(0.0)
        + merged["transformation_input"]
        + merged["transformation_losses"]
        - merged["constrained_transformation_output"]
        - merged["constrained_production"]
        - merged["stock_changes"]
    )
    merged["trade_adjustment"] = (
        merged["required_net_imports"] - merged["projected_net_imports"]
    )
    merged["uncapped_adjusted_imports"] = (
        merged["projected_imports"] + merged["trade_adjustment"].clip(lower=0.0)
    )
    merged["uncapped_adjusted_exports"] = (
        merged["projected_exports"] + (-merged["trade_adjustment"]).clip(lower=0.0)
    )
    max_imports = merged["max_imports"].where(merged["max_imports"].notna(), float("inf"))
    max_exports = merged["max_exports"].where(merged["max_exports"].notna(), float("inf"))
    merged["adjusted_imports"] = merged["uncapped_adjusted_imports"].clip(lower=0.0).where(
        merged["uncapped_adjusted_imports"] <= max_imports,
        max_imports,
    )
    merged["adjusted_exports"] = merged["uncapped_adjusted_exports"].clip(lower=0.0).where(
        merged["uncapped_adjusted_exports"] <= max_exports,
        max_exports,
    )
    merged["imports_cap_binding"] = (
        merged["uncapped_adjusted_imports"] - merged["adjusted_imports"]
    ).clip(lower=0.0)
    merged["exports_cap_binding"] = (
        merged["uncapped_adjusted_exports"] - merged["adjusted_exports"]
    ).clip(lower=0.0)
    merged["adjusted_net_imports"] = (
        merged["adjusted_imports"] - merged["adjusted_exports"]
    )
    merged["adjusted_balance"] = (
        merged["adjusted_net_imports"]
        + merged["constrained_transformation_output"]
        + merged["constrained_production"]
        + merged["stock_changes"]
        - merged["transformation_input"]
        - merged["transformation_losses"]
        - pd.to_numeric(merged["demand_value"], errors="coerce").fillna(0.0)
    )
    return merged.sort_values(
        ["economy", "scenario", "esto_product", "year"]
    ).reset_index(drop=True)


def build_transformation_trade_target_rows(
    economies: Iterable[str] | None = None,
    base_year: int = BASE_YEAR,
    final_year: int = FINAL_YEAR,
    process_records: list[dict] | None = None,
) -> tuple[pd.DataFrame, list[dict]]:
    """Return process-level transformation import/export target rows."""
    label_to_product = _build_label_to_esto_product_lookup()
    records = process_records if process_records is not None else transformation_workflow.collect_transformation_rows(economies=economies)
    rows: list[dict[str, object]] = []
    for record_index, record in enumerate(records):
        economy = str(record.get("economy") or "").strip()
        sector_title = str(record.get("sector_title") or "").strip()
        process_name = str(record.get("process_name") or "").strip()
        if not economy:
            continue
        for label, year, value in _iter_year_value_items(
            record.get("output_import_targets"),
            base_year,
            final_year,
        ):
            product = label_to_product.get(label) or label_to_product.get(label.lower())
            if not product:
                continue
            rows.append(
                {
                    "record_index": int(record_index),
                    "economy": economy,
                    "sector_title": sector_title,
                    "process_name": process_name,
                    "direction": "import",
                    "label": str(label),
                    "esto_product": str(product),
                    "year": int(year),
                    "value": max(float(value), 0.0),
                }
            )
        for label, year, value in _iter_year_value_items(
            record.get("output_export_targets"),
            base_year,
            final_year,
        ):
            product = label_to_product.get(label) or label_to_product.get(label.lower())
            if not product:
                continue
            rows.append(
                {
                    "record_index": int(record_index),
                    "economy": economy,
                    "sector_title": sector_title,
                    "process_name": process_name,
                    "direction": "export",
                    "label": str(label),
                    "esto_product": str(product),
                    "year": int(year),
                    "value": max(float(value), 0.0),
                }
            )
    if not rows:
        return pd.DataFrame(
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
        ), records
    return pd.DataFrame(rows), records


def apply_trade_split_between_transformation_and_supply(
    reconciliation_table: pd.DataFrame,
    transformation_target_rows: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Split gross imports/exports into transformation targets and supply residuals."""
    if reconciliation_table.empty:
        return reconciliation_table.copy()
    merged = reconciliation_table.copy()
    for required in ["projected_imports", "projected_exports", "adjusted_imports", "adjusted_exports"]:
        if required not in merged.columns:
            merged[required] = 0.0
        merged[required] = pd.to_numeric(merged[required], errors="coerce").fillna(0.0)

    if isinstance(transformation_target_rows, pd.DataFrame) and not transformation_target_rows.empty:
        totals = (
            transformation_target_rows.groupby(
                ["economy", "esto_product", "year", "direction"],
                dropna=False,
                as_index=False,
            )["value"]
            .sum(min_count=1)
        )
        import_totals = totals[totals["direction"] == "import"].rename(
            columns={"value": "baseline_transformation_import_target"}
        )[["economy", "esto_product", "year", "baseline_transformation_import_target"]]
        export_totals = totals[totals["direction"] == "export"].rename(
            columns={"value": "baseline_transformation_export_target"}
        )[["economy", "esto_product", "year", "baseline_transformation_export_target"]]
        merged = merged.merge(
            import_totals,
            on=["economy", "esto_product", "year"],
            how="left",
        ).merge(
            export_totals,
            on=["economy", "esto_product", "year"],
            how="left",
        )
    else:
        merged["baseline_transformation_import_target"] = 0.0
        merged["baseline_transformation_export_target"] = 0.0

    for column in [
        "baseline_transformation_import_target",
        "baseline_transformation_export_target",
    ]:
        merged[column] = pd.to_numeric(merged.get(column), errors="coerce").fillna(0.0)

    projected_imports = merged["projected_imports"].clip(lower=0.0)
    projected_exports = merged["projected_exports"].clip(lower=0.0)
    import_share = (
        merged["baseline_transformation_import_target"] / projected_imports.where(projected_imports > 0.0, pd.NA)
    ).fillna(0.0).clip(lower=0.0, upper=1.0)
    export_share = (
        merged["baseline_transformation_export_target"] / projected_exports.where(projected_exports > 0.0, pd.NA)
    ).fillna(0.0).clip(lower=0.0, upper=1.0)

    merged["transformation_import_share"] = import_share
    merged["transformation_export_share"] = export_share
    merged["transformation_import_target"] = (
        merged["adjusted_imports"].clip(lower=0.0) * merged["transformation_import_share"]
    ).clip(lower=0.0)
    merged["transformation_export_target"] = (
        merged["adjusted_exports"].clip(lower=0.0) * merged["transformation_export_share"]
    ).clip(lower=0.0)
    merged["supply_imports_residual"] = (
        merged["adjusted_imports"] - merged["transformation_import_target"]
    ).clip(lower=0.0)
    merged["supply_exports_residual"] = (
        merged["adjusted_exports"] - merged["transformation_export_target"]
    ).clip(lower=0.0)
    merged["combined_net_imports_after_split"] = (
        merged["supply_imports_residual"]
        + merged["transformation_import_target"]
        - merged["supply_exports_residual"]
        - merged["transformation_export_target"]
    )
    return merged


def build_supply_overrides(reconciliation_table: pd.DataFrame) -> dict[str, dict[str, dict[str, dict[str, dict[int, float]]]]]:
    """Convert the reconciliation table into supply override payloads."""
    overrides: dict[str, dict[str, dict[str, dict[str, dict[int, float]]]]] = {}
    if reconciliation_table.empty:
        return overrides
    use_legacy_split = _use_legacy_trade_split_mode()
    use_output_share_supply_exports = _use_output_share_supply_exports_mode()
    use_capacity_unmet_iterative = _use_capacity_unmet_iterative_mode()
    use_capacity_unmet_balanced = _use_capacity_unmet_iterative_balanced_mode()
    balanced_baseline_seed_mode = (
        use_capacity_unmet_balanced and _is_capacity_unmet_baseline_seed_pass()
    )
    for _, row in reconciliation_table.iterrows():
        economy = str(row["economy"])
        scenario = str(row["scenario"])
        product = str(row["esto_product"])
        year = int(row["year"])
        product_bucket = (
            overrides.setdefault(economy, {})
            .setdefault(scenario, {})
            .setdefault(product, {"imports": {}, "exports": {}})
        )
        if use_legacy_split:
            imports_value = row.get("supply_imports_residual", row.get("adjusted_imports", 0.0))
            exports_value = row.get("supply_exports_residual", row.get("adjusted_exports", 0.0))
        elif use_output_share_supply_exports or use_capacity_unmet_iterative:
            # Keep explicit exports on supply branches to align with trade projections,
            # while leaving imports at zero so LEAP can auto-balance imports.
            imports_value = 0.0
            exports_value = row.get("adjusted_exports", row.get("projected_exports", 0.0))
        elif use_capacity_unmet_balanced:
            # Always keep imports at zero in iterative-balanced mode.
            # baseline_seed/results_update differences only affect export
            # adjustments and whether runtime residual allocations are applied.
            imports_value = 0.0
            if CAPACITY_UNMET_PIN_EXPORTS_TO_9TH_PROJECTIONS:
                # Keep exports anchored to 9th trade projections in iterative-balanced mode.
                exports_value = row.get("projected_exports", 0.0)
            else:
                exports_value = row.get("adjusted_exports", row.get("projected_exports", 0.0))
                if not balanced_baseline_seed_mode:
                    exports_value = float(exports_value) + _lookup_runtime_export_adjustment(
                        economy=economy,
                        scenario=scenario,
                        esto_product=product,
                        year=year,
                    )
        else:
            # Capacity-constrained mode (and other non-legacy modes) writes zeros
            # so stale LEAP trade values are explicitly cleared during import.
            imports_value = 0.0
            exports_value = 0.0
        product_bucket["imports"][year] = max(float(imports_value), 0.0)
        product_bucket["exports"][year] = max(float(exports_value), 0.0)
        if use_capacity_unmet_balanced:
            primary_add = 0.0
            if not balanced_baseline_seed_mode:
                primary_add = _lookup_runtime_primary_addition(
                    economy=economy,
                    scenario=scenario,
                    esto_product=product,
                    year=year,
                )
            base_production = pd.to_numeric(row.get("constrained_production"), errors="coerce")
            base_production_value = 0.0 if pd.isna(base_production) else max(float(base_production), 0.0)
            production_target = max(base_production_value + float(primary_add), 0.0)
            max_production_value = pd.to_numeric(row.get("max_production"), errors="coerce")
            if pd.isna(max_production_value):
                max_production_target = production_target
            else:
                max_production_target = max(float(max_production_value), production_target)
            product_bucket.setdefault("max_production", {})
            product_bucket["max_production"][year] = float(max_production_target)
    return overrides


def reset_supply_and_transformation_import_export_to_zero(
    reconciliation_table: pd.DataFrame,
    transformation_process_records: list[dict] | None = None,
    *,
    economies: Iterable[str] | None = None,
    scenarios: Iterable[str] | None = None,
    sector_titles: Iterable[str] | None = None,
    esto_products: Iterable[str] | None = None,
    years: Iterable[int] | None = None,
) -> tuple[pd.DataFrame, list[dict] | None]:
    """
    Zero supply/transformation import-export values for selected scopes.

    Filters are optional and combined with logical AND when provided.
    When a filter is omitted, it is expanded to the full available set from the
    provided reconciliation/process data.
    - `reconciliation_table` columns are zeroed for matched rows.
    - `transformation_process_records` output import/export targets are zeroed for
      matched process records and target fuels.
    """
    if not isinstance(reconciliation_table, pd.DataFrame):
        raise TypeError("reconciliation_table must be a pandas DataFrame")

    def _norm_set(values: Iterable[str] | None) -> set[str]:
        if not values:
            return set()
        return {
            str(item).strip().lower()
            for item in values
            if str(item or "").strip()
        }

    def _resolve_product_filter_set(values: Iterable[str] | None) -> set[str]:
        """Resolve mixed fuel labels/codes into reconciliation esto_product tokens."""
        raw_values = [
            str(item).strip()
            for item in (values or [])
            if str(item or "").strip()
        ]
        if not raw_values:
            return set()
        lookup = _build_label_to_esto_product_lookup()
        resolved: set[str] = set()
        for token in raw_values:
            mapped = (
                lookup.get(token)
                or lookup.get(token.lower())
                or lookup.get(_normalize_label_for_lookup(token))
            )
            if mapped:
                resolved.add(str(mapped).strip())
            else:
                # Keep caller-provided raw token to support direct esto_product inputs.
                resolved.add(token)
        return resolved

    economy_set = _norm_set(economies)
    scenario_set = _norm_set(scenarios)
    configured_modules = sorted(_configured_reset_module_names())
    configured_fuels = _configured_reset_fuel_labels()
    sector_set = _norm_set(sector_titles or configured_modules)
    product_set = _resolve_product_filter_set(esto_products or configured_fuels)
    year_set = {
        int(item)
        for item in (years or [])
    }

    # Expand omitted filters to explicit "all available" sets.
    if not economy_set and "economy" in reconciliation_table.columns:
        economy_set = {
            str(item).strip().lower()
            for item in reconciliation_table["economy"].dropna().astype(str).tolist()
            if str(item).strip()
        }
    if not scenario_set and "scenario" in reconciliation_table.columns:
        scenario_set = {
            str(item).strip().lower()
            for item in reconciliation_table["scenario"].dropna().astype(str).tolist()
            if str(item).strip()
        }
    if not product_set and "esto_product" in reconciliation_table.columns:
        product_set = {
            str(item).strip()
            for item in reconciliation_table["esto_product"].dropna().astype(str).tolist()
            if str(item).strip()
        }
    if not year_set and "year" in reconciliation_table.columns:
        year_values = pd.to_numeric(reconciliation_table["year"], errors="coerce").dropna()
        year_set = {int(item) for item in year_values.tolist()}

    updated_reconciliation = reconciliation_table.copy()
    mask = pd.Series(True, index=updated_reconciliation.index)
    if economy_set and "economy" in updated_reconciliation.columns:
        mask &= updated_reconciliation["economy"].astype(str).str.strip().str.lower().isin(economy_set)
    if scenario_set and "scenario" in updated_reconciliation.columns:
        mask &= updated_reconciliation["scenario"].astype(str).str.strip().str.lower().isin(scenario_set)
    if product_set and "esto_product" in updated_reconciliation.columns:
        product_values = updated_reconciliation["esto_product"].astype(str).str.strip()
        product_mask = product_values.isin(product_set)
        normalized_product_set = {
            _normalize_esto_product_for_match(item)
            for item in product_set
            if _normalize_esto_product_for_match(item)
        }
        if normalized_product_set:
            product_mask |= product_values.map(_normalize_esto_product_for_match).isin(
                normalized_product_set
            )
        mask &= product_mask
    if year_set and "year" in updated_reconciliation.columns:
        year_values = pd.to_numeric(updated_reconciliation["year"], errors="coerce").astype("Int64")
        mask &= year_values.isin(year_set)

    reconciliation_zero_columns = [
        "projected_imports",
        "projected_exports",
        "projected_net_imports",
        "trade_adjustment",
        "required_net_imports",
        "uncapped_adjusted_imports",
        "uncapped_adjusted_exports",
        "adjusted_imports",
        "adjusted_exports",
        "adjusted_net_imports",
        "imports_cap_binding",
        "exports_cap_binding",
        "baseline_transformation_import_target",
        "baseline_transformation_export_target",
        "transformation_import_target",
        "transformation_export_target",
        "supply_imports_residual",
        "supply_exports_residual",
        "combined_net_imports_after_split",
    ]
    for column in reconciliation_zero_columns:
        if column in updated_reconciliation.columns:
            updated_reconciliation.loc[mask, column] = 0.0

    if transformation_process_records is None:
        return updated_reconciliation, None

    label_to_product = _build_label_to_esto_product_lookup()
    updated_records = copy.deepcopy(transformation_process_records)

    if not economy_set:
        economy_set = {
            str(record.get("economy") or "").strip().lower()
            for record in updated_records
            if str(record.get("economy") or "").strip()
        }
    if not sector_set:
        sector_set = {
            str(record.get("sector_title") or "").strip().lower()
            for record in updated_records
            if str(record.get("sector_title") or "").strip()
        }
    if not product_set:
        derived_products: set[str] = set()
        for record in updated_records:
            for payload_key in (
                "output_values",
                "feedstock_values",
                "loss_values",
                "output_import_targets",
                "output_export_targets",
            ):
                payload = record.get(payload_key)
                if not isinstance(payload, dict):
                    continue
                for label in payload.keys():
                    token = str(label or "").strip()
                    if not token:
                        continue
                    mapped = label_to_product.get(token) or label_to_product.get(token.lower())
                    if mapped:
                        derived_products.add(str(mapped).strip())
        product_set = derived_products

    target_years = tuple(sorted(year_set)) if year_set else tuple(range(BASE_YEAR, FINAL_YEAR + 1))

    def _record_matches(record: dict) -> bool:
        if economy_set:
            economy_value = str(record.get("economy") or "").strip().lower()
            if economy_value not in economy_set:
                return False
        if sector_set:
            sector_value = str(record.get("sector_title") or "").strip().lower()
            if sector_value not in sector_set:
                return False
        return True

    def _labels_for_product_filter(target_map: dict) -> list[str]:
        labels: list[str] = []
        for label in target_map.keys():
            token = str(label or "").strip()
            if not token:
                continue
            if not product_set:
                labels.append(token)
                continue
            mapped = label_to_product.get(token) or label_to_product.get(token.lower())
            if mapped in product_set:
                labels.append(token)
        return labels

    for record in updated_records:
        if not _record_matches(record):
            continue
        for key in ("output_import_targets", "output_export_targets"):
            target_map = record.get(key)
            if not isinstance(target_map, dict):
                continue
            for label in _labels_for_product_filter(target_map):
                year_values = target_map.get(label)
                if isinstance(year_values, dict):
                    for year in target_years:
                        year_int = int(year)
                        year_values[year_int] = 0.0
                        year_values[str(year_int)] = 0.0
                else:
                    target_map[label] = {int(year): 0.0 for year in target_years}

    return updated_reconciliation, updated_records


