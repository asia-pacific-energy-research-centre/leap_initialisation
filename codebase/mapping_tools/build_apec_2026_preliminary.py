"""Build the preliminary 2026 APEC ESTO aggregate from the new economy extracts.

``data/new 2026 esto data/`` holds one raw ESTO CSV per economy for the 2026
issue (e.g. ``01AUS_2026.csv``), released as economies become available. This
module combines whatever is there with the economies still missing (backfilled
from the 2025 vintage, carrying its latest year forward) into one table shaped
exactly like ``data/00APEC_2024_low_with_subtotals.csv`` /
``00APEC_2025_low_with_subtotals.csv`` — same columns, same
``economy,flows,products,is_subtotal,<year columns>`` schema — so it drops in
as another selectable ESTO vintage anywhere those tables are used (baseline
seed process, the ``leap_mappings``/``leap_dashboard`` pipelines, and the
portable-release/leap-review web app, which infers the vintage from the table
itself rather than a hardcoded year).

Because the raw extracts have no ``is_subtotal`` column and are missing a
handful of structurally-required rows (``16.01.99``, ``09.06.02.01/.02``),
every economy — new-for-2026 and backfilled alike — is run back through
``prepare_new_esto_data`` (see ``prepare_new_esto_data.py``), which is
idempotent: rows a source already carries are left untouched.

Output is tagged ``_PRELIMINARY`` because the 2026 issue is incomplete (11 of
21 APEC economies as of this run) and 10 economies' figures are still last
year's ESTO data carried forward, not real 2026 releases.

Rerun this script whenever ``data/new 2026 esto data/`` gains a new economy
file or an existing one is updated — it always rebuilds the output from
scratch, so there is no incremental state to keep in sync.

    python -m codebase.mapping_tools.build_apec_2026_preliminary
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from codebase.mapping_tools.prepare_new_esto_data import (
    _normalise_economy,
    prepare_new_esto_data,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"

NEW_DATA_DIR = DATA_DIR / "new 2026 esto data"
NEW_DATA_FILENAME_PATTERN = re.compile(r"^(?P<economy>\d{2}[A-Z]+)_(?P<vintage>\d{4})\.csv$", re.IGNORECASE)

# Most recent complete prior vintage: source of both the backfill rows for
# economies not yet released for 2026, and the primary is_subtotal reference.
BACKFILL_VINTAGE_PATH = DATA_DIR / "00APEC_2025_low_with_subtotals.csv"
# Secondary is_subtotal reference, consulted only for (flow, product) pairs
# absent from the 2025 vintage.
SECONDARY_REFERENCE_VINTAGE_PATH = DATA_DIR / "00APEC_2024_low_with_subtotals.csv"
NINTH_PROJECTION_TABLE_PATH = DATA_DIR / "merged_file_energy_ALL_20251106.csv"

OUTPUT_PATH = DATA_DIR / "00APEC_2026_low_with_subtotals_PRELIMINARY.csv"

REQUIRED_COLUMNS = ("economy", "flows", "products")


@dataclass
class BuildSummary:
    new_vintage_economies: list[str] = field(default_factory=list)
    backfilled_economies: list[str] = field(default_factory=list)
    backfilled_from_year: int | None = None
    backfilled_to_year: int | None = None
    input_rows: int = 0
    label_renames_applied: int = 0
    label_renames: list[dict] = field(default_factory=list)
    codes_absent_from_vocabulary: list[dict] = field(default_factory=list)
    commercial_services_unallocated_rows_added: int = 0
    lng_split_rows_added: int = 0
    output_rows: int = 0
    matched_by_reference: int = 0
    matched_by_fallback: int = 0
    defaulted_false: int = 0
    unresolved_rows: pd.DataFrame | None = None
    output_path: Path | None = None

    def describe(self) -> str:
        lines = [
            f"New-vintage economies ({len(self.new_vintage_economies)}): "
            + ", ".join(self.new_vintage_economies),
            f"Backfilled economies ({len(self.backfilled_economies)}, "
            f"{self.backfilled_from_year}->{self.backfilled_to_year} carried forward): "
            + ", ".join(self.backfilled_economies),
            f"Input rows (before structural completion): {self.input_rows:,}",
            f"Drifted labels repaired: {self.label_renames_applied:,}"
            + (
                " (" + "; ".join(
                    f"{item['before']} -> {item['after']}" for item in self.label_renames
                ) + ")"
                if self.label_renames
                else ""
            ),
            f"16.01.99 rows added: {self.commercial_services_unallocated_rows_added:,}",
            f"09.06.02.01/.02 rows added: {self.lng_split_rows_added:,}",
            f"Output rows: {self.output_rows:,}",
            "is_subtotal resolution: "
            f"{self.matched_by_reference:,} by reference vintage, "
            f"{self.matched_by_fallback:,} by hierarchy fallback, "
            f"{self.defaulted_false:,} defaulted to False",
        ]
        if self.unresolved_rows is not None and not self.unresolved_rows.empty:
            lines.append(
                f"[WARN] {len(self.unresolved_rows)} (flow, product) pairs had no is_subtotal "
                "signal from any source and defaulted to False - review before treating as final:"
            )
            for _, row in self.unresolved_rows.iterrows():
                lines.append(f"    {row['flows']} | {row['products']}")
        if self.codes_absent_from_vocabulary:
            # Drifted labels for *known* codes raise inside prepare_new_esto_data.
            # These are codes the maintained vocabulary has not caught up with,
            # which is normal as ESTO evolves - reported, not fatal.
            codes = sorted({
                f"{item['column']} {item['code']}"
                for item in self.codes_absent_from_vocabulary
            })
            lines.append(
                f"[INFO] {len(codes)} code(s) not in all_products_and_flows "
                f"(new since that list was written): {', '.join(codes)}"
            )
        if self.output_path is not None:
            lines.append(f"Output written to: {self.output_path}")
        return "\n".join(lines)


def _year_columns(df: pd.DataFrame) -> list[str]:
    return sorted((c for c in df.columns if str(c).isdigit()), key=int)


def _require_columns(df: pd.DataFrame, source: str) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{source} is missing required columns: {missing}")


def load_new_vintage_economies(new_data_dir: Path = NEW_DATA_DIR) -> pd.DataFrame:
    """Concatenate every per-economy CSV in ``new_data_dir`` into one table.

    Each file may or may not carry its own ``economy`` column; when absent
    (observed for some extracts, e.g. ``08JPN_2026.csv``) it is filled in from
    the filename. When present, it must agree with the filename - a
    mismatch usually means a file was renamed or copied by mistake.
    """
    files = sorted(new_data_dir.glob("*.csv"))
    if not files:
        raise FileNotFoundError(f"No economy CSVs found in {new_data_dir}")

    frames: list[pd.DataFrame] = []
    for path in files:
        match = NEW_DATA_FILENAME_PATTERN.match(path.name)
        if not match:
            raise ValueError(
                f"Unrecognised new-vintage filename {path.name!r}; expected "
                "'<economy code>_<year>.csv', e.g. '01AUS_2026.csv'."
            )
        economy_code = match.group("economy").upper()

        frame = pd.read_csv(path, dtype=object, low_memory=False)
        if "economy" in frame.columns:
            found = set(frame["economy"].map(_normalise_economy).dropna().unique())
            if found != {economy_code}:
                raise ValueError(
                    f"{path.name} economy column {sorted(found)} does not match "
                    f"the economy code {economy_code!r} implied by its filename."
                )
        else:
            frame.insert(0, "economy", economy_code)
        _require_columns(frame, path.name)
        frames.append(frame)

    combined = pd.concat(frames, ignore_index=True, sort=False)
    return combined


def backfill_missing_economies(
    new_vintage_df: pd.DataFrame,
    backfill_source_df: pd.DataFrame,
    target_year: int,
) -> tuple[pd.DataFrame, list[str], int | None]:
    """Return rows for economies present in ``backfill_source_df`` but not in
    ``new_vintage_df``, with ``target_year`` filled from the source's own
    latest available year (simple carry-forward — the source table has no
    newer data to offer).

    Returns ``(backfill_rows, backfilled_economy_codes, source_latest_year)``.
    """
    _require_columns(new_vintage_df, "new-vintage table")
    _require_columns(backfill_source_df, "backfill source table")

    present = set(new_vintage_df["economy"].map(_normalise_economy).dropna().unique())
    source_economies = backfill_source_df["economy"].map(_normalise_economy)
    missing = sorted(set(source_economies.unique()) - present)
    if not missing:
        return backfill_source_df.iloc[0:0].copy(), [], None

    source_year_cols = _year_columns(backfill_source_df)
    if not source_year_cols:
        raise ValueError("Backfill source table declares no year columns.")
    latest_source_year = int(source_year_cols[-1])

    rows = backfill_source_df[source_economies.isin(missing)].copy()
    target_col = str(target_year)
    if target_col not in rows.columns:
        rows[target_col] = pd.to_numeric(
            rows[str(latest_source_year)], errors="coerce"
        ).fillna(0.0)

    return rows, missing, latest_source_year


def build_apec_2026_preliminary(
    new_data_dir: Path = NEW_DATA_DIR,
    backfill_vintage_path: Path = BACKFILL_VINTAGE_PATH,
    secondary_reference_vintage_path: Path = SECONDARY_REFERENCE_VINTAGE_PATH,
    ninth_projection_table_path: Path | None = NINTH_PROJECTION_TABLE_PATH,
    output_path: Path = OUTPUT_PATH,
    target_year: int = 2026,
) -> BuildSummary:
    """Build and write the preliminary 2026 APEC ESTO aggregate.

    ``target_year`` is the vintage issue year (2026), not a data-column year;
    the base data year embedded as the last year column is derived from
    whatever years the new extracts actually carry (currently 2024).
    """
    summary = BuildSummary()

    new_vintage_df = load_new_vintage_economies(new_data_dir)
    summary.new_vintage_economies = sorted(
        new_vintage_df["economy"].map(_normalise_economy).dropna().unique()
    )
    summary.input_rows = len(new_vintage_df)
    new_year_cols = _year_columns(new_vintage_df)
    if not new_year_cols:
        raise ValueError("New-vintage economy files declare no year columns.")
    base_data_year = int(new_year_cols[-1])

    backfill_source_df = pd.read_csv(backfill_vintage_path, dtype=object, low_memory=False)
    backfill_rows, backfilled_economies, backfill_source_year = backfill_missing_economies(
        new_vintage_df, backfill_source_df, target_year=base_data_year
    )
    summary.backfilled_economies = backfilled_economies
    summary.backfilled_from_year = backfill_source_year
    summary.backfilled_to_year = base_data_year if backfilled_economies else None
    summary.input_rows += len(backfill_rows)

    combined = pd.concat([new_vintage_df, backfill_rows], ignore_index=True, sort=False)

    reference_dfs = [backfill_source_df]
    if secondary_reference_vintage_path.is_file():
        reference_dfs.append(
            pd.read_csv(secondary_reference_vintage_path, dtype=object, low_memory=False)
        )

    ninth_df = None
    if ninth_projection_table_path is not None and Path(ninth_projection_table_path).is_file():
        ninth_usecols = ["economy", "scenarios", "sub2sectors", "subfuels", *[str(y) for y in range(1990, base_data_year + 1)]]
        ninth_header = pd.read_csv(ninth_projection_table_path, nrows=0).columns
        ninth_usecols = [c for c in ninth_usecols if c in ninth_header]
        ninth_df = pd.read_csv(
            ninth_projection_table_path, dtype=object, low_memory=False, usecols=ninth_usecols
        )

    prepared, prep_summary = prepare_new_esto_data(combined, reference_dfs, ninth_df=ninth_df)
    prepared["is_subtotal"] = prepared["is_subtotal"].map(lambda v: "TRUE" if bool(v) else "FALSE")

    duplicate_mask = prepared.duplicated(["economy", "flows", "products"], keep=False)
    if duplicate_mask.any():
        dupes = prepared.loc[duplicate_mask, ["economy", "flows", "products"]].drop_duplicates()
        raise ValueError(
            f"Prepared 2026 table has {len(dupes)} duplicate (economy, flows, products) "
            f"combinations, e.g.: {dupes.head(5).to_dict('records')}"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    prepared.to_csv(output_path, index=False)

    summary.label_renames_applied = prep_summary["label_renames_applied"]
    summary.label_renames = prep_summary["label_renames"]
    summary.codes_absent_from_vocabulary = prep_summary["codes_absent_from_vocabulary"]
    summary.commercial_services_unallocated_rows_added = prep_summary[
        "commercial_services_unallocated_rows_added"
    ]
    summary.lng_split_rows_added = prep_summary["lng_split_rows_added"]
    summary.output_rows = prep_summary["output_rows"]
    summary.matched_by_reference = prep_summary["matched_by_reference"]
    summary.matched_by_fallback = prep_summary["matched_by_fallback"]
    summary.defaulted_false = prep_summary["defaulted_false"]
    summary.unresolved_rows = prep_summary["unresolved_rows"]
    summary.output_path = output_path
    return summary


def main() -> None:
    summary = build_apec_2026_preliminary()
    print(summary.describe())


if __name__ == "__main__":
    main()
