"""Focused tests for baseline seed comparison and share-total auditing."""

from pathlib import Path

import pandas as pd
import pytest

from codebase.baseline_seed_comparison_workflow import (
    build_share_sum_checks,
    compare_seed_tables,
    read_seed_workbook,
)
from codebase.functions.baseline_seed_validation import (
    BaselineSeedValidationError,
    enrich_seed_ids_from_template,
    prepare_seed_rows_for_write,
    resolve_logical_duplicates,
    validate_seed_rows,
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

    assert checks["status"].tolist() == ["blocked_by_conflicting_duplicate"]
    assert checks["share_sum"].tolist() == [100.0]
    assert checks["blocking_duplicate_logical_key_count"].tolist() == [1]


def test_duplicate_resolution_prefers_only_valid_id_row_without_row_order() -> None:
    branch = "Transformation\\Heat plant interim\\Processes\\Heat plant interim"
    rows = [
        _row(branch, "Process Share", "Data(2022,0)", branch_id=-1),
        _row(branch, "Process Share", "Data(2022,100)", branch_id=2450),
        _row(branch, "Process Share", "Data(2022,100)", branch_id=-1),
    ]
    rows[0]["VariableID"] = rows[0]["ScenarioID"] = -1
    rows[2]["VariableID"] = rows[2]["ScenarioID"] = -1
    data = _with_excel_rows(rows).sample(frac=1, random_state=7)

    resolved, duplicates = resolve_logical_duplicates(data)

    assert resolved["BranchID"].tolist() == [2450]
    assert resolved["Expression"].tolist() == ["Data(2022,100)"]
    assert duplicates["classification"].tolist() == ["conflicting_expression_one_valid_id_row"]
    assert duplicates["blocking"].tolist() == [True]


def test_duplicate_classification_exact_and_multiple_valid_rows() -> None:
    exact = _with_excel_rows([
        _row("Resources\\Gas", "Imports", "0", branch_id=1),
        _row("Resources\\Gas", "Imports", "0", branch_id=1),
    ])
    _, exact_groups = resolve_logical_duplicates(exact)
    assert exact_groups["classification"].item() == "exact_duplicate_same_ids_and_expression"
    assert not exact_groups["blocking"].item()

    conflicting = _with_excel_rows([
        _row("Resources\\Gas", "Imports", "1", branch_id=1),
        _row("Resources\\Gas", "Imports", "2", branch_id=2),
    ])
    _, conflicting_groups = resolve_logical_duplicates(conflicting)
    assert conflicting_groups["classification"].item() == "conflicting_expression_multiple_valid_id_rows"
    assert conflicting_groups["blocking"].item()


def test_validator_checks_all_ids_and_distinguishes_zero_reset() -> None:
    rows = [
        _row("Resources\\Gas", "Imports", "Data(2022,5)"),
        _row("Resources\\Coal", "Imports", "Data(2022,0)"),
    ]
    rows[0]["VariableID"] = -1
    rows[1]["ScenarioID"] = -1
    result = validate_seed_rows(_with_excel_rows(rows))

    assert len(result.findings[result.findings["rule_id"] == "SEED-003"]) == 2
    assert len(result.findings[result.findings["rule_id"] == "SEED-004"]) == 1
    zero_findings = result.findings[result.findings["rule_id"] == "SEED-005"]
    assert len(zero_findings) == 1
    assert not zero_findings["blocking"].item()


def test_missing_id_zero_exception_requires_rule_and_key_scope() -> None:
    row = _row("Resources\\Coal", "Imports", "Data(2022,0)")
    row["VariableID"] = -1
    result = validate_seed_rows(
        _with_excel_rows([row]),
        exceptions=[{
            "exception_id": "TEST-ZERO-RESET",
            "rule_id": "SEED-003",
            "Variable": "Imports",
            "Branch Path": "Resources\\Coal",
            "reason": "Explicit test-only reset exception.",
        }],
    )
    missing_id = result.findings[result.findings["rule_id"].eq("SEED-003")].iloc[0]
    assert missing_id["status"] == "excepted"
    assert not missing_id["blocking"]

    with pytest.raises(ValueError, match="measure/key"):
        validate_seed_rows(
            _with_excel_rows([row]),
            exceptions=[{"rule_id": "SEED-003"}],
        )


def test_validator_handles_inactive_shares_and_configured_coverage() -> None:
    rows = [
        _row("Transformation\\Plant\\Processes\\A", "Process Share", "Data(2022,0, 2023,0)"),
        _row("Transformation\\Plant\\Processes\\B", "Process Share", "Data(2022,0, 2023,0)"),
    ]
    result = validate_seed_rows(
        _with_excel_rows(rows),
        required_years=[2022, 2023, 2024],
        required_scenarios=["Reference", "Target"],
    )

    process_findings = result.findings[result.findings["rule_id"] == "SEED-007"]
    assert set(process_findings["status"]) == {"fail"}
    assert len(result.findings[result.findings["rule_id"] == "SEED-009"]) == 2
    assert len(result.findings[result.findings["rule_id"] == "SEED-010"]) == 2


def test_validator_branch_existence_and_explicit_exception(tmp_path: Path) -> None:
    template_path = tmp_path / "template.xlsx"
    template = pd.DataFrame([_row("Resources\\Gas", "Imports", "0")])
    with pd.ExcelWriter(template_path, engine="openpyxl") as writer:
        template.to_excel(writer, sheet_name="Export", index=False, startrow=2)
    candidate = _with_excel_rows([_row("Resources\\Unknown", "Imports", "0")])

    result = validate_seed_rows(candidate, template_path=template_path)
    assert result.findings[result.findings["rule_id"] == "SEED-011"]["blocking"].item()

    excepted = validate_seed_rows(
        candidate,
        template_path=template_path,
        exceptions=[{"rule_id": "SEED-011", "Branch Path": "Resources\\Unknown"}],
    )
    finding = excepted.findings[excepted.findings["rule_id"] == "SEED-011"].iloc[0]
    assert finding["status"] == "excepted"
    assert not finding["blocking"]


def test_june_usa_fixture_heat_interim_duplicate_is_resolved_to_valid_row() -> None:
    fixture_dir = Path("data/backup_tgt_ref_ca_20260625")
    files = sorted(fixture_dir.glob("leap_import_baseline_seed_20_USA_*.xlsx"))
    if not files:
        return
    data = read_seed_workbook(files[0])
    branch = "Transformation\\Heat plant interim\\Processes\\Heat plant interim"
    focused = data[
        data["Branch Path"].eq(branch)
        & data["Variable"].eq("Process Share")
        & data["Scenario"].eq("Current Accounts")
    ]

    resolved, duplicates = resolve_logical_duplicates(focused)

    assert len(focused) == 3
    assert resolved["BranchID"].tolist() == [2450]
    assert resolved["Expression"].tolist() == ["Data(2022,100.0)"]
    assert duplicates["classification"].tolist() == ["conflicting_expression_one_valid_id_row"]


def _write_template(path: Path, rows: list[dict[str, object]]) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(writer, sheet_name="Export", index=False, startrow=2)


def test_production_preparation_enriches_all_ids_and_collapses_exact_duplicates(
    tmp_path: Path,
) -> None:
    branch = "Transformation\\Heat plant interim\\Processes\\Heat plant interim"
    template_path = tmp_path / "template.xlsx"
    template_row = _row(branch, "Process Share", "")
    template_row.update({"BranchID": 2450, "VariableID": 418, "ScenarioID": 2, "RegionID": 1})
    _write_template(template_path, [template_row])

    rows = [
        _row(branch, "Process Share", "Data(2023,100)", branch_id=-1),
        _row(branch, "Process Share", "Data(2023, 100.0)", branch_id=2450),
    ]
    for row in rows:
        row.update({"VariableID": -1, "ScenarioID": -1, "RegionID": -1})
    result = prepare_seed_rows_for_write(
        _with_excel_rows(rows).sample(frac=1, random_state=3),
        template_path=template_path,
        diagnostics_dir=tmp_path / "diagnostics",
        diagnostic_stem="heat",
        required_years_by_scenario={"Reference": [2023]},
    )

    assert len(result.resolved_rows) == 1
    assert result.resolved_rows[["BranchID", "VariableID", "ScenarioID", "RegionID"]].iloc[0].tolist() == [2450, 418, 2, 1]
    assert result.duplicate_groups["classification"].tolist() == [
        "exact_duplicate_same_ids_and_expression"
    ]


def test_zero_reset_is_enriched_with_real_ids(tmp_path: Path) -> None:
    branch = "Resources\\Primary\\Gas"
    template_path = tmp_path / "template.xlsx"
    template_row = _row(branch, "Imports", "")
    template_row.update({"BranchID": 20, "VariableID": 30, "ScenarioID": 2, "RegionID": 1})
    _write_template(template_path, [template_row])
    candidate = _with_excel_rows([_row(branch, "Imports", "Data(2023,0)", branch_id=-1)])

    enriched = enrich_seed_ids_from_template(candidate, template_path)
    result = validate_seed_rows(enriched, template_path=template_path)

    assert enriched[["BranchID", "VariableID", "ScenarioID", "RegionID"]].iloc[0].tolist() == [20, 30, 2, 1]
    assert result.findings.empty


def test_share_validation_uses_resolved_rows_not_duplicate_physical_rows() -> None:
    gas = _row(
        "Transformation\\Plant\\Output Fuels\\Gas",
        "Output Share",
        "Data(2023,40)",
    )
    oil = _row(
        "Transformation\\Plant\\Output Fuels\\Oil",
        "Output Share",
        "Data(2023,60)",
    )
    result = validate_seed_rows(
        _with_excel_rows([gas, dict(gas), oil]),
        allow_exact_duplicate_resolution=True,
    )

    share_findings = result.findings[result.findings["rule_id"] == "SEED-006"]
    assert share_findings["status"].tolist() == ["pass"]
    assert share_findings["evidence"].tolist() == ["sum=100"]


def test_scenario_specific_year_and_source_coverage_block_when_incomplete() -> None:
    row = _row("Resources\\Primary\\Gas", "Imports", "Data(2023,1)")
    row["source_workflow"] = "supply_workflow"
    result = validate_seed_rows(
        _with_excel_rows([row]),
        required_years_by_scenario={"Reference": [2023, 2024]},
        required_scenarios_by_source={
            "supply_workflow": ["Reference", "Target"]
        },
    )

    assert result.findings[result.findings["rule_id"] == "SEED-009"]["blocking"].all()
    assert result.findings[result.findings["rule_id"] == "SEED-010"]["blocking"].all()


def test_conflicting_valid_rows_write_diagnostics_before_raising(tmp_path: Path) -> None:
    branch = "Resources\\Primary\\Gas"
    template_path = tmp_path / "template.xlsx"
    template_row = _row(branch, "Imports", "")
    _write_template(template_path, [template_row])
    candidate = _with_excel_rows([
        _row(branch, "Imports", "Data(2023,1)"),
        _row(branch, "Imports", "Data(2023,2)"),
    ])
    diagnostics_dir = tmp_path / "diagnostics"

    try:
        prepare_seed_rows_for_write(
            candidate,
            template_path=template_path,
            diagnostics_dir=diagnostics_dir,
            diagnostic_stem="conflict",
        )
    except BaselineSeedValidationError:
        pass
    else:
        raise AssertionError("Conflicting valid rows must block workbook preparation")

    findings_path = diagnostics_dir / "conflict_rule_findings.csv"
    duplicates_path = diagnostics_dir / "conflict_duplicate_groups.csv"
    assert findings_path.exists()
    assert duplicates_path.exists()
    duplicates = pd.read_csv(duplicates_path)
    assert duplicates["blocking"].tolist() == [True]


#%%
