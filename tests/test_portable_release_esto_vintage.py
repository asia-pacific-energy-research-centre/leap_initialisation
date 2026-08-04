"""Tests for deriving the ESTO base year and reporting a vintage change."""

from pathlib import Path

import pytest

from codebase.portable_release.esto_vintage import (
    EstoVintage,
    EstoVintageError,
    describe_vintage_change,
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


def test_matching_vintages_say_nothing() -> None:
    assert describe_vintage_change(supplied=_vintage(2022), packaged_base_year=2022) == []


def test_an_unknown_packaged_vintage_is_not_second_guessed() -> None:
    assert describe_vintage_change(supplied=_vintage(2023), packaged_base_year=None) == []


def test_a_different_vintage_is_described_not_refused() -> None:
    """A newer table is a supported choice now, not a mismatch to block.

    While a release could only carry ESTO rows extracted in advance, a newer
    table left the dashboard on the older data and this refused the run. The
    worker now re-derives those rows, so the message explains the consequence -
    a slower first run - instead of stopping it.
    """
    notes = describe_vintage_change(supplied=_vintage(2023), packaged_base_year=2022)
    assert len(notes) == 1
    message = notes[0]
    assert "2023" in message and "2022" in message
    assert "re-derived" in message
    assert "both the balance review and the dashboard" in message
    # The old wording promised the opposite; make sure it cannot come back.
    assert "dashboard cannot" not in message


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


# ---------------------------------------------------------------------------
# Review year against the supplied vintage
# ---------------------------------------------------------------------------


def _year_check(year: int, table: Path, packaged: Path):
    from codebase.portable_release import validation

    report = validation.ValidationReport(command="probe")
    report.facts["year"] = year
    validation._check_esto_vintage(
        report, table, packaged_esto_table=packaged, is_user_supplied=True
    )
    return report


@pytest.mark.skipif(
    not (ESTO_2024.is_file() and ESTO_2025.is_file()), reason="ESTO tables not present"
)
def test_a_year_before_the_supplied_base_year_is_caught_with_the_answer() -> None:
    """Moving to a newer ESTO issue moves the year you can review.

    Left to the diagnostics step, this surfaces as "pre-base historical years
    are not yet supported", which does not say that the base year moved or what
    to ask for instead - exactly the position a user is in the first time they
    supply a newer table.
    """
    report = _year_check(2022, ESTO_2025, ESTO_2024)
    assert not report.ok
    detail = next(c.detail for c in report.checks if not c.ok)
    assert "starts its comparison at 2023" in detail
    assert "--year 2023" in detail


@pytest.mark.skipif(
    not (ESTO_2024.is_file() and ESTO_2025.is_file()), reason="ESTO tables not present"
)
def test_the_base_year_of_the_supplied_table_is_accepted() -> None:
    assert _year_check(2023, ESTO_2025, ESTO_2024).ok
    assert _year_check(2022, ESTO_2024, ESTO_2024).ok
