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
