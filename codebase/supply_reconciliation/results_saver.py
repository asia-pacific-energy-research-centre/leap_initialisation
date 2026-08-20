from __future__ import annotations

import concurrent.futures
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

from codebase.supply_reconciliation.config import *  # noqa: F401,F403
from codebase.supply_reconciliation.config import (
    ReconciliationRunContext,
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
from codebase.utilities.fuel_catalog_preflight import (
    LEGACY_FUEL_CATALOG_PATH,
    build_incremental_template_catalog,
)
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
from codebase.functions.analysis_input_write_dispatcher import (
    get_analysis_input_write_mode,
    reset_is_effective,
)
from codebase.functions.baseline_seed_validation import (
    AGGREGATED_DEMAND_BRANCH_PREFIX,
    apply_template_ids,
    build_template_id_lookup,
    drop_zero_only_optional_unmatched_rows,
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
from codebase.utilities import leap_export_template_resolver
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
from codebase.utilities.typed_storage import (
    read_typed_cache_bundle,
    write_typed_cache_bundle_atomic,
)
from codebase.supply_reconciliation.utils import (
    _canonical_transformation_fuel_label,
    _load_code_to_name_table,
    _normalize_label_for_lookup,
    _normalize_esto_product_for_match,
    _build_label_to_esto_product_lookup,
    _iter_year_value_items,
    _sort_output_frame_for_csv,
    _normalize_template_header_value,
)
from codebase.supply_reconciliation.history import (
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
from codebase.supply_reconciliation.results import (
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
from codebase.supply_reconciliation.balance_tables import (
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
import codebase.supply_reconciliation.allocation as _sra
from codebase.supply_reconciliation import template_compatibility

from codebase.supply_reconciliation.preflight import (
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
from codebase.supply_reconciliation.demand_mapping import (
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
from codebase.supply_reconciliation.tables import (
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
from codebase.supply_reconciliation.leap_io import (
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
    build_supply_transformation_zeroing_workbooks,
    run_other_demand_zeroing_leap_import,
    run_results_linked_leap_import,
)
from codebase.functions.leap_excel_io import find_leap_header_row


def _resolve_parallel_economy_workers(value) -> int:
    """Return the effective per-economy worker count, refusing unsafe values.

    The ThreadPoolExecutor below shares this module's star-imported config
    globals across every worker, so two economies in flight at once would read
    each other's mirrored state and silently produce wrong seeds.  The dial is
    safe today only because it defaults to 0.  It stays refused until Phase 4
    B2/B3 replaces the mirrored globals with explicit state injection - see
    docs/work_queue.md [17] and docs/prompts/phase_5_feature_improvements_execution.md.
    """
    workers = int(value) if isinstance(value, int) and not isinstance(value, bool) else 0
    if workers > 1:
        raise RuntimeError(
            f"PARALLEL_ECONOMY_WORKERS={workers} is not supported. Per-economy "
            "parallelism shares mirrored module globals and would corrupt results "
            "with no error. Set it to 0 or 1 until Phase 4 B2/B3 state injection "
            "lands (docs/work_queue.md [17], "
            "docs/prompts/phase_5_feature_improvements_execution.md)."
        )
    return workers


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
        return find_leap_header_row(raw)

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
    probe_catalog_path: Path | str | None = None,
) -> pd.DataFrame:
    """Build the shared LEAP fuel-branch catalog dataframe.

    The public/private function name is retained for compatibility with the
    baseline and transfer callers. The canonical template union is now supplied
    by ``fuel_catalog_preflight``; generated transformation/supply exports and
    the live probe are additive sources for the current run.
    """
    rows: list[dict[str, object]] = []

    if USE_FULL_MODEL_EXPORT_CATALOG_SOURCE:
        template_catalog_df, _ = build_incremental_template_catalog(
            # The economy templates are the canonical branch source. The old
            # full-model export is a cross-economy union and must not seed rows
            # into an individual economy's producer workbook.
            full_model_export_path=None,
            full_model_sheet=FULL_MODEL_EXPORT_CATALOG_SHEET,
        )
        if not template_catalog_df.empty:
            rows.extend(template_catalog_df.to_dict("records"))
            print(
                f"[INFO] Added {len(template_catalog_df)} row(s) from shared LEAP template catalog union."
            )

    probe_path = _resolve(
        probe_catalog_path
        if probe_catalog_path is not None
        else LEAP_FUEL_BRANCH_PROBE_OUTPUT_PATH
    )
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


def _catalog_for_economy(
    catalog_df: pd.DataFrame,
    economy: str,
) -> pd.DataFrame:
    """Restrict producer zero-fill scaffolding to one economy's template."""
    if catalog_df is None or catalog_df.empty:
        return catalog_df
    if leap_export_template_resolver.is_aggregate_economy(economy):
        # Aggregate outputs have no single LEAP area. The catalog union of
        # economy templates is the correct scope for those outputs.
        return catalog_df
    try:
        template_path = leap_export_template_resolver.resolve_leap_export_template(
            economy,
            warn_on_provisional=False,
        )
        template_rows = _read_branch_variable_rows(template_path, sheet_name="Export")
        if template_rows.empty or "Branch Path" not in template_rows.columns:
            return catalog_df.iloc[0:0].copy()
        canonical_paths = {
            str(value).strip().casefold(): str(value).strip()
            for value in template_rows["Branch Path"].dropna()
            if str(value).strip()
        }
        filtered = catalog_df[
            catalog_df["branch_path"]
            .astype(str)
            .str.strip()
            .str.casefold()
            .isin(canonical_paths)
        ].copy()
        # The shared catalog is a union of every economy template, so a
        # case-insensitive match may carry another economy's spelling (for
        # example, ``Natural Gas`` into NZ where the branch is ``Natural gas``).
        # Adopt the target template's exact path before zero-fill and collapse
        # scenario/source repetitions to one structural fuel branch. The zero
        # builder supplies scenarios itself; retaining catalog repetitions here
        # creates duplicate share contributions.
        filtered["branch_path"] = (
            filtered["branch_path"]
            .astype(str)
            .str.strip()
            .str.casefold()
            .map(canonical_paths)
        )
        if "fuel_name" in filtered.columns:
            filtered["fuel_name"] = filtered["branch_path"].str.rsplit("\\", n=1).str[-1]
        structural_key = [
            column
            for column in ("catalog_type", "fuel_group", "branch_path")
            if column in filtered.columns
        ]
        if structural_key:
            filtered = filtered.drop_duplicates(subset=structural_key, keep="first")
        removed = len(catalog_df) - len(filtered)
        if removed:
            print(
                f"[INFO] Restricted producer branch catalog for {economy} to "
                f"{len(filtered)} structural template rows "
                f"(removed or collapsed {removed} union rows)."
            )
        return filtered
    except (FileNotFoundError, ValueError) as exc:
        raise FileNotFoundError(
            f"Cannot build producer branch catalog for {economy}: "
            "an economy-specific LEAP export template is required."
        ) from exc


def _build_transformation_supply_fuel_catalog(
    *,
    transformation_export_paths: Iterable[Path],
    supply_export_paths: Iterable[Path],
    output_dir: Path | str = RESULTS_CHECKS_DIR,
    probe_catalog_path: Path | str | None = None,
) -> Path:
    """Build and save the canonical LEAP fuel-branch catalog.

    The legacy filename is written beside the canonical file until all external
    readers have migrated.
    """
    output_path = _resolve(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    catalog_path = output_path / "leap_fuel_branch_catalog.csv"
    legacy_catalog_path = output_path / Path(LEGACY_FUEL_CATALOG_PATH).name
    catalog_df = _build_transformation_supply_fuel_catalog_df(
        transformation_export_paths=transformation_export_paths,
        supply_export_paths=supply_export_paths,
        include_print_summary=True,
        probe_catalog_path=probe_catalog_path,
    )
    catalog_df.to_csv(catalog_path, index=False)
    if legacy_catalog_path != catalog_path:
        catalog_df.to_csv(legacy_catalog_path, index=False)
    print(f"[INFO] Wrote LEAP fuel-branch catalog to {catalog_path}")
    if legacy_catalog_path != catalog_path:
        print(f"[INFO] Wrote legacy compatibility copy to {legacy_catalog_path}")
    return catalog_path


def _resolve_results_saver_run_paths(
    run_context: ReconciliationRunContext | None,
) -> dict[str, Path]:
    """Resolve this runner's paths from an explicit context or legacy globals.

    The optional context is the B3 boundary.  Preflight still applies temporary
    module overrides directly, so callers without a context retain precisely the
    established global-path behaviour while that path is migrated separately.
    """
    if run_context is None:
        return {
            "output_dir": Path(OUTPUT_DIR),
            "export_dir": _resolve(EXPORT_OUTPUT_DIR),
            "transformation_export_dir": _resolve(TRANSFORMATION_EXPORT_OUTPUT_DIR),
            "yearly_balance_dir": _resolve(YEARLY_BALANCE_DIR),
            "conventional_balance_dir": _resolve(CONVENTIONAL_BALANCE_DIR),
            "runtime_dir": _resolve(RESULTS_RUNTIME_DIR),
            "checks_dir": _resolve(RESULTS_CHECKS_DIR),
            "state_path": _resolve(CAPACITY_UNMET_STATE_PATH),
            "probe_catalog_path": _resolve(LEAP_FUEL_BRANCH_PROBE_OUTPUT_PATH),
        }
    return {
        "output_dir": Path(run_context.output_dir),
        "export_dir": Path(run_context.export_output_dir),
        "transformation_export_dir": Path(run_context.transformation_export_output_dir),
        "yearly_balance_dir": Path(run_context.yearly_balance_dir),
        "conventional_balance_dir": Path(run_context.conventional_balance_dir),
        "runtime_dir": Path(run_context.results_runtime_dir),
        "checks_dir": Path(run_context.results_checks_dir),
        "state_path": Path(run_context.capacity_unmet_state_path),
        "probe_catalog_path": Path(run_context.leap_fuel_branch_probe_output_path),
    }


def _build_capacity_allocation_process_records(
    transformation_process_records: list[dict],
    *,
    economies: Iterable[str],
    include_power_interim: bool,
) -> list[dict]:
    """Return every transformation record eligible for capacity allocation.

    Power interim records are produced by a separate workbook workflow, so they
    are not part of ``transformation_process_records``. Include them explicitly
    here so electricity and heat residuals can use the same capacity allocator
    as the other transformation modules.
    """
    records = list(transformation_process_records)
    if include_power_interim:
        records.extend(
            electricity_heat_interim_workflow.build_electricity_heat_interim_rows(
                economies=list(economies)
            )
        )
    return records


TRANSFORMATION_SUPPLY_CACHE_SCHEMA_VERSION = 2


def _validate_scenario_aware_supply_cache(cache_payload: dict) -> dict:
    """Reject pre-fix cache bundles that could copy Reference into Target."""
    for table_name in ("supply_projection_table", "supply_primary_table"):
        table = cache_payload.get(table_name)
        if not isinstance(table, pd.DataFrame) or "scenario" not in table.columns:
            raise ValueError(
                f"Stale scenario-less {table_name} cannot be reused."
            )
    lookups = cache_payload.get("supply_projection_lookups_by_scenario")
    if not isinstance(lookups, dict) or "Target" not in lookups:
        raise ValueError("Stale supply cache has no Target projection lookup.")
    return lookups


def run_results_linked_transformation_supply_workflow(
    economies: Iterable[str] | None = None,
    scenario_names: list[str] | None = None,
    export_dataset_key: str = EXPORT_DATASET_KEY,
    include_leap_import: bool | None = None,
    import_scenarios: Iterable[str] | str | None = LEAP_IMPORT_SCENARIOS,
    use_direct_leap_results_for_demand: bool | None = None,
    scrape_leap_results: bool | None = None,
    run_context: ReconciliationRunContext | None = None,
) -> dict[str, object]:
    """Build reconciled transformation + supply exports driven by LEAP balance demand results."""
    run_paths = _resolve_results_saver_run_paths(run_context)
    output_dir = run_paths["output_dir"]
    export_dir = run_paths["export_dir"]
    transformation_export_dir = run_paths["transformation_export_dir"]
    yearly_balance_dir = run_paths["yearly_balance_dir"]
    conventional_balance_dir = run_paths["conventional_balance_dir"]
    runtime_dir = run_paths["runtime_dir"]
    checks_dir = run_paths["checks_dir"]
    state_path = run_paths["state_path"]
    probe_catalog_path = run_paths["probe_catalog_path"]
    runtime_dir.mkdir(parents=True, exist_ok=True)
    from codebase.utilities.master_config import OUTLOOK_MAPPINGS_MASTER_SELECTION

    mapping_selection_manifest_path = runtime_dir / "mapping_workbook_selection.json"
    mapping_selection_manifest_path.write_text(
        json.dumps(
            OUTLOOK_MAPPINGS_MASTER_SELECTION.as_manifest_record(),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    timer = workflow_common.WorkflowTimer("supply_reconciliation", enabled=ENABLE_WORKFLOW_TIMING)
    timing_path = runtime_dir / WORKFLOW_TIMING_FILENAME
    allocation_ledger = _sra._reset_capacity_unmet_allocation_ledger()
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
    if (
        not balance_scenario_list
        and _is_capacity_unmet_baseline_seed_pass()
        and any(
            str(scenario or "").strip().lower()
            in {"current accounts", "current account"}
            for scenario in scenario_list
        )
    ):
        # Current Accounts is a base-year export scenario rather than a LEAP
        # balance/projection scenario. The baseline workflow still needs one
        # projection scenario internally to assemble its reconciliation tables.
        # Reference is the established fallback used when Current Accounts
        # records consume those tables; only the requested Current Accounts rows
        # are written to the final seed.
        balance_scenario_list = ["Reference"]
        print(
            "[INFO] Current Accounts-only baseline seed: using Reference "
            "internally for balance/reconciliation inputs while exporting only "
            "Current Accounts."
        )
    economy_list = workflow_common.normalize_economies(economies or ECONOMIES)
    template_compatibility_by_economy, template_compatibility_audit_path = (
        template_compatibility.write_template_compatibility_audit(
            economy_list,
            runtime_dir / "template_compatibility_audit.csv",
        )
    )
    timer.set_metadata(
        economies=economy_list,
        scenarios=export_scenario_list,
        year_start=int(BASE_YEAR),
        year_end=int(FINAL_YEAR),
        n_years=len(range(int(BASE_YEAR), int(FINAL_YEAR) + 1)),
    )
    _print_reset_mode_reminder(
        run_economies=economy_list,
        run_scenarios=export_scenario_list,
    )
    timer.lap("setup")
    _bd_cache_hit = False
    if TRANSFORMATION_SUPPLY_CACHE_ENABLED:
        import hashlib as _hashlib, json as _json
        _bd_cache_dir = runtime_dir / "balance_demand_cache"
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
        _bd_cache_file = _bd_cache_dir / f"{_bd_cache_key}.parquet_cache"
        if _bd_cache_file.exists():
            try:
                _bd = read_typed_cache_bundle(_bd_cache_file)
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
                write_typed_cache_bundle_atomic({
                    "comparison_long_df": comparison_long_df,
                    "mapping_status_df": mapping_status_df,
                    "balance_demand_issues": balance_demand_issues,
                    "balance_matching_diagnostics": balance_matching_diagnostics,
                    "sector_demand_table": sector_demand_table,
                    "demand_table": demand_table,
                }, _bd_cache_file)
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
        checks_dir / "supply_reconciliation_balance_demand_conservation.parquet",
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
        balance_demand_breakdown_path = write_balance_demand_conservation_table(
            balance_demand_breakdown,
            checks_dir / "supply_reconciliation_balance_demand_conservation_breakdown.parquet",
        )
        balance_demand_lineage_path = write_balance_demand_conservation_table(
            balance_demand_lineage,
            checks_dir / "supply_reconciliation_balance_demand_conservation_lineage.parquet",
        )
        print(
            "[INFO] Wrote balance-demand breakdown and lineage prototypes: "
            f"{balance_demand_breakdown_path}, {balance_demand_lineage_path}."
        )
    except Exception as exc:
        print(f"[WARN] Balance-demand breakdown/lineage prototype could not run: {exc}")
    _ts_cache_hit = False
    if TRANSFORMATION_SUPPLY_CACHE_ENABLED:
        import hashlib as _hashlib, json as _json
        _ts_cache_dir = runtime_dir / "transform_supply_cache"
        _ts_cache_dir.mkdir(parents=True, exist_ok=True)
        _config_dir = REPO_ROOT / "config"
        _config_mtimes = {
            f.name: f.stat().st_mtime
            for f in sorted(_config_dir.glob("*"))
            if f.is_file()
        } if _config_dir.exists() else {}
        # The canonical mapping workbook lives in the leap_mappings repo, so a
        # mapping edit must invalidate this cache too — the cached assets embed
        # sector_config/code_to_name_mapping derived from it.
        from codebase.utilities.master_config import OUTLOOK_MAPPINGS_MASTER_PATH as _mappings_master
        if _mappings_master.exists():
            _config_mtimes["__outlook_mappings_master__"] = _mappings_master.stat().st_mtime
        _ts_key_payload = _json.dumps({
            "supply_scenario_schema": TRANSFORMATION_SUPPLY_CACHE_SCHEMA_VERSION,
            "economies": sorted(economy_list),
            "scenarios": sorted(balance_scenario_list),
            "dataset_key": str(export_dataset_key),
            "config_mtimes": _config_mtimes,
        }, sort_keys=True)
        _ts_cache_key = _hashlib.md5(_ts_key_payload.encode()).hexdigest()[:16]
        _ts_cache_file = _ts_cache_dir / f"{_ts_cache_key}.parquet_cache"
        if _ts_cache_file.exists():
            try:
                _ts = read_typed_cache_bundle(_ts_cache_file)
                transformation_table = _ts["transformation_table"]
                transformation_sector_table = _ts["transformation_sector_table"]
                transformation_target_rows = _ts["transformation_target_rows"]
                transformation_process_records = _ts["transformation_process_records"]
                supply_projection_table = _ts["supply_projection_table"]
                supply_primary_table = _ts["supply_primary_table"]
                supply_projection_lookups_by_scenario = (
                    _validate_scenario_aware_supply_cache(_ts)
                )
                supply_data_pipeline.SUPPLY_PROJECTION_LOOKUPS_BY_SCENARIO = (
                    supply_projection_lookups_by_scenario
                )
                supply_data_pipeline.SUPPLY_PROJECTION_LOOKUP = (
                    supply_projection_lookups_by_scenario.get("Reference")
                )
                assets = _ts["assets"]
                supply_constraints = _ts["supply_constraints"]
                transformation_constraints = _ts["transformation_constraints"]
                _ts_cache_hit = True
                print(f"[INFO] Loaded transformation/supply inputs from cache (key={_ts_cache_key}).")
            except Exception as _cache_exc:
                print(f"[WARN] Could not load transformation/supply cache: {_cache_exc}. Recomputing.")
    if not _ts_cache_hit:
        transformation_table = build_transformation_balance_table(
            economies=economy_list,
            projection_scenarios=balance_scenario_list,
        )
        transformation_sector_table = build_transformation_sector_table(
            economies=economy_list,
            projection_scenarios=balance_scenario_list,
        )
        transformation_target_rows, transformation_process_records = build_transformation_trade_target_rows(
            economies=economy_list,
        )
        supply_projection_table, assets = prepare_projected_supply_table(
            economies=economy_list,
            dataset_key=export_dataset_key,
            scenarios=export_scenario_list,
        )
        supply_primary_table = prepare_supply_primary_table(
            assets,
            economies=economy_list,
            dataset_key=export_dataset_key,
            scenarios=export_scenario_list,
        )
        supply_constraints, transformation_constraints = load_leap_constraint_tables(
            template_paths=CONSTRAINT_TEMPLATE_PATHS,
            sheet_names=CONSTRAINT_TEMPLATE_SHEETS,
            economies=economy_list,
        )
        if TRANSFORMATION_SUPPLY_CACHE_ENABLED:
            try:
                write_typed_cache_bundle_atomic({
                    "transformation_table": transformation_table,
                    "transformation_sector_table": transformation_sector_table,
                    "transformation_target_rows": transformation_target_rows,
                    "transformation_process_records": transformation_process_records,
                    "supply_projection_table": supply_projection_table,
                    "supply_primary_table": supply_primary_table,
                    "supply_projection_lookups_by_scenario": (
                        supply_data_pipeline.SUPPLY_PROJECTION_LOOKUPS_BY_SCENARIO
                    ),
                    "assets": assets,
                    "supply_constraints": supply_constraints,
                    "transformation_constraints": transformation_constraints,
                }, _ts_cache_file)
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
                checks_dir
                / "supply_reconciliation_results_update_closure.csv",
            )
            mismatch_count = int(results_update_closure["is_mismatch"].sum())
            print(
                "[INFO] Wrote diagnostic-only results-update reconciliation closure check: "
                f"{results_update_closure_path} ({mismatch_count} mismatch row(s))."
            )
        except Exception as exc:
            print(f"[WARN] Results-update closure diagnostic could not run: {exc}")
    if RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT and not reset_is_effective(
        RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT
    ):
        # The reset is the *wipe* half of a wipe-then-fill pair whose fill half is
        # the LEAP API import pass (the `... or RUN_RESET_...` clauses further down,
        # and supply_leap_io's forced Current Accounts fill). With the API
        # decommissioned and analysis_write_mode == "workbook", nothing refills the
        # trade columns after they are zeroed, so running the wipe alone deletes
        # real export data instead of staging it for a refill: measured on 01_AUS,
        # 1,111,593 PJ of coal/LNG/crude exports zeroed with no replacement.
        # Printed loudly rather than skipped silently - a toggles line reading True
        # beside a reset that did not run is exactly what hid docs/work_queue.md [17].
        print(
            "[WARN] RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT=True but the LEAP "
            "import pass is disabled (analysis_write_mode is not 'api'). The reset is "
            "SKIPPED: it zeroes the trade columns that the import pass would refill, and "
            "without that pass it would delete real Import/Export values. See "
            "docs/work_queue.md [17]."
        )
    elif reset_is_effective(RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT):
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

    capacity_process_records = _build_capacity_allocation_process_records(
        transformation_process_records,
        economies=economy_list,
        include_power_interim=bool(RUN_ELECTRICITY_HEAT_INTERIM),
    )

    balance_paths = save_year_balance_tables(
        reconciliation_table,
        years=BALANCE_EXPORT_YEARS,
        output_dir=yearly_balance_dir,
        economies=economy_list,
        scenarios=balance_scenario_list,
    )
    balance_csv_paths = [path for path in balance_paths if Path(path).suffix.lower() == ".csv"]
    timer.lap("write yearly balance tables")

    if _use_capacity_unmet_iterative_mode():
        _sra._run_capacity_unmet_iterative_pass(
            reconciliation_table=reconciliation_table,
            process_records=capacity_process_records,
            economies=economy_list,
            scenarios=export_scenario_list,
            resolve_scenario_key=_resolve_reconciliation_scenario_key,
            results_dir=balance_csv_paths,
            state_path=state_path,
            allow_same_results_reuse=bool(CAPACITY_UNMET_ALLOW_SAME_RESULTS_REUSE),
            allocation_ledger=allocation_ledger,
        )
    elif _use_capacity_unmet_iterative_balanced_mode():
        if _is_capacity_unmet_baseline_seed_pass():
            seeded_state = _read_capacity_unmet_state(
                state_path=state_path,
                run_mode="baseline_seed",
            )
            seeded_state_path = _write_capacity_unmet_state(
                seeded_state, state_path=state_path
            )
            allocation_ledger.pass_summary = {
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "mode": "capacity_unmet_iterative_balanced",
                "pass_mode": "baseline_seed",
                "state_path": str(state_path),
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
            _sra._refresh_legacy_allocation_ledger_views(allocation_ledger)
            print(
                "[CAPACITY_UNMET_ITERATIVE_BALANCED] baseline_seed pass: "
                "skipping residual allocation and using imports=0 with baseline exports/capacity."
            )
        else:
            _sra._run_capacity_unmet_iterative_balanced_pass(
                reconciliation_table=reconciliation_table,
                process_records=capacity_process_records,
                economies=economy_list,
                scenarios=balance_scenario_list,
                resolve_scenario_key=_resolve_reconciliation_scenario_key,
                results_dir=balance_csv_paths,
                state_path=state_path,
                allow_same_results_reuse=bool(CAPACITY_UNMET_ALLOW_SAME_RESULTS_REUSE),
                allocation_ledger=allocation_ledger,
            )
    if _use_capacity_unmet_iterative_any_mode():
        timer.lap("capacity unmet handling")

    output_dir.mkdir(parents=True, exist_ok=True)
    balance_demand_issue_path: Path | None = None
    reconciliation_path: Path | None = None
    conventional_balance_paths: list[Path] = []
    if RESULTS_WRITE_LEGACY_SIDECAR_FILES:
        reconciliation_path = output_dir / RECONCILIATION_FILENAME
        reconciliation_table.to_csv(reconciliation_path, index=False)
        print(f"Saved reconciliation table to {reconciliation_path}")
        conventional_balance_paths = save_conventional_balance_tables(
            reconciliation_table,
            sector_demand_table,
            transformation_sector_table,
            supply_primary_table,
            assets[4],
            years=BALANCE_EXPORT_YEARS,
            output_dir=conventional_balance_dir,
            economies=economy_list,
            scenarios=balance_scenario_list,
        )
        timer.lap("write legacy sidecar outputs")

    try:
        overrides = build_supply_overrides(
            reconciliation_table,
            allocation_ledger=allocation_ledger,
        )
    except TypeError as exc:
        # Notebook/tests historically monkeypatch this wrapper seam with a
        # one-argument callable. Keep that public compatibility path while
        # the built-in producer receives the explicit run-owned ledger.
        if "allocation_ledger" not in str(exc):
            raise
        overrides = build_supply_overrides(reconciliation_table)
    dataset_map, sector_config, code_to_name_mapping, _, _ = assets
    supply_measures = _build_supply_measures_for_trade_mode()
    # Build catalog from static sources (LEAP probe + full-model export) so aux-fuel
    # branches not covered by the current run can be explicitly zeroed in LEAP.
    pre_run_catalog_df = _build_transformation_supply_fuel_catalog_df(
        transformation_export_paths=[],
        supply_export_paths=[],
        include_print_summary=False,
        probe_catalog_path=probe_catalog_path,
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
    timer.lap("prepare LEAP import workbook generation")

    def _run_one_economy(economy: str) -> dict:
        """Generate all export workbooks for one economy and return collected paths."""
        compatibility = template_compatibility_by_economy[economy]
        if SKIP_ECONOMIES_WITH_EXISTING_EXPORTS:
            _skip_combined = next(iter(sorted(
                export_dir.glob(
                    f"combined_supply_transformation*{economy}*.xlsx"
                )
            )), None)
            if _skip_combined is not None and _skip_combined.exists():
                print(f"[INFO] [{economy}] combined workbook already exists, skipping export generation.")
                _skip_supply = sorted(export_dir.glob(f"supply_leap_imports_{economy}*.xlsx"))
                _skip_trans = sorted(export_dir.glob(f"transformation_leap_imports_{economy}*.xlsx"))
                _skip_transfer = sorted(export_dir.glob(f"transfer_leap_imports_{economy}*.xlsx"))
                _skip_elec_heat = sorted(export_dir.glob(f"electricity_heat_interim_{economy}*.xlsx"))
                _skip_proxy_dir = (
                    output_dir
                    / "supporting_files"
                    / "other_loss_own_use_proxy"
                    / str(economy)
                )
                _skip_proxy = sorted(_skip_proxy_dir.glob(f"other_loss_own_use_proxy_{economy}*.xlsx"))
                _skip_agg_demand = sorted(export_dir.glob(f"aggregated_demand_{economy}*.xlsx"))
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
            projection_lookups_by_scenario=(
                supply_data_pipeline.SUPPLY_PROJECTION_LOOKUPS_BY_SCENARIO
            ),
            projection_years=supply_data_pipeline.PROJECTION_YEAR_RANGE,
            dataset_key=export_dataset_key,
            economies=[economy],
            scenario_names=export_scenario_list,
            base_year=BASE_YEAR,
            final_year=FINAL_YEAR,
            export_output_dir=export_dir,
            filename_template=EXPORT_FILENAME_TEMPLATE,
            flow_value_overrides_by_economy=overrides,
            supply_measures=supply_measures,
            keep_all_zero_rows=bool(KEEP_ALL_ZERO_SUPPLY_ROWS),
        )
        timer.lap(f"generate supply export workbook ({economy})")
        econ_process_records = [
            r for r in transformation_process_records
            if str(r.get("economy") or "").strip() == economy
        ]
        econ_transformation_paths = save_transformation_exports_with_split_targets(
            reconciliation_table,
            transformation_target_rows,
            econ_process_records,
            scenarios=export_scenario_list,
            output_dir=transformation_export_dir,
            filename_template=TRANSFORMATION_EXPORT_FILENAME_TEMPLATE,
            full_branch_catalog_df=(
                _catalog_for_economy(pre_run_catalog_df, economy)
                if not pre_run_catalog_df.empty else None
            ),
            records_by_scenario_out=transformation_records_by_scenario,
            allocation_ledger=allocation_ledger,
            green_electricity_display_name=str(
                compatibility["selected_green_electricity_label"]
            ),
        )
        timer.lap(f"generate transformation export workbook ({economy})")
        econ_transfer_paths = save_transfer_exports_with_supply_overrides(
            reconciliation_table,
            economies=[economy],
            scenarios=export_scenario_list,
            output_dir=transformation_export_dir,
            filename_template=transfers_workflow.EXPORT_FILENAME_TEMPLATE,
            full_branch_catalog_df=(
                _catalog_for_economy(pre_run_catalog_df, economy)
                if not pre_run_catalog_df.empty else None
            ),
            allocation_ledger=allocation_ledger,
        )
        timer.lap(f"generate transfer export workbook ({economy})")
        econ_dummy: list[Path] = []
        if RUN_ELECTRICITY_HEAT_INTERIM:
            econ_dummy = build_electricity_heat_interim_workbooks_for_results_supply(
                economies=[economy],
                scenarios=export_scenario_list,
                output_dir=export_dir,
                reconciliation_table=reconciliation_table,
                allocation_ledger=allocation_ledger,
                records_by_scenario_out=transformation_records_by_scenario,
            )
            timer.lap(f"generate electricity/heat interim workbook ({economy})")
        econ_combined_path = save_combined_supply_transformation_export(
            supply_export_paths=[path for _, path in econ_supply_paths],
            transformation_export_paths=econ_transformation_paths + econ_dummy,
            transfer_export_paths=econ_transfer_paths,
            output_dir=export_dir,
            filename_template=COMBINED_EXPORT_FILENAME_TEMPLATE,
            economy_label=economy,
            scenarios=export_scenario_list,
        )
        timer.lap(f"merge and write supply/transformation workbook ({economy})")
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
                output_root=output_dir / "supporting_files" / "other_loss_own_use_proxy",
            )
            timer.lap(f"generate other loss/own-use proxy workbook ({economy})")
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
                    output_dir=export_dir,
                    excluded_sectors=_effective_agg_demand_excluded,
                    use_sector_branches=bool(AGGREGATED_DEMAND_USE_SECTOR_BRANCHES),
                    nonenergy_sector_by_economy={
                        economy: str(compatibility["selected_nonenergy_sector"])
                    },
                )
                timer.lap(f"generate aggregated-demand workbook ({economy})")
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

    _n_workers = _resolve_parallel_economy_workers(PARALLEL_ECONOMY_WORKERS)
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

    timer.lap("complete per-economy LEAP import workbook generation")
    template_compatibility.warn_if_all_templates_support_preferred(
        template_compatibility_audit_path
    )

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
                            export_dir.glob(
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
                checks_dir
                / "supply_reconciliation_baseline_supply_source_preservation.csv",
            )
            baseline_supply_preservation_breakdown_path = write_supply_diagnostic(
                supply_breakdown,
                checks_dir
                / "supply_reconciliation_baseline_supply_source_preservation_breakdown.csv",
            )
            baseline_supply_preservation_lineage_path = write_supply_diagnostic(
                supply_lineage,
                checks_dir
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
                checks_dir
                / "supply_reconciliation_transformation_output_conservation.parquet",
            )
            transformation_output_conservation_breakdown_path = write_supply_diagnostic(
                transformation_breakdown,
                checks_dir
                / "supply_reconciliation_transformation_output_conservation_breakdown.parquet",
            )
            transformation_output_conservation_lineage_path = write_supply_diagnostic(
                transformation_lineage,
                checks_dir
                / "supply_reconciliation_transformation_output_conservation_lineage.parquet",
            )
            mismatch_count = int(transformation_totals["is_mismatch"].sum())
            print(
                "[INFO] Wrote diagnostic-only transformation output conservation check: "
                f"{transformation_output_conservation_path} ({mismatch_count} mismatch row(s))."
            )
        except Exception as exc:
            print(f"[WARN] Transformation output conservation diagnostic could not run: {exc}")
    timer.lap("write baseline export conservation diagnostics")
    supply_transformation_zeroing_paths: list[Path] = []
    if RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT and not reset_is_effective(
        RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT
    ):
        supply_transformation_zeroing_paths = build_supply_transformation_zeroing_workbooks(
            scenarios=export_scenario_list,
            economies=economy_list,
            output_dir=export_dir,
        )
        if supply_transformation_zeroing_paths:
            print(
                "[INFO] Supply/transformation zeroing workbook(s) written. Import these "
                "into LEAP before the main supply/transformation workbook(s)."
            )
        timer.lap("generate supply/transformation zeroing workbooks")
    demand_zeroing_paths: list[Path] = []
    if ZERO_OTHER_DEMAND_BRANCHES_FROM_EXPORT and USE_AGGREGATED_DEMAND_AS_DUMMY:
        demand_zeroing_paths = build_other_demand_zeroing_workbooks(
            scenarios=export_scenario_list,
            economies=economy_list,
            output_dir=export_dir,
            excluded_sectors=_effective_agg_demand_excluded,
            sector_map=LEAP_DEMAND_GROUP_ESTO_SECTOR_MAP,
        )
        timer.lap("generate demand zeroing workbooks")
    fuel_branch_catalog_df = _build_transformation_supply_fuel_catalog_df(
        transformation_export_paths=transformation_export_paths,
        supply_export_paths=[path for _, path in export_paths],
        include_print_summary=True,
        probe_catalog_path=probe_catalog_path,
    )
    timer.lap("build LEAP import fuel catalog")
    fuel_branch_catalog_path: Path | None = None
    if RESULTS_WRITE_LEGACY_SIDECAR_FILES:
        fuel_branch_catalog_path = _build_transformation_supply_fuel_catalog(
            transformation_export_paths=transformation_export_paths,
            supply_export_paths=[path for _, path in export_paths],
            output_dir=output_dir,
            probe_catalog_path=probe_catalog_path,
        )
    probe_catalog_path = probe_catalog_path if probe_catalog_path.exists() else None
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
        supply_workbook_dir=export_dir,
        aggregated_demand_dir=export_dir,
        output_dir=output_dir,
        # id_lookup_path is left unset so each economy resolves its own LEAP
        # export template; passing one path here applied a single area's
        # BranchIDs to every economy.
        excluded_sectors=_effective_agg_demand_excluded,
        use_sector_branches=bool(AGGREGATED_DEMAND_USE_SECTOR_BRANCHES),
        source_workbooks_by_workflow=baseline_seed_sources,
        required_years_by_scenario=baseline_seed_years_by_scenario,
        required_scenarios_by_source=baseline_seed_required_scenarios,
    )
    timer.lap("write per-economy combined workbooks")

    # A direct full workflow has one completion boundary.  Refresh materiality
    # only after seed assembly, and never in a parallel child: the parallel
    # runner owns that one shared-registry write after every worker exits.
    if not os.environ.get("LEAP_WORKER_SNAPSHOT_JSON"):
        from codebase.mapping_tools.missing_branch_registry_materiality_workflow import (
            refresh_missing_branch_registry_materiality,
        )

        try:
            refreshed_registry = refresh_missing_branch_registry_materiality()
            print(
                "[INFO] Missing-branch registry materiality refresh completed: "
                f"entries={len(refreshed_registry)}."
            )
            timer.lap("refresh missing-branch registry materiality")
        except Exception as exc:
            print(f"[WARN] Missing-branch registry materiality refresh failed: {exc!r}")

    balance_matching_diagnostics_path = checks_dir / RESULTS_BALANCE_MATCHING_DIAGNOSTICS_FILENAME
    balance_matching_diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
    _sort_output_frame_for_csv(
        balance_matching_diagnostics,
        exclude_sort_columns=("source_workbook", "source_sheet"),
    ).to_csv(balance_matching_diagnostics_path, index=False)
    timer.lap("write balance matching diagnostics")

    actionable_balance_demand_issues = pd.DataFrame()
    counts_text = ""
    if not balance_demand_issues.empty:
        balance_demand_issue_path = checks_dir / RESULTS_BALANCE_DEMAND_ISSUES_FILENAME
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
    timer.finish()
    if WRITE_WORKFLOW_TIMING_CSV:
        timer.write_csv(timing_path)
    return {
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
        "capacity_unmet_iterative_summary": allocation_ledger.pass_summary,
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
    run_context: ReconciliationRunContext | None = None,
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
        run_context=run_context,
    )

