#%%
"""Audit aggregated-demand branch coverage against economy and APEC templates.

The workflow keeps the reusable process behind the 2026-08-10 audit:

- build nonzero aggregated-demand sector/fuel paths from ESTO 2022 and the
  Reference/Target projection base year;
- compare economies with templates against their own exact branch paths;
- compare the all-economy union against the APEC union for economies without
  templates; and
- write one narrow ``Economy, Branch Path`` CSV.

Run the bottom Jupyter-style block to refresh the CSV after source data or LEAP
templates change. The APEC branch union is structural only and is never used as
an ID source.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable, Mapping

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from codebase.aggregated_demand_workflow import (
    AGGREGATED_DEMAND_ZERO_ABSOLUTE_TOLERANCE,
    BASE_YEAR,
    DEMAND_BRANCH_ROOT,
    ESTO_BASE_DATA_PATH,
    FUEL_ESTO_SHEET,
    FUEL_MAPPINGS_PATH,
    PROJECTION_DATA_PATH,
    PROJECTION_START_YEAR,
    _extract_base_year,
    _extract_contextual_projection_years,
    _load_demand_csv,
    _load_esto_base_csv,
    load_fuel_mapping,
)
from codebase.utilities.leap_export_template_resolver import (
    DEFAULT_LEAP_EXPORT_TEMPLATES_ROOT,
    available_template_economies,
    build_apec_template_branch_path_union,
    find_leap_export_template,
    read_leap_export_template_branch_paths,
)


DEFAULT_OUTPUT_PATH = (
    REPO_ROOT
    / "outputs"
    / "aggregated_demand_fuel_audit"
    / "all_economies_and_apec_missing_aggregated_demand_branches.csv"
)
DEFAULT_PROJECTION_SCENARIOS = ("reference", "target")


def _resolve(path: Path | str) -> Path:
    """Resolve repo-relative paths without depending on the notebook CWD."""
    normalized = Path(str(path).replace("\\", "/"))
    return normalized if normalized.is_absolute() else REPO_ROOT / normalized


def _add_branch_paths(pairs: pd.DataFrame) -> pd.DataFrame:
    """Return unique economy/sector/fuel pairs with exact LEAP branch paths."""
    required = {"economy", "sector", "leap_fuel_name"}
    missing = sorted(required.difference(pairs.columns))
    if missing:
        raise KeyError(f"Generated aggregated-demand pairs are missing columns: {missing}")
    result = pairs[["economy", "sector", "leap_fuel_name"]].copy()
    for column in ["economy", "sector", "leap_fuel_name"]:
        result[column] = result[column].fillna("").astype(str).str.strip()
    result = result[
        result["economy"].ne("")
        & result["sector"].ne("")
        & result["leap_fuel_name"].ne("")
    ].drop_duplicates()
    result["branch_path"] = (
        DEMAND_BRANCH_ROOT
        + "\\"
        + result["sector"]
        + "\\"
        + result["leap_fuel_name"]
    )
    return result.sort_values(
        ["economy", "branch_path"],
        kind="stable",
    ).reset_index(drop=True)


def build_generated_nonzero_branch_paths_by_economy(
    *,
    base_year: int = BASE_YEAR,
    projection_base_year: int = PROJECTION_START_YEAR,
    projection_scenarios: Iterable[str] = DEFAULT_PROJECTION_SCENARIOS,
    esto_data_path: Path | str = ESTO_BASE_DATA_PATH,
    projection_data_path: Path | str = PROJECTION_DATA_PATH,
    fuel_mappings_path: Path | str = FUEL_MAPPINGS_PATH,
    exclude_own_use_td_losses: bool = True,
    tolerance: float = AGGREGATED_DEMAND_ZERO_ABSOLUTE_TOLERANCE,
) -> pd.DataFrame:
    """Build every nonzero 2022/2023 aggregated-demand branch by economy.

    Source tables are loaded once for all economies. Projection allocation
    keeps the economy key, so this is equivalent to separate economy runs while
    avoiding repeated full-file reads.
    """
    if int(projection_base_year) < int(PROJECTION_START_YEAR):
        raise ValueError(
            f"projection_base_year must be at least {PROJECTION_START_YEAR}; "
            f"got {projection_base_year}."
        )

    resolved_esto_path = _resolve(esto_data_path)
    resolved_projection_path = _resolve(projection_data_path)
    resolved_mappings_path = _resolve(fuel_mappings_path)
    esto_data = _load_esto_base_csv(
        resolved_esto_path,
        economy=None,
        base_year=base_year,
    )
    projection_data = _load_demand_csv(
        resolved_projection_path,
        economy=None,
        final_year=projection_base_year,
    )
    esto_fuel_map = load_fuel_mapping(resolved_mappings_path, FUEL_ESTO_SHEET)

    base_rows = _extract_base_year(
        esto_data,
        base_year=base_year,
        exclude_own_use_td_losses=exclude_own_use_td_losses,
        use_sector_branches=True,
    )
    base_values = base_rows.groupby(
        ["economy", "sector", "fuel_code", "year"],
        as_index=False,
    )["value"].sum(min_count=1)
    base_values["leap_fuel_name"] = base_values["fuel_code"].map(esto_fuel_map)
    base_values = base_values[
        base_values["leap_fuel_name"].notna()
        & pd.to_numeric(base_values["value"], errors="coerce").abs().gt(tolerance)
    ]
    pair_parts = [base_values[["economy", "sector", "leap_fuel_name"]]]

    for scenario in projection_scenarios:
        projection_rows, _ = _extract_contextual_projection_years(
            ninth_df=projection_data,
            esto_df=esto_data,
            csv_scenario=str(scenario).strip().lower(),
            esto_fuel_map=esto_fuel_map,
            base_year=base_year,
            final_year=projection_base_year,
            exclude_own_use_td_losses=exclude_own_use_td_losses,
            use_sector_branches=True,
            mappings_path=resolved_mappings_path,
        )
        projection_rows = projection_rows[
            projection_rows["year"].eq(int(projection_base_year))
            & pd.to_numeric(projection_rows["value"], errors="coerce").abs().gt(tolerance)
        ]
        pair_parts.append(
            projection_rows[["economy", "sector", "leap_fuel_name"]]
        )

    return _add_branch_paths(pd.concat(pair_parts, ignore_index=True))


def build_missing_branch_cases(
    generated_pairs: pd.DataFrame,
    *,
    template_paths_by_economy: Mapping[str, Iterable[str]],
    apec_branch_paths: Iterable[str],
) -> pd.DataFrame:
    """Return templated-economy gaps plus the synthetic APEC fallback gaps."""
    required = {"economy", "branch_path"}
    missing = sorted(required.difference(generated_pairs.columns))
    if missing:
        raise KeyError(f"Generated branch paths are missing columns: {missing}")

    rows: list[dict[str, str]] = []
    for economy, available_paths in sorted(template_paths_by_economy.items()):
        available = {str(path).strip() for path in available_paths if str(path).strip()}
        requested = set(
            generated_pairs.loc[
                generated_pairs["economy"].astype(str).str.strip().eq(str(economy).strip()),
                "branch_path",
            ].astype(str)
        )
        rows.extend(
            {"Economy": str(economy).strip(), "Branch Path": branch_path}
            for branch_path in sorted(requested.difference(available))
        )

    # All demand values are made positive before aggregation, so a path is
    # nonzero in the synthetic APEC economy exactly when it is nonzero in at
    # least one member economy.
    generated_apec_paths = {
        str(path).strip()
        for path in generated_pairs["branch_path"]
        if str(path).strip()
    }
    available_apec_paths = {
        str(path).strip() for path in apec_branch_paths if str(path).strip()
    }
    rows.extend(
        {"Economy": "APEC", "Branch Path": branch_path}
        for branch_path in sorted(generated_apec_paths.difference(available_apec_paths))
    )

    result = pd.DataFrame(rows, columns=["Economy", "Branch Path"])
    return result.drop_duplicates().sort_values(
        ["Economy", "Branch Path"],
        kind="stable",
    ).reset_index(drop=True)


def run_aggregated_demand_template_coverage_audit(
    *,
    output_path: Path | str = DEFAULT_OUTPUT_PATH,
    templates_root: Path | str = DEFAULT_LEAP_EXPORT_TEMPLATES_ROOT,
    base_year: int = BASE_YEAR,
    projection_base_year: int = PROJECTION_START_YEAR,
    projection_scenarios: Iterable[str] = DEFAULT_PROJECTION_SCENARIOS,
) -> pd.DataFrame:
    """Run the complete audit, write the combined CSV, and return its rows."""
    resolved_templates_root = _resolve(templates_root)
    generated_pairs = build_generated_nonzero_branch_paths_by_economy(
        base_year=base_year,
        projection_base_year=projection_base_year,
        projection_scenarios=projection_scenarios,
    )
    template_paths_by_economy = {
        economy: read_leap_export_template_branch_paths(
            find_leap_export_template(
                economy,
                templates_root=resolved_templates_root,
            ).path
        )
        for economy in available_template_economies(resolved_templates_root)
    }
    apec_branch_paths = build_apec_template_branch_path_union(
        resolved_templates_root
    )
    missing_cases = build_missing_branch_cases(
        generated_pairs,
        template_paths_by_economy=template_paths_by_economy,
        apec_branch_paths=apec_branch_paths,
    )

    resolved_output_path = _resolve(output_path)
    resolved_output_path.parent.mkdir(parents=True, exist_ok=True)
    missing_cases.to_csv(resolved_output_path, index=False)
    counts = missing_cases.groupby("Economy").size().to_dict()
    print(
        f"Saved {len(missing_cases)} unique missing aggregated-demand branch "
        f"case(s) to {resolved_output_path}."
    )
    print(f"Missing cases by economy: {counts}")
    return missing_cases


#%%
# --- Jupyter run block ---
RUN_AGGREGATED_DEMAND_TEMPLATE_COVERAGE_AUDIT = True

if __name__ == "__main__" and RUN_AGGREGATED_DEMAND_TEMPLATE_COVERAGE_AUDIT:
    AUDIT_RESULT = run_aggregated_demand_template_coverage_audit()

#%%
