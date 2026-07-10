from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from codebase.functions.capacity_unmet_convergence_diagnostics import (
    build_capacity_unmet_run_diagnostics,
    compare_capacity_unmet_runs,
)
from codebase.supply_reconciliation_history import CONVERGENCE_CSV_COLUMNS


def _write_state(path: Path) -> None:
    state = {
        "passes": [
            {
                "run_id": "run_a",
                "timestamp_utc": "2026-01-01T00:00:00+00:00",
                "mode": "capacity_unmet_iterative_balanced",
                "iteration_run_mode": "results_update",
                "positive_import_gap_total": 15.0,
                "positive_gap_rows": [
                    {"esto_product": "01 Coal", "positive_gap": 10.0},
                    {"esto_product": "02 Gas", "positive_gap": 5.0},
                ],
                "allocation_rows": [
                    {
                        "esto_product": "01 Coal",
                        "allocated_output_uplift": 3.0,
                        "allocation_type": "primary_production",
                    },
                    {
                        "esto_product": "02 Gas",
                        "allocated_output_uplift": 4.0,
                        "allocation_type": "transformation",
                    },
                ],
                "clipping_rows": [
                    {"esto_product": "02 Gas", "clipped_output_uplift": 1.0},
                ],
                "unresolved_positive_rows": [],
            },
            {
                "run_id": "run_a",
                "timestamp_utc": "2026-01-01T01:00:00+00:00",
                "mode": "capacity_unmet_iterative_balanced",
                "iteration_run_mode": "results_update",
                "positive_import_gap_total": 2.0,
                "positive_gap_rows": [
                    {"esto_product": "01 Coal", "positive_gap": 2.0},
                ],
                "allocation_rows": [],
                "clipping_rows": [],
                "unresolved_positive_rows": [
                    {"esto_product": "01 Coal", "unresolved_output_uplift": 2.0},
                ],
            },
            {
                "run_id": "run_b",
                "timestamp_utc": "2026-01-02T00:00:00+00:00",
                "mode": "capacity_unmet_iterative",
                "iteration_run_mode": "baseline_seed",
                "unmet_proxy_total": 8.0,
                "positive_gap_rows": [
                    {"esto_product": "01 Coal", "positive_gap": 1.0},
                    {"esto_product": "03 Oil", "positive_gap": 7.0},
                ],
                "allocation_rows": [
                    {"esto_product": "03 Oil", "allocated_output_uplift": 2.0},
                ],
                "clipping_rows": [],
                "unresolved_positive_rows": [
                    {"esto_product": "03 Oil", "unresolved_output_uplift": 7.0},
                ],
            },
        ],
        "pass_deltas": [],
    }
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _write_convergence(path: Path) -> None:
    rows = [
        {
            "run_id": "run_a",
            "timestamp_utc": "2026-01-01T00:00:00+00:00",
            "mode": "capacity_unmet_iterative_balanced",
            "iteration_run_mode": "results_update",
            "pass_count": 1,
            "gap_at_first_pass": 15.0,
            "gap_at_current_pass": 15.0,
            "gap_closure_pct": 0.0,
            "gap_delta_last_pass": 0.0,
            "allocated_cumulative": 7.0,
            "clipped_total_current": 1.0,
            "unresolved_count_current": 0,
            "trend": "unknown",
            "unresolved_fuels_current": "",
        },
        {
            "run_id": "run_a",
            "timestamp_utc": "2026-01-01T01:00:00+00:00",
            "mode": "capacity_unmet_iterative_balanced",
            "iteration_run_mode": "results_update",
            "pass_count": 2,
            "gap_at_first_pass": 15.0,
            "gap_at_current_pass": 2.0,
            "gap_closure_pct": 86.6667,
            "gap_delta_last_pass": -13.0,
            "allocated_cumulative": 7.0,
            "clipped_total_current": 0.0,
            "unresolved_count_current": 1,
            "trend": "converging",
            "unresolved_fuels_current": "01 Coal",
        },
        {
            "run_id": "run_b",
            "timestamp_utc": "2026-01-02T00:00:00+00:00",
            "mode": "capacity_unmet_iterative",
            "iteration_run_mode": "baseline_seed",
            "pass_count": 1,
            "gap_at_first_pass": 8.0,
            "gap_at_current_pass": 8.0,
            "gap_closure_pct": 0.0,
            "gap_delta_last_pass": 0.0,
            "allocated_cumulative": 2.0,
            "clipped_total_current": 0.0,
            "unresolved_count_current": 1,
            "trend": "unknown",
            "unresolved_fuels_current": "03 Oil",
        },
    ]
    pd.DataFrame(rows, columns=CONVERGENCE_CSV_COLUMNS).to_csv(path, index=False)


def test_build_capacity_unmet_run_diagnostics_from_synthetic_state(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    convergence_path = tmp_path / "convergence.csv"
    _write_state(state_path)
    _write_convergence(convergence_path)

    result = build_capacity_unmet_run_diagnostics(
        "run_a",
        state_path=state_path,
        convergence_csv_path=convergence_path,
        output_dir=tmp_path,
        print_summary=False,
    )

    summary = result["summary"]
    assert summary["passes_executed"] == 2
    assert summary["first_gap"] == pytest.approx(15.0)
    assert summary["final_gap"] == pytest.approx(2.0)
    assert summary["closure_pct"] == pytest.approx(86.6667)
    assert summary["allocated_primary_production"] == pytest.approx(3.0)
    assert summary["allocated_transformation_capacity"] == pytest.approx(4.0)
    assert summary["allocated_imports_fallback"] == pytest.approx(2.0)
    assert summary["total_clipped"] == pytest.approx(1.0)
    assert result["csv_path"].exists()

    per_fuel = result["per_fuel"].set_index("esto_product")
    assert per_fuel.loc["01 Coal", "gap_delta"] == pytest.approx(-8.0)
    assert bool(per_fuel.loc["01 Coal", "still_unresolved"]) is True
    assert result["movers"].iloc[0]["esto_product"] == "01 Coal"


def test_compare_capacity_unmet_runs_reports_unresolved_diff(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    convergence_path = tmp_path / "convergence.csv"
    _write_state(state_path)
    _write_convergence(convergence_path)

    result = compare_capacity_unmet_runs(
        state_path=state_path,
        convergence_csv_path=convergence_path,
        print_summary=False,
    )

    summary = result["summary"]
    assert summary["run_id_a"] == "run_a"
    assert summary["run_id_b"] == "run_b"
    assert summary["resolved_in_b"] == ["01 Coal"]
    assert summary["newly_unresolved_in_b"] == ["03 Oil"]
    assert summary["unresolved_in_both"] == []
    assert summary["mode_mismatch"] is True
    assert list(result["gap_trajectory"]["pass_count"]) == [1, 2]


def test_build_capacity_unmet_run_diagnostics_handles_legacy_csv_without_state_passes(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    convergence_path = tmp_path / "legacy_convergence.csv"
    state_path.write_text(json.dumps({"passes": [], "pass_deltas": []}), encoding="utf-8")
    legacy_columns = [column for column in CONVERGENCE_CSV_COLUMNS if column != "run_id"]
    pd.DataFrame(
        [
            {
                "timestamp_utc": "2026-01-01T00:00:00+00:00",
                "mode": "capacity_unmet_iterative_balanced",
                "iteration_run_mode": "results_update",
                "pass_count": 1,
                "gap_at_first_pass": 10.0,
                "gap_at_current_pass": 4.0,
                "gap_closure_pct": 60.0,
                "gap_delta_last_pass": -6.0,
                "allocated_cumulative": 6.0,
                "clipped_total_current": 0.0,
                "unresolved_count_current": 0,
                "trend": "converging",
                "unresolved_fuels_current": "",
            }
        ],
        columns=legacy_columns,
    ).to_csv(convergence_path, index=False)

    result = build_capacity_unmet_run_diagnostics(
        state_path=state_path,
        convergence_csv_path=convergence_path,
        write_csv=False,
        print_summary=False,
    )

    assert result["run_id"] == ""
    assert result["summary"]["passes_executed"] == 1
    assert result["summary"]["first_gap"] == pytest.approx(10.0)
    assert result["summary"]["final_gap"] == pytest.approx(4.0)
    assert result["per_fuel"].empty
