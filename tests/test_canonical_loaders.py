"""Unit tests for the shared canonical mapping loaders."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from codebase.mappings import canonical_loaders as cl
from codebase.mappings.canonical_loaders import CanonicalMappingError


def _write_workbook(path: Path, sheets: dict[str, pd.DataFrame]) -> None:
    with pd.ExcelWriter(path) as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=name, index=False)


def _base_sheets() -> dict[str, pd.DataFrame]:
    return {
        cl.SHEET_LEAP_COMBINED_ESTO: pd.DataFrame(
            [
                {
                    "leap_sector_name_full_path": "Transformation/Oil refineries",
                    "raw_leap_fuel_name": "Crude oil",
                    "esto_flow": "09.07 Oil refineries",
                    "esto_product": "06.01 Crude oil",
                },
            ]
        ),
        cl.SHEET_LEAP_COMBINED_NINTH: pd.DataFrame(
            [
                {
                    "leap_sector_name_full_path": "Transformation/Oil refineries",
                    "raw_leap_fuel_name": "Crude oil",
                    "ninth_sector": "09_07_oil_refineries",
                    "ninth_fuel": "06_01_crude_oil",
                },
            ]
        ),
        cl.SHEET_NINTH_PAIRS_TO_ESTO_PAIRS: pd.DataFrame(
            [
                {
                    "9th_sector": "09_07_oil_refineries",
                    "9th_fuel": "06_01_crude_oil",
                    "esto_flow": "09.07 Oil refineries",
                    "esto_product": "06.01 Crude oil",
                },
            ]
        ),
        cl.SHEET_LEAP_DISPLAY_NAMES: pd.DataFrame(
            [
                {"code": "06.01", "auto_name": "Crude", "leap_display_name": "Crude oil"},
                {"code": "17", "auto_name": "Elec", "leap_display_name": ""},
            ]
        ),
    }


# --- 1. Workbook / sheet / column validation --------------------------------
def test_missing_workbook_raises(tmp_path: Path):
    missing = tmp_path / "nope.xlsx"
    with pytest.raises(CanonicalMappingError, match="not found"):
        cl.load_leap_combined_esto(workbook=missing)


def test_missing_sheet_raises(tmp_path: Path):
    wb = tmp_path / "wb.xlsx"
    sheets = _base_sheets()
    del sheets[cl.SHEET_NINTH_PAIRS_TO_ESTO_PAIRS]
    _write_workbook(wb, sheets)
    with pytest.raises(CanonicalMappingError, match="missing required sheet"):
        cl.load_ninth_pairs_to_esto_pairs(workbook=wb)


def test_missing_columns_raises(tmp_path: Path):
    wb = tmp_path / "wb.xlsx"
    sheets = _base_sheets()
    sheets[cl.SHEET_LEAP_COMBINED_ESTO] = sheets[cl.SHEET_LEAP_COMBINED_ESTO].drop(columns=["esto_product"])
    _write_workbook(wb, sheets)
    with pytest.raises(CanonicalMappingError, match="missing required columns.*esto_product"):
        cl.load_leap_combined_esto(workbook=wb)


# --- 2. Active-row filtering ------------------------------------------------
def test_remove_row_and_duplicate_to_remove_filtering(tmp_path: Path):
    wb = tmp_path / "wb.xlsx"
    sheets = _base_sheets()
    esto = sheets[cl.SHEET_LEAP_COMBINED_ESTO]
    esto = pd.concat(
        [
            esto.assign(remove_row="", duplicate_to_remove=""),
            esto.assign(remove_row="TRUE", duplicate_to_remove=""),
            esto.assign(remove_row="", duplicate_to_remove="yes"),
        ],
        ignore_index=True,
    )
    sheets[cl.SHEET_LEAP_COMBINED_ESTO] = esto
    _write_workbook(wb, sheets)
    out = cl.load_leap_combined_esto(workbook=wb)
    assert len(out) == 1  # only the blank-flag row survives


def test_blank_optional_flags_keep_rows(tmp_path: Path):
    wb = tmp_path / "wb.xlsx"
    sheets = _base_sheets()
    sheets[cl.SHEET_LEAP_COMBINED_ESTO] = sheets[cl.SHEET_LEAP_COMBINED_ESTO].assign(
        remove_row="", duplicate_to_remove=None
    )
    _write_workbook(wb, sheets)
    assert len(cl.load_leap_combined_esto(workbook=wb)) == 1


def test_sheets_without_flag_columns_unchanged(tmp_path: Path):
    wb = tmp_path / "wb.xlsx"
    _write_workbook(wb, _base_sheets())
    assert len(cl.load_leap_combined_esto(workbook=wb)) == 1


# --- 3. Name resolution -----------------------------------------------------
def test_display_name_prefers_explicit_then_auto(tmp_path: Path):
    wb = tmp_path / "wb.xlsx"
    _write_workbook(wb, _base_sheets())
    mapping, conflicts = cl.build_code_to_display_name(workbook=wb)
    assert mapping["06.01"] == "Crude oil"  # explicit
    assert mapping["17"] == "Elec"  # falls back to auto_name
    assert conflicts.empty


def test_display_name_missing_code_absent(tmp_path: Path):
    wb = tmp_path / "wb.xlsx"
    _write_workbook(wb, _base_sheets())
    mapping, _ = cl.build_code_to_display_name(workbook=wb)
    assert "99.99" not in mapping


def test_display_name_builder_can_include_explicitly_excluded_labels(tmp_path: Path):
    wb = tmp_path / "wb.xlsx"
    sheets = _base_sheets()
    sheets[cl.SHEET_LEAP_DISPLAY_NAMES] = pd.DataFrame(
        [
            {
                "code": "01_coal",
                "leap_display_name": "Coal",
                "USED_IN_LEAP_INITIALISATION": False,
            }
        ]
    )
    _write_workbook(wb, sheets)

    default_mapping, _ = cl.build_code_to_display_name(workbook=wb)
    complete_mapping, _ = cl.build_code_to_display_name(
        workbook=wb,
        include_excluded=True,
    )

    assert "01_coal" not in default_mapping
    assert complete_mapping["01_coal"] == "Coal"


def test_display_name_duplicate_conflict_detected(tmp_path: Path):
    wb = tmp_path / "wb.xlsx"
    sheets = _base_sheets()
    sheets[cl.SHEET_LEAP_DISPLAY_NAMES] = pd.DataFrame(
        [
            {"code": "06.01", "auto_name": "", "leap_display_name": "Crude oil"},
            {"code": "06.01", "auto_name": "", "leap_display_name": "Crude petroleum"},
        ]
    )
    _write_workbook(wb, sheets)
    mapping, conflicts = cl.build_code_to_display_name(workbook=wb)
    assert mapping["06.01"] == "Crude oil"  # first wins, stable
    assert list(conflicts["code"]) == ["06.01"]


# --- 4. Pair mapping + ambiguity -------------------------------------------
def test_ninth_pairs_exact_and_no_conflict(tmp_path: Path):
    wb = tmp_path / "wb.xlsx"
    _write_workbook(wb, _base_sheets())
    pairs, conflicts = cl.load_ninth_pairs_to_esto_pairs(workbook=wb)
    assert len(pairs) == 1
    assert conflicts.empty


def test_ninth_pairs_conflict_detected(tmp_path: Path):
    wb = tmp_path / "wb.xlsx"
    sheets = _base_sheets()
    sheets[cl.SHEET_NINTH_PAIRS_TO_ESTO_PAIRS] = pd.DataFrame(
        [
            {"9th_sector": "s", "9th_fuel": "f", "esto_flow": "A", "esto_product": "P"},
            {"9th_sector": "s", "9th_fuel": "f", "esto_flow": "B", "esto_product": "Q"},
        ]
    )
    _write_workbook(wb, sheets)
    _, conflicts = cl.load_ninth_pairs_to_esto_pairs(workbook=wb)
    assert len(conflicts) == 1
    assert conflicts.iloc[0]["issue"] == "duplicate_source_conflicting_target"


def test_resolve_leap_fuel_exact(tmp_path: Path):
    wb = tmp_path / "wb.xlsx"
    _write_workbook(wb, _base_sheets())
    esto = cl.load_leap_combined_esto(workbook=wb)
    flow, product, status = cl.resolve_leap_fuel_to_esto(
        "Transformation/Oil refineries", "Crude oil", esto
    )
    assert status == "exact"
    assert flow == "09.07 Oil refineries"
    assert product == "06.01 Crude oil"


def test_resolve_leap_fuel_ambiguous():
    esto = pd.DataFrame(
        [
            {"leap_sector_name_full_path": "P1", "raw_leap_fuel_name": "F", "esto_flow": "A", "esto_product": "X"},
            {"leap_sector_name_full_path": "P2", "raw_leap_fuel_name": "F", "esto_flow": "B", "esto_product": "Y"},
        ]
    )
    # No exact path match; fuel-only maps to two products -> ambiguous, not first-row.
    flow, product, status = cl.resolve_leap_fuel_to_esto("P3", "F", esto)
    assert status == "ambiguous"
    assert flow == "" and product == ""


def test_resolve_leap_fuel_fuel_only_unambiguous():
    esto = pd.DataFrame(
        [
            {"leap_sector_name_full_path": "P1", "raw_leap_fuel_name": "F", "esto_flow": "A", "esto_product": "X"},
        ]
    )
    flow, product, status = cl.resolve_leap_fuel_to_esto("Pother", "F", esto)
    assert status == "fuel_only_unambiguous"
    assert product == "X"


def test_resolve_leap_fuel_missing():
    esto = pd.DataFrame(
        [
            {"leap_sector_name_full_path": "P1", "raw_leap_fuel_name": "F", "esto_flow": "A", "esto_product": "X"},
        ]
    )
    flow, product, status = cl.resolve_leap_fuel_to_esto("P1", "Z", esto)
    assert status == "missing"


# --- 5. Real canonical workbook smoke --------------------------------------
def test_real_canonical_workbook_loads():
    if not cl.CANONICAL_WORKBOOK_PATH.exists():
        pytest.skip("canonical workbook not present in this environment")
    esto = cl.load_leap_combined_esto()
    ninth = cl.load_leap_combined_ninth()
    pairs, conflicts = cl.load_ninth_pairs_to_esto_pairs()
    names, name_conflicts = cl.build_code_to_display_name()
    assert not esto.empty and not ninth.empty and not pairs.empty
    assert names  # non-empty code->name mapping
    # conflicts frames must have the documented schema even when empty
    assert "issue" in conflicts.columns and "issue" in name_conflicts.columns
