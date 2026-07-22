"""Tests for the bounded process-based parallel economy orchestrator.

Uses a tiny throwaway Python script in place of the real (multi-hour)
``supply_reconciliation_workflow.py`` so these tests run in milliseconds and
never touch ``outputs/`` or acquire an economy run lock.
"""
from __future__ import annotations

import json
import sys
import textwrap

import pytest

from codebase.functions import parallel_economy_runner as runner


def test_build_worker_snapshots_gives_each_economy_a_distinct_label() -> None:
    snapshots = runner.build_worker_snapshots(
        ["01_AUS", "12_NZ"],
        base_run_output_label="SMOKE",
        test_horizon_base_year_plus_one=True,
    )
    assert [s.economy for s in snapshots] == ["01_AUS", "12_NZ"]
    labels = {s.run_output_label for s in snapshots}
    assert labels == {"SMOKE_01_AUS", "SMOKE_12_NZ"}
    assert all(s.test_horizon_base_year_plus_one is True for s in snapshots)


def test_build_worker_snapshots_rejects_blank_base_label() -> None:
    with pytest.raises(ValueError):
        runner.build_worker_snapshots(["01_AUS"], base_run_output_label="  ")


def test_build_worker_snapshots_rejects_duplicate_economies() -> None:
    with pytest.raises(ValueError):
        runner.build_worker_snapshots(["01_AUS", "01_AUS"], base_run_output_label="SMOKE")


def test_snapshot_env_json_round_trips() -> None:
    snapshot = runner.EconomyWorkerSnapshot(
        economy="01_AUS",
        run_output_label="SMOKE_01_AUS",
        test_horizon_base_year_plus_one=True,
    )
    payload = json.loads(snapshot.to_env_json())
    assert payload == {
        "economies": ["01_AUS"],
        "run_output_label": "SMOKE_01_AUS",
        "test_horizon_base_year_plus_one": True,
    }


_FAKE_WORKER_SCRIPT = textwrap.dedent(
    """
    import json
    import os
    import sys

    payload = json.loads(os.environ["LEAP_WORKER_SNAPSHOT_JSON"])
    economy = payload["economies"][0]
    print(f"worker for {economy} saw label={payload.get('run_output_label')}")
    if economy == "FAIL_ME":
        sys.exit(3)
    sys.exit(0)
    """
)


def test_run_economies_in_parallel_reports_one_result_per_snapshot(tmp_path, monkeypatch) -> None:
    fake_script = tmp_path / "fake_worker.py"
    fake_script.write_text(_FAKE_WORKER_SCRIPT, encoding="utf-8")
    monkeypatch.setattr(runner, "WORKFLOW_SCRIPT_PATH", fake_script)

    snapshots = runner.build_worker_snapshots(
        ["01_AUS", "12_NZ"], base_run_output_label="SMOKE"
    )
    results = runner.run_economies_in_parallel(
        snapshots,
        max_workers=2,
        log_directory=tmp_path / "logs",
        python_executable=sys.executable,
        poll_interval_seconds=0.05,
    )

    assert {r.economy for r in results} == {"01_AUS", "12_NZ"}
    for result in results:
        assert result.succeeded
        assert result.returncode == 0
        assert result.stdout_log.exists()
        contents = result.stdout_log.read_text(encoding="utf-8")
        assert f"worker for {result.economy}" in contents
        assert f"SMOKE_{result.economy}" in contents


def test_run_economies_in_parallel_respects_max_workers_of_one(tmp_path, monkeypatch) -> None:
    fake_script = tmp_path / "fake_worker.py"
    fake_script.write_text(_FAKE_WORKER_SCRIPT, encoding="utf-8")
    monkeypatch.setattr(runner, "WORKFLOW_SCRIPT_PATH", fake_script)

    snapshots = runner.build_worker_snapshots(
        ["01_AUS", "12_NZ", "20_USA"], base_run_output_label="SMOKE"
    )
    results = runner.run_economies_in_parallel(
        snapshots,
        max_workers=1,
        log_directory=tmp_path / "logs",
        python_executable=sys.executable,
        poll_interval_seconds=0.05,
    )

    assert len(results) == 3
    assert all(r.succeeded for r in results)


def test_run_economies_in_parallel_captures_a_failing_worker(tmp_path, monkeypatch) -> None:
    fake_script = tmp_path / "fake_worker.py"
    fake_script.write_text(_FAKE_WORKER_SCRIPT, encoding="utf-8")
    monkeypatch.setattr(runner, "WORKFLOW_SCRIPT_PATH", fake_script)

    snapshots = runner.build_worker_snapshots(
        ["01_AUS", "FAIL_ME"], base_run_output_label="SMOKE"
    )
    results = runner.run_economies_in_parallel(
        snapshots,
        max_workers=2,
        log_directory=tmp_path / "logs",
        python_executable=sys.executable,
        poll_interval_seconds=0.05,
    )

    by_economy = {r.economy: r for r in results}
    assert by_economy["01_AUS"].succeeded
    assert not by_economy["FAIL_ME"].succeeded
    assert by_economy["FAIL_ME"].returncode == 3


def test_run_economies_in_parallel_rejects_zero_workers(tmp_path) -> None:
    with pytest.raises(ValueError):
        runner.run_economies_in_parallel(
            [runner.EconomyWorkerSnapshot(economy="01_AUS")],
            max_workers=0,
            log_directory=tmp_path / "logs",
        )


def test_run_economies_in_parallel_empty_snapshots_returns_empty(tmp_path) -> None:
    assert runner.run_economies_in_parallel([], log_directory=tmp_path / "logs") == []
