#%%
"""
Build dashboard graph IDs and graph index tables.

This is a prototype helper for converting the LEAP comparison dashboard template
into a more explicit ESTO-first mapping structure. It does not modify the
original template JSON. It writes a graph-ID stamped copy and graph index CSVs.
"""

#%%
import copy
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

#%%
GRAPH_KEYS = ("aggregate_graphs", "by_fuel_graphs")

IGNORED_TREE_KEYS = {
    "defaults",
    "specified_fuel_mappings",
    "specified_fuel_mappings_sets",
    "product_color_legend",
    "placeholder_source_notes",
    "about_page",
    "Notes",
    "visible_note",
}

GRAPH_TYPE_SUFFIXES = {
    "aggregate_graphs": "aggregate",
    "by_fuel_graphs": "by_fuel",
}

GRAPH_INDEX_COLUMNS = [
    "graph_id",
    "page_path",
    "graph_type",
    "chart_type",
    "esto_flows_raw",
    "products_raw",
    "products_mode",
    "specified_products",
    "comparison_lines",
    "measures",
    "use_esto_to_ninth_mapping",
    "template_json_path",
]

GRAPH_FLOW_INDEX_COLUMNS = [
    "graph_id",
    "page_path",
    "graph_type",
    "esto_flow",
]

GRAPH_PRODUCT_INDEX_COLUMNS = [
    "graph_id",
    "page_path",
    "graph_type",
    "product",
    "product_source",
]

GRAPH_FLOW_PRODUCT_INDEX_COLUMNS = [
    "graph_id",
    "page_path",
    "graph_type",
    "esto_flow",
    "product_match_mode",
    "esto_product",
    "products_raw",
    "products_mode",
    "product_source",
    "specified_products",
]

#%%
def _find_repo_root(start_path: Path) -> Path:
    """Find the leap_utilities repo root from a nested uploaded helper path."""
    for candidate in [start_path, *start_path.parents]:
        if (candidate / "AGENTS.md").exists() and (candidate / "config" / "leap_mappings.xlsx").exists():
            return candidate
    raise FileNotFoundError(f"Could not find repo root above: {start_path}")


def _first_existing_path(paths: list[Path]) -> Path:
    """Return the first existing path from a short list of expected locations."""
    for path in paths:
        if path.exists():
            return path
    return paths[0]


def slugify(value: str) -> str:
    """Convert a human-readable label into a stable lowercase slug."""
    text = "" if value is None else str(value)
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def as_list(value: Any) -> list[Any]:
    """Return value as a list while preserving existing lists."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def json_string(value: Any) -> str:
    """Serialise a raw JSON-like value for compact CSV storage."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def is_ignored_template_key(key: str) -> bool:
    """Return True for metadata keys that should not count as dashboard path nodes."""
    if key in IGNORED_TREE_KEYS:
        return True
    if key.startswith("_"):
        return True
    if key.startswith("note") or key.startswith("Note"):
        return True
    return False


def stable_unique_graph_id(page_path: list[str], graph_type: str, used_ids: dict[str, int]) -> str:
    """Build a unique graph ID from the page path and graph type."""
    path_slug = "__".join(slugify(part) for part in page_path if slugify(part))
    suffix = GRAPH_TYPE_SUFFIXES.get(graph_type, slugify(graph_type))
    base_id = f"dashboard__{path_slug}__{suffix}" if path_slug else f"dashboard__{suffix}"

    used_ids[base_id] = used_ids.get(base_id, 0) + 1
    if used_ids[base_id] == 1:
        return base_id
    return f"{base_id}__{used_ids[base_id]}"


def load_dashboard_template(path: Path) -> dict[str, Any]:
    """Load dashboard template JSON."""
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_dashboard_template(template: dict[str, Any], path: Path) -> None:
    """Save dashboard template JSON with readable indentation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(template, file, ensure_ascii=False, indent=2)
        file.write("\n")


def resolve_grouped_products(
    specified_products: str,
    template: dict[str, Any],
) -> list[dict[str, str]]:
    """Resolve product group names through specified_fuel_mappings where possible."""
    product_rows: list[dict[str, str]] = []
    mapping_sets = template.get("specified_fuel_mappings_sets", {}) or {}
    fuel_mappings = template.get("specified_fuel_mappings", {}) or {}

    group_names = mapping_sets.get(specified_products, [])
    for group_name in as_list(group_names):
        resolved_products = fuel_mappings.get(group_name)
        if resolved_products:
            for product in as_list(resolved_products):
                product_rows.append(
                    {
                        "product": str(product),
                        "product_source": f"{specified_products}:{group_name}",
                    }
                )
        else:
            product_rows.append(
                {
                    "product": str(group_name),
                    "product_source": str(specified_products),
                }
            )
    return product_rows


def product_rule(
    product_match_mode: str,
    esto_product: str = "",
    product_source: str = "",
    specified_products: str = "",
) -> dict[str, str]:
    """Build one product matching rule row."""
    return {
        "product_match_mode": product_match_mode,
        "esto_product": esto_product,
        "product_source": product_source,
        "specified_products": specified_products,
    }


def resolve_products_for_graph(
    graph_config: dict[str, Any],
    template: dict[str, Any],
) -> dict[str, Any]:
    """Resolve product config into explicit product matching rules."""
    products_value = graph_config.get("products")
    fuels_value = graph_config.get("fuels")
    product_config_source = "products"

    if products_value is None and fuels_value is not None:
        products_value = fuels_value
        product_config_source = "fuels"

    product_rows: list[dict[str, str]] = []
    products_mode = "unspecified"
    specified_products = ""
    product_match_rules: list[dict[str, str]] = []

    if isinstance(products_value, str):
        if products_value.lower() == "all":
            products_mode = "all_products"
            product_match_rules.append(
                product_rule("all_products", product_source=product_config_source)
            )
        elif products_value.lower() == "total":
            products_mode = "total_chart"
            product_match_rules.append(
                product_rule("total_chart", product_source=product_config_source)
            )
        else:
            products_mode = "specified_products"
            product_rows.append({"product": products_value, "product_source": product_config_source})
            product_match_rules.append(
                product_rule(
                    "specified_products",
                    esto_product=products_value,
                    product_source=product_config_source,
                )
            )

    elif isinstance(products_value, list):
        products_mode = "specified_products"
        product_rows = [
            {"product": str(product), "product_source": product_config_source}
            for product in products_value
        ]
        product_match_rules = [
            product_rule(
                "specified_products",
                esto_product=str(product),
                product_source=product_config_source,
            )
            for product in products_value
        ]

    elif isinstance(products_value, dict):
        specified_products = str(products_value.get("specified_products", "") or "")
        how_value = str(products_value.get("how", "") or "").lower()
        products_mode = "specified_products" if specified_products else how_value or "object"
        if specified_products:
            product_rows = resolve_grouped_products(specified_products, template)
            product_match_rules = [
                product_rule(
                    "specified_products",
                    esto_product=product_row["product"],
                    product_source=product_row["product_source"],
                    specified_products=specified_products,
                )
                for product_row in product_rows
            ]

    if not product_match_rules:
        products_mode = "all_products"
        product_match_rules.append(
            product_rule("all_products", product_source="default_unspecified")
        )

    return {
        "products_raw": json_string(products_value),
        "products_mode": products_mode,
        "specified_products": specified_products,
        "product_rows": product_rows,
        "product_match_rules": product_match_rules,
    }


def walk_graph_configs(
    node: Any,
    page_path: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Find aggregate_graphs and by_fuel_graphs objects and return graph metadata."""
    if page_path is None:
        page_path = []

    graph_records: list[dict[str, Any]] = []
    if not isinstance(node, dict):
        return graph_records

    for graph_key in GRAPH_KEYS:
        graph_config = node.get(graph_key)
        if isinstance(graph_config, dict):
            graph_records.append(
                {
                    "page_path_parts": list(page_path),
                    "page_path": " > ".join(page_path),
                    "graph_type": graph_key,
                    "graph_config": graph_config,
                }
            )

    for key, child in node.items():
        if key in GRAPH_KEYS or is_ignored_template_key(str(key)):
            continue
        if isinstance(child, dict):
            graph_records.extend(walk_graph_configs(child, page_path + [str(key)]))

    return graph_records


def add_graph_ids_to_template(
    template: dict[str, Any],
    template_json_path: Path,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Add graph_id fields and return graph index tables."""
    updated_template = copy.deepcopy(template)
    graph_records = walk_graph_configs(updated_template)
    used_ids: dict[str, int] = {}

    graph_index_rows: list[dict[str, Any]] = []
    graph_flow_rows: list[dict[str, Any]] = []
    graph_product_rows: list[dict[str, Any]] = []
    graph_flow_product_rows: list[dict[str, Any]] = []

    for record in graph_records:
        graph_config = record["graph_config"]
        graph_id = stable_unique_graph_id(
            record["page_path_parts"],
            record["graph_type"],
            used_ids,
        )
        graph_config["graph_id"] = graph_id
        graph_config.setdefault("use_case", "dashboard")

        product_info = resolve_products_for_graph(graph_config, updated_template)
        esto_flows = [str(flow) for flow in as_list(graph_config.get("esto_flows"))]

        graph_index_rows.append(
            {
                "graph_id": graph_id,
                "page_path": record["page_path"],
                "graph_type": record["graph_type"],
                "chart_type": graph_config.get("chart_type", ""),
                "esto_flows_raw": json_string(graph_config.get("esto_flows")),
                "products_raw": product_info["products_raw"],
                "products_mode": product_info["products_mode"],
                "specified_products": product_info["specified_products"],
                "comparison_lines": json_string(graph_config.get("comparison_lines")),
                "measures": json_string(graph_config.get("measures")),
                "use_esto_to_ninth_mapping": bool(graph_config.get("use_esto_to_ninth_mapping", False)),
                "template_json_path": str(template_json_path),
            }
        )

        for esto_flow in esto_flows:
            graph_flow_rows.append(
                {
                    "graph_id": graph_id,
                    "page_path": record["page_path"],
                    "graph_type": record["graph_type"],
                    "esto_flow": esto_flow,
                }
            )
            for product_rule_row in product_info["product_match_rules"]:
                graph_flow_product_rows.append(
                    {
                        "graph_id": graph_id,
                        "page_path": record["page_path"],
                        "graph_type": record["graph_type"],
                        "esto_flow": esto_flow,
                        "product_match_mode": product_rule_row["product_match_mode"],
                        "esto_product": product_rule_row["esto_product"],
                        "products_raw": product_info["products_raw"],
                        "products_mode": product_info["products_mode"],
                        "product_source": product_rule_row["product_source"],
                        "specified_products": product_rule_row["specified_products"],
                    }
                )

        for product_row in product_info["product_rows"]:
            graph_product_rows.append(
                {
                    "graph_id": graph_id,
                    "page_path": record["page_path"],
                    "graph_type": record["graph_type"],
                    "product": product_row["product"],
                    "product_source": product_row["product_source"],
                }
            )

    graph_index_df = pd.DataFrame(graph_index_rows, columns=GRAPH_INDEX_COLUMNS)
    graph_flow_index_df = pd.DataFrame(graph_flow_rows, columns=GRAPH_FLOW_INDEX_COLUMNS)
    graph_product_index_df = pd.DataFrame(graph_product_rows, columns=GRAPH_PRODUCT_INDEX_COLUMNS)
    graph_flow_product_index_df = pd.DataFrame(
        graph_flow_product_rows,
        columns=GRAPH_FLOW_PRODUCT_INDEX_COLUMNS,
    )

    return updated_template, graph_index_df, graph_flow_index_df, graph_product_index_df, graph_flow_product_index_df


def save_outputs(
    updated_template: dict[str, Any],
    graph_index_df: pd.DataFrame,
    graph_flow_index_df: pd.DataFrame,
    graph_product_index_df: pd.DataFrame,
    graph_flow_product_index_df: pd.DataFrame,
    output_template_path: Path,
    graph_index_path: Path,
    graph_flow_index_path: Path,
    graph_product_index_path: Path,
    graph_flow_product_index_path: Path,
) -> None:
    """Save JSON and graph index CSV outputs."""
    output_template_path.parent.mkdir(parents=True, exist_ok=True)
    graph_index_path.parent.mkdir(parents=True, exist_ok=True)

    save_dashboard_template(updated_template, output_template_path)
    graph_index_df.to_csv(graph_index_path, index=False)
    graph_flow_index_df.to_csv(graph_flow_index_path, index=False)
    graph_product_index_df.to_csv(graph_product_index_path, index=False)
    graph_flow_product_index_df.to_csv(graph_flow_product_index_path, index=False)


def build_dashboard_graph_index(
    template_json_path: Path,
    output_template_path: Path,
    graph_index_path: Path,
    graph_flow_index_path: Path,
    graph_product_index_path: Path,
    graph_flow_product_index_path: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Run the graph-ID stamping and index export workflow."""
    template = load_dashboard_template(template_json_path)
    (
        updated_template,
        graph_index_df,
        graph_flow_index_df,
        graph_product_index_df,
        graph_flow_product_index_df,
    ) = add_graph_ids_to_template(
        template,
        template_json_path,
    )

    save_outputs(
        updated_template,
        graph_index_df,
        graph_flow_index_df,
        graph_product_index_df,
        graph_flow_product_index_df,
        output_template_path,
        graph_index_path,
        graph_flow_index_path,
        graph_product_index_path,
        graph_flow_product_index_path,
    )

    print(f"Graph configs found: {len(graph_index_df):,}")
    print(f"Unique graph IDs: {graph_index_df['graph_id'].nunique():,}")
    print(f"Unique ESTO flows in template: {graph_flow_index_df['esto_flow'].nunique():,}")
    print(f"Wrote stamped template: {output_template_path}")
    print(f"Wrote graph index: {graph_index_path}")
    print(f"Wrote graph-flow index: {graph_flow_index_path}")
    print(f"Wrote graph-product index: {graph_product_index_path}")
    print(f"Wrote graph-flow-product index: {graph_flow_product_index_path}")

    return graph_index_df, graph_flow_index_df, graph_product_index_df, graph_flow_product_index_df

#%%
# User-tuned constants / flags.
SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = _find_repo_root(SCRIPT_PATH.parent)
MAPPING_CODE_ROOT = SCRIPT_PATH.parents[2]

TEMPLATE_JSON_PATH = _first_existing_path(
    [
        REPO_ROOT / "config" / "leap_comparison_dashboard_template_v3.json",
        REPO_ROOT.parent / "leap_dashboard" / "config" / "leap_comparison_dashboard_template_v3.json",
        MAPPING_CODE_ROOT / "config" / "leap_comparison_dashboard_template_v3.json",
    ]
)
GRAPH_INDEX_DIR = REPO_ROOT / "results" / "mapping_graph_index"
OUTPUT_TEMPLATE_PATH = GRAPH_INDEX_DIR / "leap_comparison_dashboard_template_v3_with_graph_ids.json"
GRAPH_INDEX_PATH = GRAPH_INDEX_DIR / "dashboard_graph_index.csv"
GRAPH_FLOW_INDEX_PATH = GRAPH_INDEX_DIR / "dashboard_graph_flow_index.csv"
GRAPH_PRODUCT_INDEX_PATH = GRAPH_INDEX_DIR / "dashboard_graph_product_index.csv"
GRAPH_FLOW_PRODUCT_INDEX_PATH = GRAPH_INDEX_DIR / "dashboard_graph_flow_product_index.csv"

RUN_BUILD_GRAPH_INDEX = True

#%%
# Guarded so importing this module (e.g. by tooling/tests) does not run the
# build pipeline, which reads template files that may not exist.  Run the script
# directly to build the graph index.
if __name__ == "__main__":
    try:
        if RUN_BUILD_GRAPH_INDEX:
            build_dashboard_graph_index(
                template_json_path=TEMPLATE_JSON_PATH,
                output_template_path=OUTPUT_TEMPLATE_PATH,
                graph_index_path=GRAPH_INDEX_PATH,
                graph_flow_index_path=GRAPH_FLOW_INDEX_PATH,
                graph_product_index_path=GRAPH_PRODUCT_INDEX_PATH,
                graph_flow_product_index_path=GRAPH_FLOW_PRODUCT_INDEX_PATH,
            )
    except Exception as exc:
        print("Dashboard graph-index build failed.")
        print(f"Error: {exc}")
        raise

#%%
