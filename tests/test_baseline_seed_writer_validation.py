#%%
"""Focused tests for validation at the final baseline-seed workbook writer."""

from pathlib import Path

import pandas as pd
import pytest

from codebase.functions.baseline_seed_validation import BaselineSeedValidationError
from codebase.functions.supply_leap_io import write_per_economy_combined_workbooks


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


def _write_template(path: Path) -> None:
    row = _row("")
    row.update({"BranchID": 101, "VariableID": 420, "ScenarioID": 2, "RegionID": 1})
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame([row]).to_excel(
            writer, sheet_name="Export", index=False, startrow=2
        )


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

    with pytest.raises(BaselineSeedValidationError, match="05_PRC/SEED-001"):
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
    assert "05_PRC" in set(findings["economy"])


#%%
