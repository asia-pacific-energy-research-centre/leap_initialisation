"""Fuel-summary helpers extracted from transformation_analysis_utils (Phase 3d).

These functions operate only on DataFrames and year-column lists; they have no
dependency on module-level globals such as esto_data or DATASET_MAP.
"""
from __future__ import annotations

import pandas as pd

from codebase.functions.esto_data_utils import (
    try_debug_breakpoint,
    _match_code_prefix,
)


def get_years_from(year_cols, start_year):
    """Return a list with the base year column when available."""
    try:
        return [year for year in year_cols if year >= start_year]
    except Exception as exc:
        print(f"Failed to filter year columns from {start_year}: {exc}")
        try_debug_breakpoint()
        raise


def get_fuel_labels(df):
    """Return a series of fuel labels for grouping."""
    try:
        if "subfuels" in df.columns and "fuels" in df.columns:
            return df["subfuels"].where(df["subfuels"] != "x", df["fuels"])
        if "products" in df.columns:
            return df["products"]
        return None
    except Exception as exc:
        print(f"Failed to get fuel labels: {exc}")
        try_debug_breakpoint()
        raise


def summarize_fuels_by_subfuel(df, year_cols, start_year):
    """Summarize inputs (negative) and outputs (positive) per fuel label."""
    try:
        totals, _ = summarize_fuel_totals(df, year_cols, start_year, allow_all_years_fallback=False)
        negatives = totals[totals < 0].sort_values()
        positives = totals[totals > 0].sort_values(ascending=False)
        return negatives, positives
    except Exception as exc:
        print(f"Failed to summarize fuels by subfuel: {exc}")
        try_debug_breakpoint()
        raise


def summarize_fuel_totals(df, year_cols, start_year, allow_all_years_fallback=True):
    """Return totals by fuel label and whether all-years fallback was used."""
    try:
        fuel_labels = get_fuel_labels(df)
        if fuel_labels is None:
            return pd.Series(dtype=float), False
        year_cols_from_start = get_years_from(year_cols, start_year)
        totals = (
            df.assign(fuel_label=fuel_labels)
            .groupby("fuel_label")[year_cols_from_start]
            .sum()
            .sum(axis=1)
        )
        if allow_all_years_fallback and (totals[totals < 0].empty or totals[totals > 0].empty):
            totals = (
                df.assign(fuel_label=fuel_labels)
                .groupby("fuel_label")[year_cols]
                .sum()
                .sum(axis=1)
            )
            return totals.sort_values(), True
        return totals.sort_values(), False
    except Exception as exc:
        print(f"Failed to summarize fuel totals: {exc}")
        try_debug_breakpoint()
        raise


def summarize_fuel_timeseries(df, year_cols, start_year, allow_all_years_fallback=True):
    """Return (timeseries_df, used_all_years) grouped by fuel label and year."""
    try:
        fuel_labels = get_fuel_labels(df)
        if fuel_labels is None:
            return pd.DataFrame(), False
        year_cols_from_start = get_years_from(year_cols, start_year)
        timeseries = (
            df.assign(fuel_label=fuel_labels)
            .groupby("fuel_label")[year_cols_from_start]
            .sum()
        )
        totals = timeseries.sum(axis=1)
        if allow_all_years_fallback and (totals[totals < 0].empty or totals[totals > 0].empty):
            timeseries = (
                df.assign(fuel_label=fuel_labels)
                .groupby("fuel_label")[year_cols]
                .sum()
            )
            return timeseries, True
        return timeseries, False
    except Exception as exc:
        print(f"Failed to summarize fuel timeseries: {exc}")
        try_debug_breakpoint()
        raise


def get_label_timeseries(timeseries_df, label):
    """Return a series for a label, matching on code prefix when needed."""
    try:
        if timeseries_df is None or timeseries_df.empty:
            return pd.Series(dtype=float)
        if label in timeseries_df.index:
            return timeseries_df.loc[label]
        matches = [
            idx for idx in timeseries_df.index if _match_code_prefix(idx, label)
        ]
        if matches:
            return timeseries_df.loc[matches[0]]
        return pd.Series(dtype=float)
    except Exception as exc:
        print(f"Failed to get label timeseries for {label}: {exc}")
        try_debug_breakpoint()
        raise


def sum_years_by_year(df, year_cols, start_year):
    """Return a Series of year -> total for selected years."""
    try:
        year_cols_from_start = get_years_from(year_cols, start_year)
        if not year_cols_from_start:
            return pd.Series(dtype=float)
        return df[year_cols_from_start].sum()
    except Exception as exc:
        print(f"Failed to sum years by year: {exc}")
        try_debug_breakpoint()
        raise
