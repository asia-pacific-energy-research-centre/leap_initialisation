"""B3 tests for the explicit run-context boundary at the results saver."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

import codebase.supply_reconciliation.config as config
import codebase.supply_reconciliation_workflow as workflow
from codebase.supply_reconciliation import results_saver as saver


def test_economy_catalog_uses_target_template_spelling_and_one_structural_row(
    tmp_path,
    monkeypatch,
) -> None:
    """Cross-economy case variants cannot create repeated zero-fill shares."""
    template_path = tmp_path / "nz_template.xlsx"
    template_path.touch()
    canonical_path = (
        "Transformation\\NG Liquefaction\\Processes\\Liquefaction"
        "\\Feedstock Fuels\\Natural gas"
    )
    union_path = canonical_path[:-3] + "Gas"
    catalog = pd.DataFrame(
        [
            {
                "catalog_type": "transformation",
                "source_workbook": f"{source_name}_{scenario}.xlsx",
                "scenario": scenario,
                "module_or_root": "NG Liquefaction",
                "fuel_group": "Feedstock Fuels",
                "fuel_name": branch_path.rsplit("\\", 1)[-1],
                "branch_path": branch_path,
                "variable": "Feedstock Fuel Share",
                "catalog_source": "template",
                "probe_status": "",
            }
            for source_name, branch_path in (
                ("mex", union_path),
                ("nz", canonical_path),
            )
            for scenario in ("Current Accounts", "Reference", "Target")
        ]
    )
    template_rows = pd.DataFrame(
        [
            {
                "Branch Path": canonical_path,
                "Variable": "Feedstock Fuel Share",
                "Scenario": scenario,
            }
            for scenario in ("Current Accounts", "Reference", "Target")
        ]
    )
    monkeypatch.setattr(
        saver.leap_export_template_resolver,
        "resolve_leap_export_template",
        lambda economy, warn_on_provisional=False: template_path,
    )
    monkeypatch.setattr(
        saver,
        "_read_branch_variable_rows",
        lambda path, sheet_name="Export": template_rows,
    )

    result = saver._catalog_for_economy(catalog, "12_NZ")

    assert len(result) == 1
    assert result.iloc[0]["branch_path"] == canonical_path
    assert result.iloc[0]["fuel_name"] == "Natural gas"


def test_results_saver_context_paths_match_legacy_path_view(monkeypatch) -> None:
    """A context preserves the exact four paths legacy globals would resolve."""
    context = config.resolve_reconciliation_run_context(
        "baseline_seed",
        "SEED_01_AUS_CONTEXT_TEST",
    )
    monkeypatch.setattr(saver, "OUTPUT_DIR", context.output_dir)
    monkeypatch.setattr(saver, "EXPORT_OUTPUT_DIR", context.export_output_dir)
    monkeypatch.setattr(
        saver,
        "TRANSFORMATION_EXPORT_OUTPUT_DIR",
        context.transformation_export_output_dir,
    )
    monkeypatch.setattr(saver, "YEARLY_BALANCE_DIR", context.yearly_balance_dir)
    monkeypatch.setattr(saver, "CONVENTIONAL_BALANCE_DIR", context.conventional_balance_dir)
    monkeypatch.setattr(saver, "RESULTS_RUNTIME_DIR", context.results_runtime_dir)
    monkeypatch.setattr(saver, "RESULTS_CHECKS_DIR", context.results_checks_dir)
    monkeypatch.setattr(saver, "CAPACITY_UNMET_STATE_PATH", context.capacity_unmet_state_path)
    monkeypatch.setattr(
        saver,
        "LEAP_FUEL_BRANCH_PROBE_OUTPUT_PATH",
        context.leap_fuel_branch_probe_output_path,
    )

    legacy_paths = saver._resolve_results_saver_run_paths(None)
    context_paths = saver._resolve_results_saver_run_paths(context)

    assert context_paths == legacy_paths
    assert context_paths["output_dir"] == context.output_dir
    assert context_paths["runtime_dir"] == context.results_runtime_dir
    assert context_paths["checks_dir"] == context.results_checks_dir
    assert context_paths["state_path"] == context.capacity_unmet_state_path
    assert context_paths["export_dir"] == context.export_output_dir
    assert context_paths["transformation_export_dir"] == context.transformation_export_output_dir
    assert context_paths["yearly_balance_dir"] == context.yearly_balance_dir
    assert context_paths["conventional_balance_dir"] == context.conventional_balance_dir
    assert context_paths["probe_catalog_path"] == context.leap_fuel_branch_probe_output_path


def test_results_saver_context_output_families_do_not_follow_legacy_globals(monkeypatch) -> None:
    """An explicit context keeps every output family in its own run scope."""
    legacy_context = config.resolve_reconciliation_run_context(
        "baseline_seed",
        "SEED_01_AUS_LEGACY_SCOPE",
    )
    explicit_context = config.resolve_reconciliation_run_context(
        "results_update",
        "SEED_01_AUS_EXPLICIT_SCOPE",
    )
    monkeypatch.setattr(saver, "EXPORT_OUTPUT_DIR", legacy_context.export_output_dir)
    monkeypatch.setattr(
        saver,
        "TRANSFORMATION_EXPORT_OUTPUT_DIR",
        legacy_context.transformation_export_output_dir,
    )
    monkeypatch.setattr(saver, "YEARLY_BALANCE_DIR", legacy_context.yearly_balance_dir)
    monkeypatch.setattr(saver, "CONVENTIONAL_BALANCE_DIR", legacy_context.conventional_balance_dir)
    monkeypatch.setattr(
        saver,
        "LEAP_FUEL_BRANCH_PROBE_OUTPUT_PATH",
        legacy_context.leap_fuel_branch_probe_output_path,
    )

    paths = saver._resolve_results_saver_run_paths(explicit_context)

    assert paths["export_dir"] == explicit_context.export_output_dir
    assert paths["transformation_export_dir"] == explicit_context.transformation_export_output_dir
    assert paths["yearly_balance_dir"] == explicit_context.yearly_balance_dir
    assert paths["conventional_balance_dir"] == explicit_context.conventional_balance_dir
    assert paths["probe_catalog_path"] == explicit_context.leap_fuel_branch_probe_output_path


def test_fuel_catalog_uses_explicit_probe_path_not_global(tmp_path, monkeypatch) -> None:
    """The saver can carry a run-scoped fuel probe into its catalog."""
    probe_path = tmp_path / "explicit_probe.csv"
    pd.DataFrame(
        [
            {
                "catalog_type": "supply",
                "module_or_root": "Primary",
                "fuel_group": "",
                "fuel_name": "Explicit probe fuel",
                "branch_path": "Resources\\Primary\\Explicit probe fuel",
            }
        ]
    ).to_csv(probe_path, index=False)
    monkeypatch.setattr(saver, "USE_FULL_MODEL_EXPORT_CATALOG_SOURCE", False)
    monkeypatch.setattr(
        saver,
        "LEAP_FUEL_BRANCH_PROBE_OUTPUT_PATH",
        tmp_path / "legacy_probe.csv",
    )

    catalog = saver._build_transformation_supply_fuel_catalog_df(
        transformation_export_paths=[],
        supply_export_paths=[],
        include_print_summary=False,
        probe_catalog_path=probe_path,
    )

    assert catalog["fuel_name"].tolist() == ["Explicit probe fuel"]


def test_workflow_forwards_current_context_to_results_saver(monkeypatch) -> None:
    """Normal runs cross the B3 boundary without relying on saver globals."""
    context = config.resolve_reconciliation_run_context(
        "baseline_seed",
        "SEED_01_AUS_CONTEXT_FORWARD",
    )
    monkeypatch.setattr(workflow, "ACTIVE_RUN_CONTEXT", context)
    monkeypatch.setattr(workflow, "OUTPUT_DIR", context.output_dir)
    monkeypatch.setattr(workflow, "RESULTS_RUNTIME_DIR", context.results_runtime_dir)
    monkeypatch.setattr(workflow, "RESULTS_CHECKS_DIR", context.results_checks_dir)
    monkeypatch.setattr(workflow, "CAPACITY_UNMET_STATE_PATH", context.capacity_unmet_state_path)
    monkeypatch.setattr(workflow, "_sync_results_saver_overrides", lambda: None)

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        workflow._srs,
        "run_results_linked_transformation_supply_workflow",
        lambda **kwargs: captured.update(kwargs) or {"ok": True},
    )

    assert workflow.run_results_linked_transformation_supply_workflow() == {"ok": True}
    assert captured["run_context"] is context


def test_workflow_uses_legacy_fallback_for_temporary_preflight_paths(monkeypatch) -> None:
    """A direct preflight path override cannot accidentally receive a stale context."""
    context = config.resolve_reconciliation_run_context(
        "baseline_seed",
        "SEED_01_AUS_CONTEXT_STALE",
    )
    monkeypatch.setattr(workflow, "ACTIVE_RUN_CONTEXT", context)
    monkeypatch.setattr(workflow, "OUTPUT_DIR", Path("temporary_preflight_output"))
    monkeypatch.setattr(workflow, "RESULTS_RUNTIME_DIR", context.results_runtime_dir)
    monkeypatch.setattr(workflow, "RESULTS_CHECKS_DIR", context.results_checks_dir)
    monkeypatch.setattr(workflow, "CAPACITY_UNMET_STATE_PATH", context.capacity_unmet_state_path)

    assert workflow._active_run_context_for_results_saver() is None
