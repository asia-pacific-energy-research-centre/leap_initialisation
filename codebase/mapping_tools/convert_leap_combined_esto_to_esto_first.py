#%%
"""
Convert leap_combined_esto into a flat ESTO-first dashboard mapping table.

This is a prototype helper. It preserves excluded source rows where remove_row is
present and True, attaches dashboard graph IDs with product-aware graph rules,
and writes dashboard QA reports.
"""

#%%
import re
import hashlib
from pathlib import Path
from typing import Any

import pandas as pd

#%%
OUTPUT_COLUMNS = [
    "relationship_id",
    "relationship_key",
    "use_case",
    "include_in_use_case",
    "esto_flow",
    "esto_product",
    "source_system",
    "source_sector_path",
    "source_fuel",
    "source_sector_code",
    "source_fuel_code",
    "mapping_type",
    "mapping_level",
    "relationship_status",
    "exclude_reason",
    "notes",
    "cardinality",
    "source_mapping_file",
    "source_row_number",
    "remove_row",
    "graph_ids",
    "graph_count",
    "matched_template_esto_flows",
]

GRAPH_LINK_COLUMNS = [
    "source_row_number",
    "include_in_use_case",
    "relationship_id",
    "use_case",
    "esto_flow",
    "esto_product",
    "graph_id",
    "page_path",
    "graph_type",
    "product_match_mode",
    "matched_esto_flow",
    "matched_esto_product",
    "match_basis",
    "product_source",
    "specified_products",
]

COLUMN_CANDIDATES = {
    "esto_flow": [
        "esto_flow",
        "esto_sector",
        "esto_sector_name",
        "esto_flow_name",
        "flow",
    ],
    "esto_product": [
        "esto_product",
        "esto_fuel",
        "esto_product_name",
        "esto_fuel_name",
        "product",
    ],
    "source_sector_path": [
        "leap_sector_name_full_path",
        "leap_flow",
        "leap_sector",
        "leap_sector_path",
        "leap_branch",
        "leap_branch_path",
    ],
    "source_fuel": [
        "raw_leap_fuel_name",
        "leap_product",
        "leap_fuel",
        "leap_product_name",
        "leap_fuel_name",
    ],
    "source_sector_code": [
        "leap_flow_code",
        "leap_sector_code",
        "source_sector_code",
    ],
    "source_fuel_code": [
        "leap_product_code",
        "leap_fuel_code",
        "source_fuel_code",
    ],
    "remove_row": [
        "remove_row",
        "remove",
        "inactive",
        "drop_row",
    ],
    "notes": [
        "notes",
        "note",
        "comments",
        "comment",
    ],
    "cardinality": [
        "cardinality",
        "relationship_cardinality",
        "pair_mapping_cardinality",
    ],
}

QA_FILENAMES = {
    "relationships_not_used_by_template": "dashboard_relationships_not_used_by_template.csv",
    "all_relationships_not_used_by_template": "dashboard_all_relationships_not_used_by_template.csv",
    "template_flows_without_mapping": "dashboard_template_flows_without_mapping.csv",
    "duplicate_source_relationships": "dashboard_duplicate_source_relationships.csv",
    "duplicate_target_relationships": "dashboard_duplicate_target_relationships.csv",
    "parent_child_risks": "dashboard_parent_child_risks.csv",
}

#%%
def _find_repo_root(start_path: Path) -> Path:
    """Find the leap_utilities repo root from a nested uploaded helper path."""
    for candidate in [start_path, *start_path.parents]:
        if (candidate / "AGENTS.md").exists():
            return candidate
    raise FileNotFoundError(f"Could not find repo root above: {start_path}")


def clean_column_name(value: Any) -> str:
    """Normalise a source column name for matching."""
    text = "" if value is None else str(value)
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def first_existing_column(columns: list[str], candidates: list[str]) -> str | None:
    """Return the first source column matching one of the configured candidates."""
    column_set = set(columns)
    for candidate in candidates:
        if candidate in column_set:
            return candidate
    return None


def parse_remove_row(value: Any) -> bool:
    """Interpret common true-ish remove row values."""
    if pd.isna(value):
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)

    text = str(value).strip().lower()
    return text in {"true", "t", "yes", "y", "1", "remove", "removed", "drop", "inactive"}


def normalise_match_text(value: Any) -> str:
    """Normalise text for exact mapping comparisons."""
    if pd.isna(value):
        return ""
    return re.sub(r"\s+", " ", str(value).strip()).lower()


def make_relationship_id(
    source_system: str,
    source_flow: Any,
    source_product: Any,
    target_system: str,
    target_flow: Any,
    target_product: Any,
) -> str:
    """Create a stable ID for the underlying source-to-target relationship."""
    key_parts = [
        source_system,
        normalise_match_text(source_flow),
        normalise_match_text(source_product),
        target_system,
        normalise_match_text(target_flow),
        normalise_match_text(target_product),
    ]
    digest = hashlib.sha1("||".join(key_parts).encode("utf-8")).hexdigest()[:16]
    return f"rel_{digest}"


def relationship_status_for_remove_flag(remove_flag: bool) -> str:
    """Return relationship status for a generated dashboard use-case row."""
    if remove_flag:
        return "excluded_by_remove_row_for_use_case"
    return "included_in_use_case"


def normalise_path_segments(path: Any) -> list[str]:
    """Split a LEAP path on either slash style and drop empty segments."""
    if pd.isna(path):
        return []
    normalised_path = str(path).replace("\\", "/")
    return [segment.strip() for segment in normalised_path.split("/") if segment.strip()]


def read_leap_combined_esto(path: Path, sheet_name: str = "leap_combined_esto") -> pd.DataFrame:
    """Read existing LEAP to ESTO mapping file."""
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xlsm", ".xls"}:
        return pd.read_excel(path, sheet_name=sheet_name)
    if suffix == ".csv":
        return pd.read_csv(path)
    raise ValueError(f"Unsupported mapping file type: {path}")


def normalise_leap_combined_esto_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename source columns into standard converter columns."""
    original_columns = list(df.columns)
    cleaned_columns = [clean_column_name(column) for column in original_columns]
    renamed_df = df.copy()
    renamed_df.columns = cleaned_columns

    rename_map: dict[str, str] = {}
    for target_column, candidates in COLUMN_CANDIDATES.items():
        source_column = first_existing_column(cleaned_columns, candidates)
        if source_column is not None:
            rename_map[source_column] = target_column

    normalised_df = renamed_df.rename(columns=rename_map)

    required_columns = ["esto_flow", "esto_product", "source_sector_path", "source_fuel"]
    missing_required = [column for column in required_columns if column not in normalised_df.columns]
    if missing_required:
        raise ValueError(
            "Could not identify required mapping columns: "
            + ", ".join(missing_required)
            + f". Source columns were: {original_columns}"
        )

    optional_defaults = {
        "source_sector_code": "",
        "source_fuel_code": "",
        "remove_row": pd.NA,
        "notes": "",
        "cardinality": "",
    }
    for column, default_value in optional_defaults.items():
        if column not in normalised_df.columns:
            normalised_df[column] = default_value

    return normalised_df


def infer_mapping_type(esto_flow: Any) -> str:
    """Infer a coarse mapping type from the ESTO flow."""
    flow = "" if pd.isna(esto_flow) else str(esto_flow).strip()
    if flow.startswith("12 ") or flow.startswith("13 "):
        return "total_final_rollup"
    if flow.startswith("10.01") or flow.startswith("10.02"):
        return "own_use_or_losses"
    return "direct_or_existing_mapping"


def infer_mapping_level(esto_flow: Any, source_sector_path: Any) -> str:
    """Infer a coarse mapping level from ESTO flow and LEAP path depth."""
    flow = "" if pd.isna(esto_flow) else str(esto_flow).strip()
    path_segments = normalise_path_segments(source_sector_path)

    if flow.startswith("12 ") or flow.startswith("13 "):
        return "total"
    if flow.startswith("10.01") or flow.startswith("10.02"):
        return "special"
    if len(path_segments) > 1:
        return "child"
    return "parent"


def join_unique(values: pd.Series | list[Any]) -> str:
    """Join unique non-empty values with pipe separators."""
    if isinstance(values, pd.Series):
        raw_values = values.tolist()
    else:
        raw_values = values

    cleaned = []
    seen = set()
    for value in raw_values:
        if pd.isna(value):
            continue
        text = str(value).strip()
        if not text or text in seen:
            continue
        cleaned.append(text)
        seen.add(text)
    return "|".join(cleaned)


def build_product_aware_graph_links(
    mapping_df: pd.DataFrame,
    graph_flow_product_index: pd.DataFrame,
) -> pd.DataFrame:
    """Attach graph links where flow matches and product rule permits the mapping product."""
    required_columns = {
        "graph_id",
        "page_path",
        "graph_type",
        "esto_flow",
        "product_match_mode",
        "esto_product",
        "product_source",
        "specified_products",
    }
    missing = required_columns - set(graph_flow_product_index.columns)
    if missing:
        raise ValueError(f"Graph-flow-product index is missing columns: {sorted(missing)}")

    mapping_key_df = mapping_df[
        ["source_row_number", "include_in_use_case", "relationship_id", "use_case", "esto_flow", "esto_product"]
    ].copy()
    mapping_key_df["_flow_key"] = mapping_key_df["esto_flow"].apply(normalise_match_text)
    mapping_key_df["_product_key"] = mapping_key_df["esto_product"].apply(normalise_match_text)

    graph_rules_df = graph_flow_product_index.copy()
    graph_rules_df["_flow_key"] = graph_rules_df["esto_flow"].apply(normalise_match_text)
    graph_rules_df["_product_key"] = graph_rules_df["esto_product"].apply(normalise_match_text)
    graph_rules_df["product_match_mode"] = graph_rules_df["product_match_mode"].fillna("").astype(str)

    merged_df = mapping_key_df.merge(
        graph_rules_df,
        on="_flow_key",
        how="inner",
        suffixes=("", "_template"),
    )
    wildcard_modes = {"all_products", "total_chart"}
    matched_df = merged_df[
        merged_df["product_match_mode"].isin(wildcard_modes)
        | (merged_df["_product_key"] == merged_df["_product_key_template"])
    ].copy()

    if matched_df.empty:
        return pd.DataFrame(columns=GRAPH_LINK_COLUMNS)

    graph_links_df = pd.DataFrame(
        {
            "source_row_number": matched_df["source_row_number"],
            "include_in_use_case": matched_df["include_in_use_case"],
            "relationship_id": matched_df["relationship_id"],
            "use_case": matched_df["use_case"],
            "esto_flow": matched_df["esto_flow"],
            "esto_product": matched_df["esto_product"],
            "graph_id": matched_df["graph_id"],
            "page_path": matched_df["page_path"],
            "graph_type": matched_df["graph_type"],
            "product_match_mode": matched_df["product_match_mode"],
            "matched_esto_flow": matched_df["esto_flow_template"],
            "matched_esto_product": matched_df["esto_product_template"].fillna(""),
            "match_basis": matched_df["product_match_mode"].map(
                {
                    "all_products": "esto_flow_wildcard_product",
                    "total_chart": "esto_flow_total_chart",
                    "specified_products": "esto_flow_and_product",
                }
            ).fillna("esto_flow_and_product"),
            "product_source": matched_df["product_source"].fillna(""),
            "specified_products": matched_df["specified_products"].fillna(""),
        }
    )
    return graph_links_df.drop_duplicates().sort_values(["source_row_number", "graph_id"])


def build_graph_link_summary(graph_links_df: pd.DataFrame) -> pd.DataFrame:
    """Collapse long graph links to candidate-table convenience columns."""
    if graph_links_df.empty:
        return pd.DataFrame(
            columns=["source_row_number", "graph_ids", "matched_template_esto_flows", "graph_count"]
        )

    summary_df = (
        graph_links_df.groupby("source_row_number", as_index=False)
        .agg(
            graph_ids=("graph_id", join_unique),
            matched_template_esto_flows=("matched_esto_flow", join_unique),
        )
    )
    summary_df["graph_count"] = summary_df["graph_ids"].apply(
        lambda value: 0 if not value else len(str(value).split("|"))
    )
    return summary_df


def convert_to_esto_first_dashboard_mapping(
    df: pd.DataFrame,
    graph_flow_product_index: pd.DataFrame,
    source_mapping_file: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Convert leap_combined_esto to the new ESTO-first dashboard mapping format."""
    working_df = normalise_leap_combined_esto_columns(df)
    working_df = working_df.copy()
    working_df["source_row_number"] = working_df.index + 2  # Excel row number, assuming row 1 is header.

    for column in ["esto_flow", "esto_product", "source_sector_path", "source_fuel"]:
        working_df[column] = working_df[column].fillna("").astype(str).str.strip()

    remove_flags = working_df["remove_row"].apply(parse_remove_row)
    relationship_ids = [
        make_relationship_id("LEAP", source_path, source_fuel, "ESTO", esto_flow, esto_product)
        for source_path, source_fuel, esto_flow, esto_product in zip(
            working_df["source_sector_path"],
            working_df["source_fuel"],
            working_df["esto_flow"],
            working_df["esto_product"],
            strict=False,
        )
    ]

    converted_df = pd.DataFrame(
        {
            "relationship_id": relationship_ids,
            "relationship_key": [f"{relationship_id}::dashboard_chart" for relationship_id in relationship_ids],
            "use_case": "dashboard_chart",
            "include_in_use_case": ~remove_flags,
            "esto_flow": working_df["esto_flow"],
            "esto_product": working_df["esto_product"],
            "source_system": "LEAP",
            "source_sector_path": working_df["source_sector_path"],
            "source_fuel": working_df["source_fuel"],
            "source_sector_code": working_df["source_sector_code"],
            "source_fuel_code": working_df["source_fuel_code"],
            "mapping_type": [infer_mapping_type(flow) for flow in working_df["esto_flow"]],
            "mapping_level": [
                infer_mapping_level(flow, path)
                for flow, path in zip(working_df["esto_flow"], working_df["source_sector_path"], strict=False)
            ],
            "relationship_status": remove_flags.map(
                {True: "excluded_by_remove_row_for_use_case", False: "included_in_use_case"}
            ),
            "exclude_reason": remove_flags.map(
                {True: "remove_row_true_in_source_mapping", False: ""}
            ),
            "notes": working_df["notes"],
            "cardinality": working_df["cardinality"],
            "source_mapping_file": str(source_mapping_file),
            "source_row_number": working_df["source_row_number"],
            "remove_row": working_df["remove_row"],
        }
    )

    graph_links_df = build_product_aware_graph_links(converted_df, graph_flow_product_index)
    graph_link_summary_df = build_graph_link_summary(graph_links_df)
    converted_df = converted_df.merge(graph_link_summary_df, on="source_row_number", how="left")
    converted_df["graph_ids"] = converted_df["graph_ids"].fillna("")
    converted_df["graph_count"] = converted_df["graph_count"].fillna(0).astype(int)
    converted_df["matched_template_esto_flows"] = converted_df["matched_template_esto_flows"].fillna("")

    return converted_df[OUTPUT_COLUMNS], graph_links_df[GRAPH_LINK_COLUMNS]


def is_parent_child_path(parent_path: str, child_path: str) -> bool:
    """Return True if parent_path is a path parent of child_path."""
    parent_segments = normalise_path_segments(parent_path)
    child_segments = normalise_path_segments(child_path)
    return bool(parent_segments) and child_segments[: len(parent_segments)] == parent_segments and len(child_segments) > len(parent_segments)


def is_total_or_subtotal_flow(esto_flow: Any) -> bool:
    """Return True for total final rows or explicit total/subtotal labels."""
    flow = "" if pd.isna(esto_flow) else str(esto_flow).strip().lower()
    return flow.startswith(("12 ", "13 ")) or "total" in flow or "subtotal" in flow


def has_expected_cardinality(cardinality_text: Any) -> bool:
    """Return True when cardinality metadata says duplication can be expected."""
    text = "" if pd.isna(cardinality_text) else str(cardinality_text).strip().lower()
    return "many" in text or "multiple" in text or "ok" in text


def classify_duplicate_row(row: pd.Series, duplicate_kind: str) -> pd.Series:
    """Classify duplicate QA rows without treating all duplicates as defects."""
    cardinality = row.get("cardinality", "")
    mapping_types = str(row.get("mapping_types", ""))
    mapping_levels = str(row.get("mapping_levels", ""))
    esto_flows = str(row.get("esto_flows", row.get("esto_flow", "")))
    expected_duplicate = (
        has_expected_cardinality(cardinality)
        or "total_final_rollup" in mapping_types
        or "total" in mapping_levels
        or any(is_total_or_subtotal_flow(flow) for flow in esto_flows.split("|"))
    )

    if expected_duplicate:
        return pd.Series(
            {
                "qa_status": "review_expected",
                "qa_severity": "info",
                "qa_reason": f"{duplicate_kind} duplication is expected by cardinality or total/subtotal metadata.",
                "expected_duplicate": True,
            }
        )

    return pd.Series(
        {
            "qa_status": "review",
            "qa_severity": "warning",
            "qa_reason": f"{duplicate_kind} duplication needs human review; no metadata currently marks it expected.",
            "expected_duplicate": False,
        }
    )


def classify_parent_child_row(row: pd.Series) -> pd.Series:
    """Classify parent/child overlap as warning unless metadata marks it expected."""
    cardinality = row.get("cardinality", "")
    expected_duplicate = has_expected_cardinality(cardinality) or bool(row.get("subtotal_overlap", False))
    if expected_duplicate:
        return pd.Series(
            {
                "qa_status": "review_expected",
                "qa_severity": "info",
                "qa_reason": "Parent/child overlap is expected by cardinality or subtotal metadata.",
                "expected_duplicate": True,
            }
        )
    return pd.Series(
        {
            "qa_status": "review",
            "qa_severity": "warning",
            "qa_reason": "Parent/child overlap can double-count if both rows are consumed together.",
            "expected_duplicate": False,
        }
    )


def build_duplicate_source_rows(mapping_df: pd.DataFrame) -> pd.DataFrame:
    """Find included LEAP source rows mapped to multiple ESTO flow/product pairs."""
    active_df = mapping_df[mapping_df["include_in_use_case"]].copy()
    key_cols = ["source_sector_path", "source_fuel"]
    target_cols = ["esto_flow", "esto_product"]

    if active_df.empty:
        return pd.DataFrame()

    grouped = (
        active_df.groupby(key_cols, dropna=False)
        .agg(
            active_row_count=("use_case", "size"),
            target_pair_count=(target_cols[0], lambda series: 0),
            esto_pairs=("esto_flow", lambda series: ""),
            source_rows=("source_row_number", join_unique),
            graph_ids=("graph_ids", join_unique),
            cardinality=("cardinality", join_unique),
            mapping_types=("mapping_type", join_unique),
            mapping_levels=("mapping_level", join_unique),
            remove_row_values=("remove_row", join_unique),
        )
        .reset_index()
    )

    target_counts = (
        active_df.assign(
            esto_pair=active_df["esto_flow"].astype(str) + " :: " + active_df["esto_product"].astype(str)
        )
        .groupby(key_cols, dropna=False)
        .agg(
            target_pair_count=("esto_pair", "nunique"),
            esto_pairs=("esto_pair", join_unique),
            esto_flows=("esto_flow", join_unique),
        )
        .reset_index()
    )

    grouped = grouped.drop(columns=["target_pair_count", "esto_pairs"]).merge(
        target_counts,
        on=key_cols,
        how="left",
    )
    duplicate_df = grouped[grouped["target_pair_count"] > 1].copy()
    if duplicate_df.empty:
        return duplicate_df.sort_values(key_cols)
    classification_df = duplicate_df.apply(
        lambda row: classify_duplicate_row(row, "source-to-target"),
        axis=1,
    )
    return pd.concat([duplicate_df, classification_df], axis=1).sort_values(
        ["qa_severity", *key_cols]
    )


def build_duplicate_esto_rows(mapping_df: pd.DataFrame) -> pd.DataFrame:
    """Find included ESTO rows that receive multiple LEAP source rows."""
    active_df = mapping_df[mapping_df["include_in_use_case"]].copy()
    key_cols = ["esto_flow", "esto_product"]

    if active_df.empty:
        return pd.DataFrame()

    active_df["source_pair"] = (
        active_df["source_sector_path"].astype(str) + " :: " + active_df["source_fuel"].astype(str)
    )
    grouped = (
        active_df.groupby(key_cols, dropna=False)
        .agg(
            active_row_count=("use_case", "size"),
            source_pair_count=("source_pair", "nunique"),
            source_pairs=("source_pair", join_unique),
            source_rows=("source_row_number", join_unique),
            graph_ids=("graph_ids", join_unique),
            cardinality=("cardinality", join_unique),
            mapping_types=("mapping_type", join_unique),
            mapping_levels=("mapping_level", join_unique),
            remove_row_values=("remove_row", join_unique),
        )
        .reset_index()
    )
    duplicate_df = grouped[grouped["source_pair_count"] > 1].copy()
    if duplicate_df.empty:
        return duplicate_df.sort_values(key_cols)
    duplicate_df["esto_flows"] = duplicate_df["esto_flow"]
    classification_df = duplicate_df.apply(
        lambda row: classify_duplicate_row(row, "target-to-source"),
        axis=1,
    )
    return pd.concat([duplicate_df, classification_df], axis=1).sort_values(
        ["qa_severity", *key_cols]
    )


def build_parent_child_risks(mapping_df: pd.DataFrame) -> pd.DataFrame:
    """Flag where parent and child LEAP paths are included for the same target or graph."""
    active_df = mapping_df[mapping_df["include_in_use_case"]].copy()
    active_df = active_df[active_df["source_sector_path"].fillna("").astype(str).str.len() > 0]

    risk_rows: list[dict[str, Any]] = []
    if active_df.empty:
        return pd.DataFrame(risk_rows)

    active_df["graph_id_list"] = active_df["graph_ids"].fillna("").apply(
        lambda value: [item for item in str(value).split("|") if item]
    )

    # Same ESTO flow/product risk.
    for (esto_flow, esto_product), group in active_df.groupby(["esto_flow", "esto_product"], dropna=False):
        records = group.to_dict("records")
        for left_index, left in enumerate(records):
            for right in records[left_index + 1 :]:
                left_path = str(left["source_sector_path"])
                right_path = str(right["source_sector_path"])
                if is_parent_child_path(left_path, right_path):
                    parent, child = left, right
                elif is_parent_child_path(right_path, left_path):
                    parent, child = right, left
                else:
                    continue
                risk_rows.append(
                    {
                        "risk_type": "same_esto_flow_product",
                        "esto_flow": esto_flow,
                        "esto_product": esto_product,
                        "graph_id": "",
                        "parent_source_sector_path": parent["source_sector_path"],
                        "child_source_sector_path": child["source_sector_path"],
                        "parent_source_fuel": parent["source_fuel"],
                        "child_source_fuel": child["source_fuel"],
                        "parent_source_row_number": parent["source_row_number"],
                        "child_source_row_number": child["source_row_number"],
                        "cardinality": join_unique([parent.get("cardinality", ""), child.get("cardinality", "")]),
                        "mapping_types": join_unique([parent.get("mapping_type", ""), child.get("mapping_type", "")]),
                        "mapping_levels": join_unique([parent.get("mapping_level", ""), child.get("mapping_level", "")]),
                        "subtotal_overlap": is_total_or_subtotal_flow(esto_flow),
                    }
                )

    # Same graph risk. Explode graph IDs first.
    graph_exploded = active_df.explode("graph_id_list")
    graph_exploded = graph_exploded[graph_exploded["graph_id_list"].fillna("").astype(str).str.len() > 0]
    for graph_id, group in graph_exploded.groupby("graph_id_list", dropna=False):
        records = group.to_dict("records")
        for left_index, left in enumerate(records):
            for right in records[left_index + 1 :]:
                left_path = str(left["source_sector_path"])
                right_path = str(right["source_sector_path"])
                if is_parent_child_path(left_path, right_path):
                    parent, child = left, right
                elif is_parent_child_path(right_path, left_path):
                    parent, child = right, left
                else:
                    continue
                risk_rows.append(
                    {
                        "risk_type": "same_graph_id",
                        "esto_flow": join_unique([left.get("esto_flow", ""), right.get("esto_flow", "")]),
                        "esto_product": join_unique([left.get("esto_product", ""), right.get("esto_product", "")]),
                        "graph_id": graph_id,
                        "parent_source_sector_path": parent["source_sector_path"],
                        "child_source_sector_path": child["source_sector_path"],
                        "parent_source_fuel": parent["source_fuel"],
                        "child_source_fuel": child["source_fuel"],
                        "parent_source_row_number": parent["source_row_number"],
                        "child_source_row_number": child["source_row_number"],
                        "cardinality": join_unique([parent.get("cardinality", ""), child.get("cardinality", "")]),
                        "mapping_types": join_unique([parent.get("mapping_type", ""), child.get("mapping_type", "")]),
                        "mapping_levels": join_unique([parent.get("mapping_level", ""), child.get("mapping_level", "")]),
                        "subtotal_overlap": any(
                            is_total_or_subtotal_flow(flow)
                            for flow in [left.get("esto_flow", ""), right.get("esto_flow", "")]
                        ),
                    }
                )

    risk_df = pd.DataFrame(risk_rows)
    if risk_df.empty:
        return risk_df
    risk_df = risk_df.drop_duplicates()
    classification_df = risk_df.apply(classify_parent_child_row, axis=1)
    return pd.concat([risk_df, classification_df], axis=1).sort_values(
        ["risk_type", "graph_id", "esto_flow", "esto_product", "parent_source_sector_path", "child_source_sector_path"]
    )


def build_dashboard_mapping_qa(
    mapping_df: pd.DataFrame,
    graph_flow_product_index: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """Create QA tables for missing graph links, duplicate mappings, and parent-child risks."""
    active_mapping_df = mapping_df[mapping_df["include_in_use_case"]].copy()

    relationships_not_used_by_template = active_mapping_df[active_mapping_df["graph_count"] == 0].copy()
    all_source_rows_not_in_template = mapping_df[mapping_df["graph_count"] == 0].copy()

    active_template_flows = set(active_mapping_df["esto_flow"].dropna().astype(str).str.strip())
    template_flows = graph_flow_product_index[["esto_flow"]].drop_duplicates().copy()
    template_flows["esto_flow"] = template_flows["esto_flow"].fillna("").astype(str).str.strip()
    template_flows_without_mapping = template_flows[
        ~template_flows["esto_flow"].isin(active_template_flows)
    ].sort_values("esto_flow")

    duplicate_source_rows = build_duplicate_source_rows(mapping_df)
    duplicate_esto_rows = build_duplicate_esto_rows(mapping_df)
    parent_child_risks = build_parent_child_risks(mapping_df)

    return {
        "relationships_not_used_by_template": relationships_not_used_by_template,
        "all_relationships_not_used_by_template": all_source_rows_not_in_template,
        "template_flows_without_mapping": template_flows_without_mapping,
        "duplicate_source_relationships": duplicate_source_rows,
        "duplicate_target_relationships": duplicate_esto_rows,
        "parent_child_risks": parent_child_risks,
    }


def save_mapping_outputs(
    mapping_df: pd.DataFrame,
    graph_links_df: pd.DataFrame,
    qa_tables: dict[str, pd.DataFrame],
    output_csv_path: Path,
    output_xlsx_path: Path,
    graph_links_csv_path: Path,
    qa_dir: Path,
) -> None:
    """Save mapping candidate CSV, XLSX, and QA CSV outputs."""
    output_csv_path.parent.mkdir(parents=True, exist_ok=True)
    qa_dir.mkdir(parents=True, exist_ok=True)

    mapping_df.to_csv(output_csv_path, index=False)
    graph_links_df.to_csv(graph_links_csv_path, index=False)
    with pd.ExcelWriter(output_xlsx_path, engine="openpyxl") as writer:
        mapping_df.to_excel(writer, sheet_name="mapping_candidates", index=False)
        graph_links_df.to_excel(writer, sheet_name="graph_links", index=False)
        for qa_name, qa_df in qa_tables.items():
            sheet_name = qa_name[:31]
            qa_df.to_excel(writer, sheet_name=sheet_name, index=False)

    for qa_name, qa_df in qa_tables.items():
        qa_filename = QA_FILENAMES[qa_name]
        qa_df.to_csv(qa_dir / qa_filename, index=False)


def run_dashboard_mapping_conversion(
    source_mapping_path: Path,
    source_sheet_name: str,
    graph_flow_product_index_path: Path,
    output_csv_path: Path,
    output_xlsx_path: Path,
    graph_links_csv_path: Path,
    qa_dir: Path,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """Run the full ESTO-first mapping conversion workflow."""
    source_df = read_leap_combined_esto(source_mapping_path, sheet_name=source_sheet_name)
    graph_flow_product_index_df = pd.read_csv(graph_flow_product_index_path)

    mapping_df, graph_links_df = convert_to_esto_first_dashboard_mapping(
        source_df,
        graph_flow_product_index_df,
        source_mapping_path,
    )
    qa_tables = build_dashboard_mapping_qa(mapping_df, graph_flow_product_index_df)

    save_mapping_outputs(
        mapping_df,
        graph_links_df,
        qa_tables,
        output_csv_path,
        output_xlsx_path,
        graph_links_csv_path,
        qa_dir,
    )

    print(f"Mapping rows converted: {len(mapping_df):,}")
    print(f"Included dashboard mappings: {int(mapping_df['include_in_use_case'].sum()):,}")
    print(f"Excluded dashboard mappings: {int((~mapping_df['include_in_use_case']).sum()):,}")
    print(f"Product-aware graph links: {len(graph_links_df):,}")
    print(
        "Included dashboard relationships not used by template: "
        f"{len(qa_tables['relationships_not_used_by_template']):,}"
    )
    print(
        "All dashboard relationships not used by template: "
        f"{len(qa_tables['all_relationships_not_used_by_template']):,}"
    )
    print(
        "Dashboard template flows without included LEAP mappings: "
        f"{len(qa_tables['template_flows_without_mapping']):,}"
    )
    print(f"Duplicate source relationship groups: {len(qa_tables['duplicate_source_relationships']):,}")
    print(f"Duplicate target relationship groups: {len(qa_tables['duplicate_target_relationships']):,}")
    print(f"Parent/child risk rows: {len(qa_tables['parent_child_risks']):,}")
    print(f"Wrote mapping candidates: {output_csv_path}")
    print(f"Wrote graph links: {graph_links_csv_path}")
    print(f"Wrote mapping workbook: {output_xlsx_path}")
    print(f"Wrote QA files to: {qa_dir}")

    return mapping_df, qa_tables

#%%
# User-tuned constants / flags.
SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = _find_repo_root(SCRIPT_PATH.parent)
RESULTS_DIR = REPO_ROOT / "results" / "mapping_graph_index"

SOURCE_MAPPING_PATH = (
    REPO_ROOT.parent / "leap_mappings" / "config" / "outlook_mappings_master.xlsx"
)
SOURCE_SHEET_NAME = "leap_combined_esto"
GRAPH_FLOW_PRODUCT_INDEX_PATH = RESULTS_DIR / "dashboard_graph_flow_product_index.csv"

OUTPUT_CSV_PATH = RESULTS_DIR / "esto_first_mapping_candidates_dashboard.csv"
OUTPUT_XLSX_PATH = RESULTS_DIR / "esto_first_mapping_candidates_dashboard.xlsx"
GRAPH_LINKS_CSV_PATH = RESULTS_DIR / "energy_balance_graph_links.csv"
QA_DIR = RESULTS_DIR

RUN_DASHBOARD_MAPPING_CONVERSION = True

#%%
try:
    if RUN_DASHBOARD_MAPPING_CONVERSION:
        run_dashboard_mapping_conversion(
            source_mapping_path=SOURCE_MAPPING_PATH,
            source_sheet_name=SOURCE_SHEET_NAME,
            graph_flow_product_index_path=GRAPH_FLOW_PRODUCT_INDEX_PATH,
            output_csv_path=OUTPUT_CSV_PATH,
            output_xlsx_path=OUTPUT_XLSX_PATH,
            graph_links_csv_path=GRAPH_LINKS_CSV_PATH,
            qa_dir=QA_DIR,
        )
except Exception as exc:
    print("Dashboard mapping conversion failed.")
    print(f"Error: {exc}")
    raise

#%%
