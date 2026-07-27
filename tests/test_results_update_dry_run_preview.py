from pathlib import Path

import pandas as pd
import pytest

import codebase.supply_reconciliation_allocation as allocation
from codebase.functions import results_update_preview as preview


def _reconciliation() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "economy": "20_USA",
                "scenario": "Reference",
                "esto_product": "17 Electricity",
                "year": 2030,
                "adjusted_imports": 2.0,
                "adjusted_exports": 0.0,
                "max_transformation_output": 20.0,
                "constrained_transformation_output": 5.0,
                "max_production": pd.NA,
                "constrained_production": 0.0,
            }
        ]
    )


def _process_catalog() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "record_index": 0,
                "economy": "20_USA",
                "module": "Electricity generation",
                "process": "Gas plants",
                "instance": 1,
                "esto_product": "17 Electricity",
                "year": 2030,
                "product_output": 10.0,
                "module_total_output": 20.0,
                "yield": 0.5,
            }
        ]
    )


def _observed_trade() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "economy": "20_USA",
                "scenario": "reference",
                "esto_product": "17 Electricity",
                "year": 2030,
                "observed_imports": 8.0,
                "observed_exports": 0.0,
            }
        ]
    )


def test_preview_uses_allocator_without_writing_state_or_mutating_ledger(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.json"
    caller_ledger = allocation.CapacityUnmetAllocationLedger(
        {"keep": 1.0},
        {"keep": 2.0},
        {"keep": 3.0},
    )
    monkeypatch.setattr(
        allocation,
        "_build_capacity_process_catalog",
        lambda records: (_process_catalog(), []),
    )
    monkeypatch.setattr(
        allocation,
        "_build_label_to_esto_product_lookup",
        lambda: {},
    )
    monkeypatch.setattr(
        allocation,
        "_collect_observed_trade_from_supply_results",
        lambda **kwargs: (_observed_trade(), {"result": "signature"}, []),
    )
    monkeypatch.setattr(
        allocation,
        "_resolve_capacity_unmet_pass_mode",
        lambda mode=None: "results_update",
    )
    monkeypatch.setattr(
        allocation,
        "_write_capacity_unmet_state",
        lambda *args, **kwargs: pytest.fail("preview wrote iterative state"),
    )
    monkeypatch.setattr(
        allocation,
        "_write_convergence_csv",
        lambda *args, **kwargs: pytest.fail("preview wrote convergence history"),
    )
    monkeypatch.setattr(
        allocation,
        "_record_convergence_manifest",
        lambda *args, **kwargs: pytest.fail("preview wrote a manifest"),
    )

    summary = allocation._run_capacity_unmet_iterative_balanced_pass(
        reconciliation_table=_reconciliation(),
        process_records=[{}],
        economies=["20_USA"],
        scenarios=["Reference"],
        resolve_scenario_key=lambda frame, scenario: str(scenario).lower(),
        results_dir=tmp_path,
        state_path=state_path,
        allocation_ledger=caller_ledger,
        preview_only=True,
    )

    assert summary["preview_only"] is True
    assert summary["positive_import_gap_total"] == pytest.approx(6.0)
    assert summary["allocated_transformation_output_total"] == pytest.approx(6.0)
    assert state_path.exists() is False
    assert caller_ledger.capacity_additions == {"keep": 1.0}
    assert caller_ledger.primary_additions == {"keep": 2.0}
    assert caller_ledger.export_adjustments == {"keep": 3.0}
    assert caller_ledger.pass_summary is None


def test_preview_table_exposes_target_and_observed_gap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        allocation,
        "_build_capacity_process_catalog",
        lambda records: (_process_catalog(), []),
    )
    monkeypatch.setattr(
        allocation,
        "_build_label_to_esto_product_lookup",
        lambda: {},
    )
    monkeypatch.setattr(
        allocation,
        "_collect_observed_trade_from_supply_results",
        lambda **kwargs: (_observed_trade(), {}, []),
    )
    monkeypatch.setattr(
        allocation,
        "_resolve_capacity_unmet_pass_mode",
        lambda mode=None: "results_update",
    )

    summary = allocation._run_capacity_unmet_iterative_balanced_pass(
        reconciliation_table=_reconciliation(),
        process_records=[{}],
        economies=["20_USA"],
        scenarios=["Reference"],
        resolve_scenario_key=lambda frame, scenario: str(scenario).lower(),
        results_dir=tmp_path,
        state_path=tmp_path / "state.json",
        preview_only=True,
    )
    preview_table = preview.build_results_update_preview_table(summary)

    assert len(preview_table) == 1
    row = preview_table.iloc[0]
    assert row["proposal_type"] == "transformation_capacity"
    assert row["leap_branch_hint"] == (
        "Transformation\\Electricity generation\\Processes\\Gas plants"
    )
    assert row["leap_variable"] == "Exogenous Capacity"
    assert row["baseline_imports_pj"] == pytest.approx(2.0)
    assert row["observed_imports_pj"] == pytest.approx(8.0)
    assert row["import_gap_pj"] == pytest.approx(6.0)
    assert row["allocated_output_uplift_pj"] == pytest.approx(6.0)
    assert row["capacity_increment_output_equivalent_pj"] == pytest.approx(12.0)
    assert bool(row["safe_to_apply"]) is True


def test_preview_table_keeps_blocked_and_primary_export_surfaces_visible() -> None:
    summary = {
        "comparison_rows": [
            {
                "economy": "01_AUS",
                "scenario": "reference",
                "esto_product": "01 Coal",
                "year": 2022,
                "baseline_imports_pj": 2.0,
                "observed_imports_pj": 5.0,
                "import_gap_pj": 3.0,
            }
        ],
        "allocation_rows": [
            {
                "economy": "01_AUS",
                "scenario": "reference",
                "esto_product": "01 Coal",
                "year": 2022,
                "allocation_type": "primary_production",
                "allocated_output_uplift": 1.0,
                "capacity_increment": 1.0,
            }
        ],
        "export_rows": [
            {
                "economy": "01_AUS",
                "scenario": "reference",
                "esto_product": "01 Coal",
                "year": 2022,
                "extra_exports": 0.5,
            }
        ],
        "clipping_rows": [
            {
                "economy": "01_AUS",
                "scenario": "reference",
                "esto_product": "01 Coal",
                "year": 2022,
                "clipped_output_uplift": 2.0,
                "reason": "Production cap reached.",
            }
        ],
        "unresolved_positive_rows": [],
        "fatal_unresolved_positive_rows": [
            {
                "economy": "01_AUS",
                "scenario": "reference",
                "esto_product": "01 Coal",
                "year": 2022,
                "unresolved_output_uplift": 2.0,
                "reason": "No safe allocation.",
            }
        ],
    }

    preview_table = preview.build_results_update_preview_table(summary)

    assert set(preview_table["proposal_type"]) == {
        "primary_production",
        "extra_exports",
        "clipped",
        "unresolved",
    }
    primary = preview_table[
        preview_table["proposal_type"].eq("primary_production")
    ].iloc[0]
    assert primary["leap_variable"] == "Maximum Production"
    assert bool(primary["safe_to_apply"]) is False
    assert "abort this pass" in primary["blocked_reason"]


def test_public_preview_runner_writes_only_requested_review_csv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    summary = {
        "comparison_rows": [],
        "allocation_rows": [],
        "export_rows": [],
        "clipping_rows": [],
        "unresolved_positive_rows": [],
        "fatal_unresolved_positive_rows": [],
    }
    monkeypatch.setattr(
        allocation,
        "_run_capacity_unmet_iterative_balanced_pass",
        lambda **kwargs: (
            summary
            if kwargs["iteration_run_mode"] == "results_update"
            else pytest.fail("preview did not force results_update state semantics")
        ),
    )
    output_path = tmp_path / "review" / "preview.csv"

    result = preview.run_results_update_allocation_preview(
        reconciliation_table=_reconciliation(),
        process_records=[{}],
        economies=["20_USA"],
        scenarios=["Reference"],
        resolve_scenario_key=lambda frame, scenario: str(scenario).lower(),
        results_dir=tmp_path,
        state_path=tmp_path / "state.json",
        output_path=output_path,
    )

    assert output_path.exists()
    assert result["preview_path"] == output_path
    assert list(pd.read_csv(output_path).columns) == preview.RESULTS_UPDATE_PREVIEW_COLUMNS


def test_public_preview_runner_loads_reviewed_issue_decisions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    summary = {
        "comparison_rows": [],
        "allocation_rows": [
            {
                "economy": "01_AUS",
                "scenario": "reference",
                "esto_product": "01.04 Anthracite",
                "year": 2022,
                "allocation_type": "primary_production",
                "allocated_output_uplift": 5.0,
                "capacity_increment": 5.0,
            }
        ],
        "export_rows": [],
        "clipping_rows": [],
        "unresolved_positive_rows": [],
        "fatal_unresolved_positive_rows": [],
    }
    raw_review = pd.DataFrame(
        [
            {
                "economy": "01_AUS",
                "scenario": "Reference",
                "year": 2022,
                "esto_flow": "02 Imports",
                "esto_product": "01.04 Anthracite",
                "material_for_review": True,
                "primary_classification": "unresolved",
                "update_allocation_required": False,
                "next_action": "Review.",
            }
        ]
    )
    decisions = pd.read_csv(
        Path("config/runtime_tables/results_update_issue_decisions.csv")
    )
    monkeypatch.setattr(
        allocation,
        "_run_capacity_unmet_iterative_balanced_pass",
        lambda **kwargs: summary,
    )
    monkeypatch.setattr(
        preview,
        "load_results_update_issue_decisions",
        lambda: decisions,
    )

    result = preview.run_results_update_allocation_preview(
        reconciliation_table=_reconciliation(),
        process_records=[{}],
        economies=["01_AUS"],
        scenarios=["Reference"],
        resolve_scenario_key=lambda frame, scenario: str(scenario).lower(),
        results_dir=tmp_path,
        state_path=tmp_path / "state.json",
        balance_review=raw_review,
    )

    assert result["preview_table"].iloc[0]["update_disposition"] == (
        "excluded_upstream_issue"
    )


def test_balance_review_safety_keeps_unresolved_candidates_and_respects_cardinality() -> None:
    preview_table = pd.DataFrame(
        [
            {
                column: (
                    False
                    if column in {
                        "safe_to_apply",
                        "diagnostic_update_allocation_required",
                    }
                    else 0 if column == "diagnostic_material_rows" else ""
                )
                for column in preview.RESULTS_UPDATE_PREVIEW_COLUMNS
            }
            for _ in range(3)
        ]
    )
    preview_table["economy"] = "01_AUS"
    preview_table["scenario"] = "reference"
    preview_table["year"] = 2022
    preview_table["safe_to_apply"] = True
    preview_table["esto_product"] = [
        "01.02 Other bituminous coal",
        "17 Electricity",
        "07.09 LPG",
    ]
    review = pd.DataFrame(
        [
            {
                "economy": "01_AUS",
                "scenario": "Reference",
                "year": 2022,
                "esto_flow": "02 Imports",
                "esto_product": "01.02 Other bituminous coal",
                "material_for_review": True,
                "primary_classification": "approved_results_update",
                "update_allocation_required": False,
                "next_action": "Apply reviewed correction.",
            },
            {
                "economy": "01_AUS",
                "scenario": "Reference",
                "year": 2022,
                "esto_flow": "02 Imports",
                "esto_product": "17 Electricity",
                "material_for_review": True,
                "primary_classification": "approved_results_update",
                "update_allocation_required": True,
                "next_action": "Define allocation.",
            },
        ]
    )

    gated = preview.apply_balance_review_safety(preview_table, review)

    coal = gated[gated["esto_product"].eq("01.02 Other bituminous coal")].iloc[0]
    electricity = gated[gated["esto_product"].eq("17 Electricity")].iloc[0]
    lpg = gated[gated["esto_product"].eq("07.09 LPG")].iloc[0]
    assert bool(coal["safe_to_apply"]) is True
    assert coal["update_disposition"] == "approved_update_candidate"
    assert coal["safety_scope"] == "allocator_plus_balance_review"
    assert bool(electricity["safe_to_apply"]) is False
    assert electricity["update_disposition"] == "blocked_allocation_rule"
    assert "allocation rule" in electricity["blocked_reason"]
    assert bool(lpg["safe_to_apply"]) is True
    assert lpg["update_disposition"] == "provisional_update_candidate"
    assert lpg["blocked_reason"] == ""


def test_stale_export_is_provenance_while_reviewed_seed_defect_is_excluded() -> None:
    summary = {
        "comparison_rows": [],
        "allocation_rows": [
            {
                "economy": "01_AUS",
                "scenario": "reference",
                "esto_product": "01.02 Other bituminous coal",
                "year": 2022,
                "allocation_type": "primary_production",
                "allocated_output_uplift": 5.0,
                "capacity_increment": 5.0,
            }
        ],
        "export_rows": [],
        "clipping_rows": [],
        "unresolved_positive_rows": [],
        "fatal_unresolved_positive_rows": [],
    }
    preview_table = preview.build_results_update_preview_table(summary)
    review = pd.DataFrame(
        [
            {
                "economy": "01_AUS",
                "scenario": "Reference",
                "year": 2022,
                "esto_flow": "02 Imports",
                "esto_product": "01.02 Other bituminous coal",
                "material_for_review": True,
                "primary_classification": "baseline_seed_generation_bug",
                "update_allocation_required": False,
                "next_action": "Regenerate after the producer fix.",
            }
        ]
    )

    gated = preview.apply_balance_review_safety(
        preview_table,
        review,
        require_fresh_leap_cycle=True,
    )

    assert not gated["safe_to_apply"].any()
    assert gated.iloc[0]["update_disposition"] == "excluded_upstream_issue"
    assert gated.iloc[0]["diagnostic_provenance_status"] == (
        "predates_known_seed_fix"
    )
    assert "baseline_seed_generation_bug" in gated.iloc[0]["blocked_reason"]


def test_reviewed_decision_overrides_unresolved_raw_diagnostic() -> None:
    summary = {
        "comparison_rows": [],
        "allocation_rows": [
            {
                "economy": "01_AUS",
                "scenario": "reference",
                "esto_product": "01.04 Anthracite",
                "year": 2022,
                "allocation_type": "primary_production",
                "allocated_output_uplift": 5.0,
                "capacity_increment": 5.0,
            }
        ],
        "export_rows": [],
        "clipping_rows": [],
        "unresolved_positive_rows": [],
        "fatal_unresolved_positive_rows": [],
    }
    preview_table = preview.build_results_update_preview_table(summary)
    raw_review = pd.DataFrame(
        [
            {
                "economy": "01_AUS",
                "scenario": "Reference",
                "year": 2022,
                "esto_flow": "02 Imports",
                "esto_product": "01.04 Anthracite",
                "material_for_review": True,
                "primary_classification": "unresolved",
                "update_allocation_required": False,
                "next_action": "Review.",
            }
        ]
    )
    decisions = pd.read_csv(
        Path("config/runtime_tables/results_update_issue_decisions.csv")
    )

    gated = preview.apply_balance_review_safety(
        preview_table,
        raw_review,
        reviewed_decisions=decisions,
    )

    assert bool(gated.iloc[0]["safe_to_apply"]) is False
    assert gated.iloc[0]["diagnostic_classifications"] == (
        "baseline_seed_generation_bug"
    )
    assert gated.iloc[0]["update_disposition"] == "excluded_upstream_issue"


def test_non_import_diagnostic_does_not_block_import_gap_proposal() -> None:
    summary = {
        "comparison_rows": [],
        "allocation_rows": [
            {
                "economy": "01_AUS",
                "scenario": "reference",
                "esto_product": "17 Electricity",
                "year": 2022,
                "allocation_type": "primary_production",
                "allocated_output_uplift": 5.0,
                "capacity_increment": 5.0,
            }
        ],
        "export_rows": [],
        "clipping_rows": [],
        "unresolved_positive_rows": [],
        "fatal_unresolved_positive_rows": [],
    }
    preview_table = preview.build_results_update_preview_table(summary)
    review = pd.DataFrame(
        [
            {
                "economy": "01_AUS",
                "scenario": "Reference",
                "year": 2022,
                "esto_flow": "13 Total final energy demand",
                "esto_product": "17 Electricity",
                "material_for_review": True,
                "primary_classification": "diagnostic_bug",
                "update_allocation_required": False,
                "next_action": "Fix diagnostic boundary.",
            }
        ]
    )

    gated = preview.apply_balance_review_safety(preview_table, review)

    assert bool(gated.iloc[0]["safe_to_apply"]) is True
    assert gated.iloc[0]["update_disposition"] == "provisional_update_candidate"
    assert gated.iloc[0]["diagnostic_flow_scope"] == "02 Imports"


def test_balance_contract_allows_import_signal_and_blocks_export_difference() -> None:
    summary = {
        "comparison_rows": [],
        "allocation_rows": [
            {
                "economy": "01_AUS",
                "scenario": "reference",
                "esto_product": "17 Electricity",
                "year": 2022,
                "allocation_type": "primary_production",
                "allocated_output_uplift": 5.0,
                "capacity_increment": 5.0,
            }
        ],
        "export_rows": [
            {
                "economy": "01_AUS",
                "scenario": "reference",
                "esto_product": "07.09 LPG",
                "year": 2022,
                "extra_exports": 5.0,
            }
        ],
        "clipping_rows": [],
        "unresolved_positive_rows": [],
        "fatal_unresolved_positive_rows": [],
    }
    preview_table = preview.build_results_update_preview_table(summary)
    review = pd.DataFrame(
        [
            {
                "economy": "01_AUS",
                "scenario": "Reference",
                "year": 2022,
                "esto_flow": "02 Imports",
                "esto_product": "17 Electricity",
                "material_for_review": True,
                "primary_classification": "expected_error_signal",
                "update_allocation_required": False,
                "next_action": "Use as updater input.",
                "balance_variable_role": "error_signal",
                "balance_contract_issue": "expected_error_signal_difference",
                "update_signal_eligible": True,
            },
            {
                "economy": "01_AUS",
                "scenario": "Reference",
                "year": 2022,
                "esto_flow": "03 Exports",
                "esto_product": "07.09 LPG",
                "material_for_review": True,
                "primary_classification": "protected_flow_difference",
                "update_allocation_required": False,
                "next_action": "Raise an issue.",
                "balance_variable_role": "protected",
                "balance_contract_issue": "protected_flow_difference",
                "update_signal_eligible": False,
            },
        ]
    )

    gated = preview.apply_balance_review_safety(
        preview_table,
        review,
        reviewed_decisions=pd.DataFrame(),
    )

    imports = gated[gated["esto_product"].eq("17 Electricity")].iloc[0]
    exports = gated[gated["esto_product"].eq("07.09 LPG")].iloc[0]
    assert bool(imports["safe_to_apply"]) is True
    assert imports["update_disposition"] == "provisional_update_candidate"
    assert bool(imports["diagnostic_update_signal_eligible"]) is True
    assert bool(exports["safe_to_apply"]) is False
    assert exports["update_disposition"] == "blocked_balance_contract_issue"
    assert exports["diagnostic_balance_contract_issues"] == (
        "protected_flow_difference"
    )
