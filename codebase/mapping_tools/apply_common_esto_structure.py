#%%
"""
Apply the generated common ESTO structure to ESTO-shaped source data.

Input data should already be converted to ESTO-style rows with source_system,
economy, scenario, year, ESTO flow/product, and value columns.
"""

#%%
from pathlib import Path

import pandas as pd

#%%
OUTPUT_COLUMNS = [
    "comparison_scope",
    "source_system",
    "economy",
    "scenario",
    "year",
    "common_flow_code",
    "common_flow_name",
    "common_flow_label",
    "common_product_code",
    "common_product_name",
    "common_product_label",
    "value",
]
COMPARISON_INTERNAL_COLUMNS = [
    "common_row_id",
    "common_component_count",
    "common_flow_component_count",
    "common_product_component_count",
]
WIDE_OUTPUT_ID_COLUMNS = ["economy", "scenario", "product", "flow"]
SOURCE_VALUE_COLUMNS = ["source_system", "economy", "scenario", "year", "esto_flow", "esto_product", "value"]
SOURCE_VALUE_SCOPE_COLUMNS = ["comparison_scope"] + SOURCE_VALUE_COLUMNS
TOTAL_GROUP_COLUMNS = ["comparison_scope", "source_system", "economy", "scenario", "year"]
SUBTOTAL_KEYWORDS = ["total", "subtotal"]
BROAD_COMMON_ROW_COMPONENT_LIMIT = 50
ACTIVE_COMPONENT_ABS_TOLERANCE = 0.0

#%%
def _find_repo_root(start_path: Path) -> Path:
    """Find the leap_utilities repo root from a nested workflow path."""
    for candidate in [start_path, *start_path.parents]:
        if (candidate / "AGENTS.md").exists():
            return candidate
    raise FileNotFoundError(f"Could not find repo root above: {start_path}")


def read_table_if_exists(path: Path) -> pd.DataFrame:
    """Read CSV/XLSX input if it exists, otherwise return an empty table."""
    if not path.exists():
        return pd.DataFrame()
    if path.suffix.lower() in {".xlsx", ".xlsm", ".xls"}:
        return pd.read_excel(path)
    return pd.read_csv(path)


def normalise_source_columns(source_df: pd.DataFrame, default_source_system: str, default_economy: str) -> pd.DataFrame:
    """Normalise a source table to source_system/economy/scenario/year/esto/value columns."""
    if source_df.empty:
        return pd.DataFrame(columns=SOURCE_VALUE_COLUMNS)
    working_df = source_df.copy()
    rename_map = {}
    if "target_flow" in working_df.columns and "esto_flow" not in working_df.columns:
        rename_map["target_flow"] = "esto_flow"
    if "target_product" in working_df.columns and "esto_product" not in working_df.columns:
        rename_map["target_product"] = "esto_product"
    if "component_esto_flow" in working_df.columns and "esto_flow" not in working_df.columns:
        rename_map["component_esto_flow"] = "esto_flow"
    if "component_esto_product" in working_df.columns and "esto_product" not in working_df.columns:
        rename_map["component_esto_product"] = "esto_product"
    if "value_pj" in working_df.columns and "value" not in working_df.columns:
        rename_map["value_pj"] = "value"
    working_df = working_df.rename(columns=rename_map)

    if "source_system" not in working_df.columns:
        working_df["source_system"] = default_source_system
    if "economy" not in working_df.columns:
        working_df["economy"] = default_economy
    for column in ["scenario", "year"]:
        if column not in working_df.columns:
            working_df[column] = ""

    missing_columns = [column for column in ["esto_flow", "esto_product", "value"] if column not in working_df.columns]
    if missing_columns:
        raise ValueError(f"Source data for {default_source_system} is missing required columns: {missing_columns}")

    working_df["value"] = pd.to_numeric(working_df["value"], errors="coerce").fillna(0)
    if "comparison_scope" in working_df.columns:
        return working_df[SOURCE_VALUE_SCOPE_COLUMNS].copy()
    return working_df[SOURCE_VALUE_COLUMNS].copy()


def read_source_tables(source_paths: dict[str, Path], default_economy: str) -> pd.DataFrame:
    """Read and concatenate available ESTO-shaped source tables."""
    frames: list[pd.DataFrame] = []
    for source_system, path in source_paths.items():
        source_df = read_table_if_exists(path)
        if source_df.empty:
            print(f"Skipped missing or empty {source_system} source data: {path}")
            continue
        frames.append(normalise_source_columns(source_df, default_source_system=source_system, default_economy=default_economy))
        print(f"{source_system} ESTO-shaped rows read: {len(source_df):,}")
    if not frames:
        return pd.DataFrame(columns=SOURCE_VALUE_COLUMNS)
    return pd.concat(frames, ignore_index=True)


def split_code_name(label: object) -> tuple[str, str]:
    """Split an ESTO label into leading code and display name."""
    text = "" if pd.isna(label) else str(label).strip()
    if not text:
        return "", ""
    parts = text.split(" ", 1)
    if len(parts) == 1:
        return text, text
    return parts[0].strip(), parts[1].strip()


def code_sort_key(code: str) -> tuple[object, ...]:
    """Sort dotted numeric-ish ESTO codes in a stable human order."""
    parts: list[object] = []
    for part in str(code).replace("-", ".").split("."):
        if not part:
            continue
        parts.append(int(part) if part.isdigit() else part)
    return tuple(parts)


def compress_codes(codes: list[str]) -> str:
    """Compress adjacent dotted codes like 01.02, 01.03, 01.04 into 01.02-01.04."""
    cleaned_codes = sorted({str(code).strip() for code in codes if str(code).strip()}, key=code_sort_key)
    if not cleaned_codes:
        return ""

    ranges: list[str] = []
    start = cleaned_codes[0]
    previous = cleaned_codes[0]

    def adjacent(left: str, right: str) -> bool:
        left_prefix, _, left_tail = left.rpartition(".")
        right_prefix, _, right_tail = right.rpartition(".")
        if not left_prefix or left_prefix != right_prefix:
            return False
        if not left_tail.isdigit() or not right_tail.isdigit():
            return False
        return int(right_tail) == int(left_tail) + 1

    for code in cleaned_codes[1:]:
        if adjacent(previous, code):
            previous = code
            continue
        ranges.append(start if start == previous else f"{start}-{previous}")
        start = code
        previous = code
    ranges.append(start if start == previous else f"{start}-{previous}")
    return ",".join(ranges)


def make_label(code: str, name: str) -> str:
    """Combine code and name while tolerating missing names."""
    if code and name:
        return f"{code} {name}"
    return code or name


def nonzero_source_rows(source_df: pd.DataFrame, active_component_abs_tolerance: float) -> pd.DataFrame:
    """Drop zero-value rows before data-aware component pruning and mapping."""
    if source_df.empty:
        return source_df.copy()
    value_abs = pd.to_numeric(source_df["value"], errors="coerce").fillna(0).abs()
    return source_df[value_abs > active_component_abs_tolerance].copy()


def relabel_common_rows_for_active_components(
    source_df: pd.DataFrame,
    common_rows_df: pd.DataFrame,
    active_component_abs_tolerance: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Prune inactive component pairs and recalculate common labels for this run."""
    active_source_df = nonzero_source_rows(source_df, active_component_abs_tolerance)
    if active_source_df.empty or common_rows_df.empty:
        return common_rows_df.copy(), pd.DataFrame()

    active_pairs_df = active_source_df[["esto_flow", "esto_product"]].drop_duplicates().rename(
        columns={
            "esto_flow": "component_esto_flow",
            "esto_product": "component_esto_product",
        }
    )
    working_df = common_rows_df.merge(
        active_pairs_df.assign(_active_component=True),
        on=["component_esto_flow", "component_esto_product"],
        how="left",
    )
    active_mask = working_df["_active_component"].fillna(False).astype(bool)
    pruned_df = working_df[~active_mask].drop(columns=["_active_component"]).copy()
    adjusted_df = working_df[active_mask].drop(columns=["_active_component"]).copy()
    if pruned_df.empty or adjusted_df.empty:
        return adjusted_df, pruned_df

    for boolean_column in ["is_exact_row", "requires_rollup"]:
        if boolean_column in adjusted_df.columns:
            adjusted_df[boolean_column] = adjusted_df[boolean_column].astype(object)

    pruned_df["prune_status"] = "component_not_applicable_for_current_source_data"
    pruned_df["prune_reason"] = "exact_esto_flow_product_pair_has_no_nonzero_rows_in_any_source_data"

    return adjusted_df, pruned_df


def save_component_pruning_diagnostics(pruned_components_df: pd.DataFrame, output_dir: Path) -> None:
    """Write diagnostics for components pruned as not applicable for this run."""
    diagnostics_dir = output_dir / "diagnostics"
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    pruned_components_df.to_csv(diagnostics_dir / "common_esto_components_pruned_not_applicable.csv", index=False)


def apply_common_structure(source_df: pd.DataFrame, common_rows_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Join ESTO-shaped source rows to common rows and aggregate values."""
    if source_df.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS), pd.DataFrame()
    map_columns = [
        "comparison_scope",
        "component_esto_flow",
        "component_esto_product",
        "common_row_id",
        "common_flow_code",
        "common_flow_name",
        "common_flow_label",
        "common_product_code",
        "common_product_name",
        "common_product_label",
        "component_sign",
    ]
    map_df = common_rows_df[map_columns].drop_duplicates().copy()
    component_counts_df = (
        common_rows_df.groupby(["comparison_scope", "common_row_id"], dropna=False)
        .agg(
            common_component_count=("component_esto_product", "size"),
            common_flow_component_count=("component_esto_flow", "nunique"),
            common_product_component_count=("component_esto_product", "nunique"),
        )
        .reset_index()
    )
    map_df = map_df.merge(component_counts_df, on=["comparison_scope", "common_row_id"], how="left")
    if "comparison_scope" not in source_df.columns:
        scopes_df = map_df[["comparison_scope"]].drop_duplicates()
        source_df = source_df.merge(scopes_df, how="cross")
    merged_df = source_df.merge(
        map_df,
        left_on=["comparison_scope", "esto_flow", "esto_product"],
        right_on=["comparison_scope", "component_esto_flow", "component_esto_product"],
        how="left",
    )
    missing_map_df = merged_df[merged_df["common_row_id"].isna()].copy()
    mapped_df = merged_df.dropna(subset=["common_row_id"]).copy()
    mapped_df["component_sign"] = pd.to_numeric(mapped_df["component_sign"], errors="coerce").fillna(1)
    mapped_df["value"] = mapped_df["value"] * mapped_df["component_sign"]
    group_columns = OUTPUT_COLUMNS[:-1] + COMPARISON_INTERNAL_COLUMNS
    comparison_df = (
        mapped_df.groupby(group_columns, dropna=False, as_index=False)["value"]
        .sum()
        .sort_values(OUTPUT_COLUMNS[:-1])
        .reset_index(drop=True)
    )
    return comparison_df, missing_map_df


def is_subtotal_label(value: object) -> bool:
    """Return True for labels that should be filtered from final outputs."""
    text = "" if pd.isna(value) else str(value).strip().lower()
    return any(keyword in text for keyword in SUBTOTAL_KEYWORDS)


def split_subtotal_rows(comparison_df: pd.DataFrame, exclude_subtotal_rows: bool) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split final comparison rows into kept rows and subtotal/total audit rows."""
    if comparison_df.empty or not exclude_subtotal_rows:
        return comparison_df.copy(), pd.DataFrame(columns=list(comparison_df.columns) + ["subtotal_filter_reason"])

    flow_mask = comparison_df["common_flow_label"].map(is_subtotal_label)
    product_mask = comparison_df["common_product_label"].map(is_subtotal_label)
    subtotal_mask = flow_mask | product_mask
    subtotal_df = comparison_df[subtotal_mask].copy()
    kept_df = comparison_df[~subtotal_mask].copy()
    if not subtotal_df.empty:
        subtotal_df["subtotal_filter_reason"] = ""
        subtotal_df.loc[flow_mask[subtotal_mask].values, "subtotal_filter_reason"] = "common_flow_label_contains_total_or_subtotal"
        both_mask = flow_mask & product_mask
        subtotal_df.loc[both_mask[subtotal_mask].values, "subtotal_filter_reason"] = "common_flow_and_product_labels_contain_total_or_subtotal"
        product_only_mask = product_mask & ~flow_mask
        subtotal_df.loc[product_only_mask[subtotal_mask].values, "subtotal_filter_reason"] = "common_product_label_contains_total_or_subtotal"
    return kept_df, subtotal_df


def build_broad_common_row_diagnostics(
    common_rows_df: pd.DataFrame,
    comparison_df: pd.DataFrame,
    broad_component_limit: int,
) -> dict[str, pd.DataFrame]:
    """Build diagnostics for broad common rows that need mapping review."""
    component_counts_df = (
        common_rows_df.groupby(
            [
                "common_row_id",
                "common_flow_label",
                "common_product_label",
                "aggregation_reason",
                "aggregate_group_source",
                "aggregate_group_source_id",
            ],
            dropna=False,
        )
        .agg(
            exact_component_count=("component_esto_product", "size"),
            exact_flow_count=("component_esto_flow", "nunique"),
            exact_product_count=("component_esto_product", "nunique"),
        )
        .reset_index()
    )
    broad_summary_df = component_counts_df[
        component_counts_df["exact_component_count"] > broad_component_limit
    ].copy()
    if broad_summary_df.empty:
        return {
            "broad_common_row_summary": broad_summary_df,
            "broad_common_row_components": pd.DataFrame(),
            "broad_common_row_affected_output": pd.DataFrame(),
        }

    broad_summary_df["qa_status"] = "mapping_revision_required"
    broad_summary_df["qa_severity"] = "high"
    broad_summary_df["qa_reason"] = (
        "common row has too many exact ESTO components; likely caused by crossing aggregate mappings"
    )
    broad_ids = set(broad_summary_df["common_row_id"])
    broad_components_df = common_rows_df[common_rows_df["common_row_id"].isin(broad_ids)].copy()
    affected_output_df = comparison_df[comparison_df["common_row_id"].isin(broad_ids)].copy()
    return {
        "broad_common_row_summary": broad_summary_df,
        "broad_common_row_components": broad_components_df,
        "broad_common_row_affected_output": affected_output_df,
    }


def save_broad_common_row_diagnostics(
    diagnostics: dict[str, pd.DataFrame],
    output_dir: Path,
) -> None:
    """Write broad common row diagnostics as CSVs and one workbook."""
    diagnostics_dir = output_dir / "diagnostics"
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    for name, df in diagnostics.items():
        df.to_csv(diagnostics_dir / f"{name}.csv", index=False)
    with pd.ExcelWriter(diagnostics_dir / "broad_common_row_diagnostics.xlsx", engine="openpyxl") as writer:
        for name, df in diagnostics.items():
            df.to_excel(writer, sheet_name=name[:31], index=False)


def raise_if_broad_common_rows(
    diagnostics: dict[str, pd.DataFrame],
    output_dir: Path,
) -> None:
    """Raise a mapping-review error when broad common rows are present."""
    summary_df = diagnostics["broad_common_row_summary"]
    if summary_df.empty:
        return
    save_broad_common_row_diagnostics(diagnostics, output_dir)
    max_components = int(summary_df["exact_component_count"].max())
    raise ValueError(
        "Broad common ESTO rows require mapping review before final output can be written. "
        f"Broad rows: {len(summary_df):,}; max exact components in one row: {max_components:,}. "
        f"Diagnostics written to: {output_dir / 'diagnostics'}"
    )


def broad_common_row_error_message(
    diagnostics: dict[str, pd.DataFrame],
    output_dir: Path,
) -> str:
    """Return an error message for broad common rows, or blank if none exist."""
    summary_df = diagnostics["broad_common_row_summary"]
    if summary_df.empty:
        return ""
    save_broad_common_row_diagnostics(diagnostics, output_dir)
    max_components = int(summary_df["exact_component_count"].max())
    return (
        "Broad common ESTO rows require mapping review. "
        f"Broad rows: {len(summary_df):,}; max exact components in one row: {max_components:,}. "
        f"Diagnostics written to: {output_dir / 'diagnostics'}"
    )


def build_intersecting_axis_group_diagnostics(
    adjusted_common_rows_df: pd.DataFrame,
    comparison_df: pd.DataFrame,
    axis: str,
) -> pd.DataFrame:
    """Find overlapping product or flow groups in final output rows."""
    if comparison_df.empty:
        return pd.DataFrame()
    if axis == "product":
        label_column = "common_product_label"
        component_column = "component_esto_product"
    elif axis == "flow":
        label_column = "common_flow_label"
        component_column = "component_esto_flow"
    else:
        raise ValueError(f"Unsupported axis for intersection check: {axis}")

    active_common_ids = set(comparison_df["common_row_id"].dropna().astype(str))
    active_components_df = adjusted_common_rows_df[
        adjusted_common_rows_df["common_row_id"].astype(str).isin(active_common_ids)
    ].copy()
    if active_components_df.empty:
        return pd.DataFrame()

    group_rows: list[dict[str, object]] = []
    for label, group_df in active_components_df.groupby(label_column, dropna=False):
        components = sorted(set(group_df[component_column].dropna().astype(str)))
        if not components:
            continue
        group_rows.append(
            {
                "axis": axis,
                "group_label": str(label),
                "component_set": set(components),
                "component_count": len(components),
                "common_row_ids": "|".join(sorted(set(group_df["common_row_id"].dropna().astype(str)))),
            }
        )

    diagnostics_rows: list[dict[str, object]] = []
    for left_index, left in enumerate(group_rows):
        for right in group_rows[left_index + 1 :]:
            intersection = left["component_set"] & right["component_set"]
            if not intersection:
                continue
            if left["component_set"] == right["component_set"]:
                continue
            diagnostics_rows.append(
                {
                    "axis": axis,
                    "left_group_label": left["group_label"],
                    "right_group_label": right["group_label"],
                    "left_component_count": left["component_count"],
                    "right_component_count": right["component_count"],
                    "intersection_component_count": len(intersection),
                    "intersection_components": "|".join(sorted(intersection)),
                    "left_only_components": "|".join(sorted(left["component_set"] - right["component_set"])),
                    "right_only_components": "|".join(sorted(right["component_set"] - left["component_set"])),
                    "left_common_row_ids": left["common_row_ids"],
                    "right_common_row_ids": right["common_row_ids"],
                    "qa_status": "mapping_revision_required",
                    "qa_severity": "high",
                    "qa_reason": f"intersecting_common_{axis}_groups_are_not_allowed",
                }
            )
    return pd.DataFrame(diagnostics_rows)


def save_intersecting_axis_group_diagnostics(
    product_diagnostics_df: pd.DataFrame,
    flow_diagnostics_df: pd.DataFrame,
    output_dir: Path,
) -> None:
    """Write intersecting flow/product group diagnostics."""
    diagnostics_dir = output_dir / "diagnostics"
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    product_diagnostics_df.to_csv(diagnostics_dir / "intersecting_common_product_groups.csv", index=False)
    flow_diagnostics_df.to_csv(diagnostics_dir / "intersecting_common_flow_groups.csv", index=False)
    with pd.ExcelWriter(diagnostics_dir / "intersecting_common_axis_groups.xlsx", engine="openpyxl") as writer:
        product_diagnostics_df.to_excel(writer, sheet_name="product_group_overlaps", index=False)
        flow_diagnostics_df.to_excel(writer, sheet_name="flow_group_overlaps", index=False)


def intersecting_axis_group_error_message(
    adjusted_common_rows_df: pd.DataFrame,
    comparison_df: pd.DataFrame,
    output_dir: Path,
) -> str:
    """Return an error message if final flow/product groups intersect."""
    product_diagnostics_df = build_intersecting_axis_group_diagnostics(
        adjusted_common_rows_df,
        comparison_df,
        axis="product",
    )
    flow_diagnostics_df = build_intersecting_axis_group_diagnostics(
        adjusted_common_rows_df,
        comparison_df,
        axis="flow",
    )
    if product_diagnostics_df.empty and flow_diagnostics_df.empty:
        return ""
    save_intersecting_axis_group_diagnostics(product_diagnostics_df, flow_diagnostics_df, output_dir)
    return (
        "Intersecting common ESTO axis groups require mapping review. "
        f"Product group overlaps: {len(product_diagnostics_df):,}; "
        f"flow group overlaps: {len(flow_diagnostics_df):,}. "
        f"Diagnostics written to: {output_dir / 'diagnostics'}"
    )


def build_total_check(source_df: pd.DataFrame, comparison_df: pd.DataFrame) -> pd.DataFrame:
    """Check before/after total preservation by source/economy/scenario/year."""
    if source_df.empty:
        return pd.DataFrame(columns=TOTAL_GROUP_COLUMNS + ["source_total", "common_total", "difference"])
    source_df = source_df.copy()
    if "comparison_scope" not in source_df.columns:
        if comparison_df.empty or "comparison_scope" not in comparison_df.columns:
            source_df["comparison_scope"] = ""
        else:
            scopes_df = comparison_df[["comparison_scope"]].drop_duplicates()
            source_df = source_df.merge(scopes_df, how="cross")
    before_df = source_df.groupby(TOTAL_GROUP_COLUMNS, dropna=False, as_index=False)["value"].sum().rename(columns={"value": "source_total"})
    if comparison_df.empty:
        after_df = pd.DataFrame(columns=TOTAL_GROUP_COLUMNS + ["common_total"])
    else:
        after_df = comparison_df.groupby(TOTAL_GROUP_COLUMNS, dropna=False, as_index=False)["value"].sum().rename(columns={"value": "common_total"})
    check_df = before_df.merge(after_df, on=TOTAL_GROUP_COLUMNS, how="outer")
    check_df["source_total"] = pd.to_numeric(check_df["source_total"], errors="coerce").fillna(0)
    check_df["common_total"] = pd.to_numeric(check_df["common_total"], errors="coerce").fillna(0)
    check_df["difference"] = check_df["common_total"] - check_df["source_total"]
    return check_df.sort_values(TOTAL_GROUP_COLUMNS).reset_index(drop=True)


def build_wide_year_output(comparison_df: pd.DataFrame) -> pd.DataFrame:
    """Create economy/scenario/product/flow rows with year columns.

    The wide file intentionally has no source_system column, so source_system is
    folded into scenario to avoid summing LEAP, 9th, and ESTO rows together.
    """
    if comparison_df.empty:
        return pd.DataFrame(columns=WIDE_OUTPUT_ID_COLUMNS)

    working_df = comparison_df.copy()
    working_df["product"] = working_df["common_product_label"]
    working_df["flow"] = working_df["common_flow_label"]
    working_df["scenario"] = (
        working_df["source_system"].fillna("").astype(str).str.strip()
        + " "
        + working_df["scenario"].fillna("").astype(str).str.strip()
    ).str.strip()
    working_df["year"] = working_df["year"].astype(str)
    wide_df = (
        working_df.pivot_table(
            index=WIDE_OUTPUT_ID_COLUMNS,
            columns="year",
            values="value",
            aggfunc="sum",
            fill_value=0,
        )
        .reset_index()
    )
    wide_df.columns = [str(column) for column in wide_df.columns]
    year_columns = sorted(
        [column for column in wide_df.columns if column not in WIDE_OUTPUT_ID_COLUMNS],
        key=lambda value: int(value) if value.isdigit() else value,
    )
    return wide_df[WIDE_OUTPUT_ID_COLUMNS + year_columns]


def drop_internal_common_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Remove internal QA columns from final comparison output."""
    return df.drop(columns=[column for column in COMPARISON_INTERNAL_COLUMNS if column in df.columns])


def write_csv_with_locked_fallback(df: pd.DataFrame, output_path: Path) -> Path:
    """Write a CSV, falling back to a rebuilt filename if the target is locked."""
    try:
        df.to_csv(output_path, index=False)
        return output_path
    except PermissionError:
        fallback_path = output_path.with_name(f"{output_path.stem}_rebuilt{output_path.suffix}")
        print(f"Could not overwrite locked CSV: {output_path}")
        print(f"Writing rebuilt CSV instead: {fallback_path}")
        df.to_csv(fallback_path, index=False)
        return fallback_path


def error_tagged_path(output_path: Path, error_occurred: bool) -> Path:
    """Add an error tag to output filenames when QA errors occurred."""
    return output_path


def save_outputs(
    comparison_df: pd.DataFrame,
    wide_year_df: pd.DataFrame,
    total_check_df: pd.DataFrame,
    missing_map_df: pd.DataFrame,
    subtotal_filtered_df: pd.DataFrame,
    output_dir: Path,
    error_occurred: bool,
) -> None:
    """Write common comparison data and QA outputs."""
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv_with_locked_fallback(
        drop_internal_common_columns(comparison_df),
        error_tagged_path(output_dir / "common_esto_comparison_data.csv", error_occurred),
    )
    write_csv_with_locked_fallback(
        wide_year_df,
        error_tagged_path(output_dir / "common_esto_comparison_wide.csv", error_occurred),
    )
    write_csv_with_locked_fallback(
        total_check_df,
        error_tagged_path(output_dir / "common_esto_total_check.csv", error_occurred),
    )
    write_csv_with_locked_fallback(
        total_check_df,
        error_tagged_path(output_dir / "qa_common_esto_total_check.csv", error_occurred),
    )
    write_csv_with_locked_fallback(
        missing_map_df,
        error_tagged_path(output_dir / "common_esto_source_rows_missing_common_map.csv", error_occurred),
    )
    write_csv_with_locked_fallback(
        subtotal_filtered_df,
        error_tagged_path(output_dir / "common_esto_subtotal_rows_filtered.csv", error_occurred),
    )


def run_apply_common_esto_structure(
    source_paths: dict[str, Path],
    common_rows_path: Path,
    output_dir: Path,
    default_economy: str,
    exclude_subtotal_rows: bool,
    broad_common_row_component_limit: int,
    active_component_abs_tolerance: float,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Apply the common ESTO structure to available ESTO-shaped source data."""
    source_df = read_source_tables(source_paths, default_economy=default_economy)
    common_rows_df = pd.read_csv(common_rows_path, dtype=str).fillna("")
    active_source_df = nonzero_source_rows(source_df, active_component_abs_tolerance)
    adjusted_common_rows_df, pruned_components_df = relabel_common_rows_for_active_components(
        source_df=source_df,
        common_rows_df=common_rows_df,
        active_component_abs_tolerance=active_component_abs_tolerance,
    )
    save_component_pruning_diagnostics(pruned_components_df, output_dir)
    unfiltered_comparison_df, missing_map_df = apply_common_structure(active_source_df, adjusted_common_rows_df)
    subtotal_kept_df, subtotal_filtered_df = split_subtotal_rows(unfiltered_comparison_df, exclude_subtotal_rows=exclude_subtotal_rows)
    broad_diagnostics = build_broad_common_row_diagnostics(
        common_rows_df=adjusted_common_rows_df,
        comparison_df=subtotal_kept_df,
        broad_component_limit=broad_common_row_component_limit,
    )
    broad_error_message = broad_common_row_error_message(broad_diagnostics, output_dir)
    intersecting_axis_error_message_text = intersecting_axis_group_error_message(
        adjusted_common_rows_df=adjusted_common_rows_df,
        comparison_df=subtotal_kept_df,
        output_dir=output_dir,
    )
    error_occurred = bool(broad_error_message or intersecting_axis_error_message_text)
    if broad_error_message:
        print(f"ERROR_OCCURED: {broad_error_message}")
    if intersecting_axis_error_message_text:
        print(f"ERROR_OCCURED: {intersecting_axis_error_message_text}")
    comparison_df = subtotal_kept_df.copy()
    wide_year_df = build_wide_year_output(comparison_df)
    total_check_df = build_total_check(source_df, comparison_df)
    save_outputs(
        comparison_df,
        wide_year_df,
        total_check_df,
        missing_map_df,
        subtotal_filtered_df,
        output_dir,
        error_occurred=error_occurred,
    )

    max_abs_difference = total_check_df["difference"].abs().max() if "difference" in total_check_df.columns and not total_check_df.empty else 0
    print(f"ESTO-shaped source rows read: {len(source_df):,}")
    print(f"Nonzero ESTO-shaped source rows used: {len(active_source_df):,}")
    print(f"Common ESTO components pruned as not applicable: {len(pruned_components_df):,}")
    print(f"Common comparison rows before subtotal filtering: {len(unfiltered_comparison_df):,}")
    print(f"Subtotal/total rows filtered from final outputs: {len(subtotal_filtered_df):,}")
    print(f"Common comparison rows written: {len(comparison_df):,}")
    print(f"Wide year rows written: {len(wide_year_df):,}")
    print(f"Source rows missing common map: {len(missing_map_df):,}")
    print(f"before/after total differences max abs: {max_abs_difference}")
    print(f"Error tag applied to output filenames: {error_occurred}")
    print(f"Wrote common ESTO comparison output to: {output_dir}")
    return comparison_df, total_check_df, missing_map_df

#%%
# User-tuned constants / flags.
SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = _find_repo_root(SCRIPT_PATH.parent)

RELATIONSHIP_DIR = REPO_ROOT / "results" / "mapping_relationships"
COMMON_STRUCTURE_DIR = REPO_ROOT / "results" / "common_esto"
COMMON_ROWS_PATH = COMMON_STRUCTURE_DIR / "common_esto_rows.csv"
OUTPUT_DIR = REPO_ROOT / "results" / "common_esto"

SOURCE_PATHS = {
    "LEAP": RELATIONSHIP_DIR / "leap_results_converted_to_esto.csv",
    "NINTH": RELATIONSHIP_DIR / "ninth_results_converted_to_esto.csv",
    "ESTO": RELATIONSHIP_DIR / "esto_results_exact_rows.csv",
}
DEFAULT_ECONOMY = "20_USA"
EXCLUDE_SUBTOTAL_ROWS = True
BROAD_COMMON_ROW_COMPONENT_LIMIT = 50
ACTIVE_COMPONENT_ABS_TOLERANCE = 0.0

RUN_APPLY_COMMON_ESTO_STRUCTURE = False

#%%
try:
    if RUN_APPLY_COMMON_ESTO_STRUCTURE:
        run_apply_common_esto_structure(
            source_paths=SOURCE_PATHS,
            common_rows_path=COMMON_ROWS_PATH,
            output_dir=OUTPUT_DIR,
            default_economy=DEFAULT_ECONOMY,
            exclude_subtotal_rows=EXCLUDE_SUBTOTAL_ROWS,
            broad_common_row_component_limit=BROAD_COMMON_ROW_COMPONENT_LIMIT,
            active_component_abs_tolerance=ACTIVE_COMPONENT_ABS_TOLERANCE,
        )
    else:
        print("Set RUN_APPLY_COMMON_ESTO_STRUCTURE = True after setting SOURCE_PATHS.")
except Exception as exc:
    print("Apply common ESTO structure workflow failed.")
    print(f"Error: {exc}")
    raise

#%%
