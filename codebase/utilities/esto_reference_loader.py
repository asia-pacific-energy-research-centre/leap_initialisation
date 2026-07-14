"""Shared loader for ESTO and 9th Outlook reference tables.

Moved here from codebase/scrapbook/utilities.py so that production
workflows can import a stable, non-scrapbook path.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from codebase.mappings.canonical_mapping import load_canonical_pairs
from codebase.utilities.master_config import config_table_exists, read_config_table
from codebase.utilities.leap_results_dashboard_utils import (
    apply_explicit_sector_reassignments,
    load_explicit_sector_fuel_mappings,
    load_explicit_sector_reassignments,
)
from codebase.utilities.leap_results_dashboard_v2.reference_loader import (
    append_synthetic_reference_rows,
    load_synthetic_reference_rows_config,
)


def apply_esto_subtotal_mapping(df: pd.DataFrame, mapping_path=None) -> pd.DataFrame:
    """Normalize the existing ESTO ``is_subtotal`` column.

    The active ESTO CSVs already carry ``is_subtotal``. This helper keeps the
    historical name but no longer reads a separate subtotal workbook.
    """
    if "is_subtotal" in df.columns:
        out = df.copy()
        out["is_subtotal"] = (
            out["is_subtotal"]
            .fillna(False)
            .astype(str)
            .str.strip()
            .str.lower()
            .isin(["true", "1", "yes"])
        )
        return out

    raise ValueError(
        "ESTO subtotal labeling now requires an input column named 'is_subtotal'. "
        "The legacy subtotal workbook is no longer consulted."
    )

    year_cols = [col for col in out.columns if str(col).isdigit()]
    leading_cols = [col for col in ["economy", "flows", "products"] if col in out.columns]
    other_cols = [
        col for col in out.columns
        if col not in leading_cols and col != "is_subtotal" and col not in year_cols
    ]
    return out[leading_cols + ["is_subtotal"] + other_cols + year_cols]


def filter_esto_subtotals(df: pd.DataFrame) -> pd.DataFrame:
    """Drop rows where ``is_subtotal`` is True."""
    if "is_subtotal" not in df.columns:
        return df
    return df[df["is_subtotal"] == False].copy()


def save_subtotal_labeled_data(df: pd.DataFrame, output_path, label: str) -> None:
    """Save a subtotal-labeled dataset to CSV for inspection."""
    if df is None or df.empty:
        print(f"No data to save for {label}; skipping {output_path}.")
        return
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    print(f"Saved {label} with subtotal labels to {path}")


def _file_signature(path) -> dict:
    path = Path(path)
    if not path.exists():
        return {"path": str(path), "exists": False}
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "exists": True,
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }


def _build_reference_cache_key(payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def load_augmented_reference_tables(
    *,
    esto_path,
    ninth_path,
    explicit_reassignments_path=None,
    explicit_mappings_path=None,
    canonical_pairs_path=None,
    synthetic_rules_path="config/synthetic_reference_rows.csv",
    cache_dir="data/.cache/augmented_reference_tables",
    apply_esto_subtotal_map: bool = False,
    filter_esto_subtotals_flag: bool = False,
    filter_ninth_subtotals_flag: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load ESTO + 9th tables with optional subtotal cleanup, explicit reassignments,
    and synthetic-row augmentation, then cache the result on disk.

    The cache is keyed by a hash of the source-file signatures and option flags,
    so it is invalidated automatically when any input changes.
    """
    esto_path = Path(esto_path)
    ninth_path = Path(ninth_path)
    explicit_reassignments_path = (
        Path(explicit_reassignments_path) if explicit_reassignments_path else None
    )
    explicit_mappings_path = Path(explicit_mappings_path) if explicit_mappings_path else None
    canonical_pairs_path = Path(canonical_pairs_path) if canonical_pairs_path else None
    synthetic_rules_path = Path(synthetic_rules_path) if synthetic_rules_path else None
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    cache_payload = {
        "esto": _file_signature(esto_path),
        "ninth": _file_signature(ninth_path),
        "explicit_reassignments": _file_signature(explicit_reassignments_path) if explicit_reassignments_path else {},
        "explicit_mappings": _file_signature(explicit_mappings_path) if explicit_mappings_path else {},
        "canonical_pairs": _file_signature(canonical_pairs_path) if canonical_pairs_path else {},
        "synthetic_rules": _file_signature(synthetic_rules_path) if synthetic_rules_path else {},
        "options": {
            "apply_esto_subtotal_map": bool(apply_esto_subtotal_map),
            "filter_esto_subtotals_flag": bool(filter_esto_subtotals_flag),
            "filter_ninth_subtotals_flag": bool(filter_ninth_subtotals_flag),
        },
    }
    cache_key = _build_reference_cache_key(cache_payload)
    esto_cache = cache_dir / f"{cache_key}_esto.csv"
    ninth_cache = cache_dir / f"{cache_key}_ninth.csv"
    meta_cache = cache_dir / f"{cache_key}_meta.json"

    if esto_cache.exists() and ninth_cache.exists() and meta_cache.exists():
        return read_config_table(esto_cache), read_config_table(ninth_cache)

    esto_df = read_config_table(esto_path)
    ninth_df = read_config_table(ninth_path, low_memory=False)

    if apply_esto_subtotal_map:
        esto_df = apply_esto_subtotal_mapping(esto_df)
    if filter_esto_subtotals_flag:
        esto_df = filter_esto_subtotals(esto_df)
    if filter_ninth_subtotals_flag:
        for subtotal_col in ["subtotal_results", "subtotal_layout"]:
            if subtotal_col in ninth_df.columns:
                mask = (
                    ninth_df[subtotal_col]
                    .fillna(False)
                    .astype(str)
                    .str.strip()
                    .str.lower()
                    .isin({"true", "1", "yes"})
                )
                ninth_df = ninth_df.loc[~mask].copy()

    explicit_reassignments = (
        load_explicit_sector_reassignments(explicit_reassignments_path)
        if explicit_reassignments_path and config_table_exists(explicit_reassignments_path)
        else pd.DataFrame()
    )
    if not explicit_reassignments.empty:
        esto_df, ninth_df, _ = apply_explicit_sector_reassignments(
            esto_df, ninth_df, explicit_reassignments
        )

    explicit_mappings = (
        load_explicit_sector_fuel_mappings(explicit_mappings_path)
        if explicit_mappings_path and explicit_mappings_path.exists()
        else pd.DataFrame()
    )
    canonical_pairs = (
        load_canonical_pairs(canonical_pairs_path, strict=False)[0]
        if canonical_pairs_path and config_table_exists(canonical_pairs_path)
        else pd.DataFrame()
    )
    synthetic_rules = (
        load_synthetic_reference_rows_config(synthetic_rules_path)
        if synthetic_rules_path and config_table_exists(synthetic_rules_path)
        else pd.DataFrame()
    )
    if not synthetic_rules.empty:
        esto_df, ninth_df, _ = append_synthetic_reference_rows(
            esto_df=esto_df,
            ninth_df=ninth_df,
            rules=synthetic_rules,
            explicit_mappings=explicit_mappings,
            canonical_pairs=canonical_pairs,
        )

    esto_df.to_csv(esto_cache, index=False)
    ninth_df.to_csv(ninth_cache, index=False)
    meta_cache.write_text(json.dumps(cache_payload, indent=2))
    return esto_df, ninth_df
