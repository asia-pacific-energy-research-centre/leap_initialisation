"""Shared LEAP structure-migration classification policy tests."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from codebase.functions.baseline_seed_structure_migration import (
    CLASSIFICATION_COLUMN,
    classify_structure_migration_findings,
)


def _finding(rule_id: str, branch: str, *, blocking: bool = True) -> dict[str, object]:
    return {
        "rule_id": rule_id,
        "status": "fail" if blocking else "warn",
        "severity": "error" if blocking else "warning",
        "blocking": blocking,
        "Branch Path": branch,
        "Variable": "Activity Level",
        "Scenario": "Reference",
        "Region": "United States",
        "source_workflow": "test_producer",
    }


def _registry(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "entries": [
                    {
                        "backlog_id": "LEAP-MIG-TEST-001",
                        "economy": "20_USA",
                        "branch_path": "Demand\\Known pending branch\\",
                        "path_match": "prefix",
                        "first_seen": "2026-08-01",
                        "owner": "test_producer",
                        "review_status": "confirmed",
                        "notes": "Queued for the next area update.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_known_and_new_missing_structure_are_warnings_but_other_failures_block(
    tmp_path: Path,
) -> None:
    known = "Demand\\Known pending branch\\Electricity"
    new = "Transformation\\New process\\Output Fuels\\Hydrogen"
    findings = pd.DataFrame(
        [
            _finding("SEED-011", known),
            _finding("SEED-003", known),
            _finding("SEED-011", new),
            _finding("SEED-004", new),
            _finding("SEED-008", "Transformation\\Broken shares"),
        ]
    )

    classified, report = classify_structure_migration_findings(
        findings,
        economy="20_USA",
        run_id="RUN-1",
        registry_path=_registry(tmp_path / "registry.json"),
    )

    known_rows = classified[classified["Branch Path"].eq(known)]
    new_rows = classified[classified["Branch Path"].eq(new)]
    share_row = classified[classified["rule_id"].eq("SEED-008")].iloc[0]
    assert set(known_rows[CLASSIFICATION_COLUMN]) == {"known_migration_backlog"}
    assert set(new_rows[CLASSIFICATION_COLUMN]) == {"new_migration_candidate"}
    assert not known_rows["blocking"].any()
    assert not new_rows["blocking"].any()
    assert set(known_rows["migration_backlog_id"]) == {"LEAP-MIG-TEST-001"}
    assert new_rows["migration_backlog_id"].str.startswith("LEAP-MIG-CAND-").all()
    assert share_row[CLASSIFICATION_COLUMN] == "not_structure_migration"
    assert bool(share_row["blocking"])
    assert set(report["reconciliation_status"]) == {"still_missing"}


def test_missing_id_without_missing_template_branch_is_not_migration(tmp_path: Path) -> None:
    findings = pd.DataFrame(
        [_finding("SEED-003", "Resources\\Primary\\Coal")]
    )

    classified, _ = classify_structure_migration_findings(
        findings,
        economy="20_USA",
        registry_path=_registry(tmp_path / "registry.json"),
    )

    assert classified.iloc[0][CLASSIFICATION_COLUMN] == "not_structure_migration"
    assert bool(classified.iloc[0]["blocking"])


def test_same_finding_classifies_identically_for_rebuild_and_patch_labels(tmp_path: Path) -> None:
    branch = "Transformation\\Queued process\\Output Fuels\\Gas"
    findings = pd.DataFrame([_finding("SEED-011", branch), _finding("SEED-003", branch)])
    registry_path = _registry(tmp_path / "registry.json")

    rebuilt, _ = classify_structure_migration_findings(
        findings, economy="20_USA", run_id="full-rebuild", registry_path=registry_path
    )
    patched, _ = classify_structure_migration_findings(
        findings, economy="20_USA", run_id="surgical-patch", registry_path=registry_path
    )

    columns = [CLASSIFICATION_COLUMN, "migration_backlog_id", "blocking", "severity", "status"]
    pd.testing.assert_frame_equal(rebuilt[columns], patched[columns])
