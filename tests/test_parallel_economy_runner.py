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


# ---------------------------------------------------------------------------
# Resource diagnostics: peak RSS per worker + a portable machine-spec file,
# so a worker-count decision measured here can be checked on another PC.
# ---------------------------------------------------------------------------

_SLOW_FAKE_WORKER_SCRIPT = textwrap.dedent(
    """
    import json
    import os
    import time

    payload = json.loads(os.environ["LEAP_WORKER_SNAPSHOT_JSON"])
    economy = payload["economies"][0]
    # Hold onto some real memory for long enough that at least one poll tick
    # samples this process before it exits.
    _hold = bytearray(20 * 1024 * 1024)  # 20MB
    print(f"worker for {economy} saw label={payload.get('run_output_label')}")
    time.sleep(0.3)
    """
)


def test_run_economies_in_parallel_records_peak_rss_per_worker(tmp_path, monkeypatch) -> None:
    fake_script = tmp_path / "slow_fake_worker.py"
    fake_script.write_text(_SLOW_FAKE_WORKER_SCRIPT, encoding="utf-8")
    monkeypatch.setattr(runner, "WORKFLOW_SCRIPT_PATH", fake_script)

    snapshots = runner.build_worker_snapshots(["01_AUS"], base_run_output_label="RSS")
    results = runner.run_economies_in_parallel(
        snapshots,
        max_workers=1,
        log_directory=tmp_path / "logs",
        python_executable=sys.executable,
        poll_interval_seconds=0.05,
    )

    assert len(results) == 1
    assert results[0].succeeded
    assert results[0].peak_rss_bytes is not None
    assert results[0].peak_rss_bytes > 0


def test_run_economies_in_parallel_writes_resource_diagnostics_file(tmp_path, monkeypatch) -> None:
    fake_script = tmp_path / "slow_fake_worker.py"
    fake_script.write_text(_SLOW_FAKE_WORKER_SCRIPT, encoding="utf-8")
    monkeypatch.setattr(runner, "WORKFLOW_SCRIPT_PATH", fake_script)

    log_dir = tmp_path / "logs"
    snapshots = runner.build_worker_snapshots(
        ["01_AUS", "12_NZ"], base_run_output_label="RSS"
    )
    runner.run_economies_in_parallel(
        snapshots,
        max_workers=2,
        log_directory=log_dir,
        python_executable=sys.executable,
        poll_interval_seconds=0.05,
    )

    diagnostics_path = log_dir / "concurrency_resource_diagnostics.json"
    assert diagnostics_path.exists()
    payload = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    assert payload["max_workers_configured"] == 2
    assert payload["system_before_run"]["logical_cpu_count"] > 0
    assert payload["system_before_run"]["total_ram_gb"] > 0
    assert payload["peak_aggregate_rss_bytes"] > 0
    assert "peak_exceeded_pre_run_available_ram" in payload
    assert {entry["economy"] for entry in payload["per_worker"]} == {"01_AUS", "12_NZ"}
    for entry in payload["per_worker"]:
        assert entry["peak_rss_bytes"] > 0


def test_resource_diagnostics_headroom_is_judged_against_pre_run_available_ram(
    tmp_path, monkeypatch
) -> None:
    """Headroom must reflect what else was already running on the machine,
    not total RAM - that's the whole point of measuring pre-run available RAM
    rather than total capacity."""
    import codebase.functions.parallel_economy_runner as runner_module
    from codebase.utilities.system_resources import SystemResourceSnapshot

    fake_script = tmp_path / "slow_fake_worker.py"
    fake_script.write_text(_SLOW_FAKE_WORKER_SCRIPT, encoding="utf-8")
    monkeypatch.setattr(runner, "WORKFLOW_SCRIPT_PATH", fake_script)

    # Simulate a machine with very little free RAM already (other apps busy).
    tiny_available = SystemResourceSnapshot(
        hostname="test-host",
        platform="test-platform",
        logical_cpu_count=8,
        physical_cpu_count=4,
        total_ram_bytes=32 * 1024 ** 3,
        available_ram_bytes=1,  # essentially nothing free before this run
    )
    monkeypatch.setattr(
        runner_module, "get_system_resource_snapshot", lambda: tiny_available
    )

    log_dir = tmp_path / "logs"
    snapshots = runner.build_worker_snapshots(["01_AUS"], base_run_output_label="RSS")
    runner.run_economies_in_parallel(
        snapshots,
        max_workers=1,
        log_directory=log_dir,
        python_executable=sys.executable,
        poll_interval_seconds=0.05,
    )

    payload = json.loads(
        (log_dir / "concurrency_resource_diagnostics.json").read_text(encoding="utf-8")
    )
    assert payload["peak_exceeded_pre_run_available_ram"] is True
    assert payload["available_ram_headroom_gb_at_peak"] < 0


def test_run_economies_in_parallel_skips_diagnostics_when_disabled(tmp_path, monkeypatch) -> None:
    fake_script = tmp_path / "fake_worker.py"
    fake_script.write_text(_FAKE_WORKER_SCRIPT, encoding="utf-8")
    monkeypatch.setattr(runner, "WORKFLOW_SCRIPT_PATH", fake_script)

    log_dir = tmp_path / "logs"
    snapshots = runner.build_worker_snapshots(["01_AUS"], base_run_output_label="RSS")
    results = runner.run_economies_in_parallel(
        snapshots,
        max_workers=1,
        log_directory=log_dir,
        python_executable=sys.executable,
        poll_interval_seconds=0.05,
        record_resource_diagnostics=False,
    )

    assert results[0].peak_rss_bytes is None
    assert not (log_dir / "concurrency_resource_diagnostics.json").exists()
