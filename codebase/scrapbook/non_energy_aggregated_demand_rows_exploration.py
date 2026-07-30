#%%
"""Build auditable evidence for proposed All demand aggregated/Non energy fuels."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd


# --- Stable paths and rules ---

REPO_ROOT = Path(__file__).resolve().parents[2]
MAPPINGS_ROOT = REPO_ROOT.parent / "leap_mappings"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ESTO_2025_PATH = MAPPINGS_ROOT / "data" / "00APEC_2025_low_with_subtotals.csv"
ESTO_2024_PATH = MAPPINGS_ROOT / "data" / "00APEC_2024_low_with_subtotals.csv"
NINTH_PATH = MAPPINGS_ROOT / "data" / "merged_file_energy_ALL_20251106.csv"
MAPPING_PATH = MAPPINGS_ROOT / "config" / "outlook_mappings_single_axis.xlsx"
OUTPUT_DIR = REPO_ROOT / "outputs" / "non_energy_aggregated_demand_rows_20260730"
OUTPUT_JSON_PATH = OUTPUT_DIR / "non_energy_rows_evidence.json"

ESTO_2025_FINAL_YEAR = 2023
ESTO_2024_FINAL_YEAR = 2022
NINTH_FIRST_YEAR = 2023
NINTH_LAST_YEAR = 2070
NONZERO_TOLERANCE = 1e-12
LEAP_SECTOR_NAME = "Non energy"
LEAP_SECTOR_BRANCH_PATH = rf"Demand\All demand aggregated\{LEAP_SECTOR_NAME}"


# --- Evidence extraction ---

def _load_esto_evidence(
    path: Path,
    final_year: int,
    prefix: str,
) -> pd.DataFrame:
    """Return final-year non-energy evidence by ESTO product."""
    frame = pd.read_csv(path, low_memory=False)
    subtotal = (
        frame["is_subtotal"]
        .astype(str)
        .str.strip()
        .str.lower()
        .isin({"true", "1", "yes"})
    )
    frame = frame[
        ~subtotal
        & frame["flows"].astype(str).str.startswith("17")
    ].copy()
    frame["value"] = pd.to_numeric(
        frame[str(final_year)],
        errors="coerce",
    ).fillna(0.0)
    frame["abs_value"] = frame["value"].abs()

    records: list[dict[str, object]] = []
    for product, group in frame.groupby("products", dropna=False):
        nonzero = group[group["abs_value"].gt(NONZERO_TOLERANCE)]
        australia = group[group["economy"].astype(str).str.upper().eq("01AUS")]
        records.append(
            {
                "esto_product": str(product),
                f"{prefix}_nonzero_rows": int(len(nonzero)),
                f"{prefix}_nonzero_economies": int(nonzero["economy"].nunique()),
                f"{prefix}_abs_sum": float(group["abs_value"].sum()),
                f"{prefix}_net_sum": float(group["value"].sum()),
                f"{prefix}_aus_nonzero_rows": int(
                    australia["abs_value"].gt(NONZERO_TOLERANCE).sum()
                ),
                f"{prefix}_aus_abs_sum": float(australia["abs_value"].sum()),
                f"{prefix}_aus_net_sum": float(australia["value"].sum()),
            }
        )
    return pd.DataFrame(records)


def _load_ninth_evidence() -> pd.DataFrame:
    """Return post-2023 non-energy evidence by deepest Ninth fuel code."""
    frame = pd.read_csv(NINTH_PATH, low_memory=False)
    frame = frame[
        frame["sectors"].astype(str).eq("17_nonenergy_use")
        & ~frame["subtotal_layout"].astype(bool)
        & ~frame["subtotal_results"].astype(bool)
    ].copy()
    frame["ninth_fuel"] = np.where(
        frame["subfuels"].astype(str).ne("x"),
        frame["subfuels"],
        frame["fuels"],
    )
    year_columns = [
        str(year)
        for year in range(NINTH_FIRST_YEAR, NINTH_LAST_YEAR + 1)
        if str(year) in frame.columns
    ]
    values = frame[year_columns].apply(
        pd.to_numeric,
        errors="coerce",
    ).fillna(0.0)
    frame["abs_sum"] = values.abs().sum(axis=1)
    frame["max_abs"] = values.abs().max(axis=1)

    records: list[dict[str, object]] = []
    for fuel, group in frame.groupby("ninth_fuel", dropna=False):
        nonzero = group[group["abs_sum"].gt(NONZERO_TOLERANCE)]
        australia = group[group["economy"].astype(str).eq("01_AUS")]
        records.append(
            {
                "ninth_fuel": str(fuel),
                "ninth_nonzero_rows": int(len(nonzero)),
                "ninth_nonzero_economies": int(nonzero["economy"].nunique()),
                "ninth_nonzero_scenarios": int(nonzero["scenarios"].nunique()),
                "ninth_abs_sum": float(group["abs_sum"].sum()),
                "ninth_max_abs": float(group["max_abs"].max()),
                "ninth_aus_nonzero_rows": int(
                    australia["abs_sum"].gt(NONZERO_TOLERANCE).sum()
                ),
                "ninth_aus_abs_sum": float(australia["abs_sum"].sum()),
            }
        )
    return pd.DataFrame(records)


def _roll_evidence_to_leap_fuel(
    mapping: pd.DataFrame,
    evidence: pd.DataFrame,
    source_key: str,
    prefix: str,
) -> pd.DataFrame:
    """Roll source-code evidence through the maintained single-axis mapping."""
    merged = mapping.merge(evidence, on=source_key, how="left")
    numeric_columns = [
        column
        for column in merged.columns
        if column.startswith(prefix)
        and pd.api.types.is_numeric_dtype(merged[column])
    ]
    rolled = (
        merged.groupby("leap_fuel", dropna=False)[numeric_columns]
        .sum(min_count=1)
        .reset_index()
    )
    nonzero_column = f"{prefix}_nonzero_rows"
    code_rows = merged[merged[nonzero_column].fillna(0).gt(0)]
    source_codes = (
        code_rows.groupby("leap_fuel")[source_key]
        .agg(lambda values: "; ".join(sorted(set(values.astype(str)))))
        .rename(f"{prefix}_source_codes")
        .reset_index()
    )
    return rolled.merge(source_codes, on="leap_fuel", how="left")


def build_non_energy_fuel_evidence() -> pd.DataFrame:
    """Build the complete mapped LEAP-fuel evidence table."""
    fuel_to_esto = pd.read_excel(
        MAPPING_PATH,
        sheet_name="leap_fuel_to_esto",
        dtype=str,
    ).fillna("")
    fuel_to_ninth = pd.read_excel(
        MAPPING_PATH,
        sheet_name="leap_fuel_to_ninth",
        dtype=str,
    ).fillna("")

    esto_2025 = _load_esto_evidence(
        ESTO_2025_PATH,
        ESTO_2025_FINAL_YEAR,
        "esto_2025",
    )
    esto_2024 = _load_esto_evidence(
        ESTO_2024_PATH,
        ESTO_2024_FINAL_YEAR,
        "esto_2024",
    )
    ninth = _load_ninth_evidence()

    evidence = (
        _roll_evidence_to_leap_fuel(
            fuel_to_esto,
            esto_2025,
            "esto_product",
            "esto_2025",
        )
        .merge(
            _roll_evidence_to_leap_fuel(
                fuel_to_esto,
                esto_2024,
                "esto_product",
                "esto_2024",
            ),
            on="leap_fuel",
            how="outer",
        )
        .merge(
            _roll_evidence_to_leap_fuel(
                fuel_to_ninth,
                ninth,
                "ninth_fuel",
                "ninth",
            ),
            on="leap_fuel",
            how="outer",
        )
    )

    code_columns = [
        "esto_2025_source_codes",
        "esto_2024_source_codes",
        "ninth_source_codes",
    ]
    for column in evidence.columns:
        if column != "leap_fuel" and column not in code_columns:
            evidence[column] = pd.to_numeric(
                evidence[column],
                errors="coerce",
            ).fillna(0)
    for column in code_columns:
        evidence[column] = evidence[column].fillna("")

    evidence["esto_2025_final_nonzero"] = evidence[
        "esto_2025_nonzero_rows"
    ].gt(0)
    evidence["esto_2024_final_nonzero"] = evidence[
        "esto_2024_nonzero_rows"
    ].gt(0)
    evidence["ninth_2023_plus_nonzero"] = evidence[
        "ninth_nonzero_rows"
    ].gt(0)
    evidence["recommended_for_shared_template"] = (
        evidence["esto_2025_final_nonzero"]
        & evidence["esto_2024_final_nonzero"]
        & evidence["ninth_2023_plus_nonzero"]
    )
    evidence["aus_nonzero_all_three"] = (
        evidence["esto_2025_aus_nonzero_rows"].gt(0)
        & evidence["esto_2024_aus_nonzero_rows"].gt(0)
        & evidence["ninth_aus_nonzero_rows"].gt(0)
    )
    evidence["sector"] = LEAP_SECTOR_NAME
    evidence["sector_branch_path"] = LEAP_SECTOR_BRANCH_PATH
    evidence["fuel_branch_path"] = (
        evidence["sector_branch_path"]
        + "\\"
        + evidence["leap_fuel"]
    )
    return evidence.sort_values("leap_fuel", kind="mergesort").reset_index(
        drop=True
    )


def build_output_payload(evidence: pd.DataFrame) -> dict[str, object]:
    """Build the compact workbook payload and retained near-miss evidence."""
    recommended = evidence[
        evidence["recommended_for_shared_template"]
    ].copy()
    near_misses = evidence[
        ~evidence["recommended_for_shared_template"]
        & evidence[
            [
                "esto_2025_final_nonzero",
                "esto_2024_final_nonzero",
                "ninth_2023_plus_nonzero",
            ]
        ].any(axis=1)
    ].copy()

    recommended_columns = [
        "sector",
        "sector_branch_path",
        "leap_fuel",
        "fuel_branch_path",
        "recommended_for_shared_template",
        "aus_nonzero_all_three",
    ]
    evidence_columns = [
        "leap_fuel",
        "recommended_for_shared_template",
        "aus_nonzero_all_three",
        "esto_2025_final_nonzero",
        "esto_2025_source_codes",
        "esto_2025_nonzero_economies",
        "esto_2025_abs_sum",
        "esto_2025_aus_abs_sum",
        "esto_2024_final_nonzero",
        "esto_2024_source_codes",
        "esto_2024_nonzero_economies",
        "esto_2024_abs_sum",
        "esto_2024_aus_abs_sum",
        "ninth_2023_plus_nonzero",
        "ninth_source_codes",
        "ninth_nonzero_economies",
        "ninth_nonzero_scenarios",
        "ninth_abs_sum",
        "ninth_aus_abs_sum",
    ]
    return {
        "summary": {
            "recommended_branch_count": int(len(recommended)),
            "australia_active_count": int(
                recommended["aus_nonzero_all_three"].sum()
            ),
            "near_miss_count": int(len(near_misses)),
            "branch_name": LEAP_SECTOR_NAME,
            "full_sector_branch_path": LEAP_SECTOR_BRANCH_PATH,
            "criterion": (
                "Mapped LEAP fuel is non-zero in 2023 under non-energy in "
                "ESTO 2025, non-zero in 2022 under non-energy in ESTO 2024, "
                "and non-zero in at least one 2023-2070 reference or target "
                "row under Ninth sector 17_nonenergy_use."
            ),
        },
        "sources": [
            {
                "source": "ESTO 2025",
                "path": str(ESTO_2025_PATH),
                "evidence_years": "2023",
                "filter": "Non-subtotal flows beginning 17",
            },
            {
                "source": "ESTO 2024",
                "path": str(ESTO_2024_PATH),
                "evidence_years": "2022",
                "filter": "Non-subtotal flows beginning 17",
            },
            {
                "source": "Ninth",
                "path": str(NINTH_PATH),
                "evidence_years": "2023-2070",
                "filter": (
                    "Sector 17_nonenergy_use; subtotal_layout=FALSE; "
                    "subtotal_results=FALSE; reference or target"
                ),
            },
            {
                "source": "Single-axis mappings",
                "path": str(MAPPING_PATH),
                "evidence_years": "Current",
                "filter": "leap_fuel_to_esto and leap_fuel_to_ninth",
            },
        ],
        "recommended": recommended[recommended_columns].to_dict(
            orient="records"
        ),
        "evidence": recommended[evidence_columns].to_dict(orient="records"),
        "near_misses": near_misses[evidence_columns].to_dict(orient="records"),
    }


def validate_output_payload(payload: dict[str, object]) -> None:
    """Fail early on duplicate, aggregate, or evidence-inconsistent rows."""
    recommended = pd.DataFrame(payload["recommended"])
    evidence = pd.DataFrame(payload["evidence"])
    if recommended.empty:
        raise ValueError("No strict non-energy branch candidates were found.")
    duplicate_paths = recommended["fuel_branch_path"].duplicated(keep=False)
    if duplicate_paths.any():
        duplicates = recommended.loc[
            duplicate_paths,
            "fuel_branch_path",
        ].tolist()
        raise ValueError(f"Duplicate proposed LEAP paths: {duplicates}")
    prohibited_aggregate_fuels = {
        "Biomass",
        "Coal",
        "Gas",
        "Others",
        "Municipal solid waste non and renewable",
    }
    aggregate_rows = recommended[
        recommended["leap_fuel"].isin(prohibited_aggregate_fuels)
    ]
    if not aggregate_rows.empty:
        raise ValueError(
            "Aggregate-only fuel labels must not become LEAP leaves: "
            f"{aggregate_rows['leap_fuel'].tolist()}"
        )
    required_flags = [
        "esto_2025_final_nonzero",
        "esto_2024_final_nonzero",
        "ninth_2023_plus_nonzero",
    ]
    inconsistent = evidence[
        ~evidence[required_flags].astype(bool).all(axis=1)
    ]
    if not inconsistent.empty:
        raise ValueError(
            "Recommended rows failed the strict evidence rule: "
            f"{inconsistent['leap_fuel'].tolist()}"
        )


def write_evidence_json(
    output_path: Path = OUTPUT_JSON_PATH,
) -> Path:
    """Write the workbook payload for the artifact-tool builder."""
    evidence = build_non_energy_fuel_evidence()
    payload = build_output_payload(evidence)
    validate_output_payload(payload)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(payload["summary"], indent=2))
    print("Recommended fuels:")
    for row in payload["recommended"]:
        print(row["leap_fuel"])
    print(f"Wrote {output_path}")
    return output_path


# --- Runnable notebook block ---

CREATE_EVIDENCE_JSON = True

if CREATE_EVIDENCE_JSON:
    EVIDENCE_JSON_PATH = write_evidence_json()

#%%
