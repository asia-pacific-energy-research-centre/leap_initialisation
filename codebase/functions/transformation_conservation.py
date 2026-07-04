"""Internal conservation diagnostics for transformation output energy (v1)."""

#%%

from hashlib import sha256
import re

import pandas as pd


SCHEMA_VERSION = "1.0"
COMPARISON_GROUP = "__all_transformation_outputs__"
OUTPUT_FUEL_GROUP = "__all_fuels__"
_CODE_PATTERN = re.compile(r"^\s*(\d+(?:[._]\d+)*)")


def build_raw_transformation_output_reference(
    esto: pd.DataFrame,
    ninth: pd.DataFrame,
    economies: list[str],
    scenarios: list[str],
    base_year: int,
    final_year: int,
) -> pd.DataFrame:
    """Extract independent positive transformation outputs from raw balances."""
    rows = []
    for economy in economies:
        base = esto[esto["economy"].astype(str).eq(str(economy).replace("_", ""))]
        base = base[base["flows"].astype(str).str.match(r"^09(?:\.|\s)")]
        rows.extend(_raw_rows(base, economy, scenarios, base_year, "ESTO", "flows", "products"))
        projection = ninth[ninth["economy"].astype(str).eq(str(economy))]
        projection = projection[projection["sectors"].astype(str).str.match(r"^09(?:_|\s)")]
        for scenario in scenarios:
            scenario_rows = projection
            if "scenarios" in scenario_rows.columns:
                scenario_rows = scenario_rows[scenario_rows["scenarios"].astype(str).str.casefold().eq(str(scenario).casefold())]
            for year in range(base_year + 1, final_year + 1):
                rows.extend(_raw_rows(scenario_rows, economy, [scenario], year, "9TH", "sectors", "fuels"))
    return pd.DataFrame(rows, columns=_lineage_columns())


def build_transformation_output_conservation(
    reference_rows: pd.DataFrame,
    process_records: list[dict],
    scenarios: list[str],
    tolerance_pj: float = 1e-6,
    compressed_projection_years: set[int] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Compare raw positive outputs with final pre-export process-record outputs."""
    if tolerance_pj < 0:
        raise ValueError("tolerance_pj must be non-negative")
    produced = _produced_rows(process_records, scenarios)
    included_reference = reference_rows[reference_rows["included"]].copy()
    if included_reference.empty and produced.empty:
        raise ValueError("Transformation output conservation comparison is empty")
    keys = ["economy", "scenario", "transformation_module", "output_fuel", "year"]
    reference_totals = included_reference.groupby(keys, as_index=False)["value"].sum().rename(columns={"value": "reference_total"})
    produced_totals = produced.groupby(keys, as_index=False)["value"].sum().rename(columns={"value": "produced_total"})
    totals = reference_totals.merge(produced_totals, on=keys, how="outer")
    totals[["reference_total", "produced_total"]] = totals[["reference_total", "produced_total"]].fillna(0.0)
    totals["difference"] = totals["produced_total"] - totals["reference_total"]
    totals["absolute_difference"] = totals["difference"].abs()
    totals["is_mismatch"] = totals["absolute_difference"].gt(tolerance_pj)
    totals["status"] = totals["is_mismatch"].map({True: "value_mismatch", False: "match"})
    totals["reason"] = totals.apply(_reason, axis=1)
    totals["tolerance_pj"] = tolerance_pj
    totals["year_type"] = totals["year"].map(lambda year: "compressed_projection" if year in (compressed_projection_years or set()) else "actual")
    totals["schema_version"] = SCHEMA_VERSION
    totals["row_id"] = _ids(totals, keys)

    reference_detail = included_reference.copy()
    reference_detail["stage"] = "reference"
    reference_detail["difference"] = -reference_detail["value"]
    produced["stage"] = "produced"
    produced["difference"] = produced["value"]
    breakdown = pd.concat([reference_detail, produced], ignore_index=True, sort=False)
    group_sum = breakdown.groupby(keys)["difference"].transform("sum")
    headline = totals.set_index(keys)["difference"]
    breakdown["headline_difference"] = [headline.loc[tuple(row)] for row in breakdown[keys].itertuples(index=False, name=None)]
    breakdown["breakdown_group_difference"] = group_sum
    breakdown["breakdown_remainder"] = breakdown["headline_difference"] - group_sum
    breakdown["schema_version"] = SCHEMA_VERSION
    breakdown["row_id"] = _ids(breakdown, [*keys, "stage", "source_row_id"])

    excluded = reference_rows[~reference_rows["included"]].copy()
    excluded["stage"] = "source_scope"
    lineage = pd.concat([reference_detail, excluded, produced], ignore_index=True, sort=False)
    lineage["schema_version"] = SCHEMA_VERSION
    lineage["row_id"] = _ids(lineage, [*keys, "stage", "source_row_id"])
    return totals.sort_values(keys).reset_index(drop=True), breakdown.reset_index(drop=True), lineage.reset_index(drop=True)


def _raw_rows(frame, economy, scenarios, year, source_system, module_column, fuel_column):
    year_column = year if year in frame.columns else str(year)
    if year_column not in frame.columns:
        return []
    module_parents = _parents(frame[module_column])
    fuel_parents = _parents(frame[fuel_column]) if fuel_column in frame.columns else set()
    rows = []
    for index, row in frame.iterrows():
        module = str(row.get(module_column, ""))
        fuel = str(row.get(fuel_column, ""))
        subtotal = any(_truthy(row.get(column)) for column in ("is_subtotal", "subtotal_layout", "subtotal_results"))
        aggregate = _code(module) in module_parents or _code(fuel) in fuel_parents
        raw_value = float(pd.to_numeric(pd.Series([row.get(year_column)]), errors="coerce").fillna(0.0).iloc[0])
        positive_output = raw_value > 0
        included = positive_output and not subtotal and not aggregate
        exclusion = "" if included else "non_positive_input_or_zero" if not positive_output else "subtotal_or_structural_aggregate"
        for scenario in scenarios:
            rows.append(_lineage_row(economy, scenario, year, source_system, module, fuel, raw_value if included else max(raw_value, 0.0), included, exclusion, index))
    return rows


def _produced_rows(process_records, scenarios):
    rows = []
    label_counts = {}
    for record in process_records:
        key = (record.get("economy"), record.get("sector_title"), tuple(sorted((record.get("output_values") or {}).keys())))
        label_counts[key] = label_counts.get(key, 0) + 1
    for record_index, record in enumerate(process_records):
        economy = str(record.get("economy", ""))
        module = str(record.get("sector_title") or record.get("process_name") or "")
        output_values = record.get("output_values") or {}
        fan_out = label_counts.get((record.get("economy"), record.get("sector_title"), tuple(sorted(output_values.keys()))), 0) > 1
        for fuel, series in output_values.items():
            if not isinstance(series, dict):
                continue
            for year, raw_value in series.items():
                value = float(pd.to_numeric(pd.Series([raw_value]), errors="coerce").fillna(0.0).iloc[0])
                if value <= 0:
                    continue
                for scenario in scenarios:
                    rows.append({"economy": economy, "scenario": scenario, "transformation_module": COMPARISON_GROUP,
                        "output_fuel": OUTPUT_FUEL_GROUP, "year": int(year), "source_system": "PRODUCED_TRANSFORMATION",
                        "source_module": module, "source_fuel": str(fuel), "value": value, "included": True,
                        "inclusion_reason": "positive_pre_export_process_output", "exclusion_reason": "",
                        "value_classification": "untraceable" if fan_out else "exact",
                        "mapping_status": "fan_out_source_link_not_retained" if fan_out else "exact_direct",
                        "source_row_id": _hash(["produced", record_index, economy, module, fuel, year, value])})
    return pd.DataFrame(rows, columns=_lineage_columns())


def _lineage_row(economy, scenario, year, system, module, fuel, value, included, exclusion, index):
    return {"economy": economy, "scenario": scenario, "transformation_module": COMPARISON_GROUP,
        "output_fuel": OUTPUT_FUEL_GROUP, "year": int(year), "source_system": system,
        "source_module": module, "source_fuel": fuel, "value": value, "included": included,
        "inclusion_reason": "positive_leaf_transformation_output" if included else "", "exclusion_reason": exclusion,
        "value_classification": "exact" if included else "excluded", "mapping_status": "exact_aggregated" if included else "excluded",
        "source_row_id": _hash([system, index, economy, scenario, module, fuel, year, value])}


def _lineage_columns():
    return ["economy", "scenario", "transformation_module", "output_fuel", "year", "source_system", "source_module", "source_fuel", "value", "included", "inclusion_reason", "exclusion_reason", "value_classification", "mapping_status", "source_row_id"]


def _reason(row):
    if row.reference_total == 0 and row.produced_total != 0:
        return "unexpected_produced"
    if row.reference_total != 0 and row.produced_total == 0:
        return "missing_produced"
    return "within_tolerance" if not row.is_mismatch else "value_difference"


def _code(value):
    match = _CODE_PATTERN.match(str(value))
    return match.group(1).replace("_", ".") if match else ""


def _parents(values):
    codes = {_code(value) for value in values}
    return {code for code in codes if code and any(other.startswith(code + ".") for other in codes if other != code)}


def _truthy(value):
    return value is True or str(value).strip().lower() in {"true", "1", "yes"}


def _hash(values):
    return sha256("|".join("" if pd.isna(value) else str(value) for value in values).encode()).hexdigest()[:20]


def _ids(frame, columns):
    return [_hash(row) for row in frame[columns].itertuples(index=False, name=None)]


#%%
