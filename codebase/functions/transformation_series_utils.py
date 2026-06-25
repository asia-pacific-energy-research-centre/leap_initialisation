"""Pure series computation helpers for transformation analysis.

Stateless functions for energy series arithmetic: efficiency, allocation, share
computation, and year-range helpers. No module-level globals required.
"""
import pandas as pd

from codebase.functions.esto_data_utils import try_debug_breakpoint


def ensure_full_year_series(series, base_year, final_year):
    """Return a Series indexed by the full year range, filling missing with 0."""
    try:
        full_years = list(range(base_year, final_year + 1))
        if series is None or series.empty:
            return pd.Series({year: 0.0 for year in full_years})
        return series.reindex(full_years, fill_value=0.0)
    except Exception as exc:
        print(f"Failed to ensure full year series: {exc}")
        try_debug_breakpoint()
        raise


def series_to_year_dict(series, base_year, final_year):
    """Return a dict of year -> value for the full year range."""
    try:
        full_series = ensure_full_year_series(series, base_year, final_year)
        return full_series.to_dict()
    except Exception as exc:
        print(f"Failed to convert series to year dict: {exc}")
        try_debug_breakpoint()
        raise


def safe_divide_series(numerator, denominator):
    """Return numerator/denominator with zeros where denominator is 0."""
    try:
        if numerator is None or denominator is None:
            return pd.Series(dtype=float)
        aligned = numerator.align(denominator, fill_value=0.0)
        num, denom = aligned
        result = num.copy()
        result[denom == 0] = 0.0
        result[denom != 0] = num[denom != 0] / denom[denom != 0]
        return result
    except Exception as exc:
        print(f"Failed to divide series safely: {exc}")
        try_debug_breakpoint()
        raise


def to_input_only_series(series):
    """Return the input-only component of a signed series (negative values as positives)."""
    try:
        if series is None:
            return pd.Series(dtype=float)
        return series.clip(upper=0).abs()
    except Exception as exc:
        print(f"Failed to build input-only series: {exc}")
        try_debug_breakpoint()
        raise


def to_output_only_series(series):
    """Return the output-only component of a signed series (positive values only)."""
    try:
        if series is None:
            return pd.Series(dtype=float)
        return series.clip(lower=0)
    except Exception as exc:
        print(f"Failed to build output-only series: {exc}")
        try_debug_breakpoint()
        raise


def build_auxiliary_ratios_by_year(negative_timeseries, auxiliary_fuels, output_series):
    """Return auxiliary fuel ratios by year for each auxiliary fuel."""
    try:
        ratios = {}
        if negative_timeseries is None or output_series is None:
            return ratios
        output_series_pos = to_output_only_series(output_series)
        for label in auxiliary_fuels:
            if label not in negative_timeseries.index:
                continue
            aux_input_only = to_input_only_series(negative_timeseries.loc[label])
            ratio_series = safe_divide_series(
                aux_input_only,
                output_series_pos,
            )
            ratios[label] = ratio_series.to_dict()
        return ratios
    except Exception as exc:
        print(f"Failed to build auxiliary ratios by year: {exc}")
        try_debug_breakpoint()
        raise


def build_auxiliary_from_losses_by_year(loss_values_by_year, output_series, feedstock_labels=None):
    """Return auxiliary fuels and ratios by year derived from losses, excluding feedstock fuels."""
    try:
        if not loss_values_by_year:
            return [], {}
        exclude = {str(label) for label in (feedstock_labels or [])}
        output_series_pos = to_output_only_series(output_series)
        fuels = []
        ratios = {}
        for label, series in loss_values_by_year.items():
            if str(label) in exclude:
                continue
            fuels.append(label)
            ratio_series = safe_divide_series(pd.Series(series).abs(), output_series_pos)
            ratios[label] = ratio_series.to_dict()
        return fuels, ratios
    except Exception as exc:
        print(f"Failed to build auxiliary fuels from losses by year: {exc}")
        try_debug_breakpoint()
        raise


def merge_loss_into_auxiliary_by_year(
    auxiliary_fuels, auxiliary_ratios, loss_values_by_year, output_series, feedstock_label
):
    """Treat own use/loss fuels as auxiliary by year (unless same as feedstock)."""
    try:
        if not loss_values_by_year or output_series is None or output_series.empty:
            return auxiliary_fuels, auxiliary_ratios
        output_series_pos = to_output_only_series(output_series)
        updated_fuels = list(auxiliary_fuels) if auxiliary_fuels else []
        updated_ratios = dict(auxiliary_ratios) if auxiliary_ratios else {}
        for label, series in loss_values_by_year.items():
            if label == feedstock_label:
                continue
            if label not in updated_fuels:
                updated_fuels.append(label)
            ratio_series = safe_divide_series(pd.Series(series).abs(), output_series_pos)
            updated_ratios[label] = ratio_series.to_dict()
        return updated_fuels, updated_ratios
    except Exception as exc:
        print(f"Failed to merge loss fuels into auxiliary list by year: {exc}")
        try_debug_breakpoint()
        raise


def filter_loss_values_for_feedstock_by_year(loss_values_by_year, feedstock_label):
    """Return loss values by year for the feedstock fuel only."""
    try:
        if not loss_values_by_year or not feedstock_label:
            return {}
        if feedstock_label not in loss_values_by_year:
            return {}
        return {feedstock_label: loss_values_by_year[feedstock_label]}
    except Exception as exc:
        print(f"Failed to filter loss values for feedstock by year: {exc}")
        try_debug_breakpoint()
        raise


def get_loss_total_for_efficiency_by_year(loss_values_by_year, feedstock_label, output_label, years):
    """Return year->loss total using feedstock/output labels only."""
    try:
        if not loss_values_by_year:
            return pd.Series({year: 0.0 for year in years})
        relevant_labels = {feedstock_label, output_label}
        totals = {year: 0.0 for year in years}
        for label in relevant_labels:
            series = loss_values_by_year.get(label)
            if not series:
                continue
            for year, value in series.items():
                totals[int(year)] = totals.get(int(year), 0.0) + abs(value)
        return pd.Series(totals)
    except Exception as exc:
        print(f"Failed to build loss total for efficiency by year: {exc}")
        try_debug_breakpoint()
        raise


def compute_efficiency_by_year(output_series, input_series, loss_series):
    """Return efficiency by year: output / (input + losses)."""
    try:
        output_series_pos = to_output_only_series(output_series)
        denom = input_series.add(loss_series, fill_value=0.0)
        denom = denom.clip(lower=0.0)
        return safe_divide_series(output_series_pos, denom)
    except Exception as exc:
        print(f"Failed to compute efficiency by year: {exc}")
        try_debug_breakpoint()
        raise


def compute_primary_io(negative_series, positive_series):
    """Return primary input/output labels and totals.

    Expects `negative_series` to contain the feedstock or own-use rows (negative balances)
    and `positive_series` to hold the corresponding outputs. The returned input total is
    always reported as a positive volume for LEAP.
    """
    try:
        primary_input = negative_series.idxmin()
        primary_output = positive_series.idxmax()
        input_total = abs(negative_series.loc[primary_input])
        output_total = positive_series.loc[primary_output]
        return primary_input, primary_output, input_total, output_total
    except Exception as exc:
        print(f"Failed to compute primary input/output: {exc}")
        try_debug_breakpoint()
        raise


def build_total_input_series(input_series_map, years):
    """Return total input series from per-label input series."""
    try:
        total = pd.Series({year: 0.0 for year in years}, dtype=float)
        if not input_series_map:
            return total
        for series in input_series_map.values():
            if series is None:
                continue
            aligned = series.reindex(years, fill_value=0.0)
            total = total.add(aligned, fill_value=0.0)
        return total
    except Exception as exc:
        print(f"Failed to build total input series: {exc}")
        try_debug_breakpoint()
        raise


def build_input_share_series(input_series, total_input_series, fallback_to_one=False):
    """Return input share series with optional fallback when totals are zero."""
    try:
        share = safe_divide_series(input_series, total_input_series)
        if total_input_series is None or total_input_series.empty:
            return share
        zero_mask = total_input_series.eq(0.0)
        if zero_mask.any():
            if fallback_to_one:
                share = share.where(~zero_mask, 1.0)
            else:
                share = share.where(~zero_mask, 0.0)
        return share
    except Exception as exc:
        print(f"Failed to build input share series: {exc}")
        try_debug_breakpoint()
        raise


def allocate_outputs_by_share(output_series_by_label, share_series):
    """Return output series scaled by a share series."""
    try:
        if not output_series_by_label:
            return {}
        if share_series is None or share_series.empty:
            return {label: series.copy() for label, series in output_series_by_label.items()}
        allocated = {}
        for label, series in output_series_by_label.items():
            if series is None:
                continue
            allocated[label] = series.mul(share_series, fill_value=0.0)
        return allocated
    except Exception as exc:
        print(f"Failed to allocate outputs by share: {exc}")
        try_debug_breakpoint()
        raise


def allocate_loss_by_share(loss_values_by_year, share_series):
    """Return loss values scaled by a share series."""
    try:
        if not loss_values_by_year:
            return {}
        if share_series is None or share_series.empty:
            return dict(loss_values_by_year)
        share_map = {int(year): float(val) for year, val in share_series.items()}
        allocated = {}
        for label, values in loss_values_by_year.items():
            if not values:
                continue
            scaled = {}
            for year, share in share_map.items():
                value = values.get(year, values.get(str(year), 0.0))
                if value is None or pd.isna(value):
                    continue
                scaled[int(year)] = float(value) * float(share)
            if scaled:
                allocated[label] = scaled
        return allocated
    except Exception as exc:
        print(f"Failed to allocate losses by share: {exc}")
        try_debug_breakpoint()
        raise


def sum_loss_values_by_year(loss_values_by_year, years):
    """Return a year-indexed series with total losses across labels."""
    try:
        totals = {int(year): 0.0 for year in years}
        if not loss_values_by_year:
            return pd.Series(totals, dtype=float)
        for values in loss_values_by_year.values():
            if not values:
                continue
            for year in years:
                value = values.get(year, values.get(str(year), 0.0))
                if value is None or pd.isna(value):
                    continue
                totals[int(year)] = totals.get(int(year), 0.0) + abs(float(value))
        return pd.Series(totals, dtype=float)
    except Exception as exc:
        print(f"Failed to sum loss values by year: {exc}")
        try_debug_breakpoint()
        raise


def scale_year_dict_by_share(year_dict, share_series):
    """Scale a year->value dict by a share series."""
    try:
        if not year_dict:
            return {}
        if share_series is None or share_series.empty:
            return dict(year_dict)
        share_map = {int(year): float(val) for year, val in share_series.items()}
        scaled = {}
        for year, value in year_dict.items():
            if value is None or pd.isna(value):
                continue
            year_int = int(year)
            share = share_map.get(year_int, share_map.get(str(year_int), 0.0))
            scaled[year_int] = float(value) * float(share)
        return scaled
    except Exception as exc:
        print(f"Failed to scale year dict by share: {exc}")
        try_debug_breakpoint()
        raise


def calculate_efficiency_with_losses(output_total, input_total, loss_total):
    """Return efficiency including losses (output / (input + losses))."""
    try:
        denominator = input_total + loss_total
        if denominator == 0:
            return 0.0
        return output_total / denominator
    except Exception as exc:
        print(f"Failed to calculate efficiency with losses: {exc}")
        try_debug_breakpoint()
        raise
