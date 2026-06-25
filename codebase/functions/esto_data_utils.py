"""Shared ESTO/9th data utilities used by both transformation_analysis_utils and supply_data_pipeline.

Moved here (Phase 3 deduplication) to eliminate 11 duplicate function bodies.
"""
from __future__ import annotations

import re

import pandas as pd

from codebase.utilities.master_config import read_config_table

ENABLE_DEBUG_BREAKPOINTS = True


def try_debug_breakpoint():
    """Trigger a debug breakpoint when enabled (safe to call anywhere)."""
    if not ENABLE_DEBUG_BREAKPOINTS:
        return
    try:
        breakpoint()
    except Exception as breakpoint_exc:
        print(f"Debug breakpoint failed: {breakpoint_exc}")


def _extract_numeric_segments(value):
    """Return a list of numeric code segments from a code or label."""
    try:
        if value is None:
            return []
        text = str(value)
        if text == "x":
            return []
        segments = []
        for chunk in text.replace(".", "_").split("_"):
            match = re.match(r"^(\d+)", chunk)
            if not match:
                break
            segments.append(match.group(1).zfill(2))
        return segments
    except Exception as exc:
        print(f"Failed to extract numeric segments from {value}: {exc}")
        try_debug_breakpoint()
        raise


def _match_code_prefix(label_value, code_value):
    """Check if label_value shares the numeric prefix of code_value."""
    try:
        code_segments = _extract_numeric_segments(code_value)
        if not code_segments:
            return False
        label_segments = _extract_numeric_segments(label_value)
        if len(label_segments) < len(code_segments):
            return False
        return label_segments[: len(code_segments)] == code_segments
    except Exception as exc:
        print(f"Failed to match code prefix for {code_value}: {exc}")
        try_debug_breakpoint()
        raise


def load_csv_data(path, label):
    """Load a CSV file and return a pandas DataFrame."""
    try:
        df = read_config_table(path)
        print(f"Loaded {label}: {df.shape[0]} rows, {df.shape[1]} columns")
        return df
    except Exception as exc:
        print(f"Failed to load {label} from {path}: {exc}")
        try_debug_breakpoint()
        raise


def normalize_year_columns(df):
    """Convert year-like columns to int and return (df, year_cols)."""
    try:
        year_cols = [int(col) for col in df.columns if str(col).isdigit()]
        df.columns = [int(col) if str(col).isdigit() else col for col in df.columns]
        return df, year_cols
    except Exception as exc:
        print(f"Failed to normalize year columns: {exc}")
        try_debug_breakpoint()
        raise


def filter_reference_scenario(df, label):
    """Filter to the Reference scenario when a scenarios column is present."""
    try:
        if "scenarios" not in df.columns:
            return df
        scenarios = df["scenarios"].astype(str).str.strip().str.lower()
        filtered = df[scenarios == "reference"].copy()
        unique_vals = sorted(set(scenarios.unique()))
        print(
            f"{label}: filtering to scenarios=reference "
            f"(available={unique_vals}, rows={filtered.shape[0]})"
        )
        return filtered
    except Exception as exc:
        print(f"Failed to filter scenarios for {label}: {exc}")
        try_debug_breakpoint()
        raise


def sum_years(df, year_cols):
    """Sum values over year columns, returning a float."""
    try:
        if df.empty:
            return 0.0
        return df[year_cols].sum().sum()
    except Exception as exc:
        print(f"Failed to sum years for frame: {exc}")
        try_debug_breakpoint()
        raise


def get_economy_list(df, requested_economies=None):
    """Return a list of economies to analyze."""
    try:
        available = sorted(df["economy"].dropna().unique())
        if requested_economies:
            requested = [econ for econ in requested_economies if econ in available]
            missing = [econ for econ in requested_economies if econ not in available]
            if missing:
                print(
                    "Warning: requested economies not found in this dataset: "
                    f"{', '.join(missing)}"
                )
            if requested:
                return requested
            print("Warning: no requested economies found; using all available economies.")
        return available
    except Exception as exc:
        print(f"Failed to build economy list: {exc}")
        try_debug_breakpoint()
        raise


def add_all_economy_total(df, year_cols, economy_label="ALL"):
    """Append an all-economy total row set to a dataset."""
    try:
        if "economy" not in df.columns or df.empty:
            return df
        if df["economy"].astype(str).eq(economy_label).any():
            return df
        group_cols = [
            col for col in df.columns if col not in year_cols and col != "economy"
        ]
        totals = (
            df.groupby(group_cols, dropna=False)[year_cols]
            .sum()
            .reset_index()
        )
        totals["economy"] = economy_label
        totals = totals[df.columns.tolist()]
        return pd.concat([df, totals], ignore_index=True)
    except Exception as exc:
        print(f"Failed to add all-economy totals: {exc}")
        try_debug_breakpoint()
        raise


def build_dataset_map(esto_data, esto_year_cols, ninth_data, ninth_year_cols, matt_data, matt_year_cols):
    """Return a dataset map keyed by dataset_key."""
    try:
        return {
            "esto": (esto_data, esto_year_cols),
            "ninth": (ninth_data, ninth_year_cols),
            "matt": (matt_data, matt_year_cols),
        }
    except Exception as exc:
        print(f"Failed to build dataset map: {exc}")
        try_debug_breakpoint()
        raise


def resolve_dataset(dataset_map, dataset_key):
    """Return (data, year_cols) for a dataset key."""
    try:
        if dataset_key not in dataset_map:
            raise KeyError(f"Unknown dataset key: {dataset_key}")
        return dataset_map[dataset_key]
    except Exception as exc:
        print(f"Failed to resolve dataset key {dataset_key}: {exc}")
        try_debug_breakpoint()
        raise
