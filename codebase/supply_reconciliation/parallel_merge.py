"""Deterministic parent merge for bounded process-based economy parallelism.

Scope, deliberately narrow (docs/prompts/continuation_20260722_phase4_parallelism_and_release_readiness.md
and docs/current_execution_roadmap.md flagged this as still-open work needing
its own design pass, not a rushed add-on to
``codebase/supply_reconciliation/parallel_runner.py``):

* This module merges only the **consolidated baseline-seed validation
  findings** (``baseline_seed_<stamp>_consolidated_rule_findings.csv`` and
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
* **NOT included**: merging the single-file combined workbook
  (``supply_recon_run_baseline_seed_<economies>_<scenarios>.xlsx``) that a
  sequential multi-economy run also produces. The merge preserves the first
  worker's LEAP ``Export`` preamble and header exactly, verifies every worker
  has the same layout, and resolves data rows in configured economy order
  (later economy rows win for the intentional broad-proxy overlap). It also
  preserves the optional ``RUN_MANIFEST`` sheet by
  concatenating its rows after verifying a common header. This was built and
  structurally diffed against the sequential two-economy/two-year reference
  run; see ``tests/test_parallel_economy_merge.py``.
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
from codebase.functions.leap_excel_io import find_leap_header_row
from codebase.supply_reconciliation.parallel_runner import EconomyWorkerResult

_FINDINGS_COLUMNS = (
    "economy", "rule_id", "status", "severity", "blocking",
    "violated_rule_expectation",
    "scope", "message", "evidence", "documentation_reference", "Branch Path",
    "Variable", "Scenario", "Region", "source_workflow", "source_file",
    "year", "exception_applied", "exception_id", "exception_reason",
)
_LEAP_KEY_COLUMNS = ("Branch Path", "Variable", "Scenario", "Region")


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


def _ordered_successful_results(
    results: Sequence[EconomyWorkerResult],
    *,
    economies_run_order: Sequence[str],
) -> list[EconomyWorkerResult]:
    """Return successful workers in the explicit parent economy order.

    A combined LEAP workbook is not useful if it quietly omits a failed
    economy. Unlike diagnostics, this merge therefore fails closed when any
    worker failed or the supplied order does not exactly describe the workers.
    """
    if not economies_run_order:
        raise ValueError("economies_run_order must name every worker economy")
    expected = [str(economy).strip() for economy in economies_run_order if str(economy).strip()]
    if len(expected) != len(set(expected)):
        raise ValueError("economies_run_order contains duplicate economies")
    by_economy = {result.economy: result for result in results}
    if len(by_economy) != len(results):
        raise ValueError("Parallel worker results contain duplicate economies")
    missing = [economy for economy in expected if economy not in by_economy]
    unexpected = sorted(set(by_economy) - set(expected))
    failed = sorted(result.economy for result in results if not result.succeeded)
    if missing or unexpected or failed:
        details = []
        if missing:
            details.append(f"missing={missing}")
        if unexpected:
            details.append(f"unexpected={unexpected}")
        if failed:
            details.append(f"failed={failed}")
        raise RuntimeError(
            "Refusing to write a partial parallel combined workbook (" + "; ".join(details) + ")."
        )
    return [by_economy[economy] for economy in expected]


def _worker_results_workbook_path(result: EconomyWorkerResult, *, pass_mode: str) -> Path:
    """Locate exactly one active consolidated workbook in a worker directory."""
    worker_dir = worker_output_dir(result, pass_mode=pass_mode)
    candidates = sorted(worker_dir.glob("supply_recon_run_*.xlsx"))
    if len(candidates) != 1:
        raise FileNotFoundError(
            f"Expected exactly one consolidated results workbook for {result.economy} "
            f"under {worker_dir}; found {len(candidates)}: {[path.name for path in candidates]}"
        )
    return candidates[0]


def _read_export_raw(path: Path) -> tuple[pd.DataFrame, int, list[object]]:
    """Read an Export sheet without normalizing any LEAP preamble/header cells."""
    raw = pd.read_excel(path, sheet_name="Export", header=None)
    header_row = find_leap_header_row(raw)
    if header_row is None:
        raise ValueError(f"No LEAP Export header found in {path}")
    return raw, header_row, raw.iloc[header_row].tolist()


def _normalize_key_value(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _validate_no_duplicate_leap_keys(raw: pd.DataFrame, *, header_row: int, path: Path) -> None:
    """Fail loudly if the parent merge would create duplicate LEAP target rows."""
    header = raw.iloc[header_row].tolist()
    positions = {str(column).strip(): index for index, column in enumerate(header)}
    missing = [column for column in _LEAP_KEY_COLUMNS if column not in positions]
    if missing:
        raise ValueError(f"{path} lacks LEAP key columns required for merge: {missing}")
    data = raw.iloc[header_row + 1 :].dropna(how="all")
    keys = data.iloc[:, [positions[column] for column in _LEAP_KEY_COLUMNS]].copy()
    keys.columns = list(_LEAP_KEY_COLUMNS)
    for column in _LEAP_KEY_COLUMNS:
        keys[column] = keys[column].map(_normalize_key_value)
    duplicates = keys.duplicated(keep=False)
    if duplicates.any():
        sample = keys.loc[duplicates].head(5).to_dict("records")
        raise ValueError(f"{path} contains duplicate LEAP keys; sample={sample}")


def merge_parallel_results_workbooks(
    results: Sequence[EconomyWorkerResult],
    *,
    output_path: Path | str,
    economies_run_order: Sequence[str],
    pass_mode: str = "baseline_seed",
) -> Path:
    """Build the parent combined workbook from isolated worker result workbooks.

    The ``Export`` layout is intentionally copied as raw cells: row 0/1 LEAP
    preamble, header row, ID columns, blank spacer, year columns, and Level
    columns are never reconstructed from DataFrames with renamed headers.
    Every input must have an identical header layout and preamble shape. The
    first worker's preamble is retained verbatim; its area-name cell may
    differ legitimately between per-economy workers. Data rows are resolved
    in ``economies_run_order``; later rows replace an earlier row
    with the same LEAP key, matching the sequential workflow's overwrite
    behavior for the intentionally broad own-use proxy producer. This makes
    the result independent of worker completion order. ``RUN_MANIFEST`` rows
    are similarly concatenated when present in all worker workbooks.
    """
    ordered_results = _ordered_successful_results(
        results,
        economies_run_order=economies_run_order,
    )
    source_paths = [
        _worker_results_workbook_path(result, pass_mode=pass_mode)
        for result in ordered_results
    ]

    first_raw, first_header_row, _ = _read_export_raw(source_paths[0])
    _validate_no_duplicate_leap_keys(first_raw, header_row=first_header_row, path=source_paths[0])
    export_preamble_and_header = first_raw.iloc[: first_header_row + 1].copy()
    key_order: list[tuple[str, str, str, str]] = []
    row_by_key: dict[tuple[str, str, str, str], list[object]] = {}

    for path in source_paths:
        raw, header_row, header = _read_export_raw(path)
        if (
            header_row != first_header_row
            or [_normalize_key_value(value) for value in header]
            != [_normalize_key_value(value) for value in first_raw.iloc[first_header_row].tolist()]
            or raw.iloc[:header_row].shape != first_raw.iloc[:first_header_row].shape
        ):
            raise ValueError(
                f"LEAP Export preamble/header layout differs for {path}; parent merge aborted."
            )
        _validate_no_duplicate_leap_keys(raw, header_row=header_row, path=path)
        data = raw.iloc[header_row + 1 :].dropna(how="all").copy()
        positions = {str(column).strip(): index for index, column in enumerate(header)}
        for _, row in data.iterrows():
            key = tuple(_normalize_key_value(row.iloc[positions[column]]) for column in _LEAP_KEY_COLUMNS)
            if key not in row_by_key:
                key_order.append(key)
            # Sequential packaging processes economies in run order and lets
            # later broad-proxy rows replace the earlier economy's target.
            row_by_key[key] = row.tolist()

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    merged_data = pd.DataFrame(
        [row_by_key[key] for key in key_order],
        columns=export_preamble_and_header.columns,
    )
    merged_export = pd.concat([export_preamble_and_header, merged_data], ignore_index=True)
    with pd.ExcelWriter(output, engine="openpyxl", mode="w") as writer:
        merged_export.to_excel(writer, sheet_name="Export", index=False, header=False)
        _write_merged_run_manifest(writer, source_paths)
    return output


def _write_merged_run_manifest(writer, source_paths: Sequence[Path]) -> None:
    """Concatenate RUN_MANIFEST rows if every worker wrote the optional sheet."""
    manifests: list[pd.DataFrame] = []
    for path in source_paths:
        with pd.ExcelFile(path) as workbook:
            if "RUN_MANIFEST" not in workbook.sheet_names:
                return
        manifests.append(pd.read_excel(path, sheet_name="RUN_MANIFEST"))
    if not manifests:
        return
    columns = list(manifests[0].columns)
    if any(list(frame.columns) != columns for frame in manifests[1:]):
        raise ValueError("RUN_MANIFEST headers differ across parallel worker workbooks")
    pd.concat(manifests, ignore_index=True).to_excel(
        writer,
        sheet_name="RUN_MANIFEST",
        index=False,
    )


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
