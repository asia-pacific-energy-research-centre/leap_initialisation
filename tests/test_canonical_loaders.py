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
                    "ninth_sector": "09_07_oil_refineries",
                    "ninth_fuel": "06_01_crude_oil",
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


# --- 3b. D3.2 rollup-label handling -----------------------------------------
# No rollup ever appears in LEAP - only its components do, recursively where
# a component is itself a rollup - sourced from leap_rollup_rules.

def _rollup_rules_df(rows: list[dict[str, object]]) -> pd.DataFrame:
    """Fill every leap_rollup_rules contract column, defaulting to blank."""
    columns = list(cl.CANONICAL_SHEET_CONTRACT[cl.SHEET_LEAP_ROLLUP_RULES])
    filled = [{col: row.get(col, "") for col in columns} for row in rows]
    return pd.DataFrame(filled, columns=columns)


def test_rollup_flagged_row_excluded_from_default_display_name_mapping(tmp_path: Path):
    wb = tmp_path / "wb.xlsx"
    sheets = _base_sheets()
    sheets[cl.SHEET_LEAP_DISPLAY_NAMES] = pd.DataFrame(
        [
            {
                "code": "09_08_coal_transformation",
                "leap_display_name": "Coal transformation",
                "IS_LEAP_ROLLUP_NAME": True,
            },
            {"code": "06.01", "leap_display_name": "Crude oil"},
        ]
    )
    _write_workbook(wb, sheets)
    mapping, _ = cl.build_code_to_display_name(workbook=wb)
    assert "09_08_coal_transformation" not in mapping
    assert mapping["06.01"] == "Crude oil"


def test_rollup_flagged_row_included_when_usage_filter_disabled(tmp_path: Path):
    """Mirrors the USED_IN_LEAP_INITIALISATION include_excluded contract: a
    caller that opts out of usage filtering (e.g. electricity_heat_interim_
    workflow's own suppression guard, which resolves aggregate labels by name
    on purpose so it can suppress them) must keep seeing rollup labels too.
    """
    wb = tmp_path / "wb.xlsx"
    sheets = _base_sheets()
    sheets[cl.SHEET_LEAP_DISPLAY_NAMES] = pd.DataFrame(
        [
            {
                "code": "09_08_coal_transformation",
                "leap_display_name": "Coal transformation",
                "IS_LEAP_ROLLUP_NAME": True,
            },
        ]
    )
    _write_workbook(wb, sheets)
    default_mapping, _ = cl.build_code_to_display_name(workbook=wb)
    complete_mapping, _ = cl.build_code_to_display_name(workbook=wb, include_excluded=True)
    assert "09_08_coal_transformation" not in default_mapping
    assert complete_mapping["09_08_coal_transformation"] == "Coal transformation"


def test_resolve_rollup_components_single_level(tmp_path: Path):
    wb = tmp_path / "wb.xlsx"
    sheets = _base_sheets()
    sheets[cl.SHEET_LEAP_ROLLUP_RULES] = _rollup_rules_df(
        [
            {
                "rolled_leap_sector_name_full_path": "Coal transformation",
                "input_leap_sector_name_full_path": "Coke ovens",
            },
            {
                "rolled_leap_sector_name_full_path": "Coal transformation",
                "input_leap_sector_name_full_path": "Blast furnaces",
            },
        ]
    )
    _write_workbook(wb, sheets)
    components = cl.resolve_rollup_components("Coal transformation", workbook=wb)
    assert components == ["Blast furnaces", "Coke ovens"]


def test_resolve_rollup_components_recurses_rollup_of_rollup(tmp_path: Path):
    """The likely-wrong implementation stops after one level; this must not."""
    wb = tmp_path / "wb.xlsx"
    sheets = _base_sheets()
    sheets[cl.SHEET_LEAP_ROLLUP_RULES] = _rollup_rules_df(
        [
            {
                "rolled_leap_sector_name_full_path": "Total transformation sector",
                "input_leap_sector_name_full_path": "Coal transformation",
            },
            {
                "rolled_leap_sector_name_full_path": "Total transformation sector",
                "input_leap_sector_name_full_path": "Oil refineries",
            },
            {
                "rolled_leap_sector_name_full_path": "Coal transformation",
                "input_leap_sector_name_full_path": "Coke ovens",
            },
            {
                "rolled_leap_sector_name_full_path": "Coal transformation",
                "input_leap_sector_name_full_path": "Blast furnaces",
            },
        ]
    )
    _write_workbook(wb, sheets)
    components = cl.resolve_rollup_components("Total transformation sector", workbook=wb)
    # "Coal transformation" must be expanded to its own components, not
    # returned as-is - a one-level implementation would return it unexpanded.
    assert "Coal transformation" not in components
    assert set(components) == {"Blast furnaces", "Coke ovens", "Oil refineries"}


def test_resolve_rollup_components_fuel_level(tmp_path: Path):
    wb = tmp_path / "wb.xlsx"
    sheets = _base_sheets()
    sheets[cl.SHEET_LEAP_ROLLUP_RULES] = _rollup_rules_df(
        [
            {
                "rolled_raw_leap_fuel_name": "Other petroleum products",
                "input_raw_leap_fuel_name": "Naphtha",
            },
            {
                "rolled_raw_leap_fuel_name": "Other petroleum products",
                "input_raw_leap_fuel_name": "White spirit",
            },
        ]
    )
    _write_workbook(wb, sheets)
    components = cl.resolve_rollup_components("Other petroleum products", workbook=wb)
    assert components == ["Naphtha", "White spirit"]


def test_resolve_rollup_components_raises_on_cycle(tmp_path: Path):
    wb = tmp_path / "wb.xlsx"
    sheets = _base_sheets()
    sheets[cl.SHEET_LEAP_ROLLUP_RULES] = _rollup_rules_df(
        [
            {
                "rolled_leap_sector_name_full_path": "A",
                "input_leap_sector_name_full_path": "B",
            },
            {
                "rolled_leap_sector_name_full_path": "B",
                "input_leap_sector_name_full_path": "A",
            },
        ]
    )
    _write_workbook(wb, sheets)
    with pytest.raises(CanonicalMappingError, match="cycle"):
        cl.resolve_rollup_components("A", workbook=wb)


def test_resolve_rollup_components_raises_when_not_a_rollup(tmp_path: Path):
    wb = tmp_path / "wb.xlsx"
    sheets = _base_sheets()
    sheets[cl.SHEET_LEAP_ROLLUP_RULES] = _rollup_rules_df([])
    _write_workbook(wb, sheets)
    with pytest.raises(CanonicalMappingError, match="no matching row"):
        cl.resolve_rollup_components("Not a rollup at all", workbook=wb)


def test_is_rollup_label_cross_check_catches_unflagged_rollup():
    """The stronger test T10 recommended: ask the rollup-rule sheet directly
    rather than trusting IS_LEAP_ROLLUP_NAME, so a rollup missing the flag is
    still caught."""
    rules = _rollup_rules_df(
        [
            {
                "rolled_leap_sector_name_full_path": "Coal transformation",
                "input_leap_sector_name_full_path": "Coke ovens",
            },
        ]
    )
    assert cl.is_rollup_label("Coal transformation", rules) is True
    assert cl.is_rollup_label("Coke ovens", rules) is False
    assert cl.is_rollup_label("Never mentioned anywhere", rules) is False


def test_assert_not_rollup_label_raises_for_rollup_and_passes_for_real_branch(tmp_path: Path):
    wb = tmp_path / "wb.xlsx"
    sheets = _base_sheets()
    sheets[cl.SHEET_LEAP_ROLLUP_RULES] = _rollup_rules_df(
        [
            {
                "rolled_leap_sector_name_full_path": "Coal transformation",
                "input_leap_sector_name_full_path": "Coke ovens",
            },
        ]
    )
    _write_workbook(wb, sheets)
    with pytest.raises(CanonicalMappingError, match="Rollup label"):
        cl.assert_not_rollup_label("Coal transformation", code="09.08", workbook=wb)
    # A real (non-rollup) branch name must pass silently.
    cl.assert_not_rollup_label("Coke ovens", code="09.08.01", workbook=wb)


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
            {"ninth_sector": "s", "ninth_fuel": "f", "esto_flow": "A", "esto_product": "P"},
            {"ninth_sector": "s", "ninth_fuel": "f", "esto_flow": "B", "esto_product": "Q"},
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
