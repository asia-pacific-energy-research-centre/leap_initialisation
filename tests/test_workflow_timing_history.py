"""Focused coverage for horizon-aware workflow timing history."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from codebase.utilities import workflow_common


def _write_history_record(path, *, duration_seconds: float = 10.0) -> None:
    pd.DataFrame(
        [
            {
                "workflow": "test",
                "stage_order": 1,
                "stage": "setup",
                "status": "success",
                "duration_seconds": duration_seconds,
            }
        ]
    ).to_csv(path, index=False)


def test_timer_history_filename_includes_actual_horizon(tmp_path) -> None:
    output_path = tmp_path / "workflow_stage_timings.csv"
    timer = workflow_common.WorkflowTimer("test", print_each=False)
    timer.set_metadata(
        economies=["01_AUS"],
        scenarios=["Reference"],
        year_start=2022,
        year_end=2023,
        n_years=2,
    )
    record = timer.lap("setup")
    assert {"rss_start_bytes", "rss_end_bytes", "rss_delta_bytes"}.issubset(record)
    timer.write_csv(output_path)

    history_files = list((tmp_path / "history").glob("*.csv"))
    assert len(history_files) == 1
    metadata = workflow_common._parse_history_filename(history_files[0].name)
    assert metadata["year_start"] == 2022
    assert metadata["year_end"] == 2023
    assert metadata["n_years"] == 2


def test_history_summary_filters_to_requested_horizon_and_reads_legacy_names(tmp_path) -> None:
    output_path = tmp_path / "workflow_stage_timings.csv"
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    stamp = datetime(2026, 7, 22, 12, 0, 0)

    two_year_name = workflow_common._encode_history_stem(
        output_path.stem, stamp, 1, 1, "full", "nocommit", 2022, 2023, 2
    )
    full_horizon_name = workflow_common._encode_history_stem(
        output_path.stem, stamp, 1, 1, "full", "nocommit", 2022, 2070, 49
    )
    legacy_name = "workflow_stage_timings_20260722_120001_e1_s1_full_nocommit"
    _write_history_record(history_dir / f"{two_year_name}.csv", duration_seconds=10)
    _write_history_record(history_dir / f"{full_horizon_name}.csv", duration_seconds=100)
    _write_history_record(history_dir / f"{legacy_name}.csv", duration_seconds=1_000)

    legacy_metadata = workflow_common._parse_history_filename(f"{legacy_name}.csv")
    assert legacy_metadata["year_start"] is None
    assert legacy_metadata["n_years"] is None

    summary = workflow_common.load_history_summary(
        output_path,
        n_economies=1,
        n_scenarios=1,
        run_type="full",
        year_start=2022,
        year_end=2023,
        n_years=2,
        current_commit="nocommit",
    )

    assert summary is not None
    assert summary.loc[0, "n_runs"] == 1
    assert summary.loc[0, "avg_duration_seconds"] == 10.0
