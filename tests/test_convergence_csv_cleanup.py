"""Tests for convergence CSV cleanup helpers in supply_reconciliation_history."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import json

from codebase.supply_reconciliation_history import (
    CONVERGENCE_CSV_COLUMNS,
    clear_convergence_csv,
    load_convergence_csv,
    remove_convergence_run,
    rollback_last_capacity_unmet_pass,
    build_convergence_input_fingerprints,
    compare_convergence_manifest_inputs,
    load_convergence_run_manifest,
    prune_convergence_history,
    trim_convergence_csv_to_pass,
    write_convergence_run_manifest,
)

_COLUMNS = CONVERGENCE_CSV_COLUMNS


def _make_csv(path: Path, pass_counts: list[int], run_id: str = "run_a") -> None:
    rows = [
        {
            "run_id": run_id,
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
    frame = pd.DataFrame(rows, columns=_COLUMNS)
    if path.exists():
        existing = pd.read_csv(path)
        frame = pd.concat([existing, frame], ignore_index=True)
    frame.to_csv(path, index=False)


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


def test_trim_to_mid_pass_is_scoped_to_run_id(tmp_path):
    csv = tmp_path / "convergence.csv"
    _make_csv(csv, [1, 2, 3], run_id="run_a")
    _make_csv(csv, [1, 2, 3], run_id="run_b")

    trim_convergence_csv_to_pass(2, csv_path=csv, run_id="run_b")

    df = pd.read_csv(csv)
    assert list(df[df["run_id"] == "run_a"]["pass_count"]) == [1, 2, 3]
    assert list(df[df["run_id"] == "run_b"]["pass_count"]) == [1, 2]


def test_load_convergence_csv_adds_blank_run_id_for_legacy_csv(tmp_path):
    csv = tmp_path / "legacy.csv"
    legacy_columns = [column for column in _COLUMNS if column != "run_id"]
    pd.DataFrame(
        [
            {
                column: "" if column != "pass_count" else 1
                for column in legacy_columns
            }
        ],
        columns=legacy_columns,
    ).to_csv(csv, index=False)

    df = load_convergence_csv(csv)

    assert list(df.columns)[0] == "run_id"
    assert df["run_id"].tolist() == [""]


def test_remove_convergence_run_removes_latest_run_by_default(tmp_path):
    csv = tmp_path / "convergence.csv"
    _make_csv(csv, [1, 2], run_id="run_a")
    _make_csv(csv, [1, 2], run_id="run_b")

    remove_convergence_run(csv_path=csv)

    df = pd.read_csv(csv)
    assert set(df["run_id"]) == {"run_a"}
    assert list(df["pass_count"]) == [1, 2]


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
            {"pass_index": 1, "run_id": "run_a", "mode": "balanced", "timestamp_utc": "2026-01-01T00:00:00+00:00",
             "capacity_additions": {}, "output_additions": {}, "primary_additions": {},
             "export_adjustments": {}, "pre_pass_signatures": {}},
            {"pass_index": 2, "run_id": "run_a", "mode": "balanced", "timestamp_utc": "2026-01-02T00:00:00+00:00",
             "capacity_additions": {}, "output_additions": {}, "primary_additions": {},
             "export_adjustments": {}, "pre_pass_signatures": {}},
            {"pass_index": 3, "run_id": "run_a", "mode": "balanced", "timestamp_utc": "2026-01-03T00:00:00+00:00",
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


def test_manifest_round_trip_and_input_drift_are_additive(tmp_path):
    source = tmp_path / "esto.csv"
    source.write_text("first", encoding="utf-8")
    template = tmp_path / "template.xlsx"
    template.write_text("template", encoding="utf-8")
    paths = {"esto_csv": source, "export_template": template}
    fingerprints = build_convergence_input_fingerprints(paths)

    manifest_path = write_convergence_run_manifest(
        run_id="run_a",
        economies=["01_AUS"],
        scenarios=["Target"],
        mode="capacity_unmet_iterative_balanced",
        iteration_run_mode="results_update",
        input_paths=paths,
        input_fingerprints=fingerprints,
        runtime_dir=tmp_path,
    )

    manifest = load_convergence_run_manifest("run_a", runtime_dir=tmp_path)
    assert manifest_path.exists()
    assert manifest["economies"] == ["01_AUS"]
    assert manifest["input_fingerprints"] == fingerprints
    assert compare_convergence_manifest_inputs("run_a", paths, runtime_dir=tmp_path) == {}

    source.write_text("changed", encoding="utf-8")
    drift = compare_convergence_manifest_inputs("run_a", paths, runtime_dir=tmp_path)
    assert set(drift) == {"esto_csv"}


def test_prune_convergence_history_defaults_to_dry_run_and_keeps_latest(tmp_path):
    csv_path = tmp_path / "convergence.csv"
    _make_csv(csv_path, [1], run_id="run_a")
    _make_csv(csv_path, [1], run_id="run_b")
    _make_csv(csv_path, [1], run_id="run_c")
    paths = {"source": tmp_path / "source.csv"}
    paths["source"].write_text("source", encoding="utf-8")
    for run_id in ("run_a", "run_b", "run_c"):
        write_convergence_run_manifest(
            run_id=run_id,
            economies=["01_AUS"], scenarios=["Target"], mode="balanced",
            iteration_run_mode="results_update", input_paths=paths, runtime_dir=tmp_path,
        )

    preview = prune_convergence_history(keep_runs=1, csv_path=csv_path, runtime_dir=tmp_path)
    assert preview["dry_run"] is True
    assert preview["removed_run_ids"] == ["run_a", "run_b"]
    assert set(pd.read_csv(csv_path)["run_id"]) == {"run_a", "run_b", "run_c"}

    result = prune_convergence_history(
        keep_runs=1, csv_path=csv_path, runtime_dir=tmp_path, dry_run=False,
    )
    assert result["removed_run_ids"] == ["run_a", "run_b"]
    assert set(pd.read_csv(csv_path)["run_id"]) == {"run_c"}
    assert load_convergence_run_manifest("run_a", runtime_dir=tmp_path) is None
    assert load_convergence_run_manifest("run_c", runtime_dir=tmp_path) is not None
