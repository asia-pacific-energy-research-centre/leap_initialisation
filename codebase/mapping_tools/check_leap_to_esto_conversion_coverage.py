#%%
"""
Check LEAP-to-ESTO conversion coverage.

This workflow audits included LEAP-to-ESTO relationships against optional raw
LEAP result exports and an optional expected ESTO flow/product universe.
"""

#%%
import re
from pathlib import Path
from typing import Any

import pandas as pd

#%%
OUTPUT_FILENAMES = {
    "leap_result_rows_without_esto_mapping": "leap_result_rows_without_esto_mapping.csv",
    "mapped_leap_sources_missing_from_latest_export": "mapped_leap_sources_missing_from_latest_export.csv",
    "expected_esto_rows_without_converted_leap_data": "expected_esto_rows_without_converted_leap_data.csv",
    "mapped_esto_targets_not_in_expected_esto_structure": "mapped_esto_targets_not_in_expected_esto_structure.csv",
    "one_to_many_mappings_without_allocation_or_combined_target": "one_to_many_mappings_without_allocation_or_combined_target.csv",
    "leap_to_esto_parent_child_double_count_risks": "leap_to_esto_parent_child_double_count_risks.csv",
    "leap_to_esto_conversion_total_check": "leap_to_esto_conversion_total_check.csv",
    "leap_to_esto_coverage_summary": "leap_to_esto_coverage_summary.csv",
    "not_considered_esto_rows": "not_considered_esto_rows.csv",
}

#%%
def _find_repo_root(start_path: Path) -> Path:
    """Find the leap_utilities repo root from a nested workflow path."""
    for candidate in [start_path, *start_path.parents]:
        if (candidate / "AGENTS.md").exists():
            return candidate
    raise FileNotFoundError(f"Could not find repo root above: {start_path}")


def read_table_if_exists(path: Path) -> pd.DataFrame:
    """Read a CSV/XLSX file if it exists, else return an empty frame."""
    if not path.exists():
        return pd.DataFrame()
    if path.suffix.lower() in {".xlsx", ".xlsm", ".xls"}:
        return pd.read_excel(path)
    return pd.read_csv(path)


def normalise_text(value: Any) -> str:
    """Normalise text for matching."""
    if pd.isna(value):
        return ""
    return re.sub(r"\s+", " ", str(value).strip()).lower()


def normalise_path_segments(path: Any) -> list[str]:
    """Split a path on either slash style and drop empty segments."""
    if pd.isna(path):
        return []
    return [segment.strip() for segment in str(path).replace("\\", "/").split("/") if segment.strip()]


def is_parent_child_path(parent_path: Any, child_path: Any) -> bool:
    """Return True if parent_path is a strict parent of child_path."""
    parent_segments = normalise_path_segments(parent_path)
    child_segments = normalise_path_segments(child_path)
    return bool(parent_segments) and child_segments[: len(parent_segments)] == parent_segments and len(child_segments) > len(parent_segments)


def load_relationships(relationships_path: Path) -> pd.DataFrame:
    """Load included LEAP-to-ESTO conversion relationships."""
    relationships_df = pd.read_csv(relationships_path)
    return relationships_df[
        (relationships_df["use_case"] == "leap_to_esto_balance_conversion")
        & relationships_df["include_in_use_case"]
        & (relationships_df["source_system"] == "LEAP")
        & relationships_df["target_system"].isin(["ESTO", "ESTO_COMBINED"])
    ].copy()


def apply_coverage_exclusions(expected_esto_df: pd.DataFrame, exclusions_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split expected ESTO rows into considered and not-considered rows."""
    if expected_esto_df.empty or exclusions_df.empty:
        return expected_esto_df.copy(), pd.DataFrame(columns=list(expected_esto_df.columns) + ["coverage_status", "coverage_reason"])

    exclusions_df = exclusions_df[
        (exclusions_df["use_case"] == "leap_to_esto_balance_conversion")
        & (exclusions_df["source_system"] == "LEAP")
        & (exclusions_df["target_system"] == "ESTO")
    ].copy()
    if exclusions_df.empty:
        return expected_esto_df.copy(), pd.DataFrame(columns=list(expected_esto_df.columns) + ["coverage_status", "coverage_reason"])

    expected_df = expected_esto_df.copy()
    expected_df["_flow_key"] = expected_df["target_flow"].apply(normalise_text)
    expected_df["_product_key"] = expected_df["target_product"].apply(normalise_text)
    exclusions_df["_flow_key"] = exclusions_df["target_flow"].apply(normalise_text)
    exclusions_df["_product_key"] = exclusions_df["target_product"].apply(normalise_text)

    excluded_keys = set()
    wildcard_flows = set()
    for _, row in exclusions_df.iterrows():
        if row["_product_key"]:
            excluded_keys.add((row["_flow_key"], row["_product_key"]))
        else:
            wildcard_flows.add(row["_flow_key"])

    mask = expected_df.apply(
        lambda row: (row["_flow_key"], row["_product_key"]) in excluded_keys or row["_flow_key"] in wildcard_flows,
        axis=1,
    )
    not_considered_df = expected_df[mask].drop(columns=["_flow_key", "_product_key"]).copy()
    not_considered_df["coverage_status"] = "not_considered"
    not_considered_df["coverage_reason"] = "flow_excluded_from_use_case"
    considered_df = expected_df[~mask].drop(columns=["_flow_key", "_product_key"]).copy()
    return considered_df, not_considered_df


def build_one_to_many_issues(relationships_df: pd.DataFrame, combined_rows_df: pd.DataFrame) -> pd.DataFrame:
    """Find one-to-many relationships without allocation or combined target."""
    one_to_many_df = relationships_df[
        relationships_df["cardinality"].fillna("").astype(str).str.lower().str.contains("one_to_many")
    ].copy()
    if one_to_many_df.empty:
        return one_to_many_df
    valid_allocation = ~one_to_many_df["allocation_method"].fillna("").astype(str).str.lower().isin(["", "direct", "none"])
    valid_combined = one_to_many_df["target_system"].eq("ESTO_COMBINED")
    if not combined_rows_df.empty:
        combined_targets = set(zip(combined_rows_df["target_flow"].astype(str), combined_rows_df["target_product"].astype(str)))
        valid_combined = valid_combined | one_to_many_df.apply(
            lambda row: (str(row["target_flow"]), str(row["target_product"])) in combined_targets,
            axis=1,
        )
    issue_df = one_to_many_df[~valid_allocation & ~valid_combined].copy()
    issue_df["qa_status"] = "review"
    issue_df["qa_severity"] = "high"
    issue_df["qa_reason"] = "one_to_many mapping has no allocation method and no valid ESTO_COMBINED target."
    issue_df["expected_duplicate"] = False
    return issue_df


def build_parent_child_risks(relationships_df: pd.DataFrame) -> pd.DataFrame:
    """Find parent/child source paths in included relationships."""
    rows: list[dict[str, Any]] = []
    for (target_flow, target_product), group_df in relationships_df.groupby(["target_flow", "target_product"], dropna=False):
        records = group_df.to_dict("records")
        for left_index, left in enumerate(records):
            for right in records[left_index + 1 :]:
                if is_parent_child_path(left["source_flow"], right["source_flow"]):
                    parent, child = left, right
                elif is_parent_child_path(right["source_flow"], left["source_flow"]):
                    parent, child = right, left
                else:
                    continue
                rows.append(
                    {
                        "target_flow": target_flow,
                        "target_product": target_product,
                        "parent_source_flow": parent["source_flow"],
                        "child_source_flow": child["source_flow"],
                        "parent_source_product": parent["source_product"],
                        "child_source_product": child["source_product"],
                        "qa_status": "review",
                        "qa_severity": "warning",
                        "qa_reason": "Parent/child LEAP paths may double count if both are converted.",
                        "expected_duplicate": False,
                    }
                )
    return pd.DataFrame(rows).drop_duplicates() if rows else pd.DataFrame(rows)


def build_coverage_outputs(
    relationships_df: pd.DataFrame,
    leap_results_df: pd.DataFrame,
    expected_esto_df: pd.DataFrame,
    exclusions_df: pd.DataFrame,
    combined_rows_df: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """Build LEAP-to-ESTO coverage output tables."""
    relationship_sources_df = relationships_df[["source_flow", "source_product"]].drop_duplicates()
    relationship_targets_df = relationships_df[["target_system", "target_flow", "target_product"]].drop_duplicates()

    if leap_results_df.empty:
        unmapped_leap_df = pd.DataFrame()
        stale_sources_df = relationship_sources_df.copy()
        converted_targets_df = relationship_targets_df.copy()
        total_check_df = pd.DataFrame([{"metric": "raw_leap_total", "value": pd.NA}, {"metric": "converted_total", "value": pd.NA}, {"metric": "difference", "value": pd.NA}])
    else:
        leap_results_df = leap_results_df.copy()
        merged_df = leap_results_df.merge(
            relationships_df,
            left_on=["leap_flow", "leap_product"],
            right_on=["source_flow", "source_product"],
            how="left",
        )
        unmapped_leap_df = merged_df[merged_df["relationship_id"].isna()].copy()
        latest_sources_df = leap_results_df[["leap_flow", "leap_product"]].drop_duplicates().rename(
            columns={"leap_flow": "source_flow", "leap_product": "source_product"}
        )
        stale_sources_df = relationship_sources_df.merge(
            latest_sources_df,
            on=["source_flow", "source_product"],
            how="left",
            indicator=True,
        )
        stale_sources_df = stale_sources_df[stale_sources_df["_merge"] == "left_only"].drop(columns=["_merge"])
        converted_targets_df = merged_df.dropna(subset=["target_flow", "target_product"])[
            ["target_system", "target_flow", "target_product"]
        ].drop_duplicates()
        raw_total = leap_results_df["value"].sum() if "value" in leap_results_df.columns else pd.NA
        converted_total = merged_df.dropna(subset=["target_flow", "target_product"])["value"].sum() if "value" in merged_df.columns else pd.NA
        total_check_df = pd.DataFrame(
            [
                {"metric": "raw_leap_total", "value": raw_total},
                {"metric": "converted_total", "value": converted_total},
                {"metric": "difference", "value": converted_total - raw_total if pd.notna(raw_total) and pd.notna(converted_total) else pd.NA},
            ]
        )

    considered_esto_df, not_considered_df = apply_coverage_exclusions(expected_esto_df, exclusions_df)
    if considered_esto_df.empty:
        missing_expected_df = pd.DataFrame()
        invalid_targets_df = pd.DataFrame()
    else:
        expected_targets_df = considered_esto_df[["target_flow", "target_product"]].drop_duplicates()
        converted_esto_targets_df = converted_targets_df[converted_targets_df["target_system"] == "ESTO"][
            ["target_flow", "target_product"]
        ].drop_duplicates()
        missing_expected_df = expected_targets_df.merge(
            converted_esto_targets_df,
            on=["target_flow", "target_product"],
            how="left",
            indicator=True,
        )
        missing_expected_df = missing_expected_df[missing_expected_df["_merge"] == "left_only"].drop(columns=["_merge"])
        invalid_targets_df = converted_esto_targets_df.merge(
            expected_targets_df,
            on=["target_flow", "target_product"],
            how="left",
            indicator=True,
        )
        invalid_targets_df = invalid_targets_df[invalid_targets_df["_merge"] == "left_only"].drop(columns=["_merge"])

    one_to_many_df = build_one_to_many_issues(relationships_df, combined_rows_df)
    parent_child_df = build_parent_child_risks(relationships_df)
    summary_df = pd.DataFrame(
        [
            {"metric": "LEAP export rows read", "value": len(leap_results_df)},
            {"metric": "included LEAP-to-ESTO relationships", "value": len(relationships_df)},
            {"metric": "unmapped LEAP result rows", "value": len(unmapped_leap_df)},
            {"metric": "stale mapped LEAP sources", "value": len(stale_sources_df)},
            {"metric": "expected ESTO rows missing converted data", "value": len(missing_expected_df)},
            {"metric": "not-considered ESTO rows", "value": len(not_considered_df)},
            {"metric": "invalid ESTO targets", "value": len(invalid_targets_df)},
            {"metric": "one-to-many allocation/combined-target issues", "value": len(one_to_many_df)},
            {"metric": "parent-child risks", "value": len(parent_child_df)},
        ]
    )
    return {
        "leap_result_rows_without_esto_mapping": unmapped_leap_df,
        "mapped_leap_sources_missing_from_latest_export": stale_sources_df,
        "expected_esto_rows_without_converted_leap_data": missing_expected_df,
        "mapped_esto_targets_not_in_expected_esto_structure": invalid_targets_df,
        "one_to_many_mappings_without_allocation_or_combined_target": one_to_many_df,
        "leap_to_esto_parent_child_double_count_risks": parent_child_df,
        "leap_to_esto_conversion_total_check": total_check_df,
        "leap_to_esto_coverage_summary": summary_df,
        "not_considered_esto_rows": not_considered_df,
    }


def save_outputs(outputs: dict[str, pd.DataFrame], output_dir: Path) -> None:
    """Save coverage outputs."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, output_df in outputs.items():
        output_df.to_csv(output_dir / OUTPUT_FILENAMES[name], index=False)


def run_coverage_check(
    relationships_path: Path,
    leap_results_path: Path,
    expected_esto_path: Path,
    coverage_exclusions_path: Path,
    esto_combined_rows_path: Path,
    output_dir: Path,
) -> dict[str, pd.DataFrame]:
    """Run coverage check."""
    relationships_df = load_relationships(relationships_path)
    leap_results_df = read_table_if_exists(leap_results_path)
    expected_esto_df = read_table_if_exists(expected_esto_path)
    exclusions_df = read_table_if_exists(coverage_exclusions_path)
    combined_rows_df = read_table_if_exists(esto_combined_rows_path)
    outputs = build_coverage_outputs(
        relationships_df=relationships_df,
        leap_results_df=leap_results_df,
        expected_esto_df=expected_esto_df,
        exclusions_df=exclusions_df,
        combined_rows_df=combined_rows_df,
    )
    save_outputs(outputs, output_dir)
    summary = outputs["leap_to_esto_coverage_summary"].set_index("metric")["value"].to_dict()
    for metric, value in summary.items():
        print(f"{metric}: {value}")
    print(f"before/after conversion total difference: {outputs['leap_to_esto_conversion_total_check'].tail(1)['value'].iloc[0]}")
    print(f"Wrote coverage outputs to: {output_dir}")
    return outputs

#%%
# User-tuned constants / flags.
SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = _find_repo_root(SCRIPT_PATH.parent)

RELATIONSHIP_DIR = REPO_ROOT / "results" / "mapping_relationships"
RELATIONSHIPS_PATH = RELATIONSHIP_DIR / "energy_balance_relationships.csv"
LEAP_RESULTS_PATH = RELATIONSHIP_DIR / "raw_leap_results_placeholder.csv"
EXPECTED_ESTO_PATH = RELATIONSHIP_DIR / "expected_esto_rows_placeholder.csv"
COVERAGE_EXCLUSIONS_PATH = RELATIONSHIP_DIR / "coverage_exclusions.csv"
ESTO_COMBINED_ROWS_PATH = RELATIONSHIP_DIR / "esto_combined_rows.csv"
OUTPUT_DIR = RELATIONSHIP_DIR / "leap_to_esto_coverage"

RUN_LEAP_TO_ESTO_COVERAGE_CHECK = True

#%%
try:
    if RUN_LEAP_TO_ESTO_COVERAGE_CHECK:
        run_coverage_check(
            relationships_path=RELATIONSHIPS_PATH,
            leap_results_path=LEAP_RESULTS_PATH,
            expected_esto_path=EXPECTED_ESTO_PATH,
            coverage_exclusions_path=COVERAGE_EXCLUSIONS_PATH,
            esto_combined_rows_path=ESTO_COMBINED_ROWS_PATH,
            output_dir=OUTPUT_DIR,
        )
except Exception as exc:
    print("LEAP-to-ESTO coverage check failed.")
    print(f"Error: {exc}")
    raise

#%%
