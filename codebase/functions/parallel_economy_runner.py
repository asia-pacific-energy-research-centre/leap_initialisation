"""Bounded process-based parallel economy runner for the supply reconciliation workflow.

Design constraints (see docs/prompts/continuation_20260722_phase4_parallelism_and_release_readiness.md):

* Process-based only, never thread-based. ``supply_results_saver.py`` already
  rejects ``PARALLEL_ECONOMY_WORKERS > 1`` in-process because that path shares
  one interpreter's mirrored module globals (``from ... import *`` copies of
  config in every extracted module); a shared-interpreter worker pool would
  silently corrupt results. A separate OS process per economy has its own
  interpreter and its own copy of every module global, so that failure mode
  cannot occur here.
* Each worker gets an explicit, immutable snapshot (economy, run label, test
  horizon) delivered via the ``LEAP_WORKER_SNAPSHOT_JSON`` environment
  variable, applied by
  ``supply_reconciliation_workflow._apply_worker_snapshot_overrides`` before
  anything else in that process resolves paths or runs. Workers are never
  given a shared ``ECONOMIES`` list to read from the source file.
* Each snapshot gets its own ``run_output_label``, which — via the existing
  ``ReconciliationRunContext`` path resolution — already isolates every
  per-run artifact family (output dir, results runtime dir, results checks
  dir, capacity-unmet iterative-state JSON, workflow timing CSV, convergence
  CSV). No new artifact-scoping mechanism is introduced; distinct labels are
  the whole isolation story for those files.
* Per-economy output-file collisions and the "same economy already running"
  case are already handled by ``codebase/utilities/economy_run_lock.py``,
  which each worker process calls into via
  ``supply_reconciliation_workflow._run_with_config_inner``. This module does
  not duplicate that locking.
* ``max_workers`` defaults to 1 (fully sequential, one subprocess at a time),
  keeping parallelism strictly opt-in.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from codebase.utilities.system_resources import (
    get_system_resource_snapshot,
    process_rss_bytes,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_SCRIPT_PATH = REPO_ROOT / "codebase" / "supply_reconciliation_workflow.py"


@dataclass(frozen=True)
class EconomyWorkerSnapshot:
    """Immutable per-process run snapshot for exactly one economy worker."""

    economy: str
    run_output_label: str | None = None
    test_horizon_base_year_plus_one: bool | None = None

    def to_env_json(self) -> str:
        payload: dict[str, object] = {"economies": [self.economy]}
        if self.run_output_label is not None:
            payload["run_output_label"] = self.run_output_label
        if self.test_horizon_base_year_plus_one is not None:
            payload["test_horizon_base_year_plus_one"] = self.test_horizon_base_year_plus_one
        return json.dumps(payload)


@dataclass(frozen=True)
class EconomyWorkerResult:
    economy: str
    snapshot: EconomyWorkerSnapshot
    returncode: int
    stdout_log: Path
    stderr_log: Path
    started_at: float
    ended_at: float
    # This worker process's own peak resident memory over its lifetime, or
    # None if it was never sampled (e.g. it exited between poll ticks).
    peak_rss_bytes: int | None = None

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0

    @property
    def duration_seconds(self) -> float:
        return self.ended_at - self.started_at


def build_worker_snapshots(
    economies: Sequence[str],
    *,
    base_run_output_label: str,
    test_horizon_base_year_plus_one: bool | None = None,
) -> list[EconomyWorkerSnapshot]:
    """Build one isolated snapshot per economy from an explicit base label.

    Each economy's ``run_output_label`` is ``f"{base_run_output_label}_{economy}"``
    — a distinct label per worker, which is what gives each worker its own
    isolated output tree via the existing run-context path resolution. Raises
    on a blank base label or a duplicate economy rather than silently
    collapsing two workers onto the same label.
    """
    if not base_run_output_label or not base_run_output_label.strip():
        raise ValueError("base_run_output_label must be a non-empty explicit label")
    seen: set[str] = set()
    snapshots: list[EconomyWorkerSnapshot] = []
    for economy in economies:
        token = str(economy).strip()
        if not token:
            continue
        if token in seen:
            raise ValueError(f"Duplicate economy in parallel worker list: {token}")
        seen.add(token)
        snapshots.append(
            EconomyWorkerSnapshot(
                economy=token,
                run_output_label=f"{base_run_output_label.strip()}_{token}",
                test_horizon_base_year_plus_one=test_horizon_base_year_plus_one,
            )
        )
    return snapshots


@dataclass
class _RunningWorker:
    snapshot: EconomyWorkerSnapshot
    process: subprocess.Popen
    stdout_log: Path
    stderr_log: Path
    started_at: float
    _stdout_fh: object = field(repr=False)
    _stderr_fh: object = field(repr=False)
    peak_rss_bytes: int | None = None


def run_economies_in_parallel(
    snapshots: Sequence[EconomyWorkerSnapshot],
    *,
    max_workers: int = 1,
    log_directory: Path | str,
    python_executable: str | None = None,
    extra_env: dict[str, str] | None = None,
    poll_interval_seconds: float = 2.0,
    record_resource_diagnostics: bool = True,
) -> list[EconomyWorkerResult]:
    """Launch one OS process per economy snapshot, bounded to ``max_workers`` concurrent.

    Never threads and never shares an interpreter: each worker is a fresh
    ``subprocess.Popen`` running ``supply_reconciliation_workflow.py`` as
    ``__main__`` with its own environment, so the config globals that module
    (and its ``import *`` mirrors) rebind at import time cannot race between
    workers. Returns one :class:`EconomyWorkerResult` per snapshot, in
    completion order (not launch order) once every worker has terminated;
    this function blocks until all workers finish.

    When ``record_resource_diagnostics`` is True (default), each worker's
    resident memory (Working Set on Windows) is sampled at every poll tick
    via ``psutil`` and the per-worker peak is attached to its
    :class:`EconomyWorkerResult`. This machine's CPU/RAM and the observed
    peak *aggregate* concurrent memory across all workers (the number that
    actually determines whether a given ``max_workers`` is safe) are written
    to ``log_directory/concurrency_resource_diagnostics.json`` - the point is
    to let a worker-count decision measured on one machine be checked or
    re-derived on another, rather than assumed to transfer as-is.
    """
    if max_workers < 1:
        raise ValueError("max_workers must be >= 1")
    if not snapshots:
        return []

    interpreter = python_executable or sys.executable
    log_dir = Path(log_directory)
    log_dir.mkdir(parents=True, exist_ok=True)

    pending = list(snapshots)
    running: dict[str, _RunningWorker] = {}
    results: list[EconomyWorkerResult] = []
    peak_aggregate_rss_bytes = 0
    peak_concurrent_workers = 0

    def _launch(snapshot: EconomyWorkerSnapshot) -> None:
        stdout_log = log_dir / f"parallel_worker_{snapshot.economy}.log"
        stderr_log = log_dir / f"parallel_worker_{snapshot.economy}.err.log"
        env = dict(os.environ)
        if extra_env:
            env.update(extra_env)
        env["LEAP_WORKER_SNAPSHOT_JSON"] = snapshot.to_env_json()
        stdout_fh = open(stdout_log, "w", encoding="utf-8")
        stderr_fh = open(stderr_log, "w", encoding="utf-8")
        process = subprocess.Popen(
            [interpreter, str(WORKFLOW_SCRIPT_PATH)],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=stdout_fh,
            stderr=stderr_fh,
        )
        running[snapshot.economy] = _RunningWorker(
            snapshot=snapshot,
            process=process,
            stdout_log=stdout_log,
            stderr_log=stderr_log,
            started_at=time.time(),
            _stdout_fh=stdout_fh,
            _stderr_fh=stderr_fh,
        )

    try:
        while pending or running:
            while pending and len(running) < max_workers:
                _launch(pending.pop(0))

            if record_resource_diagnostics and running:
                tick_total = 0
                tick_sampled = 0
                for worker in running.values():
                    sample = process_rss_bytes(worker.process.pid)
                    if sample is None:
                        continue
                    tick_sampled += 1
                    tick_total += sample
                    if worker.peak_rss_bytes is None or sample > worker.peak_rss_bytes:
                        worker.peak_rss_bytes = sample
                if tick_sampled:
                    peak_aggregate_rss_bytes = max(peak_aggregate_rss_bytes, tick_total)
                    peak_concurrent_workers = max(peak_concurrent_workers, tick_sampled)

            finished = [
                economy for economy, worker in running.items()
                if worker.process.poll() is not None
            ]
            for economy in finished:
                worker = running.pop(economy)
                worker._stdout_fh.close()
                worker._stderr_fh.close()
                results.append(
                    EconomyWorkerResult(
                        economy=economy,
                        snapshot=worker.snapshot,
                        returncode=worker.process.returncode,
                        stdout_log=worker.stdout_log,
                        stderr_log=worker.stderr_log,
                        started_at=worker.started_at,
                        ended_at=time.time(),
                        peak_rss_bytes=worker.peak_rss_bytes,
                    )
                )
            if running:
                time.sleep(poll_interval_seconds)
    except BaseException:
        # Never leave orphaned child processes behind on an unexpected exit
        # (KeyboardInterrupt, etc.) — terminate anything still running.
        for worker in running.values():
            try:
                worker.process.terminate()
            finally:
                worker._stdout_fh.close()
                worker._stderr_fh.close()
        raise

    if record_resource_diagnostics:
        _write_resource_diagnostics(
            log_dir / "concurrency_resource_diagnostics.json",
            max_workers=max_workers,
            results=results,
            peak_aggregate_rss_bytes=peak_aggregate_rss_bytes,
            peak_concurrent_workers=peak_concurrent_workers,
        )

    return results


def _write_resource_diagnostics(
    path: Path,
    *,
    max_workers: int,
    results: Sequence[EconomyWorkerResult],
    peak_aggregate_rss_bytes: int,
    peak_concurrent_workers: int,
) -> None:
    """Write the machine spec plus measured peak memory for this run to ``path``.

    Portable by design: run this on a different machine and diff the two
    JSON files to see whether a worker count that was safe here is likely
    safe there, instead of assuming it transfers.
    """
    system = get_system_resource_snapshot()
    payload = {
        "system": system.to_dict(),
        "max_workers_configured": max_workers,
        "peak_concurrent_workers_observed": peak_concurrent_workers,
        "peak_aggregate_rss_bytes": peak_aggregate_rss_bytes,
        "peak_aggregate_rss_gb": round(peak_aggregate_rss_bytes / (1024 ** 3), 2),
        "available_ram_headroom_gb_at_peak": round(
            (system.total_ram_bytes - peak_aggregate_rss_bytes) / (1024 ** 3), 2
        ),
        "per_worker": [
            {
                "economy": r.economy,
                "peak_rss_bytes": r.peak_rss_bytes,
                "peak_rss_gb": (
                    round(r.peak_rss_bytes / (1024 ** 3), 2)
                    if r.peak_rss_bytes is not None
                    else None
                ),
                "duration_seconds": round(r.duration_seconds, 1),
                "succeeded": r.succeeded,
            }
            for r in results
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
