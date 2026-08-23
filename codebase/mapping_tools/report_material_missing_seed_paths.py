#%%
"""Report material missing LEAP template paths once per economy/path."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from codebase.functions.baseline_seed_validation import normalize_template_key
from codebase.functions.leap_expressions import parse_expression
from codebase.functions.patch_baseline_seeds import _find_header_row, _template_for_economy
from codebase.functions.baseline_seed_validation import build_template_id_lookup

REPO_ROOT = Path(__file__).resolve().parents[2]
ESTO_VINTAGE_FINAL_YEARS = {"2024": 2022, "2025": 2023, "2026": 2024}


def report_material_missing_seed_paths(seed_paths: list[Path]) -> pd.DataFrame:
    """Return unique material unknown template paths for supplied seed workbooks."""
    records = []
    for seed_path in seed_paths:
        economy = seed_path.name.split("_")[4] + "_" + seed_path.name.split("_")[5]
        raw = pd.read_excel(seed_path, sheet_name="LEAP", header=None)
        _, rows = _find_header_row(raw)
        lookup = build_template_id_lookup(_template_for_economy(economy))
        for _, row in rows.iterrows():
            path = str(row.get("Branch Path", "") or "").strip()
            if not path or normalize_template_key(path) in lookup.canonical_paths:
                continue
            mode, payload = parse_expression(row.get("Expression"))
            values = payload if mode == "series" and isinstance(payload, dict) else {}
            if mode == "const" and payload not in (None, 0):
                values = {2022: float(payload)}
            projection_years = sorted(year for year, value in values.items() if year >= 2023 and value != 0)
            vintage_years = [
                f"ESTO {vintage} ({year})" for vintage, year in ESTO_VINTAGE_FINAL_YEARS.items()
                if values.get(year, 0) != 0
            ]
            if projection_years or vintage_years:
                records.append({
                    "economy": economy, "branch_path": path,
                    "nonzero_projection_years": "|".join(map(str, projection_years)),
                    "nonzero_esto_vintage_final_years": "|".join(vintage_years),
                })
    if not records:
        return pd.DataFrame(columns=["economy", "branch_path", "nonzero_projection_years", "nonzero_esto_vintage_final_years"])
    grouped = pd.DataFrame(records).groupby(["economy", "branch_path"], as_index=False)
    return grouped.agg(
        nonzero_projection_years=(
            "nonzero_projection_years",
            lambda values: "|".join(sorted(set("|".join(values).split("|")) - {""}, key=int)),
        ),
        nonzero_esto_vintage_final_years=(
            "nonzero_esto_vintage_final_years",
            lambda values: "|".join(sorted(set("|".join(values).split("|")) - {""})),
        ),
    )

#%%
