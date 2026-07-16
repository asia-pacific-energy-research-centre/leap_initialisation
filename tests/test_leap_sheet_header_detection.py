"""Tests for the shared LEAP sheet header detector.

LEAP-style sheets carry a preamble above the real column header, so every reader
must find that header row first. That scan had been reimplemented ~8 times with
scan depths of 6 rows, 8 rows and unlimited, so a sheet whose header moved was
found by some readers and silently mis-parsed by others. These tests pin the
shared behaviour.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from codebase.functions.leap_excel_io import (
    LEAP_HEADER_TOKENS,
    find_leap_header_row,
    read_export_sheet,
    read_leap_sheet,
)


def _sheet(preamble_rows: int, *, blank_col: bool = False) -> pd.DataFrame:
    """Build a raw LEAP-style sheet with `preamble_rows` junk rows on top.

    The empty row and any blank spacer column sit mid-sheet on purpose: pandas
    drops *trailing* empty rows/columns when writing, so a fixture that put them
    last would never exercise the behaviour under test.
    """
    if blank_col:
        header = ["Branch Path", "Variable", None, "Scenario", "Region", "Expression"]
        row_a = ["Demand\\A", "Activity Level", None, "Reference", "United States", "0"]
        row_b = ["Demand\\B", "Activity Level", None, "Reference", "United States", "0"]
    else:
        header = ["Branch Path", "Variable", "Scenario", "Region", "Expression"]
        row_a = ["Demand\\A", "Activity Level", "Reference", "United States", "0"]
        row_b = ["Demand\\B", "Activity Level", "Reference", "United States", "0"]
    width = len(header)
    rows = [["LEAP preamble", *([None] * (width - 1))] for _ in range(preamble_rows)]
    rows.append(header)
    rows.append(row_a)
    rows.append([None] * width)  # all-empty row, kept mid-sheet
    rows.append(row_b)
    return pd.DataFrame(rows)


def test_finds_header_directly_at_row_zero():
    assert find_leap_header_row(_sheet(0)) == 0


def test_finds_header_below_a_preamble():
    assert find_leap_header_row(_sheet(2)) == 2


def test_returns_none_when_absent():
    raw = pd.DataFrame([["nothing", "here"], ["still", "nothing"]])
    assert find_leap_header_row(raw) is None


@pytest.mark.parametrize("depth", [7, 9, 15])
def test_scan_is_unlimited_not_capped_at_six_or_eight(depth: int):
    """The old readers capped at 6 or 8 rows and would miss these."""
    assert find_leap_header_row(_sheet(depth)) == depth


def test_detection_is_case_and_whitespace_insensitive():
    raw = pd.DataFrame([["  BRANCH path  ", "Variable ", "Scenario"]])
    assert find_leap_header_row(raw) == 0


def test_requires_all_tokens_not_just_one():
    raw = pd.DataFrame([["Branch Path", "Scale", "Units"]])
    assert find_leap_header_row(raw) is None
    assert set(LEAP_HEADER_TOKENS) == {"branch path", "variable"}


def _write(tmp_path: Path, raw: pd.DataFrame, sheet_name: str = "LEAP") -> Path:
    path = tmp_path / "sheet.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        raw.to_excel(writer, sheet_name=sheet_name, index=False, header=False)
    return path


def test_read_leap_sheet_splits_preamble_and_data(tmp_path: Path):
    sheet = read_leap_sheet(_write(tmp_path, _sheet(2)))

    assert sheet.header_row == 2
    assert len(sheet.preamble) == 2
    assert list(sheet.columns)[:2] == ["Branch Path", "Variable"]
    assert sheet.data["Branch Path"].tolist() == ["Demand\\A", "Demand\\B"]


def test_read_leap_sheet_drops_empty_rows_by_default(tmp_path: Path):
    sheet = read_leap_sheet(_write(tmp_path, _sheet(1)))
    assert len(sheet.data) == 2, "the all-empty row should be dropped"


def test_read_leap_sheet_can_keep_empty_rows(tmp_path: Path):
    """Write-back paths need row positions to line up with the original sheet."""
    sheet = read_leap_sheet(_write(tmp_path, _sheet(1)), drop_empty_rows=False)
    assert len(sheet.data) == 3, "the all-empty row must be preserved"


def test_blank_columns_are_kept_by_default(tmp_path: Path):
    """Default must not change any existing caller's column set."""
    sheet = read_leap_sheet(_write(tmp_path, _sheet(1, blank_col=True)))
    assert len(sheet.columns) == 6


def test_blank_columns_can_be_dropped_on_request(tmp_path: Path):
    """Seed sheets carry blank spacer columns whose duplicate NaN labels break
    per-row lookups during validation."""
    sheet = read_leap_sheet(
        _write(tmp_path, _sheet(1, blank_col=True)), drop_blank_columns=True
    )
    assert len(sheet.columns) == 5
    assert all(str(col).strip() not in ("", "nan") for col in sheet.columns)


def test_missing_header_raises_with_a_useful_message(tmp_path: Path):
    raw = pd.DataFrame([["nothing", "here"]])
    with pytest.raises(ValueError, match="Could not locate LEAP header row"):
        read_leap_sheet(_write(tmp_path, raw))


def test_routed_callers_use_the_shared_detector():
    """Regression guard: routed standard-sheet callers import the detector."""
    from codebase import aggregated_demand_workflow
    from codebase.functions import analysis_input_write_dispatcher
    from codebase.functions import patch_baseline_seeds, supply_leap_io, supply_results_saver

    assert hasattr(aggregated_demand_workflow, "find_leap_header_row")
    assert hasattr(analysis_input_write_dispatcher, "find_leap_header_row")
    assert hasattr(patch_baseline_seeds, "find_leap_header_row")
    assert hasattr(supply_leap_io, "read_leap_sheet")
    assert hasattr(supply_results_saver, "find_leap_header_row")


def test_patcher_keeps_blank_spacer_removal_and_uses_unlimited_scan():
    from codebase.functions.patch_baseline_seeds import _find_header_row

    columns, data = _find_header_row(_sheet(9, blank_col=True))

    assert columns == ["Branch Path", "Variable", "Scenario", "Region", "Expression"]
    assert data["Branch Path"].tolist() == ["Demand\\A", "Demand\\B"]


def test_supply_workbook_reader_uses_shared_unlimited_scan(tmp_path: Path):
    from codebase.functions.supply_leap_io import _read_workbook_sheet_with_header_detection

    path = _write(tmp_path, _sheet(9, blank_col=True))
    preamble, data, columns = _read_workbook_sheet_with_header_detection(path, "LEAP")

    assert len(preamble) == 9
    assert len(columns) == 6, "supply readers intentionally retain spacer columns"
    assert data["Branch Path"].tolist() == ["Demand\\A", "Demand\\B"]


def _export_sheet(preamble_rows: int) -> pd.DataFrame:
    header = [
        "BranchID", "VariableID", "ScenarioID", "RegionID", "Branch Path",
        "Variable", "Scenario", "Region",
    ]
    row = [1, 2, 3, 4, "Demand\\Other loss and own use\\A", "Activity Level", "Reference", "United States"]
    return pd.DataFrame(
        [["Export preamble", *([None] * (len(header) - 1))] for _ in range(preamble_rows)]
        + [header, row]
    )


def test_export_reader_keeps_branchid_criterion_with_unlimited_scan(tmp_path: Path):
    path = _write(tmp_path, _export_sheet(9), sheet_name="Export")

    preamble, data, columns = read_export_sheet(path, "Export")

    assert len(preamble) == 9
    assert columns[0] == "BranchID"
    assert data["Branch Path"].tolist() == ["Demand\\Other loss and own use\\A"]


def test_export_key_loader_detects_moved_export_header(tmp_path: Path):
    from codebase.functions.other_loss_own_use_proxy_utils import load_export_key_table

    path = _write(tmp_path, _export_sheet(7), sheet_name="Export")
    keys = load_export_key_table(path)

    assert keys[["BranchID", "VariableID", "ScenarioID", "RegionID"]].iloc[0].tolist() == [1, 2, 3, 4]


def test_results_saver_filter_detects_header_below_long_preamble(tmp_path: Path):
    from codebase.functions.supply_results_saver import _filter_transformation_workbook_to_trade_targets

    raw = _sheet(9)
    raw.iloc[10, 1] = "Import Target"
    raw.iloc[12, 1] = "Activity Level"
    path = _write(tmp_path, raw)

    _filter_transformation_workbook_to_trade_targets(path)
    filtered = read_leap_sheet(path)

    assert filtered.header_row == 9
    assert filtered.data["Variable"].tolist() == ["Import Target"]
