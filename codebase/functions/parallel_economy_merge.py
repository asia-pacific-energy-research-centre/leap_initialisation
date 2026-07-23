"""Deterministic parent merge for bounded process-based economy parallelism.

Scope, deliberately narrow (docs/prompts/continuation_20260722_phase4_parallelism_and_release_readiness.md
and docs/current_execution_roadmap.md flagged this as still-open work needing
its own design pass, not a rushed add-on to
``codebase/functions/parallel_economy_runner.py``):

* This module merges only the **consolidated baseline-seed validation
  findings** (``baseline_seed_<stamp>_consolidated_rule_findings.csv`` and
  ``..._consolidated_issue_groups.csv``) across a set of parallel workers.
  Each worker already writes these two files for its own single economy;
  merging is a safe, deterministic concatenation because
  ``codebase/functions/supply_leap_io.py``'s sequential multi-economy writer
  builds them the exact same way - by looping over economies and
  concatenating each economy's own findings, tagged with an ``economy``
  column, then recomputing issue groups from the concatenated frame with
  ``build_validation_issue_groups``. A worker with ``ECONOMIES=[economy]`` is
  already computing that same per-economy slice correctly in isolation
  (verified: SEED-012 producer-coverage findings are resolved from paths
  under the worker's own isolated output tree, not a cross-process view, so a
  single-economy worker's own consolidated findings file already contains
  everything the sequential path would have contributed for that economy).
* **NOT included**: merging the single-file combined workbook
  (``supply_recon_run_baseline_seed_<economies>_<scenarios>.xlsx``) that a
  sequential multi-economy run also produces. Reconstructing its exact
  preamble/header/column layout from N independent per-economy workbooks is
  a separate, higher-risk task - producing malformed LEAP-import structure
  would be a silent defect, not a loud one - and needs its own verification
  pass (built and diffed against a real sequential multi-economy run) before
  being attempted. Each worker's own per-economy seed workbook
  (``leap_import_baseline_seed_<economy>_<date>.xlsx``) is already correct
  and complete on its own and needs no merging.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pandas as pd

import codebase.supply_reconciliation_config as _supply_reconciliation_config
from codebase.functions.baseline_seed_validation import build_validation_issue_groups
from codebase.functions.parallel_economy_runner import EconomyWorkerResult

_FINDINGS_COLUMNS = (
    "economy", "rule_id", "status", "severity", "blocking", "description",
    "scope", "message", "evidence", "documentation_reference", "Branch Path",
    "Variable", "Scenario", "Region", "source_workflow", "source_file",
    "year", "exception_applied", "exception_id", "exception_reason",
)


def worker_output_dir(result: EconomyWorkerResult, *, pass_mode: str = "baseline_seed") -> Path:
    """Resolve a worker's isolated output directory from its own snapshot label.

    Uses the same ``ReconciliationRunContext`` resolution the workflow itself
    uses, so this can never disagree with where the worker actually wrote.
    """
    context = _supply_reconciliation_config.resolve_reconciliation_run_context(
        pass_mode,
        result.snapshot.run_output_label,
    )
    return context.output_dir


def _read_consolidated_findings_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=_FINDINGS_COLUMNS)
    try:
        frame = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=_FINDINGS_COLUMNS)
    return frame


def merge_consolidated_baseline_seed_findings(
    results: Sequence[EconomyWorkerResult],
    *,
    run_stamp: str,
    output_dir: Path | str,
    pass_mode: str = "baseline_seed",
    economies_run_order: Sequence[str] | None = None,
) -> tuple[Path, Path]:
    """Merge each successful worker's consolidated findings into one parent file.

    Skips workers that did not succeed (``result.succeeded`` is False) -
    their findings are incomplete/unreliable by definition, not a "no
    findings" result, and must not be silently read as a clean pass. Row
    order is deterministic: workers are sorted by their position in
    ``economies_run_order`` when supplied (workers for economies not present
    in that order sort after, in economy-name order, so the output is stable
    even for an ad-hoc economy list), then by ``rule_id`` within an economy.
    Writes both the merged findings CSV and issue-groups CSV (the latter
    freshly recomputed from the merged frame via
    ``build_validation_issue_groups``, matching how the sequential writer
    builds it - never a merge of separately-computed group ids, which could
    collide across independently-run workers) under
    ``output_dir/supporting_files/baseline_seed_validation/``.
    """
    order = {str(econ): index for index, econ in enumerate(economies_run_order or ())}

    frames: list[pd.DataFrame] = []
    for result in results:
        if not result.succeeded:
            continue
        worker_dir = worker_output_dir(result, pass_mode=pass_mode)
        findings_path = (
            worker_dir
            / "supporting_files"
            / "baseline_seed_validation"
            / f"baseline_seed_{run_stamp}_consolidated_rule_findings.csv"
        )
        frame = _read_consolidated_findings_csv(findings_path)
        if frame.empty:
            continue
        frame = frame.copy()
        frame["__economy_order"] = frame.get("economy", result.economy).map(
            lambda econ: order.get(str(econ), len(order))
        )
        frames.append(frame)

    if frames:
        merged = pd.concat(frames, ignore_index=True, sort=False)
        sort_cols = [c for c in ("__economy_order", "rule_id") if c in merged.columns]
        if sort_cols:
            merged = merged.sort_values(sort_cols, kind="stable").reset_index(drop=True)
        merged = merged.drop(columns=["__economy_order"], errors="ignore")
    else:
        merged = pd.DataFrame(columns=_FINDINGS_COLUMNS)

    out_dir = Path(output_dir) / "supporting_files" / "baseline_seed_validation"
    out_dir.mkdir(parents=True, exist_ok=True)
    findings_out = out_dir / f"baseline_seed_{run_stamp}_consolidated_rule_findings.csv"
    merged.to_csv(findings_out, index=False)

    issue_groups_out = out_dir / f"baseline_seed_{run_stamp}_consolidated_issue_groups.csv"
    build_validation_issue_groups(merged).to_csv(issue_groups_out, index=False)

    return findings_out, issue_groups_out
