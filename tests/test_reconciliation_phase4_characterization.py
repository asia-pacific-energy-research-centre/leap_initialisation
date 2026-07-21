"""Characterization contracts required before Phase 4 state injection.

These tests deliberately inspect imports and signatures only.  They do not run
the reconciliation workflow, acquire economy locks, or write output files, so
they are safe while a real economy run is in flight.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import codebase.supply_reconciliation_allocation as allocation
import codebase.supply_reconciliation_balance_tables as balance_tables
import codebase.supply_reconciliation_history as history
import codebase.supply_reconciliation_results as results
import codebase.supply_reconciliation_workflow as workflow


REPO_ROOT = Path(__file__).resolve().parents[1]

# B1 interface measurement.  These are the five modules produced by the Phase
# 4 split; the larger supply helper modules are deliberately outside this seam.
EXPECTED_CONFIG_SURFACES = {
    "supply_reconciliation_allocation.py": {
        "BASE_YEAR", "CAPACITY_UNMET_ALLOW_SAME_RESULTS_REUSE",
        "CAPACITY_UNMET_IMPORT_SHEETS", "CAPACITY_UNMET_MODULE_CAPACITY_UPPER_LIMITS",
        "CAPACITY_UNMET_PIN_EXPORTS_TO_9TH_PROJECTIONS",
        "CAPACITY_UNMET_PRIORITY_BY_PRODUCT", "CAPACITY_UNMET_PRODUCTION_UPPER_LIMITS",
        "CAPACITY_UNMET_RESULTS_DIR", "CAPACITY_UNMET_STATE_PATH",
        "CAPACITY_UNMET_UNRESOLVED_POSITIVE_POLICY", "FINAL_YEAR",
        "RESULTS_CHECKS_DIR", "RESULTS_RUNTIME_DIR", "_ModuleCapRule",
        "_resolve_module_cap_rule",
    },
    "supply_reconciliation_balance_tables.py": {
        "BALANCE_DEMAND_REF_WORKBOOK_PATH", "BALANCE_DEMAND_TGT_WORKBOOK_PATH",
        "BASE_YEAR", "CONVENTIONAL_BALANCE_DIR", "DROP_DISAGGREGATED_DEMAND_SECTORS",
        "DROP_PARENT_DEMAND_ROWS_WHEN_CHILDREN_PRESENT",
        "INCLUDE_TOP_LEVEL_DEMAND_CATEGORY_ROWS", "REFINERY_FUEL_LABEL_ALIASES",
        "REFINERY_RESULTS_SHEET_NAME", "REFINERY_SECTOR_NAME", "YEARLY_BALANCE_DIR",
    },
    "supply_reconciliation_history.py": {
        "BASE_YEAR", "CAPACITY_UNMET_FIRST_CLEAN_ARCHIVE_EXISTING_STATE",
        "CAPACITY_UNMET_PASS_MODE", "CAPACITY_UNMET_STATE_PATH", "FINAL_YEAR",
        "RESULTS_RUNTIME_DIR", "RESULTS_SINGLE_FILE_ARCHIVE_DIR",
    },
    "supply_reconciliation_results.py": {
        "BASE_YEAR", "CAPACITY_UNMET_RESULTS_DIR", "FINAL_YEAR",
        "LEAP_RESULTS_TABLES_DIR", "REFINERY_RESULTS_FILENAME_TEMPLATE",
        "TRANSFORMATION_RESULTS_FILENAME_TEMPLATE",
    },
    "supply_reconciliation_workflow.py": {
        "ACTIVE_SUPPLY_LINK_METHOD", "BALANCE_DEMAND_EXPORTS_ROOT",
        "BALANCE_DEMAND_FAIL_ON_MAPPING_ISSUES", "CAPACITY_UNMET_PASS_MODE",
        "COMPLETION_BEEP_ON_ERROR", "ENABLE_COMPLETION_BEEP", "ENABLE_WORKFLOW_TIMING",
        "EXPORT_DATASET_KEY", "FINAL_YEAR", "KEEP_ALL_ZERO_SUPPLY_ROWS",
        "LEAP_IMPORT_INCLUDE_CURRENT_ACCOUNTS", "LEAP_IMPORT_LOG_LEVEL",
        "LEAP_IMPORT_MAX_YEAR", "LEAP_IMPORT_SCENARIOS", "LEAP_IMPORT_SUPPLY_TO_LEAP",
        "LEAP_IMPORT_TRANSFERS_TO_LEAP", "LEAP_IMPORT_TRANSFORMATION_TO_LEAP",
        "OTHER_LOSS_OWN_USE_INCLUDE_IN_LEAP_IMPORT", "OTHER_LOSS_OWN_USE_OUTPUT_FUEL_SCOPE",
        "REPO_ROOT", "REQUIRE_LEVEL2_BALANCE_EXPORT_DETAIL", "RESULTS_RUNTIME_DIR",
        "RESULTS_WRITE_LEGACY_SIDECAR_FILES", "RUN_LEAP_FUEL_BRANCH_PROBE_AT_START",
        "RUN_OTHER_LOSS_OWN_USE_PROXY", "RUN_OUTPUT_LABEL", "SCRAPE_LEAP_RESULTS",
        "WRITE_WORKFLOW_TIMING_CSV",
    },
}


def _module_config_surface(filename: str) -> set[str]:
    """Return config names loaded by a split module's source AST."""
    config_path = REPO_ROOT / "codebase" / "supply_reconciliation_config.py"
    config_tree = ast.parse(config_path.read_text(encoding="utf-8-sig"))
    config_names = {
        node.target.id
        for node in config_tree.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    config_names |= {
        target.id
        for node in config_tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    config_names |= {
        node.name for node in config_tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))
    }
    tree = ast.parse((REPO_ROOT / "codebase" / filename).read_text(encoding="utf-8-sig"))
    return {
        node.id for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in config_names
    }


def test_split_module_config_surfaces_match_characterized_snapshot() -> None:
    actual = {name: _module_config_surface(name) for name in EXPECTED_CONFIG_SURFACES}
    assert actual == EXPECTED_CONFIG_SURFACES


def test_convergence_csv_schema_is_exact_and_legacy_reader_is_public() -> None:
    assert history.CONVERGENCE_CSV_COLUMNS == [
        "run_id", "timestamp_utc", "mode", "iteration_run_mode", "pass_count",
        "gap_at_first_pass", "gap_at_current_pass", "gap_closure_pct",
        "gap_delta_last_pass", "allocated_cumulative", "clipped_total_current",
        "unresolved_count_current", "trend", "unresolved_fuels_current",
    ]
    assert callable(history.load_convergence_csv)


def test_public_workflow_callables_keep_their_notebook_contract() -> None:
    expected = {
        "run_with_config": (),
        "run_results_linked_transformation_supply_workflow": ("args", "kwargs"),
        "run_results_linked_supply_workflow": ("args", "kwargs"),
        "build_supply_overrides": ("reconciliation_table",),
    }
    for name, parameter_names in expected.items():
        function = getattr(workflow, name)
        assert callable(function)
        assert tuple(inspect.signature(function).parameters) == parameter_names


def test_split_modules_remain_importable() -> None:
    assert all(module is not None for module in (allocation, balance_tables, history, results))
