"""Pure computation helpers for the transfers workflow.

Functions here have no file I/O, no LEAP API calls, and no writes to
module-level globals.  They are imported by ``codebase/transfers_workflow.py``
which owns all configuration constants and orchestration logic.
"""
from __future__ import annotations

from typing import Iterable, Sequence

import pandas as pd

from codebase.functions import transformation_analysis_utils as core


# ---------------------------------------------------------------------------
# Basic series helpers
# ---------------------------------------------------------------------------

def _sum_series(series_list: Iterable[pd.Series]) -> pd.Series:
    """Sum a list of pandas Series, aligning indices and filling missing with 0."""
    total = None
    for series in series_list:
        if series is None or series.empty:
            continue
        total = series if total is None else total.add(series, fill_value=0.0)
    return total if total is not None else pd.Series(dtype=float)


def _flow_has_nonzero(flow_rows: pd.DataFrame, year_cols: list[int]) -> bool:
    """Return True if any nonzero value exists in the flow rows."""
    if flow_rows.empty:
        return False
    return (flow_rows[year_cols] != 0).any().any()


def _combine_flow_rows(
    data: pd.DataFrame, economy: str, flow_codes: Iterable[str]
) -> pd.DataFrame:
    """Return concatenated rows for the requested flows."""
    frames = [
        core.select_flow_rows(data, economy, flow_code) for flow_code in flow_codes
    ]
    frames = [frame for frame in frames if frame is not None and not frame.empty]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# Label / IO resolution helpers
# ---------------------------------------------------------------------------

def _resolve_transfer_io_labels(
    process_config: dict,
    totals: pd.Series,
) -> tuple[list[str], list[str]]:
    """Assign labels to inputs/outputs based on sign in totals."""
    label_keys = ("inputs", "outputs", "products", "fuels", "labels")
    labels: list[str] = []
    for key in label_keys:
        values = process_config.get(key, [])
        if not values:
            continue
        for value in values:
            label = str(value).strip()
            if label:
                labels.append(label)
    if not labels:
        return [], []
    seen = set()
    unique_labels = [label for label in labels if not (label in seen or seen.add(label))]
    inputs = [label for label in unique_labels if totals.get(label, 0.0) < 0]
    outputs = [label for label in unique_labels if totals.get(label, 0.0) > 0]
    return inputs, outputs


# ---------------------------------------------------------------------------
# Template-based process building
# ---------------------------------------------------------------------------

def _template_processes_cover_all(
    totals: pd.Series,
    processes: list[dict],
) -> bool:
    """Return True if template processes cover all nonzero inputs/outputs."""
    if not processes:
        return False
    nonzero_inputs = {label for label, value in totals.items() if value < 0}
    nonzero_outputs = {label for label, value in totals.items() if value > 0}
    covered_inputs: set[str] = set()
    covered_outputs: set[str] = set()
    for process in processes:
        covered_inputs.update(process.get("inputs", []))
        covered_outputs.update(process.get("outputs", []))
    return nonzero_inputs.issubset(covered_inputs) and nonzero_outputs.issubset(covered_outputs)


# ---------------------------------------------------------------------------
# Process record building
# ---------------------------------------------------------------------------

def _build_process_records_for_mapping(
    flow_rows: pd.DataFrame,
    year_cols: list[int],
    start_year: int,
    economy: str,
    flow_code: str,
    process_config: dict,
    sector_title: str,
    normalize_process_name_fn,
    use_output_targets: bool = False,
    feedstock_method: str | None = None,
) -> list[dict]:
    """Build process records for a configured transfer mapping.

    ``normalize_process_name_fn`` is passed in by the workflow to avoid
    importing the workflow-level ``TRANSFER_PROCESS_NAMES`` constant here.
    """
    method = core.resolve_feedstock_method(feedstock_method)
    timeseries, _ = core.summarize_fuel_timeseries(
        flow_rows, year_cols, start_year, allow_all_years_fallback=True
    )
    totals, _ = core.summarize_fuel_totals(
        flow_rows, year_cols, start_year, allow_all_years_fallback=True
    )
    input_labels, output_labels = _resolve_transfer_io_labels(process_config, totals)
    if not input_labels or not output_labels:
        return []

    output_series_map = {
        label: core.ensure_full_year_series(
            core.get_label_timeseries(timeseries, label),
            core.EXPORT_BASE_YEAR,
            core.EXPORT_FINAL_YEAR,
        )
        for label in output_labels
    }
    input_series_map = {
        label: core.ensure_full_year_series(
            core.get_label_timeseries(timeseries, label).abs(),
            core.EXPORT_BASE_YEAR,
            core.EXPORT_FINAL_YEAR,
        )
        for label in input_labels
    }
    total_output = _sum_series(output_series_map.values())
    total_input = _sum_series(input_series_map.values())

    if total_output.empty or total_input.empty:
        return []

    output_import_targets: dict = {}
    output_export_targets: dict = {}
    if use_output_targets:
        output_import_targets, output_export_targets = core.gather_output_target_dicts(
            economy,
            list(output_series_map.keys()),
            core.EXPORT_BASE_YEAR,
            core.EXPORT_FINAL_YEAR,
            output_series_by_fuel=output_series_map,
        )
        zero_target = core.build_value_by_year(0.0, core.EXPORT_BASE_YEAR, core.EXPORT_FINAL_YEAR)
        for label in output_series_map.keys():
            if label not in output_import_targets:
                output_import_targets[label] = dict(zero_target)
            if label not in output_export_targets:
                output_export_targets[label] = dict(zero_target)

    process_name = normalize_process_name_fn(process_config, flow_code)

    if method == core.FEEDSTOCK_METHOD_SPLIT:
        feedstock_labels = list(input_series_map.keys())
        records: list[dict] = []
        for idx, feedstock_label in enumerate(feedstock_labels):
            input_series = input_series_map[feedstock_label]
            share_series = core.build_input_share_series(
                input_series,
                total_input,
                fallback_to_one=(idx == 0),
            )
            allocated_outputs = {
                label: series.mul(share_series, fill_value=0.0)
                for label, series in output_series_map.items()
            }
            allocated_output_total = _sum_series(allocated_outputs.values())
            efficiency_series = core.safe_divide_series(
                allocated_output_total,
                input_series,
            )
            output_values = {
                label: core.series_to_year_dict(series, core.EXPORT_BASE_YEAR, core.EXPORT_FINAL_YEAR)
                for label, series in allocated_outputs.items()
            }
            output_import_targets_split = {
                label: core.scale_year_dict_by_share(values, share_series)
                for label, values in (output_import_targets or {}).items()
            }
            output_export_targets_split = {
                label: core.scale_year_dict_by_share(values, share_series)
                for label, values in (output_export_targets or {}).items()
            }
            process_label = (
                process_name
                if len(feedstock_labels) == 1
                else f"{process_name} - {feedstock_label}"
            )
            records.append(
                core.build_process_record(
                    economy,
                    sector_title,
                    process_label,
                    output_values,
                    {
                        feedstock_label: core.series_to_year_dict(
                            input_series, core.EXPORT_BASE_YEAR, core.EXPORT_FINAL_YEAR
                        )
                    },
                    core.series_to_year_dict(
                        efficiency_series, core.EXPORT_BASE_YEAR, core.EXPORT_FINAL_YEAR
                    ),
                    auxiliary_ratios={},
                    loss_values={},
                    loss_total=0.0,
                    feedstock_shares={feedstock_label: 1.0},
                    input_total=float(input_series.sum()),
                    output_import_targets=output_import_targets_split,
                    output_export_targets=output_export_targets_split,
                )
            )
        return records

    if method == core.FEEDSTOCK_METHOD_MULTI:
        efficiency_series = core.safe_divide_series(total_output, total_input)
        feedstock_shares = {
            label: core.safe_divide_series(series, total_input).to_dict()
            for label, series in input_series_map.items()
        }
        feedstock_values = {
            label: core.series_to_year_dict(series, core.EXPORT_BASE_YEAR, core.EXPORT_FINAL_YEAR)
            for label, series in input_series_map.items()
        }
        output_values = {
            label: core.series_to_year_dict(series, core.EXPORT_BASE_YEAR, core.EXPORT_FINAL_YEAR)
            for label, series in output_series_map.items()
        }
        record = core.build_process_record(
            economy,
            sector_title,
            process_name,
            output_values,
            feedstock_values,
            core.series_to_year_dict(
                efficiency_series, core.EXPORT_BASE_YEAR, core.EXPORT_FINAL_YEAR
            ),
            auxiliary_ratios={},
            loss_values={},
            loss_total=0.0,
            feedstock_shares=feedstock_shares,
            input_total=total_input.sum(),
            output_import_targets=output_import_targets,
            output_export_targets=output_export_targets,
        )
        return [record]

    primary_input = max(input_series_map, key=lambda label: input_series_map[label].sum())
    primary_series = input_series_map[primary_input]
    other_feedstocks = [label for label in input_series_map if label != primary_input]
    auxiliary_ratios = core.build_auxiliary_ratios_by_year(
        timeseries,
        other_feedstocks,
        total_output,
    )
    efficiency_series = core.safe_divide_series(total_output, primary_series)
    record = core.build_process_record(
        economy,
        sector_title,
        process_name,
        {
            label: core.series_to_year_dict(series, core.EXPORT_BASE_YEAR, core.EXPORT_FINAL_YEAR)
            for label, series in output_series_map.items()
        },
        {
            primary_input: core.series_to_year_dict(
                primary_series, core.EXPORT_BASE_YEAR, core.EXPORT_FINAL_YEAR
            )
        },
        core.series_to_year_dict(
            efficiency_series, core.EXPORT_BASE_YEAR, core.EXPORT_FINAL_YEAR
        ),
        auxiliary_ratios=auxiliary_ratios,
        loss_values={},
        loss_total=0.0,
        feedstock_shares={primary_input: 1.0},
        input_total=float(primary_series.sum()),
        output_import_targets=output_import_targets,
        output_export_targets=output_export_targets,
    )
    return [record]


# ---------------------------------------------------------------------------
# Year-dict / label-series aggregation helpers
# ---------------------------------------------------------------------------

def _sum_label_series_dict(label_map: dict[str, dict]) -> pd.Series:
    """Return total year series across label->year maps."""
    total = pd.Series(dtype=float)
    for values in (label_map or {}).values():
        if not values:
            continue
        total = total.add(pd.Series(values, dtype=float), fill_value=0.0)
    return total


def _max_efficiency_ratio(record: dict) -> float:
    """Return the maximum efficiency ratio found in a process record."""
    efficiency_map = record.get("efficiency")
    if not isinstance(efficiency_map, dict) or not efficiency_map:
        return 0.0
    ratios = [float(value) for value in efficiency_map.values() if value is not None]
    if not ratios:
        return 0.0
    return float(max(ratios))


def _normalized_name_set(values: Iterable[object] | None) -> set[str]:
    """Return normalized lowercase process-name tokens."""
    if not values:
        return set()
    out: set[str] = set()
    for value in values:
        token = str(value or "").strip().lower()
        if token:
            out.add(token)
    return out


def _sum_year_dicts(series_list: Iterable[dict]) -> dict:
    """Sum year->value dicts, aligning years."""
    totals: dict[int, float] = {}
    for series in series_list:
        if not series:
            continue
        for year, value in series.items():
            if value is None:
                continue
            totals[int(year)] = totals.get(int(year), 0.0) + float(value)
    return totals


def _sum_label_series(label_map: dict[str, dict]) -> pd.Series:
    """Sum dict-of-year series across labels."""
    total = pd.Series(dtype=float)
    for series in (label_map or {}).values():
        if not series:
            continue
        total = total.add(pd.Series(series, dtype=float), fill_value=0.0)
    return total


# ---------------------------------------------------------------------------
# Unallocated-policy helper
# ---------------------------------------------------------------------------

def _apply_unallocated_policy(
    records: list[dict],
    policy: dict | None,
) -> list[dict]:
    """Collapse selected transfer rows into one unallocated process when triggered."""
    if not records:
        return records
    if not isinstance(policy, dict) or not policy:
        return records
    if not bool(policy.get("enabled", False)):
        return records

    include_names = _normalized_name_set(policy.get("include_processes"))
    exclude_names = _normalized_name_set(policy.get("exclude_processes"))

    def _is_included(record: dict) -> bool:
        name = str(record.get("process_name") or "").strip().lower()
        if not name:
            return False
        if include_names and name not in include_names:
            return False
        if exclude_names and name in exclude_names:
            return False
        return True

    candidate_records = [record for record in records if _is_included(record)]
    if not candidate_records:
        return records

    max_efficiency_ratio = policy.get("max_efficiency_ratio")
    max_efficiency_limit = (
        float(max_efficiency_ratio) if max_efficiency_ratio is not None else None
    )
    min_input_total = policy.get("min_input_total")
    min_input_limit = float(min_input_total) if min_input_total is not None else None

    bad_records: list[dict] = []
    for record in candidate_records:
        record_is_bad = False
        if max_efficiency_limit is not None and _max_efficiency_ratio(record) > max_efficiency_limit:
            record_is_bad = True
        if min_input_limit is not None:
            input_total = float(record.get("input_total") or 0.0)
            if input_total < min_input_limit:
                record_is_bad = True
        if record_is_bad:
            bad_records.append(record)
    if not bad_records:
        return records

    merge_all = bool(policy.get("merge_all_when_triggered", True))
    merge_targets = candidate_records if merge_all else bad_records
    if not merge_targets:
        return records

    output_values_by_label: dict[str, list[dict]] = {}
    feedstock_values_by_label: dict[str, list[dict]] = {}
    import_targets_by_label: dict[str, list[dict]] = {}
    export_targets_by_label: dict[str, list[dict]] = {}
    for record in merge_targets:
        for label, values in (record.get("output_values") or {}).items():
            output_values_by_label.setdefault(label, []).append(values)
        for label, values in (record.get("feedstock_values") or {}).items():
            feedstock_values_by_label.setdefault(label, []).append(values)
        for label, values in (record.get("output_import_targets") or {}).items():
            import_targets_by_label.setdefault(label, []).append(values)
        for label, values in (record.get("output_export_targets") or {}).items():
            export_targets_by_label.setdefault(label, []).append(values)

    aggregated_outputs = {
        label: _sum_year_dicts(values)
        for label, values in output_values_by_label.items()
        if values
    }
    aggregated_feedstocks = {
        label: _sum_year_dicts(values)
        for label, values in feedstock_values_by_label.items()
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

    total_output_series = _sum_label_series_dict(aggregated_outputs)
    total_input_series = _sum_label_series_dict(aggregated_feedstocks)
    efficiency_series = core.safe_divide_series(total_output_series, total_input_series)
    feedstock_shares = {
        label: core.safe_divide_series(pd.Series(series, dtype=float), total_input_series).to_dict()
        for label, series in aggregated_feedstocks.items()
    }

    carrier = dict(merge_targets[0])
    carrier["process_name"] = str(policy.get("process_name") or "Transfers unallocated")
    carrier["sector_title"] = carrier["process_name"]
    carrier["output_values"] = aggregated_outputs
    carrier["feedstock_values"] = aggregated_feedstocks
    carrier["feedstock_shares"] = feedstock_shares
    carrier["efficiency"] = core.series_to_year_dict(
        efficiency_series,
        core.EXPORT_BASE_YEAR,
        core.EXPORT_FINAL_YEAR,
    )
    carrier["input_total"] = (
        float(total_input_series.sum()) if not total_input_series.empty else 0.0
    )
    carrier["output_import_targets"] = aggregated_imports
    carrier["output_export_targets"] = aggregated_exports

    merged_target_ids = {id(record) for record in merge_targets}
    output_rows: list[dict] = [record for record in records if id(record) not in merged_target_ids]
    output_rows.append(carrier)
    return output_rows


# ---------------------------------------------------------------------------
# Economy inference
# ---------------------------------------------------------------------------

def _infer_primary_economy(rows: Sequence[dict]) -> str:
    for row in rows:
        economy = row.get("economy")
        if economy:
            return economy
    if core.ECONOMIES_TO_ANALYZE:
        return core.ECONOMIES_TO_ANALYZE[0]
    return "economy"


# ---------------------------------------------------------------------------
# Output consolidation
# ---------------------------------------------------------------------------

def consolidate_transfer_output_rows(
    rows: list[dict],
    include_output_series: bool,
    use_output_targets: bool,
) -> None:
    """Ensure transfer output values/targets are aggregated to avoid duplicates."""
    if not rows or not (include_output_series or use_output_targets):
        return
    grouped: dict[tuple[str, str], list[dict]] = {}
    for record in rows:
        key = (record.get("economy"), record.get("sector_title"))
        grouped.setdefault(key, []).append(record)
    for _, records in grouped.items():
        if len(records) < 2:
            continue
        output_values_by_label: dict[str, list[dict]] = {}
        import_targets_by_label: dict[str, list[dict]] = {}
        export_targets_by_label: dict[str, list[dict]] = {}
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
        carrier["output_values"] = aggregated_outputs if include_output_series else {}
        if use_output_targets:
            carrier["output_import_targets"] = aggregated_imports
            carrier["output_export_targets"] = aggregated_exports
        else:
            carrier["output_import_targets"] = {}
            carrier["output_export_targets"] = {}
        for record in records[1:]:
            record["output_values"] = {}
            record["output_import_targets"] = {}
            record["output_export_targets"] = {}


# ---------------------------------------------------------------------------
# Row merging
# ---------------------------------------------------------------------------

def merge_transfer_rows(rows: list[dict]) -> list[dict]:
    """Merge rows that share economy/sector/process to avoid duplicate LEAP rows."""
    if not rows:
        return rows
    grouped: dict[tuple[str, str, str], list[dict]] = {}
    for record in rows:
        key = (
            record.get("economy"),
            record.get("sector_title"),
            record.get("process_name"),
        )
        grouped.setdefault(key, []).append(record)
    merged_records: list[dict] = []
    for _, records in grouped.items():
        if len(records) == 1:
            merged_records.append(records[0])
            continue
        output_values_by_label: dict[str, list[dict]] = {}
        feedstock_values_by_label: dict[str, list[dict]] = {}
        import_targets_by_label: dict[str, list[dict]] = {}
        export_targets_by_label: dict[str, list[dict]] = {}
        for record in records:
            for label, values in (record.get("output_values") or {}).items():
                output_values_by_label.setdefault(label, []).append(values)
            for label, values in (record.get("feedstock_values") or {}).items():
                feedstock_values_by_label.setdefault(label, []).append(values)
            for label, values in (record.get("output_import_targets") or {}).items():
                import_targets_by_label.setdefault(label, []).append(values)
            for label, values in (record.get("output_export_targets") or {}).items():
                export_targets_by_label.setdefault(label, []).append(values)
        aggregated_outputs = {
            label: _sum_year_dicts(values)
            for label, values in output_values_by_label.items()
            if values
        }
        aggregated_feedstocks = {
            label: _sum_year_dicts(values)
            for label, values in feedstock_values_by_label.items()
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
        total_output_series = _sum_label_series(aggregated_outputs)
        total_input_series = _sum_label_series(aggregated_feedstocks)
        efficiency_series = core.safe_divide_series(total_output_series, total_input_series)
        feedstock_shares = {
            label: core.safe_divide_series(pd.Series(series, dtype=float), total_input_series).to_dict()
            for label, series in aggregated_feedstocks.items()
        }
        carrier = dict(records[0])
        carrier["output_values"] = aggregated_outputs
        carrier["feedstock_values"] = aggregated_feedstocks
        carrier["feedstock_shares"] = feedstock_shares
        carrier["efficiency"] = core.series_to_year_dict(
            efficiency_series, core.EXPORT_BASE_YEAR, core.EXPORT_FINAL_YEAR
        )
        carrier["input_total"] = float(total_input_series.sum()) if not total_input_series.empty else 0.0
        carrier["output_import_targets"] = aggregated_imports
        carrier["output_export_targets"] = aggregated_exports
        merged_records.append(carrier)
    return merged_records


# ---------------------------------------------------------------------------
# Legacy thin wrappers (kept here so they're in scope for re-export)
# ---------------------------------------------------------------------------

def _merge_transfer_process_records(process_records: list[dict]) -> list[dict]:
    return merge_transfer_rows(process_records)


def _consolidate_transfer_outputs(
    process_records: list[dict],
    include_output_series: bool,
    use_output_targets: bool,
) -> None:
    return consolidate_transfer_output_rows(
        process_records,
        include_output_series,
        use_output_targets,
    )
