"""Work out which ESTO vintage a run is using, and say when it changes.

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


def describe_vintage_change(
    *,
    supplied: EstoVintage,
    packaged_base_year: int | None,
) -> list[str]:
    """Describe what changes when a supplied table differs from the packaged one.

    This used to refuse the run. That was right while a release could only carry
    ESTO rows extracted in advance from one issue: a newer table then updated
    the balance review and left the dashboard silently comparing against the
    older data.

    The mapping-chain worker now re-derives those rows from whichever table a
    run is given, so both tools follow the supplied issue and the mismatch it
    guarded against cannot arise. What remains is worth *saying* rather than
    blocking: re-derivation adds a couple of minutes to the first run against a
    given table, and the 9th-edition projections keep their own release cycle,
    so they are unchanged by an ESTO update.
    """
    if packaged_base_year is None or supplied.base_year == packaged_base_year:
        return []
    return [
        f"Using your ESTO table (base year {supplied.base_year}) instead of the "
        f"one shipped with this release (base year {packaged_base_year}).\n"
        "    The comparison rows are re-derived from your table, so both the "
        "balance review and the dashboard follow it. The first run against a "
        "given table takes a couple of minutes longer while that happens.\n"
        "    The 9th-edition projections are on their own release cycle and are "
        "not affected by an ESTO update."
    ]
