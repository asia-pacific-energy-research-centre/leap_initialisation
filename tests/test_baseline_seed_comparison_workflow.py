"""Focused tests for baseline seed comparison and share-total auditing."""

from pathlib import Path

import pandas as pd

from codebase.baseline_seed_comparison_workflow import (
    build_share_sum_checks,
    compare_seed_tables,
)


def _row(branch: str, variable: str, expression: object, *, branch_id: int = 1) -> dict[str, object]:
    return {
        "BranchID": branch_id,
        "VariableID": 10,
        "ScenarioID": 2,
        "RegionID": 1,
        "Branch Path": branch,
        "Variable": variable,
        "Scenario": "Reference",
        "Region": "Australia",
        "Units": "Share",
        "Expression": expression,
    }


def _with_excel_rows(rows: list[dict[str, object]]) -> pd.DataFrame:
    data = pd.DataFrame(rows)
    data["source_excel_row"] = range(4, 4 + len(data))
    return data


def test_semantic_expression_comparison_reports_only_changed_year() -> None:
    reference = _with_excel_rows(
        [_row("Transformation\\Plant\\Output Fuels\\Gas", "Output Share", "Data(2022,40, 2023,50)")]
    )
    candidate = _with_excel_rows(
        [_row("Transformation\\Plant\\Output Fuels\\Gas", "Output Share", "Data(2022,40.0, 2023,55)")]
    )

    row_diff, expression_diff, summary = compare_seed_tables(
        reference,
        candidate,
        economy="01_AUS",
        reference_file=Path("reference.xlsx"),
        candidate_file=Path("candidate.xlsx"),
        numeric_tolerance=1e-9,
    )

    assert row_diff["status"].tolist() == ["expression_changed"]
    assert expression_diff["year"].tolist() == [2023]
    assert expression_diff["difference"].tolist() == [5.0]
    assert summary["expression_changed_rows"] == 1


def test_data_and_interp_are_not_treated_as_equivalent() -> None:
    reference = _with_excel_rows(
        [_row("Transformation\\Plant\\Output Fuels\\Gas", "Output Share", "Data(2022,40, 2030,60)")]
    )
    candidate = _with_excel_rows(
        [_row("Transformation\\Plant\\Output Fuels\\Gas", "Output Share", "Interp(2022,40, 2030,60)")]
    )

    row_diff, expression_diff, _ = compare_seed_tables(
        reference,
        candidate,
        economy="01_AUS",
        reference_file=Path("reference.xlsx"),
        candidate_file=Path("candidate.xlsx"),
        numeric_tolerance=1e-9,
    )

    assert row_diff["status"].tolist() == ["expression_changed"]
    assert expression_diff["status"].tolist() == ["expression_kind_changed"]


def test_added_and_removed_rows_are_reported() -> None:
    reference = _with_excel_rows([_row("Resources\\Primary\\Gas", "Imports", "Data(2022,1)")])
    candidate = _with_excel_rows([_row("Resources\\Primary\\Coal", "Imports", "Data(2022,1)")])

    row_diff, _, summary = compare_seed_tables(
        reference,
        candidate,
        economy="01_AUS",
        reference_file=Path("reference.xlsx"),
        candidate_file=Path("candidate.xlsx"),
        numeric_tolerance=1e-9,
    )

    assert set(row_diff["status"]) == {"reference_only", "candidate_only"}
    assert summary["reference_only_rows"] == 1
    assert summary["candidate_only_rows"] == 1


def test_share_sum_check_groups_sibling_fuel_leaves() -> None:
    data = _with_excel_rows(
        [
            _row("Transformation\\Plant\\Output Fuels\\Gas", "Output Share", "Data(2022,40, 2023,50)"),
            _row("Transformation\\Plant\\Output Fuels\\Oil", "Output Share", "Data(2022,60, 2023,40)"),
        ]
    )

    checks = build_share_sum_checks(
        data,
        economy="01_AUS",
        source="candidate",
        file_path=Path("candidate.xlsx"),
        tolerance=1e-9,
    )

    assert checks.loc[checks["year"] == 2022, "status"].item() == "pass"
    assert checks.loc[checks["year"] == 2023, "status"].item() == "fail_not_100"
    assert checks.loc[checks["year"] == 2023, "share_sum"].item() == 90.0


def test_share_sum_check_flags_conflicting_duplicate_key() -> None:
    branch = "Transformation\\Plant\\Output Fuels\\Gas"
    data = _with_excel_rows(
        [
            _row(branch, "Output Share", "Data(2022,100)", branch_id=1),
            _row(branch, "Output Share", "Data(2022,90)", branch_id=-1),
        ]
    )

    checks = build_share_sum_checks(
        data,
        economy="01_AUS",
        source="candidate",
        file_path=Path("candidate.xlsx"),
        tolerance=1e-9,
    )

    assert checks["status"].tolist() == ["review_ambiguous_expression"]
    assert checks["ambiguous_logical_key_count"].tolist() == [1]
