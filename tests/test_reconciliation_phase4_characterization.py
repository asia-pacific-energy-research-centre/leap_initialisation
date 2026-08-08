"""Characterization contracts required before Phase 4 state injection.

These tests deliberately inspect imports and signatures only.  They do not run
the reconciliation workflow, acquire economy locks, or write output files, so
they are safe while a real economy run is in flight.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import codebase.supply_reconciliation.allocation as allocation
import codebase.supply_reconciliation.balance_tables as balance_tables
import codebase.supply_reconciliation.config as config
import codebase.supply_reconciliation.history as history
import codebase.supply_reconciliation.results as results
import codebase.supply_reconciliation_workflow as workflow
from codebase.functions import patch_baseline_seeds


REPO_ROOT = Path(__file__).resolve().parents[1]

RUN_CONTEXT_CONFIG_NAMES = (
    "CAPACITY_UNMET_PASS_MODE",
    "RUN_OUTPUT_LABEL",
    "OUTPUT_DIR",
    "EXPORT_OUTPUT_DIR",
    "TRANSFORMATION_EXPORT_OUTPUT_DIR",
    "YEARLY_BALANCE_DIR",
    "CONVENTIONAL_BALANCE_DIR",
    "CAPACITY_UNMET_RESULTS_DIR",
    "RESULTS_SINGLE_FILE_ARCHIVE_DIR",
    "RESULTS_CHECKS_DIR",
    "RESULTS_RUNTIME_DIR",
    "CAPACITY_UNMET_STATE_PATH",
    "LEAP_FUEL_BRANCH_PROBE_OUTPUT_PATH",
)

# B3 characterization.  The patch preset now pins CAPACITY_UNMET_PASS_MODE to
# "baseline_seed" explicitly (2026-07-23 presets scoped review, finding 3 -
# it used to leave the name unset and silently inherit whatever the config
# default or a prior preset run left behind). It still bypasses normal
# run-output labelling (RUN_MODE=="patch_baseline_seeds" short-circuits
# _automatic_run_output_label() to None regardless of pass mode).
# These snapshots pin that contract before the paths become an injected object.
EXPECTED_PRESET_RUN_CONTEXTS = (
    ("_PRESET_BASELINE_SEED", "baseline_seed", "SEED_01_AUS_TGT"),
    ("_PRESET_RESULTS_UPDATE", "results_update", "UPDATE_01_AUS_TGT"),
    ("_PRESET_PATCH_BASELINE_SEEDS", "baseline_seed", None),
)

# B1 interface measurement.  These are the five modules produced by the Phase
# 4 split; the larger supply helper modules are deliberately outside this seam.
EXPECTED_CONFIG_SURFACES = {
    "supply_reconciliation/allocation.py": {
        "BASE_YEAR", "CAPACITY_UNMET_ALLOW_SAME_RESULTS_REUSE", "ENERGY_SOURCE_CONFIG",
        "CAPACITY_UNMET_IMPORT_SHEETS", "CAPACITY_UNMET_MODULE_CAPACITY_UPPER_LIMITS",
        "CAPACITY_UNMET_PIN_EXPORTS_TO_9TH_PROJECTIONS",
        "CAPACITY_UNMET_PRIORITY_BY_PRODUCT", "CAPACITY_UNMET_PRODUCTION_UPPER_LIMITS",
        "CAPACITY_UNMET_RESULTS_DIR", "CAPACITY_UNMET_STATE_PATH",
        "CAPACITY_UNMET_UNRESOLVED_POSITIVE_POLICY", "FINAL_YEAR", "FULL_MODEL_EXPORT_CATALOG_PATH",
        "RESULTS_CHECKS_DIR", "RESULTS_RUNTIME_DIR", "_ModuleCapRule",
        "_resolve_module_cap_rule",
    },
    "supply_reconciliation/balance_tables.py": {
        "BALANCE_DEMAND_REF_WORKBOOK_PATH", "BALANCE_DEMAND_TGT_WORKBOOK_PATH",
        "BASE_YEAR", "CONVENTIONAL_BALANCE_DIR", "DROP_DISAGGREGATED_DEMAND_SECTORS",
        "DROP_PARENT_DEMAND_ROWS_WHEN_CHILDREN_PRESENT",
        "INCLUDE_TOP_LEVEL_DEMAND_CATEGORY_ROWS", "REFINERY_FUEL_LABEL_ALIASES",
        "REFINERY_RESULTS_SHEET_NAME", "REFINERY_SECTOR_NAME", "YEARLY_BALANCE_DIR",
    },
    "supply_reconciliation/history.py": {
        "BASE_YEAR", "CAPACITY_UNMET_FIRST_CLEAN_ARCHIVE_EXISTING_STATE",
        "CAPACITY_UNMET_PASS_MODE", "CAPACITY_UNMET_STATE_PATH", "FINAL_YEAR",
        "RESULTS_RUNTIME_DIR", "RESULTS_SINGLE_FILE_ARCHIVE_DIR",
    },
    "supply_reconciliation/results.py": {
        "BASE_YEAR", "CAPACITY_UNMET_RESULTS_DIR", "FINAL_YEAR",
        "LEAP_RESULTS_TABLES_DIR", "REFINERY_RESULTS_FILENAME_TEMPLATE",
        "TRANSFORMATION_RESULTS_FILENAME_TEMPLATE",
    },
    "supply_reconciliation_workflow.py": {
        "ACTIVE_SUPPLY_LINK_METHOD", "BALANCE_DEMAND_FAIL_ON_MAPPING_ISSUES",
        "CAPACITY_UNMET_PASS_MODE",
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
    config_path = REPO_ROOT / "codebase" / "supply_reconciliation" / "config.py"
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


@pytest.mark.parametrize(
    ("preset_name", "expected_mode", "expected_label"),
    EXPECTED_PRESET_RUN_CONTEXTS,
)
def test_each_preset_resolves_its_characterized_run_context(
    monkeypatch: pytest.MonkeyPatch,
    preset_name: str,
    expected_mode: str,
    expected_label: str | None,
) -> None:
    """Pin B3's current preset-to-path contract without starting a workflow.

    The test exercises only label/path resolution.  It does not call
    ``run_with_config()``, acquire an economy lock, or write any output file.
    ``refresh_output_paths_for_pass_mode`` mutates config globals, so the
    monkeypatch fixture restores every touched value at test teardown.
    """
    preset = getattr(workflow, preset_name)
    for name in RUN_CONTEXT_CONFIG_NAMES:
        monkeypatch.setattr(config, name, getattr(config, name))

    # Keep the automatic label deterministic and apply only the few preset
    # controls that determine a run context.
    monkeypatch.setattr(workflow, "ECONOMIES", ["01_AUS"])
    monkeypatch.setattr(workflow, "SCENARIOS", ["Target"])
    monkeypatch.setattr(workflow, "RUN_MODE", preset.get("RUN_MODE", "full"))
    monkeypatch.setattr(
        workflow,
        "CAPACITY_UNMET_PASS_MODE",
        preset.get("CAPACITY_UNMET_PASS_MODE", "results_update"),
    )
    monkeypatch.setattr(workflow, "RUN_OUTPUT_LABEL", "auto")

    resolved_label = workflow._resolve_run_output_label()
    refreshed = config.refresh_output_paths_for_pass_mode(
        workflow.CAPACITY_UNMET_PASS_MODE,
        resolved_label,
    )

    assert config.CAPACITY_UNMET_PASS_MODE == expected_mode
    assert resolved_label == expected_label
    assert refreshed["RUN_OUTPUT_LABEL"] == expected_label
    if expected_label is None:
        assert config.OUTPUT_DIR == config.INTEGRATED_LEAP_EXPORTS_ROOT / expected_mode
    else:
        assert config.OUTPUT_DIR == (
            config.INTEGRATED_LEAP_EXPORTS_ROOT / expected_mode / "runs" / expected_label
        )
    assert config.RESULTS_RUNTIME_DIR == config.OUTPUT_DIR / "supporting_files" / "runtime"
    assert config.CAPACITY_UNMET_STATE_PATH == (
        config.RESULTS_RUNTIME_DIR / "capacity_unmet_iterative_state.json"
    )


def test_run_contexts_are_independent_values_before_legacy_global_refresh() -> None:
    """B3 may construct two output scopes without mutating config globals."""
    original_values = {
        name: getattr(config, name)
        for name in RUN_CONTEXT_CONFIG_NAMES
    }

    baseline_context = config.resolve_reconciliation_run_context(
        "baseline_seed",
        "SEED_01_AUS_TGT",
    )
    update_context = config.resolve_reconciliation_run_context(
        "results_update",
        "UPDATE_02_BD_TGT",
    )

    assert baseline_context.capacity_unmet_pass_mode == "baseline_seed"
    assert update_context.capacity_unmet_pass_mode == "results_update"
    assert baseline_context.output_dir != update_context.output_dir
    assert baseline_context.results_runtime_dir == (
        baseline_context.output_dir / "supporting_files" / "runtime"
    )
    assert update_context.capacity_unmet_state_path == (
        update_context.results_runtime_dir / "capacity_unmet_iterative_state.json"
    )
    assert baseline_context.as_config_overrides()["RUN_OUTPUT_LABEL"] == "SEED_01_AUS_TGT"
    assert update_context.as_config_overrides()["RUN_OUTPUT_LABEL"] == "UPDATE_02_BD_TGT"
    assert {
        name: getattr(config, name)
        for name in RUN_CONTEXT_CONFIG_NAMES
    } == original_values


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


def test_patch_baseline_seed_entry_keeps_its_notebook_contract() -> None:
    """The patch preset delegates to this public entry without a CLI wrapper."""
    assert callable(patch_baseline_seeds.run_patch)
    assert tuple(inspect.signature(patch_baseline_seeds.run_patch).parameters) == (
        "module",
        "economies",
        "run_workflow",
    )


def test_split_modules_remain_importable() -> None:
    assert all(module is not None for module in (allocation, balance_tables, history, results))


def test_allocation_ledger_is_the_canonical_runtime_accumulator_container() -> None:
    """B2 introduction keeps legacy globals as views without changing values."""
    original = allocation._CAPACITY_UNMET_ALLOCATION_LEDGER
    capacity = {"01_AUS|Reference|Gas": 1.0}
    primary = {"01_AUS|Reference|Coal": 2.0}
    exports = {"01_AUS|Reference|Oil": 3.0}
    summary = {"pass_count": 1}
    try:
        ledger = allocation.CapacityUnmetAllocationLedger(capacity, primary, exports, summary)
        allocation._set_capacity_unmet_allocation_ledger(ledger)

        assert allocation._CAPACITY_UNMET_ALLOCATION_LEDGER is ledger
        assert allocation._CAPACITY_UNMET_RUNTIME_CAPACITY_ADDITIONS is capacity
        assert allocation._CAPACITY_UNMET_RUNTIME_PRIMARY_ADDITIONS is primary
        assert allocation._CAPACITY_UNMET_RUNTIME_EXPORT_ADJUSTMENTS is exports
        assert allocation._CAPACITY_UNMET_RUNTIME_PASS_SUMMARY is summary
    finally:
        allocation._set_capacity_unmet_allocation_ledger(original)


def test_allocation_ledger_reset_and_summary_setter_refresh_legacy_view() -> None:
    original = allocation._CAPACITY_UNMET_ALLOCATION_LEDGER
    try:
        ledger = allocation._reset_capacity_unmet_allocation_ledger()
        summary = {"pass_count": 2}
        allocation._set_capacity_unmet_runtime_pass_summary(summary)

        assert allocation._CAPACITY_UNMET_ALLOCATION_LEDGER is ledger
        assert ledger.pass_summary is summary
        assert allocation._CAPACITY_UNMET_RUNTIME_PASS_SUMMARY is summary
        assert allocation._CAPACITY_UNMET_RUNTIME_CAPACITY_ADDITIONS == {}
    finally:
        allocation._set_capacity_unmet_allocation_ledger(original)
