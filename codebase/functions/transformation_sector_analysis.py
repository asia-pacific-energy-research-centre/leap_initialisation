# Summary: Sector-level transformation analysis functions extracted from
# transformation_analysis_utils.py (Phase 3e). Contains the four large
# analyze_* functions and their private hydrogen helpers.
#
# IMPORTANT: All imports from transformation_analysis_utils (TAU) are deferred
# to the bottom of this file (after all function definitions).  This avoids
# a circular-import deadlock when transformation_sector_analysis is imported
# directly: Python executes this file top-to-bottom, defines all functions,
# then runs the deferred TAU imports — at which point TAU is already fully
# initialized and in sys.modules (having triggered this file's load via its
# own re-export block at the bottom of transformation_analysis_utils.py).

import pandas as pd
from codebase.functions.esto_data_utils import (
    try_debug_breakpoint,
    sum_years,
)
from codebase.functions.transformation_series_utils import (
    ensure_full_year_series,
    series_to_year_dict,
    safe_divide_series,
    to_input_only_series,
    to_output_only_series,
    build_auxiliary_ratios_by_year,
    build_auxiliary_from_losses_by_year,
    merge_loss_into_auxiliary_by_year,
    filter_loss_values_for_feedstock_by_year,
    get_loss_total_for_efficiency_by_year,
    compute_efficiency_by_year,
    compute_primary_io,
    build_total_input_series,
    build_input_share_series,
    allocate_outputs_by_share,
    allocate_loss_by_share,
    sum_loss_values_by_year,
    scale_year_dict_by_share,
    calculate_efficiency_with_losses,
)
from codebase.functions.transformation_fuel_utils import (
    get_years_from,
    get_fuel_labels,
    summarize_fuels_by_subfuel,
    summarize_fuel_totals,
    summarize_fuel_timeseries,
    get_label_timeseries,
    sum_years_by_year,
)
from codebase.functions.transformation_record_builder import (
    map_series_index,
    map_code_label,
    has_required_columns,
    append_process_record,
    build_zero_skeleton_record,
    build_process_record,
    print_leap_structure_block,
    summarize_numeric_value,
    build_value_by_year,
    compute_own_use_ratios_for_record,
)


def _coerce_label_list(value):
    """Return a clean list[str] from a scalar/list config value."""
    try:
        if value is None:
            return []
        if isinstance(value, list):
            raw_values = value
        else:
            raw_values = [value]
        labels = []
        for raw in raw_values:
            text = str(raw).strip()
            if text:
                labels.append(text)
        return labels
    except Exception as exc:
        print(f"Failed to coerce label list from {value}: {exc}")
        try_debug_breakpoint()
        raise


def _sum_series_collection(series_list, year_index):
    """Return the sum of aligned Series objects over year_index."""
    try:
        total = pd.Series({year: 0.0 for year in year_index}, dtype=float)
        for series in series_list:
            if series is None:
                continue
            aligned = series.reindex(year_index, fill_value=0.0)
            total = total.add(aligned, fill_value=0.0)
        return total
    except Exception as exc:
        print(f"Failed to sum series collection: {exc}")
        try_debug_breakpoint()
        raise


def _merge_year_value_maps(target_map, updates):
    """Merge dict[label][year] values into target_map by summing overlaps."""
    try:
        if not updates:
            return target_map
        for label, year_map in updates.items():
            if not isinstance(year_map, dict):
                continue
            destination = target_map.setdefault(label, {})
            for year, value in year_map.items():
                if value is None or pd.isna(value):
                    continue
                year_int = int(year)
                destination[year_int] = destination.get(year_int, 0.0) + float(value)
        return target_map
    except Exception as exc:
        print(f"Failed to merge year value maps: {exc}")
        try_debug_breakpoint()
        raise


def _build_hydrogen_loss_context(
    loss_data,
    loss_year_cols,
    start_year,
    economy,
    loss_sub2_codes,
):
    """Return (loss_values_by_year, loss_total_by_year) for configured loss sub2 codes."""
    try:
        if not loss_sub2_codes:
            return {}, pd.Series(dtype=float)
        merged_loss_values = {}
        for loss_sub2 in loss_sub2_codes:
            _, _, loss_values_by_year = summarize_own_use_losses_by_year(
                loss_data,
                loss_year_cols,
                start_year,
                economy,
                loss_sub2_code=loss_sub2,
                allow_all_years_fallback=True,
            )
            _merge_year_value_maps(merged_loss_values, loss_values_by_year)
        if not merged_loss_values:
            return {}, pd.Series(dtype=float)
        loss_totals = {}
        for year_map in merged_loss_values.values():
            for year, value in year_map.items():
                if value is None or pd.isna(value):
                    continue
                year_int = int(year)
                loss_totals[year_int] = loss_totals.get(year_int, 0.0) + abs(float(value))
        return merged_loss_values, pd.Series(loss_totals, dtype=float)
    except Exception as exc:
        print(f"Failed to build hydrogen loss context: {exc}")
        try_debug_breakpoint()
        raise


def _build_esto_split_lng_flows(esto_ref, economy, flow_code, esto_year_cols, start_year, export_base_year, export_final_year):
    """
    Extract output_series and input_series_by_label from ESTO rows for one LNG sub-flow.

    In ESTO format positive values are outputs and negative values are inputs.
    Returns (output_series, input_series_by_label) or (None, None) if the base year
    total is zero (no real data yet for this economy).
    """
    if esto_ref is None or "flows" not in esto_ref.columns or "economy" not in esto_ref.columns:
        return None, None

    flow_rows = esto_ref[
        (esto_ref["economy"] == economy) &
        (esto_ref["flows"] == flow_code)
    ].copy()

    if flow_rows.empty:
        return None, None

    # Find the base year column (may be int or str after normalisation)
    base_col = next(
        (c for c in esto_year_cols if str(c) == str(start_year) and c in flow_rows.columns),
        None,
    )
    if base_col is None:
        return None, None

    if flow_rows[base_col].fillna(0).abs().sum() == 0:
        return None, None

    export_years = list(range(export_base_year, export_final_year + 1))
    valid_cols = {}
    for c in esto_year_cols:
        try:
            yr = int(c)
        except (ValueError, TypeError):
            continue
        if c in flow_rows.columns and export_base_year <= yr <= export_final_year:
            valid_cols[yr] = c

    # Output series: sum of positive values per year
    output_data = {yr: float(flow_rows[col].fillna(0).clip(lower=0).sum()) for yr, col in valid_cols.items()}
    output_series = ensure_full_year_series(pd.Series(output_data, dtype=float), export_base_year, export_final_year)

    # Input series by product label: absolute value of negative-valued rows
    input_series_by_label = {}
    product_col = "products" if "products" in flow_rows.columns else None
    if product_col:
        for product, prod_rows in flow_rows.groupby(product_col):
            product_label = str(product).strip()
            if not product_label or product_label.lower() == "nan":
                continue
            input_data = {}
            for yr, col in valid_cols.items():
                val = float(prod_rows[col].fillna(0).sum())
                if val < 0:
                    input_data[yr] = abs(val)
            if input_data:
                s = ensure_full_year_series(pd.Series(input_data, dtype=float), export_base_year, export_final_year)
                if s.sum() > 0:
                    input_series_by_label[product_label] = s

    return output_series, input_series_by_label


def analyze_lng_liquefaction_regas(
    esto_data,
    year_cols,
    start_year,
    economy,
    code_to_name_mapping,
    loss_data,
    loss_year_cols,
    sector_config=None,
    process_records=None,
    esto_reference_data=None,
    esto_reference_year_cols=None,
):
    """Estimate LNG liquefaction/regasification efficiency and auxiliary fuel use."""
    try:
        lng_config = sector_config or MAJOR_SECTOR_CONFIG["lng"]
        fuel_codes = {
            "natural_gas": "08_01_natural_gas",
            "lng": "08_02_lng",
            "gas_works_gas": "08_03_gas_works_gas",
            "lignite": "01_05_lignite",
            "electricity": "17_electricity",
        }
        lng_sub2 = lng_config["transformation_sub2"][0]
        print(f"\n==== LNG liquefaction/regasification ({economy}) ====")
        if not has_required_columns(
            esto_data,
            [["sub2sectors", "subfuels", "fuels"], ["flows", "products"]],
            "LNG liquefaction/regasification",
        ):
            return
        export_base_year = EXPORT_BASE_YEAR
        export_final_year = EXPORT_FINAL_YEAR
        export_years = list(range(export_base_year, export_final_year + 1))
        print_sector_rows(
            esto_data,
            "LNG liquefaction/regas rows",
            {"economy": economy, "sub2sectors": lng_sub2},
            year_cols,
            start_year,
            code_to_name_mapping,
        )

        def _zero_series():
            return pd.Series({year: 0.0 for year in export_years}, dtype=float)

        def _mask_loss_values_by_year(loss_values_by_year, mask_series):
            masked = {}
            if not loss_values_by_year:
                return masked
            for label, series in loss_values_by_year.items():
                if not isinstance(series, dict):
                    continue
                selected = {}
                for year in export_years:
                    if not bool(mask_series.get(year, False)):
                        continue
                    value = series.get(year, series.get(str(year), 0.0))
                    if value is None or pd.isna(value):
                        continue
                    selected[year] = abs(float(value))
                if selected:
                    masked[label] = selected
            return masked

        def _accumulate_loss_values(target, updates):
            if not updates:
                return
            for label, series in updates.items():
                if not isinstance(series, dict):
                    continue
                destination = target.setdefault(label, {})
                for year, value in series.items():
                    if value is None or pd.isna(value):
                        continue
                    year_int = int(year)
                    destination[year_int] = destination.get(year_int, 0.0) + abs(float(value))

        feedstock_method = resolve_feedstock_method()
        regas_output_series = _zero_series()
        liquefaction_output_series = _zero_series()
        regas_input_series_by_label = {}
        liq_input_series_by_label = {}
        regas_loss_values_by_year = {}
        liq_loss_values_by_year = {}

        normalized_economy = _normalize_economy_value(economy).upper()
        aggregate_mode = "ALL" in normalized_economy or normalized_economy == "00APEC"
        if not aggregate_mode and "economy" in esto_data.columns:
            year_cols_from_start = get_years_from(year_cols, start_year)
            aggregate_rows = select_rows(
                esto_data,
                {"economy": economy, "sub2sectors": lng_sub2},
            )
            non_aggregate_rows = esto_data[
                esto_data["economy"]
                .apply(_normalize_economy_value)
                .ne(_normalize_economy_value(economy))
            ]
            non_aggregate_rows = select_rows(
                non_aggregate_rows,
                {"sub2sectors": lng_sub2},
            )
            aggregate_total = sum_years(aggregate_rows, year_cols_from_start)
            non_aggregate_total = sum_years(non_aggregate_rows, year_cols_from_start)
            tolerance = 1e-6 * max(1.0, abs(aggregate_total), abs(non_aggregate_total))
            if abs(aggregate_total - non_aggregate_total) <= tolerance:
                aggregate_mode = True
        component_economies = [economy]
        if aggregate_mode and "economy" in esto_data.columns:
            available_economies = sorted(esto_data["economy"].dropna().astype(str).unique())
            non_aggregate = [
                value
                for value in available_economies
                if _normalize_economy_value(value).upper() != normalized_economy
            ]
            if non_aggregate:
                component_economies = non_aggregate
                print(
                    "LNG aggregate mode: classifying each economy-year before summing "
                    f"({len(component_economies)} economies)."
                )

        regas_direction_count = 0
        liq_direction_count = 0
        ambiguous_direction_count = 0

        def _accumulate_series_map(target, label, series):
            if series is None or series.empty:
                return
            existing = target.get(label)
            if existing is None or existing.empty:
                target[label] = series.copy()
            else:
                target[label] = existing.add(series, fill_value=0.0)

        liq_flow_code = lng_config.get("esto_flow_code_liquefaction", "09.06.02.01 Liquefaction")
        regas_flow_code = lng_config.get("esto_flow_code_regasification", "09.06.02.02 Regasification")

        for component_economy in component_economies:
            # --- ESTO split data path ---
            # If ESTO already has non-zero base-year data for the split sub-flows,
            # use those directly rather than running the ninth sign analysis.
            if esto_reference_data is not None:
                esto_liq_out, esto_liq_inputs = _build_esto_split_lng_flows(
                    esto_reference_data, component_economy, liq_flow_code,
                    esto_reference_year_cols or [], start_year, export_base_year, export_final_year,
                )
                esto_regas_out, esto_regas_inputs = _build_esto_split_lng_flows(
                    esto_reference_data, component_economy, regas_flow_code,
                    esto_reference_year_cols or [], start_year, export_base_year, export_final_year,
                )
                if esto_liq_out is not None or esto_regas_out is not None:
                    print(f"LNG {component_economy}: using ESTO split data ({liq_flow_code} / {regas_flow_code})")
                    if esto_liq_out is not None and esto_liq_out.sum() > 0:
                        liquefaction_output_series = liquefaction_output_series.add(esto_liq_out, fill_value=0.0)
                        for label, series in (esto_liq_inputs or {}).items():
                            _accumulate_series_map(liq_input_series_by_label, label, series)
                        liq_direction_count += int(esto_liq_out.gt(0).sum())
                    if esto_regas_out is not None and esto_regas_out.sum() > 0:
                        regas_output_series = regas_output_series.add(esto_regas_out, fill_value=0.0)
                        for label, series in (esto_regas_inputs or {}).items():
                            _accumulate_series_map(regas_input_series_by_label, label, series)
                        regas_direction_count += int(esto_regas_out.gt(0).sum())
                    continue  # skip ninth sign analysis for this economy

            # --- Ninth sign-analysis path (default) ---
            ng_series_raw = ensure_full_year_series(
                sum_years_by_year(
                    select_rows(
                        esto_data,
                        {
                            "economy": component_economy,
                            "sub2sectors": lng_sub2,
                            "subfuels": fuel_codes["natural_gas"],
                        },
                    ),
                    year_cols,
                    start_year,
                ),
                export_base_year,
                export_final_year,
            )
            lng_series_raw = ensure_full_year_series(
                sum_years_by_year(
                    select_rows(
                        esto_data,
                        {
                            "economy": component_economy,
                            "sub2sectors": lng_sub2,
                            "subfuels": fuel_codes["lng"],
                        },
                    ),
                    year_cols,
                    start_year,
                ),
                export_base_year,
                export_final_year,
            )
            process_rows = select_rows(
                esto_data,
                {"economy": component_economy, "sub2sectors": lng_sub2},
            )
            timeseries, _ = summarize_fuel_timeseries(
                process_rows,
                year_cols,
                start_year,
                allow_all_years_fallback=True,
            )

            regas_mask = (ng_series_raw > 0) & (lng_series_raw < 0)
            liq_mask = (lng_series_raw > 0) & (ng_series_raw < 0)
            activity_mask = ng_series_raw.ne(0) | lng_series_raw.ne(0)
            ambiguous_mask = activity_mask & ~(regas_mask | liq_mask)

            regas_direction_count += int(regas_mask.sum())
            liq_direction_count += int(liq_mask.sum())
            ambiguous_direction_count += int(ambiguous_mask.sum())

            regas_output_series = regas_output_series.add(
                to_output_only_series(ng_series_raw.where(regas_mask, 0.0)),
                fill_value=0.0,
            )

            liquefaction_output_series = liquefaction_output_series.add(
                to_output_only_series(lng_series_raw.where(liq_mask, 0.0)),
                fill_value=0.0,
            )
            if timeseries is not None and not timeseries.empty:
                for label in timeseries.index:
                    series_full = ensure_full_year_series(
                        timeseries.loc[label],
                        export_base_year,
                        export_final_year,
                    )
                    regas_input = to_input_only_series(series_full.where(regas_mask, 0.0))
                    liq_input = to_input_only_series(series_full.where(liq_mask, 0.0))
                    if regas_input.sum() > 0:
                        _accumulate_series_map(regas_input_series_by_label, label, regas_input)
                    if liq_input.sum() > 0:
                        _accumulate_series_map(liq_input_series_by_label, label, liq_input)

            if not (regas_mask.any() or liq_mask.any()):
                continue

            _, _, _, loss_values_by_year = build_loss_context(
                loss_data,
                loss_year_cols,
                start_year,
                component_economy,
                "lng",
                lng_sub2,
            )
            _accumulate_loss_values(
                regas_loss_values_by_year,
                _mask_loss_values_by_year(loss_values_by_year, regas_mask),
            )
            _accumulate_loss_values(
                liq_loss_values_by_year,
                _mask_loss_values_by_year(loss_values_by_year, liq_mask),
            )

        print(
            "LNG direction summary: "
            f"regas economy-years={regas_direction_count}, "
            f"liq economy-years={liq_direction_count}, "
            f"ambiguous economy-years={ambiguous_direction_count}"
        )
        if ambiguous_direction_count > 0:
            print(
                "Warning: LNG ambiguous direction years were excluded from both processes."
            )

        def _aux_ratios_from_inputs(input_series_by_label, output_series, labels):
            ratios = {}
            output_series_pos = to_output_only_series(output_series)
            for label in labels:
                series = input_series_by_label.get(label)
                if series is None:
                    continue
                ratio_series = safe_divide_series(series, output_series_pos)
                ratios[label] = ratio_series.to_dict()
            return ratios

        def _build_lng_process(process_name, output_label, output_series, input_series_by_label, loss_values_by_year):
            _lng_sector_title = (
                lng_config.get("regasification_title", "LNG regasification")
                if str(process_name).strip().lower() == "regasification"
                else lng_config.get("liquefaction_title", lng_config.get("title", "NG Liquefaction"))
            )
            if output_series.sum() == 0 and not input_series_by_label:
                print(f"{process_name}: no output or inputs for {economy}; writing zero skeleton.")
                append_process_record(process_records, build_zero_skeleton_record(
                    economy, _lng_sector_title, process_name, [output_label],
                    export_base_year, export_final_year,
                ))
                return
            sector_title = _lng_sector_title
            total_input_series = build_total_input_series(input_series_by_label, export_years)
            total_loss_by_year = sum_loss_values_by_year(loss_values_by_year, export_years)
            output_import_targets_total, output_export_targets_total = gather_output_target_dicts(
                economy,
                [output_label],
                export_base_year,
                export_final_year,
                output_series_by_fuel={output_label: output_series},
            )
            if feedstock_method == FEEDSTOCK_METHOD_SPLIT:
                feedstock_labels = list(input_series_by_label.keys())
                for idx, feedstock_label in enumerate(feedstock_labels):
                    input_series = input_series_by_label[feedstock_label]
                    share_series = build_input_share_series(
                        input_series,
                        total_input_series,
                        fallback_to_one=(idx == 0),
                    )
                    allocated_output_series = output_series.mul(share_series, fill_value=0.0)
                    allocated_loss_values = allocate_loss_by_share(
                        loss_values_by_year,
                        share_series,
                    )
                    loss_total_for_eff = total_loss_by_year.mul(share_series, fill_value=0.0)
                    efficiency_series = compute_efficiency_by_year(
                        allocated_output_series,
                        input_series,
                        loss_total_for_eff,
                    )
                    auxiliary_fuels, auxiliary_ratios = build_auxiliary_from_losses_by_year(
                        allocated_loss_values,
                        allocated_output_series,
                        feedstock_labels=[feedstock_label],
                    )
                    output_import_targets = {
                        label: scale_year_dict_by_share(values, share_series)
                        for label, values in (output_import_targets_total or {}).items()
                    }
                    output_export_targets = {
                        label: scale_year_dict_by_share(values, share_series)
                        for label, values in (output_export_targets_total or {}).items()
                    }
                    process_label = (
                        process_name
                        if len(feedstock_labels) == 1
                        else f"{process_name} - {feedstock_label}"
                    )
                    print_leap_structure_block(
                        f"LNG {process_label}",
                        [output_label],
                        process_label,
                        [feedstock_label],
                        auxiliary_fuels,
                        loss_fuels=list(allocated_loss_values.keys()),
                        code_to_name_mapping=code_to_name_mapping,
                        output_fuel_values={output_label: allocated_output_series.sum()},
                        process_value=f"{efficiency_series.mean():.4f}",
                        feedstock_fuel_values={feedstock_label: input_series.sum()},
                        auxiliary_fuel_values={
                            label: summarize_numeric_value(values, summary="mean")
                            for label, values in auxiliary_ratios.items()
                        },
                        loss_fuel_values={
                            label: summarize_numeric_value(values, summary="sum")
                            for label, values in allocated_loss_values.items()
                        },
                    )
                    append_process_record(
                        process_records,
                        build_process_record(
                            economy,
                            sector_title,
                            process_label,
                            {
                                output_label: series_to_year_dict(
                                    allocated_output_series, export_base_year, export_final_year
                                )
                            },
                            {
                                feedstock_label: series_to_year_dict(
                                    input_series, export_base_year, export_final_year
                                )
                            },
                            series_to_year_dict(
                                efficiency_series, export_base_year, export_final_year
                            ),
                            auxiliary_ratios,
                            allocated_loss_values,
                            float(pd.Series(loss_total_for_eff, dtype=float).sum()),
                            loss_values_for_efficiency=series_to_year_dict(
                                loss_total_for_eff,
                                export_base_year,
                                export_final_year,
                            ),
                            feedstock_shares={feedstock_label: 1.0},
                            input_total=float(input_series.sum()),
                            output_import_targets=output_import_targets,
                            output_export_targets=output_export_targets,
                        ),
                    )
                return
            if feedstock_method == FEEDSTOCK_METHOD_MULTI:
                auxiliary_fuels, auxiliary_ratios = build_auxiliary_from_losses_by_year(
                    loss_values_by_year,
                    output_series,
                    feedstock_labels=list(input_series_by_label.keys()) if LOSS_AUX_EXCLUDE_FEEDSTOCKS else None,
                )
                efficiency_series = compute_efficiency_by_year(
                    output_series,
                    total_input_series,
                    total_loss_by_year,
                )
                feedstock_values = {
                    label: series_to_year_dict(series, export_base_year, export_final_year)
                    for label, series in input_series_by_label.items()
                }
                feedstock_shares = {
                    label: safe_divide_series(series, total_input_series).to_dict()
                    for label, series in input_series_by_label.items()
                }
                print_leap_structure_block(
                    f"LNG {process_name}",
                    [output_label],
                    process_name,
                    list(feedstock_values.keys()),
                    auxiliary_fuels,
                    loss_fuels=list(loss_values_by_year.keys()),
                    code_to_name_mapping=code_to_name_mapping,
                    output_fuel_values={output_label: output_series.sum()},
                    process_value=f"{efficiency_series.mean():.4f}",
                    feedstock_fuel_values={
                        label: summarize_numeric_value(values, summary="sum")
                        for label, values in feedstock_values.items()
                    },
                    auxiliary_fuel_values={
                        label: summarize_numeric_value(values, summary="mean")
                        for label, values in auxiliary_ratios.items()
                    },
                    loss_fuel_values={
                        label: summarize_numeric_value(values, summary="sum")
                        for label, values in loss_values_by_year.items()
                    },
                )
                append_process_record(
                    process_records,
                    build_process_record(
                        economy,
                        sector_title,
                        process_name,
                        {
                            output_label: series_to_year_dict(
                                output_series, export_base_year, export_final_year
                            )
                        },
                        feedstock_values,
                        series_to_year_dict(
                            efficiency_series, export_base_year, export_final_year
                        ),
                        auxiliary_ratios,
                        loss_values_by_year,
                        float(pd.Series(total_loss_by_year, dtype=float).sum()),
                        loss_values_for_efficiency=series_to_year_dict(
                            total_loss_by_year,
                            export_base_year,
                            export_final_year,
                        ),
                        feedstock_shares=feedstock_shares,
                        input_total=float(total_input_series.sum()),
                        output_import_targets=output_import_targets_total,
                        output_export_targets=output_export_targets_total,
                        own_use_ratios=compute_own_use_ratios_for_record(
                            loss_values_by_year, input_series_by_label, export_years
                        ),
                    ),
                )
                return

            if not input_series_by_label:
                return
            primary_input = max(
                input_series_by_label,
                key=lambda label: input_series_by_label[label].sum(),
            )
            input_series = input_series_by_label.get(primary_input)
            if input_series is None or input_series.sum() == 0:
                return
            other_feedstocks = [
                label for label in input_series_by_label.keys() if label != primary_input
            ]
            auxiliary_fuels = list(other_feedstocks)
            auxiliary_ratios = _aux_ratios_from_inputs(
                input_series_by_label,
                output_series,
                auxiliary_fuels,
            )
            auxiliary_fuels, auxiliary_ratios = merge_loss_into_auxiliary_by_year(
                auxiliary_fuels,
                auxiliary_ratios,
                loss_values_by_year,
                output_series,
                primary_input,
            )
            efficiency_series = compute_efficiency_by_year(
                output_series,
                total_input_series,
                total_loss_by_year,
            )
            print_leap_structure_block(
                f"LNG {process_name}",
                [output_label],
                process_name,
                [primary_input],
                auxiliary_fuels,
                loss_fuels=list(loss_values_by_year.keys()),
                code_to_name_mapping=code_to_name_mapping,
                output_fuel_values={output_label: output_series.sum()},
                process_value=f"{efficiency_series.mean():.4f}",
                feedstock_fuel_values={primary_input: input_series.sum()},
                auxiliary_fuel_values={
                    label: summarize_numeric_value(values, summary="mean")
                    for label, values in auxiliary_ratios.items()
                },
                loss_fuel_values={
                    label: summarize_numeric_value(values, summary="sum")
                    for label, values in loss_values_by_year.items()
                },
            )
            append_process_record(
                process_records,
                build_process_record(
                    economy,
                    sector_title,
                    process_name,
                    {
                        output_label: series_to_year_dict(
                            output_series, export_base_year, export_final_year
                        )
                    },
                    {
                        primary_input: series_to_year_dict(
                            input_series, export_base_year, export_final_year
                        )
                    },
                    series_to_year_dict(
                        efficiency_series, export_base_year, export_final_year
                    ),
                    auxiliary_ratios,
                    loss_values_by_year,
                    float(pd.Series(total_loss_by_year, dtype=float).sum()),
                    loss_values_for_efficiency=series_to_year_dict(
                        total_loss_by_year,
                        export_base_year,
                        export_final_year,
                    ),
                    feedstock_shares={primary_input: 1.0},
                    input_total=float(total_input_series.sum()),
                    output_import_targets=output_import_targets_total,
                    output_export_targets=output_export_targets_total,
                ),
            )

        # Always build both configured LNG processes. The builder emits a zero
        # skeleton when a process has no activity, keeping branch keys present
        # across scenarios so SEED-010 can continue to detect genuine omissions.
        _build_lng_process(
            "Regasification",
            fuel_codes["natural_gas"],
            regas_output_series,
            regas_input_series_by_label,
            regas_loss_values_by_year,
        )

        _build_lng_process(
            "Liquefaction",
            fuel_codes["lng"],
            liquefaction_output_series,
            liq_input_series_by_label,
            liq_loss_values_by_year,
        )
    except Exception as exc:
        print(f"LNG analysis failed: {exc}")
        try_debug_breakpoint()
        raise


def analyze_gas_processing(
    esto_data,
    year_cols,
    start_year,
    economy,
    code_to_name_mapping,
    loss_data,
    loss_year_cols,
    sector_config=None,
    process_records=None,
):
    """Estimate efficiencies for gas works and natural gas blending plants."""
    try:
        if sector_config is None:
            raise ValueError("Gas processing analysis requires a sector_config")
        gas_config = sector_config
        fuel_codes = {
            "natural_gas": "08_01_natural_gas",
            "lng": "08_02_lng",
            "gas_works_gas": "08_03_gas_works_gas",
            "lignite": "01_05_lignite",
            "electricity": "17_electricity",
        }
        transformation_sub2 = gas_config.get("transformation_sub2") or []
        gas_works_sub2 = transformation_sub2[0] if len(transformation_sub2) > 0 else None
        blending_sub2 = transformation_sub2[1] if len(transformation_sub2) > 1 else None
        gas_works_flow_code = gas_config.get("flow_code_gas_works")
        blending_flow_code = gas_config.get("flow_code_blending")
        product_code_natural_gas = gas_config.get("product_code_natural_gas")
        product_code_gas_works_gas = gas_config.get("product_code_gas_works_gas")
        product_code_lignite = gas_config.get("product_code_lignite")
        print(f"\n==== Gas processing (no imports/exports expected) ({economy}) ====")
        if not has_required_columns(
            esto_data,
            [["sub2sectors", "subfuels", "fuels"], ["flows", "products"]],
            "Gas processing",
        ):
            return
        year_cols_from_start = get_years_from(year_cols, start_year)
        export_base_year = EXPORT_BASE_YEAR
        export_final_year = EXPORT_FINAL_YEAR
        export_years = list(range(export_base_year, export_final_year + 1))

        def _build_gas_process_records(
            sector_title,
            process_name,
            output_label,
            process_rows,
            output_rows,
            loss_sub2_code,
        ):
            if process_rows.empty:
                print(f"{process_name}: no data rows for {economy}; writing zero skeleton.")
                append_process_record(process_records, build_zero_skeleton_record(
                    economy, sector_title, process_name, [output_label],
                    export_base_year, export_final_year,
                ))
                return
            feedstock_method = resolve_feedstock_method()
            totals, _ = summarize_fuel_totals(
                process_rows, year_cols, start_year, allow_all_years_fallback=True
            )
            timeseries, _ = summarize_fuel_timeseries(
                process_rows, year_cols, start_year, allow_all_years_fallback=True
            )
            negative = totals[totals < 0]
            if negative.empty or timeseries.empty:
                print(f"{process_name}: no negative inputs available; writing zero skeleton.")
                append_process_record(process_records, build_zero_skeleton_record(
                    economy, sector_title, process_name, [output_label],
                    export_base_year, export_final_year,
                ))
                return
            output_series = ensure_full_year_series(
                sum_years_by_year(output_rows, year_cols, start_year),
                export_base_year,
                export_final_year,
            )
            if output_series.sum() == 0:
                print(f"{process_name}: no output series available; writing zero skeleton.")
                append_process_record(process_records, build_zero_skeleton_record(
                    economy, sector_title, process_name, [output_label],
                    export_base_year, export_final_year,
                ))
                return
            input_series_map, zero_sum_labels = build_input_series_map(
                timeseries,
                list(negative.index),
                export_base_year,
                export_final_year,
            )
            if zero_sum_labels:
                log_dropped_input_fuels(economy, str(process_name), zero_sum_labels, export_base_year, export_final_year)
            if not input_series_map:
                print(f"{process_name}: no input series after normalization; writing zero skeleton.")
                append_process_record(process_records, build_zero_skeleton_record(
                    economy, sector_title, process_name, [output_label],
                    export_base_year, export_final_year,
                ))
                return
            total_input_series = build_total_input_series(input_series_map, export_years)
            loss_series, loss_total, loss_values, loss_values_by_year = build_loss_context(
                loss_data,
                loss_year_cols,
                start_year,
                economy,
                "gas_processing",
                loss_sub2_code,
            )
            total_loss_by_year = sum_loss_values_by_year(loss_values_by_year, export_years)
            output_import_targets_total, output_export_targets_total = gather_output_target_dicts(
                economy,
                [output_label],
                export_base_year,
                export_final_year,
                output_series_by_fuel={output_label: output_series},
            )

            if feedstock_method == FEEDSTOCK_METHOD_SPLIT:
                feedstock_labels = list(input_series_map.keys())
                for idx, feedstock_label in enumerate(feedstock_labels):
                    input_series = input_series_map[feedstock_label]
                    share_series = build_input_share_series(
                        input_series,
                        total_input_series,
                        fallback_to_one=(idx == 0),
                    )
                    allocated_output_series = output_series.mul(share_series, fill_value=0.0)
                    allocated_loss_values = allocate_loss_by_share(
                        loss_values_by_year,
                        share_series,
                    )
                    loss_total_for_eff = total_loss_by_year.mul(share_series, fill_value=0.0)
                    efficiency_series = compute_efficiency_by_year(
                        allocated_output_series,
                        input_series,
                        loss_total_for_eff,
                    )
                    auxiliary_fuels, auxiliary_ratios = build_auxiliary_from_losses_by_year(
                        allocated_loss_values,
                        allocated_output_series,
                        feedstock_labels=[feedstock_label],
                    )
                    output_import_targets = {
                        label: scale_year_dict_by_share(values, share_series)
                        for label, values in (output_import_targets_total or {}).items()
                    }
                    output_export_targets = {
                        label: scale_year_dict_by_share(values, share_series)
                        for label, values in (output_export_targets_total or {}).items()
                    }
                    process_label = (
                        process_name
                        if len(feedstock_labels) == 1
                        else f"{process_name} - {feedstock_label}"
                    )
                    print_leap_structure_block(
                        process_label,
                        [output_label],
                        process_label,
                        [feedstock_label],
                        auxiliary_fuels,
                        loss_fuels=list(allocated_loss_values.keys()),
                        code_to_name_mapping=code_to_name_mapping,
                        output_fuel_values={output_label: allocated_output_series.sum()},
                        process_value=f"{efficiency_series.mean():.6f}",
                        feedstock_fuel_values={feedstock_label: input_series.sum()},
                        auxiliary_fuel_values={
                            label: summarize_numeric_value(values, summary="mean")
                            for label, values in auxiliary_ratios.items()
                        },
                        loss_fuel_values={
                            label: summarize_numeric_value(values, summary="sum")
                            for label, values in allocated_loss_values.items()
                        },
                    )
                    record = build_process_record(
                        economy,
                        sector_title,
                        process_label,
                        {output_label: series_to_year_dict(allocated_output_series, export_base_year, export_final_year)},
                        {feedstock_label: series_to_year_dict(input_series, export_base_year, export_final_year)},
                        series_to_year_dict(efficiency_series, export_base_year, export_final_year),
                        auxiliary_ratios,
                        allocated_loss_values,
                        float(pd.Series(loss_total_for_eff, dtype=float).sum()),
                        loss_values_for_efficiency=series_to_year_dict(
                            loss_total_for_eff,
                            export_base_year,
                            export_final_year,
                        ),
                        feedstock_shares={feedstock_label: 1.0},
                        input_total=float(input_series.sum()),
                        output_import_targets=output_import_targets,
                        output_export_targets=output_export_targets,
                    )
                    append_process_record(process_records, record)
            elif feedstock_method == FEEDSTOCK_METHOD_MULTI:
                auxiliary_fuels, auxiliary_ratios = build_auxiliary_from_losses_by_year(
                    loss_values_by_year,
                    output_series,
                    feedstock_labels=list(input_series_map.keys()) if LOSS_AUX_EXCLUDE_FEEDSTOCKS else None,
                )
                efficiency_series = compute_efficiency_by_year(
                    output_series,
                    total_input_series,
                    total_loss_by_year,
                )
                feedstock_values = {
                    label: series_to_year_dict(series, export_base_year, export_final_year)
                    for label, series in input_series_map.items()
                }
                feedstock_shares = {
                    label: safe_divide_series(series, total_input_series).to_dict()
                    for label, series in input_series_map.items()
                }
                print_leap_structure_block(
                    process_name,
                    [output_label],
                    process_name,
                    list(feedstock_values.keys()),
                    auxiliary_fuels,
                    loss_fuels=list(loss_values_by_year.keys()),
                    code_to_name_mapping=code_to_name_mapping,
                    output_fuel_values={output_label: output_series.sum()},
                    process_value=f"{efficiency_series.mean():.6f}",
                    feedstock_fuel_values={
                        label: summarize_numeric_value(values, summary="sum")
                        for label, values in feedstock_values.items()
                    },
                    auxiliary_fuel_values={
                        label: summarize_numeric_value(values, summary="mean")
                        for label, values in auxiliary_ratios.items()
                    },
                    loss_fuel_values={
                        label: summarize_numeric_value(values, summary="sum")
                        for label, values in loss_values_by_year.items()
                    },
                )
                record = build_process_record(
                    economy,
                    sector_title,
                    process_name,
                    {output_label: series_to_year_dict(output_series, export_base_year, export_final_year)},
                    feedstock_values,
                    series_to_year_dict(efficiency_series, export_base_year, export_final_year),
                    auxiliary_ratios,
                    loss_values_by_year,
                    loss_total,
                    loss_values_for_efficiency=series_to_year_dict(
                        total_loss_by_year,
                        export_base_year,
                        export_final_year,
                    ),
                    feedstock_shares=feedstock_shares,
                    input_total=float(total_input_series.sum()),
                    output_import_targets=output_import_targets_total,
                    output_export_targets=output_export_targets_total,
                    own_use_ratios=compute_own_use_ratios_for_record(
                        loss_values_by_year, input_series_map, export_years
                    ),
                )
                append_process_record(process_records, record)
            else:
                primary_input = negative.idxmin()
                input_series = input_series_map.get(primary_input)
                if input_series is None or input_series.empty:
                    print(f"{process_name}: primary input series missing after normalization.")
                    return
                other_feedstock_fuels = [
                    label for label in input_series_map.keys() if label != primary_input
                ]
                auxiliary_fuels = list(other_feedstock_fuels)
                auxiliary_ratios = build_auxiliary_ratios_by_year(
                    timeseries, auxiliary_fuels, output_series
                )
                auxiliary_fuels, auxiliary_ratios = merge_loss_into_auxiliary_by_year(
                    auxiliary_fuels,
                    auxiliary_ratios,
                    loss_values_by_year,
                    output_series,
                    primary_input,
                )
                efficiency_series = compute_efficiency_by_year(
                    output_series,
                    total_input_series,
                    total_loss_by_year,
                )
                print_leap_structure_block(
                    process_name,
                    [output_label],
                    process_name,
                    [primary_input],
                    auxiliary_fuels,
                    loss_fuels=list(loss_values_by_year.keys()),
                    code_to_name_mapping=code_to_name_mapping,
                    output_fuel_values={output_label: output_series.sum()},
                    process_value=f"{efficiency_series.mean():.6f}",
                    feedstock_fuel_values={primary_input: input_series.sum()},
                    auxiliary_fuel_values={
                        label: summarize_numeric_value(values, summary="mean")
                        for label, values in auxiliary_ratios.items()
                    },
                    loss_fuel_values={
                        label: summarize_numeric_value(values, summary="sum")
                        for label, values in loss_values_by_year.items()
                    },
                )
                record = build_process_record(
                    economy,
                    sector_title,
                    process_name,
                    {output_label: series_to_year_dict(output_series, export_base_year, export_final_year)},
                    {primary_input: series_to_year_dict(input_series, export_base_year, export_final_year)},
                    series_to_year_dict(efficiency_series, export_base_year, export_final_year),
                    auxiliary_ratios,
                    loss_values_by_year,
                    loss_total,
                    loss_values_for_efficiency=series_to_year_dict(
                        total_loss_by_year,
                        export_base_year,
                        export_final_year,
                    ),
                    feedstock_shares={primary_input: 1.0},
                    input_total=float(total_input_series.sum()),
                    output_import_targets=output_import_targets_total,
                    output_export_targets=output_export_targets_total,
                )
                append_process_record(process_records, record)

        if "sub2sectors" in esto_data.columns and gas_works_sub2:
            gas_works_output = select_rows(
                esto_data,
                {
                    "economy": economy,
                    "sub2sectors": gas_works_sub2,
                    "subfuels": fuel_codes["gas_works_gas"],
                },
            )
            gas_works_input = select_rows(
                esto_data,
                {"economy": economy, "sub2sectors": gas_works_sub2, "subfuels": fuel_codes["lignite"]},
            )
            gas_works_rows = select_rows(
                esto_data,
                {"economy": economy, "sub2sectors": gas_works_sub2},
            )
        else:
            if gas_works_flow_code:
                gas_works_output = select_rows(
                    esto_data,
                    {
                        "economy": economy,
                        "flows": gas_works_flow_code,
                        "products": product_code_gas_works_gas,
                    },
                )
                gas_works_input = select_rows(
                    esto_data,
                    {
                        "economy": economy,
                        "flows": gas_works_flow_code,
                        "products": product_code_lignite,
                    },
                )
                gas_works_rows = select_rows(
                    esto_data,
                    {"economy": economy, "flows": gas_works_flow_code},
                )
            else:
                gas_works_output = esto_data.iloc[0:0]
                gas_works_input = esto_data.iloc[0:0]
                gas_works_rows = esto_data.iloc[0:0]
        print_sector_rows_from_df(
            gas_works_rows,
            "Gas works rows",
            year_cols,
            start_year,
            code_to_name_mapping,
        )
        output_label = fuel_codes["gas_works_gas"]
        if "products" in esto_data.columns:
            output_label = product_code_gas_works_gas
        gas_works_sector_title = str(
            gas_config.get("title", "Gas works plants")
        ).strip() or "Gas works plants"
        _build_gas_process_records(
            gas_works_sector_title,
            "Gas works plants",
            output_label,
            gas_works_rows,
            gas_works_output,
            gas_works_sub2,
        )

        if "sub2sectors" in esto_data.columns and blending_sub2:
            blending_output = select_rows(
                esto_data,
                {
                    "economy": economy,
                    "sub2sectors": blending_sub2,
                    "subfuels": fuel_codes["natural_gas"],
                },
            )
            blending_input = select_rows(
                esto_data,
                {
                    "economy": economy,
                    "sub2sectors": blending_sub2,
                    "subfuels": fuel_codes["gas_works_gas"],
                },
            )
            blending_rows = select_rows(
                esto_data,
                {"economy": economy, "sub2sectors": blending_sub2},
            )
        else:
            if blending_flow_code:
                blending_output = select_rows(
                    esto_data,
                    {
                        "economy": economy,
                        "flows": blending_flow_code,
                        "products": product_code_natural_gas,
                    },
                )
                blending_input = select_rows(
                    esto_data,
                    {
                        "economy": economy,
                        "flows": blending_flow_code,
                        "products": product_code_gas_works_gas,
                    },
                )
                blending_rows = select_rows(
                    esto_data,
                    {"economy": economy, "flows": blending_flow_code},
                )
            else:
                blending_output = esto_data.iloc[0:0]
                blending_input = esto_data.iloc[0:0]
                blending_rows = esto_data.iloc[0:0]
        print_sector_rows_from_df(
            blending_rows,
            "Natural gas blending rows",
            year_cols,
            start_year,
            code_to_name_mapping,
        )
        output_label = fuel_codes["natural_gas"]
        if "products" in esto_data.columns:
            output_label = product_code_natural_gas
        blending_sector_title = str(
            MAJOR_SECTOR_CONFIG.get("gas_blending", {}).get(
                "title",
                "Natural gas blending plants",
            )
        ).strip() or "Natural gas blending plants"
        _build_gas_process_records(
            blending_sector_title,
            "Natural gas blending plants",
            output_label,
            blending_rows,
            blending_output,
            blending_sub2,
        )

        if PRINT_GAS_PROCESSING_SUMMARY:
            flow_list = [
                code for code in [gas_works_flow_code, blending_flow_code] if code
            ]
            gas_processing_rows = pd.concat(
                [select_flow_rows(esto_data, economy, code) for code in flow_list],
                ignore_index=True,
            ) if flow_list else esto_data.iloc[0:0]
            negatives, positives = summarize_fuels_by_subfuel(
                gas_processing_rows, year_cols, start_year
            )
            if not negatives.empty:
                print("Gas processing inputs by fuel label:")
                print(map_series_index(negatives, code_to_name_mapping).to_string())
            if not positives.empty:
                print("Gas processing outputs by fuel label:")
                print(map_series_index(positives, code_to_name_mapping).to_string())
    except Exception as exc:
        print(f"Gas processing analysis failed: {exc}")
        try_debug_breakpoint()
        raise


def summarize_transformation_flows(
    data,
    year_cols,
    start_year,
    economy,
    flow_codes,
    title,
    code_to_name_mapping,
    loss_data,
    loss_year_cols,
    sector_key,
    process_records=None,
    multi_output=False,
):
    """Summarize transformation flows with primary input/output fuels."""
    try:
        print(f"\n==== {title} ({economy}) ====")
        if not has_required_columns(
            data,
            [["flows", "products"], ["flows", "subfuels", "fuels"]],
            title,
        ):
            return
        flow_list = get_flow_list(data, flow_codes)
        if not flow_list:
            print(f"{title}: no flows configured or found")
            return

        for flow_code in flow_list:
            flow_rows = select_flow_rows(data, economy, flow_code)
            if flow_rows.empty:
                print(f"{flow_code}: no data rows for {economy}; writing zero skeleton.")
                append_process_record(process_records, build_zero_skeleton_record(
                    economy, title, flow_code, None, EXPORT_BASE_YEAR, EXPORT_FINAL_YEAR,
                ))
                continue

            totals, used_all_years = summarize_fuel_totals(
                flow_rows, year_cols, start_year, allow_all_years_fallback=True
            )
            timeseries, _ = summarize_fuel_timeseries(
                flow_rows, year_cols, start_year, allow_all_years_fallback=True
            )
            # Negative totals represent feedstocks/own-use inputs, while positives are outputs.
            negative = totals[totals < 0]
            positive = totals[totals > 0]

            if negative.empty or positive.empty:
                print(f"{flow_code}: missing input/output balance for {start_year}+ and all years; writing zero skeleton.")
                append_process_record(process_records, build_zero_skeleton_record(
                    economy, title, flow_code, None, EXPORT_BASE_YEAR, EXPORT_FINAL_YEAR,
                ))
                continue
            if used_all_years:
                print(f"{flow_code}: no {start_year}+ activity, using all years for summary")

            feedstock_method = resolve_feedstock_method()
            primary_input, primary_output, input_total, output_total = compute_primary_io(
                negative, positive
            )
            # Loss rows come in negative, but build_loss_context returns the absolute values we feed to LEAP.
            loss_series, loss_total, loss_values, loss_values_by_year = build_loss_context(
                loss_data,
                loss_year_cols,
                start_year,
                economy,
                sector_key,
                flow_code=flow_code,
            )
            export_base_year = EXPORT_BASE_YEAR
            export_final_year = EXPORT_FINAL_YEAR
            export_years = list(range(export_base_year, export_final_year + 1))
            # Outputs should already be positive, but we still enforce the year range here.
            output_series = ensure_full_year_series(
                get_label_timeseries(timeseries, primary_output),
                export_base_year,
                export_final_year,
            )
            if multi_output:
                output_series_by_label = {
                    label: ensure_full_year_series(
                        get_label_timeseries(timeseries, label),
                        export_base_year,
                        export_final_year,
                    )
                    for label in positive.index
                }
            else:
                output_series_by_label = {primary_output: output_series}
            input_series_map, zero_sum_labels = build_input_series_map(
                timeseries,
                list(negative.index),
                export_base_year,
                export_final_year,
            )
            if zero_sum_labels:
                log_dropped_input_fuels(economy, flow_code, zero_sum_labels, export_base_year, export_final_year)
            if not input_series_map:
                print(f"[WARN] {flow_code}: no input series available after normalization; writing zero skeleton.")
                # If the summary fell back to years before the export window,
                # its output labels describe historical activity only.  Do not
                # let those labels create present-day LEAP branches: canonical
                # zero Output Share rows are added later from the full-model
                # branch catalog.  This matters when an old ESTO product is not
                # a valid output of the current LEAP module (for example, NZ GTL
                # Other hydrocarbons activity that ended in 1997).
                skeleton_output_labels = (
                    None if used_all_years else list(output_series_by_label.keys())
                )
                append_process_record(process_records, build_zero_skeleton_record(
                    economy,
                    title,
                    flow_code,
                    skeleton_output_labels,
                    export_base_year,
                    export_final_year,
                ))
                continue
            total_input_series = build_total_input_series(input_series_map, export_years)
            total_loss_by_year = sum_loss_values_by_year(loss_values_by_year, export_years)

            input_name = map_code_label(primary_input, code_to_name_mapping)
            output_name = map_code_label(primary_output, code_to_name_mapping)

            print(
                f"{flow_code}: output {output_name} ({output_total:.2f}), "
                f"input {input_name} ({-input_total:.2f})"
            )

            output_import_targets_total, output_export_targets_total = gather_output_target_dicts(
                economy,
                list(output_series_by_label.keys()),
                export_base_year,
                export_final_year,
                output_series_by_fuel=output_series_by_label,
            )

            if feedstock_method == FEEDSTOCK_METHOD_SPLIT:
                feedstock_labels = list(input_series_map.keys())
                for idx, feedstock_label in enumerate(feedstock_labels):
                    input_series = input_series_map[feedstock_label]
                    share_series = build_input_share_series(
                        input_series,
                        total_input_series,
                        fallback_to_one=(idx == 0),
                    )
                    allocated_outputs = allocate_outputs_by_share(
                        output_series_by_label,
                        share_series,
                    )
                    allocated_loss_values = allocate_loss_by_share(
                        loss_values_by_year,
                        share_series,
                    )
                    loss_total_for_eff = total_loss_by_year.mul(share_series, fill_value=0.0)
                    allocated_output_series = allocated_outputs.get(primary_output, pd.Series(dtype=float))
                    efficiency_series = compute_efficiency_by_year(
                        allocated_output_series,
                        input_series,
                        loss_total_for_eff,
                    )
                    auxiliary_fuels, auxiliary_ratios = build_auxiliary_from_losses_by_year(
                        allocated_loss_values,
                        allocated_output_series,
                        feedstock_labels=[feedstock_label],
                    )
                    output_import_targets = {
                        label: scale_year_dict_by_share(values, share_series)
                        for label, values in (output_import_targets_total or {}).items()
                    }
                    output_export_targets = {
                        label: scale_year_dict_by_share(values, share_series)
                        for label, values in (output_export_targets_total or {}).items()
                    }
                    process_name = (
                        flow_code
                        if len(feedstock_labels) == 1
                        else f"{flow_code} - {feedstock_label}"
                    )
                    print_leap_structure_block(
                        f"{title} - {process_name}",
                        [primary_output],
                        process_name,
                        [feedstock_label],
                        auxiliary_fuels,
                        loss_fuels=list(allocated_loss_values.keys()),
                        code_to_name_mapping=code_to_name_mapping,
                        output_fuel_values={
                            primary_output: summarize_numeric_value(
                                series_to_year_dict(allocated_output_series, export_base_year, export_final_year),
                                summary="sum",
                            )
                        },
                        process_value=f"{efficiency_series.mean():.4f}",
                        feedstock_fuel_values={
                            feedstock_label: summarize_numeric_value(
                                series_to_year_dict(input_series, export_base_year, export_final_year),
                                summary="sum",
                            )
                        },
                        auxiliary_fuel_values={
                            label: summarize_numeric_value(values, summary="mean")
                            for label, values in auxiliary_ratios.items()
                        },
                        loss_fuel_values={
                            label: summarize_numeric_value(values, summary="sum")
                            for label, values in allocated_loss_values.items()
                        },
                    )
                    record = build_process_record(
                        economy,
                        title,
                        process_name,
                        {
                            primary_output: series_to_year_dict(
                                allocated_output_series, export_base_year, export_final_year
                            )
                        },
                        {
                            feedstock_label: series_to_year_dict(
                                input_series, export_base_year, export_final_year
                            )
                        },
                        series_to_year_dict(efficiency_series, export_base_year, export_final_year),
                        auxiliary_ratios,
                        allocated_loss_values,
                        float(pd.Series(loss_total_for_eff, dtype=float).sum()),
                        loss_values_for_efficiency=series_to_year_dict(
                            loss_total_for_eff,
                            export_base_year,
                            export_final_year,
                        ),
                        feedstock_shares={feedstock_label: 1.0},
                        input_total=float(input_series.sum()),
                        output_import_targets=output_import_targets,
                        output_export_targets=output_export_targets,
                    )
                    append_process_record(process_records, record)
            elif feedstock_method == FEEDSTOCK_METHOD_MULTI:
                efficiency_output_series = (
                    sum(output_series_by_label.values())
                    if multi_output
                    else output_series
                )
                auxiliary_fuels, auxiliary_ratios = build_auxiliary_from_losses_by_year(
                    loss_values_by_year,
                    efficiency_output_series,
                    feedstock_labels=list(input_series_map.keys()) if LOSS_AUX_EXCLUDE_FEEDSTOCKS else None,
                )
                loss_total_for_eff = total_loss_by_year
                efficiency_series = compute_efficiency_by_year(
                    efficiency_output_series,
                    total_input_series,
                    loss_total_for_eff,
                )
                feedstock_values = {
                    label: series_to_year_dict(series, export_base_year, export_final_year)
                    for label, series in input_series_map.items()
                }
                feedstock_shares = {
                    label: safe_divide_series(series, total_input_series).to_dict()
                    for label, series in input_series_map.items()
                }
                print_leap_structure_block(
                    f"{title} - {flow_code}",
                    list(output_series_by_label.keys()),
                    flow_code,
                    list(feedstock_values.keys()),
                    auxiliary_fuels,
                    loss_fuels=list(loss_values_by_year.keys()),
                    code_to_name_mapping=code_to_name_mapping,
                    output_fuel_values={
                        label: summarize_numeric_value(
                            series_to_year_dict(s, export_base_year, export_final_year),
                            summary="sum",
                        )
                        for label, s in output_series_by_label.items()
                    },
                    process_value=f"{efficiency_series.mean():.4f}",
                    feedstock_fuel_values={
                        label: summarize_numeric_value(values, summary="sum")
                        for label, values in feedstock_values.items()
                    },
                    auxiliary_fuel_values={
                        label: summarize_numeric_value(values, summary="mean")
                        for label, values in auxiliary_ratios.items()
                    },
                    loss_fuel_values={
                        label: summarize_numeric_value(values, summary="sum")
                        for label, values in loss_values_by_year.items()
                    },
                )
                record = build_process_record(
                    economy,
                    title,
                    flow_code,
                    {
                        label: series_to_year_dict(s, export_base_year, export_final_year)
                        for label, s in output_series_by_label.items()
                    },
                    feedstock_values,
                    series_to_year_dict(efficiency_series, export_base_year, export_final_year),
                    auxiliary_ratios,
                    loss_values_by_year,
                    float(loss_total),
                    loss_values_for_efficiency=series_to_year_dict(
                        loss_total_for_eff,
                        export_base_year,
                        export_final_year,
                    ),
                    feedstock_shares=feedstock_shares,
                    input_total=float(total_input_series.sum()),
                    output_import_targets=output_import_targets_total,
                    output_export_targets=output_export_targets_total,
                    own_use_ratios=compute_own_use_ratios_for_record(
                        loss_values_by_year, input_series_map, export_years
                    ),
                )
                append_process_record(process_records, record)
            else:
                other_feedstock_fuels = [
                    label for label in input_series_map.keys() if label != primary_input
                ]
                auxiliary_fuels = list(other_feedstock_fuels)
                auxiliary_ratios = build_auxiliary_ratios_by_year(
                    timeseries, auxiliary_fuels, output_series
                )
                auxiliary_fuels, auxiliary_ratios = merge_loss_into_auxiliary_by_year(
                    auxiliary_fuels,
                    auxiliary_ratios,
                    loss_values_by_year,
                    output_series,
                    primary_input,
                )
                input_series = input_series_map.get(primary_input)
                if input_series is None or input_series.empty:
                    print(f"{flow_code}: primary input series missing after normalization")
                    continue
                loss_total_for_eff = total_loss_by_year
                # Compute efficiency from total process input so auxiliary
                # feedstocks are included in the denominator.
                efficiency_series = compute_efficiency_by_year(
                    output_series,
                    total_input_series,
                    loss_total_for_eff,
                )
                print_leap_structure_block(
                    f"{title} - {flow_code}",
                    [primary_output],
                    flow_code,
                    [primary_input],
                    auxiliary_fuels,
                    loss_fuels=list(loss_values_by_year.keys()),
                    code_to_name_mapping=code_to_name_mapping,
                    output_fuel_values={primary_output: output_total},
                    process_value=f"{efficiency_series.mean():.4f}",
                    feedstock_fuel_values={primary_input: input_total},
                    auxiliary_fuel_values={
                        label: summarize_numeric_value(values, summary="mean")
                        for label, values in auxiliary_ratios.items()
                    },
                    loss_fuel_values={
                        label: summarize_numeric_value(values, summary="sum")
                        for label, values in loss_values_by_year.items()
                    },
                )
                record = build_process_record(
                    economy,
                    title,
                    flow_code,
                    {primary_output: series_to_year_dict(output_series, export_base_year, export_final_year)},
                    {primary_input: series_to_year_dict(input_series, export_base_year, export_final_year)},
                    series_to_year_dict(efficiency_series, export_base_year, export_final_year),
                    auxiliary_ratios,
                    loss_values_by_year,
                    loss_total,
                    loss_values_for_efficiency=series_to_year_dict(
                        loss_total_for_eff,
                        export_base_year,
                        export_final_year,
                    ),
                    feedstock_shares={primary_input: 1.0},
                    input_total=float(total_input_series.sum()),
                    output_import_targets=output_import_targets_total,
                    output_export_targets=output_export_targets_total,
                )
                append_process_record(process_records, record)

            print_sector_rows_from_df(
                flow_rows,
                f"{title} rows ({flow_code})",
                year_cols,
                start_year,
                code_to_name_mapping,
            )

            negatives, positives = summarize_fuels_by_subfuel(
                flow_rows, year_cols, start_year
            )
            if not negatives.empty:
                print("Inputs by fuel label:")
                print(map_series_index(negatives, code_to_name_mapping).to_string())
            if not positives.empty:
                print("Outputs by fuel label:")
                print(map_series_index(positives, code_to_name_mapping).to_string())
    except Exception as exc:
        print(f"{title} flow analysis failed: {exc}")
        try_debug_breakpoint()
        raise


def analyze_hydrogen_transformation(
    data,
    year_cols,
    start_year,
    economy,
    code_to_name_mapping,
    loss_data,
    loss_year_cols,
    sector_config=None,
    process_records=None,
):
    """Build hydrogen transformation process records from 9th sub-sector data."""
    try:
        hydrogen_config = sector_config or MAJOR_SECTOR_CONFIG["hydrogen_transformation"]
        sector_title = hydrogen_config.get("title", "09_13_hydrogen_transformation")
        transformation_sub1 = hydrogen_config.get(
            "transformation_sub1",
            "09_13_hydrogen_transformation",
        )
        output_fuels = set(
            _coerce_label_list(hydrogen_config.get("output_fuels") or ["16_others"])
        )
        default_output_subfuels = _coerce_label_list(
            hydrogen_config.get("output_subfuels") or HYDROGEN_OUTPUT_SUBFUELS
        )
        process_config = hydrogen_config.get("process_config") or HYDROGEN_PROCESS_CONFIG
        if not process_config:
            print(f"{sector_title}: no hydrogen process config found; skipping.")
            return
        print(f"\n==== {sector_title} ({economy}) ====")
        if not has_required_columns(
            data,
            [["sub1sectors", "sub2sectors", "fuels", "subfuels"]],
            sector_title,
        ):
            return

        export_base_year = EXPORT_BASE_YEAR
        export_final_year = EXPORT_FINAL_YEAR
        export_years = list(range(export_base_year, export_final_year + 1))

        enabled_processes = []
        for raw_cfg in process_config:
            if not isinstance(raw_cfg, dict):
                continue
            if not raw_cfg.get("enabled", True):
                continue
            process_code = str(raw_cfg.get("process_code", "")).strip()
            source_sub2 = str(
                raw_cfg.get("source_sub2sectors") or raw_cfg.get("sub2sectors") or process_code
            ).strip()
            if not process_code or not source_sub2:
                continue
            cfg = dict(raw_cfg)
            cfg["process_code"] = process_code
            cfg["source_sub2sectors"] = source_sub2
            cfg["input_fuel_codes"] = _coerce_label_list(cfg.get("input_fuel_codes"))
            cfg["output_subfuels"] = _coerce_label_list(
                cfg.get("output_subfuels") or default_output_subfuels
            )
            cfg["loss_sub2sectors"] = _coerce_label_list(cfg.get("loss_sub2sectors"))
            enabled_processes.append(cfg)
        if not enabled_processes:
            print(f"{sector_title}: no enabled hydrogen process configs.")
            return

        process_groups = {}
        for cfg in enabled_processes:
            process_groups.setdefault(cfg["source_sub2sectors"], []).append(cfg)

        for source_sub2, group_configs in process_groups.items():
            process_rows = select_rows(
                data,
                {
                    "economy": economy,
                    "sub1sectors": transformation_sub1,
                    "sub2sectors": source_sub2,
                },
            )
            if process_rows.empty:
                for _cfg in group_configs:
                    _pname = _cfg.get("process_code", source_sub2)
                    _out_labels = _cfg.get("output_subfuels") or []
                    print(f"{sector_title} ({_pname}): no data rows for {economy}; writing zero skeleton.")
                    append_process_record(process_records, build_zero_skeleton_record(
                        economy, sector_title, _pname, _out_labels,
                        export_base_year, export_final_year,
                    ))
                continue

            print_sector_rows_from_df(
                process_rows,
                f"{sector_title} rows ({source_sub2})",
                year_cols,
                start_year,
                code_to_name_mapping,
            )
            timeseries, _ = summarize_fuel_timeseries(
                process_rows,
                year_cols,
                start_year,
                allow_all_years_fallback=True,
            )
            totals, _ = summarize_fuel_totals(
                process_rows,
                year_cols,
                start_year,
                allow_all_years_fallback=True,
            )
            if timeseries.empty:
                continue
            feedstock_method = resolve_feedstock_method()

            output_rows = process_rows
            if "fuels" in output_rows.columns and output_fuels:
                output_rows = output_rows[output_rows["fuels"].astype(str).isin(output_fuels)]
            output_timeseries, _ = summarize_fuel_timeseries(
                output_rows,
                year_cols,
                start_year,
                allow_all_years_fallback=True,
            )
            group_output_labels = []
            for cfg in group_configs:
                for label in cfg["output_subfuels"]:
                    if label not in group_output_labels:
                        group_output_labels.append(label)
            source_output_series = {}
            for output_label in group_output_labels:
                series = ensure_full_year_series(
                    to_output_only_series(get_label_timeseries(output_timeseries, output_label)),
                    export_base_year,
                    export_final_year,
                )
                if series.sum() == 0:
                    continue
                source_output_series[output_label] = series
            if not source_output_series:
                # All output series are zero for this scenario (a legitimate zero
                # pathway); keep the process present with a zero skeleton so
                # scenario coverage stays symmetric across scenarios.
                for _cfg in group_configs:
                    _pname = _cfg.get("process_code", source_sub2)
                    print(
                        f"{sector_title} ({_pname}): all output series zero for "
                        f"{economy}; writing zero skeleton for scenario coverage."
                    )
                    append_process_record(process_records, build_zero_skeleton_record(
                        economy, sector_title, _pname,
                        _cfg.get("output_subfuels") or [],
                        export_base_year, export_final_year,
                    ))
                continue

            process_inputs = {}
            negative_labels = list(totals[totals < 0].index)
            input_series_map_all, zero_sum_labels = build_input_series_map(
                timeseries,
                negative_labels,
                export_base_year,
                export_final_year,
            )
            if zero_sum_labels:
                log_dropped_input_fuels(economy, "hydrogen_transformation", zero_sum_labels, export_base_year, export_final_year)
            for cfg in group_configs:
                input_series_by_label = dict(input_series_map_all)
                input_total_series = build_total_input_series(
                    input_series_by_label,
                    export_years,
                )
                process_inputs[cfg["process_code"]] = {
                    "config": cfg,
                    "input_series_by_label": input_series_by_label,
                    "input_total_series": input_total_series,
                }

            group_total_input = _sum_series_collection(
                [
                    details["input_total_series"]
                    for details in process_inputs.values()
                ],
                export_years,
            )
            process_codes = [cfg["process_code"] for cfg in group_configs]

            for index, process_code in enumerate(process_codes):
                details = process_inputs.get(process_code, {})
                cfg = details.get("config")
                input_series_by_label = details.get("input_series_by_label", {})
                input_total_series = details.get("input_total_series")
                if cfg is None or input_total_series is None:
                    continue
                if not input_series_by_label:
                    continue

                share_series = safe_divide_series(input_total_series, group_total_input)
                if index == 0:
                    zero_mask = group_total_input.eq(0.0)
                    if zero_mask.any():
                        share_series = share_series.where(~zero_mask, 1.0)

                output_series_by_label = {}
                for output_label, series in source_output_series.items():
                    allocated = series.mul(share_series, fill_value=0.0)
                    if allocated.sum() == 0:
                        continue
                    output_series_by_label[output_label] = allocated
                total_output_series = _sum_series_collection(
                    list(output_series_by_label.values()),
                    export_years,
                )

                if total_output_series.sum() == 0 and input_total_series.sum() == 0:
                    continue

                loss_values_by_year, _ = _build_hydrogen_loss_context(
                    loss_data,
                    loss_year_cols,
                    start_year,
                    economy,
                    cfg.get("loss_sub2sectors"),
                )
                total_loss_by_year = sum_loss_values_by_year(loss_values_by_year, export_years)
                output_import_targets_total, output_export_targets_total = gather_output_target_dicts(
                    economy,
                    list(output_series_by_label.keys()),
                    export_base_year,
                    export_final_year,
                    output_series_by_fuel=output_series_by_label,
                )

                if feedstock_method == FEEDSTOCK_METHOD_SPLIT:
                    feedstock_labels = list(input_series_by_label.keys())
                    for idx, feedstock_label in enumerate(feedstock_labels):
                        input_series = input_series_by_label[feedstock_label]
                        feedstock_share_series = build_input_share_series(
                            input_series,
                            input_total_series,
                            fallback_to_one=(idx == 0),
                        )
                        allocated_outputs = allocate_outputs_by_share(
                            output_series_by_label,
                            feedstock_share_series,
                        )
                        allocated_output_total = _sum_series_collection(
                            list(allocated_outputs.values()),
                            export_years,
                        )
                        allocated_loss_values = allocate_loss_by_share(
                            loss_values_by_year,
                            feedstock_share_series,
                        )
                        loss_total_for_eff = total_loss_by_year.mul(
                            feedstock_share_series,
                            fill_value=0.0,
                        )
                        efficiency_series = compute_efficiency_by_year(
                            allocated_output_total,
                            input_series,
                            loss_total_for_eff,
                        )
                        auxiliary_fuels, auxiliary_ratios = build_auxiliary_from_losses_by_year(
                            allocated_loss_values,
                            allocated_output_total,
                            feedstock_labels=[feedstock_label],
                        )
                        output_import_targets = {
                            label: scale_year_dict_by_share(values, feedstock_share_series)
                            for label, values in (output_import_targets_total or {}).items()
                        }
                        output_export_targets = {
                            label: scale_year_dict_by_share(values, feedstock_share_series)
                            for label, values in (output_export_targets_total or {}).items()
                        }
                        process_name = (
                            cfg["process_code"]
                            if len(feedstock_labels) == 1
                            else f"{cfg['process_code']} - {feedstock_label}"
                        )
                        print_leap_structure_block(
                            f"{sector_title} - {process_name}",
                            list(allocated_outputs.keys()),
                            process_name,
                            [feedstock_label],
                            auxiliary_fuels,
                            loss_fuels=list(allocated_loss_values.keys()),
                            code_to_name_mapping=code_to_name_mapping,
                            output_fuel_values={
                                label: series.sum() for label, series in allocated_outputs.items()
                            },
                            process_value=f"{efficiency_series.mean():.4f}",
                            feedstock_fuel_values={feedstock_label: input_series.sum()},
                            auxiliary_fuel_values={
                                label: summarize_numeric_value(values, summary="mean")
                                for label, values in auxiliary_ratios.items()
                            },
                            loss_fuel_values={
                                label: summarize_numeric_value(values, summary="sum")
                                for label, values in allocated_loss_values.items()
                            },
                        )
                        append_process_record(
                            process_records,
                            build_process_record(
                                economy,
                                sector_title,
                                process_name,
                                {
                                    label: series_to_year_dict(
                                        series, export_base_year, export_final_year
                                    )
                                    for label, series in allocated_outputs.items()
                                },
                                {
                                    feedstock_label: series_to_year_dict(
                                        input_series, export_base_year, export_final_year
                                    )
                                },
                                series_to_year_dict(
                                    efficiency_series,
                                    export_base_year,
                                    export_final_year,
                                ),
                                auxiliary_ratios,
                                allocated_loss_values,
                                float(pd.Series(loss_total_for_eff, dtype=float).sum()),
                                loss_values_for_efficiency=series_to_year_dict(
                                    loss_total_for_eff,
                                    export_base_year,
                                    export_final_year,
                                ),
                                feedstock_shares={feedstock_label: 1.0},
                                input_total=input_series.sum(),
                                output_import_targets=output_import_targets,
                                output_export_targets=output_export_targets,
                            ),
                        )
                elif feedstock_method == FEEDSTOCK_METHOD_MULTI:
                    auxiliary_fuels, auxiliary_ratios = build_auxiliary_from_losses_by_year(
                        loss_values_by_year,
                        total_output_series,
                        feedstock_labels=list(input_series_by_label.keys()) if LOSS_AUX_EXCLUDE_FEEDSTOCKS else None,
                    )
                    efficiency_series = compute_efficiency_by_year(
                        total_output_series,
                        input_total_series,
                        total_loss_by_year,
                    )
                    feedstock_values = {
                        label: series_to_year_dict(series, export_base_year, export_final_year)
                        for label, series in input_series_by_label.items()
                    }
                    feedstock_shares = {
                        label: safe_divide_series(series, input_total_series).to_dict()
                        for label, series in input_series_by_label.items()
                    }
                    output_values = {
                        label: series_to_year_dict(series, export_base_year, export_final_year)
                        for label, series in output_series_by_label.items()
                    }
                    print_leap_structure_block(
                        f"{sector_title} - {cfg['process_code']}",
                        list(output_values.keys()),
                        cfg["process_code"],
                        list(feedstock_values.keys()),
                        auxiliary_fuels,
                        loss_fuels=list(loss_values_by_year.keys()),
                        code_to_name_mapping=code_to_name_mapping,
                        output_fuel_values={
                            label: series.sum() for label, series in output_series_by_label.items()
                        },
                        process_value=f"{efficiency_series.mean():.4f}",
                        feedstock_fuel_values={
                            label: series.sum() for label, series in input_series_by_label.items()
                        },
                        auxiliary_fuel_values={
                            label: summarize_numeric_value(values, summary="mean")
                            for label, values in auxiliary_ratios.items()
                        },
                        loss_fuel_values={
                            label: summarize_numeric_value(values, summary="sum")
                            for label, values in loss_values_by_year.items()
                        },
                    )
                    append_process_record(
                        process_records,
                        build_process_record(
                            economy,
                            sector_title,
                            cfg["process_code"],
                            output_values,
                            feedstock_values,
                            series_to_year_dict(
                                efficiency_series,
                                export_base_year,
                                export_final_year,
                            ),
                            auxiliary_ratios,
                            loss_values_by_year,
                            float(pd.Series(total_loss_by_year, dtype=float).sum()),
                            loss_values_for_efficiency=series_to_year_dict(
                                total_loss_by_year,
                                export_base_year,
                                export_final_year,
                            ),
                            feedstock_shares=feedstock_shares,
                            input_total=input_total_series.sum(),
                            output_import_targets=output_import_targets_total,
                            output_export_targets=output_export_targets_total,
                            own_use_ratios=compute_own_use_ratios_for_record(
                                loss_values_by_year, input_series_by_label, export_years
                            ),
                        ),
                    )
                else:
                    primary_input = max(
                        input_series_by_label,
                        key=lambda label: input_series_by_label[label].sum(),
                    )
                    input_series = input_series_by_label.get(primary_input)
                    if input_series is None or input_series.sum() == 0:
                        continue
                    auxiliary_fuels = [
                        label for label in input_series_by_label.keys() if label != primary_input
                    ]
                    auxiliary_ratios = build_auxiliary_ratios_by_year(
                        timeseries,
                        auxiliary_fuels,
                        total_output_series,
                    )
                    auxiliary_fuels, auxiliary_ratios = merge_loss_into_auxiliary_by_year(
                        auxiliary_fuels,
                        auxiliary_ratios,
                        loss_values_by_year,
                        total_output_series,
                        primary_input,
                    )
                    # Use total process input for efficiency so years where the
                    # chosen primary fuel is zero do not inflate efficiency.
                    efficiency_series = compute_efficiency_by_year(
                        total_output_series,
                        input_total_series,
                        total_loss_by_year,
                    )
                    output_values = {
                        label: series_to_year_dict(series, export_base_year, export_final_year)
                        for label, series in output_series_by_label.items()
                    }
                    print_leap_structure_block(
                        f"{sector_title} - {cfg['process_code']}",
                        list(output_values.keys()),
                        cfg["process_code"],
                        [primary_input],
                        auxiliary_fuels,
                        loss_fuels=list(loss_values_by_year.keys()),
                        code_to_name_mapping=code_to_name_mapping,
                        output_fuel_values={
                            label: series.sum() for label, series in output_series_by_label.items()
                        },
                        process_value=f"{efficiency_series.mean():.4f}",
                        feedstock_fuel_values={primary_input: input_series.sum()},
                        auxiliary_fuel_values={
                            label: summarize_numeric_value(values, summary="mean")
                            for label, values in auxiliary_ratios.items()
                        },
                        loss_fuel_values={
                            label: summarize_numeric_value(values, summary="sum")
                            for label, values in loss_values_by_year.items()
                        },
                    )
                    append_process_record(
                        process_records,
                        build_process_record(
                            economy,
                            sector_title,
                            cfg["process_code"],
                            output_values,
                            {primary_input: series_to_year_dict(input_series, export_base_year, export_final_year)},
                            series_to_year_dict(
                                efficiency_series,
                                export_base_year,
                                export_final_year,
                            ),
                            auxiliary_ratios,
                            loss_values_by_year,
                            float(pd.Series(total_loss_by_year, dtype=float).sum()),
                            loss_values_for_efficiency=series_to_year_dict(
                                total_loss_by_year,
                                export_base_year,
                                export_final_year,
                            ),
                            feedstock_shares={primary_input: 1.0},
                            input_total=input_series.sum(),
                            output_import_targets=output_import_targets_total,
                            output_export_targets=output_export_targets_total,
                        ),
                    )
    except Exception as exc:
        print(f"Hydrogen transformation analysis failed: {exc}")
        try_debug_breakpoint()
        raise



# ---------------------------------------------------------------------------
# Deferred imports from transformation_analysis_utils (TAU).
# These come AFTER all function definitions so that when TSA is imported
# while TAU is still initializing (circular import), Python can define all
# functions first, then satisfy the TAU imports once TAU is fully loaded.
# All symbols listed here are referenced as bare names inside the function
# bodies above and are resolved via the module globals dict at call time.
# noqa: E402 because these imports appear after module-level code.
# ---------------------------------------------------------------------------
from codebase.functions.transformation_analysis_utils import (  # noqa: F401, E402
    # constants
    MAJOR_SECTOR_CONFIG,
    EXPORT_BASE_YEAR,
    EXPORT_FINAL_YEAR,
    FEEDSTOCK_METHOD_SPLIT,
    FEEDSTOCK_METHOD_MULTI,
    FEEDSTOCK_METHOD,
    FEEDSTOCK_METHOD_SINGLE_AUX,
    LOSS_AUX_EXCLUDE_FEEDSTOCKS,
    INCLUDE_ALL_DETECTED_INPUT_FUELS,
    ESTO_IMPORT_SECTOR_LABEL,
    ESTO_EXPORT_SECTOR_LABEL,
    TRANSFORMATION_OUTPUT_VARIABLES,
    LOSS_SECTOR_CODE_9TH,
    PRINT_SECTOR_ROWS,
    PRINT_TOP_FUEL_ROWS,
    PRINT_ONLY_NONZERO_ROWS,
    ENABLE_DEBUG_BREAKPOINTS,
    DEFAULT_REGION,
    DEFAULT_OUTPUT_UNITS,
    DEFAULT_EFFICIENCY_UNITS,
    DEFAULT_FEEDSTOCK_UNITS,
    DEFAULT_FEEDSTOCK_SCALE,
    DEFAULT_AUXILIARY_UNITS,
    DEFAULT_AUXILIARY_PER,
    AUXILIARY_THRESHOLD_RATIO,
    INCLUDE_ALL_AUXILIARY,
    PRINT_GAS_PROCESSING_SUMMARY,
    HYDROGEN_OUTPUT_SUBFUELS,
    HYDROGEN_PROCESS_CONFIG,
    # helper functions
    select_rows,
    _normalize_economy_value,
    print_sector_rows,
    print_sector_rows_from_df,
    _match_est_product_label,
    _filter_est_import_export_rows,
    build_est_output_target_dict,
    gather_output_target_dicts,
    resolve_feedstock_method,
    build_input_series_map,
    log_dropped_input_fuels,
    get_dropped_fuel_log,
    reset_dropped_fuel_log,
    get_analyzed_sector_titles,
    reset_analyzed_sector_titles,
    print_dropped_fuel_summary,
    save_dropped_fuel_report,
    build_loss_context,
    summarize_own_use_losses,
    summarize_own_use_losses_by_year,
    get_flow_list,
    select_flow_rows,
    summarize_loss_sectors,
    calculate_efficiency,
    calculate_aux_fuel_use,
)
