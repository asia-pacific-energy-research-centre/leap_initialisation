#%%
"""
Build product-aware dashboard graph links from energy-balance relationships.

The dashboard still filters converted data by ESTO flow/product. This script
adds lineage by linking included dashboard-chart relationships to dashboard
graph IDs using the graph flow/product rule index.
"""

#%%
import re
from pathlib import Path
from typing import Any

import pandas as pd

#%%
GRAPH_LINK_COLUMNS = [
    "relationship_id",
    "relationship_key",
    "use_case",
    "graph_id",
    "page_path",
    "graph_type",
    "matched_esto_flow",
    "matched_esto_product",
    "product_match_mode",
    "match_basis",
]

DASHBOARD_RELATIONSHIP_COLUMNS = [
    "relationship_id",
    "relationship_key",
    "use_case",
    "include_in_use_case",
    "source_system",
    "source_flow",
    "source_product",
    "target_system",
    "target_flow",
    "target_product",
    "relationship_type",
    "relationship_level",
    "cardinality",
    "relationship_status",
    "exclude_reason",
    "graph_ids",
    "graph_count",
]

QA_FILENAMES = {
    "relationships_not_used_by_template": "dashboard_relationships_not_used_by_template.csv",
    "template_flows_without_mapping": "dashboard_template_flows_without_mapping.csv",
    "duplicate_source_relationships": "dashboard_duplicate_source_relationships.csv",
    "duplicate_target_relationships": "dashboard_duplicate_target_relationships.csv",
    "parent_child_risks": "dashboard_parent_child_risks.csv",
}

#%%
def _find_repo_root(start_path: Path) -> Path:
    """Find the leap_utilities repo root from a nested workflow path."""
    for candidate in [start_path, *start_path.parents]:
        if (candidate / "AGENTS.md").exists():
            return candidate
    raise FileNotFoundError(f"Could not find repo root above: {start_path}")


def normalise_match_text(value: Any) -> str:
    """Normalise text for exact matching."""
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


def is_total_or_subtotal_flow(flow: Any) -> bool:
    """Return True for total final rows or explicit total/subtotal labels."""
    text = "" if pd.isna(flow) else str(flow).strip().lower()
    return text.startswith(("12 ", "13 ", "12_", "13_")) or "total" in text or "subtotal" in text


def has_expected_cardinality(cardinality_text: Any) -> bool:
    """Return True when cardinality metadata says duplication can be expected."""
    text = "" if pd.isna(cardinality_text) else str(cardinality_text).strip().lower()
    return "many" in text or "multiple" in text or "ok" in text


def join_unique(values: pd.Series | list[Any]) -> str:
    """Join unique non-empty values with pipe separators."""
    raw_values = values.tolist() if isinstance(values, pd.Series) else values
    cleaned: list[str] = []
    seen: set[str] = set()
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
    relationships_df: pd.DataFrame,
    graph_flow_product_index_df: pd.DataFrame,
) -> pd.DataFrame:
    """Link dashboard relationships to graphs using ESTO flow and product rules."""
    relationship_df = relationships_df[
        (relationships_df["use_case"] == "dashboard_chart")
        & relationships_df["include_in_use_case"]
        & (relationships_df["target_system"] == "ESTO")
    ].copy()
    relationship_df["_flow_key"] = relationship_df["target_flow"].apply(normalise_match_text)
    relationship_df["_product_key"] = relationship_df["target_product"].apply(normalise_match_text)

    graph_rules_df = graph_flow_product_index_df.copy()
    graph_rules_df["_flow_key"] = graph_rules_df["esto_flow"].apply(normalise_match_text)
    graph_rules_df["_product_key"] = graph_rules_df["esto_product"].apply(normalise_match_text)
    graph_rules_df["product_match_mode"] = graph_rules_df["product_match_mode"].fillna("").astype(str)

    merged_df = relationship_df.merge(
        graph_rules_df,
        on="_flow_key",
        how="inner",
        suffixes=("", "_graph"),
    )
    wildcard_modes = {"all_products", "total_chart"}
    matched_df = merged_df[
        merged_df["product_match_mode"].isin(wildcard_modes)
        | (merged_df["_product_key"] == merged_df["_product_key_graph"])
    ].copy()

    if matched_df.empty:
        return pd.DataFrame(columns=GRAPH_LINK_COLUMNS)

    graph_links_df = pd.DataFrame(
        {
            "relationship_id": matched_df["relationship_id"],
            "relationship_key": matched_df["relationship_key"],
            "use_case": matched_df["use_case"],
            "graph_id": matched_df["graph_id"],
            "page_path": matched_df["page_path"],
            "graph_type": matched_df["graph_type"],
            "matched_esto_flow": matched_df["esto_flow"],
            "matched_esto_product": matched_df["esto_product"].fillna(""),
            "product_match_mode": matched_df["product_match_mode"],
            "match_basis": matched_df["product_match_mode"].map(
                {
                    "all_products": "target_flow_wildcard_product",
                    "total_chart": "target_flow_total_chart",
                    "specified_products": "target_flow_and_product",
                }
            ).fillna("target_flow_and_product"),
        }
    )
    return graph_links_df.drop_duplicates().sort_values(["relationship_id", "graph_id"])


def build_dashboard_relationships(
    relationships_df: pd.DataFrame,
    graph_links_df: pd.DataFrame,
) -> pd.DataFrame:
    """Build dashboard relationship view with convenience graph IDs."""
    dashboard_df = relationships_df[
        (relationships_df["use_case"] == "dashboard_chart")
        & (relationships_df["target_system"] == "ESTO")
    ].copy()
    if graph_links_df.empty:
        link_summary_df = pd.DataFrame(columns=["relationship_key", "graph_ids", "graph_count"])
    else:
        link_summary_df = (
            graph_links_df.groupby("relationship_key", as_index=False)
            .agg(graph_ids=("graph_id", join_unique))
        )
        link_summary_df["graph_count"] = link_summary_df["graph_ids"].apply(
            lambda value: 0 if not value else len(str(value).split("|"))
        )
    dashboard_df = dashboard_df.merge(link_summary_df, on="relationship_key", how="left")
    dashboard_df["graph_ids"] = dashboard_df["graph_ids"].fillna("")
    dashboard_df["graph_count"] = dashboard_df["graph_count"].fillna(0).astype(int)
    return dashboard_df[DASHBOARD_RELATIONSHIP_COLUMNS]


def classify_duplicate_row(row: pd.Series, duplicate_kind: str) -> pd.Series:
    """Classify duplicates without treating all duplicates as defects."""
    expected_duplicate = (
        has_expected_cardinality(row.get("cardinality", ""))
        or "total_final_rollup" in str(row.get("relationship_types", ""))
        or "total" in str(row.get("relationship_levels", ""))
        or any(is_total_or_subtotal_flow(flow) for flow in str(row.get("target_flows", "")).split("|"))
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


def build_duplicate_source_relationships(dashboard_df: pd.DataFrame) -> pd.DataFrame:
    """Find included source pairs that map to multiple dashboard target pairs."""
    included_df = dashboard_df[dashboard_df["include_in_use_case"]].copy()
    included_df["target_pair"] = included_df["target_flow"].astype(str) + " :: " + included_df["target_product"].astype(str)
    grouped_df = (
        included_df.groupby(["source_flow", "source_product"], dropna=False)
        .agg(
            relationship_count=("relationship_id", "size"),
            target_pair_count=("target_pair", "nunique"),
            target_pairs=("target_pair", join_unique),
            target_flows=("target_flow", join_unique),
            cardinality=("cardinality", join_unique),
            relationship_types=("relationship_type", join_unique),
            relationship_levels=("relationship_level", join_unique),
            graph_ids=("graph_ids", join_unique),
        )
        .reset_index()
    )
    duplicate_df = grouped_df[grouped_df["target_pair_count"] > 1].copy()
    if duplicate_df.empty:
        return duplicate_df
    classification_df = duplicate_df.apply(lambda row: classify_duplicate_row(row, "source-to-target"), axis=1)
    return pd.concat([duplicate_df, classification_df], axis=1)


def build_duplicate_target_relationships(dashboard_df: pd.DataFrame) -> pd.DataFrame:
    """Find included target pairs that receive multiple source pairs."""
    included_df = dashboard_df[dashboard_df["include_in_use_case"]].copy()
    included_df["source_pair"] = included_df["source_flow"].astype(str) + " :: " + included_df["source_product"].astype(str)
    grouped_df = (
        included_df.groupby(["target_flow", "target_product"], dropna=False)
        .agg(
            relationship_count=("relationship_id", "size"),
            source_pair_count=("source_pair", "nunique"),
            source_pairs=("source_pair", join_unique),
            target_flows=("target_flow", join_unique),
            cardinality=("cardinality", join_unique),
            relationship_types=("relationship_type", join_unique),
            relationship_levels=("relationship_level", join_unique),
            graph_ids=("graph_ids", join_unique),
        )
        .reset_index()
    )
    duplicate_df = grouped_df[grouped_df["source_pair_count"] > 1].copy()
    if duplicate_df.empty:
        return duplicate_df
    classification_df = duplicate_df.apply(lambda row: classify_duplicate_row(row, "target-to-source"), axis=1)
    return pd.concat([duplicate_df, classification_df], axis=1)


def build_parent_child_risks(dashboard_df: pd.DataFrame) -> pd.DataFrame:
    """Find included parent/child source paths that may double-count in graphs."""
    included_df = dashboard_df[
        dashboard_df["include_in_use_case"]
        & (dashboard_df["source_flow"].fillna("").astype(str).str.len() > 0)
    ].copy()
    risk_rows: list[dict[str, Any]] = []
    for graph_id, graph_group_df in included_df.assign(
        graph_id_list=included_df["graph_ids"].fillna("").apply(lambda value: [item for item in str(value).split("|") if item])
    ).explode("graph_id_list").groupby("graph_id_list", dropna=False):
        if not graph_id:
            continue
        records = graph_group_df.to_dict("records")
        for left_index, left in enumerate(records):
            for right in records[left_index + 1 :]:
                if is_parent_child_path(left["source_flow"], right["source_flow"]):
                    parent, child = left, right
                elif is_parent_child_path(right["source_flow"], left["source_flow"]):
                    parent, child = right, left
                else:
                    continue
                risk_rows.append(
                    {
                        "graph_id": graph_id,
                        "parent_relationship_id": parent["relationship_id"],
                        "child_relationship_id": child["relationship_id"],
                        "parent_source_flow": parent["source_flow"],
                        "child_source_flow": child["source_flow"],
                        "parent_source_product": parent["source_product"],
                        "child_source_product": child["source_product"],
                        "target_flows": join_unique([parent["target_flow"], child["target_flow"]]),
                        "target_products": join_unique([parent["target_product"], child["target_product"]]),
                        "cardinality": join_unique([parent["cardinality"], child["cardinality"]]),
                        "qa_status": "review",
                        "qa_severity": "warning",
                        "qa_reason": "Parent/child source paths can double-count if both relationships feed the same graph.",
                        "expected_duplicate": False,
                    }
                )
    return pd.DataFrame(risk_rows).drop_duplicates() if risk_rows else pd.DataFrame(risk_rows)


def build_dashboard_qa(
    dashboard_df: pd.DataFrame,
    graph_links_df: pd.DataFrame,
    graph_flow_product_index_df: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """Build dashboard chart coverage and risk QA."""
    included_df = dashboard_df[dashboard_df["include_in_use_case"]].copy()
    linked_keys = set(graph_links_df["relationship_key"]) if not graph_links_df.empty else set()
    relationships_not_used_df = included_df[~included_df["relationship_key"].isin(linked_keys)].copy()

    included_flows = set(included_df["target_flow"].dropna().astype(str).str.strip())
    template_flows_df = graph_flow_product_index_df[["esto_flow"]].drop_duplicates().copy()
    template_flows_df["esto_flow"] = template_flows_df["esto_flow"].fillna("").astype(str).str.strip()
    template_flows_without_mapping_df = template_flows_df[
        ~template_flows_df["esto_flow"].isin(included_flows)
    ].sort_values("esto_flow")

    return {
        "relationships_not_used_by_template": relationships_not_used_df,
        "template_flows_without_mapping": template_flows_without_mapping_df,
        "duplicate_source_relationships": build_duplicate_source_relationships(dashboard_df),
        "duplicate_target_relationships": build_duplicate_target_relationships(dashboard_df),
        "parent_child_risks": build_parent_child_risks(dashboard_df),
    }


def save_outputs(
    graph_links_df: pd.DataFrame,
    dashboard_df: pd.DataFrame,
    qa_tables: dict[str, pd.DataFrame],
    graph_links_path: Path,
    dashboard_relationships_path: Path,
    relationships_workbook_path: Path,
    qa_dir: Path,
) -> None:
    """Save graph links, dashboard relationships, QA CSVs, and workbook sheets."""
    graph_links_path.parent.mkdir(parents=True, exist_ok=True)
    qa_dir.mkdir(parents=True, exist_ok=True)
    graph_links_df.to_csv(graph_links_path, index=False)
    dashboard_df.to_csv(dashboard_relationships_path, index=False)
    for qa_name, qa_df in qa_tables.items():
        qa_df.to_csv(qa_dir / QA_FILENAMES[qa_name], index=False)

    if relationships_workbook_path.exists():
        try:
            with pd.ExcelWriter(relationships_workbook_path, engine="openpyxl", mode="a", if_sheet_exists="replace") as writer:
                graph_links_df.to_excel(writer, sheet_name="energy_balance_graph_links", index=False)
                dashboard_df.to_excel(writer, sheet_name="dashboard_relationships", index=False)
                pd.DataFrame(
                    [
                        {"qa_table": qa_name, "row_count": len(qa_df)}
                        for qa_name, qa_df in qa_tables.items()
                    ]
                ).to_excel(writer, sheet_name="qa_summary", index=False)
                qa_tables["relationships_not_used_by_template"].to_excel(writer, sheet_name="qa_missing", index=False)
                qa_tables["duplicate_source_relationships"].to_excel(writer, sheet_name="qa_duplicates", index=False)
                qa_tables["parent_child_risks"].to_excel(writer, sheet_name="qa_parent_child_risks", index=False)
        except Exception as exc:
            print(f"Skipped workbook graph-link append because workbook is not writable/readable: {exc}")


def run_graph_link_workflow(
    relationships_path: Path,
    graph_flow_product_index_path: Path,
    graph_links_path: Path,
    dashboard_relationships_path: Path,
    relationships_workbook_path: Path,
    qa_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, pd.DataFrame]]:
    """Run the dashboard graph-link workflow."""
    relationships_df = pd.read_csv(relationships_path)
    graph_flow_product_index_df = pd.read_csv(graph_flow_product_index_path)
    graph_links_df = build_product_aware_graph_links(relationships_df, graph_flow_product_index_df)
    dashboard_df = build_dashboard_relationships(relationships_df, graph_links_df)
    qa_tables = build_dashboard_qa(dashboard_df, graph_links_df, graph_flow_product_index_df)
    save_outputs(
        graph_links_df=graph_links_df,
        dashboard_df=dashboard_df,
        qa_tables=qa_tables,
        graph_links_path=graph_links_path,
        dashboard_relationships_path=dashboard_relationships_path,
        relationships_workbook_path=relationships_workbook_path,
        qa_dir=qa_dir,
    )

    print(f"Dashboard relationships read: {len(dashboard_df):,}")
    print(f"Included dashboard relationships: {int(dashboard_df['include_in_use_case'].sum()):,}")
    print(f"Graph links created: {len(graph_links_df):,}")
    print(f"Dashboard relationships not used by template: {len(qa_tables['relationships_not_used_by_template']):,}")
    print(f"Dashboard template flows without mapping: {len(qa_tables['template_flows_without_mapping']):,}")
    print(f"Duplicate source relationship groups: {len(qa_tables['duplicate_source_relationships']):,}")
    print(f"Duplicate target relationship groups: {len(qa_tables['duplicate_target_relationships']):,}")
    print(f"Parent/child risk count: {len(qa_tables['parent_child_risks']):,}")
    print(f"Wrote graph links: {graph_links_path}")
    print(f"Wrote dashboard relationships: {dashboard_relationships_path}")
    return graph_links_df, dashboard_df, qa_tables

#%%
# User-tuned constants / flags.
SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = _find_repo_root(SCRIPT_PATH.parent)

RELATIONSHIP_DIR = REPO_ROOT / "results" / "mapping_relationships"
GRAPH_INDEX_DIR = REPO_ROOT / "results" / "mapping_graph_index"
RELATIONSHIPS_PATH = RELATIONSHIP_DIR / "energy_balance_relationships.csv"
RELATIONSHIPS_WORKBOOK_PATH = RELATIONSHIP_DIR / "energy_balance_relationships.xlsx"
GRAPH_FLOW_PRODUCT_INDEX_PATH = GRAPH_INDEX_DIR / "dashboard_graph_flow_product_index.csv"
GRAPH_LINKS_PATH = GRAPH_INDEX_DIR / "energy_balance_graph_links.csv"
DASHBOARD_RELATIONSHIPS_PATH = GRAPH_INDEX_DIR / "dashboard_chart_relationships.csv"
QA_DIR = GRAPH_INDEX_DIR

RUN_BUILD_ENERGY_BALANCE_GRAPH_LINKS = True

#%%
try:
    if RUN_BUILD_ENERGY_BALANCE_GRAPH_LINKS:
        run_graph_link_workflow(
            relationships_path=RELATIONSHIPS_PATH,
            graph_flow_product_index_path=GRAPH_FLOW_PRODUCT_INDEX_PATH,
            graph_links_path=GRAPH_LINKS_PATH,
            dashboard_relationships_path=DASHBOARD_RELATIONSHIPS_PATH,
            relationships_workbook_path=RELATIONSHIPS_WORKBOOK_PATH,
            qa_dir=QA_DIR,
        )
except Exception as exc:
    print("Energy-balance graph-link build failed.")
    print(f"Error: {exc}")
    raise

#%%
