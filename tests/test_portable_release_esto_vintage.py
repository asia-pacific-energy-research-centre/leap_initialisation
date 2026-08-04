"""Tests for deriving the ESTO base year and refusing to mix vintages."""

from pathlib import Path

import pytest

from codebase.portable_release.esto_vintage import (
    EstoVintage,
    EstoVintageError,
    check_vintage_consistency,
    infer_esto_vintage,
    read_year_columns,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
ESTO_2024 = REPO_ROOT / "data" / "00APEC_2024_low_with_subtotals.csv"
ESTO_2025 = REPO_ROOT / "data" / "00APEC_2025_low_with_subtotals.csv"


def _write_table(path: Path, years: list[int]) -> Path:
    header = ["economy", "flows", "products", "is_subtotal", *[str(y) for y in years]]
    row = ["01AUS", "01 Production", "17 Electricity", "FALSE", *["0"] * len(years)]
    path.write_text(",".join(header) + "\n" + ",".join(row) + "\n", encoding="utf-8")
    return path


def test_base_year_is_the_last_year_column(tmp_path: Path) -> None:
    table = _write_table(tmp_path / "esto.csv", list(range(1990, 2023)))
    vintage = infer_esto_vintage(table)
    assert vintage.first_year == 1990
    assert vintage.base_year == 2022
    assert vintage.label == "1990-2022"


def test_a_later_issue_moves_the_base_year(tmp_path: Path) -> None:
    vintage = infer_esto_vintage(_write_table(tmp_path / "esto.csv", list(range(1990, 2025))))
    assert vintage.base_year == 2024


def test_non_year_columns_are_ignored(tmp_path: Path) -> None:
    path = tmp_path / "esto.csv"
    path.write_text(
        "economy,flows,products,is_subtotal,2020,2021,notes\n"
        "01AUS,01 Production,17 Electricity,FALSE,0,0,something\n",
        encoding="utf-8",
    )
    assert read_year_columns(path) == [2020, 2021]
    assert infer_esto_vintage(path).base_year == 2021


def test_implausible_numeric_columns_are_not_treated_as_years(tmp_path: Path) -> None:
    path = tmp_path / "esto.csv"
    path.write_text("economy,12345,2020,2021\n01AUS,0,0,0\n", encoding="utf-8")
    assert read_year_columns(path) == [2020, 2021]


def test_a_table_with_no_year_columns_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "esto.csv"
    path.write_text("economy,flows,products\n01AUS,x,y\n", encoding="utf-8")
    with pytest.raises(EstoVintageError, match="declares no year columns"):
        infer_esto_vintage(path)


def test_a_single_year_column_is_rejected(tmp_path: Path) -> None:
    table = _write_table(tmp_path / "esto.csv", [2022])
    with pytest.raises(EstoVintageError, match="only one year column"):
        infer_esto_vintage(table)


def test_a_missing_file_is_reported_in_plain_language(tmp_path: Path) -> None:
    with pytest.raises(EstoVintageError, match="Could not read"):
        infer_esto_vintage(tmp_path / "absent.csv")


# ---------------------------------------------------------------------------
# Vintage consistency
# ---------------------------------------------------------------------------


def _vintage(base_year: int) -> EstoVintage:
    return EstoVintage(path=Path("esto.csv"), first_year=1990, base_year=base_year)


def test_matching_vintages_raise_no_problem() -> None:
    assert check_vintage_consistency(supplied=_vintage(2022), packaged_base_year=2022) == []


def test_an_unknown_packaged_vintage_is_not_second_guessed() -> None:
    assert check_vintage_consistency(supplied=_vintage(2023), packaged_base_year=None) == []


def test_a_different_vintage_explains_which_tool_is_affected() -> None:
    problems = check_vintage_consistency(supplied=_vintage(2023), packaged_base_year=2022)
    assert len(problems) == 1
    message = problems[0]
    assert "2023" in message and "2022" in message
    # The point of the message is that one tool is safe and the other is not.
    assert "balance review can use your table" in message
    assert "dashboard cannot" in message
    assert "looks correct but" in message


# ---------------------------------------------------------------------------
# The real shipped tables
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not ESTO_2024.is_file(), reason="ESTO 2024 table not present")
def test_the_shipped_2024_table_reports_base_year_2022() -> None:
    assert infer_esto_vintage(ESTO_2024).base_year == 2022


@pytest.mark.skipif(not ESTO_2025.is_file(), reason="ESTO 2025 table not present")
def test_the_2025_table_reports_base_year_2023() -> None:
    # Proves the derivation actually tracks the issue rather than returning a
    # constant that happens to match the table in use today.
    assert infer_esto_vintage(ESTO_2025).base_year == 2023
