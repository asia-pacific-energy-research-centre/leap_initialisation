#%%
"""Refresh source-based materiality fields in the missing LEAP branch registry.

The registry stays user-owned: this workflow never adds/removes paths or edits
``date_added``/``notes``.  It only refreshes derived PJ values from the active
ESTO vintage's configured base year and the active 9th projection horizon.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

import pandas as pd

from codebase.configuration import workflow_config as workflow_cfg
from codebase.functions.ninth_projection_mapping import add_ninth_pair_columns
from codebase.functions.unified_name_lookup import load_active_mapping_sheet
from codebase.transfers_workflow import TRANSFER_FLOW_CODES


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

# These two processes are produced at an explicitly detailed 09 boundary in
# the transformation workflow. The compatibility mapping deliberately rolls
# them up for some comparison uses, so a missing LEAP leaf cannot obtain this
# detail by composing the canonical axes alone. Keep the source boundaries
# here, next to the materiality resolver, rather than infer them from a broad
# transformation parent.
PROCESS_SOURCE_BOUNDARIES = {
    "Coke ovens": {
        "esto_flow": "09.08.01 Coke ovens",
        "ninth_sector": "09_08_01_coke_ovens",
    },
    "Gas to liquids plants": {
        "esto_flow": "09.06.04 Gas-to-liquids plants",
        "ninth_sector": "09_06_04_gastoliquids_plants",
    },
}


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


@lru_cache(maxsize=1)
def _canonical_leaf_relationships() -> pd.DataFrame:
    """Load canonical leaf relationships once per materiality refresh process."""
    ninth_mapping = load_active_mapping_sheet("leap_combined_ninth").fillna("")
    esto_mapping = load_active_mapping_sheet("leap_combined_esto").fillna("")
    key_columns = ["leap_sector_name_full_path", "raw_leap_fuel_name"]
    for mapping in (ninth_mapping, esto_mapping):
        for column in [
            *key_columns,
            *[
                column for column in mapping.columns
                if column in {"ninth_sector", "ninth_fuel", "esto_flow", "esto_product"}
            ],
        ]:
            mapping[column] = mapping[column].astype(str).str.strip()
    ninth_mapping = ninth_mapping[key_columns + ["ninth_sector", "ninth_fuel"]].drop_duplicates()
    esto_mapping = esto_mapping[key_columns + ["esto_flow", "esto_product"]].drop_duplicates()
    return ninth_mapping.merge(esto_mapping, on=key_columns, how="inner")


@lru_cache(maxsize=1)
def _canonical_axis_relationships() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load the two canonical LEAP axes without requiring an existing pair.

    The combined mapping sheets remain the source of truth.  This view is used
    only for a missing branch whose sector/process and fuel are each already
    mapped, but whose *new combination* is absent because the LEAP branch is an
    interim or proxy branch.  We never choose between multiple axis targets.
    """
    key_columns = ["leap_sector_name_full_path", "raw_leap_fuel_name"]
    esto = load_active_mapping_sheet("leap_combined_esto").fillna("")
    ninth = load_active_mapping_sheet("leap_combined_ninth").fillna("")
    for mapping, target_columns in (
        (esto, ["esto_flow", "esto_product"]),
        (ninth, ["ninth_sector", "ninth_fuel"]),
    ):
        for column in [*key_columns, *target_columns]:
            mapping[column] = mapping[column].astype(str).str.strip()
    return (
        esto[key_columns + ["esto_flow", "esto_product"]].drop_duplicates(),
        ninth[key_columns + ["ninth_sector", "ninth_fuel"]].drop_duplicates(),
    )


def _axis_target(
    mapping: pd.DataFrame,
    *,
    sector_candidates: list[str],
    fuel: str,
    sector_target_column: str,
    fuel_target_column: str,
    path: str,
) -> tuple[str, str]:
    """Return one explicit axis target or raise an auditable ambiguity error."""
    normalised_candidates = {_normalise_path(candidate) for candidate in sector_candidates}
    sector_matches = mapping[
        mapping["leap_sector_name_full_path"].map(_normalise_path).isin(normalised_candidates)
    ]
    sector_targets = sorted({
        str(value).strip() for value in sector_matches[sector_target_column] if str(value).strip()
    })
    fuel_matches = mapping[
        mapping["raw_leap_fuel_name"].astype(str).str.strip().str.casefold().eq(fuel.casefold())
    ]
    fuel_targets = sorted({
        str(value).strip() for value in fuel_matches[fuel_target_column] if str(value).strip()
    })
    if len(sector_targets) != 1 or len(fuel_targets) != 1:
        raise ValueError(
            f"Cannot compose unambiguous {sector_target_column}/{fuel_target_column} mappings for {path}: "
            f"sector targets={sector_targets!r}; fuel targets={fuel_targets!r}"
        )
    return sector_targets[0], fuel_targets[0]


def _fuel_axis_target(
    mapping: pd.DataFrame,
    *,
    fuel: str,
    target_column: str,
    path: str,
) -> str:
    """Return one mapped source fuel/product, refusing ambiguous labels."""
    matches = mapping[
        mapping["raw_leap_fuel_name"].astype(str).str.strip().str.casefold().eq(fuel.casefold())
    ]
    targets = sorted({str(value).strip() for value in matches[target_column] if str(value).strip()})
    if len(targets) != 1:
        raise ValueError(
            f"Cannot compose an unambiguous {target_column} mapping for {path}: "
            f"fuel targets={targets!r}"
        )
    return targets[0]


def _transfer_source_key(*, path: str, fuel: str) -> dict[str, str]:
    """Resolve the explicit transfer-workflow source boundary for a LEAP leaf."""
    esto, ninth = _canonical_axis_relationships()
    return {
        "branch_path": path,
        "leap_sector_name_full_path": "Transfers unallocated",
        "raw_leap_fuel_name": fuel,
        "esto_flow": TRANSFER_FLOW_CODES[0],
        "esto_product": _fuel_axis_target(
            esto, fuel=fuel, target_column="esto_product", path=path,
        ),
        "ninth_sector": "08_transfers",
        "ninth_fuel": _fuel_axis_target(
            ninth, fuel=fuel, target_column="ninth_fuel", path=path,
        ),
    }


def _process_source_key(*, path: str, process: str, fuel: str) -> dict[str, str]:
    """Resolve a detailed transformation process with a reviewed boundary."""
    boundary = PROCESS_SOURCE_BOUNDARIES[process]
    esto, ninth = _canonical_axis_relationships()
    return {
        "branch_path": path,
        "leap_sector_name_full_path": process,
        "raw_leap_fuel_name": fuel,
        "esto_flow": boundary["esto_flow"],
        "esto_product": _fuel_axis_target(
            esto, fuel=fuel, target_column="esto_product", path=path,
        ),
        "ninth_sector": boundary["ninth_sector"],
        "ninth_fuel": _fuel_axis_target(
            ninth, fuel=fuel, target_column="ninth_fuel", path=path,
        ),
    }


def _composed_source_key(
    *,
    path: str,
    sector_candidates: list[str],
    fuel: str,
) -> dict[str, str]:
    """Compose source keys from canonical sector and fuel axes when unique."""
    esto, ninth = _canonical_axis_relationships()
    esto_flow, esto_product = _axis_target(
        esto,
        sector_candidates=sector_candidates,
        fuel=fuel,
        sector_target_column="esto_flow",
        fuel_target_column="esto_product",
        path=path,
    )
    ninth_sector, ninth_fuel = _axis_target(
        ninth,
        sector_candidates=sector_candidates,
        fuel=fuel,
        sector_target_column="ninth_sector",
        fuel_target_column="ninth_fuel",
        path=path,
    )
    return {
        "branch_path": path,
        "leap_sector_name_full_path": sector_candidates[0],
        "raw_leap_fuel_name": fuel,
        "esto_flow": esto_flow,
        "esto_product": esto_product,
        "ninth_sector": ninth_sector,
        "ninth_fuel": ninth_fuel,
    }


def _source_sector_candidates(parts: list[str]) -> list[str]:
    """Return canonical source-sector candidates for one LEAP branch path.

    LEAP transformation paths add presentation groups such as ``Processes``
    and ``Feedstock Fuels``.  They do not change the source process.  The
    canonical mapping records that process as ``module/process`` (including
    an intentionally repeated name for interim single-process modules), so
    add that semantic form before falling back to progressively shorter raw
    paths.  This is structural normalization, not a process alias table.
    """
    source_parts = parts[1:-1]
    candidates = ["/".join(source_parts[:length]) for length in range(len(source_parts), 0, -1)]
    if parts[0] != "Transformation":
        return candidates
    grouping_nodes = {"Processes", "Feedstock Fuels", "Output Fuels", "Auxiliary Fuels"}
    process_parts = [part for part in source_parts if part not in grouping_nodes]
    if len(process_parts) == 1:
        process_parts *= 2
    semantic = "/".join(process_parts)
    if semantic and semantic not in candidates:
        candidates.insert(0, semantic)
    return candidates


def _registry_source_keys(registry_rows: list[dict[str, str]]) -> pd.DataFrame:
    """Resolve registered LEAP leaves through the canonical mapping interface.

    The compatibility workbook is generated from the editable single-axis
    contract.  It is the operational way to obtain a coherent LEAP-to-ESTO and
    LEAP-to-Ninth relationship; do not re-create a smaller hard-coded mapping
    dictionary here.
    """
    canonical = _canonical_leaf_relationships()
    keys: list[dict[str, str]] = []
    for row in registry_rows:
        parts = [part.strip() for part in row["branch_path"].split("\\") if part.strip()]
        if len(parts) < 3 or parts[0] not in {"Demand", "Transformation"}:
            raise ValueError(f"Cannot derive source mapping for registry path: {row['branch_path']}")
        if parts[0] == "Demand" and parts[1] == "All demand aggregated" and len(parts) == 3:
            raise ValueError(
                f"Aggregate-demand path needs a sector child before it can be mapped: {row['branch_path']}"
            )
        fuel = parts[-1]
        if parts[0] == "Transformation" and parts[1] == "Transfers unallocated":
            keys.append(_transfer_source_key(path=row["branch_path"], fuel=fuel))
            continue
        if parts[0] == "Transformation" and parts[1] in PROCESS_SOURCE_BOUNDARIES:
            keys.append(_process_source_key(
                path=row["branch_path"], process=parts[1], fuel=fuel,
            ))
            continue
        sector_candidates = _source_sector_candidates(parts)
        matched = canonical[
            canonical["raw_leap_fuel_name"].eq(fuel)
            & canonical["leap_sector_name_full_path"].isin(sector_candidates)
        ]
        if matched.empty:
            keys.append(_composed_source_key(
                path=row["branch_path"], sector_candidates=sector_candidates, fuel=fuel,
            ))
            continue
        matched = matched.copy()
        matched["branch_path"] = row["branch_path"]
        keys.extend(matched[[
            "branch_path", "leap_sector_name_full_path", "raw_leap_fuel_name",
            "esto_flow", "esto_product", "ninth_sector", "ninth_fuel",
        ]].to_dict("records"))
    return pd.DataFrame(keys).drop_duplicates()


def _numeric_sum(values: pd.Series) -> tuple[float, float]:
    numeric = pd.to_numeric(values, errors="coerce").fillna(0.0)
    return float(numeric.sum()), float(numeric.abs().sum())


def _is_blank(value: object) -> bool:
    """Treat CSV blanks and pandas' NaN representation as missing."""
    return value is None or pd.isna(value) or not str(value).strip()


def _esto_base_materiality(keys: pd.DataFrame, *, esto_path: Path, base_year: int) -> dict[str, tuple[float, float]]:
    """Return exact mapped ESTO values, retaining subtotal-only source pairs.

    Detailed non-subtotal rows take precedence over a same-pair subtotal. If a
    mapped pair is represented only by its subtotal, the subtotal is the best
    available source evidence and is retained. This avoids both dropping real
    parent-only data and double-counting a parent with its detailed children.
    """
    result = {path: (0.0, 0.0) for path in keys["branch_path"]}
    subtotal_result = {path: (0.0, 0.0) for path in keys["branch_path"]}
    paths_with_detail_rows: set[str] = set()
    lookup = defaultdict(set)
    for row in keys.itertuples(index=False):
        lookup[(row.esto_flow, row.esto_product)].add(row.branch_path)
    usecols = ["flows", "products", "is_subtotal", str(base_year)]
    for chunk in pd.read_csv(esto_path, usecols=usecols, chunksize=200_000, low_memory=False):
        for (flow, product), group in chunk.groupby(["flows", "products"], sort=False):
            branch_paths = lookup.get((str(flow), str(product)), set())
            if not branch_paths:
                continue
            is_subtotal = group["is_subtotal"].fillna(False).astype(str).str.strip().str.casefold().isin(
                {"true", "1", "yes", "y", "t"}
            )
            detailed_rows = group.loc[~is_subtotal]
            subtotal_rows = group.loc[is_subtotal]
            for branch_path in branch_paths:
                if not detailed_rows.empty:
                    signed, absolute = _numeric_sum(detailed_rows[str(base_year)])
                    prior_signed, prior_absolute = result[str(branch_path)]
                    result[str(branch_path)] = (prior_signed + signed, prior_absolute + absolute)
                    paths_with_detail_rows.add(str(branch_path))
                if not subtotal_rows.empty:
                    signed, absolute = _numeric_sum(subtotal_rows[str(base_year)])
                    prior_signed, prior_absolute = subtotal_result[str(branch_path)]
                    subtotal_result[str(branch_path)] = (prior_signed + signed, prior_absolute + absolute)
    for branch_path, subtotal_values in subtotal_result.items():
        if branch_path not in paths_with_detail_rows:
            result[branch_path] = subtotal_values
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
        "scenarios", "sectors", "sub1sectors", "sub2sectors", "sub3sectors", "sub4sectors", "fuels", "subfuels",
        "subtotal_layout", "subtotal_results", *year_columns,
    ]
    available_columns = set(pd.read_csv(ninth_path, nrows=0).columns)
    usecols = [column for column in usecols if column in available_columns]
    for chunk in pd.read_csv(ninth_path, usecols=usecols, chunksize=200_000, low_memory=False):
        for column in ("sectors", "sub1sectors", "sub2sectors", "sub3sectors", "sub4sectors", "fuels", "subfuels"):
            if column not in chunk:
                chunk[column] = "x"
        chunk = chunk[
            chunk["scenarios"].astype(str).str.casefold().isin({"reference", "target"})
            & chunk["subtotal_layout"].fillna(False).eq(False)
            & chunk["subtotal_results"].fillna(False).eq(False)
        ]
        chunk = add_ninth_pair_columns(chunk)
        for key in keys.itertuples(index=False):
            sector_exact = chunk["ninth_sector"].eq(key.ninth_sector)
            sector_any_level = chunk[["sectors", "sub1sectors", "sub2sectors", "sub3sectors", "sub4sectors"]].eq(key.ninth_sector).any(axis=1)
            fuel_exact = chunk["ninth_fuel"].eq(key.ninth_fuel)
            fuel_parent = chunk["fuels"].eq(key.ninth_fuel)
            sector_match = sector_exact if sector_exact.any() else sector_any_level
            fuel_match = fuel_exact if fuel_exact.any() else fuel_parent
            subset = chunk[sector_match & fuel_match]
            if subset.empty:
                continue
            for scenario, scenario_rows in subset.groupby("scenarios", sort=False):
                signed, absolute = _numeric_sum(scenario_rows[year_columns].stack())
                bucket = values[key.branch_path][str(scenario).casefold()]["exact"]
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
        if any(_is_blank(row.get(column, "")) for column in MATERIALITY_COLUMNS)
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
            if _is_blank(refreshed.at[index, column] if column in refreshed.columns else ""):
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
