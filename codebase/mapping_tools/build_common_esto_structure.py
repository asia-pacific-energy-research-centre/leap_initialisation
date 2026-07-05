#%%
"""
Build a generated common ESTO structure for LEAP / ESTO / 9th comparison.

The workflow treats exact ESTO flow/product pairs as graph nodes. Source rows
that map to multiple ESTO pairs add graph edges, so connected components become
the smallest common ESTO rows that do not split source aggregates.
"""

#%%
import hashlib
import re
from pathlib import Path
from typing import Any

import pandas as pd

#%%
COMMON_STRUCTURE_VERSION = "common_esto_v1"
AXIS_PARTITION_SOURCE_COMPONENT_LIMIT = 50
CONVERSION_USE_CASES = [
    "leap_to_esto_balance_conversion",
    "ninth_to_esto_balance_conversion",
]
COMPARISON_SCOPES = {
    "leap_vs_esto": {
        "systems": ["LEAP", "ESTO"],
        "use_cases": ["leap_to_esto_balance_conversion"],
        "aggregate_source_systems": ["LEAP"],
    },
    "leap_vs_ninth": {
        "systems": ["LEAP", "NINTH"],
        "use_cases": ["leap_to_esto_balance_conversion", "ninth_to_esto_balance_conversion"],
        "aggregate_source_systems": ["LEAP", "NINTH"],
    },
    "leap_vs_esto_vs_ninth": {
        "systems": ["LEAP", "ESTO", "NINTH"],
        "use_cases": ["leap_to_esto_balance_conversion", "ninth_to_esto_balance_conversion"],
        "aggregate_source_systems": ["LEAP", "NINTH"],
    },
    "esto_only": {
        "systems": ["ESTO"],
        "use_cases": ["leap_to_esto_balance_conversion", "ninth_to_esto_balance_conversion"],
        "aggregate_source_systems": [],
    },
}
COMMON_ROW_COLUMNS = [
    "comparison_scope",
    "common_structure_version",
    "common_row_id",
    "common_flow_code",
    "common_flow_name",
    "common_flow_label",
    "common_product_code",
    "common_product_name",
    "common_product_label",
    "component_esto_flow",
    "component_esto_product",
    "component_flow_code",
    "component_flow_name",
    "component_product_code",
    "component_product_name",
    "component_sign",
    "is_exact_row",
    "requires_rollup",
    "common_row_basis",
    "aggregate_group_source",
    "aggregate_group_source_id",
    "aggregation_reason",
    "notes",
]
MAP_COLUMNS = [
    "comparison_scope",
    "component_esto_flow",
    "component_esto_product",
    "common_row_id",
    "common_flow_label",
    "common_product_label",
    "component_sign",
]
OVERRIDE_COLUMNS = [
    "comparison_scope",
    "override_group_id",
    "component_esto_flow",
    "component_esto_product",
    "preferred_common_flow_label",
    "preferred_common_product_label",
    "override_reason",
    "notes",
]
LABEL_OVERRIDE_COLUMNS = [
    "common_row_id",
    "auto_common_flow_label",
    "auto_common_product_label",
    "preferred_common_flow_label",
    "preferred_common_product_label",
    "notes",
]
COVERAGE_EXCLUSION_COLUMNS = [
    "use_case",
    "comparison_scope",
    "source_system",
    "target_system",
    "target_flow",
    "target_product",
    "exclusion_reason",
    "notes",
]

#%%
def _find_repo_root(start_path: Path) -> Path:
    """Find the repository root from a nested workflow path."""
    for candidate in [start_path, *start_path.parents]:
        if (candidate / "AGENTS.md").exists():
            return candidate
    raise FileNotFoundError(f"Could not find repo root above: {start_path}")


def read_table_if_exists(path: Path, columns: list[str] | None = None) -> pd.DataFrame:
    """Read a CSV/XLSX file if it exists, otherwise return an empty table."""
    if not path.exists():
        return pd.DataFrame(columns=columns or [])
    if path.suffix.lower() in {".xlsx", ".xlsm", ".xls"}:
        df = pd.read_excel(path)
    else:
        df = pd.read_csv(path)
    if columns is None:
        return df.fillna("")
    for column in columns:
        if column not in df.columns:
            df[column] = ""
    return df[columns].fillna("")


def normalise_text(value: Any) -> str:
    """Normalise text used for keys."""
    if pd.isna(value):
        return ""
    return re.sub(r"\s+", " ", str(value).strip())


def split_code_name(label: Any) -> tuple[str, str]:
    """Split an ESTO label into leading code and display name."""
    text = normalise_text(label)
    if not text:
        return "", ""
    match = re.match(r"^([0-9][0-9A-Za-z_.-]*(?:\.[0-9A-Za-z_.-]+)*)\s+(.+)$", text)
    if not match:
        return text, text
    return match.group(1).strip(), match.group(2).strip()


def code_sort_key(code: str) -> tuple[Any, ...]:
    """Sort dotted numeric-ish ESTO codes in a stable human order."""
    parts: list[Any] = []
    for part in re.split(r"([0-9]+)", str(code)):
        if not part:
            continue
        parts.append(int(part) if part.isdigit() else part)
    return tuple(parts)


def compress_codes(codes: list[str]) -> str:
    """Compress adjacent dotted codes like 07.12, 07.13, 07.14 into 07.12-07.14."""
    cleaned_codes = sorted({code for code in codes if code}, key=code_sort_key)
    if not cleaned_codes:
        return ""

    ranges: list[str] = []
    start = cleaned_codes[0]
    previous = cleaned_codes[0]

    def adjacent(left: str, right: str) -> bool:
        left_match = re.match(r"^(.+\.)(\d+)$", left)
        right_match = re.match(r"^(.+\.)(\d+)$", right)
        if not left_match or not right_match:
            return False
        return left_match.group(1) == right_match.group(1) and int(right_match.group(2)) == int(left_match.group(2)) + 1

    for code in cleaned_codes[1:]:
        if adjacent(previous, code):
            previous = code
            continue
        ranges.append(start if start == previous else f"{start}-{previous}")
        start = code
        previous = code
    ranges.append(start if start == previous else f"{start}-{previous}")
    return ",".join(ranges)


def common_row_id_for_components(component_pairs: list[tuple[str, str]]) -> str:
    """Create a stable common row ID from the exact ESTO component set."""
    key = "||".join(f"{flow}::{product}" for flow, product in sorted(component_pairs))
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return f"common_esto_{digest}"


def make_label(code: str, name: str) -> str:
    """Combine code and name while tolerating missing names."""
    if code and name:
        return f"{code} {name}"
    return code or name


def nearest_parent_name(component_codes: list[str], code_to_name: dict[str, str], fallback_name: str) -> str:
    """Find the nearest useful parent name from code prefixes."""
    cleaned_codes = [code for code in component_codes if code]
    if not cleaned_codes:
        return fallback_name
    first_segments = {code.split(".")[0] for code in cleaned_codes}
    if len(first_segments) == 1:
        parent_code = next(iter(first_segments))
        if parent_code in code_to_name:
            return code_to_name[parent_code]
    common_prefix = cleaned_codes[0]
    for code in cleaned_codes[1:]:
        while common_prefix and not code.startswith(common_prefix):
            common_prefix = common_prefix.rsplit(".", 1)[0] if "." in common_prefix else ""
    if common_prefix in code_to_name:
        return code_to_name[common_prefix]
    return fallback_name


def load_code_name_lookups(canonical_mapping_path: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Load ESTO flow/product labels from canonical ``leap_display_names``."""
    flow_lookup: dict[str, str] = {}
    product_lookup: dict[str, str] = {}
    try:
        labels_df = pd.read_excel(canonical_mapping_path, sheet_name="leap_display_names")
    except Exception:
        return flow_lookup, product_lookup
    for _, row in labels_df.iterrows():
        label = row.get("code", "")
        name = row.get("leap_display_name", "")
        label_type = normalise_text(row.get("code_type", "")).lower()
        code, parsed_name = split_code_name(label)
        clean_name = normalise_text(name) or parsed_name
        if not code or not clean_name:
            continue
        if label_type == "esto_flow":
            flow_lookup[code] = clean_name
        elif label_type == "esto_product":
            product_lookup[code] = clean_name
    return flow_lookup, product_lookup


def exclusion_applies(row: pd.Series, exclusions_df: pd.DataFrame, comparison_scope: str) -> bool:
    """Return True when a use-case-specific coverage exclusion removes a component."""
    if exclusions_df.empty:
        return False
    use_case = normalise_text(row.get("use_case", ""))
    scope = normalise_text(comparison_scope)
    source_system = normalise_text(row.get("source_system", ""))
    target_system = normalise_text(row.get("target_system", ""))
    target_flow = normalise_text(row.get("target_flow", ""))
    target_product = normalise_text(row.get("target_product", ""))
    exclusion_scopes = exclusions_df["comparison_scope"].astype(str).map(normalise_text)
    matches_df = exclusions_df[
        (exclusions_df["use_case"].astype(str).map(normalise_text) == use_case)
        & ((exclusion_scopes == "") | (exclusion_scopes == scope))
        & (exclusions_df["source_system"].astype(str).map(normalise_text) == source_system)
        & (exclusions_df["target_system"].astype(str).map(normalise_text) == target_system)
        & (exclusions_df["target_flow"].astype(str).map(normalise_text) == target_flow)
    ].copy()
    if matches_df.empty:
        return False
    products = matches_df["target_product"].astype(str).map(normalise_text)
    return bool(((products == "") | (products == target_product)).any())


def included_esto_relationships(
    relationships_df: pd.DataFrame,
    exclusions_df: pd.DataFrame,
    comparison_scope: str,
    use_cases: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return included ESTO-target relationships and rows excluded by coverage rules."""
    relationships_df = relationships_df.copy()
    relationships_df["include_in_use_case"] = relationships_df["include_in_use_case"].astype(str).str.lower().isin(["true", "1", "yes"])
    included_df = relationships_df[
        relationships_df["include_in_use_case"]
        & relationships_df["use_case"].isin(use_cases)
        & relationships_df["target_system"].eq("ESTO")
    ].copy()
    if included_df.empty:
        return included_df, pd.DataFrame()
    included_df["comparison_scope"] = comparison_scope
    exclusion_mask = included_df.apply(lambda row: exclusion_applies(row, exclusions_df, comparison_scope), axis=1)
    excluded_df = included_df[exclusion_mask].copy()
    excluded_df["component_status"] = "excluded_component"
    excluded_df["component_status_reason"] = "coverage_exclusion_applied"
    return included_df[~exclusion_mask].copy(), excluded_df


def component_pair(row: pd.Series) -> tuple[str, str]:
    """Return the exact ESTO component key for a relationship row."""
    return normalise_text(row.get("target_flow", "")), normalise_text(row.get("target_product", ""))


def build_required_components(relationships_df: pd.DataFrame) -> pd.DataFrame:
    """Build exact ESTO component rows from included conversion relationships."""
    if relationships_df.empty:
        return pd.DataFrame(columns=["component_esto_flow", "component_esto_product"])
    components_df = relationships_df[["target_flow", "target_product"]].copy()
    components_df["target_flow"] = components_df["target_flow"].map(normalise_text)
    components_df["target_product"] = components_df["target_product"].map(normalise_text)
    components_df = components_df.drop_duplicates().rename(
        columns={
            "target_flow": "component_esto_flow",
            "target_product": "component_esto_product",
        }
    )
    return components_df.sort_values(["component_esto_flow", "component_esto_product"]).reset_index(drop=True)


def find_root(parent: dict[tuple[str, str], tuple[str, str]], node: tuple[str, str]) -> tuple[str, str]:
    """Find a union-find root with path compression."""
    if parent[node] != node:
        parent[node] = find_root(parent, parent[node])
    return parent[node]


def union_nodes(parent: dict[tuple[str, str], tuple[str, str]], left: tuple[str, str], right: tuple[str, str]) -> None:
    """Union two component nodes."""
    left_root = find_root(parent, left)
    right_root = find_root(parent, right)
    if left_root != right_root:
        parent[right_root] = left_root


def source_group_id(row: pd.Series) -> str:
    """Create a readable source aggregate group ID."""
    return " :: ".join(
        [
            normalise_text(row.get("use_case", "")),
            normalise_text(row.get("source_system", "")),
            normalise_text(row.get("source_flow", "")),
            normalise_text(row.get("source_product", "")),
        ]
    )


def allocation_allows_split(group_df: pd.DataFrame) -> bool:
    """Return True when explicit allocation metadata allows splitting a source aggregate."""
    methods = set(group_df["allocation_method"].fillna("").astype(str).str.strip().str.lower())
    return bool(methods - {"", "direct", "none"})


def build_source_aggregate_edges(
    relationships_df: pd.DataFrame,
    comparison_scope: str,
    aggregate_source_systems: list[str],
) -> tuple[list[tuple[tuple[str, str], tuple[str, str]]], pd.DataFrame]:
    """Build graph edges from source rows that map to multiple ESTO components."""
    edges: list[tuple[tuple[str, str], tuple[str, str]]] = []
    aggregate_rows: list[dict[str, Any]] = []
    if not aggregate_source_systems:
        return edges, pd.DataFrame()
    relationships_df = relationships_df[relationships_df["source_system"].isin(aggregate_source_systems)].copy()
    group_columns = ["use_case", "source_system", "source_flow", "source_product"]
    for group_values, group_df in relationships_df.groupby(group_columns, dropna=False):
        component_pairs = sorted({component_pair(row) for _, row in group_df.iterrows()})
        if len(component_pairs) <= 1 or allocation_allows_split(group_df):
            continue
        for pair in component_pairs[1:]:
            edges.append((component_pairs[0], pair))
        aggregate_rows.append(
            {
                "comparison_scope": comparison_scope,
                "aggregate_group_source": group_values[1],
                "aggregate_group_source_id": source_group_id(group_df.iloc[0]),
                "use_case": group_values[0],
                "source_system": group_values[1],
                "source_flow": group_values[2],
                "source_product": group_values[3],
                "component_count": len(component_pairs),
                "component_pairs": "|".join(f"{flow} :: {product}" for flow, product in component_pairs),
                "aggregation_reason": f"{str(group_values[1]).lower()}_defined_aggregate",
            }
        )
    return edges, pd.DataFrame(aggregate_rows)


def build_manual_override_edges(
    overrides_df: pd.DataFrame,
    comparison_scope: str,
) -> tuple[list[tuple[tuple[str, str], tuple[str, str]]], pd.DataFrame]:
    """Build graph edges from manual common row overrides."""
    if overrides_df.empty:
        return [], pd.DataFrame()
    scope_values = overrides_df["comparison_scope"].astype(str).map(normalise_text)
    overrides_df = overrides_df[(scope_values == "") | (scope_values == normalise_text(comparison_scope))].copy()
    if overrides_df.empty:
        return [], pd.DataFrame()
    edges: list[tuple[tuple[str, str], tuple[str, str]]] = []
    rows: list[dict[str, Any]] = []
    for override_group_id, group_df in overrides_df.groupby("override_group_id", dropna=False):
        component_pairs = sorted(
            {
                (normalise_text(row["component_esto_flow"]), normalise_text(row["component_esto_product"]))
                for _, row in group_df.iterrows()
                if normalise_text(row["component_esto_flow"]) and normalise_text(row["component_esto_product"])
            }
        )
        if len(component_pairs) <= 1:
            continue
        for pair in component_pairs[1:]:
            edges.append((component_pairs[0], pair))
        rows.append(
            {
                "comparison_scope": comparison_scope,
                "aggregate_group_source": "manual_override",
                "aggregate_group_source_id": normalise_text(override_group_id),
                "component_count": len(component_pairs),
                "component_pairs": "|".join(f"{flow} :: {product}" for flow, product in component_pairs),
                "aggregation_reason": "manual_override",
            }
        )
    return edges, pd.DataFrame(rows)


def build_connected_components(
    components_df: pd.DataFrame,
    edges: list[tuple[tuple[str, str], tuple[str, str]]],
) -> dict[tuple[str, str], list[tuple[str, str]]]:
    """Build connected components from exact ESTO component nodes and edges."""
    nodes = [
        (normalise_text(row["component_esto_flow"]), normalise_text(row["component_esto_product"]))
        for _, row in components_df.iterrows()
    ]
    parent = {node: node for node in nodes}
    for left, right in edges:
        if left not in parent:
            parent[left] = left
        if right not in parent:
            parent[right] = right
        union_nodes(parent, left, right)

    components_by_root: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for node in sorted(parent):
        root = find_root(parent, node)
        components_by_root.setdefault(root, []).append(node)
    return components_by_root


def aggregate_metadata_for_component(
    component_pairs: list[tuple[str, str]],
    aggregate_groups_df: pd.DataFrame,
) -> tuple[str, str, str]:
    """Summarise why a common row was rolled up."""
    if len(component_pairs) == 1:
        return "exact_esto_component", "", ""
    component_set = set(component_pairs)
    matched_reasons: list[str] = []
    matched_sources: list[str] = []
    matched_ids: list[str] = []
    for _, row in aggregate_groups_df.iterrows():
        row_pairs: set[tuple[str, str]] = set()
        for text_pair in str(row.get("component_pairs", "")).split("|"):
            if " :: " not in text_pair:
                continue
            flow, product = text_pair.split(" :: ", 1)
            row_pairs.add((flow, product))
        if row_pairs and row_pairs.issubset(component_set):
            matched_reasons.append(normalise_text(row.get("aggregation_reason", "")))
            matched_sources.append(normalise_text(row.get("aggregate_group_source", "")))
            matched_ids.append(normalise_text(row.get("aggregate_group_source_id", "")))
    reason = "|".join(sorted({value for value in matched_reasons if value})) or "crossing_aggregate_groups"
    source = "|".join(sorted({value for value in matched_sources if value}))
    source_id = "|".join(sorted({value for value in matched_ids if value}))
    return reason, source, source_id


def build_common_rows(
    components_by_root: dict[tuple[str, str], list[tuple[str, str]]],
    aggregate_groups_df: pd.DataFrame,
    label_overrides_df: pd.DataFrame,
    flow_code_to_name: dict[str, str],
    product_code_to_name: dict[str, str],
    comparison_scope: str,
) -> pd.DataFrame:
    """Create common ESTO component rows from connected components."""
    output_rows: list[dict[str, Any]] = []
    label_override_map = {
        normalise_text(row["common_row_id"]): row
        for _, row in label_overrides_df.iterrows()
        if normalise_text(row.get("common_row_id", ""))
    }

    for component_pairs in components_by_root.values():
        component_pairs = sorted(component_pairs)
        common_row_id = common_row_id_for_components(component_pairs)
        flow_codes: list[str] = []
        flow_names: list[str] = []
        product_codes: list[str] = []
        product_names: list[str] = []
        for flow, product in component_pairs:
            flow_code, flow_name = split_code_name(flow)
            product_code, product_name = split_code_name(product)
            flow_codes.append(flow_code)
            flow_names.append(flow_name)
            product_codes.append(product_code)
            product_names.append(product_name)

        common_flow_code = compress_codes(flow_codes)
        common_product_code = compress_codes(product_codes)
        is_exact_row = len(component_pairs) == 1
        unique_flow_codes = {code for code in flow_codes if code}
        unique_product_codes = {code for code in product_codes if code}
        if len(unique_flow_codes) == 1:
            common_flow_name = flow_names[0] if flow_names else ""
        else:
            common_flow_name = nearest_parent_name(flow_codes, flow_code_to_name, flow_names[0] if flow_names else "")
        if len(unique_product_codes) == 1:
            common_product_name = product_names[0] if product_names else ""
        else:
            common_product_name = nearest_parent_name(product_codes, product_code_to_name, product_names[0] if product_names else "")
        auto_flow_label = make_label(common_flow_code, common_flow_name)
        auto_product_label = make_label(common_product_code, common_product_name)
        label_override = label_override_map.get(common_row_id)
        common_flow_label = normalise_text(label_override.get("preferred_common_flow_label", "")) if label_override is not None else ""
        common_product_label = normalise_text(label_override.get("preferred_common_product_label", "")) if label_override is not None else ""
        common_flow_label = common_flow_label or auto_flow_label
        common_product_label = common_product_label or auto_product_label
        aggregation_reason, aggregate_source, aggregate_source_id = aggregate_metadata_for_component(component_pairs, aggregate_groups_df)

        for flow, product in component_pairs:
            component_flow_code, component_flow_name = split_code_name(flow)
            component_product_code, component_product_name = split_code_name(product)
            output_rows.append(
                {
                    "comparison_scope": comparison_scope,
                    "common_structure_version": COMMON_STRUCTURE_VERSION,
                    "common_row_id": common_row_id,
                    "common_flow_code": common_flow_code,
                    "common_flow_name": common_flow_name,
                    "common_flow_label": common_flow_label,
                    "common_product_code": common_product_code,
                    "common_product_name": common_product_name,
                    "common_product_label": common_product_label,
                    "component_esto_flow": flow,
                    "component_esto_product": product,
                    "component_flow_code": component_flow_code,
                    "component_flow_name": component_flow_name,
                    "component_product_code": component_product_code,
                    "component_product_name": component_product_name,
                    "component_sign": 1,
                    "is_exact_row": is_exact_row,
                    "requires_rollup": not is_exact_row,
                    "common_row_basis": "exact_esto_row" if is_exact_row else "connected_component_rollup",
                    "aggregate_group_source": aggregate_source,
                    "aggregate_group_source_id": aggregate_source_id,
                    "aggregation_reason": "" if is_exact_row else aggregation_reason,
                    "notes": "",
                }
            )
    return pd.DataFrame(output_rows, columns=COMMON_ROW_COLUMNS).sort_values(
        ["common_flow_code", "common_product_code", "component_esto_flow", "component_esto_product"]
    )


def axis_settings(axis: str) -> dict[str, str]:
    """Return common/component column names for one axis."""
    if axis == "product":
        return {
            "component_label": "component_esto_product",
            "component_code": "component_product_code",
            "component_name": "component_product_name",
            "common_code": "common_product_code",
            "common_name": "common_product_name",
            "common_label": "common_product_label",
        }
    if axis == "flow":
        return {
            "component_label": "component_esto_flow",
            "component_code": "component_flow_code",
            "component_name": "component_flow_name",
            "common_code": "common_flow_code",
            "common_name": "common_flow_name",
            "common_label": "common_flow_label",
        }
    raise ValueError(f"Unsupported axis: {axis}")


def find_axis_partition_root(parent: dict[str, str], node: str) -> str:
    """Find an axis partition root with path compression."""
    if parent[node] != node:
        parent[node] = find_axis_partition_root(parent, parent[node])
    return parent[node]


def union_axis_partition_nodes(parent: dict[str, str], left: str, right: str) -> None:
    """Union two axis partition nodes."""
    left_root = find_axis_partition_root(parent, left)
    right_root = find_axis_partition_root(parent, right)
    if left_root != right_root:
        parent[right_root] = left_root


def build_axis_group_sets(common_rows_df: pd.DataFrame, axis: str, max_component_count: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build one axis component set per common row."""
    settings = axis_settings(axis)
    rows: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []
    for common_row_id, group_df in common_rows_df.groupby("common_row_id", dropna=False):
        if len(group_df) > max_component_count:
            first = group_df.iloc[0]
            skipped_rows.append(
                {
                    "axis": axis,
                    "common_row_id": common_row_id,
                    "common_flow_label": first["common_flow_label"],
                    "common_product_label": first["common_product_label"],
                    "exact_component_count": len(group_df),
                    "skip_reason": f"common_row_has_more_than_{max_component_count}_components",
                    "qa_status": "excluded_from_axis_partition_closure",
                    "qa_severity": "high",
                }
            )
            continue
        components = sorted({normalise_text(value) for value in group_df[settings["component_label"]] if normalise_text(value)})
        if not components:
            continue
        first = group_df.iloc[0]
        rows.append(
            {
                "axis": axis,
                "common_row_id": common_row_id,
                "group_label": first[settings["common_label"]],
                "component_count": len(components),
                "component_set": set(components),
                "component_list": "|".join(components),
            }
        )
    return pd.DataFrame(rows), pd.DataFrame(skipped_rows)


def build_intersecting_axis_group_diagnostics(axis_group_sets_df: pd.DataFrame) -> pd.DataFrame:
    """Find overlapping axis groups before partition closure."""
    if axis_group_sets_df.empty:
        return pd.DataFrame()
    diagnostics_rows: list[dict[str, Any]] = []
    group_rows = axis_group_sets_df.to_dict("records")
    for left_index, left in enumerate(group_rows):
        for right in group_rows[left_index + 1 :]:
            intersection = left["component_set"] & right["component_set"]
            if not intersection or left["component_set"] == right["component_set"]:
                continue
            diagnostics_rows.append(
                {
                    "axis": left["axis"],
                    "left_common_row_id": left["common_row_id"],
                    "right_common_row_id": right["common_row_id"],
                    "left_group_label": left["group_label"],
                    "right_group_label": right["group_label"],
                    "left_component_count": left["component_count"],
                    "right_component_count": right["component_count"],
                    "intersection_component_count": len(intersection),
                    "intersection_components": "|".join(sorted(intersection)),
                    "left_only_components": "|".join(sorted(left["component_set"] - right["component_set"])),
                    "right_only_components": "|".join(sorted(right["component_set"] - left["component_set"])),
                    "qa_status": "resolved_by_axis_partition_closure",
                    "qa_severity": "warning",
                    "qa_reason": f"intersecting_common_{left['axis']}_groups_were_closed_to_global_partition",
                }
            )
    return pd.DataFrame(diagnostics_rows)


def build_axis_partition_lookup(
    common_rows_df: pd.DataFrame,
    axis: str,
    code_to_name: dict[str, str],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build global non-overlapping partitions for product or flow labels."""
    settings = axis_settings(axis)
    axis_group_sets_df, skipped_broad_rows_df = build_axis_group_sets(
        common_rows_df,
        axis,
        max_component_count=AXIS_PARTITION_SOURCE_COMPONENT_LIMIT,
    )
    intersection_df = build_intersecting_axis_group_diagnostics(axis_group_sets_df)

    components = sorted(
        {
            normalise_text(value)
            for value in common_rows_df[settings["component_label"]]
            if normalise_text(value)
        }
    )
    parent = {component: component for component in components}
    for _, row in axis_group_sets_df.iterrows():
        group_components = sorted(row["component_set"])
        if len(group_components) <= 1:
            continue
        for component in group_components[1:]:
            union_axis_partition_nodes(parent, group_components[0], component)

    components_by_root: dict[str, list[str]] = {}
    for component in components:
        root = find_axis_partition_root(parent, component)
        components_by_root.setdefault(root, []).append(component)

    lookup_rows: list[dict[str, Any]] = []
    for root, partition_components in components_by_root.items():
        partition_components = sorted(partition_components)
        component_codes: list[str] = []
        component_names: list[str] = []
        for component in partition_components:
            component_code, component_name = split_code_name(component)
            component_codes.append(component_code)
            component_names.append(component_name)
        partition_code = compress_codes(component_codes)
        unique_codes = {code for code in component_codes if code}
        if len(unique_codes) == 1:
            partition_name = next((name for name in component_names if name), "")
        else:
            partition_name = nearest_parent_name(component_codes, code_to_name, component_names[0] if component_names else "")
        partition_label = make_label(partition_code, partition_name)
        partition_id = f"{axis}_partition_{hashlib.sha1('|'.join(partition_components).encode('utf-8')).hexdigest()[:16]}"
        for component in partition_components:
            lookup_rows.append(
                {
                    "axis": axis,
                    "axis_partition_id": partition_id,
                    "axis_partition_component_count": len(partition_components),
                    "component_label": component,
                    "partition_code": partition_code,
                    "partition_name": partition_name,
                    "partition_label": partition_label,
                    "partition_components": "|".join(partition_components),
                    "partition_created_by": "axis_partition_closure" if len(partition_components) > 1 else "exact_axis_component",
                }
            )
    return pd.DataFrame(lookup_rows), intersection_df, skipped_broad_rows_df


def apply_axis_partition_labels(
    common_rows_df: pd.DataFrame,
    product_partition_lookup_df: pd.DataFrame,
    flow_partition_lookup_df: pd.DataFrame,
) -> pd.DataFrame:
    """Apply global product and flow partition labels to common rows."""
    adjusted_df = common_rows_df.copy()
    for axis, lookup_df in [("product", product_partition_lookup_df), ("flow", flow_partition_lookup_df)]:
        settings = axis_settings(axis)
        if lookup_df.empty:
            continue
        axis_lookup_df = lookup_df[
            [
                "component_label",
                "axis_partition_id",
                "axis_partition_component_count",
                "partition_code",
                "partition_name",
                "partition_label",
                "partition_created_by",
            ]
        ].rename(
            columns={
                "component_label": settings["component_label"],
                "axis_partition_id": f"{axis}_partition_id",
                "axis_partition_component_count": f"{axis}_partition_component_count",
                "partition_code": f"{settings['common_code']}_partition",
                "partition_name": f"{settings['common_name']}_partition",
                "partition_label": f"{settings['common_label']}_partition",
                "partition_created_by": f"{axis}_partition_created_by",
            }
        )
        adjusted_df = adjusted_df.drop(
            columns=[
                column
                for column in [
                    f"{axis}_partition_id",
                    f"{axis}_partition_component_count",
                    f"{axis}_partition_created_by",
                ]
                if column in adjusted_df.columns
            ]
        )
        adjusted_df = adjusted_df.merge(axis_lookup_df, on=settings["component_label"], how="left")
        for common_column in [settings["common_code"], settings["common_name"], settings["common_label"]]:
            partition_column = f"{common_column}_partition"
            if partition_column in adjusted_df.columns:
                adjusted_df[common_column] = adjusted_df[partition_column].where(
                    adjusted_df[partition_column].fillna("").astype(str).str.strip().ne(""),
                    adjusted_df[common_column],
                )
                adjusted_df = adjusted_df.drop(columns=[partition_column])
    return adjusted_df[COMMON_ROW_COLUMNS + [column for column in adjusted_df.columns if column not in COMMON_ROW_COLUMNS]]


def build_map_table(common_rows_df: pd.DataFrame) -> pd.DataFrame:
    """Create the exact ESTO component to common row map."""
    if common_rows_df.empty:
        return pd.DataFrame(columns=MAP_COLUMNS)
    return common_rows_df[MAP_COLUMNS].drop_duplicates().reset_index(drop=True)


def build_duplicate_components(common_rows_df: pd.DataFrame) -> pd.DataFrame:
    """Find exact ESTO components assigned to more than one common row."""
    if common_rows_df.empty:
        return pd.DataFrame()
    counts_df = (
        common_rows_df.groupby(["comparison_scope", "component_esto_flow", "component_esto_product"], dropna=False)
        .agg(common_row_count=("common_row_id", "nunique"), common_row_ids=("common_row_id", lambda values: "|".join(sorted(set(values)))))
        .reset_index()
    )
    duplicate_df = counts_df[counts_df["common_row_count"] > 1].copy()
    duplicate_df["qa_status"] = "duplicate_component"
    duplicate_df["qa_severity"] = "high"
    return duplicate_df


def build_missing_components(required_components_df: pd.DataFrame, common_rows_df: pd.DataFrame) -> pd.DataFrame:
    """Find required exact ESTO components missing from the common structure."""
    if required_components_df.empty:
        return pd.DataFrame()
    assigned_df = common_rows_df[["component_esto_flow", "component_esto_product"]].drop_duplicates()
    missing_df = required_components_df.merge(
        assigned_df,
        on=["component_esto_flow", "component_esto_product"],
        how="left",
        indicator=True,
    )
    missing_df = missing_df[missing_df["_merge"] == "left_only"].drop(columns=["_merge"])
    missing_df["qa_status"] = "missing_component"
    missing_df["qa_severity"] = "high"
    return missing_df


def build_source_aggregate_split_check(source_aggregates_df: pd.DataFrame, map_df: pd.DataFrame) -> pd.DataFrame:
    """Flag source aggregate groups that are split across multiple common rows."""
    if source_aggregates_df.empty or map_df.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    map_lookup = {
        (row["comparison_scope"], row["component_esto_flow"], row["component_esto_product"]): row["common_row_id"]
        for _, row in map_df.iterrows()
    }
    for _, row in source_aggregates_df.iterrows():
        common_ids: set[str] = set()
        comparison_scope = row.get("comparison_scope", "")
        for text_pair in str(row.get("component_pairs", "")).split("|"):
            if " :: " not in text_pair:
                continue
            flow, product = text_pair.split(" :: ", 1)
            common_id = map_lookup.get((comparison_scope, flow, product))
            if common_id:
                common_ids.add(common_id)
        if len(common_ids) > 1:
            output_row = row.to_dict()
            output_row["common_row_ids"] = "|".join(sorted(common_ids))
            output_row["qa_status"] = "source_aggregate_split_across_common_rows"
            output_row["qa_severity"] = "high"
            rows.append(output_row)
    return pd.DataFrame(rows)


def build_unresolved_partial_coverage(relationships_df: pd.DataFrame, common_rows_df: pd.DataFrame) -> pd.DataFrame:
    """Flag source coverage that touches but does not cover a common row."""
    if relationships_df.empty or common_rows_df.empty:
        return pd.DataFrame()
    component_to_common = {
        (row["comparison_scope"], row["component_esto_flow"], row["component_esto_product"]): row["common_row_id"]
        for _, row in common_rows_df.iterrows()
    }
    common_components = {
        (comparison_scope, common_row_id): set(zip(group_df["component_esto_flow"], group_df["component_esto_product"]))
        for (comparison_scope, common_row_id), group_df in common_rows_df.groupby(["comparison_scope", "common_row_id"], dropna=False)
    }
    rows: list[dict[str, Any]] = []
    for (comparison_scope, use_case, source_system), source_df in relationships_df.groupby(["comparison_scope", "use_case", "source_system"], dropna=False):
        covered_by_common: dict[str, set[tuple[str, str]]] = {}
        for _, row in source_df.iterrows():
            pair = component_pair(row)
            common_row_id = component_to_common.get((comparison_scope, pair[0], pair[1]))
            if common_row_id:
                covered_by_common.setdefault(common_row_id, set()).add(pair)
        for common_row_id, covered_pairs in covered_by_common.items():
            expected_pairs = common_components.get((comparison_scope, common_row_id), set())
            if expected_pairs and covered_pairs and covered_pairs != expected_pairs:
                rows.append(
                    {
                        "comparison_scope": comparison_scope,
                        "use_case": use_case,
                        "source_system": source_system,
                        "common_row_id": common_row_id,
                        "covered_component_count": len(covered_pairs),
                        "expected_component_count": len(expected_pairs),
                        "missing_component_pairs": "|".join(
                            f"{flow} :: {product}" for flow, product in sorted(expected_pairs - covered_pairs)
                        ),
                        "qa_status": "unresolved_partial_component_coverage",
                        "qa_severity": "high",
                    }
                )
    return pd.DataFrame(rows)


def build_structure_summary(
    relationships_df: pd.DataFrame,
    excluded_components_df: pd.DataFrame,
    source_aggregates_df: pd.DataFrame,
    manual_aggregates_df: pd.DataFrame,
    common_rows_df: pd.DataFrame,
    missing_df: pd.DataFrame,
    duplicate_df: pd.DataFrame,
    split_df: pd.DataFrame,
    unresolved_df: pd.DataFrame,
) -> pd.DataFrame:
    """Build summary metrics for console and CSV output."""
    comparison_scope = common_rows_df["comparison_scope"].iloc[0] if not common_rows_df.empty else ""
    common_summary_df = common_rows_df[["comparison_scope", "common_row_id", "is_exact_row", "requires_rollup"]].drop_duplicates()
    metrics = [
        ("exact_esto_components_read", int(common_rows_df[["component_esto_flow", "component_esto_product"]].drop_duplicates().shape[0])),
        ("excluded_components", int(len(excluded_components_df))),
        ("leap_defined_aggregate_groups", int((source_aggregates_df["aggregate_group_source"] == "LEAP").sum()) if not source_aggregates_df.empty else 0),
        ("ninth_defined_aggregate_groups", int((source_aggregates_df["aggregate_group_source"] == "NINTH").sum()) if not source_aggregates_df.empty else 0),
        ("manual_override_groups", int(len(manual_aggregates_df))),
        ("common_rows_created", int(len(common_summary_df))),
        ("exact_common_rows", int(common_summary_df["is_exact_row"].sum()) if not common_summary_df.empty else 0),
        ("rolled_up_common_rows", int(common_summary_df["requires_rollup"].sum()) if not common_summary_df.empty else 0),
        ("missing_components", int(len(missing_df))),
        ("duplicate_components", int(len(duplicate_df))),
        ("unresolved_partial_coverage_rows", int(len(unresolved_df))),
        ("source_aggregate_split_issues", int(len(split_df))),
        ("included_conversion_relationships_read", int(len(relationships_df))),
    ]
    summary_df = pd.DataFrame(metrics, columns=["metric", "value"])
    summary_df.insert(0, "comparison_scope", comparison_scope)
    return summary_df


def save_outputs(
    common_rows_df: pd.DataFrame,
    map_df: pd.DataFrame,
    qa_outputs: dict[str, pd.DataFrame],
    output_dir: Path,
) -> None:
    """Write common structure and QA outputs."""
    output_dir.mkdir(parents=True, exist_ok=True)
    common_rows_df.to_csv(output_dir / "common_esto_rows.csv", index=False)
    common_rows_df.to_csv(output_dir / "common_esto_row_components.csv", index=False)
    map_df.to_csv(output_dir / "esto_to_common_esto_map.csv", index=False)
    for name, df in qa_outputs.items():
        df.to_csv(output_dir / f"{name}.csv", index=False)
    with pd.ExcelWriter(output_dir / "common_esto_rows.xlsx", engine="openpyxl") as writer:
        common_rows_df.to_excel(writer, sheet_name="common_esto_rows", index=False)
        map_df.to_excel(writer, sheet_name="esto_to_common_esto_map", index=False)
        for name, df in qa_outputs.items():
            df.to_excel(writer, sheet_name=name[:31], index=False)
    with pd.ExcelWriter(output_dir / "common_esto_structure.xlsx", engine="openpyxl") as writer:
        common_rows_df.to_excel(writer, sheet_name="common_esto_rows", index=False)
        map_df.to_excel(writer, sheet_name="esto_to_common_esto_map", index=False)
        for name, df in qa_outputs.items():
            df.to_excel(writer, sheet_name=name[:31], index=False)


def build_common_esto_for_scope(
    comparison_scope: str,
    scope_config: dict[str, list[str]],
    relationships_df: pd.DataFrame,
    exclusions_df: pd.DataFrame,
    overrides_df: pd.DataFrame,
    label_overrides_df: pd.DataFrame,
    flow_code_to_name: dict[str, str],
    product_code_to_name: dict[str, str],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, pd.DataFrame]]:
    """Build common ESTO rows, map rows, and QA outputs for one comparison scope."""
    included_df, excluded_components_df = included_esto_relationships(
        relationships_df,
        exclusions_df,
        comparison_scope=comparison_scope,
        use_cases=scope_config["use_cases"],
    )
    required_components_df = build_required_components(included_df)
    source_edges, source_aggregates_df = build_source_aggregate_edges(
        included_df,
        comparison_scope=comparison_scope,
        aggregate_source_systems=scope_config["aggregate_source_systems"],
    )
    override_edges, manual_aggregates_df = build_manual_override_edges(
        overrides_df,
        comparison_scope=comparison_scope,
    )
    aggregate_groups_df = pd.concat([source_aggregates_df, manual_aggregates_df], ignore_index=True)
    components_by_root = build_connected_components(required_components_df, source_edges + override_edges)
    common_rows_df = build_common_rows(
        components_by_root,
        aggregate_groups_df,
        label_overrides_df,
        flow_code_to_name,
        product_code_to_name,
        comparison_scope=comparison_scope,
    )
    if common_rows_df.empty:
        map_df = build_map_table(common_rows_df)
        qa_outputs = {
            "qa_common_esto_structure_summary": pd.DataFrame({"comparison_scope": [comparison_scope], "metric": ["common_rows_created"], "value": [0]}),
            "qa_common_esto_components_missing_from_structure": pd.DataFrame(),
            "qa_common_esto_duplicate_components": pd.DataFrame(),
            "qa_common_esto_source_aggregates_split": pd.DataFrame(),
            "qa_common_esto_rollup_explanations": pd.DataFrame(),
            "qa_common_esto_unresolved_partial_coverage": pd.DataFrame(),
        }
        return common_rows_df, map_df, qa_outputs

    product_partition_lookup_df, product_intersections_df, product_partition_skipped_df = build_axis_partition_lookup(
        common_rows_df,
        axis="product",
        code_to_name=product_code_to_name,
    )
    flow_partition_lookup_df, flow_intersections_df, flow_partition_skipped_df = build_axis_partition_lookup(
        common_rows_df,
        axis="flow",
        code_to_name=flow_code_to_name,
    )
    common_rows_df = apply_axis_partition_labels(
        common_rows_df,
        product_partition_lookup_df=product_partition_lookup_df,
        flow_partition_lookup_df=flow_partition_lookup_df,
    )
    map_df = build_map_table(common_rows_df)

    missing_df = build_missing_components(required_components_df, common_rows_df)
    if not missing_df.empty:
        missing_df.insert(0, "comparison_scope", comparison_scope)
    duplicate_df = build_duplicate_components(common_rows_df)
    split_df = build_source_aggregate_split_check(source_aggregates_df, map_df)
    rollup_df = common_rows_df[common_rows_df["requires_rollup"]].copy()
    unresolved_df = build_unresolved_partial_coverage(included_df, common_rows_df)
    summary_df = build_structure_summary(
        relationships_df=included_df,
        excluded_components_df=excluded_components_df,
        source_aggregates_df=source_aggregates_df,
        manual_aggregates_df=manual_aggregates_df,
        common_rows_df=common_rows_df,
        missing_df=missing_df,
        duplicate_df=duplicate_df,
        split_df=split_df,
        unresolved_df=unresolved_df,
    )
    qa_outputs = {
        "qa_common_esto_structure_summary": summary_df,
        "qa_common_esto_components_missing_from_structure": missing_df,
        "qa_common_esto_duplicate_components": duplicate_df,
        "qa_common_esto_source_aggregates_split": split_df,
        "qa_common_esto_rollup_explanations": rollup_df,
        "qa_common_esto_unresolved_partial_coverage": unresolved_df,
        "qa_common_esto_product_axis_partitions": product_partition_lookup_df.assign(comparison_scope=comparison_scope),
        "qa_common_esto_flow_axis_partitions": flow_partition_lookup_df.assign(comparison_scope=comparison_scope),
        "qa_common_esto_product_intersections_resolved": product_intersections_df.assign(comparison_scope=comparison_scope),
        "qa_common_esto_flow_intersections_resolved": flow_intersections_df.assign(comparison_scope=comparison_scope),
        "qa_common_esto_axis_partition_skipped_broad_rows": pd.concat(
            [product_partition_skipped_df, flow_partition_skipped_df],
            ignore_index=True,
        ).assign(comparison_scope=comparison_scope),
        "qa_common_esto_excluded_components": excluded_components_df,
    }
    return common_rows_df, map_df, qa_outputs


def run_common_esto_structure_workflow(
    relationships_path: Path,
    coverage_exclusions_path: Path,
    common_esto_overrides_path: Path,
    common_esto_label_overrides_path: Path,
    canonical_mapping_path: Path,
    output_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, pd.DataFrame]]:
    """Build the common ESTO structure and QA outputs."""
    relationships_df = pd.read_csv(relationships_path, low_memory=False)
    exclusions_df = read_table_if_exists(coverage_exclusions_path, COVERAGE_EXCLUSION_COLUMNS)
    overrides_df = read_table_if_exists(common_esto_overrides_path, OVERRIDE_COLUMNS)
    label_overrides_df = read_table_if_exists(common_esto_label_overrides_path, LABEL_OVERRIDE_COLUMNS)
    flow_code_to_name, product_code_to_name = load_code_name_lookups(canonical_mapping_path)

    common_frames: list[pd.DataFrame] = []
    map_frames: list[pd.DataFrame] = []
    qa_frames: dict[str, list[pd.DataFrame]] = {}
    for comparison_scope, scope_config in COMPARISON_SCOPES.items():
        scope_common_df, scope_map_df, scope_qa_outputs = build_common_esto_for_scope(
            comparison_scope=comparison_scope,
            scope_config=scope_config,
            relationships_df=relationships_df,
            exclusions_df=exclusions_df,
            overrides_df=overrides_df,
            label_overrides_df=label_overrides_df,
            flow_code_to_name=flow_code_to_name,
            product_code_to_name=product_code_to_name,
        )
        common_frames.append(scope_common_df)
        map_frames.append(scope_map_df)
        for qa_name, qa_df in scope_qa_outputs.items():
            qa_frames.setdefault(qa_name, []).append(qa_df)

    common_rows_df = pd.concat(common_frames, ignore_index=True) if common_frames else pd.DataFrame(columns=COMMON_ROW_COLUMNS)
    map_df = pd.concat(map_frames, ignore_index=True) if map_frames else pd.DataFrame(columns=MAP_COLUMNS)
    qa_outputs = {
        qa_name: pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        for qa_name, frames in qa_frames.items()
    }
    save_outputs(common_rows_df, map_df, qa_outputs, output_dir)

    summary_df = qa_outputs.get("qa_common_esto_structure_summary", pd.DataFrame())
    for _, row in summary_df.iterrows():
        print(f"{row['comparison_scope']} {row['metric']}: {row['value']}")
    print("before/after total differences: run apply_common_esto_structure.py with source data")
    print(f"Wrote common ESTO structure to: {output_dir}")
    return common_rows_df, map_df, qa_outputs

#%%
# User-tuned constants / flags.
SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = _find_repo_root(SCRIPT_PATH.parent)

RELATIONSHIP_DIR = REPO_ROOT / "results" / "mapping_relationships"
RELATIONSHIPS_PATH = RELATIONSHIP_DIR / "energy_balance_relationships.csv"
COVERAGE_EXCLUSIONS_PATH = RELATIONSHIP_DIR / "coverage_exclusions.csv"
COMMON_ESTO_OVERRIDES_PATH = RELATIONSHIP_DIR / "common_esto_overrides.csv"
COMMON_ESTO_LABEL_OVERRIDES_PATH = RELATIONSHIP_DIR / "common_esto_label_overrides.csv"
CANONICAL_MAPPING_PATH = REPO_ROOT.parent / "leap_mappings" / "config" / "outlook_mappings_master.xlsx"
OUTPUT_DIR = REPO_ROOT / "results" / "common_esto"

RUN_BUILD_COMMON_ESTO_STRUCTURE = True

#%%
try:
    if RUN_BUILD_COMMON_ESTO_STRUCTURE:
        run_common_esto_structure_workflow(
            relationships_path=RELATIONSHIPS_PATH,
            coverage_exclusions_path=COVERAGE_EXCLUSIONS_PATH,
            common_esto_overrides_path=COMMON_ESTO_OVERRIDES_PATH,
            common_esto_label_overrides_path=COMMON_ESTO_LABEL_OVERRIDES_PATH,
            canonical_mapping_path=CANONICAL_MAPPING_PATH,
            output_dir=OUTPUT_DIR,
        )
except Exception as exc:
    print("Common ESTO structure build failed.")
    print(f"Error: {exc}")
    raise

#%%
