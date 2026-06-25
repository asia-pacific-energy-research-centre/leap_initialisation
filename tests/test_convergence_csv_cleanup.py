"""Tests for convergence CSV cleanup helpers in supply_reconciliation_history."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import json

from codebase.supply_reconciliation_history import (
    clear_convergence_csv,
    rollback_last_capacity_unmet_pass,
    trim_convergence_csv_to_pass,
)

_COLUMNS = [
    "timestamp_utc",
    "mode",
    "iteration_run_mode",
    "pass_count",
    "gap_at_first_pass",
    "gap_at_current_pass",
    "gap_closure_pct",
    "gap_delta_last_pass",
    "allocated_cumulative",
    "clipped_total_current",
    "unresolved_count_current",
    "trend",
    "unresolved_fuels_current",
]


def _make_csv(path: Path, pass_counts: list[int]) -> None:
    rows = [
        {
            "timestamp_utc": f"2026-01-0{i+1}T00:00:00+00:00",
            "mode": "balanced",
            "iteration_run_mode": "results_update",
            "pass_count": pc,
            "gap_at_first_pass": 100.0,
            "gap_at_current_pass": float(100 - pc * 10),
            "gap_closure_pct": float(pc * 10),
            "gap_delta_last_pass": -10.0,
            "allocated_cumulative": float(pc * 5),
            "clipped_total_current": 0.0,
            "unresolved_count_current": 0,
            "trend": "improving",
            "unresolved_fuels_current": "",
        }
        for i, pc in enumerate(pass_counts)
    ]
    pd.DataFrame(rows, columns=_COLUMNS).to_csv(path, index=False)


def test_trim_to_pass_zero_removes_all_data_rows(tmp_path):
    csv = tmp_path / "convergence.csv"
    _make_csv(csv, [1, 2, 3])

    trim_convergence_csv_to_pass(0, csv_path=csv)

    df = pd.read_csv(csv)
    assert list(df.columns) == _COLUMNS
    assert len(df) == 0


def test_trim_to_mid_pass_keeps_earlier_rows(tmp_path):
    csv = tmp_path / "convergence.csv"
    _make_csv(csv, [1, 2, 3, 4, 5])

    trim_convergence_csv_to_pass(3, csv_path=csv)

    df = pd.read_csv(csv)
    assert list(df["pass_count"]) == [1, 2, 3]


def test_clear_convergence_csv_leaves_header_only(tmp_path):
    csv = tmp_path / "convergence.csv"
    _make_csv(csv, [1, 2, 3])

    clear_convergence_csv(csv_path=csv)

    df = pd.read_csv(csv)
    assert list(df.columns) == _COLUMNS
    assert len(df) == 0


def test_trim_no_op_when_file_missing(tmp_path):
    missing = tmp_path / "does_not_exist.csv"
    trim_convergence_csv_to_pass(5, csv_path=missing)
    assert not missing.exists()


def test_clear_no_op_when_file_missing(tmp_path):
    missing = tmp_path / "does_not_exist.csv"
    clear_convergence_csv(csv_path=missing)
    assert not missing.exists()


def test_rollback_also_trims_convergence_csv(tmp_path):
    state = {
        "passes": ["pass1", "pass2", "pass3"],
        "pass_deltas": [
            {"pass_index": 1, "mode": "balanced", "timestamp_utc": "2026-01-01T00:00:00+00:00",
             "capacity_additions": {}, "output_additions": {}, "primary_additions": {},
             "export_adjustments": {}, "pre_pass_signatures": {}},
            {"pass_index": 2, "mode": "balanced", "timestamp_utc": "2026-01-02T00:00:00+00:00",
             "capacity_additions": {}, "output_additions": {}, "primary_additions": {},
             "export_adjustments": {}, "pre_pass_signatures": {}},
            {"pass_index": 3, "mode": "balanced", "timestamp_utc": "2026-01-03T00:00:00+00:00",
             "capacity_additions": {}, "output_additions": {}, "primary_additions": {},
             "export_adjustments": {}, "pre_pass_signatures": {}},
        ],
        "cumulative_capacity_additions": {},
        "cumulative_output_additions": {},
        "cumulative_primary_additions": {},
        "cumulative_export_adjustments": {},
        "last_results_signatures": {},
    }
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    csv_path = tmp_path / "convergence.csv"
    _make_csv(csv_path, [1, 2, 3])

    rollback_last_capacity_unmet_pass(state_path=state_path, convergence_csv_path=csv_path)

    df = pd.read_csv(csv_path)
    assert list(df["pass_count"]) == [1, 2]
