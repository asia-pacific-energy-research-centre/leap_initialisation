#%%
"""Classify baseline-seed findings caused by batched LEAP structure updates."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY_PATH = REPO_ROOT / "config" / "missing_leap_branch_registry.csv"
STRUCTURE_ROOT_RULE_ID = "SEED-011"
STRUCTURE_COMPANION_RULE_IDS = frozenset(
    {"SEED-003", "SEED-004", "SEED-005", "SEED-009", "SEED-010", "SEED-011"}
)
CLASSIFICATION_COLUMN = "structure_migration_classification"
MIGRATION_CLASSIFICATIONS = frozenset({"known_missing_branch"})


def normalize_branch_path(value: object) -> str:
    parts = [part.strip() for part in str(value or "").replace("/", "\\").split("\\") if part.strip()]
    return "\\".join(parts).casefold()


def load_structure_migration_registry(
    path: Path | str = DEFAULT_REGISTRY_PATH,
) -> list[dict[str, str]]:
    """Load the user-maintained exact missing-branch registry.

    This file is intentionally small and append-only: existing rows are never
    rewritten by workflow code, so a modeller's notes remain theirs.  A missing
    path must be explicitly added before it can be non-blocking.
    """
    resolved = Path(path)
    try:
        with resolved.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except Exception as exc:
        raise ValueError(f"Could not read missing-branch registry {resolved}: {exc}") from exc
    required = {"branch_path", "date_added", "notes"}
    actual = set(rows[0]) if rows else set()
    if not required.issubset(actual):
        raise ValueError(
            f"Missing-branch registry {resolved} must contain exactly the usable columns "
            "branch_path, date_added, notes."
        )
    entries: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    for row_number, row in enumerate(rows, start=2):
        branch_path = str(row.get("branch_path", "")).strip()
        date_added = str(row.get("date_added", "")).strip()
        normalized = normalize_branch_path(branch_path)
        if not branch_path or not date_added:
            raise ValueError(f"Missing-branch registry row {row_number} requires branch_path and date_added.")
        if normalized in seen_paths:
            raise ValueError(f"Duplicate branch_path in missing-branch registry: {branch_path!r}")
        seen_paths.add(normalized)
        entries.append({
            "branch_path": branch_path,
            "date_added": date_added,
            "notes": str(row.get("notes", "")),
        })
    return entries


def build_missing_branch_validation_exceptions(
    path: Path | str = DEFAULT_REGISTRY_PATH,
) -> list[dict[str, str]]:
    """Build precise in-memory exceptions for known absent LEAP branches."""
    return [
        {
            "exception_id": f"KNOWN-MISSING-BRANCH-{index:04d}",
            "rule_id": rule_id,
            "Branch Path": entry["branch_path"],
            "reason": f"Known missing LEAP branch; added {entry['date_added']}. {entry['notes']}".strip(),
        }
        for index, entry in enumerate(load_structure_migration_registry(path), start=1)
        for rule_id in sorted(STRUCTURE_COMPANION_RULE_IDS)
    ]


def _template_paths(template_path: Path | str | None) -> set[str]:
    if template_path is None or not Path(template_path).is_file():
        return set()
    from codebase.functions.baseline_seed_validation import load_template_rows

    rows = load_template_rows(Path(template_path))
    return {normalize_branch_path(value) for value in rows.get("Branch Path", pd.Series(dtype=object))}


def classify_structure_migration_findings(
    findings: pd.DataFrame,
    *,
    economy: str = "",
    run_id: str = "",
    template_path: Path | str | None = None,
    registry_path: Path | str = DEFAULT_REGISTRY_PATH,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply migration-only warning policy and return a reconciliation report.

    A row is a structure migration only when the same validation result contains
    ``SEED-011`` for its branch path. This keeps wrong IDs on an existing branch,
    broken shares, duplicates, and missing producer evidence fully blocking.
    """
    registry = load_structure_migration_registry(registry_path)
    registry_by_path = {normalize_branch_path(entry["branch_path"]): entry for entry in registry}
    work = findings.copy()
    metadata_columns = {
        CLASSIFICATION_COLUMN: "not_structure_migration",
        "migration_backlog_id": "",
        "migration_first_seen": "",
        "migration_last_seen_run_id": "",
        "migration_owner": "",
        "migration_materiality": "",
        "migration_review_status": "",
        "migration_notes": "",
        "original_status": "",
        "original_severity": "",
        "would_block_without_migration_policy": False,
    }
    for column, default in metadata_columns.items():
        if column not in work.columns:
            work[column] = default
    if work.empty:
        return work, _build_reconciliation_report(
            work, registry, economy=economy, run_id=run_id,
            template_paths=_template_paths(template_path),
        )

    normalized_paths = work.get("Branch Path", pd.Series("", index=work.index)).map(normalize_branch_path)
    root_mask = (
        work.get("rule_id", pd.Series("", index=work.index)).astype(str).eq(STRUCTURE_ROOT_RULE_ID)
        & work.get("status", pd.Series("", index=work.index)).astype(str).str.casefold().isin({"fail", "warn"})
    )
    missing_structure_paths = {path for path in normalized_paths[root_mask] if path}

    for index in work.index:
        rule_id = str(work.at[index, "rule_id"]) if "rule_id" in work else ""
        normalized_path = normalized_paths.at[index]
        is_structure = (
            rule_id in STRUCTURE_COMPANION_RULE_IDS
            and bool(normalized_path)
            and normalized_path in missing_structure_paths
        )
        if not is_structure:
            continue
        entry = registry_by_path.get(normalized_path)
        # Unknown missing branches remain blocking.  This registry is the
        # deliberate decision boundary; the workflow must never auto-enrol a
        # new path merely because it appeared in a run.
        if entry is None:
            continue
        classification = "known_missing_branch"
        work.at[index, "original_status"] = str(work.at[index, "status"])
        work.at[index, "original_severity"] = str(work.at[index, "severity"])
        work.at[index, "would_block_without_migration_policy"] = bool(work.at[index, "blocking"])
        work.at[index, CLASSIFICATION_COLUMN] = classification
        work.at[index, "migration_backlog_id"] = normalized_path
        work.at[index, "migration_first_seen"] = entry["date_added"]
        work.at[index, "migration_last_seen_run_id"] = run_id
        work.at[index, "migration_owner"] = str(
            work.at[index, "source_workflow"]
            if "source_workflow" in work and str(work.at[index, "source_workflow"]).strip()
            else "unassigned"
        )
        work.at[index, "migration_materiality"] = (
            "nonzero_or_unknown" if rule_id == "SEED-004" else "zero_or_unknown" if rule_id == "SEED-005" else "not_recorded"
        )
        work.at[index, "migration_review_status"] = str(
            "known_missing_branch"
        )
        work.at[index, "migration_notes"] = entry["notes"]
        work.at[index, "status"] = "warn"
        work.at[index, "severity"] = "warning"
        work.at[index, "blocking"] = False

    report = _build_reconciliation_report(
        work, registry, economy=economy, run_id=run_id,
        template_paths=_template_paths(template_path),
    )
    return work, report


def _build_reconciliation_report(
    findings: pd.DataFrame,
    entries: Iterable[dict[str, str]],
    *,
    economy: str,
    run_id: str,
    template_paths: set[str],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    observed_ids = set(findings.get("migration_backlog_id", pd.Series(dtype=object)).dropna().astype(str))
    observed = findings[
        findings.get(CLASSIFICATION_COLUMN, pd.Series("", index=findings.index)).isin(MIGRATION_CLASSIFICATIONS)
    ] if not findings.empty else findings
    for backlog_id, group in observed.groupby("migration_backlog_id", sort=True):
        first = group.iloc[0]
        rows.append({
            "migration_backlog_id": backlog_id,
            "economy": economy,
            "branch_path": first.get("Branch Path", ""),
            "classification": first.get(CLASSIFICATION_COLUMN, ""),
            "reconciliation_status": "still_missing",
            "finding_count": len(group),
            "first_seen": first.get("migration_first_seen", ""),
            "last_seen_run_id": run_id,
            "owner": first.get("migration_owner", ""),
            "materiality": "|".join(sorted(set(group["migration_materiality"].astype(str)))),
            "review_status": first.get("migration_review_status", ""),
            "requires_review": first.get(CLASSIFICATION_COLUMN) == "new_migration_candidate",
            "notes": first.get("migration_notes", ""),
        })
    for entry in entries:
        backlog_id = normalize_branch_path(entry["branch_path"])
        if backlog_id in observed_ids:
            continue
        pattern = normalize_branch_path(entry["branch_path"])
        scope_present = pattern in template_paths
        rows.append({
            "migration_backlog_id": backlog_id,
            "economy": economy,
            "branch_path": entry["branch_path"],
            "classification": "known_missing_branch",
            "reconciliation_status": (
                "not_observed_template_scope_present" if scope_present else "not_observed_requires_review"
            ),
            "finding_count": 0,
            "first_seen": entry["date_added"],
            "last_seen_run_id": run_id,
            "owner": "unassigned",
            "materiality": "not_observed",
            "review_status": "known_missing_branch",
            "requires_review": True,
            "notes": entry["notes"],
        })
    return pd.DataFrame(rows)


#%%
