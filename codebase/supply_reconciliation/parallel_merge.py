"""Deterministic parent merge for bounded process-based economy parallelism.

Scope, deliberately narrow (docs/prompts/continuation_20260722_phase4_parallelism_and_release_readiness.md
and docs/current_execution_roadmap.md flagged this as still-open work needing
its own design pass, not a rushed add-on to
``codebase/supply_reconciliation/parallel_runner.py``):

* This module merges the **consolidated baseline-seed validation findings**
  (``baseline_seed_<stamp>_consolidated_rule_findings.csv`` and
  ``..._consolidated_issue_groups.csv``) across a set of parallel workers.
  Each worker already writes these two files for its own single economy;
  merging is a safe, deterministic concatenation because
  ``codebase/supply_reconciliation/leap_io.py``'s sequential multi-economy writer
  builds them the exact same way - by looping over economies and
  concatenating each economy's own findings, tagged with an ``economy``
  column, then recomputing issue groups from the concatenated frame with
  ``build_validation_issue_groups``. A worker with ``ECONOMIES=[economy]`` is
  already computing that same per-economy slice correctly in isolation
  (verified: SEED-012 producer-coverage findings are resolved from paths
  under the worker's own isolated output tree, not a cross-process view, so a
  single-economy worker's own consolidated findings file already contains
  everything the sequential path would have contributed for that economy).
* It also provides additive parent views for the per-worker source/template
  diagnostics and the two conservation summary/breakdown/lineage families.
  Worker files remain untouched; parent rows are tagged with their economy
  when a producer does not already emit that column.
Cross-economy workbooks are intentionally outside this module's scope. Both
parallel and sequential runs retain one assembled LEAP-import workbook per
economy, while the parent receives CSV-only diagnostic views.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pandas as pd

import codebase.supply_reconciliation.config as _supply_reconciliation_config
from codebase.functions.baseline_seed_validation import (
    build_branch_issue_summary,
    build_validation_issue_groups,
)
from codebase.supply_reconciliation.parallel_runner import EconomyWorkerResult
from codebase.utilities.typed_storage import (
    read_manifested_parquet_file,
    write_manifested_parquet,
)

_FINDINGS_COLUMNS = (
    "economy", "rule_id", "status", "severity", "blocking",
    "violated_rule_expectation",
    "scope", "message", "evidence", "documentation_reference", "Branch Path",
    "Variable", "Scenario", "Region", "source_workflow", "source_file",
    "year", "exception_applied", "exception_id", "exception_reason",
)
_PARALLEL_DIAGNOSTIC_FILENAMES = (
    "supply_reconciliation_source_diagnostics.csv",
    "supply_reconciliation_balance_demand_conservation.csv",
    "supply_reconciliation_balance_demand_conservation_breakdown.csv",
    "supply_reconciliation_balance_demand_conservation_lineage.parquet",
    "supply_reconciliation_transformation_output_conservation.csv",
    "supply_reconciliation_transformation_output_conservation_breakdown.csv",
    "supply_reconciliation_transformation_output_conservation_lineage.parquet",
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
    # Older worker outputs called the failed invariant "description", which
    # reads as though the finding itself were being described. Normalize that
    # legacy heading so newly merged reports use the clearer human-facing name.
    legacy_column = "description"
    expectation_column = "violated_rule_expectation"
    if legacy_column in frame.columns:
        if expectation_column in frame.columns:
            missing_expectation = frame[expectation_column].isna()
            frame.loc[missing_expectation, expectation_column] = frame.loc[
                missing_expectation,
                legacy_column,
            ]
            frame = frame.drop(columns=[legacy_column])
        else:
            frame = frame.rename(columns={legacy_column: expectation_column})
    return frame


def _read_diagnostic_table(path: Path) -> pd.DataFrame:
    """Read one worker CSV or manifested Parquet diagnostic."""
    if not path.exists():
        return pd.DataFrame()
    if path.suffix.casefold() == ".parquet":
        return read_manifested_parquet_file(path)
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def merge_parallel_diagnostic_families(
    results: Sequence[EconomyWorkerResult],
    *,
    output_dir: Path | str,
    pass_mode: str = "baseline_seed",
    economies_run_order: Sequence[str] | None = None,
) -> dict[str, Path]:
    """Write deterministic cross-economy views of worker diagnostic CSVs.

    Only successful workers contribute. A missing optional diagnostic is not
    treated as a clean result and contributes no rows; the parent view is still
    written so consumers have one stable path for every supported family.
    Existing ``economy`` values are preserved, while blank or absent values
    are filled from the isolated worker snapshot. Worker files are read-only.
    """
    order = {
        str(economy).strip(): index
        for index, economy in enumerate(economies_run_order or ())
        if str(economy).strip()
    }
    successful = [result for result in results if result.succeeded]
    successful.sort(
        key=lambda result: (
            order.get(result.economy, len(order)),
            result.economy,
        )
    )

    parent_checks_dir = Path(output_dir) / "supporting_files" / "checks"
    parent_checks_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, Path] = {}

    for filename in _PARALLEL_DIAGNOSTIC_FILENAMES:
        frames: list[pd.DataFrame] = []
        all_columns: list[str] = []
        for result in successful:
            worker_path = (
                worker_output_dir(result, pass_mode=pass_mode)
                / "supporting_files"
                / "checks"
                / filename
            )
            frame = _read_diagnostic_table(worker_path)
            for column in frame.columns:
                if column not in all_columns:
                    all_columns.append(column)
            if frame.empty:
                continue
            frame = frame.copy()
            if "economy" not in frame.columns:
                frame.insert(0, "economy", result.economy)
            else:
                frame["economy"] = frame["economy"].astype(object)
                missing_economy = frame["economy"].isna() | frame[
                    "economy"
                ].astype(str).str.strip().eq("")
                frame.loc[missing_economy, "economy"] = result.economy
            frame.insert(0, "__economy_order", order.get(result.economy, len(order)))
            frames.append(frame)

        if frames:
            merged = pd.concat(frames, ignore_index=True, sort=False)
            merged = merged.sort_values("__economy_order", kind="stable")
            merged = merged.drop(columns=["__economy_order"]).reset_index(drop=True)
        else:
            columns = [
                "economy",
                *[column for column in all_columns if column != "economy"],
            ]
            merged = pd.DataFrame(columns=columns)

        output_path = parent_checks_dir / filename
        if output_path.suffix.casefold() == ".parquet":
            write_manifested_parquet(
                merged,
                output_path,
                artifact_type="parallel_supply_reconciliation_conservation_lineage",
            )
        else:
            merged.to_csv(output_path, index=False)
        outputs[filename] = output_path

    return outputs


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
    branch_summary_out = (
        out_dir / f"baseline_seed_{run_stamp}_consolidated_branch_issue_summary.csv"
    )
    build_branch_issue_summary(merged).to_csv(branch_summary_out, index=False)

    return findings_out, issue_groups_out
