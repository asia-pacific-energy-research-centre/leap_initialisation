from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
LEAP_MAPPINGS_REPO_ROOT = REPO_ROOT.parent / "leap_mappings"
OUTLOOK_MAPPINGS_MASTER_PATH = LEAP_MAPPINGS_REPO_ROOT / "config" / "outlook_mappings_master.xlsx"
RUNTIME_TABLE_DIR = REPO_ROOT / "config" / "runtime_tables"

# Operational tables are standalone CSVs. Semantic LEAP/ESTO/9th mappings are
# never read from the retired consolidated compatibility workbook.
LEGACY_FILE_RUNTIME_TABLES = {
    "ESTO_subtotal_mapping.xlsx": "ESTO_subtotal_mapping.csv",
    "leap_results_explicit_reassignments.csv": "leap_explicit_reassignments.csv",
    "leap_results_sheet_map.csv": "leap_results_sheet_map.csv",
    "leap_results_x_hierarchy_overrides.csv": "leap_x_hierarchy_overrides.csv",
    "ninth_sector_fuel_pairs.csv": "ninth_sector_fuel_pairs.csv",
    "synthetic_reference_rows.csv": "synthetic_reference_rows.csv",
}

CANONICAL_FILE_DEFAULT_SHEETS = {
    "ninth_pairs_to_esto_pairs.xlsx": "ninth_pairs_to_esto_pairs",
}

CANONICAL_WORKBOOK_SHEETS = {
    ("leap_mappings.xlsx", "leap_combined_esto"): "leap_combined_esto",
    ("leap_mappings.xlsx", "leap_combined_ninth"): "leap_combined_ninth",
    ("sector_fuel_codes_to_names.xlsx", "code_to_name"): "__compat_code_to_name",
    ("sector_fuel_codes_to_names.xlsx", "ESTO_LEAP_names"): "__compat_esto_leap_names",
    ("sector_fuel_codes_to_names.xlsx", "9th"): "__compat_ninth_names",
    ("sector_fuel_codes_to_names.xlsx", "ESTO"): "__compat_esto_names",
    ("independent product flow mappings.xlsx", "product"): "ninth fuel to esto product",
    ("independent product flow mappings.xlsx", "flow"): "__compat_independent_flow",
}

CANONICAL_COMPATIBILITY_SHEETS = {
    "code_to_name": "__compat_code_to_name",
    "ESTO_LEAP_names": "__compat_esto_leap_names",
    "9th": "__compat_ninth_names",
    "ESTO": "__compat_esto_names",
}


def resolve_runtime_table(path: str | Path) -> Path | None:
    """Resolve an old operational-table filename to its standalone CSV."""
    filename = LEGACY_FILE_RUNTIME_TABLES.get(Path(path).name)
    return RUNTIME_TABLE_DIR / filename if filename else None


def resolve_canonical_mapping_sheet(path: str | Path, sheet_name: str | None = None) -> str | None:
    """Return the canonical sheet replacing a legacy mapping-file reference."""
    source = Path(path)
    if source.name == OUTLOOK_MAPPINGS_MASTER_PATH.name:
        if sheet_name is None:
            return None
        return CANONICAL_COMPATIBILITY_SHEETS.get(str(sheet_name), str(sheet_name))
    if sheet_name is not None:
        mapped = CANONICAL_WORKBOOK_SHEETS.get((source.name, str(sheet_name)))
        if mapped:
            return mapped
    return CANONICAL_FILE_DEFAULT_SHEETS.get(source.name)


def _read_canonical_compatibility_table(sheet_name: str, **kwargs: Any) -> pd.DataFrame:
    """Reconstruct retired codebook shapes from canonical workbook sheets."""
    dtype = kwargs.get("dtype")
    names = pd.read_excel(
        OUTLOOK_MAPPINGS_MASTER_PATH,
        sheet_name="leap_display_names",
        dtype=dtype,
    ).fillna("")
    pairs = pd.read_excel(
        OUTLOOK_MAPPINGS_MASTER_PATH,
        sheet_name="ninth_pairs_to_esto_pairs",
        dtype=dtype,
    ).fillna("")

    resolved_name = names["leap_display_name"].astype(str).str.strip()
    if "auto_name" in names.columns:
        resolved_name = resolved_name.where(resolved_name.ne(""), names["auto_name"].astype(str).str.strip())
    name_lookup = dict(zip(zip(names["code_type"].astype(str), names["code"].astype(str)), resolved_name))

    if sheet_name == "__compat_code_to_name":
        rows: list[dict[str, str]] = []
        for _, row in pairs.iterrows():
            ninth_sector = str(row.get("9th_sector", "")).strip()
            ninth_fuel = str(row.get("9th_fuel", "")).strip()
            esto_flow = str(row.get("esto_flow", "")).strip()
            esto_product = str(row.get("esto_product", "")).strip()
            rows.extend([
                {"9th_label": ninth_sector, "9th_column": "sectors", "esto_label": esto_flow,
                 "esto_column": "flows", "name": name_lookup.get(("esto_flow", esto_flow), "")},
                {"9th_label": ninth_fuel, "9th_column": "fuels", "esto_label": esto_product,
                 "esto_column": "products", "name": name_lookup.get(("esto_product", esto_product), "")},
            ])
        return pd.DataFrame(rows).drop_duplicates().reset_index(drop=True)

    if sheet_name == "__compat_esto_leap_names":
        combined = pd.read_excel(
            OUTLOOK_MAPPINGS_MASTER_PATH,
            sheet_name="leap_combined_esto",
            dtype=dtype,
        ).fillna("")
        return pd.DataFrame({
            "category": "products",
            "leap_name": combined["raw_leap_fuel_name"],
            "original_label": combined["esto_product"],
        }).drop_duplicates().reset_index(drop=True)

    if sheet_name in {"__compat_ninth_names", "__compat_esto_names"}:
        prefix = "ninth_" if sheet_name == "__compat_ninth_names" else "esto_"
        selected = names[names["code_type"].astype(str).str.startswith(prefix)].copy()
        return pd.DataFrame({
            "code": selected["code"],
            "name": [name_lookup.get((str(t), str(c)), "") for t, c in zip(selected["code_type"], selected["code"])],
            "code_type": selected["code_type"],
        }).reset_index(drop=True)

    if sheet_name == "__compat_independent_flow":
        return pairs[["9th_sector", "esto_flow"]].drop_duplicates().reset_index(drop=True)

    raise ValueError(f"Unknown canonical compatibility sheet: {sheet_name}")


def config_table_exists(path: str | Path, sheet_name: str | None = None) -> bool:
    """Return True for canonical mappings, standalone runtime tables, or direct files."""
    canonical_sheet = resolve_canonical_mapping_sheet(path, sheet_name)
    if canonical_sheet:
        if not OUTLOOK_MAPPINGS_MASTER_PATH.exists():
            return False
        try:
            return canonical_sheet.startswith("__compat_") or canonical_sheet in pd.ExcelFile(OUTLOOK_MAPPINGS_MASTER_PATH).sheet_names
        except Exception:
            return False
    runtime_table = resolve_runtime_table(path)
    if runtime_table is not None:
        return runtime_table.exists()
    return Path(path).exists()


def read_config_table(
    path: str | Path,
    sheet_name: str | None = None,
    **kwargs: Any,
) -> pd.DataFrame:
    """Read a canonical mapping, standalone runtime table, or direct file."""
    path = Path(path)
    canonical_sheet = resolve_canonical_mapping_sheet(path, sheet_name)
    if canonical_sheet:
        if not OUTLOOK_MAPPINGS_MASTER_PATH.exists():
            raise FileNotFoundError(
                f"Canonical mapping workbook not found: {OUTLOOK_MAPPINGS_MASTER_PATH}"
            )
        kwargs.pop("encoding", None)
        if canonical_sheet.startswith("__compat_"):
            return _read_canonical_compatibility_table(canonical_sheet, **kwargs)
        return pd.read_excel(
            OUTLOOK_MAPPINGS_MASTER_PATH,
            sheet_name=canonical_sheet,
            **kwargs,
        )

    runtime_table = resolve_runtime_table(path)
    if runtime_table is not None:
        if not runtime_table.exists():
            raise FileNotFoundError(f"Runtime configuration table not found: {runtime_table}")
        kwargs.pop("sheet_name", None)
        return pd.read_csv(runtime_table, **kwargs)

    if path.suffix.lower() in {".xlsx", ".xlsm", ".xls"}:
        if sheet_name is not None:
            kwargs["sheet_name"] = sheet_name
        return pd.read_excel(path, **kwargs)

    kwargs.pop("sheet_name", None)
    return pd.read_csv(path, **kwargs)
