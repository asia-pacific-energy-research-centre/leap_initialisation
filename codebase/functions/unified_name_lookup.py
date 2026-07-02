"""
unified_name_lookup.py

Build a consolidated code → display-name mapping table from all available
mapping sources in leap_mappings.xlsx and master_config.xlsx.

Key types produced:
    ninth_fuel     – 9th-edition fuel/subfuel codes  (e.g. 01_01_coking_coal)
    ninth_sector   – 9th-edition sector codes        (e.g. 14_03_01_iron_and_steel)
    esto_product   – ESTO product labels             (e.g. "01.01 Coking coal")
    esto_flow      – ESTO flow labels                (e.g. "09.07 Oil refineries")

Sources consulted
-----------------
leap_mappings.xlsx
    fuel_ninth_final_proposed   : ninth_fuel   → leap_fuel_name
    sector_ninth_final_proposed : ninth_sector → leap_sector_name
    fuel_product_final_proposed : esto_product → leap_fuel_name
    sector_flow_final_proposed  : esto_flow    → leap_sector_name
    leap_combined_ninth         : active-row   ninth_fuel    → raw_leap_fuel_name
    leap_combined_esto          : active-row   esto_product  → raw_leap_fuel_name

master_config.xlsx
    sector_fuel_code_to_name    : 9th_label / esto_label → name
                                  (9th_column / esto_column determines key_type)
    sector_fuel_ESTO_LEAP_names : original_label (by category) → leap_name

Public API
----------
    load_source_records()       → long-form DataFrame (key_type, code, name, source_sheet)
    build_unified_name_lookup() → summary DataFrame   (key_type, code, name,
                                                        confirming_sources,
                                                        confirming_source_count,
                                                        all_names_found,
                                                        name_count,
                                                        cardinality,
                                                        is_conflict)
    resolve_name(key_type, code) → str | None
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

LEAP_MAPPINGS_PATH = REPO_ROOT / "config" / "leap_mappings.xlsx"
MASTER_CONFIG_PATH = REPO_ROOT / "config" / "master_config.xlsx"

from codebase.utilities.master_config import OUTLOOK_MAPPINGS_MASTER_PATH  # noqa: E402

_NINTH_FUEL_COLUMNS = frozenset({"subfuels", "fuels"})
_NINTH_SECTOR_COLUMNS = frozenset({"sectors", "sub1sectors", "sub2sectors", "sub3sectors", "sub4sectors"})


# ---------------------------------------------------------------------------
# Helpers (aligned with outlook_mapping_maintenance_workflow conventions)
# ---------------------------------------------------------------------------

def _clean(value: object) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in {"", "nan", "none"} else text


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def _active_rows(frame: pd.DataFrame) -> pd.DataFrame:
    """Filter out rows where remove_row or duplicate_to_remove is truthy."""
    remove = frame.get("remove_row", pd.Series(False, index=frame.index)).map(_truthy)
    duplicate = frame.get("duplicate_to_remove", pd.Series(False, index=frame.index)).map(_truthy)
    return frame[~(remove | duplicate)].copy()


def _read_sheet(workbook_path: Path, sheet_name: str) -> pd.DataFrame:
    return pd.read_excel(workbook_path, sheet_name=sheet_name, dtype=object).fillna("")


def load_active_mapping_sheet(
    sheet_name: str,
    workbook_path: Path = LEAP_MAPPINGS_PATH,
) -> pd.DataFrame:
    """Return a leap_mappings.xlsx sheet with inactive mapping rows removed."""
    return _active_rows(_read_sheet(workbook_path, sheet_name))


def _make_records(
    rows: Iterable[tuple[str, str, str]],
    source_sheet: str,
) -> list[dict]:
    """Convert (key_type, code, name) triples into record dicts, dropping blanks."""
    out = []
    for key_type, code, name in rows:
        code = _clean(code)
        name = _clean(name)
        if code and name:
            out.append({"key_type": key_type, "code": code, "name": name, "source_sheet": source_sheet})
    return out


# ---------------------------------------------------------------------------
# Per-source loaders
# ---------------------------------------------------------------------------

def _load_fuel_ninth_final_proposed() -> list[dict]:
    df = _read_sheet(LEAP_MAPPINGS_PATH, "fuel_ninth_final_proposed")
    return _make_records(
        (("ninth_fuel", row["ninth_fuel"], row["leap_fuel_name"]) for _, row in df.iterrows()),
        "fuel_ninth_final_proposed",
    )


def _load_sector_ninth_final_proposed() -> list[dict]:
    df = _read_sheet(LEAP_MAPPINGS_PATH, "sector_ninth_final_proposed")
    return _make_records(
        (("ninth_sector", row["ninth_sector"], row["leap_sector_name"]) for _, row in df.iterrows()),
        "sector_ninth_final_proposed",
    )


def _load_fuel_product_final_proposed() -> list[dict]:
    df = _read_sheet(LEAP_MAPPINGS_PATH, "fuel_product_final_proposed")
    return _make_records(
        (("esto_product", row["esto_product"], row["leap_fuel_name"]) for _, row in df.iterrows()),
        "fuel_product_final_proposed",
    )


def _load_sector_flow_final_proposed() -> list[dict]:
    df = _read_sheet(LEAP_MAPPINGS_PATH, "sector_flow_final_proposed")
    return _make_records(
        (("esto_flow", row["esto_flow"], row["leap_sector_name"]) for _, row in df.iterrows()),
        "sector_flow_final_proposed",
    )


def _load_leap_combined_ninth_fuels() -> list[dict]:
    """Extract fuel-level mappings from active rows: ninth_fuel → raw_leap_fuel_name."""
    df = _read_sheet(OUTLOOK_MAPPINGS_MASTER_PATH, "leap_combined_ninth")
    active = _active_rows(df)
    pairs = (
        active[["ninth_fuel", "raw_leap_fuel_name"]]
        .drop_duplicates()
    )
    return _make_records(
        (("ninth_fuel", row["ninth_fuel"], row["raw_leap_fuel_name"]) for _, row in pairs.iterrows()),
        "leap_combined_ninth",
    )


def _load_leap_combined_esto_products() -> list[dict]:
    """Extract fuel-level mappings from active rows: esto_product → raw_leap_fuel_name."""
    df = _read_sheet(OUTLOOK_MAPPINGS_MASTER_PATH, "leap_combined_esto")
    active = _active_rows(df)
    pairs = (
        active[["esto_product", "raw_leap_fuel_name"]]
        .drop_duplicates()
    )
    return _make_records(
        (("esto_product", row["esto_product"], row["raw_leap_fuel_name"]) for _, row in pairs.iterrows()),
        "leap_combined_esto",
    )


def _load_sector_fuel_code_to_name() -> list[dict]:
    """
    Map 9th_label and esto_label to name.

    9th_column tells us the key type:
        subfuels / fuels            → ninth_fuel
        sectors / sub*sectors       → ninth_sector
    esto_column tells us:
        products                    → esto_product
        flows                       → esto_flow
    A row may carry both a 9th_label and an esto_label; emit records for each.
    """
    df = _read_sheet(MASTER_CONFIG_PATH, "sector_fuel_code_to_name")
    records: list[dict] = []
    for _, row in df.iterrows():
        name = _clean(row.get("name", ""))
        if not name:
            continue

        ninth_label = _clean(row.get("9th_label", ""))
        ninth_col = _clean(row.get("9th_column", "")).lower()
        if ninth_label:
            if ninth_col in _NINTH_FUEL_COLUMNS:
                key_type = "ninth_fuel"
            elif ninth_col in _NINTH_SECTOR_COLUMNS:
                key_type = "ninth_sector"
            else:
                key_type = "ninth_sector" if ninth_col else "ninth_fuel"
            records.extend(_make_records([(key_type, ninth_label, name)], "sector_fuel_code_to_name"))

        esto_label = _clean(row.get("esto_label", ""))
        esto_col = _clean(row.get("esto_column", "")).lower()
        if esto_label:
            key_type = "esto_flow" if esto_col == "flows" else "esto_product"
            records.extend(_make_records([(key_type, esto_label, name)], "sector_fuel_code_to_name"))

    return records


def _load_sector_fuel_esto_leap_names() -> list[dict]:
    """
    Map ESTO original_label → leap_name by category.
        category=flows    → esto_flow
        category=products → esto_product
    """
    df = _read_sheet(MASTER_CONFIG_PATH, "sector_fuel_ESTO_LEAP_names")
    records: list[dict] = []
    for _, row in df.iterrows():
        category = _clean(row.get("category", "")).lower()
        label = _clean(row.get("original_label", ""))
        name = _clean(row.get("leap_name", ""))
        if not label or not name:
            continue
        key_type = "esto_flow" if category == "flows" else "esto_product"
        records.extend(_make_records([(key_type, label, name)], "sector_fuel_ESTO_LEAP_names"))
    return records


# ---------------------------------------------------------------------------
# Public: raw long-form records
# ---------------------------------------------------------------------------

_LOADERS = [
    _load_fuel_ninth_final_proposed,
    _load_sector_ninth_final_proposed,
    _load_fuel_product_final_proposed,
    _load_sector_flow_final_proposed,
    _load_leap_combined_ninth_fuels,
    _load_leap_combined_esto_products,
    _load_sector_fuel_code_to_name,
    _load_sector_fuel_esto_leap_names,
]


def load_source_records() -> pd.DataFrame:
    """
    Return all raw (key_type, code, name, source_sheet) records from every
    mapping source.  One row per occurrence — duplicates across sources are
    retained so you can see which sources agree.
    """
    all_records: list[dict] = []
    for loader in _LOADERS:
        all_records.extend(loader())

    df = pd.DataFrame(all_records, columns=["key_type", "code", "name", "source_sheet"])
    return df.drop_duplicates().reset_index(drop=True)


# ---------------------------------------------------------------------------
# Public: consolidated summary
# ---------------------------------------------------------------------------

def _compute_cardinality(n_names: int, n_codes: int) -> str:
    if n_names <= 0 or n_codes <= 0:
        return ""
    if n_names == 1 and n_codes == 1:
        return "one_to_one"
    if n_names > 1 and n_codes == 1:
        return "one_to_many"
    if n_names == 1 and n_codes > 1:
        return "many_to_one"
    return "many_to_many"


def build_unified_name_lookup() -> pd.DataFrame:
    """
    Build a consolidated name-lookup table.

    Each row represents one (key_type, code, name) combination found across
    all mapping sources, with:

    confirming_sources      : pipe-separated list of source sheets that yield
                              this exact (code, name) pair
    confirming_source_count : number of distinct sources confirming this name
    all_names_found         : pipe-separated list of every name seen for this
                              code across all sources
    name_count              : number of distinct names for this code
                              (1 = unambiguous; >1 = conflict)
    cardinality             : one_to_one | one_to_many | many_to_one | many_to_many
                              (computed across all sources jointly)
    is_conflict             : True when name_count > 1
    """
    raw = load_source_records()
    if raw.empty:
        return pd.DataFrame(columns=[
            "key_type", "code", "name",
            "confirming_sources", "confirming_source_count",
            "all_names_found", "name_count",
            "cardinality", "is_conflict",
        ])

    # Aggregate: one row per (key_type, code, name) — collect confirming sources
    agg = (
        raw.groupby(["key_type", "code", "name"], as_index=False)
        .agg(confirming_sources=("source_sheet", lambda s: " | ".join(sorted(s.unique()))))
    )
    agg["confirming_source_count"] = agg["confirming_sources"].str.count(r"\|").add(1)

    # Count unique names per (key_type, code) and collect them all
    per_code = (
        raw.groupby(["key_type", "code"], as_index=False)
        .agg(
            all_names_found=("name", lambda s: " | ".join(sorted(s.unique()))),
            name_count=("name", "nunique"),
        )
    )
    agg = agg.merge(per_code, on=["key_type", "code"], how="left")

    # Count unique codes per (key_type, name) for many-to-one detection
    per_name = (
        raw.groupby(["key_type", "name"], as_index=False)
        .agg(code_count=("code", "nunique"))
    )
    agg = agg.merge(per_name, on=["key_type", "name"], how="left")

    agg["cardinality"] = agg.apply(
        lambda row: _compute_cardinality(int(row["name_count"]), int(row["code_count"])),
        axis=1,
    )
    agg["is_conflict"] = agg["name_count"].gt(1)

    return agg.drop(columns=["code_count"]).sort_values(
        ["key_type", "code", "name"],
        key=lambda col: col.str.lower(),
    ).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Public: convenience resolver
# ---------------------------------------------------------------------------

_LOOKUP_CACHE: pd.DataFrame | None = None


def _get_lookup() -> pd.DataFrame:
    global _LOOKUP_CACHE
    if _LOOKUP_CACHE is None:
        _LOOKUP_CACHE = build_unified_name_lookup()
    return _LOOKUP_CACHE


def invalidate_cache() -> None:
    """Force reload of lookup on next call to resolve_name()."""
    global _LOOKUP_CACHE
    _LOOKUP_CACHE = None


def resolve_name(
    key_type: str,
    code: str,
    *,
    prefer_source: str | None = None,
) -> str | None:
    """
    Resolve a single code to a display name.

    Returns the unambiguous name if name_count == 1.  When multiple names
    exist (conflict), returns the name from *prefer_source* if supplied and
    found, otherwise returns the name with the most confirming sources
    (ties broken alphabetically).  Returns None if the code is not found.
    """
    lookup = _get_lookup()
    subset = lookup[(lookup["key_type"] == key_type) & (lookup["code"] == code)]
    if subset.empty:
        return None
    if len(subset) == 1:
        return str(subset.iloc[0]["name"])
    if prefer_source:
        match = subset[subset["confirming_sources"].str.contains(prefer_source, regex=False)]
        if not match.empty:
            best = match.sort_values("confirming_source_count", ascending=False).iloc[0]
            return str(best["name"])
    best = subset.sort_values(["confirming_source_count", "name"], ascending=[False, True]).iloc[0]
    return str(best["name"])


# ---------------------------------------------------------------------------
# Script entry-point: write outputs to CSV for inspection
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os

    out_dir = REPO_ROOT / "outputs" / "mappings" / "unified_name_lookup"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Loading source records …")
    records = load_source_records()
    records_path = out_dir / "unified_name_lookup_records.csv"
    records.to_csv(records_path, index=False)
    print(f"  {len(records)} raw records -> {records_path.relative_to(REPO_ROOT)}")

    print("Building unified lookup ...")
    lookup = build_unified_name_lookup()
    lookup_path = out_dir / "unified_name_lookup.csv"
    lookup.to_csv(lookup_path, index=False)
    print(f"  {len(lookup)} (key_type, code, name) rows -> {lookup_path.relative_to(REPO_ROOT)}")

    # Summary
    print("\nBreakdown:")
    for key_type, grp in lookup.groupby("key_type"):
        codes = grp["code"].nunique()
        conflicts = grp[grp["is_conflict"]]["code"].nunique()
        print(f"  {key_type}: {codes} codes, {conflicts} with name conflicts")

    print("\nName conflicts (same code -> multiple names):")
    conflicts = lookup[lookup["is_conflict"]].sort_values(["key_type", "code"])
    if conflicts.empty:
        print("  none")
    else:
        for _, row in conflicts.iterrows():
            print(
                f"  [{row['key_type']}] {row['code']!r:50s} "
                f"name={row['name']!r:35s} "
                f"from: {row['confirming_sources']}"
            )
