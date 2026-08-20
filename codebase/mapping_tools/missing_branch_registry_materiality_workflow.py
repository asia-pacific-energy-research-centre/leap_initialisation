#%%
"""Refresh source-based materiality fields in the missing LEAP branch registry.

The registry stays user-owned: this workflow never adds/removes paths or edits
``date_added``/``notes``.  It only refreshes derived PJ values from the active
ESTO vintage's configured base year and the active 9th projection horizon.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

import pandas as pd

from codebase.analysis.missing_branch_esto_vintage_impact import (
    FLOW_BY_SECTOR,
    NINTH_FUEL,
    NINTH_SECTOR_LEVEL,
    PRODUCT_BY_FUEL,
)
from codebase.configuration import workflow_config as workflow_cfg


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY_PATH = REPO_ROOT / "config" / "missing_leap_branch_registry.csv"
BASE_COLUMNS = ["branch_path", "date_added", "notes"]
MATERIALITY_COLUMNS = [
    "esto_base_year",
    "esto_base_year_signed_pj_all_economies",
    "esto_base_year_absolute_pj_all_economies",
    "projection_start_year",
    "projection_end_year",
    "projection_year_count",
    "reference_projection_signed_average_pj_per_year_all_economies",
    "reference_projection_absolute_average_pj_per_year_all_economies",
    "target_projection_signed_average_pj_per_year_all_economies",
    "target_projection_absolute_average_pj_per_year_all_economies",
]


def _normalise_path(value: object) -> str:
    return "\\".join(
        part.strip() for part in str(value or "").replace("/", "\\").split("\\") if part.strip()
    ).casefold()


def _read_registry(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        missing = set(BASE_COLUMNS).difference(fieldnames)
        if missing:
            raise ValueError(f"Registry {path} is missing columns: {sorted(missing)}")
        rows = [dict(row) for row in reader]
    identities = [_normalise_path(row["branch_path"]) for row in rows]
    if any(not identity for identity in identities) or len(identities) != len(set(identities)):
        raise ValueError(f"Registry {path} contains a blank or duplicate branch_path.")
    return rows, fieldnames


def _registry_source_keys(registry_rows: list[dict[str, str]]) -> pd.DataFrame:
    """Map exact registered LEAP demand/transformation leaves to ESTO/9th keys."""
    keys: list[dict[str, str]] = []
    for row in registry_rows:
        parts = [part.strip() for part in row["branch_path"].split("\\") if part.strip()]
        if len(parts) < 3 or parts[0] not in {"Demand", "Transformation"}:
            raise ValueError(f"Cannot derive source mapping for registry path: {row['branch_path']}")
        sector = parts[-2]
        fuel = parts[-1]
        missing = []
        if sector not in FLOW_BY_SECTOR:
            missing.append(f"sector={sector!r}")
        if fuel not in PRODUCT_BY_FUEL or fuel not in NINTH_FUEL:
            missing.append(f"fuel={fuel!r}")
        if sector not in NINTH_SECTOR_LEVEL:
            missing.append(f"9th sector={sector!r}")
        if missing:
            raise ValueError(
                f"Registry path needs an explicit source mapping before materiality can be refreshed: "
                f"{row['branch_path']} ({'; '.join(missing)})"
            )
        keys.append({
            "branch_path": row["branch_path"],
            "sector": sector,
            "fuel": fuel,
            "esto_flow": FLOW_BY_SECTOR[sector],
            "esto_product": PRODUCT_BY_FUEL[fuel],
        })
    return pd.DataFrame(keys)


def _numeric_sum(values: pd.Series) -> tuple[float, float]:
    numeric = pd.to_numeric(values, errors="coerce").fillna(0.0)
    return float(numeric.sum()), float(numeric.abs().sum())


def _esto_base_materiality(keys: pd.DataFrame, *, esto_path: Path, base_year: int) -> dict[str, tuple[float, float]]:
    result = {path: (0.0, 0.0) for path in keys["branch_path"]}
    lookup = {
        (row.esto_flow, row.esto_product): row.branch_path
        for row in keys.itertuples(index=False)
    }
    usecols = ["flows", "products", "is_subtotal", str(base_year)]
    for chunk in pd.read_csv(esto_path, usecols=usecols, chunksize=200_000, low_memory=False):
        chunk = chunk[chunk["is_subtotal"].fillna(False).ne(True)].copy()
        pairs = list(zip(chunk["flows"].astype(str), chunk["products"].astype(str)))
        chunk["branch_path"] = [lookup.get(pair, "") for pair in pairs]
        chunk = chunk[chunk["branch_path"].ne("")]
        for branch_path, group in chunk.groupby("branch_path", sort=False):
            signed, absolute = _numeric_sum(group[str(base_year)])
            prior_signed, prior_absolute = result[str(branch_path)]
            result[str(branch_path)] = (prior_signed + signed, prior_absolute + absolute)
    return result


def _projection_materiality(
    keys: pd.DataFrame,
    *,
    ninth_path: Path,
    projection_years: list[int],
) -> dict[str, dict[str, tuple[float, float]]]:
    year_columns = [str(year) for year in projection_years]
    values = defaultdict(lambda: defaultdict(lambda: {"exact": [0.0, 0.0, 0], "fallback": [0.0, 0.0, 0]}))
    usecols = [
        "scenarios", "sectors", "sub1sectors", "sub2sectors", "fuels", "subfuels",
        "subtotal_layout", "subtotal_results", *year_columns,
    ]
    for chunk in pd.read_csv(ninth_path, usecols=usecols, chunksize=200_000, low_memory=False):
        chunk = chunk[
            chunk["scenarios"].astype(str).str.casefold().isin({"reference", "target"})
            & chunk["subtotal_layout"].fillna(False).eq(False)
            & chunk["subtotal_results"].fillna(False).eq(False)
        ]
        for key in keys.itertuples(index=False):
            level, sector_code = NINTH_SECTOR_LEVEL[key.sector]
            fuel_code, subfuel_code = NINTH_FUEL[key.fuel]
            subset = chunk[chunk[level].eq(sector_code) & chunk["fuels"].eq(fuel_code)]
            if subset.empty:
                continue
            for match_name, match in (
                ("exact", subset[subset["subfuels"].eq(subfuel_code)]),
                ("fallback", subset[subset["subfuels"].eq("x")] if subfuel_code != "x" else pd.DataFrame()),
            ):
                if match.empty:
                    continue
                for scenario, scenario_rows in match.groupby("scenarios", sort=False):
                    signed, absolute = _numeric_sum(scenario_rows[year_columns].stack())
                    bucket = values[key.branch_path][str(scenario).casefold()][match_name]
                    bucket[0] += signed
                    bucket[1] += absolute
                    bucket[2] += len(scenario_rows)
    result: dict[str, dict[str, tuple[float, float]]] = {}
    for branch_path in keys["branch_path"]:
        result[branch_path] = {}
        for scenario in ("reference", "target"):
            exact = values[branch_path][scenario]["exact"]
            fallback = values[branch_path][scenario]["fallback"]
            selected = exact if exact[2] else fallback
            result[branch_path][scenario] = (selected[0], selected[1])
    return result


def refresh_missing_branch_registry_materiality(
    registry_path: Path | str = DEFAULT_REGISTRY_PATH,
    *,
    esto_path: Path | str | None = None,
    esto_base_year: int | None = None,
    ninth_path: Path | str | None = None,
    projection_start_year: int | None = None,
    projection_final_year: int | None = None,
) -> pd.DataFrame:
    """Refresh derived values while preserving registry identity/date/notes exactly."""
    source = workflow_cfg.get_energy_source_config()
    registry = Path(registry_path)
    rows, existing_columns = _read_registry(registry)
    rows_needing_materiality = [
        row for row in rows
        if any(not str(row.get(column, "")).strip() for column in MATERIALITY_COLUMNS)
    ]
    if not rows_needing_materiality:
        return pd.DataFrame(rows)
    keys = _registry_source_keys(rows_needing_materiality)
    base_year = int(esto_base_year if esto_base_year is not None else source.esto_base_year)
    start_year = int(projection_start_year if projection_start_year is not None else source.projection_start_year)
    final_year = int(projection_final_year if projection_final_year is not None else (source.projection_final_year or 2060))
    if final_year < start_year:
        raise ValueError("Projection final year precedes projection start year.")
    projection_years = list(range(start_year, final_year + 1))
    esto_values = _esto_base_materiality(
        keys, esto_path=Path(esto_path or source.esto_base_table_path), base_year=base_year,
    )
    projection_values = _projection_materiality(
        keys, ninth_path=Path(ninth_path or source.ninth_projection_table_path), projection_years=projection_years,
    )
    refreshed = pd.DataFrame(rows)
    for index, row in refreshed.iterrows():
        if row["branch_path"] not in set(keys["branch_path"]):
            continue
        signed, absolute = esto_values[row["branch_path"]]
        derived_values = {
            "esto_base_year": base_year,
            "esto_base_year_signed_pj_all_economies": signed,
            "esto_base_year_absolute_pj_all_economies": absolute,
            "projection_start_year": start_year,
            "projection_end_year": final_year,
            "projection_year_count": len(projection_years),
        }
        for scenario in ("reference", "target"):
            projection_signed, projection_absolute = projection_values[row["branch_path"]][scenario]
            derived_values[f"{scenario}_projection_signed_average_pj_per_year_all_economies"] = projection_signed / len(projection_years)
            derived_values[f"{scenario}_projection_absolute_average_pj_per_year_all_economies"] = projection_absolute / len(projection_years)
        for column, value in derived_values.items():
            if not str(refreshed.at[index, column] if column in refreshed.columns else "").strip():
                refreshed.at[index, column] = value
    column_order = [*BASE_COLUMNS, *MATERIALITY_COLUMNS, *[
        column for column in existing_columns if column not in {*BASE_COLUMNS, *MATERIALITY_COLUMNS}
    ]]
    refreshed = refreshed.reindex(columns=column_order)
    refreshed.to_csv(registry, index=False, float_format="%.12g")
    return refreshed


# --- Notebook run block ---
REFRESH_REGISTRY = False

if __name__ == "__main__" and REFRESH_REGISTRY:
    result = refresh_missing_branch_registry_materiality()
    print(result.to_string(index=False))

#%%
