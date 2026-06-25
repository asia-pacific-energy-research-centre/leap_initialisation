from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from codebase.functions import supply_export_io


def _write_leap_style_workbook(path: Path, rows: list[dict]) -> None:
    """Write a tiny LEAP-style workbook with headers on row index 2."""
    df = pd.DataFrame(rows)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="LEAP", index=False, startrow=2)


def test_locate_supply_export_finds_explicit_and_latest_matching_files(tmp_path: Path) -> None:
    older = tmp_path / "supply_leap_imports_20_USA_Reference.xlsx"
    latest = tmp_path / "supply_leap_imports_20_USA_Target.xlsx"
    unrelated = tmp_path / "transformation_leap_imports_20_USA_Target.xlsx"
    older.touch()
    latest.touch()
    unrelated.touch()

    explicit = supply_export_io.locate_supply_export(
        tmp_path,
        filename="supply_leap_imports_20_USA_Reference.xlsx",
    )
    detected_latest = supply_export_io.locate_supply_export(tmp_path)

    assert explicit == older
    assert detected_latest == latest


def test_extract_export_metadata_parses_scenario_names_from_filename() -> None:
    export_path = Path("supply_leap_imports_20_USA_CurrentAccounts_Target.xlsx")

    metadata = supply_export_io.extract_export_metadata(export_path)

    assert metadata == ["Current Accounts", "Target"]


def test_get_available_scenarios_reads_leap_header_row(tmp_path: Path) -> None:
    workbook = tmp_path / "supply_leap_imports_20_USA_Reference_Target.xlsx"
    _write_leap_style_workbook(
        workbook,
        [
            {"Scenario": "Reference", "Region": "United States", "Branch Path": "Resources\\Primary\\Coal"},
            {"Scenario": "Target", "Region": "United States", "Branch Path": "Resources\\Primary\\Coal"},
            {"Scenario": "Reference", "Region": "United States", "Branch Path": "Resources\\Secondary\\Electricity"},
        ],
    )

    scenarios = supply_export_io.get_available_scenarios(workbook)

    assert scenarios == ["Reference", "Target"]


def test_ensure_region_in_export_raises_for_missing_region(tmp_path: Path) -> None:
    workbook = tmp_path / "supply_leap_imports_20_USA_Reference.xlsx"
    _write_leap_style_workbook(
        workbook,
        [
            {"Scenario": "Reference", "Region": "United States", "Branch Path": "Resources\\Primary\\Coal"},
        ],
    )

    with pytest.raises(ValueError, match="Region 'Canada' not found"):
        supply_export_io.ensure_region_in_export(workbook, "Canada")


def test_get_supply_fuels_from_export_extracts_final_branch_path_segments(tmp_path: Path) -> None:
    workbook = tmp_path / "supply_leap_imports_20_USA_Reference.xlsx"
    _write_leap_style_workbook(
        workbook,
        [
            {"Scenario": "Reference", "Region": "United States", "Branch Path": "Resources\\Primary\\Coal"},
            {"Scenario": "Reference", "Region": "United States", "Branch Path": "Resources\\Primary\\Coal"},
            {"Scenario": "Reference", "Region": "United States", "Branch Path": "Resources\\Secondary\\Electricity"},
            {"Scenario": "Reference", "Region": "United States", "Branch Path": "Resources"},
        ],
    )

    fuels = supply_export_io.get_supply_fuels_from_export(workbook)

    assert fuels == ["Coal", "Electricity"]
