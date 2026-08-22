"""Shared LEAP structure-migration classification policy tests."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from codebase.functions.baseline_seed_structure_migration import (
    CLASSIFICATION_COLUMN,
    build_missing_branch_validation_exceptions,
    classify_structure_migration_findings,
    load_structure_migration_registry,
)
from codebase.functions.baseline_seed_validation import validate_seed_rows
from codebase.functions.baseline_seed_validation_exceptions import REQUIRED_COLUMNS
from openpyxl import Workbook


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
        "branch_path,date_added,notes,esto_base_year,esto_base_year_absolute_pj_all_economies,projection_start_year,projection_end_year,projection_year_count,reference_projection_absolute_average_pj_per_year_all_economies,target_projection_absolute_average_pj_per_year_all_economies\n"
        "Demand\\Known pending branch\\Electricity,2026-08-01,Queued for the next area update.,2022,1,2023,2060,38,1,1\n",
        encoding="utf-8",
    )
    return path


def _exception_workbook(path: Path, branch_path: str = "") -> Path:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "branch_exceptions"
    sheet.append(REQUIRED_COLUMNS)
    if branch_path:
        sheet.append([True, branch_path, "Queued.", "", "", *([""] * (len(REQUIRED_COLUMNS) - 5))])
    workbook.save(path)
    return path


def test_only_registered_missing_structure_is_nonblocking(
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
        exception_workbook_path=_exception_workbook(tmp_path / "exceptions.xlsx"),
    )

    known_rows = classified[classified["Branch Path"].eq(known)]
    new_rows = classified[classified["Branch Path"].eq(new)]
    share_row = classified[classified["rule_id"].eq("SEED-008")].iloc[0]
    assert set(known_rows[CLASSIFICATION_COLUMN]) == {"known_missing_branch"}
    assert set(new_rows[CLASSIFICATION_COLUMN]).issubset({"new_missing_branch_recorded", "known_missing_branch"})
    assert not known_rows["blocking"].any()
    assert not new_rows["blocking"].any()
    assert set(known_rows["migration_first_seen"]) == {"2026-08-01"}
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
        exception_workbook_path=_exception_workbook(tmp_path / "exceptions.xlsx"),
    )

    assert classified.iloc[0][CLASSIFICATION_COLUMN] == "not_structure_migration"
    assert bool(classified.iloc[0]["blocking"])


def test_same_finding_classifies_identically_for_rebuild_and_patch_labels(tmp_path: Path) -> None:
    branch = "Transformation\\Queued process\\Output Fuels\\Gas"
    findings = pd.DataFrame([_finding("SEED-011", branch), _finding("SEED-003", branch)])
    registry_path = _registry(tmp_path / "registry.json")
    exception_path = _exception_workbook(tmp_path / "exceptions.xlsx")

    rebuilt, _ = classify_structure_migration_findings(
        findings, economy="20_USA", run_id="full-rebuild", registry_path=registry_path,
        exception_workbook_path=exception_path,
    )
    patched, _ = classify_structure_migration_findings(
        findings, economy="20_USA", run_id="surgical-patch", registry_path=registry_path,
        exception_workbook_path=exception_path,
    )

    columns = ["migration_backlog_id", "blocking", "severity", "status"]
    pd.testing.assert_frame_equal(rebuilt[columns], patched[columns])


def test_registry_builds_exact_companion_exceptions_and_rejects_duplicates(tmp_path: Path) -> None:
    registry_path = _registry(tmp_path / "registry.csv")
    # The workbook, rather than the retired CSV registry, is the reviewed
    # source for baseline-seed warning exceptions.
    exception_path = _exception_workbook(tmp_path / "exceptions.xlsx", "Demand\\Known pending branch\\Electricity")
    exceptions = build_missing_branch_validation_exceptions(
        registry_path, exception_workbook_path=exception_path,
    )

    assert {row["rule_id"] for row in exceptions} == {
        "SEED-003", "SEED-004", "SEED-005", "SEED-009", "SEED-010", "SEED-011"
    }
    assert {row["Branch Path"] for row in exceptions} == {"Demand\\Known pending branch\\Electricity"}

    # The old CSV loader still protects legacy callers from duplicate rows.
    registry_path.write_text(registry_path.read_text(encoding="utf-8") + "Demand\\Known pending branch\\Electricity,2026-08-02,Duplicate must fail.\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate branch_path"):
        load_structure_migration_registry(registry_path)


def test_aggregate_preflight_uses_union_paths_without_area_specific_ids(tmp_path: Path) -> None:
    template = tmp_path / "usa_template.xlsx"
    pd.DataFrame([
        {"BranchID": 1, "VariableID": 2, "ScenarioID": 3, "RegionID": 4,
         "Branch Path": "Demand\\USA-only", "Variable": "Activity Level",
         "Scenario": "Reference", "Region": "United States"}
    ]).to_excel(template, sheet_name="Export", index=False, startrow=2)
    aggregate_only_path = "Demand\\Present in another economy\\Fuel"
    rows = pd.DataFrame([
        {"BranchID": -1, "VariableID": -1, "ScenarioID": -1, "RegionID": -1,
         "Branch Path": aggregate_only_path, "Variable": "Activity Level",
         "Scenario": "Reference", "Region": "United States", "Expression": "1"}
    ])

    result = validate_seed_rows(
        rows,
        template_path=template,
        template_branch_paths={"Demand\\USA-only", aggregate_only_path},
        validate_template_ids=False,
        validate_template_share_completeness=False,
    )

    assert result.blocking_findings.empty

    absent_result = validate_seed_rows(
        rows,
        template_path=template,
        template_branch_paths={"Demand\\USA-only"},
        validate_template_ids=False,
        validate_template_share_completeness=False,
        missing_template_branches_are_warnings=True,
    )
    assert not absent_result.findings.empty
    assert absent_result.blocking_findings.empty
    assert set(absent_result.findings["rule_id"]) == {"SEED-011"}
