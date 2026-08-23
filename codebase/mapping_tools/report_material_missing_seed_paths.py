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


def report_material_exception_path_usage(
    seed_paths: list[Path], exception_branch_paths: set[str],
) -> pd.DataFrame:
    """Return material seed rows that use an existing warning-ledger path.

    Unlike the missing-template report, this deliberately does not consult the
    template.  A placeholder row (BranchID 99/100) is still an exception that
    needs relevance evidence even though its path is present in the export.
    """
    normalized_paths = {normalize_template_key(path): str(path).strip() for path in exception_branch_paths}
    records = []
    for seed_path in seed_paths:
        economy = seed_path.name.split("_")[4] + "_" + seed_path.name.split("_")[5]
        raw = pd.read_excel(seed_path, sheet_name="LEAP", header=None)
        _, rows = _find_header_row(raw)
        for _, row in rows.iterrows():
            path = str(row.get("Branch Path", "") or "").strip()
            canonical_path = normalized_paths.get(normalize_template_key(path))
            if canonical_path is None:
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
                    "economy": economy, "branch_path": canonical_path,
                    "nonzero_projection_years": "|".join(map(str, projection_years)),
                    "nonzero_esto_vintage_final_years": "|".join(vintage_years),
                })
    if not records:
        return pd.DataFrame(columns=["economy", "branch_path", "nonzero_projection_years", "nonzero_esto_vintage_final_years"])
    grouped = pd.DataFrame(records).groupby(["economy", "branch_path"], as_index=False)
    return grouped.agg(
        nonzero_projection_years=("nonzero_projection_years", lambda values: "|".join(sorted(set("|".join(values).split("|")) - {""}, key=int))),
        nonzero_esto_vintage_final_years=("nonzero_esto_vintage_final_years", lambda values: "|".join(sorted(set("|".join(values).split("|")) - {""}))),
    )


def register_and_audit_material_missing_seed_paths(
    findings_by_vintage: dict[str, pd.DataFrame],
    *,
    exception_workbook_path: Path | None = None,
    prune_after_all_vintages: bool = False,
) -> dict[str, object]:
    """Make final-stage material unknown paths reviewable warning-ledger entries."""
    from codebase.functions.baseline_seed_validation_exceptions import (
        audit_exception_relevance,
        register_material_missing_branch_findings,
    )

    combined = pd.concat(findings_by_vintage.values(), ignore_index=True) if findings_by_vintage else pd.DataFrame(columns=["economy", "branch_path"])
    kwargs = {} if exception_workbook_path is None else {"workbook_path": exception_workbook_path}
    additions = register_material_missing_branch_findings(combined, **kwargs)
    audited = audit_exception_relevance(
        findings_by_vintage, prune_after_all_vintages=prune_after_all_vintages, **kwargs,
    )
    return {"added_branch_paths": additions, "audited_rows": len(audited)}

#%%
