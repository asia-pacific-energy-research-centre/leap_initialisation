"""Diagnostic-only supply source preservation and reconciliation closure checks."""

#%%

from hashlib import sha256
from pathlib import Path
import re

import pandas as pd

from codebase.functions import supply_data_pipeline


SUPPLY_FLOWS = ("production", "imports", "exports")
SUPPLY_CONSERVATION_SCHEMA_VERSION = "1.0"
_CODE_PATTERN = re.compile(r"^\s*(\d+(?:[._]\d+)*)")


def build_baseline_supply_source_preservation(
    assets: tuple,
    supply_projection_table: pd.DataFrame,
    supply_primary_table: pd.DataFrame,
    economies: list[str],
    base_year: int,
    final_year: int,
    tolerance_pj: float = 1e-6,
    included_esto_products: set[str] | None = None,
) -> pd.DataFrame:
    """Return the backward-compatible headline supply preservation diagnostic."""
    totals, _, _ = build_baseline_supply_conservation_artifacts(
        assets=assets,
        supply_projection_table=supply_projection_table,
        supply_primary_table=supply_primary_table,
        economies=economies,
        base_year=base_year,
        final_year=final_year,
        tolerance_pj=tolerance_pj,
        included_esto_products=included_esto_products,
    )
    return totals


def build_baseline_supply_conservation_artifacts(
    assets: tuple,
    supply_projection_table: pd.DataFrame,
    supply_primary_table: pd.DataFrame,
    economies: list[str],
    base_year: int,
    final_year: int,
    tolerance_pj: float = 1e-6,
    included_esto_products: set[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build headline, breakdown, and lineage supply-conservation artifacts."""
    if tolerance_pj < 0:
        raise ValueError("tolerance_pj must be non-negative")
    dataset_map = assets[0]
    esto, _ = supply_data_pipeline.resolve_dataset(dataset_map, "esto")
    ninth, _ = supply_data_pipeline.resolve_dataset(dataset_map, "ninth")
    reference = _build_supply_reference_rows(
        esto=esto, ninth=ninth, economies=economies,
        base_year=base_year, final_year=final_year,
        included_esto_products=included_esto_products,
    )
    produced = _build_produced_supply_rows(
        supply_projection_table=supply_projection_table,
        supply_primary_table=supply_primary_table,
        economies=economies,
        included_esto_products=included_esto_products,
    )
    if reference[reference["included"]].empty and produced.empty:
        raise ValueError("Supply conservation comparison is empty")

    keys = ["economy", "flow", "year"]
    reference_totals = (reference[reference["included"]]
        .groupby(keys, as_index=False)["value"].sum()
        .rename(columns={"value": "reference_total"}))
    produced_totals = (produced.groupby(keys, as_index=False)["value"].sum()
        .rename(columns={"value": "resolved_total"}))
    totals = reference_totals.merge(produced_totals, on=keys, how="outer")
    totals[["reference_total", "resolved_total"]] = totals[
        ["reference_total", "resolved_total"]].fillna(0.0)
    totals["difference"] = totals["resolved_total"] - totals["reference_total"]
    totals["absolute_difference"] = totals["difference"].abs()
    totals["is_mismatch"] = totals["absolute_difference"].gt(float(tolerance_pj))
    totals["status"] = totals["is_mismatch"].map({True: "value_mismatch", False: "match"})
    totals["reason"] = totals.apply(_comparison_reason, axis=1)
    totals["tolerance_pj"] = float(tolerance_pj)
    totals["schema_version"] = SUPPLY_CONSERVATION_SCHEMA_VERSION
    totals["row_id"] = _row_ids(totals, keys)

    reference_detail = reference[reference["included"]].copy()
    reference_detail["stage"] = "reference"
    reference_detail["difference"] = -reference_detail["value"]
    produced_detail = produced.copy()
    produced_detail["stage"] = "produced"
    produced_detail["difference"] = produced_detail["value"]
    breakdown = pd.concat([reference_detail, produced_detail], ignore_index=True, sort=False)
    group_difference = breakdown.groupby(keys)["difference"].transform("sum")
    headline = totals.set_index(keys)["difference"]
    breakdown["headline_difference"] = [headline.loc[tuple(row)] for row in breakdown[keys].itertuples(index=False, name=None)]
    breakdown["breakdown_group_difference"] = group_difference
    breakdown["breakdown_remainder"] = breakdown["headline_difference"] - group_difference
    breakdown["schema_version"] = SUPPLY_CONSERVATION_SCHEMA_VERSION
    breakdown["row_id"] = _row_ids(breakdown, [*keys, "stage", "source_row_id"])

    excluded = reference[~reference["included"]].copy()
    excluded["stage"] = "source_scope"
    lineage = pd.concat([reference_detail, excluded, produced_detail], ignore_index=True, sort=False)
    lineage["schema_version"] = SUPPLY_CONSERVATION_SCHEMA_VERSION
    lineage["row_id"] = _row_ids(lineage, [*keys, "stage", "source_row_id"])
    return (
        totals.sort_values(keys).reset_index(drop=True),
        breakdown.sort_values([*keys, "stage", "source_row_id"]).reset_index(drop=True),
        lineage.sort_values([*keys, "stage", "source_row_id"]).reset_index(drop=True),
    )


def _build_supply_reference_rows(esto, ninth, economies, base_year, final_year, included_esto_products):
    rows = []
    for economy in economies:
        compact = str(economy).replace("_", "").casefold()
        for flow in SUPPLY_FLOWS:
            esto_flow = supply_data_pipeline.FLOW_CODES_BY_DATASET["esto"][flow]
            subset = esto[
                esto["economy"]
                .astype(str)
                .str.replace("_", "", regex=False)
                .str.casefold()
                .eq(compact)
                & esto["flows"].astype(str).eq(esto_flow)
            ]
            rows.extend(_source_rows(subset, economy, flow, base_year, "ESTO", "flows", "products", included_esto_products))
            ninth_flow = supply_data_pipeline.FLOW_CODES_BY_DATASET["ninth"][flow]
            subset = ninth[ninth["economy"].astype(str).eq(str(economy)) & ninth["sectors"].astype(str).eq(ninth_flow)]
            for year in range(base_year + 1, final_year + 1):
                rows.extend(_source_rows(subset, economy, flow, year, "9TH", "sectors", "fuels", None))
    columns = ["economy", "flow", "year", "source_system", "source_flow", "source_product", "esto_product", "value", "included", "inclusion_reason", "exclusion_reason", "value_classification", "mapping_status", "source_row_id"]
    return pd.DataFrame(rows, columns=columns)


def _source_rows(frame, economy, flow, year, source_system, flow_col, product_col, included_products):
    if year not in frame.columns and str(year) not in frame.columns:
        return []
    year_col = year if year in frame.columns else str(year)
    product_col = product_col if product_col in frame.columns else ("subfuels" if "subfuels" in frame.columns else product_col)
    products = frame[product_col].fillna("").astype(str) if product_col in frame.columns else pd.Series("", index=frame.index)
    parent_codes = _parent_codes(products)
    detailed_subfuel = pd.Series(False, index=frame.index)
    parent_fuels_with_detail: set[str] = set()
    if source_system == "9TH" and "subfuels" in frame.columns and "fuels" in frame.columns:
        subfuel_text = frame["subfuels"].fillna("").astype(str).str.strip()
        detailed_subfuel = ~subfuel_text.str.casefold().isin({"", "x", "nan", "none"})
        parent_fuels_with_detail = set(
            frame.loc[detailed_subfuel, "fuels"].fillna("").astype(str)
        )
    output = []
    for index, row in frame.iterrows():
        product = str(row.get(product_col, ""))
        is_detailed_subfuel = bool(detailed_subfuel.loc[index])
        if source_system == "9TH" and is_detailed_subfuel:
            product = str(row.get("subfuels", ""))
        code = _code(product)
        subtotal = any(_truthy(row.get(column)) for column in ("is_subtotal", "subtotal_layout", "subtotal_results"))
        structural_parent = bool(code and code in parent_codes)
        if source_system == "9TH" and not is_detailed_subfuel:
            structural_parent = structural_parent or str(row.get("fuels", "")) in parent_fuels_with_detail
        in_export_scope = included_products is None or product in included_products
        included = not subtotal and not structural_parent and in_export_scope
        reason = "included_leaf_in_export_scope" if included else (
            "subtotal_flagged" if subtotal else "structural_parent_aggregate" if structural_parent else "product_not_written_to_export"
        )
        raw_value = pd.to_numeric(pd.Series([row.get(year_col)]), errors="coerce").fillna(0.0).iloc[0]
        value = _normalize_supply_value(float(raw_value), flow)
        source_id = _hash([source_system, economy, flow, year, index, product, value])
        output.append({"economy": economy, "flow": flow, "year": int(year), "source_system": source_system,
            "source_flow": str(row.get(flow_col, "")), "source_product": product,
            "esto_product": product if source_system == "ESTO" else pd.NA, "value": value,
            "included": included, "inclusion_reason": reason if included else "",
            "exclusion_reason": "" if included else reason,
            "value_classification": "exact" if included else "excluded",
            "mapping_status": "exact_direct" if included and source_system == "ESTO" else "untraceable" if included else "excluded",
            "source_row_id": source_id})
    return output


def _build_produced_supply_rows(supply_projection_table, supply_primary_table, economies, included_esto_products):
    parts = []
    specs = [("production", supply_primary_table, "production"), ("imports", supply_projection_table, "projected_imports"), ("exports", supply_projection_table, "projected_exports")]
    for flow, table, value_column in specs:
        if table.empty or value_column not in table.columns:
            continue
        part = table[table["economy"].astype(str).isin([str(e) for e in economies])].copy()
        if included_esto_products is not None:
            part = part[part["esto_product"].astype(str).isin(included_esto_products)]
        for index, row in part.iterrows():
            value = float(pd.to_numeric(pd.Series([row[value_column]]), errors="coerce").fillna(0.0).iloc[0])
            parts.append({"economy": str(row["economy"]), "flow": flow, "year": int(row["year"]),
                "source_system": "PRODUCED_SUPPLY", "source_flow": flow, "source_product": pd.NA,
                "esto_product": str(row["esto_product"]), "value": value, "included": True,
                "inclusion_reason": "product_written_to_export", "exclusion_reason": "",
                "value_classification": "untraceable", "mapping_status": "mapped_but_source_link_not_retained",
                "source_row_id": _hash(["PRODUCED_SUPPLY", flow, index, row["economy"], row["year"], row["esto_product"], value])})
    return pd.DataFrame(parts, columns=["economy", "flow", "year", "source_system", "source_flow", "source_product", "esto_product", "value", "included", "inclusion_reason", "exclusion_reason", "value_classification", "mapping_status", "source_row_id"])


def find_exported_supply_products(export_paths: list[Path | str], sector_config: dict) -> set[str]:
    """Resolve mapped ESTO products whose LEAP fuel branches were actually written."""
    exported_fuel_names = set()
    for raw_path in export_paths:
        path = Path(raw_path)
        if path.exists():
            rows = pd.read_excel(path, header=2, usecols=["Branch Path"])
            exported_fuel_names.update(_normalise_label(str(value).split("\\")[-1]) for value in rows["Branch Path"].dropna())
    return {str(product) for product, entry in sector_config.items() if _normalise_label(entry.get("fuel_name", "")) in exported_fuel_names}


def build_results_update_closure_diagnostics(reconciliation_table: pd.DataFrame, tolerance_pj: float = 1e-6) -> pd.DataFrame:
    """Independently recompute the resolved supply-demand balance residual."""
    if tolerance_pj < 0:
        raise ValueError("tolerance_pj must be non-negative")
    key_columns = ["economy", "scenario", "esto_product", "year"]
    term_columns = ["adjusted_imports", "adjusted_exports", "constrained_transformation_output", "constrained_production", "stock_changes", "transformation_input", "transformation_losses", "demand_value"]
    missing = [column for column in [*key_columns, *term_columns] if column not in reconciliation_table]
    if missing:
        raise KeyError(f"reconciliation_table is missing closure columns: {missing}")
    out = reconciliation_table[[*key_columns, *term_columns]].copy()
    for column in term_columns:
        out[column] = pd.to_numeric(out[column], errors="coerce").fillna(0.0)
    out["resolved_supply"] = out["adjusted_imports"] - out["adjusted_exports"] + out["constrained_transformation_output"] + out["constrained_production"] + out["stock_changes"]
    out["resolved_requirement"] = out["transformation_input"] + out["transformation_losses"] + out["demand_value"]
    out["closure_residual"] = out["resolved_supply"] - out["resolved_requirement"]
    out["absolute_residual"] = out["closure_residual"].abs()
    out["is_mismatch"] = out["absolute_residual"].gt(float(tolerance_pj))
    out["status"] = out["is_mismatch"].map({True: "closure_mismatch", False: "closed"})
    out["tolerance_pj"] = float(tolerance_pj)
    return out.sort_values(key_columns).reset_index(drop=True)


def write_supply_diagnostic(rows: pd.DataFrame, output_path: Path | str) -> Path:
    path = Path(output_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    rows.to_csv(path, index=False)
    return path


def _normalize_supply_value(value, flow):
    if flow == "exports":
        if value > 0:
            raise ValueError(f"Raw export reference must be non-positive, got {value}")
        return -value
    if value < 0:
        raise ValueError(f"Raw {flow} reference must be non-negative, got {value}")
    return value


def _comparison_reason(row):
    if row["reference_total"] == 0 and row["resolved_total"] != 0:
        return "unexpected_produced"
    if row["reference_total"] != 0 and row["resolved_total"] == 0:
        return "missing_produced"
    return "within_tolerance" if not row["is_mismatch"] else "value_difference"


def _code(value):
    match = _CODE_PATTERN.match(str(value))
    return match.group(1).replace("_", ".") if match else ""


def _parent_codes(values):
    codes = {_code(value) for value in values}
    return {code for code in codes if code and any(other.startswith(code + ".") for other in codes if other != code)}


def _truthy(value):
    return value is True or str(value).strip().lower() in {"true", "1", "yes"}


def _hash(values):
    return sha256("|".join("" if pd.isna(value) else str(value) for value in values).encode("utf-8")).hexdigest()[:20]


def _row_ids(frame, columns):
    return [_hash(row) for row in frame[columns].itertuples(index=False, name=None)]


def _normalise_label(value):
    return " ".join(str(value or "").strip().lower().split())


#%%
