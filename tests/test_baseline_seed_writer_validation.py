#%%
"""Focused tests for validation at the final baseline-seed workbook writer."""

from pathlib import Path

import pandas as pd
import pytest

from codebase.functions.baseline_seed_validation import (
    BaselineSeedValidationError,
    build_validation_issue_groups,
)
from codebase.functions.supply_leap_io import write_per_economy_combined_workbooks
from codebase.configuration.workflow_config import get_baseline_seed_validation_years


def _row(expression: str) -> dict[str, object]:
    return {
        "BranchID": -1,
        "VariableID": -1,
        "ScenarioID": -1,
        "RegionID": -1,
        "Branch Path": "Resources\\Primary\\Natural gas",
        "Variable": "Imports",
        "Scenario": "Reference",
        "Region": "United States",
        "Scale": "",
        "Units": "Petajoule",
        "Per...": "",
        "Expression": expression,
    }


def _write_leap_workbook(path: Path, rows: list[dict[str, object]]) -> None:
    columns = list(rows[0])
    preamble = {column: pd.NA for column in columns}
    preamble["Branch Path"] = "Area:"
    preamble["Scenario"] = "Ver:"
    preamble["Region"] = "2"
    full = pd.concat(
        [
            pd.DataFrame([preamble]),
            pd.DataFrame([{column: pd.NA for column in columns}]),
            pd.DataFrame([columns], columns=columns),
            pd.DataFrame(rows),
        ],
        ignore_index=True,
    )
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        full.to_excel(writer, sheet_name="LEAP", index=False, header=False)


def _write_template(path: Path, *, variable_id: int = 420) -> None:
    row = _row("")
    row.update({"BranchID": 101, "VariableID": variable_id, "ScenarioID": 2, "RegionID": 1})
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame([row]).to_excel(
            writer, sheet_name="Export", index=False, startrow=2
        )


def _write_template_rows(path: Path, rows: list[dict[str, object]]) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(
            writer, sheet_name="Export", index=False, startrow=2
        )


def test_default_scenario_windows_use_2022_base_and_2060_final_year() -> None:
    windows = get_baseline_seed_validation_years(
        ["Current Accounts", "Reference", "Target"]
    )
    assert windows["Current Accounts"] == [2022]
    assert windows["Reference"][0] == 2023
    assert windows["Reference"][-1] == 2060
    assert windows["Target"] == windows["Reference"]


def test_final_writer_collapses_exact_duplicates_and_populates_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "supply_leap_imports_20_USA_reference.xlsx"
    _write_leap_workbook(source, [_row("Data(2023,1)"), _row("Data(2023, 1.0)")])
    template = tmp_path / "full model export.xlsx"
    _write_template(template)
    monkeypatch.setattr(
        "codebase.functions.supply_leap_io._load_reference_export_data",
        lambda: pd.DataFrame(),
    )

    written = write_per_economy_combined_workbooks(
        economies=["20_USA"],
        output_dir=tmp_path / "output",
        id_lookup_path=template,
        source_workbooks_by_workflow={"supply_workflow": [source]},
        required_years_by_scenario={"Reference": [2023]},
    )

    assert len(written) == 1
    data = pd.read_excel(written[0], sheet_name="LEAP", header=2)
    assert len(data) == 1
    assert data[["BranchID", "VariableID", "ScenarioID", "RegionID"]].iloc[0].tolist() == [101, 420, 2, 1]


def test_final_writer_writes_diagnostics_before_conflict_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "supply_leap_imports_20_USA_reference.xlsx"
    _write_leap_workbook(source, [_row("Data(2023,1)"), _row("Data(2023,2)")])
    template = tmp_path / "full model export.xlsx"
    _write_template(template)
    output_dir = tmp_path / "output"
    monkeypatch.setattr(
        "codebase.functions.supply_leap_io._load_reference_export_data",
        lambda: pd.DataFrame(),
    )

    with pytest.raises(BaselineSeedValidationError):
        write_per_economy_combined_workbooks(
            economies=["20_USA"],
            output_dir=output_dir,
            id_lookup_path=template,
            source_workbooks_by_workflow={"supply_workflow": [source]},
        )

    assert not list(output_dir.glob("leap_import_baseline_seed_*.xlsx"))
    diagnostics = output_dir / "supporting_files" / "baseline_seed_validation"
    assert list(diagnostics.glob("*_rule_findings.csv"))
    assert list(diagnostics.glob("*_duplicate_groups.csv"))


def test_writer_accumulates_economy_failures_and_writes_no_final_workbook(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    usa = tmp_path / "supply_leap_imports_20_USA_reference.xlsx"
    prc = tmp_path / "supply_leap_imports_05_PRC_reference.xlsx"
    _write_leap_workbook(usa, [_row("Data(2023,1)")])
    _write_leap_workbook(prc, [_row("Data(2023,1)"), _row("Data(2023,2)")])
    template = tmp_path / "full model export.xlsx"
    _write_template(template)
    output_dir = tmp_path / "output"
    monkeypatch.setattr(
        "codebase.functions.supply_leap_io._load_reference_export_data",
        lambda: pd.DataFrame(),
    )

    # The consolidated summary reports aggregated rule counts (e.g. "SEED-001=1"),
    # not per-economy prefixes -- economy attribution is verified below via the
    # consolidated findings CSV instead.
    with pytest.raises(BaselineSeedValidationError, match="SEED-001"):
        write_per_economy_combined_workbooks(
            economies=["20_USA", "05_PRC"],
            output_dir=output_dir,
            id_lookup_path=template,
            source_workbooks_by_workflow={"supply_workflow": [usa, prc]},
            required_years_by_scenario={"Reference": [2023]},
        )

    assert not list(output_dir.glob("leap_import_baseline_seed_*.xlsx"))
    diagnostics = output_dir / "supporting_files" / "baseline_seed_validation"
    assert list(diagnostics.glob("baseline_seed_20_USA_*_rule_findings.csv"))
    consolidated = list(diagnostics.glob("*_consolidated_rule_findings.csv"))
    assert len(consolidated) == 1
    findings = pd.read_csv(consolidated[0])
    seed_001 = findings[findings["rule_id"] == "SEED-001"]
    assert set(seed_001["economy"]) == {"05_PRC"}


def test_final_writer_writes_grouped_missing_branch_issue_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "electricity_heat_interim_20_USA_Target_Reference_Current_Accounts.xlsx"
    _write_leap_workbook(source, [{
        "BranchID": -1,
        "VariableID": -1,
        "ScenarioID": -1,
        "RegionID": -1,
        "Branch Path": "Transformation\\CHP interim\\Processes\\CHP interim\\Feedstock Fuels\\Ammonia",
        "Variable": "Imports",
        "Scenario": "Reference",
        "Region": "United States",
        "Scale": "",
        "Units": "Petajoule",
        "Per...": "",
        "Expression": "Data(2023,1)",
    }])
    template = tmp_path / "full model export.xlsx"
    _write_template(template)
    output_dir = tmp_path / "output"
    monkeypatch.setattr(
        "codebase.functions.supply_leap_io._load_reference_export_data",
        lambda: pd.DataFrame(),
    )
    monkeypatch.setattr("codebase.utilities.workflow_common.THROW_ERROR_AFTER_RUN", True)

    write_per_economy_combined_workbooks(
        economies=["20_USA"],
        output_dir=output_dir,
        id_lookup_path=template,
        source_workbooks_by_workflow={"electricity_heat_interim_workflow": [source]},
        required_years_by_scenario={"Reference": [2023]},
    )

    diagnostics = output_dir / "supporting_files" / "baseline_seed_validation"
    issue_groups = next(diagnostics.glob("*_issue_groups.csv"))
    grouped = pd.read_csv(issue_groups)
    assert len(grouped) == 1
    assert grouped["primary_rule_id"].iloc[0] == "SEED-011"
    assert grouped["member_rule_ids"].iloc[0] == "SEED-003|SEED-004|SEED-011"
    assert "canonical full-model export" in grouped["summary"].iloc[0]


def test_grouped_share_issues_collapse_to_one_issue_per_share_group() -> None:
    findings = pd.DataFrame([
        {
            "economy": "20_USA",
            "rule_id": "SEED-007",
            "blocking": True,
            "Branch Path": "Transformation\\Plant",
            "Variable": "Process Share",
            "Scenario": "Reference",
            "Region": "United States",
            "year": 2023,
            "source_workflow": "transformation_workflow",
            "source_file": "transformation_20_USA.xlsx",
            "evidence": "sum=80",
        },
        {
            "economy": "20_USA",
            "rule_id": "SEED-007",
            "blocking": True,
            "Branch Path": "Transformation\\Plant",
            "Variable": "Process Share",
            "Scenario": "Reference",
            "Region": "United States",
            "year": 2024,
            "source_workflow": "transformation_workflow",
            "source_file": "transformation_20_USA.xlsx",
            "evidence": "sum=75",
        },
    ])

    grouped = build_validation_issue_groups(findings)
    share = grouped[grouped["issue_group_type"].eq("share_group")]
    assert len(share) == 1
    assert share["primary_rule_id"].iloc[0] == "SEED-007"
    assert share["member_count"].iloc[0] == 2
    assert share["year_min"].iloc[0] == 2023
    assert share["year_max"].iloc[0] == 2024


def test_final_writer_exposes_key_scoped_zero_reset_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "supply_leap_imports_20_USA_reference.xlsx"
    expression = "Data(" + ",".join(
        token for year in range(2023, 2061) for token in (str(year), "0")
    ) + ")"
    _write_leap_workbook(source, [_row(expression)])
    template = tmp_path / "full model export.xlsx"
    _write_template(template, variable_id=-1)
    monkeypatch.setattr(
        "codebase.functions.supply_leap_io._load_reference_export_data",
        lambda: pd.DataFrame(),
    )

    written = write_per_economy_combined_workbooks(
        economies=["20_USA"],
        output_dir=tmp_path / "output",
        id_lookup_path=template,
        source_workbooks_by_workflow={"supply_workflow": [source]},
        validation_exceptions=[{
            "exception_id": "TEST-ZERO-RESET",
            "rule_id": "SEED-003",
            "Variable": "Imports",
            "Branch Path": "Resources\\Primary\\Natural gas",
            "reason": "Test-only explicit exception.",
        }],
    )

    assert len(written) == 1
    output = pd.read_excel(written[0], sheet_name="LEAP", header=2)
    assert output["VariableID"].iloc[0] == -1


def test_final_writer_preserves_non_branch_ids_for_warning_only_aggregated_demand_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "aggregated_demand_20_USA_reference.xlsx"
    _write_leap_workbook(source, [{
        "BranchID": -1,
        "VariableID": 2040,
        "ScenarioID": 2,
        "RegionID": 1,
        "Branch Path": "Demand\\All demand aggregated\\Black liquor",
        "Variable": "Final Energy Intensity",
        "Scenario": "Reference",
        "Region": "United States",
        "Scale": "",
        "Units": "Petajoule",
        "Per...": "Million households",
        "Expression": "1",
    }])
    template = tmp_path / "full model export.xlsx"
    _write_template_rows(template, [{
        "BranchID": 500,
        "VariableID": 900,
        "ScenarioID": 2,
        "RegionID": 1,
        "Branch Path": "Demand\\All demand aggregated\\Electricity",
        "Variable": "Final Energy Intensity",
        "Scenario": "Reference",
        "Region": "United States",
        "Scale": "",
        "Units": "Petajoule",
        "Per...": "Million households",
        "Expression": "1",
    }])
    monkeypatch.setattr(
        "codebase.functions.supply_leap_io._load_reference_export_data",
        lambda: pd.DataFrame(),
    )

    written = write_per_economy_combined_workbooks(
        economies=["20_USA"],
        output_dir=tmp_path / "output",
        id_lookup_path=template,
        source_workbooks_by_workflow={"aggregated_demand_workflow": [source]},
        required_years_by_scenario={"Reference": [2023]},
    )

    assert len(written) == 1
    output = pd.read_excel(written[0], sheet_name="LEAP", header=2)
    row = output.loc[
        output["Branch Path"].eq("Demand\\All demand aggregated\\Black liquor")
        & output["Variable"].eq("Final Energy Intensity")
    ].iloc[0]
    assert row["BranchID"] == -1
    assert row["VariableID"] == 2040

    consolidated = next(
        (tmp_path / "output" / "supporting_files" / "baseline_seed_validation").glob(
            "*_consolidated_rule_findings.csv"
        )
    )
    findings = pd.read_csv(consolidated)
    aggregate_findings = findings[
        findings["rule_id"].isin(["SEED-003", "SEED-004", "SEED-011"])
    ]
    assert set(aggregate_findings["status"]) == {"warn"}
    assert not aggregate_findings["blocking"].any()


def test_default_reference_validation_window_requires_2023_through_2060(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "supply_leap_imports_20_USA_reference.xlsx"
    _write_leap_workbook(source, [_row("Data(2023,1,2060,1)")])
    template = tmp_path / "full model export.xlsx"
    _write_template(template)
    output_dir = tmp_path / "output"
    monkeypatch.setattr(
        "codebase.functions.supply_leap_io._load_reference_export_data",
        lambda: pd.DataFrame(),
    )

    with pytest.raises(BaselineSeedValidationError, match="SEED-009"):
        write_per_economy_combined_workbooks(
            economies=["20_USA"],
            output_dir=output_dir,
            id_lookup_path=template,
            source_workbooks_by_workflow={"supply_workflow": [source]},
        )
    assert not list(output_dir.glob("leap_import_baseline_seed_*.xlsx"))


def test_missing_configured_producer_for_economy_blocks_final_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "supply_leap_imports_20_USA_reference.xlsx"
    _write_leap_workbook(source, [_row("1")])
    other_economy_source = tmp_path / "transformation_leap_imports_05_PRC_reference.xlsx"
    _write_leap_workbook(other_economy_source, [_row("1")])
    template = tmp_path / "full model export.xlsx"
    _write_template(template)
    output_dir = tmp_path / "output"
    monkeypatch.setattr(
        "codebase.functions.supply_leap_io._load_reference_export_data",
        lambda: pd.DataFrame(),
    )

    with pytest.raises(BaselineSeedValidationError, match="SEED-012"):
        write_per_economy_combined_workbooks(
            economies=["20_USA"],
            output_dir=output_dir,
            id_lookup_path=template,
            source_workbooks_by_workflow={
                "supply_workflow": [source],
                "transformation_workflow": [other_economy_source],
            },
        )
    consolidated = next(
        (output_dir / "supporting_files" / "baseline_seed_validation").glob(
            "*_consolidated_rule_findings.csv"
        )
    )
    findings = pd.read_csv(consolidated)
    coverage = findings[findings["rule_id"].eq("SEED-012")]
    assert coverage["source_workflow"].tolist() == ["transformation_workflow"]
    # The finding must explain why the probe rejected each configured path:
    # here the transformation workbook exists but is named for another economy.
    message = str(coverage["message"].iloc[0])
    assert "1 configured workbook(s) exist only for other economies" in message


def test_missing_producer_finding_names_nonexistent_workbook_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "supply_leap_imports_20_USA_reference.xlsx"
    _write_leap_workbook(source, [_row("1")])
    absent_source = tmp_path / "transformation_leap_imports_20_USA_reference.xlsx"
    template = tmp_path / "full model export.xlsx"
    _write_template(template)
    output_dir = tmp_path / "output"
    monkeypatch.setattr(
        "codebase.functions.supply_leap_io._load_reference_export_data",
        lambda: pd.DataFrame(),
    )

    with pytest.raises(BaselineSeedValidationError, match="SEED-012"):
        write_per_economy_combined_workbooks(
            economies=["20_USA"],
            output_dir=output_dir,
            id_lookup_path=template,
            source_workbooks_by_workflow={
                "supply_workflow": [source],
                "transformation_workflow": [absent_source],
            },
        )
    consolidated = next(
        (output_dir / "supporting_files" / "baseline_seed_validation").glob(
            "*_consolidated_rule_findings.csv"
        )
    )
    findings = pd.read_csv(consolidated)
    coverage = findings[findings["rule_id"].eq("SEED-012")]
    assert coverage["source_workflow"].tolist() == ["transformation_workflow"]
    message = str(coverage["message"].iloc[0])
    assert "1 expected workbook(s) do not exist on disk" in message
    # The concrete missing path is carried on the finding itself.
    assert str(absent_source) in str(coverage["source_file"].iloc[0])


def test_final_writer_can_skip_validation_for_side_combines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "supply_leap_imports_20_USA_reference.xlsx"
    _write_leap_workbook(source, [_row("Data(2023,1)")])
    monkeypatch.setattr(
        "codebase.functions.supply_leap_io._load_reference_export_data",
        lambda: pd.DataFrame(),
    )

    written = write_per_economy_combined_workbooks(
        economies=["20_USA"],
        output_dir=tmp_path / "output",
        source_workbooks_by_workflow={"supply_workflow": [source]},
        enforce_validation=False,
    )

    assert len(written) == 1
    assert written[0].exists()
    output = pd.read_excel(written[0], sheet_name="LEAP", header=2)
    assert output["Branch Path"].iloc[0] == "Resources\\Primary\\Natural gas"


#%%
