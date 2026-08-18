"""Summarise ESTO values behind missing baseline-seed branch findings.

The report keeps ESTO's signed PJ values, separates the 2022 base year from
years after 2022, and compares the 2024, 2025, and 2026 ESTO vintages.
"""

from pathlib import Path

import pandas as pd
from openpyxl import load_workbook


REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_YEAR = 2022
VINTAGES = {
    "2024": REPO_ROOT / "data" / "00APEC_2024_low_with_subtotals.csv",
    "2025": REPO_ROOT / "data" / "00APEC_2025_low_with_subtotals.csv",
    "2026": REPO_ROOT / "data" / "00APEC_2026_low_with_subtotals_PRELIMINARY.csv",
}
BATCH_FINDINGS = [
    REPO_ROOT
    / "outputs/leap_exports/supply_reconciliation/baseline_seed/runs/"
    / "SEED_5521F03_BATCH1_AUS_USA_PRC_20260818_100306/supporting_files/"
    / "baseline_seed_validation/baseline_seed_20260818_consolidated_rule_findings.csv",
    REPO_ROOT.parent
    / "worktrees/leap_initialisation_seed_5521f03/outputs/leap_exports/"
    / "supply_reconciliation/baseline_seed/runs/"
    / "SEED_5521F03_BATCH2_BD_MAS_MEX_NZ_20260818_115901/supporting_files/"
    / "baseline_seed_validation/baseline_seed_20260818_consolidated_rule_findings.csv",
    REPO_ROOT.parent
    / "worktrees/leap_initialisation_seed_5521f03/outputs/leap_exports/"
    / "supply_reconciliation/baseline_seed/runs/"
    / "SEED_5521F03_BATCH3_PNG_PHL_RUS_THA_VN_20260818_145954/supporting_files/"
    / "baseline_seed_validation/baseline_seed_20260818_consolidated_rule_findings.csv",
]
SEED_RUNS = [
    REPO_ROOT
    / "outputs/leap_exports/supply_reconciliation/baseline_seed/runs/"
    / "SEED_5521F03_BATCH1_AUS_USA_PRC_20260818_100306",
    REPO_ROOT.parent
    / "worktrees/leap_initialisation_seed_5521f03/outputs/leap_exports/"
    / "supply_reconciliation/baseline_seed/runs/"
    / "SEED_5521F03_BATCH2_BD_MAS_MEX_NZ_20260818_115901",
    REPO_ROOT.parent
    / "worktrees/leap_initialisation_seed_5521f03/outputs/leap_exports/"
    / "supply_reconciliation/baseline_seed/runs/"
    / "SEED_5521F03_BATCH3_PNG_PHL_RUS_THA_VN_20260818_145954",
]
FLOW_BY_SECTOR = {
    "Coal mines": "10.01.06 Coal mines",
    "Electricity CHP and heat plants": "10.01.01 Electricity, CHP and heat plants",
    "Oil and gas extraction": "10.01.12 Oil and gas extraction",
    "Non specified own uses": "10.01.17 Non-specified own uses",
    "Transmission and distribution loss": "10.02 Transmission and distribution losses",
    "Non specified transformation": "09.12 Non-specified transformation",
    "LNG regasification": "09.06.02 Liquefaction/regasification plants",
    "NG liquefaction": "09.06.02 Liquefaction/regasification plants",
    "NG Liquefaction": "09.06.02 Liquefaction/regasification plants",
    "Heat plant interim": "09.01.03 Heat plants",
    "Coke ovens": "09.08.01 Coke ovens",
}
PRODUCT_BY_FUEL = {
    "Anthracite": "01.04 Anthracite",
    "BKB and PB": "02.08 BKB/PB",
    "Lignite": "01.05 Lignite",
    "Bitumen": "07.14 Bitumen",
    "Blast furnace gas": "02.04 Blast furnace gas",
    "Lubricants": "07.13 Lubricants",
    "Other recovered gases": "02.05 Other recovered gases",
    "Petroleum coke": "07.16 Petroleum coke",
    "Refinery gas not liquefied": "07.10 Refinery gas (not liquefied)",
    "Patent fuel": "02.06 Patent fuel",
    "Kerosene type jet fuel": "07.05 Kerosene type jet fuel",
    "Coal tar": "02.07 Coal tar",
    "Coking coal": "01.01 Coking coal",
    "Gas works gas": "08.03 Gas works gas",
    "Paraffin waxes": "07.15 Paraffin waxes",
    "Natural gas liquids": "06.02 Natural gas liquids",
    "Crude oil": "06.01 Crude oil",
    "Coke oven coke": "02.01 Coke oven coke",
    "White spirit sbp": "07.12 White spirit SBP",
    "Other bituminous coal": "01.02 Other bituminous coal",
    "Peat": "03 Peat",
    "Additives and oxygenates": "06.04 Additives/ oxygenates",
    "Refinery feedstocks": "06.03 Refinery feedstocks",
    "Gas": "08 Gas",
}


def _normalise_economy(value: object) -> str:
    text = str(value).strip()
    return f"{text[:2]}_{text[2:]}" if len(text) > 2 and text[2] != "_" else text


def load_missing_branch_rows() -> pd.DataFrame:
    frames = [pd.read_csv(path) for path in BATCH_FINDINGS if path.exists()]
    if len(frames) != len(BATCH_FINDINGS):
        missing = [str(path) for path in BATCH_FINDINGS if not path.exists()]
        raise FileNotFoundError(f"Missing findings files: {missing}")
    findings = pd.concat(frames, ignore_index=True)
    findings = findings[(findings["rule_id"] == "SEED-011") & (findings["status"] == "fail")]
    rows = []
    for _, row in findings[["economy", "Branch Path"]].drop_duplicates().iterrows():
        parts = str(row["Branch Path"]).split("\\")
        if parts[0] == "Demand":
            sector, fuel = parts[2], parts[-1]
        else:
            sector, fuel = parts[1], parts[-1]
        rows.append(
            {
                "economy": str(row["economy"]),
                "sector": sector,
                "fuel": fuel,
                "branch_path": row["Branch Path"],
                "source_flow": FLOW_BY_SECTOR.get(sector, ""),
                "esto_product": PRODUCT_BY_FUEL.get(fuel, ""),
            }
        )
    output = pd.DataFrame(rows).sort_values(["economy", "sector", "fuel"])
    unknown = output[(output["source_flow"] == "") | (output["esto_product"] == "")]
    if not unknown.empty:
        raise ValueError(f"Unmapped missing-branch rows: {unknown.to_dict('records')}")
    return output.reset_index(drop=True)


def load_esto_values(path: Path, keys: pd.DataFrame, vintage: str) -> pd.DataFrame:
    years = pd.read_csv(path, nrows=0).columns.tolist()
    year_columns = [column for column in years if column.isdigit()]
    data = pd.read_csv(
        path,
        usecols=["economy", "flows", "products", "is_subtotal", *year_columns],
    )
    data["economy"] = data["economy"].map(_normalise_economy)
    data = data[data["is_subtotal"].fillna(False).eq(False)]
    joined = keys.merge(
        data,
        left_on=["economy", "source_flow", "esto_product"],
        right_on=["economy", "flows", "products"],
        how="left",
    )
    base_column = f"esto_{vintage}_base_2022"
    projected_column = f"esto_{vintage}_projected_sum"
    available_projected = [year for year in year_columns if int(year) > BASE_YEAR]
    joined[base_column] = pd.to_numeric(joined.get("2022"), errors="coerce").fillna(0.0)
    if available_projected:
        joined[projected_column] = joined[available_projected].apply(
            pd.to_numeric, errors="coerce"
        ).fillna(0.0).sum(axis=1)
    else:
        joined[projected_column] = 0.0
    return joined[["economy", "branch_path", base_column, projected_column]]


def load_seed_presence(keys: pd.DataFrame) -> pd.DataFrame:
    def nonzero(value: object) -> bool:
        try:
            return abs(float(value)) > 1e-12
        except (TypeError, ValueError):
            return False

    rows = []
    for run in SEED_RUNS:
        for workbook_path in sorted(run.glob("leap_import_baseline_seed_*.xlsx")):
            economy = workbook_path.stem.split("_2026")[0].replace("leap_import_baseline_seed_", "")
            workbook = load_workbook(workbook_path, read_only=True, data_only=True)
            sheet = workbook["FOR_VIEWING"]
            header = [cell.value for cell in next(sheet.iter_rows(min_row=3, max_row=3))]
            index = {str(value): position for position, value in enumerate(header) if value is not None}
            branch_index = index.get("Branch Path")
            year_indices = {
                year: index.get(str(year))
                for year in range(BASE_YEAR, 2061)
                if index.get(str(year)) is not None
            }
            matching = {}
            for values in sheet.iter_rows(min_row=4, values_only=True):
                branch_path = values[branch_index] if branch_index is not None else None
                if branch_path is None:
                    continue
                matching.setdefault(str(branch_path), []).append(values)
            for branch_path in keys.loc[keys["economy"] == economy, "branch_path"].unique():
                values = matching.get(branch_path, [])
                base_nonzero = any(nonzero(row[year_indices[BASE_YEAR]]) for row in values)
                projected_nonzero = any(
                    nonzero(row[year_index])
                    for row in values
                    for year, year_index in year_indices.items()
                    if year > BASE_YEAR
                )
                rows.append(
                    {
                        "economy": economy,
                        "branch_path": branch_path,
                        "seed_matching_rows": len(values),
                        "seed_base_nonzero_any": base_nonzero,
                        "seed_projected_nonzero_any": projected_nonzero,
                    }
                )
            workbook.close()
    return pd.DataFrame(rows)


def build_report(output_path: Path) -> pd.DataFrame:
    keys = load_missing_branch_rows()
    report = keys.copy()
    for vintage, path in VINTAGES.items():
        values = load_esto_values(path, keys, vintage)
        report = report.merge(values, on=["economy", "branch_path"], how="left")
    report = report.merge(load_seed_presence(keys), on=["economy", "branch_path"], how="left")
    value_columns = [
        column
        for column in report
        if column.startswith("esto_")
        and ("base_" in column or "projected_" in column)
    ]
    report["nonzero_in_any_vintage"] = report[value_columns].abs().gt(1e-12).any(axis=1)
    report["base_year"] = BASE_YEAR
    report["interpretation"] = report["nonzero_in_any_vintage"].map(
        {True: "ESTO has nonzero source value; investigate omission", False: "ESTO source is zero across reported vintage windows"}
    )
    report["seed_impact"] = report.apply(
        lambda row: (
            "Rows retained in seed with nonzero values but unresolved IDs"
            if row["seed_matching_rows"] and (row["seed_base_nonzero_any"] or row["seed_projected_nonzero_any"])
            else "Rows retained but all seed values are zero"
            if row["seed_matching_rows"]
            else "No matching seed rows; data omitted from seed"
        ),
        axis=1,
    )
    report.to_csv(output_path, index=False, float_format="%.12g")
    return report


if __name__ == "__main__":
    output = REPO_ROOT / "outputs" / "leap_exports" / "supply_reconciliation" / "baseline_seed_missing_branch_esto_vintage_impact_20260818.csv"
    result = build_report(output)
    print(f"Wrote {len(result)} rows to {output}")
    print(result["nonzero_in_any_vintage"].value_counts(dropna=False).to_string())
