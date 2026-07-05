#%%
"""Resolve code display names exclusively from the canonical Outlook workbook.

The public API is retained for existing notebook and scrapbook callers. Genuine
overrides come from ``leap_display_names``; other names are derived by stripping
the leading numeric code and cleaning separators.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from codebase.mappings.canonical_loaders import (
    CANONICAL_WORKBOOK_PATH,
    load_canonical_sheet,
    load_leap_display_names,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
LEAP_MAPPINGS_PATH = CANONICAL_WORKBOOK_PATH

_LOOKUP_CACHE: pd.DataFrame | None = None
_FALSE_VALUES = {"false", "0", "0.0", "f", "no", "n"}


def _clean(value: object) -> str:
    text = str(value if value is not None else "").strip()
    return "" if text.lower() in {"", "nan", "none"} else text


def _derive_name(code: object) -> str:
    """Derive a readable fallback by removing a leading hierarchy code."""
    text = _clean(code)
    if not text:
        return ""
    text = re.sub(r"^\d+(?:[._]\d+)*(?:[._]x)?(?:[._\s-]+)", "", text, count=1)
    text = text.replace("_", " ").replace("/", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:1].upper() + text[1:] if text else _clean(code)


def _is_genuine_override(row: pd.Series) -> bool:
    value = row.get("matches_original_product_flow_name", "")
    return _clean(value).lower() in _FALSE_VALUES


def load_active_mapping_sheet(
    sheet_name: str,
    workbook_path: Path = CANONICAL_WORKBOOK_PATH,
) -> pd.DataFrame:
    """Load an active canonical sheet for backward-compatible callers."""
    required_by_sheet = {
        "leap_combined_esto": (
            "leap_sector_name_full_path", "raw_leap_fuel_name", "esto_flow", "esto_product"
        ),
        "leap_combined_ninth": (
            "leap_sector_name_full_path", "raw_leap_fuel_name", "ninth_sector", "ninth_fuel"
        ),
        "ninth_pairs_to_esto_pairs": ("9th_sector", "9th_fuel", "esto_flow", "esto_product"),
        "leap_display_names": ("code_type", "code", "leap_display_name"),
    }
    required = required_by_sheet.get(sheet_name)
    if required is None:
        raise ValueError(
            f"Unsupported canonical mapping sheet {sheet_name!r}; "
            f"expected one of {sorted(required_by_sheet)}."
        )
    return load_canonical_sheet(sheet_name, required, workbook=workbook_path, dtype=object)


def load_source_records() -> pd.DataFrame:
    """Return one canonical name record per code in ``leap_display_names``."""
    frame = load_leap_display_names()
    rows: list[dict[str, object]] = []
    for _, row in frame.iterrows():
        key_type = _clean(row.get("code_type"))
        code = _clean(row.get("code"))
        if not key_type or not code:
            continue
        fallback = _derive_name(code)
        override = _clean(row.get("leap_display_name")) if _is_genuine_override(row) else ""
        rows.append(
            {
                "key_type": key_type,
                "code": code,
                "name": override or fallback,
                "source_sheet": "leap_display_names_override" if override else "derived_from_code",
            }
        )
    return pd.DataFrame(rows, columns=["key_type", "code", "name", "source_sheet"]).drop_duplicates()


def build_unified_name_lookup() -> pd.DataFrame:
    """Return the legacy lookup shape backed only by canonical name records."""
    raw = load_source_records()
    columns = [
        "key_type", "code", "name", "confirming_sources", "confirming_source_count",
        "all_names_found", "name_count", "cardinality", "is_conflict",
    ]
    if raw.empty:
        return pd.DataFrame(columns=columns)
    output = raw.rename(columns={"source_sheet": "confirming_sources"}).copy()
    output["confirming_source_count"] = 1
    output["all_names_found"] = output["name"]
    output["name_count"] = 1
    output["cardinality"] = "one_to_one"
    output["is_conflict"] = False
    return output[columns].sort_values(["key_type", "code"], kind="stable").reset_index(drop=True)


def _get_lookup() -> pd.DataFrame:
    global _LOOKUP_CACHE
    if _LOOKUP_CACHE is None:
        _LOOKUP_CACHE = build_unified_name_lookup()
    return _LOOKUP_CACHE


def invalidate_cache() -> None:
    """Force canonical names to reload on the next lookup."""
    global _LOOKUP_CACHE
    _LOOKUP_CACHE = None


def resolve_name(
    key_type: str,
    code: str,
    *,
    prefer_source: str | None = None,
) -> str | None:
    """Resolve a canonical override or return the deterministic code fallback."""
    del prefer_source
    lookup = _get_lookup()
    subset = lookup[
        (lookup["key_type"].astype(str) == str(key_type))
        & (lookup["code"].astype(str) == str(code))
    ]
    if not subset.empty:
        return str(subset.iloc[0]["name"])
    fallback = _derive_name(code)
    return fallback or None


#%%
if __name__ == "__main__":
    output_dir = REPO_ROOT / "outputs" / "mappings" / "unified_name_lookup"
    output_dir.mkdir(parents=True, exist_ok=True)
    load_source_records().to_csv(output_dir / "unified_name_lookup_records.csv", index=False)
    build_unified_name_lookup().to_csv(output_dir / "unified_name_lookup.csv", index=False)
#%%
