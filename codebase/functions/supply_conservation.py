"""Diagnostic-only supply source preservation and reconciliation closure checks."""

#%%

from pathlib import Path

import pandas as pd

from codebase.functions import supply_data_pipeline


SUPPLY_FLOWS = ("production", "imports", "exports")


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
    """Compare pre-mapping ESTO/9th flow totals with mapped baseline tables."""
    if tolerance_pj < 0:
        raise ValueError("tolerance_pj must be non-negative")
    dataset_map = assets[0]
    esto, _ = supply_data_pipeline.resolve_dataset(dataset_map, "esto")
    ninth, _ = supply_data_pipeline.resolve_dataset(dataset_map, "ninth")

    reference_parts: list[pd.DataFrame] = []
    resolved_parts: list[pd.DataFrame] = []
    for economy in economies:
        compact_economy = str(economy).replace("_", "")
        for flow in SUPPLY_FLOWS:
            esto_flow = supply_data_pipeline.FLOW_CODES_BY_DATASET["esto"][flow]
            ninth_flow = supply_data_pipeline.FLOW_CODES_BY_DATASET["ninth"][flow]
            base_rows = esto[
                esto["economy"].astype(str).eq(compact_economy)
                & esto["flows"].astype(str).eq(esto_flow)
            ]
            reference_parts.append(
                pd.DataFrame(
                    [{
                        "economy": economy,
                        "flow": flow,
                        "year": int(base_year),
                        "reference_total": _normalized_flow_total(base_rows, base_year, flow),
                    }]
                )
            )
            projection_rows = ninth[
                ninth["economy"].astype(str).eq(str(economy))
                & ninth["sectors"].astype(str).eq(ninth_flow)
            ]
            for year in range(base_year + 1, final_year + 1):
                reference_parts.append(
                    pd.DataFrame(
                        [{
                            "economy": economy,
                            "flow": flow,
                            "year": year,
                            "reference_total": _normalized_flow_total(projection_rows, year, flow),
                        }]
                    )
                )

        projection = supply_projection_table[
            supply_projection_table["economy"].astype(str).eq(str(economy))
        ]
        primary = supply_primary_table[
            supply_primary_table["economy"].astype(str).eq(str(economy))
        ]
        if included_esto_products is not None:
            projection = projection[
                projection["esto_product"].astype(str).isin(included_esto_products)
            ]
            primary = primary[
                primary["esto_product"].astype(str).isin(included_esto_products)
            ]
        for flow, table, value_column in [
            ("production", primary, "production"),
            ("imports", projection, "projected_imports"),
            ("exports", projection, "projected_exports"),
        ]:
            grouped = (
                table.assign(
                    resolved_total=pd.to_numeric(table[value_column], errors="coerce").fillna(0.0)
                )
                .groupby(["economy", "year"], as_index=False)["resolved_total"]
                .sum()
            )
            grouped["flow"] = flow
            resolved_parts.append(grouped[["economy", "flow", "year", "resolved_total"]])

    reference = pd.concat(reference_parts, ignore_index=True)
    resolved = pd.concat(resolved_parts, ignore_index=True)
    diagnostics = reference.merge(
        resolved,
        on=["economy", "flow", "year"],
        how="outer",
    )
    diagnostics[["reference_total", "resolved_total"]] = diagnostics[
        ["reference_total", "resolved_total"]
    ].fillna(0.0)
    diagnostics["difference"] = diagnostics["resolved_total"] - diagnostics["reference_total"]
    diagnostics["absolute_difference"] = diagnostics["difference"].abs()
    diagnostics["is_mismatch"] = diagnostics["absolute_difference"].gt(float(tolerance_pj))
    diagnostics["status"] = diagnostics["is_mismatch"].map(
        {True: "value_mismatch", False: "match"}
    )
    diagnostics["tolerance_pj"] = float(tolerance_pj)
    return diagnostics.sort_values(["economy", "flow", "year"]).reset_index(drop=True)


def find_exported_supply_products(
    export_paths: list[Path | str],
    sector_config: dict,
) -> set[str]:
    """Resolve mapped ESTO products whose LEAP fuel branches were actually written."""
    exported_fuel_names: set[str] = set()
    for raw_path in export_paths:
        path = Path(raw_path)
        if not path.exists():
            continue
        rows = pd.read_excel(path, header=2, usecols=["Branch Path"])
        exported_fuel_names.update(
            _normalise_label(str(branch_path).split("\\")[-1])
            for branch_path in rows["Branch Path"].dropna()
        )
    return {
        str(esto_product)
        for esto_product, entry in sector_config.items()
        if _normalise_label(entry.get("fuel_name", "")) in exported_fuel_names
    }


def build_results_update_closure_diagnostics(
    reconciliation_table: pd.DataFrame,
    tolerance_pj: float = 1e-6,
) -> pd.DataFrame:
    """Independently recompute the resolved supply-demand balance residual."""
    if tolerance_pj < 0:
        raise ValueError("tolerance_pj must be non-negative")
    key_columns = ["economy", "scenario", "esto_product", "year"]
    term_columns = [
        "adjusted_imports",
        "adjusted_exports",
        "constrained_transformation_output",
        "constrained_production",
        "stock_changes",
        "transformation_input",
        "transformation_losses",
        "demand_value",
    ]
    missing = [column for column in [*key_columns, *term_columns] if column not in reconciliation_table]
    if missing:
        raise KeyError(f"reconciliation_table is missing closure columns: {missing}")
    out = reconciliation_table[[*key_columns, *term_columns]].copy()
    for column in term_columns:
        out[column] = pd.to_numeric(out[column], errors="coerce").fillna(0.0)
    out["resolved_supply"] = (
        out["adjusted_imports"]
        - out["adjusted_exports"]
        + out["constrained_transformation_output"]
        + out["constrained_production"]
        + out["stock_changes"]
    )
    out["resolved_requirement"] = (
        out["transformation_input"]
        + out["transformation_losses"]
        + out["demand_value"]
    )
    out["closure_residual"] = out["resolved_supply"] - out["resolved_requirement"]
    out["absolute_residual"] = out["closure_residual"].abs()
    out["is_mismatch"] = out["absolute_residual"].gt(float(tolerance_pj))
    out["status"] = out["is_mismatch"].map({True: "closure_mismatch", False: "closed"})
    out["tolerance_pj"] = float(tolerance_pj)
    return out.sort_values(key_columns).reset_index(drop=True)


def write_supply_diagnostic(rows: pd.DataFrame, output_path: Path | str) -> Path:
    """Write a diagnostic CSV and return its resolved path."""
    path = Path(output_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    rows.to_csv(path, index=False)
    return path


def _normalized_flow_total(rows: pd.DataFrame, year: int, flow: str) -> float:
    if year not in rows.columns:
        return 0.0
    total = float(pd.to_numeric(rows[year], errors="coerce").fillna(0.0).sum())
    if flow == "exports":
        return abs(total)
    return max(total, 0.0)


def _normalise_label(value: object) -> str:
    return " ".join(str(value or "").strip().lower().split())


#%%
