"""Tests for the workbook-backed missing-branch warning ledger."""
from pathlib import Path

import pandas as pd
from openpyxl import Workbook, load_workbook

from codebase.functions.baseline_seed_validation_exceptions import (
    REQUIRED_COLUMNS,
    NINTH_VALUE_COLUMN,
    refresh_exception_materiality,
    apply_zero_filter,
    audit_exception_relevance,
    register_material_missing_branch_findings,
    register_missing_branch_paths,
)


def _workbook(path: Path, branch_path: str = "") -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "branch_exceptions"
    sheet.append(REQUIRED_COLUMNS)
    if branch_path:
        sheet.append([True, branch_path, "", "", "", *([""] * (len(REQUIRED_COLUMNS) - 5))])
    workbook.save(path)


def test_registers_new_paths_enabled_with_observed_economy(tmp_path: Path) -> None:
    path = tmp_path / "exceptions.xlsx"
    _workbook(path)

    added = register_missing_branch_paths(
        ["Demand\\Other loss and own use\\Coal mines\\BKB and PB"],
        economy="20_USA", workbook_path=path,
    )

    assert added == ["Demand\\Other loss and own use\\Coal mines\\BKB and PB"]
    values = list(load_workbook(path)["branch_exceptions"].values)
    assert values[1][0] is True
    assert values[1][3] == "20_USA"


def test_refresh_uses_last_esto_year_and_reference_ninth_average(tmp_path: Path) -> None:
    branch = "Demand\\Other loss and own use\\Coal mines\\BKB and PB"
    workbook = tmp_path / "exceptions.xlsx"
    _workbook(workbook, branch)
    esto = tmp_path / "esto.csv"
    pd.DataFrame([{
        "economy": "01AUS", "flows": "10.01.06 Coal mines", "products": "02.08 BKB/PB",
        "is_subtotal": False, "2022": -2.0,
    }]).to_csv(esto, index=False)
    ninth = tmp_path / "ninth.csv"
    pd.DataFrame([
        {"scenarios": scenario, "sectors": "x", "sub1sectors": "x", "sub2sectors": "10_01_06_coal_mines",
         "fuels": "02_coal_products", "subfuels": "02_08_bkb_pb", "subtotal_layout": False,
         "subtotal_results": False, "2023": value, "2024": value}
        for scenario, value in (("reference", -3.0), ("target", -9.0))
    ]).to_csv(ninth, index=False)

    refreshed = refresh_exception_materiality(
        workbook, esto_vintages={"2024": (esto, 2022)}, ninth_path=ninth,
        projection_start_year=2023, projection_final_year=2024,
    )

    assert refreshed.at[0, "esto_2024_last_year_signed_pj_all_economies"] == -2.0
    assert refreshed.at[0, NINTH_VALUE_COLUMN] == -3.0


def test_final_stage_registers_material_economies_and_prunes_only_after_all_vintages(tmp_path: Path) -> None:
    path = tmp_path / "exceptions.xlsx"
    branch = r"Demand\Other loss and own use\Coal mines\BKB and PB"
    _workbook(path, branch)
    register_material_missing_branch_findings(
        pd.DataFrame([{"economy": "20_USA", "branch_path": branch}]), workbook_path=path,
    )
    audit_exception_relevance(
        {"ESTO 2026": pd.DataFrame([{"economy": "20_USA", "branch_path": branch}])},
        workbook_path=path, prune_after_all_vintages=True,
    )
    row = pd.read_excel(path).iloc[0]
    assert row["enabled"]
    assert row["economies_that_need_it"] == "20_USA"
    assert "ESTO 2026: triggered for 20_USA" in row["notes"]

    audit_exception_relevance(
        {"ESTO 2026": pd.DataFrame(columns=["economy", "branch_path"])},
        workbook_path=path, prune_after_all_vintages=True,
    )
    row = pd.read_excel(path).iloc[0]
    assert not row["enabled"]
    assert pd.isna(row["economies_that_need_it"])  # blank Excel cell reads as NaN
    assert "Disabled after the completed all-vintage relevance audit" in row["notes"]


def test_zero_filter_blanks_false_mapping_zeros_when_seed_audit_triggered() -> None:
    rows = pd.DataFrame([{
        "enabled": True,
        "branch_path": r"Demand\Other\Fuel",
        "relevance_audit": "ESTO 2026: triggered for 20_USA.",
        "esto_2024_last_year_signed_pj_all_economies": 0.0,
        "esto_2025_last_year_signed_pj_all_economies": 0.0,
        "esto_2026_last_year_signed_pj_all_economies": 0.0,
        "ninth_reference_average_pj_per_year_all_economies": 0.0,
    }])

    filtered = apply_zero_filter(rows)

    assert filtered.loc[0, "zero filter"] == "MAPPING INCOMPLETE — seed triggered"
    assert filtered.loc[0, "esto_2024_last_year_signed_pj_all_economies"] == ""


def test_materiality_refresh_does_not_refill_a_seed_triggered_mapping_gap(tmp_path: Path) -> None:
    workbook = tmp_path / "exceptions.xlsx"
    _workbook(workbook, r"Demand\Other loss and own use\Coal mines\BKB and PB")
    rows = pd.read_excel(workbook).fillna("")
    rows.loc[0, "relevance_audit"] = "ESTO 2026: triggered for 20_USA."
    rows.loc[0, "zero filter"] = "MAPPING INCOMPLETE — seed triggered"
    rows.to_excel(workbook, sheet_name="branch_exceptions", index=False)

    refreshed = refresh_exception_materiality(
        workbook,
        esto_vintages={},
        ninth_path=tmp_path / "not_needed.csv",
    )

    assert refreshed.loc[0, "zero filter"] == "MAPPING INCOMPLETE — seed triggered"
    assert refreshed.loc[0, NINTH_VALUE_COLUMN] == ""
