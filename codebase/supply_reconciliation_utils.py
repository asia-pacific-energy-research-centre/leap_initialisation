from __future__ import annotations

import re
from typing import Iterable

import pandas as pd

from codebase import transformation_workflow
from codebase.functions.supply_export_rows import coerce_value_by_year
from codebase.mappings.canonical_loaders import (
    load_leap_display_names,
    load_ninth_pairs_to_esto_pairs,
)


def _canonical_transformation_fuel_label(label: str) -> str:
    """Return a stable display fuel label used by transformation LEAP branch paths."""
    token = str(label or "").strip()
    if not token:
        return ""
    try:
        mapped = transformation_workflow.core.map_code_label(
            token,
            transformation_workflow.core.code_to_name_mapping,
        )
    except Exception:
        mapped = token
    normalized = str(mapped or "").strip()
    if not normalized:
        return token
    try:
        # Match LEAP branch-name sanitization so aliases like "Gas/diesel oil" and
        # "Gas and diesel oil" collapse to one canonical key before export rows.
        sanitized = transformation_workflow.core.build_branch_path([normalized])
        sanitized_token = str(sanitized or "").strip()
        if sanitized_token:
            return sanitized_token
    except Exception:
        pass
    return normalized


def _load_code_to_name_table() -> pd.DataFrame:
    """Build the legacy lookup shape from canonical names and pair mappings."""
    names = load_leap_display_names().fillna("")
    product_names = names[names["code_type"].astype(str).eq("esto_product")].copy()
    product_names = product_names.rename(
        columns={"code": "esto_label", "leap_display_name": "name"}
    )
    pairs, _conflicts = load_ninth_pairs_to_esto_pairs(detect_conflicts=False)
    bridge = pairs[["ninth_fuel", "esto_product"]].drop_duplicates().rename(
        columns={"ninth_fuel": "ninth_label", "esto_product": "esto_label"}
    )
    table = product_names[["esto_label", "name"]].merge(
        bridge,
        on="esto_label",
        how="left",
    )
    table["code"] = table["esto_label"]
    return table.fillna("")


def _normalize_label_for_lookup(value: object) -> str:
    """Normalize fuel/sector labels for tolerant crosswalk matching."""
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = text.replace("&", " and ")
    text = text.replace("/", " and ")
    text = text.replace("-", " ")
    text = text.replace("(", " ")
    text = text.replace(")", " ")
    text = text.replace(":", " ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _normalize_esto_product_for_match(value: object) -> str:
    """Normalize esto_product strings, stripping leading numeric code prefixes."""
    text = str(value or "").strip()
    if not text:
        return ""
    # Convert "07.07 Gas/diesel oil" -> "Gas/diesel oil" before fuzzy normalization.
    text = re.sub(r"^\d+(?:\.\d+)*\s+", "", text)
    return _normalize_label_for_lookup(text)


def _build_label_to_esto_product_lookup() -> dict[str, str]:
    """Map human-readable labels and known codes back to ESTO products."""
    table = _load_code_to_name_table()
    lookup: dict[str, str] = {}
    for _, row in table.iterrows():
        esto_product = str(row.get("esto_label") or "").strip()
        if not esto_product:
            continue
        keys = [
            row.get("name"),
            row.get("esto_label"),
            row.get("ninth_label"),
            row.get("code"),
        ]
        for key in keys:
            normalized = str(key or "").strip()
            if normalized:
                lookup.setdefault(normalized, esto_product)
                lookup.setdefault(normalized.lower(), esto_product)
                fuzzy_key = _normalize_label_for_lookup(normalized)
                if fuzzy_key:
                    lookup.setdefault(fuzzy_key, esto_product)
    return lookup


def _iter_year_value_items(
    labeled_values: dict | None,
    base_year: int,
    final_year: int,
):
    """Yield (label, year, value) triples from a transformation record payload."""
    if not isinstance(labeled_values, dict):
        return
    for label, raw_value in labeled_values.items():
        year_map = coerce_value_by_year(raw_value, base_year, final_year)
        for year, value in year_map.items():
            year_int = int(year)
            if year_int < base_year or year_int > final_year:
                continue
            yield str(label), year_int, float(value)


def _sort_output_frame_for_csv(
    frame: pd.DataFrame,
    *,
    exclude_sort_columns: Iterable[str] = (),
    defer_sort_columns: Iterable[str] = ("year", "source", "source_sheet"),
) -> pd.DataFrame:
    """Return a stably sorted copy for human-facing CSV outputs."""
    if frame is None:
        return pd.DataFrame()
    if frame.empty:
        return frame.copy()

    exclude = {
        str(column).strip()
        for column in exclude_sort_columns
        if str(column).strip() and str(column).strip() in frame.columns
    }
    deferred = [
        str(column).strip()
        for column in defer_sort_columns
        if str(column).strip()
        and str(column).strip() in frame.columns
        and str(column).strip() not in exclude
    ]
    primary = [
        column
        for column in frame.columns
        if column not in exclude and column not in deferred
    ]
    sort_columns = primary + deferred
    if not sort_columns:
        return frame.copy().reset_index(drop=True)

    out = frame.copy()
    try:
        return out.sort_values(by=sort_columns, kind="mergesort", na_position="last").reset_index(
            drop=True
        )
    except Exception:
        normalized = pd.DataFrame(index=out.index)
        for column in sort_columns:
            normalized[column] = out[column].map(
                lambda value: "" if pd.isna(value) else str(value)
            )
        sorted_index = normalized.sort_values(
            by=sort_columns,
            kind="mergesort",
            na_position="last",
        ).index
        return out.loc[sorted_index].reset_index(drop=True)


def _normalize_template_header_value(value: object) -> str:
    """Normalize LEAP import header cells into stable string column names."""
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()
