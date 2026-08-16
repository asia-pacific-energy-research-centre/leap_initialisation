#%%
"""Classify baseline-seed findings caused by batched LEAP structure updates."""
from __future__ import annotations

from datetime import date
import hashlib
import json
from pathlib import Path
from typing import Iterable

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY_PATH = REPO_ROOT / "config" / "leap_structure_migration_registry.json"
STRUCTURE_ROOT_RULE_ID = "SEED-011"
STRUCTURE_COMPANION_RULE_IDS = frozenset(
    {"SEED-003", "SEED-004", "SEED-005", "SEED-009", "SEED-010", "SEED-011"}
)
CLASSIFICATION_COLUMN = "structure_migration_classification"
MIGRATION_CLASSIFICATIONS = frozenset(
    {"known_migration_backlog", "new_migration_candidate"}
)


def normalize_branch_path(value: object) -> str:
    parts = [part.strip() for part in str(value or "").replace("/", "\\").split("\\") if part.strip()]
    return "\\".join(parts).casefold()


def load_structure_migration_registry(
    path: Path | str = DEFAULT_REGISTRY_PATH,
) -> dict[str, object]:
    resolved = Path(path)
    try:
        registry = json.loads(resolved.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Could not read LEAP structure migration registry {resolved}: {exc}") from exc
    if registry.get("schema_version") != "1.0.0":
        raise ValueError(
            f"Unsupported LEAP structure migration registry schema in {resolved}: "
            f"{registry.get('schema_version')!r}"
        )
    entries = registry.get("entries")
    if not isinstance(entries, list):
        raise ValueError(f"LEAP structure migration registry {resolved} has no entries list.")
    required = {"backlog_id", "economy", "branch_path", "path_match", "first_seen", "owner", "review_status"}
    seen_ids: set[str] = set()
    for entry in entries:
        missing = sorted(required - set(entry)) if isinstance(entry, dict) else sorted(required)
        if missing:
            raise ValueError(f"Invalid migration registry entry; missing {missing}: {entry!r}")
        backlog_id = str(entry["backlog_id"]).strip()
        if not backlog_id or backlog_id in seen_ids:
            raise ValueError(f"Migration backlog IDs must be nonblank and unique: {backlog_id!r}")
        seen_ids.add(backlog_id)
        if entry["path_match"] not in {"exact", "prefix"}:
            raise ValueError(f"Invalid path_match for {backlog_id}: {entry['path_match']!r}")
    return registry


def _economy_matches(entry_economy: object, economy: str) -> bool:
    token = str(entry_economy or "").strip().casefold()
    return token == "*" or token == str(economy or "").strip().casefold()


def _entry_matches(entry: dict[str, object], economy: str, normalized_path: str) -> bool:
    if not _economy_matches(entry.get("economy"), economy):
        return False
    pattern = normalize_branch_path(entry.get("branch_path"))
    return (
        normalized_path == pattern
        if entry.get("path_match") == "exact"
        else normalized_path.startswith(pattern + "\\") or normalized_path == pattern
    )


def _candidate_id(economy: str, normalized_path: str) -> str:
    identity = f"{economy.strip().casefold()}|{normalized_path}".encode("utf-8")
    return f"LEAP-MIG-CAND-{hashlib.sha256(identity).hexdigest()[:12].upper()}"


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
            work, registry["entries"], economy=economy, run_id=run_id,
            template_paths=_template_paths(template_path),
        )

    normalized_paths = work.get("Branch Path", pd.Series("", index=work.index)).map(normalize_branch_path)
    root_mask = (
        work.get("rule_id", pd.Series("", index=work.index)).astype(str).eq(STRUCTURE_ROOT_RULE_ID)
        & work.get("status", pd.Series("", index=work.index)).astype(str).str.casefold().isin({"fail", "warn"})
    )
    missing_structure_paths = {path for path in normalized_paths[root_mask] if path}
    today = date.today().isoformat()

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
        entry = next(
            (
                item for item in registry["entries"]
                if _entry_matches(item, economy, normalized_path)
            ),
            None,
        )
        classification = "known_migration_backlog" if entry else "new_migration_candidate"
        backlog_id = str(entry["backlog_id"]) if entry else _candidate_id(economy, normalized_path)
        work.at[index, "original_status"] = str(work.at[index, "status"])
        work.at[index, "original_severity"] = str(work.at[index, "severity"])
        work.at[index, "would_block_without_migration_policy"] = bool(work.at[index, "blocking"])
        work.at[index, CLASSIFICATION_COLUMN] = classification
        work.at[index, "migration_backlog_id"] = backlog_id
        work.at[index, "migration_first_seen"] = str(entry.get("first_seen", today)) if entry else today
        work.at[index, "migration_last_seen_run_id"] = run_id
        work.at[index, "migration_owner"] = str(
            work.at[index, "source_workflow"]
            if "source_workflow" in work and str(work.at[index, "source_workflow"]).strip()
            else entry.get("owner", "unassigned") if entry else "unassigned"
        )
        work.at[index, "migration_materiality"] = (
            "nonzero_or_unknown" if rule_id == "SEED-004" else "zero_or_unknown" if rule_id == "SEED-005" else "not_recorded"
        )
        work.at[index, "migration_review_status"] = str(
            entry.get("review_status", "needs_review_and_backlog_entry") if entry else "needs_review_and_backlog_entry"
        )
        work.at[index, "migration_notes"] = str(entry.get("notes", "New structure gap; review for the next coordinated LEAP area update.") if entry else "New structure gap; review for the next coordinated LEAP area update.")
        work.at[index, "status"] = "warn"
        work.at[index, "severity"] = "warning"
        work.at[index, "blocking"] = False

    report = _build_reconciliation_report(
        work, registry["entries"], economy=economy, run_id=run_id,
        template_paths=_template_paths(template_path),
    )
    return work, report


def _build_reconciliation_report(
    findings: pd.DataFrame,
    entries: Iterable[dict[str, object]],
    *,
    economy: str,
    run_id: str,
    template_paths: set[str],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    observed_ids = set(
        findings.get("migration_backlog_id", pd.Series(dtype=object)).dropna().astype(str)
    )
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
        backlog_id = str(entry["backlog_id"])
        if backlog_id in observed_ids or not _economy_matches(entry.get("economy"), economy):
            continue
        pattern = normalize_branch_path(entry.get("branch_path"))
        scope_present = any(
            path == pattern or path.startswith(pattern + "\\") for path in template_paths
        )
        rows.append({
            "migration_backlog_id": backlog_id,
            "economy": economy or entry.get("economy", ""),
            "branch_path": entry.get("branch_path", ""),
            "classification": "known_migration_backlog",
            "reconciliation_status": (
                "not_observed_template_scope_present" if scope_present else "not_observed_requires_review"
            ),
            "finding_count": 0,
            "first_seen": entry.get("first_seen", ""),
            "last_seen_run_id": run_id,
            "owner": entry.get("owner", ""),
            "materiality": "not_observed",
            "review_status": entry.get("review_status", ""),
            "requires_review": True,
            "notes": "Registry entry was not observed in this validation; reconcile after template refresh.",
        })
    return pd.DataFrame(rows)


#%%
