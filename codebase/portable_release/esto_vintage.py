"""Work out which ESTO vintage a run is using, and refuse to mix vintages.

ESTO data is reissued yearly and each issue moves the base year: the 2024 issue
carries years 1990-2022, the 2025 issue 1990-2023. The base year was previously
hardcoded as ``2022`` in three unrelated places, so moving to a new issue meant
editing code in two repositories and rebuilding.

The base year is not a separate fact to be configured — it is a property of the
table, namely its last year column. Reading it from the file removes the
opportunity for the three values to disagree.

The second job here is the more important one. A release carries both the raw
ESTO table (used by the balance-review path) and four artifacts *derived* from a
particular ESTO issue (used by the dashboard path). Replacing the raw table
alone leaves the derived artifacts on the old issue, and nothing about the
result would look wrong — the dashboard would render happily against stale
values. :func:`check_vintage_consistency` makes that mismatch loud instead.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


#: Years outside this range in a header are not real data columns.
MIN_PLAUSIBLE_YEAR = 1960
MAX_PLAUSIBLE_YEAR = 2100


class EstoVintageError(ValueError):
    """Raised when an ESTO table's vintage cannot be established."""


@dataclass(frozen=True)
class EstoVintage:
    """What one ESTO source table says about itself."""

    path: Path
    first_year: int
    base_year: int

    @property
    def label(self) -> str:
        return f"{self.first_year}-{self.base_year}"

    def describe(self) -> str:
        return (
            f"{self.path.name}: years {self.label}, so the base year is "
            f"{self.base_year}."
        )


def read_year_columns(path: Path | str) -> list[int]:
    """Return the year columns an ESTO table declares, in ascending order."""
    table = Path(path)
    try:
        with table.open("r", encoding="utf-8-sig", newline="") as handle:
            header = next(csv.reader(handle), [])
    except OSError as exc:  # noqa: BLE001 - reported in plain language
        raise EstoVintageError(f"Could not read {table}: {exc}") from None

    years: list[int] = []
    for column in header:
        text = str(column).strip()
        if not text.isdigit():
            continue
        value = int(text)
        if MIN_PLAUSIBLE_YEAR <= value <= MAX_PLAUSIBLE_YEAR:
            years.append(value)
    return sorted(set(years))


def infer_esto_vintage(path: Path | str) -> EstoVintage:
    """Derive the base year from an ESTO table's last year column.

    An ESTO issue reports history up to its base year and no further, so the
    highest year column *is* the base year. This is deliberately derived rather
    than configured: a configured value can disagree with the file it describes,
    and that disagreement is silent.
    """
    table = Path(path)
    years = read_year_columns(table)
    if not years:
        raise EstoVintageError(
            f"{table.name} declares no year columns, so its base year cannot be "
            "determined. An ESTO base table should have a column per year "
            "(1990, 1991, ... ) alongside economy, flows and products."
        )
    if len(years) < 2:
        raise EstoVintageError(
            f"{table.name} declares only one year column ({years[0]}). That is "
            "too little history to be an ESTO base table."
        )
    return EstoVintage(path=table, first_year=years[0], base_year=years[-1])


def check_vintage_consistency(
    *,
    supplied: EstoVintage,
    packaged_base_year: int | None,
) -> list[str]:
    """Return a problem for each way a supplied table conflicts with the release.

    ``packaged_base_year`` is the base year of the ESTO table this release was
    built against, recorded at build time. The four derived mapping artifacts
    were produced from that same issue, and nothing in a release can regenerate
    them — so a supplied table from a different issue can be used for the
    balance review but would silently mismatch the dashboard.
    """
    if packaged_base_year is None:
        return []
    if supplied.base_year == packaged_base_year:
        return []
    return [
        f"The ESTO table you supplied has base year {supplied.base_year}, but "
        f"this release was built against the {packaged_base_year} issue.\n"
        "    The balance review can use your table. The dashboard cannot: its "
        "comparison data is prepared in advance from a single ESTO issue, and "
        "this release carries the "
        f"{packaged_base_year} one.\n"
        "    Mixing them would produce a dashboard that looks correct but "
        "compares against the older data. Ask for a release built on the "
        f"{supplied.base_year} issue instead."
    ]
