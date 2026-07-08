"""Transformation process record building, table construction, and export helpers.

Extracted from transformation_analysis_utils.py (Phase 3b).
Import these functions via transformation_analysis_utils which re-exports them,
or directly from this module.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Sequence

import pandas as pd

from codebase.utilities.master_config import config_table_exists, read_config_table
from codebase.functions.leap_excel_io import finalise_export_df, save_export_files
from codebase.functions.leap_core import sanitize_leap_branch_path
from codebase.functions.esto_data_utils import (
    _extract_numeric_segments,
    _match_code_prefix,
    try_debug_breakpoint as _try_debug_breakpoint,
)

# Scenario export constants (re-derived from workflow_cfg to avoid circular import)
from codebase.configuration import workflow_config as _wf_cfg_rb

_PROJECTION_END_YEAR_RB = 2060
_esc_rb = _wf_cfg_rb.get_energy_source_config()
if _esc_rb.projection_final_year is not None:
    _PROJECTION_END_YEAR_RB = int(_esc_rb.projection_final_year)
_cfg_final_year_rb = _wf_cfg_rb.TRANSFORMATION_EXPORT_FINAL_YEAR
EXPORT_BASE_YEAR = int(_wf_cfg_rb.TRANSFORMATION_EXPORT_BASE_YEAR)
EXPORT_FINAL_YEAR = _PROJECTION_END_YEAR_RB if _cfg_final_year_rb is None else int(_cfg_final_year_rb)
SCENARIO_EXPORT_OVERRIDES = _wf_cfg_rb.TRANSFORMATION_SCENARIO_EXPORT_OVERRIDES
INCLUDE_OUTPUT_SERIES_IN_LEAP_EXPORT = (
    _wf_cfg_rb.TRANSFORMATION_INCLUDE_OUTPUT_SERIES_IN_LEAP_EXPORT
)
TRANSFORMATION_OUTPUT_VARIABLES = {
    "output": True,
    "output_import_target": True,
    "output_export_target": True,
    "feedstock_share": True,
    "process_efficiency": True,
    "auxiliary_ratio": True,
    "loss_value": True,
}
DEFAULT_OUTPUT_UNITS = "Petajoule"
DEFAULT_EFFICIENCY_UNITS = "Percent"
DEFAULT_FEEDSTOCK_UNITS = "Share"
DEFAULT_FEEDSTOCK_SCALE = "%"
DEFAULT_AUXILIARY_UNITS = "Petajoule"
DEFAULT_AUXILIARY_PER = "Petajoule"

# Transformation flow codes intentionally NOT represented in LEAP yet, so they
# are skipped from transformation record naming/export.  These carry no ESTO
# energy (e.g. 09.10 Biofuels processing is confirmed zero in ESTO) and have no
# leap_display_name in the mappings workbook, so dropping them is safe and avoids
# a "Missing code-to-name mapping" error on their code labels.
EXCLUDED_TRANSFORMATION_FLOW_CODES = frozenset({
    "09.03 Heat pumps",
    "09.10 Biofuels processing",
})


def _is_excluded_transformation_record(record) -> bool:
    """Return True for records whose sector/process is an excluded (not-in-LEAP)
    transformation flow code — see EXCLUDED_TRANSFORMATION_FLOW_CODES."""
    for key in ("sector_title", "process_name"):
        value = " ".join(str((record or {}).get(key) or "").split())
        if value in EXCLUDED_TRANSFORMATION_FLOW_CODES:
            return True
    return False


def get_scenario_export_config(scenario, default_base_year=None, default_final_year=None):
    """Return export overrides for the given scenario."""
    overrides = SCENARIO_EXPORT_OVERRIDES.get(scenario, {})
    scenario_name = str(scenario or "").strip().lower()
    is_current_accounts = scenario_name in {"current accounts", "current account"}
    resolved_base_year = (
        EXPORT_BASE_YEAR if default_base_year is None else int(default_base_year)
    )
    resolved_final_year = (
        EXPORT_FINAL_YEAR if default_final_year is None else int(default_final_year)
    )
    default_final_year = resolved_base_year if is_current_accounts else resolved_final_year
    return {
        "export_base_year": overrides.get("export_base_year", resolved_base_year),
        "export_final_year": overrides.get("export_final_year", default_final_year),
        "include_current_account_rows": overrides.get(
            "include_current_account_rows",
            is_current_accounts,
        ),
    }


def compute_combined_year_range(base_year, final_year, scenario_configs):
    """Return the min base year and max final year over all scenarios."""
    base_candidates = [base_year]
    final_candidates = [final_year]
    for cfg in scenario_configs.values():
        base_candidates.append(cfg.get("export_base_year", base_year))
        final_candidates.append(cfg.get("export_final_year", final_year))
    return int(min(base_candidates)), int(max(final_candidates))


def is_code_like_label(label):
    """Return True when the label looks like a coded fuel/sector/flow."""
    try:
        if label is None:
            return False
        text = str(label).strip()
        if not text:
            return False
        if text[0].isdigit():
            return True
        return any(token in text for token in ["_", "."])
    except Exception as exc:
        print(f"Failed to check if label is code-like: {exc}")
        _try_debug_breakpoint()
        raise


def resolve_label_name(label, code_to_name_mapping, context_label=""):
    """Return a mapped label name or raise when missing."""
    try:
        if not code_to_name_mapping:
            raise ValueError("Code-to-name mapping is empty.")
        if label is None:
            return label
        if isinstance(label, float) and pd.isna(label):
            return label
        text = " ".join(str(label).split())
        if text == "":
            return text
        if not is_code_like_label(text):
            return text
        if text in code_to_name_mapping:
            return code_to_name_mapping[text]
        if text in code_to_name_mapping.values():
            return text
        # Handle combined "code name" labels (e.g. "07.15 Paraffin waxes") by looking up the code prefix
        segments = _extract_numeric_segments(text)
        if segments:
            code_prefix = ".".join(segments)
            if code_prefix != text and code_prefix in code_to_name_mapping:
                return code_to_name_mapping[code_prefix]
        # For underscore-format ninth sector/fuel codes not yet in the mapping,
        # auto-generate a readable name by stripping the numeric prefix and
        # converting underscores to spaces (e.g. 09_06_02_liquefaction_regasification_plants
        # → "Liquefaction regasification plants").
        if "_" in text and segments:
            numeric_prefix = "_".join(segments)  # e.g. "09_06_02"
            if text.startswith(numeric_prefix + "_"):
                remainder = text[len(numeric_prefix) + 1:]
                if remainder:
                    return remainder.replace("_", " ").capitalize()
        context_text = f" ({context_label})" if context_label else ""
        raise ValueError(f"Missing code-to-name mapping for label: {text}{context_text}")
    except Exception as exc:
        print(f"Failed to resolve label name for {label}: {exc}")
        _try_debug_breakpoint()
        raise


def map_code_label(label, code_to_name_mapping):
    """Return a label mapped to a human-readable name when available."""
    try:
        return resolve_label_name(label, code_to_name_mapping)
    except Exception as exc:
        print(f"Failed to map label {label}: {exc}")
        _try_debug_breakpoint()
        raise


def map_label_list(labels, code_to_name_mapping):
    """Map a list of labels to human-readable names."""
    try:
        return [
            resolve_label_name(label, code_to_name_mapping, context_label="label list")
            for label in labels
        ]
    except Exception as exc:
        print(f"Failed to map label list: {exc}")
        _try_debug_breakpoint()
        raise


def format_fuel_label(label, code_to_name_mapping):
    """Return a fuel label formatted with numeric code prefix when available."""
    try:
        if label is None:
            return label
        text = str(label)
        if text == "nan":
            return label
        name = resolve_label_name(label, code_to_name_mapping, context_label="format_fuel_label")
        segments = _extract_numeric_segments(label)
        if segments:
            code_prefix = ".".join(segments)
            return f"{code_prefix} {name}"
        return name
    except Exception as exc:
        print(f"Failed to format fuel label {label}: {exc}")
        _try_debug_breakpoint()
        raise


def map_series_index(series, code_to_name_mapping):
    """Map a Series index to human-readable names."""
    try:
        new_index = [
            resolve_label_name(idx, code_to_name_mapping, context_label="series index")
            for idx in series.index
        ]
        return series.rename(index=dict(zip(series.index, new_index)))
    except Exception as exc:
        print(f"Failed to map series index: {exc}")
        _try_debug_breakpoint()
        raise


def split_auxiliary_fuels(negative_series, primary_input, threshold_ratio, include_all=False):
    """Split negative fuels into primary input and auxiliary candidates."""
    try:
        if negative_series is None or negative_series.empty:
            return []
        primary_label = primary_input
        if primary_label not in negative_series.index:
            matches = [
                label
                for label in negative_series.index
                if _match_code_prefix(label, primary_input)
            ]
            if matches:
                primary_label = matches[0]
            else:
                return []
        primary_value = abs(negative_series.loc[primary_label])
        auxiliary = []
        for fuel_label, value in negative_series.items():
            if fuel_label == primary_label:
                continue
            if include_all or abs(value) <= primary_value * threshold_ratio:
                auxiliary.append(fuel_label)
        return auxiliary
    except Exception as exc:
        print(f"Failed to split auxiliary fuels: {exc}")
        _try_debug_breakpoint()
        raise


def get_all_other_negative_fuels(negative_series, primary_input):
    """Return all negative fuel labels except the primary input."""
    try:
        if negative_series is None or negative_series.empty:
            return []
        return [label for label in negative_series.index if label != primary_input]
    except Exception as exc:
        print(f"Failed to build auxiliary fuels from negatives: {exc}")
        _try_debug_breakpoint()
        raise


def has_required_columns(df, required_sets, context_label):
    """Check for required column sets and warn/skip when missing."""
    try:
        for required_columns in required_sets:
            if all(col in df.columns for col in required_columns):
                return True
        print(
            f"{context_label}: missing required columns for this dataset, skipping."
        )
        return False
    except Exception as exc:
        print(f"Failed to validate columns for {context_label}: {exc}")
        _try_debug_breakpoint()
        raise


def build_auxiliary_ratios(negative_series, auxiliary_fuels, output_total):
    """Return auxiliary fuel ratios (abs(input)/output)."""
    try:
        ratios = {}
        if negative_series is None or output_total == 0:
            return ratios
        for label in auxiliary_fuels:
            if label in negative_series.index:
                ratios[label] = abs(negative_series.get(label)) / output_total
        return ratios
    except Exception as exc:
        print(f"Failed to build auxiliary ratios: {exc}")
        _try_debug_breakpoint()
        raise


def build_auxiliary_from_losses(loss_values, output_total):
    """Return auxiliary fuels/ratios derived from loss values."""
    try:
        if not loss_values:
            return [], {}
        fuels = []
        ratios = {}
        for label, value in loss_values.items():
            fuels.append(label)
            ratios[label] = abs(value) / output_total if output_total else 0.0
        return fuels, ratios
    except Exception as exc:
        print(f"Failed to build auxiliary fuels from losses: {exc}")
        _try_debug_breakpoint()
        raise


def merge_loss_into_auxiliary(
    auxiliary_fuels, auxiliary_ratios, loss_values, output_total, feedstock_label
):
    """Treat own use/loss fuels as auxiliary (unless same as feedstock)."""
    try:
        if not loss_values or output_total == 0:
            return auxiliary_fuels, auxiliary_ratios
        updated_fuels = list(auxiliary_fuels) if auxiliary_fuels else []
        updated_ratios = dict(auxiliary_ratios) if auxiliary_ratios else {}
        for label, value in loss_values.items():
            if label == feedstock_label:
                continue
            if label not in updated_fuels:
                updated_fuels.append(label)
            updated_ratios[label] = abs(value) / output_total
        return updated_fuels, updated_ratios
    except Exception as exc:
        print(f"Failed to merge loss fuels into auxiliary list: {exc}")
        _try_debug_breakpoint()
        raise


def filter_loss_values_for_feedstock(loss_values, feedstock_label):
    """Return loss values for the feedstock fuel only."""
    try:
        if not loss_values or not feedstock_label:
            return {}
        if feedstock_label not in loss_values:
            return {}
        return {feedstock_label: loss_values[feedstock_label]}
    except Exception as exc:
        print(f"Failed to filter loss values for feedstock: {exc}")
        _try_debug_breakpoint()
        raise


def get_loss_total_for_efficiency(loss_values, feedstock_label, output_label):
    """Return loss total for efficiency using feedstock/output fuel losses only."""
    try:
        if not loss_values:
            return 0.0
        relevant_labels = {feedstock_label, output_label}
        return sum(
            value for label, value in loss_values.items() if label in relevant_labels
        )
    except Exception as exc:
        print(f"Failed to build loss total for efficiency: {exc}")
        _try_debug_breakpoint()
        raise


def print_leap_structure_header(title):
    """Print a section header that mirrors the LEAP branch structure."""
    try:
        print("")
        print(title)
        print("-" * len(title))
    except Exception as exc:
        print(f"Failed to print LEAP structure header: {exc}")
        _try_debug_breakpoint()
        raise


def format_value(value):
    """Format numeric values for LEAP structure output."""
    try:
        if isinstance(value, str):
            return value
        if value is None or pd.isna(value):
            return ""
        return f"{float(value):.6f}"
    except Exception as exc:
        print(f"Failed to format value {value}: {exc}")
        _try_debug_breakpoint()
        raise


def build_year_rows(branch_path, measure, scenario, value_by_year, units, scale, per_value):
    """Return log-style rows for a LEAP import file.

    Inputs:
        branch_path: LEAP branch path string (e.g., Transformation\\Coke ovens)
        measure: LEAP variable name (e.g., "Process Efficiency")
        scenario: scenario label (e.g., "Current Accounts")
        value_by_year: dict of year -> value
        units: units string for LEAP
        scale: scale string for LEAP
        per_value: per... string for LEAP

    Outputs:
        List[dict] with fields expected by finalise_export_df.

    Side effects:
        None.
    """
    try:
        rows = []
        for year, value in sorted(value_by_year.items()):
            rows.append(
                {
                    "Branch_Path": branch_path,
                    "Scenario": scenario,
                    "Measure": measure,
                    "Units": units,
                    "Scale": scale,
                    "Per...": per_value,
                    "Date": int(year),
                    "Value": float(value),
                }
            )
        return rows
    except Exception as exc:
        print(f"Failed to build year rows for {branch_path}: {exc}")
        _try_debug_breakpoint()
        raise


def build_value_by_year(value, base_year, final_year):
    """Return a dict of year -> value for the given range."""
    try:
        return {year: value for year in range(base_year, final_year + 1)}
    except Exception as exc:
        print(f"Failed to build value-by-year map: {exc}")
        _try_debug_breakpoint()
        raise


def coerce_value_by_year(value, base_year, final_year):
    """Return a year->value dict from a scalar, series, or dict."""
    try:
        if isinstance(value, dict):
            return {int(year): float(val) for year, val in value.items()}
        if isinstance(value, pd.Series):
            return {int(year): float(val) for year, val in value.items()}
        return build_value_by_year(value, base_year, final_year)
    except Exception as exc:
        print(f"Failed to coerce value to year map: {exc}")
        _try_debug_breakpoint()
        raise


def normalize_feedstock_share_to_percent(value_by_year):
    """Convert 0-1 feedstock shares to 0-100 percentages for LEAP."""
    try:
        if not value_by_year:
            return value_by_year
        values = [abs(float(v)) for v in value_by_year.values() if v is not None and not pd.isna(v)]
        if not values:
            return value_by_year
        if max(values) <= 1.000001:
            return {int(year): float(val) * 100.0 for year, val in value_by_year.items()}
        return {int(year): float(val) for year, val in value_by_year.items()}
    except Exception as exc:
        print(f"Failed to normalize feedstock shares to percent: {exc}")
        _try_debug_breakpoint()
        raise


def resolve_scenario_year_range(base_year, final_year, scenario_config=None):
    """Return the year window to export for the active scenario."""
    try:
        scenario_base_year = int(base_year)
        scenario_final_year = int(final_year)
        if scenario_config:
            scenario_base_year = int(
                scenario_config.get("export_base_year", scenario_base_year)
            )
            scenario_final_year = int(
                scenario_config.get("export_final_year", scenario_final_year)
            )
        if scenario_final_year < scenario_base_year:
            scenario_final_year = scenario_base_year
        return scenario_base_year, scenario_final_year
    except Exception as exc:
        print(f"Failed to resolve scenario year range: {exc}")
        _try_debug_breakpoint()
        raise


def clip_value_by_year_range(value_by_year, start_year, end_year):
    """Keep only year entries within [start_year, end_year]."""
    try:
        if not value_by_year:
            return {}
        start = int(start_year)
        end = int(end_year)
        return {
            int(year): float(value)
            for year, value in value_by_year.items()
            if start <= int(year) <= end and value is not None and not pd.isna(value)
        }
    except Exception as exc:
        print(f"Failed to clip year map to range {start_year}-{end_year}: {exc}")
        _try_debug_breakpoint()
        raise


def normalize_feedstock_shares_for_export(feedstock_shares, base_year, final_year):
    """Normalize per-fuel shares so each process-year sums to exactly 100%."""
    try:
        if not feedstock_shares:
            return {}
        labels = list(feedstock_shares.keys())
        if not labels:
            return {}

        normalized = {}
        for label, raw_share in feedstock_shares.items():
            value_by_year = coerce_value_by_year(raw_share, base_year, final_year)
            value_by_year = clip_value_by_year_range(
                value_by_year,
                base_year,
                final_year,
            )
            value_by_year = normalize_feedstock_share_to_percent(value_by_year)
            normalized[label] = {
                int(year): max(float(value), 0.0)
                for year, value in value_by_year.items()
                if value is not None and not pd.isna(value)
            }

        # Build a stable fallback distribution for years with zero/undefined totals.
        fallback_weights = {
            label: sum(max(float(value), 0.0) for value in normalized[label].values())
            for label in labels
        }
        fallback_total = sum(fallback_weights.values())
        if fallback_total > 0.0:
            fallback_distribution = {
                label: fallback_weights[label] * 100.0 / fallback_total
                for label in labels
            }
            anchor_label = max(fallback_distribution, key=fallback_distribution.get)
            fallback_distribution[anchor_label] += 100.0 - sum(
                fallback_distribution.values()
            )
        else:
            fallback_distribution = {label: 0.0 for label in labels}

        # Build explicit normalized profiles for years that have a valid total.
        positive_profiles = {}
        zero_years = []
        tolerance = 1e-12
        for year in range(int(base_year), int(final_year) + 1):
            year_total = sum(normalized[label].get(year, 0.0) for label in labels)
            if year_total <= tolerance:
                zero_years.append(year)
                continue

            scaled_by_label = {
                label: normalized[label].get(year, 0.0) * 100.0 / year_total
                for label in labels
            }
            anchor_label = max(scaled_by_label, key=scaled_by_label.get)
            residual = 100.0 - sum(scaled_by_label.values())
            scaled_by_label[anchor_label] += residual
            positive_profiles[year] = scaled_by_label

        # For years with zero/undefined totals, copy nearest nonzero profile.
        # Preference: nearest future year, then nearest past year.
        valid_years = sorted(positive_profiles.keys())
        for year in zero_years:
            chosen_profile = None
            if valid_years:
                chosen_year = min(
                    valid_years,
                    key=lambda candidate: (
                        abs(candidate - year),
                        0 if candidate >= year else 1,
                    ),
                )
                chosen_profile = positive_profiles.get(chosen_year)
            if chosen_profile is None:
                chosen_profile = fallback_distribution
            positive_profiles[year] = dict(chosen_profile)

        for year in range(int(base_year), int(final_year) + 1):
            scaled_by_label = positive_profiles.get(year, fallback_distribution)
            for label, value in scaled_by_label.items():
                normalized[label][year] = value
        return normalized
    except Exception as exc:
        print(f"Failed to normalize feedstock shares for export: {exc}")
        _try_debug_breakpoint()
        raise


def _build_feedstock_label_universe(process_records):
    """Return per-process feedstock label sets discovered in records."""
    try:
        label_lookup = {}
        for record in process_records or []:
            key = (
                str(record.get("sector_title") or "").strip(),
                str(record.get("process_name") or "").strip(),
            )
            if not key[0] or not key[1]:
                continue
            labels = []
            for source in (record.get("feedstock_values"), record.get("feedstock_shares")):
                if isinstance(source, dict):
                    labels.extend(str(label).strip() for label in source.keys() if str(label).strip())
            if not labels:
                continue
            bucket = label_lookup.setdefault(key, [])
            for label in labels:
                if label not in bucket:
                    bucket.append(label)
        return label_lookup
    except Exception as exc:
        print(f"Failed to build feedstock label universe: {exc}")
        _try_debug_breakpoint()
        raise


def prepare_feedstock_shares_for_export(
    feedstock_shares,
    feedstock_values,
    process_feedstock_labels,
    base_year,
    final_year,
):
    """Return normalized feedstock shares with zero-use safeguards for LEAP export."""
    try:
        labels = []
        for source in (process_feedstock_labels, feedstock_values, feedstock_shares):
            if isinstance(source, dict):
                values = source.keys()
            elif isinstance(source, list):
                values = source
            else:
                values = []
            for raw in values:
                label = str(raw).strip()
                if label and label not in labels:
                    labels.append(label)
        if not labels:
            return {}

        start = int(base_year)
        end = int(final_year)
        years = list(range(start, end + 1))
        prepared_shares = {}
        usage_totals = {}

        for label in labels:
            share_map = {}
            if isinstance(feedstock_shares, dict) and label in feedstock_shares:
                share_map = coerce_value_by_year(feedstock_shares.get(label), start, end)
                share_map = clip_value_by_year_range(share_map, start, end)
                share_map = normalize_feedstock_share_to_percent(share_map)
            prepared_shares[label] = {
                int(year): float(share_map.get(year, 0.0))
                for year in years
            }

            usage_map = {}
            if isinstance(feedstock_values, dict) and label in feedstock_values:
                usage_map = coerce_value_by_year(feedstock_values.get(label), start, end)
                usage_map = clip_value_by_year_range(usage_map, start, end)
            usage_totals[label] = sum(abs(float(usage_map.get(year, 0.0))) for year in years)

        # Fuels not used in the current economy/process stay at zero share in all years.
        usage_tolerance = 1e-12
        for label, usage_total in usage_totals.items():
            if usage_total <= usage_tolerance:
                prepared_shares[label] = {year: 0.0 for year in years}

        process_used = any(usage_total > usage_tolerance for usage_total in usage_totals.values())
        if not process_used:
            # Process branch exists but is unused: spread 100% equally to avoid LEAP share errors.
            equal_share = 100.0 / float(len(labels))
            for label in labels:
                prepared_shares[label] = {year: equal_share for year in years}
            anchor_label = labels[0]
            for year in years:
                residual = 100.0 - sum(prepared_shares[label][year] for label in labels)
                prepared_shares[anchor_label][year] += residual

        return normalize_feedstock_shares_for_export(prepared_shares, start, end)
    except Exception as exc:
        print(f"Failed to prepare feedstock shares for export: {exc}")
        _try_debug_breakpoint()
        raise


def normalize_process_efficiency_to_percent(value_by_year, input_scale="ratio"):
    """Normalize process efficiency to percent using explicit input-scale rules."""
    try:
        if not value_by_year:
            return value_by_year
        cleaned = {
            int(year): float(val)
            for year, val in value_by_year.items()
            if val is not None and not pd.isna(val)
        }
        if not cleaned:
            return value_by_year
        scale_key = str(input_scale or "ratio").strip().lower()
        if scale_key == "ratio":
            cleaned = {year: value * 100.0 for year, value in cleaned.items()}
        elif scale_key == "percent":
            pass
        else:
            raise ValueError(
                f"Unknown process efficiency input_scale={input_scale!r}. "
                "Use 'ratio' or 'percent'."
            )
        # LEAP rejects non-positive process efficiencies. Prefer carrying forward
        # the previous valid year to avoid artificial tiny values in exports.
        years_sorted = sorted(cleaned.keys())
        first_positive = next((cleaned[year] for year in years_sorted if cleaned[year] > 0.0), None)
        fallback = float(first_positive) if first_positive is not None else 1.0
        last_valid = None
        normalized: dict[int, float] = {}
        for year in years_sorted:
            value = cleaned[year]
            if value > 0.0:
                normalized[year] = value
                last_valid = value
            elif last_valid is not None:
                normalized[year] = last_valid
            else:
                normalized[year] = fallback
        cleaned = normalized
        return cap_process_efficiency_value_by_year(cleaned)
    except Exception as exc:
        print(f"Failed to normalize process efficiency to percent: {exc}")
        _try_debug_breakpoint()
        raise


def _process_efficiency_ceiling_percent():
    """Return the configured maximum process-efficiency percent."""
    ceiling = getattr(_wf_cfg_rb, "TRANSFORMATION_PROCESS_EFFICIENCY_MAX_PERCENT", 1000.0)
    return float(ceiling)


def _process_efficiency_ceiling_enabled():
    """Return whether process-efficiency values should be clipped."""
    return bool(getattr(_wf_cfg_rb, "TRANSFORMATION_CLIP_PROCESS_EFFICIENCY_TO_MAX", True))


def cap_process_efficiency_value(value, ceiling=None):
    """Clip a single process-efficiency value when the ceiling flag is enabled."""
    try:
        if value is None or pd.isna(value):
            return value
        if not _process_efficiency_ceiling_enabled():
            return float(value)
        max_value = _process_efficiency_ceiling_percent() if ceiling is None else float(ceiling)
        numeric_value = float(value)
        return min(numeric_value, max_value)
    except Exception as exc:
        print(f"Failed to cap process efficiency value: {exc}")
        _try_debug_breakpoint()
        raise


def cap_process_efficiency_value_by_year(value_by_year, ceiling=None):
    """Clip a year->value process-efficiency map when the ceiling flag is enabled."""
    try:
        if not isinstance(value_by_year, dict):
            return cap_process_efficiency_value(value_by_year, ceiling=ceiling)
        max_value = _process_efficiency_ceiling_percent() if ceiling is None else float(ceiling)
        return {
            int(year): cap_process_efficiency_value(value, ceiling=max_value)
            for year, value in value_by_year.items()
        }
    except Exception as exc:
        print(f"Failed to cap process efficiency values by year: {exc}")
        _try_debug_breakpoint()
        raise


def summarize_numeric_value(value, summary="sum"):
    """Summarize a scalar or year->value mapping for tables."""
    try:
        if isinstance(value, dict):
            values = [val for val in value.values() if val is not None]
            if not values:
                return None
            if summary == "mean":
                return sum(values) / len(values)
            return sum(values)
        return value
    except Exception as exc:
        print(f"Failed to summarize numeric value: {exc}")
        _try_debug_breakpoint()
        raise


def format_filename_segment(value):
    """Return a file-safe string for economy or scenario labels."""
    try:
        if value is None:
            return ""
        text = str(value).strip()
        if not text:
            return ""
        sanitized = re.sub(r"[^A-Za-z0-9_-]+", "_", text)
        return sanitized.strip("_") or text
    except Exception as exc:
        print(f"Failed to format filename segment for {value}: {exc}")
        _try_debug_breakpoint()
        raise


def build_export_filename(template, fallback, economy, scenario):
    """Format an export filename with economy/scenario segments."""
    try:
        if not template:
            return fallback
        economy_segment = format_filename_segment(economy)
        scenario_segment = format_filename_segment(scenario)
        if "{economy}" not in template and "{scenario}" not in template:
            return template
        return template.format(
            economy=economy_segment,
            scenario=scenario_segment,
        )
    except Exception as exc:
        print(f"Failed to build export filename: {exc}")
        _try_debug_breakpoint()
        return fallback or template

def compute_own_use_ratios_for_record(loss_values_by_year, input_series_map, years):
    """Return {fuel_label: scalar_ratio} for fuels that appear in BOTH losses and feedstock inputs.

    ratio = mean_own_use / (mean_own_use + mean_feedstock_input) over years.

    Only fuels where 0 < ratio < 1 are returned — i.e. fuels that are ambiguously used as
    both feedstock and own-use.  Pure-feedstock fuels (ratio=0) and pure-own-use fuels
    (ratio=1, not in input_series_map) are omitted.

    These ratios are stored on the process record so that on subsequent LEAP results
    readbacks, the reported feedstock 'Inputs' can be split into true feedstock vs
    estimated own-use, allowing auxiliary_ratios to be recalibrated.
    """
    try:
        ratios = {}
        year_index = pd.Index(years)
        for fuel, loss_by_year in (loss_values_by_year or {}).items():
            input_series = (input_series_map or {}).get(fuel)
            if input_series is None:
                continue
            loss_mean = float(
                pd.Series(loss_by_year, dtype=float).reindex(year_index, fill_value=0.0).mean()
            )
            input_mean = float(input_series.reindex(year_index, fill_value=0.0).mean())
            total_mean = loss_mean + input_mean
            if total_mean > 0 and loss_mean > 0:
                ratios[fuel] = loss_mean / total_mean
        return ratios
    except Exception as exc:
        print(f"Failed to compute own-use ratios: {exc}")
        _try_debug_breakpoint()
        raise


def build_process_record(
    economy,
    sector_title,
    process_name,
    output_values,
    feedstock_values,
    efficiency,
    auxiliary_ratios,
    loss_values,
    loss_total,
    loss_values_for_efficiency=None,
    feedstock_shares=None,
    input_total=None,
    output_import_targets=None,
    output_export_targets=None,
    efficiency_scale="ratio",
    own_use_ratios=None,
):
    """Return a standardized record for a transformation process."""
    try:
        return {
            "economy": economy,
            "sector_title": sector_title,
            "process_name": process_name,
            "output_values": dict(output_values or {}),
            "feedstock_values": dict(feedstock_values or {}),
            "feedstock_shares": dict(feedstock_shares or {}),
            "efficiency": efficiency,
            "efficiency_scale": str(efficiency_scale or "ratio"),
            "auxiliary_ratios": dict(auxiliary_ratios or {}),
            "loss_values": dict(loss_values or {}),
            "loss_total": loss_total,
            "loss_values_for_efficiency": dict(loss_values_for_efficiency or {}),
            "input_total": input_total,
            "output_import_targets": dict(output_import_targets or {}),
            "output_export_targets": dict(output_export_targets or {}),
            "own_use_ratios": dict(own_use_ratios or {}),
        }
    except Exception as exc:
        print(f"Failed to build process record for {process_name}: {exc}")
        _try_debug_breakpoint()
        raise


def append_process_record(process_records, record):
    """Append a process record to the list when provided."""
    try:
        if process_records is None:
            return
        process_records.append(record)
    except Exception as exc:
        print(f"Failed to append process record: {exc}")
        _try_debug_breakpoint()
        raise


def build_zero_skeleton_record(
    economy,
    sector_title,
    process_name,
    output_labels=None,
    export_base_year=None,
    export_final_year=None,
):
    """Return a zero-activity process record for sectors with no ESTO data.

    Ensures LEAP receives explicit zero rows for processes that are in scope but
    had no activity, rather than leaving stale values from a prior run untouched.
    The record carries the full branch/variable key set a genuine record would
    (zero output series per configured output fuel, inert efficiency, zero
    import/export targets) so a scenario with legitimately zero activity emits
    the same keys as scenarios with real values and scenario-coverage validation
    (SEED-010) stays symmetric. All-zero share groups resolve to 100 via the
    final writer's INIT-003 synthetic anchor, permitted because Exogenous
    Capacity is explicitly zero. The caller is responsible for printing the
    reason before calling this so the log stays informative.
    """
    base = int(export_base_year if export_base_year is not None else EXPORT_BASE_YEAR)
    final = int(export_final_year if export_final_year is not None else EXPORT_FINAL_YEAR)
    zero_by_year = {year: 0.0 for year in range(base, final + 1)}
    zero_targets = {str(label): dict(zero_by_year) for label in (output_labels or [])}
    record = build_process_record(
        economy=economy,
        sector_title=sector_title,
        process_name=process_name,
        output_values={str(label): dict(zero_by_year) for label in (output_labels or [])},
        feedstock_values={},
        # Inert placeholder for a zero-capacity process; keeps the Process
        # Efficiency key present in every scenario. Replaced by a genuine donor
        # scenario's value via borrow_zero_skeleton_measures when one exists.
        efficiency=1.0,
        auxiliary_ratios={},
        loss_values={},
        loss_total=0.0,
        output_import_targets=zero_targets,
        output_export_targets=dict(zero_targets),
    )
    record["is_zero_skeleton"] = True
    return record


def borrow_zero_skeleton_measures(
    records_by_scenario,
    donor_priority=("Reference", "Current Accounts", "Target"),
):
    """Copy inert technology measures onto zero skeletons from scenarios with data.

    A scenario can legitimately have zero activity for a process (e.g. USA Target
    hydrogen) while other scenarios carry genuine values. Shares are borrowed
    across scenarios by the final writer's canonical share completion; this
    handles the record-level measures (efficiency, auxiliary and own-use ratios)
    so a zero-capacity process shows the donor scenario's technology parameters
    instead of placeholders. With zero capacity these values are inert.
    """
    def _key(record):
        return (
            str(record.get("economy") or "").strip(),
            str(record.get("sector_title") or "").strip(),
            str(record.get("process_name") or "").strip(),
        )

    genuine_by_scenario = {}
    for scenario, records in (records_by_scenario or {}).items():
        for record in records or []:
            if not record.get("is_zero_skeleton"):
                genuine_by_scenario.setdefault(str(scenario), {})[_key(record)] = record

    borrowed = 0
    for scenario, records in (records_by_scenario or {}).items():
        for record in records or []:
            if not record.get("is_zero_skeleton"):
                continue
            for donor_scenario in donor_priority:
                if str(donor_scenario) == str(scenario):
                    continue
                donor = genuine_by_scenario.get(str(donor_scenario), {}).get(_key(record))
                if donor is None:
                    continue
                if donor.get("efficiency") is not None:
                    record["efficiency"] = donor.get("efficiency")
                    record["efficiency_scale"] = donor.get(
                        "efficiency_scale", record.get("efficiency_scale")
                    )
                record["auxiliary_ratios"] = dict(donor.get("auxiliary_ratios") or {})
                record["own_use_ratios"] = dict(donor.get("own_use_ratios") or {})
                record["borrowed_measures_from_scenario"] = str(donor_scenario)
                borrowed += 1
                break
    if borrowed:
        print(
            f"[INFO] Borrowed inert technology measures onto {borrowed} zero-skeleton "
            "record(s) from donor scenarios."
        )
    return borrowed


def select_primary_label(value_map):
    """Return the label with the largest absolute value."""
    try:
        if not value_map:
            return ""
        return max(
            value_map,
            key=lambda label: abs(summarize_numeric_value(value_map.get(label, 0), summary="sum") or 0),
        )
    except Exception as exc:
        print(f"Failed to select primary label: {exc}")
        _try_debug_breakpoint()
        raise


def build_transformation_process_table(process_records, code_to_name_mapping):
    """Return a process-level summary table for transformations."""
    try:
        rows = []
        for record in process_records:
            output_label = select_primary_label(record.get("output_values"))
            feedstock_label = select_primary_label(record.get("feedstock_values"))
            output_value = summarize_numeric_value(
                record.get("output_values", {}).get(output_label), summary="sum"
            )
            feedstock_value = summarize_numeric_value(
                record.get("feedstock_values", {}).get(feedstock_label), summary="sum"
            )
            efficiency_value = summarize_numeric_value(
                record.get("efficiency"), summary="mean"
            )
            rows.append(
                {
                    "economy": record.get("economy"),
                    "sector_title": record.get("sector_title"),
                    "process_name": record.get("process_name"),
                    "output_label": format_fuel_label(output_label, code_to_name_mapping),
                    "output_value": output_value,
                    "feedstock_label": format_fuel_label(feedstock_label, code_to_name_mapping),
                    "feedstock_value": feedstock_value,
                    "efficiency": efficiency_value,
                    "loss_total": record.get("loss_total"),
                    "auxiliary_count": len(record.get("auxiliary_ratios", {})),
                }
            )
        return pd.DataFrame(rows)
    except Exception as exc:
        print(f"Failed to build transformation process table: {exc}")
        _try_debug_breakpoint()
        raise


def build_transformation_detail_table(process_records, code_to_name_mapping):
    """Return a long-form detail table for outputs, feedstocks, and auxiliaries."""
    try:
        rows = []
        for record in process_records:
            economy = record.get("economy")
            sector_title = record.get("sector_title")
            process_name = record.get("process_name")
            if (
                INCLUDE_OUTPUT_SERIES_IN_LEAP_EXPORT
                and TRANSFORMATION_OUTPUT_VARIABLES.get("output")
            ):
                for label, value in record.get("output_values", {}).items():
                    summary_value = summarize_numeric_value(value, summary="sum")
                    rows.append(
                        {
                            "economy": economy,
                            "sector_title": sector_title,
                            "process_name": process_name,
                            "category": "output",
                            "fuel_label": label,
                            "fuel_label_display": format_fuel_label(label, code_to_name_mapping),
                            "value": summary_value,
                            "units": DEFAULT_OUTPUT_UNITS,
                            "per": "",
                        }
                    )
            if TRANSFORMATION_OUTPUT_VARIABLES.get("output_import_target"):
                for label, value in record.get("output_import_targets", {}).items():
                    summary_value = summarize_numeric_value(value, summary="sum")
                    rows.append(
                        {
                            "economy": economy,
                            "sector_title": sector_title,
                            "process_name": process_name,
                            "category": "output_import_target",
                            "fuel_label": label,
                            "fuel_label_display": format_fuel_label(label, code_to_name_mapping),
                            "value": summary_value,
                            "units": DEFAULT_OUTPUT_UNITS,
                            "per": "",
                        }
                    )
            if TRANSFORMATION_OUTPUT_VARIABLES.get("output_export_target"):
                for label, value in record.get("output_export_targets", {}).items():
                    summary_value = summarize_numeric_value(value, summary="sum")
                    rows.append(
                        {
                            "economy": economy,
                            "sector_title": sector_title,
                            "process_name": process_name,
                            "category": "output_export_target",
                            "fuel_label": label,
                            "fuel_label_display": format_fuel_label(label, code_to_name_mapping),
                            "value": summary_value,
                            "units": DEFAULT_OUTPUT_UNITS,
                            "per": "",
                        }
                    )
            if TRANSFORMATION_OUTPUT_VARIABLES.get("feedstock_share"):
                for label, value in record.get("feedstock_shares", {}).items():
                    summary_value = summarize_numeric_value(value, summary="mean")
                    rows.append(
                        {
                            "economy": economy,
                            "sector_title": sector_title,
                            "process_name": process_name,
                            "category": "feedstock_share",
                            "fuel_label": label,
                            "fuel_label_display": format_fuel_label(label, code_to_name_mapping),
                            "value": summary_value,
                            "units": DEFAULT_FEEDSTOCK_UNITS,
                            "per": "",
                        }
                    )
            if TRANSFORMATION_OUTPUT_VARIABLES.get("process_efficiency") and record.get("efficiency") is not None:
                efficiency_data = record.get("efficiency")
                if isinstance(efficiency_data, dict):
                    efficiency_data = normalize_process_efficiency_to_percent(
                        efficiency_data,
                        input_scale=record.get("efficiency_scale", "ratio"),
                    )
                efficiency_value = summarize_numeric_value(
                    efficiency_data, summary="mean"
                )
                efficiency_value = cap_process_efficiency_value(efficiency_value)
                rows.append(
                    {
                        "economy": economy,
                        "sector_title": sector_title,
                        "process_name": process_name,
                        "category": "process_efficiency",
                        "fuel_label": "",
                        "fuel_label_display": "",
                        "value": efficiency_value,
                        "units": DEFAULT_EFFICIENCY_UNITS,
                        "per": "",
                    }
                )
            if TRANSFORMATION_OUTPUT_VARIABLES.get("auxiliary_ratio"):
                for label, value in record.get("auxiliary_ratios", {}).items():
                    summary_value = summarize_numeric_value(value, summary="mean")
                    rows.append(
                        {
                            "economy": economy,
                            "sector_title": sector_title,
                            "process_name": process_name,
                            "category": "auxiliary_ratio",
                            "fuel_label": label,
                            "fuel_label_display": format_fuel_label(label, code_to_name_mapping),
                            "value": summary_value,
                            "units": DEFAULT_AUXILIARY_UNITS,
                            "per": DEFAULT_AUXILIARY_PER,
                        }
                    )
            if TRANSFORMATION_OUTPUT_VARIABLES.get("loss_value"):
                for label, value in record.get("loss_values", {}).items():
                    summary_value = summarize_numeric_value(value, summary="sum")
                    rows.append(
                        {
                            "economy": economy,
                            "sector_title": sector_title,
                            "process_name": process_name,
                            "category": "loss_value",
                            "fuel_label": label,
                            "fuel_label_display": format_fuel_label(label, code_to_name_mapping),
                            "value": summary_value,
                            "units": DEFAULT_OUTPUT_UNITS,
                            "per": "",
                        }
                    )
        return pd.DataFrame(rows)
    except Exception as exc:
        print(f"Failed to build transformation detail table: {exc}")
        _try_debug_breakpoint()
        raise


def build_branch_path(parts):
    """Return a LEAP branch path from parts."""
    try:
        cleaned_parts = [str(part).strip() for part in parts if part and str(part).strip()]
        return sanitize_leap_branch_path("\\".join(cleaned_parts))
    except Exception as exc:
        print(f"Failed to build branch path from {parts}: {exc}")
        _try_debug_breakpoint()
        raise


def _sum_series_map_by_year(value_map, years):
    """Return year totals from a fuel->(year->value) mapping."""
    try:
        totals = {int(year): 0.0 for year in years}
        if not isinstance(value_map, dict):
            return totals
        for raw_series in value_map.values():
            if isinstance(raw_series, dict):
                for year in years:
                    raw_value = raw_series.get(year, raw_series.get(str(year), 0.0))
                    if raw_value is None or pd.isna(raw_value):
                        continue
                    totals[int(year)] += abs(float(raw_value))
                continue
            if raw_series is None or pd.isna(raw_series):
                continue
            scalar_value = abs(float(raw_series))
            for year in years:
                totals[int(year)] += scalar_value
        return totals
    except Exception as exc:
        print(f"Failed to sum series map by year: {exc}")
        _try_debug_breakpoint()
        raise


def _build_process_share_lookup(
    process_records,
    code_to_name_mapping,
    base_year,
    final_year,
):
    """Return per-process share percentages by economy/sector/year."""
    try:
        years = list(range(int(base_year), int(final_year) + 1))
        process_sets = {}
        process_activity = {}
        for record in process_records or []:
            if _is_excluded_transformation_record(record):
                continue
            economy = str(record.get("economy") or "").strip()
            sector_title = map_code_label(record.get("sector_title"), code_to_name_mapping)
            process_name = map_code_label(record.get("process_name"), code_to_name_mapping)
            if not sector_title or not process_name:
                continue
            key = (economy, str(sector_title))
            process_sets.setdefault(key, set()).add(str(process_name))
            process_key = (economy, str(sector_title), str(process_name))
            output_totals = _sum_series_map_by_year(record.get("output_values"), years)
            feedstock_totals = _sum_series_map_by_year(record.get("feedstock_values"), years)
            loss_totals = _sum_series_map_by_year(record.get("loss_values"), years)
            totals = {}
            for year in years:
                # Use output-first activity as the main basis for Process Share.
                output_value = float(output_totals.get(year, 0.0))
                # Fallback to wider activity if output is unavailable in that year.
                total_activity = (
                    output_value
                    + float(feedstock_totals.get(year, 0.0))
                    + float(loss_totals.get(year, 0.0))
                )
                totals[int(year)] = (
                    output_value
                    if output_value > 0.0
                    else total_activity
                )
            process_activity[process_key] = totals

        share_lookup = {}
        usage_tolerance = 1e-12
        for (economy, sector_title), processes in process_sets.items():
            process_list = sorted(processes)
            if not process_list:
                continue
            for process_name in process_list:
                share_lookup[(economy, sector_title, process_name)] = {
                    int(year): 0.0 for year in years
                }
            for year in years:
                active_processes = []
                denominator = 0.0
                for process_name in process_list:
                    activity = process_activity.get(
                        (economy, sector_title, process_name),
                        {},
                    ).get(year, 0.0)
                    if float(activity) > usage_tolerance:
                        activity_value = float(activity)
                        active_processes.append((process_name, activity_value))
                        denominator += activity_value
                if not active_processes:
                    continue
                if denominator <= usage_tolerance:
                    continue
                for process_name, activity_value in active_processes:
                    share_value = (activity_value / denominator) * 100.0
                    share_lookup[(economy, sector_title, process_name)][int(year)] = share_value
        return share_lookup
    except Exception as exc:
        print(f"Failed to build process share lookup: {exc}")
        _try_debug_breakpoint()
        raise


def _normalize_share_percentages(raw_share_by_label, rounding_decimals=6):
    """Return rounded shares that sum to exactly 100.0."""
    try:
        if not raw_share_by_label:
            return {}
        ordered = sorted(raw_share_by_label.items(), key=lambda item: str(item[0]))
        rounded = {
            label: round(max(float(value), 0.0), int(rounding_decimals))
            for label, value in ordered
        }
        rounded_sum = round(sum(rounded.values()), int(rounding_decimals))
        residual = round(100.0 - rounded_sum, int(rounding_decimals))
        if abs(residual) > 0.0:
            target_label = sorted(
                raw_share_by_label.items(),
                key=lambda item: (-float(item[1]), str(item[0])),
            )[0][0]
            rounded[target_label] = round(
                float(rounded.get(target_label, 0.0)) + residual,
                int(rounding_decimals),
            )
        return rounded
    except Exception as exc:
        print(f"Failed to normalize share percentages: {exc}")
        _try_debug_breakpoint()
        raise


def _normalize_output_shares_for_export(output_shares, base_year, final_year):
    """Normalize genuine shares and fill gaps from the nearest genuine profile."""
    try:
        if not output_shares:
            return {}
        labels = sorted(str(label) for label in output_shares.keys() if str(label).strip())
        if not labels:
            return {}

        years = list(range(int(base_year), int(final_year) + 1))
        normalized = {label: {} for label in labels}
        value_tolerance = 1e-12
        raw_by_year = {}
        for year in years:
            raw_by_label = {}
            for label in labels:
                value_by_year = coerce_value_by_year(
                    output_shares.get(label, {}),
                    int(base_year),
                    int(final_year),
                )
                raw_value = value_by_year.get(year, value_by_year.get(str(year), 0.0))
                if raw_value is None or pd.isna(raw_value):
                    raw_value = 0.0
                raw_by_label[label] = max(float(raw_value), 0.0)
            raw_by_year[year] = raw_by_label

        genuine_profiles = {}
        for year, raw_by_label in raw_by_year.items():
            year_total = sum(raw_by_label.values())
            if year_total > value_tolerance:
                genuine_profiles[year] = _normalize_share_percentages(
                    {
                        label: raw_by_label[label] * 100.0 / year_total
                        for label in labels
                    }
                )

        # Preserve an explicit zero profile so the final canonical-group layer
        # can capacity-gate any synthetic fallback and emit every sibling.
        if not genuine_profiles:
            return {
                label: {year: 0.0 for year in years}
                for label in labels
            }

        for year in years:
            share_by_label = genuine_profiles.get(year)
            if share_by_label is None:
                nearest_year = min(genuine_profiles, key=lambda candidate: (abs(candidate - year), candidate))
                share_by_label = genuine_profiles[nearest_year]
            for label in labels:
                normalized[label][year] = float(share_by_label.get(label, 0.0))

        return normalized
    except Exception as exc:
        print(f"Failed to normalize output shares for export: {exc}")
        _try_debug_breakpoint()
        raise


def _build_output_share_lookup(
    process_records,
    code_to_name_mapping,
    base_year,
    final_year,
):
    """Return output fuel share percentages by (economy, sector, fuel, year)."""
    try:
        years = list(range(int(base_year), int(final_year) + 1))
        sector_fuels = {}
        output_totals = {}
        value_tolerance = 1e-12
        for record in process_records or []:
            if _is_excluded_transformation_record(record):
                continue
            economy = str(record.get("economy") or "").strip()
            sector_title = map_code_label(record.get("sector_title"), code_to_name_mapping)
            if not economy or not sector_title:
                continue
            sector_key = (economy, str(sector_title))
            output_values = record.get("output_values") or {}
            for label, value in output_values.items():
                fuel_label = map_code_label(label, code_to_name_mapping)
                if not fuel_label:
                    continue
                sector_fuels.setdefault(sector_key, set()).add(str(fuel_label))
                value_by_year = coerce_value_by_year(value, base_year, final_year)
                for year in years:
                    year_value = float(value_by_year.get(year, value_by_year.get(str(year), 0.0)) or 0.0)
                    year_value = max(year_value, 0.0)
                    key = (economy, str(sector_title), str(fuel_label), int(year))
                    output_totals[key] = output_totals.get(key, 0.0) + year_value

        lookup = {}
        for sector_key, fuel_set in sector_fuels.items():
            fuel_labels = sorted(fuel_set)
            if not fuel_labels:
                continue
            economy, sector_title = sector_key
            sector_bucket = lookup.setdefault((economy, sector_title), {})
            raw_by_year = {}
            for year in years:
                raw_by_year[year] = {
                    fuel_label: float(
                        output_totals.get((economy, sector_title, fuel_label, int(year)), 0.0)
                    )
                    for fuel_label in fuel_labels
                }
            genuine_profiles = {}
            for year, fuel_totals in raw_by_year.items():
                sector_total = float(sum(fuel_totals.values()))
                if sector_total > value_tolerance:
                    raw_shares = {
                        fuel_label: (fuel_totals[fuel_label] / sector_total) * 100.0
                        for fuel_label in fuel_labels
                    }
                    genuine_profiles[year] = _normalize_share_percentages(raw_shares)
            if not genuine_profiles:
                for fuel_label in fuel_labels:
                    sector_bucket[fuel_label] = {
                        int(year): 0.0 for year in years
                    }
                continue
            for year in years:
                share_by_label = genuine_profiles.get(year)
                if share_by_label is None:
                    nearest_year = min(genuine_profiles, key=lambda candidate: (abs(candidate - year), candidate))
                    share_by_label = genuine_profiles[nearest_year]
                for fuel_label in fuel_labels:
                    sector_bucket.setdefault(fuel_label, {})[int(year)] = float(
                        share_by_label.get(fuel_label, 0.0)
                    )
        return lookup
    except Exception as exc:
        print(f"Failed to build output share lookup: {exc}")
        _try_debug_breakpoint()
        raise


def build_scenario_specific_rows(
    process_records,
    scenario,
    scenario_config,
    base_year,
    final_year,
):
    """Return scenario-specific LEAP rows (hook for future custom rows)."""
    try:
        if not scenario_config or not scenario_config.get("include_current_account_rows"):
            return []
        # Placeholder for future Current Accounts-only rows. No additional rows today.
        return []
    except Exception as exc:
        print(f"Failed to build scenario-specific rows for {scenario}: {exc}")
        _try_debug_breakpoint()
        raise


def build_transformation_log_rows(
    process_records,
    scenario,
    region,
    base_year,
    final_year,
    code_to_name_mapping,
    scenario_config=None,
):
    """Return log-style rows for LEAP import from process records."""
    try:
        rows = []
        process_feedstock_labels = _build_feedstock_label_universe(process_records)
        process_share_lookup = _build_process_share_lookup(
            process_records,
            code_to_name_mapping,
            base_year,
            final_year,
        )
        output_share_lookup = _build_output_share_lookup(
            process_records,
            code_to_name_mapping,
            base_year,
            final_year,
        )
        emitted_output_share_sectors = set()
        scenario_base_year, scenario_final_year = resolve_scenario_year_range(
            base_year,
            final_year,
            scenario_config,
        )
        for record in process_records:
            if _is_excluded_transformation_record(record):
                continue
            economy = str(record.get("economy") or "").strip()
            sector_title = map_code_label(record.get("sector_title"), code_to_name_mapping)
            process_name = map_code_label(record.get("process_name"), code_to_name_mapping)
            output_values = record.get("output_values", {})
            feedstock_shares = record.get("feedstock_shares", {})
            auxiliary_ratios = record.get("auxiliary_ratios", {})
            efficiency = record.get("efficiency")
            sector_key = (economy, str(sector_title))
            if sector_key not in emitted_output_share_sectors:
                sector_output_shares = _normalize_output_shares_for_export(
                    output_share_lookup.get(sector_key, {}),
                    base_year,
                    final_year,
                )
                for fuel_label, value in sorted(sector_output_shares.items(), key=lambda item: str(item[0])):
                    branch_path = build_branch_path(
                        [
                            "Transformation",
                            sector_title,
                            "Output Fuels",
                            str(fuel_label),
                        ]
                    )
                    rows.extend(
                        build_year_rows(
                            branch_path,
                            "Output Share",
                            scenario,
                            value,
                            "Share",
                            "%",
                            "",
                        )
                    )
                emitted_output_share_sectors.add(sector_key)

            scenario_process_share = record.get("process_share_by_year")
            if isinstance(scenario_process_share, dict) and scenario_process_share:
                process_share = scenario_process_share
            else:
                process_share = process_share_lookup.get(
                    (economy, str(sector_title), str(process_name)),
                    {},
                )
            if isinstance(process_share, dict):
                process_share_by_year = clip_value_by_year_range(
                    process_share,
                    scenario_base_year,
                    scenario_final_year,
                )
            else:
                process_share_by_year = build_value_by_year(
                    process_share,
                    scenario_base_year,
                    scenario_final_year,
                )
            process_branch_path = build_branch_path(
                ["Transformation", sector_title, "Processes", str(process_name)]
            )
            rows.extend(
                build_year_rows(
                    process_branch_path,
                    "Process Share",
                    scenario,
                    process_share_by_year,
                    "Share",
                    "%",
                    "",
                )
            )

            capacity_units = str(record.get("capacity_units") or "Gigajoules/Year")
            capacity_scale = str(record.get("capacity_scale") or "")
            historical_production_by_year = record.get("historical_production_by_year")
            if isinstance(historical_production_by_year, dict) and historical_production_by_year:
                historical_values = clip_value_by_year_range(
                    historical_production_by_year,
                    scenario_base_year,
                    scenario_final_year,
                )
                rows.extend(
                    build_year_rows(
                        process_branch_path,
                        "Historical Production",
                        scenario,
                        historical_values,
                        "Petajoule",
                        "",
                        "",
                    )
                )

            exogenous_capacity_by_year = record.get("exogenous_capacity_by_year")
            if isinstance(exogenous_capacity_by_year, dict) and exogenous_capacity_by_year:
                exogenous_values = clip_value_by_year_range(
                    exogenous_capacity_by_year,
                    scenario_base_year,
                    scenario_final_year,
                )
                rows.extend(
                    build_year_rows(
                        process_branch_path,
                        "Exogenous Capacity",
                        scenario,
                        exogenous_values,
                        capacity_units,
                        capacity_scale,
                        "",
                    )
                )

            endogenous_capacity_by_year = record.get("endogenous_capacity_by_year")
            if isinstance(endogenous_capacity_by_year, dict) and endogenous_capacity_by_year:
                endogenous_values = clip_value_by_year_range(
                    endogenous_capacity_by_year,
                    scenario_base_year,
                    scenario_final_year,
                )
                rows.extend(
                    build_year_rows(
                        process_branch_path,
                        "Endogenous Capacity",
                        scenario,
                        endogenous_values,
                        capacity_units,
                        capacity_scale,
                        "",
                    )
                )

            max_availability_by_year = record.get("maximum_availability_by_year")
            if isinstance(max_availability_by_year, dict) and max_availability_by_year:
                availability_values = clip_value_by_year_range(
                    max_availability_by_year,
                    scenario_base_year,
                    scenario_final_year,
                )
                rows.extend(
                    build_year_rows(
                        process_branch_path,
                        "Maximum Availability",
                        scenario,
                        availability_values,
                        "Percent",
                        "",
                        "",
                    )
                )

            capacity_credit_by_year = record.get("capacity_credit_by_year")
            if isinstance(capacity_credit_by_year, dict) and capacity_credit_by_year:
                credit_values = clip_value_by_year_range(
                    capacity_credit_by_year,
                    scenario_base_year,
                    scenario_final_year,
                )
                rows.extend(
                    build_year_rows(
                        process_branch_path,
                        "Capacity Credit",
                        scenario,
                        credit_values,
                        "Percent",
                        "",
                        "",
                    )
                )

            if (
                INCLUDE_OUTPUT_SERIES_IN_LEAP_EXPORT
                and TRANSFORMATION_OUTPUT_VARIABLES.get("output")
            ):
                for label, value in output_values.items():
                    value_by_year = coerce_value_by_year(value, base_year, final_year)
                    value_by_year = clip_value_by_year_range(
                        value_by_year,
                        scenario_base_year,
                        scenario_final_year,
                    )
                    branch_path = build_branch_path(
                        [
                            "Transformation",
                            sector_title,
                            "Output Fuels",
                            map_code_label(label, code_to_name_mapping),
                        ]
                    )
                    rows.extend(
                        build_year_rows(
                            branch_path,
                            "Output",
                            scenario,
                            value_by_year,
                            DEFAULT_OUTPUT_UNITS,
                            "",
                            "",
                        )
                    )
            if TRANSFORMATION_OUTPUT_VARIABLES.get("output_import_target"):
                for label, value in record.get("output_import_targets", {}).items():
                    value_by_year = coerce_value_by_year(value, base_year, final_year)
                    value_by_year = clip_value_by_year_range(
                        value_by_year,
                        scenario_base_year,
                        scenario_final_year,
                    )
                    branch_path = build_branch_path(
                        [
                            "Transformation",
                            sector_title,
                            "Output Fuels",
                            map_code_label(label, code_to_name_mapping),
                        ]
                    )
                    rows.extend(
                        build_year_rows(
                            branch_path,
                            "Import Target",
                            scenario,
                            value_by_year,
                            DEFAULT_OUTPUT_UNITS,
                            "",
                            "",
                        )
                    )
            if TRANSFORMATION_OUTPUT_VARIABLES.get("output_export_target"):
                for label, value in record.get("output_export_targets", {}).items():
                    value_by_year = coerce_value_by_year(value, base_year, final_year)
                    value_by_year = clip_value_by_year_range(
                        value_by_year,
                        scenario_base_year,
                        scenario_final_year,
                    )
                    branch_path = build_branch_path(
                        [
                            "Transformation",
                            sector_title,
                            "Output Fuels",
                            map_code_label(label, code_to_name_mapping),
                        ]
                    )
                    rows.extend(
                        build_year_rows(
                            branch_path,
                            "Export Target",
                            scenario,
                            value_by_year,
                            DEFAULT_OUTPUT_UNITS,
                            "",
                            "",
                        )
                    )

            if TRANSFORMATION_OUTPUT_VARIABLES.get("process_efficiency") and efficiency is not None:
                efficiency_by_year = coerce_value_by_year(efficiency, base_year, final_year)
                efficiency_by_year = clip_value_by_year_range(
                    efficiency_by_year,
                    scenario_base_year,
                    scenario_final_year,
                )
                efficiency_by_year = normalize_process_efficiency_to_percent(
                    efficiency_by_year,
                    input_scale=record.get("efficiency_scale", "ratio"),
                )
                efficiency_by_year = cap_process_efficiency_value_by_year(efficiency_by_year)
                rows.extend(
                    build_year_rows(
                        process_branch_path,
                        "Process Efficiency",
                        scenario,
                        efficiency_by_year,
                        DEFAULT_EFFICIENCY_UNITS,
                        "",
                        "",
                    )
                )

            if TRANSFORMATION_OUTPUT_VARIABLES.get("feedstock_share"):
                process_key = (
                    str(record.get("sector_title") or "").strip(),
                    str(record.get("process_name") or "").strip(),
                )
                normalized_feedstock_shares = prepare_feedstock_shares_for_export(
                    feedstock_shares,
                    record.get("feedstock_values", {}),
                    process_feedstock_labels.get(process_key, []),
                    scenario_base_year,
                    scenario_final_year,
                )
                for label, value_by_year in normalized_feedstock_shares.items():
                    branch_path = build_branch_path(
                        [
                            "Transformation",
                            sector_title,
                            "Processes",
                            str(process_name),
                            "Feedstock Fuels",
                            map_code_label(label, code_to_name_mapping),
                        ]
                    )
                    rows.extend(
                        build_year_rows(
                            branch_path,
                            "Feedstock Fuel Share",
                            scenario,
                            value_by_year,
                            DEFAULT_FEEDSTOCK_UNITS,
                            DEFAULT_FEEDSTOCK_SCALE,
                            "",
                        )
                    )

            if TRANSFORMATION_OUTPUT_VARIABLES.get("auxiliary_ratio"):
                for label, value in auxiliary_ratios.items():
                    auxiliary_leaf = map_code_label(label, code_to_name_mapping)
                    value_by_year = coerce_value_by_year(value, base_year, final_year)
                    value_by_year = clip_value_by_year_range(
                        value_by_year,
                        scenario_base_year,
                        scenario_final_year,
                    )
                    branch_path = build_branch_path(
                        [
                            "Transformation",
                            sector_title,
                            "Processes",
                            str(process_name),
                            "Auxiliary Fuels",
                            auxiliary_leaf,
                        ]
                    )
                    rows.extend(
                        build_year_rows(
                            branch_path,
                            "Auxiliary Fuel Use",
                            scenario,
                            value_by_year,
                            DEFAULT_AUXILIARY_UNITS,
                            "",
                            DEFAULT_AUXILIARY_PER,
                        )
                    )

        rows.extend(
            build_scenario_specific_rows(
                process_records,
                scenario,
                scenario_config,
                scenario_base_year,
                scenario_final_year,
            )
        )
        return rows
    except Exception as exc:
        print(f"Failed to build transformation log rows: {exc}")
        _try_debug_breakpoint()
        raise


def build_data_expression(row, year_cols):
    """Return a LEAP Data(...) expression from year columns."""
    try:
        scenario_name = str(row.get("Scenario", "")).strip().lower()
        is_current_accounts = scenario_name in {"current accounts", "current account"}
        parts = []
        for year in year_cols:
            value = row.get(year)
            if value is None or pd.isna(value):
                continue
            parts.append(f"{int(year)},{float(value)}")
        if is_current_accounts and not parts:
            fallback_year = int(year_cols[0]) if year_cols else int(EXPORT_BASE_YEAR)
            parts.append(f"{fallback_year},0.0")
        if not is_current_accounts and not parts:
            fallback_year = int(year_cols[0]) if year_cols else int(EXPORT_BASE_YEAR)
            parts.append(f"{fallback_year},0.0")
        return f"Data({', '.join(parts)})"
    except Exception as exc:
        print(f"Failed to build Data expression: {exc}")
        _try_debug_breakpoint()
        raise


def build_expression_export_df(export_df):
    """Return a LEAP sheet df with Expression and no year columns."""
    try:
        year_cols = sorted([col for col in export_df.columns if str(col).isdigit()])
        expression_df = export_df.copy()
        expression_df["Expression"] = expression_df.apply(
            lambda row: build_data_expression(row, year_cols),
            axis=1,
        )
        expression_df = expression_df.drop(columns=year_cols)
        base_cols = ["Branch Path", "Variable", "Scenario", "Region", "Scale", "Units", "Per...", "Expression"]
        level_cols = [col for col in expression_df.columns if col.startswith("Level ")]
        expression_df = expression_df[base_cols + level_cols]
        return expression_df
    except Exception as exc:
        print(f"Failed to build expression export df: {exc}")
        _try_debug_breakpoint()
        raise


def build_export_from_log_rows(log_rows, scenario_label, region, base_year, final_year):
    """Finalize a log row list into LEAP export/log DataFrames."""
    try:
        log_df = pd.DataFrame(log_rows)
        export_df = finalise_export_df(log_df, scenario_label, region, base_year, final_year)
        return export_df, log_df
    except Exception as exc:
        print(f"Failed to build export from log rows: {exc}")
        _try_debug_breakpoint()
        raise


def save_transformation_summaries(
    process_records,
    code_to_name_mapping,
    output_dir,
    process_filename,
    detail_filename,
):
    """Save transformation summary tables to CSV."""
    try:
        if not process_records:
            print("No process records available for summary tables.")
            return None, None
        process_summary = build_transformation_process_table(
            process_records,
            code_to_name_mapping,
        )
        detail_summary = build_transformation_detail_table(
            process_records,
            code_to_name_mapping,
        )
        os.makedirs(output_dir, exist_ok=True)
        process_summary_path = os.path.join(output_dir, process_filename)
        detail_summary_path = os.path.join(output_dir, detail_filename)
        process_summary.to_csv(process_summary_path, index=False)
        detail_summary.to_csv(detail_summary_path, index=False)
        print(f"Saved transformation process summary to {process_summary_path}")
        print(f"Saved transformation detail summary to {detail_summary_path}")
        return process_summary, detail_summary
    except Exception as exc:
        print(f"Failed to save transformation summary tables: {exc}")
        _try_debug_breakpoint()
        raise


def _sum_year_dicts(series_list):
    """Sum year->value dicts, aligning years."""
    totals = {}
    for series in series_list:
        if not series:
            continue
        for year, value in series.items():
            if value is None or pd.isna(value):
                continue
            year_int = int(year)
            totals[year_int] = totals.get(year_int, 0.0) + float(value)
    return totals


def consolidate_transformation_output_rows(
    process_records,
    include_output_series=False,
    use_output_targets=False,
):
    """Aggregate output values/targets to avoid duplicate LEAP rows."""
    if not process_records or not (include_output_series or use_output_targets):
        return
    grouped = {}
    for record in process_records:
        key = (record.get("economy"), record.get("sector_title"))
        grouped.setdefault(key, []).append(record)
    for records in grouped.values():
        if len(records) < 2:
            continue
        output_values_by_label = {}
        import_targets_by_label = {}
        export_targets_by_label = {}
        for record in records:
            for label, values in (record.get("output_values") or {}).items():
                output_values_by_label.setdefault(label, []).append(values)
            for label, values in (record.get("output_import_targets") or {}).items():
                import_targets_by_label.setdefault(label, []).append(values)
            for label, values in (record.get("output_export_targets") or {}).items():
                export_targets_by_label.setdefault(label, []).append(values)
        aggregated_outputs = {
            label: _sum_year_dicts(values)
            for label, values in output_values_by_label.items()
            if values
        }
        aggregated_imports = {
            label: _sum_year_dicts(values)
            for label, values in import_targets_by_label.items()
            if values
        }
        aggregated_exports = {
            label: _sum_year_dicts(values)
            for label, values in export_targets_by_label.items()
            if values
        }
        carrier = records[0]
        if include_output_series:
            carrier["output_values"] = aggregated_outputs
        if use_output_targets:
            carrier["output_import_targets"] = aggregated_imports
            carrier["output_export_targets"] = aggregated_exports
        for record in records[1:]:
            if include_output_series:
                record["output_values"] = {}
            if use_output_targets:
                record["output_import_targets"] = {}
                record["output_export_targets"] = {}


def build_aux_fuel_zero_rows(
    existing_rows,
    full_branch_catalog_df,
    scenarios,
    base_year,
    final_year,
    in_scope_sector_titles: set[str] | None = None,
):
    """
    Return zero-value rows for any catalog fuel branches not already set.

    Covers Auxiliary Fuels (Auxiliary Fuel Use) and Feedstock Fuels (Feedstock Fuel Share).

    Two tiers of zero-fill:

    1. Measure-specific process prefixes (derived from existing_rows): only branches under
       processes where we actually wrote that specific measure this run.  Feedstock Fuel Share
       zero-fill also applies the 100.0 fallback so LEAP doesn't reject an all-zero process.
       Data written by other researchers is never touched here.

    2. In-scope sector titles (from in_scope_sector_titles): sectors this workflow is
       responsible for but where some or all economies had no ESTO data (so no process records
       were produced).  All catalog branches under these sectors that weren't written in tier 1
       are cleared to 0.  No 100.0 fallback here — we have no data to anchor a share.

    NOTE (part-2 limitation): On re-runs after a LEAP model solve, auxiliary fuel use
    values are reported by LEAP as transformation inputs in the energy balance, not as
    separate own-use rows.  There is currently no reliable way to extract them back out
    and feed them into the ESTO-based auxiliary ratio calculation for the next iteration.
    This is a known gap — the auxiliary ratios used here always derive from ESTO loss data
    regardless of what LEAP reports.
    """
    if full_branch_catalog_df is None or (
        hasattr(full_branch_catalog_df, "empty") and full_branch_catalog_df.empty
    ):
        return []

    # Derive allowed process branch prefixes per measure from rows already written this run.
    # A branch path containing "\Processes\" gives us the process prefix up to and
    # including the process name, e.g. "Transformation\LNG\Processes\Liquefaction".
    # We use measure-specific sets so that, e.g., writing Process Share for a sector
    # does NOT entitle us to zero-fill that sector's Feedstock Fuel Share branches —
    # only processes for which we actually wrote Feedstock Fuel Share rows are touched.
    _processes_marker = "\\Processes\\"

    def _extract_process_prefix(bp: str) -> str | None:
        idx = bp.find(_processes_marker)
        if idx == -1:
            return None
        after_marker = idx + len(_processes_marker)
        next_sep = bp.find("\\", after_marker)
        return bp[:next_sep] if next_sep != -1 else bp

    # measure_name → set of process prefixes we wrote rows for
    allowed_prefixes_by_measure: dict[str, set[str]] = {}
    for row in existing_rows:
        measure = str(row.get("Measure", "")).strip()
        bp = str(row.get("Branch_Path", "")).strip()
        prefix = _extract_process_prefix(bp)
        if prefix:
            allowed_prefixes_by_measure.setdefault(measure, set()).add(prefix)

    # Map fuel_group label → (LEAP variable name, units, scale, per)
    fuel_group_spec = {
        "Auxiliary Fuels": ("Auxiliary Fuel Use", DEFAULT_AUXILIARY_UNITS, "", DEFAULT_AUXILIARY_PER),
        "Feedstock Fuels": ("Feedstock Fuel Share", DEFAULT_FEEDSTOCK_UNITS, DEFAULT_FEEDSTOCK_SCALE, ""),
    }

    # Collect (measure, scenario, branch_path) triples already written.
    existing: set[tuple[str, str, str]] = set()
    for row in existing_rows:
        existing.add((
            str(row.get("Measure", "")).strip(),
            str(row.get("Scenario", "")),
            str(row.get("Branch_Path", "")),
        ))

    zero_rows = []

    def _years_for_scenario(scenario_name):
        scenario_config = get_scenario_export_config(
            scenario_name,
            default_base_year=base_year,
            default_final_year=final_year,
        )
        scenario_start, scenario_end = resolve_scenario_year_range(
            base_year,
            final_year,
            scenario_config,
        )
        scenario_text = str(scenario_name or "").strip().lower()
        if scenario_text not in {"current accounts", "current account"}:
            scenario_start = max(int(scenario_start), int(base_year) + 1)
        return list(range(int(scenario_start), int(scenario_end) + 1))

    for group, (measure, units, scale, per) in fuel_group_spec.items():
        # Only operate on processes where we actually wrote this specific measure.
        # This prevents zeroing feedstock branches for sectors where we only wrote
        # Process Share / Efficiency, and avoids touching any data set by others.
        allowed_prefixes = allowed_prefixes_by_measure.get(measure, set())
        if not allowed_prefixes:
            continue

        group_catalog = full_branch_catalog_df[
            full_branch_catalog_df["fuel_group"].astype(str).str.strip() == group
        ]
        if group_catalog.empty:
            continue

        is_feedstock = measure == "Feedstock Fuel Share"

        # Pre-compute which process prefixes have at least one written row for this measure,
        # keyed by (scenario). This catches branches written but absent from the catalog
        # (e.g. Lignite for BKB when only Other bituminous coal is in the catalog), so
        # those processes are not incorrectly treated as having no written rows.
        written_prefixes_by_scenario: dict[str, set[str]] = {}
        for ex_m, ex_sc, ex_bp in existing:
            if ex_m != measure:
                continue
            ex_prefix = _extract_process_prefix(ex_bp)
            if ex_prefix:
                written_prefixes_by_scenario.setdefault(ex_sc, set()).add(ex_prefix)

        for scenario in scenarios:
            years = _years_for_scenario(scenario)
            # process_prefix → list of (branch_path, is_already_set) — for feedstock grouping
            process_branch_map: dict[str, list[tuple[str, bool]]] = {}

            for _, catalog_row in group_catalog.iterrows():
                branch_path = str(catalog_row.get("branch_path", "")).strip()
                if not branch_path:
                    continue
                matched_prefix = next(
                    (p for p in allowed_prefixes if branch_path.startswith(p + "\\")),
                    None,
                )
                if matched_prefix is None:
                    continue
                already_set = (measure, scenario, branch_path) in existing
                if is_feedstock:
                    process_branch_map.setdefault(matched_prefix, []).append(
                        (branch_path, already_set)
                    )
                elif not already_set:
                    for year in years:
                        zero_rows.append(
                            {
                                "Branch_Path": branch_path,
                                "Scenario": scenario,
                                "Measure": measure,
                                "Units": units,
                                "Scale": scale,
                                "Per...": per,
                                "Date": year,
                                "Value": 0.0,
                            }
                        )

            if is_feedstock:
                for prefix, branches in process_branch_map.items():
                    # any_already_set is True when at least one catalog branch was written
                    # OR when any row for this process prefix was written (even branches
                    # absent from the catalog — e.g. Lignite for BKB when only Other
                    # bituminous coal is catalogued). Without the second check, the first
                    # catalog branch incorrectly receives the 100.0 anchor.
                    any_already_set = (
                        any(already_set for _, already_set in branches)
                        or prefix in written_prefixes_by_scenario.get(scenario, set())
                    )
                    first_unset = True
                    for branch_path, already_set in branches:
                        if already_set:
                            continue
                        if not any_already_set and first_unset:
                            value = 100.0
                            first_unset = False
                        else:
                            value = 0.0
                        for year in years:
                            zero_rows.append(
                                {
                                    "Branch_Path": branch_path,
                                    "Scenario": scenario,
                                    "Measure": measure,
                                    "Units": units,
                                    "Scale": scale,
                                    "Per...": per,
                                    "Date": year,
                                    "Value": value,
                                }
                            )

    # Tier-2: clear branches for in-scope sectors where we had no data this run.
    # These are sectors this workflow owns but produced no process records for.
    # All catalog branches under them that weren't already handled in tier 1 are zeroed,
    # except Feedstock Fuel Share which gets the same 100.0 anchor as tier 1 so LEAP
    # doesn't reject an all-zero process.
    if in_scope_sector_titles:
        for group, (measure, units, scale, per) in fuel_group_spec.items():
            group_catalog = full_branch_catalog_df[
                full_branch_catalog_df["fuel_group"].astype(str).str.strip() == group
            ]
            if group_catalog.empty:
                continue
            tier1_prefixes = allowed_prefixes_by_measure.get(measure, set())
            is_feedstock = measure == "Feedstock Fuel Share"
            for scenario in scenarios:
                years = _years_for_scenario(scenario)
                # For feedstock, group by process prefix so we can anchor the first branch
                # at 100.0.  For non-feedstock, collect directly for zeroing.
                tier2_process_map: dict[str, list[str]] = {}
                for _, catalog_row in group_catalog.iterrows():
                    branch_path = str(catalog_row.get("branch_path", "")).strip()
                    if not branch_path:
                        continue
                    # Skip if already handled by tier 1 (under a process we wrote).
                    if any(branch_path.startswith(p + "\\") for p in tier1_prefixes):
                        continue
                    # Skip if already explicitly set this run.
                    if (measure, scenario, branch_path) in existing:
                        continue
                    # Check if this branch is under an in-scope sector.
                    under_in_scope = any(
                        branch_path.startswith("Transformation\\" + title + "\\")
                        for title in in_scope_sector_titles
                    )
                    if not under_in_scope:
                        continue
                    if is_feedstock:
                        prefix = _extract_process_prefix(branch_path)
                        if prefix:
                            tier2_process_map.setdefault(prefix, []).append(branch_path)
                            continue
                    for year in years:
                        zero_rows.append(
                            {
                                "Branch_Path": branch_path,
                                "Scenario": scenario,
                                "Measure": measure,
                                "Units": units,
                                "Scale": scale,
                                "Per...": per,
                                "Date": year,
                                "Value": 0.0,
                            }
                        )

                if is_feedstock:
                    for prefix, branches in tier2_process_map.items():
                        for i, branch_path in enumerate(branches):
                            value = 100.0 if i == 0 else 0.0
                            for year in years:
                                zero_rows.append(
                                    {
                                        "Branch_Path": branch_path,
                                        "Scenario": scenario,
                                        "Measure": measure,
                                        "Units": units,
                                        "Scale": scale,
                                        "Per...": per,
                                        "Date": year,
                                        "Value": value,
                                    }
                                )

        # Tier-2 extension: zero process-level variables (Historical Production,
        # Exogenous Capacity) and output-fuel targets (Import Target, Export Target)
        # for in-scope sectors that had no data this run.
        #
        # "Had data" means tier-1 wrote Feedstock Fuel Share or Auxiliary Fuel Use
        # rows for that sector's processes.  We identify those sectors by extracting
        # the sector name (path level 2) from every tier-1 process prefix so we can
        # exclude them here and avoid overwriting rows already emitted for active modules.
        sectors_with_tier1_data: set[str] = set()
        for pfx_set in allowed_prefixes_by_measure.values():
            for pfx in pfx_set:
                parts = pfx.split("\\")
                if len(parts) >= 2:
                    sectors_with_tier1_data.add(parts[1])

        # Collect unique process branch prefixes (derived from Feedstock/Auxiliary
        # catalog entries via _extract_process_prefix) and output-fuel branch paths
        # (from Output Fuels catalog entries) for zero-data in-scope sectors.
        tier2_ext_process_prefixes: set[str] = set()
        tier2_ext_output_fuel_paths: set[str] = set()

        for _, catalog_row in full_branch_catalog_df.iterrows():
            bp = str(catalog_row.get("branch_path", "")).strip()
            fg = str(catalog_row.get("fuel_group", "")).strip()
            if not bp:
                continue
            bp_parts = bp.split("\\")
            bp_sector = bp_parts[1] if len(bp_parts) >= 2 else ""
            if not any(
                bp.startswith("Transformation\\" + title + "\\")
                for title in in_scope_sector_titles
            ):
                continue
            if bp_sector in sectors_with_tier1_data:
                continue
            if fg in ("Feedstock Fuels", "Auxiliary Fuels"):
                prefix = _extract_process_prefix(bp)
                if prefix:
                    tier2_ext_process_prefixes.add(prefix)
            elif fg == "Output Fuels":
                tier2_ext_output_fuel_paths.add(bp)

        # Process-level zero rows: Historical Production and Exogenous Capacity.
        # Explicit zeros tell LEAP this module had no output/capacity rather than
        # inheriting stale values from a prior import.
        process_level_spec = [
            ("Historical Production", "Petajoule", "", ""),
            ("Exogenous Capacity", "Gigajoules/Year", "", ""),
        ]
        for process_prefix in sorted(tier2_ext_process_prefixes):
            for scenario in scenarios:
                years = _years_for_scenario(scenario)
                for p_measure, p_units, p_scale, p_per in process_level_spec:
                    if (p_measure, scenario, process_prefix) not in existing:
                        for year in years:
                            zero_rows.append(
                                {
                                    "Branch_Path": process_prefix,
                                    "Scenario": scenario,
                                    "Measure": p_measure,
                                    "Units": p_units,
                                    "Scale": p_scale,
                                    "Per...": p_per,
                                    "Date": year,
                                    "Value": 0.0,
                                }
                            )

        # Output-fuel target zero rows: Import Target and Export Target.
        output_fuel_measure_spec = [
            ("Import Target", DEFAULT_OUTPUT_UNITS, "", ""),
            ("Export Target", DEFAULT_OUTPUT_UNITS, "", ""),
        ]
        for of_path in sorted(tier2_ext_output_fuel_paths):
            for scenario in scenarios:
                years = _years_for_scenario(scenario)
                for of_measure, of_units, of_scale, of_per in output_fuel_measure_spec:
                    if (of_measure, scenario, of_path) not in existing:
                        for year in years:
                            zero_rows.append(
                                {
                                    "Branch_Path": of_path,
                                    "Scenario": scenario,
                                    "Measure": of_measure,
                                    "Units": of_units,
                                    "Scale": of_scale,
                                    "Per...": of_per,
                                    "Date": year,
                                    "Value": 0.0,
                                }
                            )

    # Tier-1 extension: zero Output Share for catalog fuels not set this run,
    # under sectors where we did write at least one Output Share row.
    # This clears stale non-zero shares (e.g. kerosene at 0.1 left over in LEAP)
    # for fuels the ESTO data shows as zero output.
    output_share_measure = "Output Share"
    output_share_sectors: set[str] = set()
    for ex_m, _ex_sc, ex_bp in existing:
        if ex_m != output_share_measure:
            continue
        bp_parts = ex_bp.split("\\")
        if len(bp_parts) >= 2:
            output_share_sectors.add(bp_parts[1])

    if output_share_sectors:
        output_fuels_catalog = full_branch_catalog_df[
            full_branch_catalog_df["fuel_group"].astype(str).str.strip() == "Output Fuels"
        ]
        for scenario in scenarios:
            years = _years_for_scenario(scenario)
            for _, catalog_row in output_fuels_catalog.iterrows():
                bp = str(catalog_row.get("branch_path", "")).strip()
                if not bp:
                    continue
                bp_parts = bp.split("\\")
                sector = bp_parts[1] if len(bp_parts) >= 2 else ""
                if sector not in output_share_sectors:
                    continue
                if (output_share_measure, scenario, bp) in existing:
                    continue
                for year in years:
                    zero_rows.append(
                        {
                            "Branch_Path": bp,
                            "Scenario": scenario,
                            "Measure": output_share_measure,
                            "Units": "%",
                            "Scale": "Share",
                            "Per...": "",
                            "Date": year,
                            "Value": 0.0,
                        }
                    )

    return zero_rows


def save_transformation_export(
    process_records,
    region,
    base_year,
    final_year,
    code_to_name_mapping,
    output_dir,
    output_filename,
    model_name,
    scenarios,
    full_branch_catalog_df=None,
    in_scope_sector_titles: set[str] | None = None,
):
    """Save a LEAP import file built from process records across scenarios."""
    try:
        can_build_catalog_zero_skeleton = (
            full_branch_catalog_df is not None
            and not full_branch_catalog_df.empty
            and bool(in_scope_sector_titles)
        )
        if not process_records and not can_build_catalog_zero_skeleton:
            print("No process records available for LEAP export.")
            return None
        if not process_records:
            print(
                "No process records available; building a canonical zero skeleton "
                "from the full-model branch catalog."
            )
        scenario_configs = {
            scenario: get_scenario_export_config(
                scenario,
                default_base_year=base_year,
                default_final_year=final_year,
            )
            for scenario in scenarios
        }
        combined_base_year, combined_final_year = compute_combined_year_range(
            base_year, final_year, scenario_configs
        )
        combined_rows = []
        for scenario in scenarios:
            scenario_config = scenario_configs.get(scenario, {})
            combined_rows.extend(
                build_transformation_log_rows(
                    process_records,
                    scenario,
                    region,
                    combined_base_year,
                    combined_final_year,
                    code_to_name_mapping,
                    scenario_config=scenario_config,
                )
            )
        if full_branch_catalog_df is not None:
            zero_rows = build_aux_fuel_zero_rows(
                combined_rows,
                full_branch_catalog_df,
                scenarios,
                combined_base_year,
                combined_final_year,
                in_scope_sector_titles=in_scope_sector_titles,
            )
            if zero_rows:
                combined_rows = zero_rows + combined_rows
        if not combined_rows:
            print("No log rows generated across scenarios; skipping export.")
            return None
        scenario_label = ", ".join(scenarios)
        export_df, log_df = build_export_from_log_rows(
            combined_rows,
            scenario_label,
            region,
            combined_base_year,
            combined_final_year,
        )
        if export_df is None:
            print("No export dataframe created for LEAP export.")
            return None
        leap_expression_df = build_expression_export_df(export_df)
        os.makedirs(output_dir, exist_ok=True)
        export_path = os.path.join(output_dir, output_filename)
        save_export_files(
            leap_expression_df,
            export_df,
            export_path,
            combined_base_year,
            combined_final_year,
            model_name,
        )
        return export_path
    except Exception as exc:
        print(f"Failed to save transformation LEAP export: {exc}")
        _try_debug_breakpoint()
        raise


def print_leap_structure_block(
    title,
    output_fuels,
    process_name,
    feedstock_fuels,
    auxiliary_fuels,
    loss_fuels=None,
    code_to_name_mapping=None,
    output_fuel_values=None,
    process_value=None,
    feedstock_fuel_values=None,
    auxiliary_fuel_values=None,
    loss_fuel_values=None,
    other_feedstock_fuels=None,
    other_feedstock_values=None,
    other_feedstock_ratios=None,
):
    """Print a LEAP-structure outline for a transformation process."""
    try:
        output_pairs = [
            (label, format_fuel_label(label, code_to_name_mapping)) for label in output_fuels
        ]
        feedstock_pairs = [
            (label, format_fuel_label(label, code_to_name_mapping)) for label in feedstock_fuels
        ]
        auxiliary_pairs = [
            (label, format_fuel_label(label, code_to_name_mapping)) for label in auxiliary_fuels
        ]
        loss_pairs = [
            (label, format_fuel_label(label, code_to_name_mapping))
            for label in (loss_fuels or [])
        ]
        process_name = map_code_label(process_name, code_to_name_mapping)

        print_leap_structure_header(title)
        print("Output fuels (export target, import target):")
        for raw_label, fuel in output_pairs:
            fuel_value = ""
            if output_fuel_values is not None:
                fuel_value = format_value(output_fuel_values.get(raw_label))
            print(f"  - {fuel}" + (f" {fuel_value}" if fuel_value else ""))
        print("Processes (process efficiency):")
        process_value_text = ""
        if process_value is not None:
            process_value_text = f" {format_value(process_value)}"
        print(f"  - {process_name}:{process_value_text}")
        if feedstock_fuels:
            print("      Feedstock fuels:")
            for raw_label, fuel in feedstock_pairs:
                fuel_value = ""
                if feedstock_fuel_values is not None:
                    fuel_value = format_value(feedstock_fuel_values.get(raw_label))
                print(f"        - {fuel}" + (f" {fuel_value}" if fuel_value else ""))
        if auxiliary_fuels:
            print("      Auxiliary fuels (Aux fuel use pj/pj output):")
            for raw_label, fuel in auxiliary_pairs:
                fuel_value = ""
                if auxiliary_fuel_values is not None:
                    fuel_value = format_value(auxiliary_fuel_values.get(raw_label))
                print(f"        - {fuel}" + (f" {fuel_value}" if fuel_value else ""))
        if other_feedstock_fuels:
            other_feedstock_pairs = [
                (label, format_fuel_label(label, code_to_name_mapping))
                for label in other_feedstock_fuels
            ]
            total_other_feedstock = 0.0
            if other_feedstock_values:
                total_other_feedstock = sum(
                    value for value in other_feedstock_values.values() if value is not None
                )
            total_text = f" (total {format_value(total_other_feedstock)})"
            print(
                "      Other feedstock fuels (set as aux fuel use)"
                + total_text
                + ":"
            )
            for raw_label, fuel in other_feedstock_pairs:
                fuel_value = ""
                fuel_ratio = ""
                if other_feedstock_values is not None:
                    fuel_value = format_value(other_feedstock_values.get(raw_label))
                if other_feedstock_ratios is not None:
                    fuel_ratio = format_value(other_feedstock_ratios.get(raw_label))
                value_text = f" {fuel_value}" if fuel_value else ""
                ratio_text = f" ({fuel_ratio} pj/pj)" if fuel_ratio else ""
                print(f"        - {fuel}" + value_text + ratio_text)
        if loss_pairs:
            print("      Own use and losses (PJ):")
            for raw_label, fuel in loss_pairs:
                fuel_value = ""
                if loss_fuel_values is not None:
                    fuel_value = format_value(loss_fuel_values.get(raw_label))
                print(f"        - {fuel}" + (f" {fuel_value}" if fuel_value else ""))
        print("")
    except Exception as exc:
        print(f"Failed to print LEAP structure block: {exc}")
        _try_debug_breakpoint()
        raise

