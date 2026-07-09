#%%
"""
Build simplified interim transformation modules for electricity plants, CHP plants,
and heat plants.

Three separate LEAP transformation sectors are produced from ESTO power sector data,
one per plant type.  Each sector follows the same branch pattern:
  Transformation\\{module}\\Processes\\{module}

Modules and source codes covered
--------------------------------
Electricity interim  (mono output: electricity)
  ESTO: 09.01.01 Electricity plants, 09.02.01 Electricity plants
  9th signed input/output rows: 09_01_electricity_plants

CHP interim  (dual output: electricity + heat)
  ESTO: 09.01.02 CHP plants, 09.02.02 CHP plants
  9th signed input/output rows: 09_02_chp_plants

Heat plant interim  (mono output: heat)
  ESTO: 09.01.03 Heat plants, 09.02.03 Heat plants
  9th signed input/output rows: 09_x_heat_plants

Data sources:
- core.esto_data for historical/base-year rows, filtered away from ESTO subtotals.
- core.ninth_data for projection rows, filtered away from subtotal_results rows.

All negative source rows (feedstocks) for each module are used as inputs.
Auxiliary fuel use is excluded.  Own-use and losses are handled separately by
other_loss_own_use_proxy_workflow (sector 10.01.01).

The three modules are written into a single export workbook per economy and can
be toggled via RUN_ELECTRICITY_HEAT_DUMMY in supply_reconciliation_workflow.py.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
try:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
except Exception as exc:
    print(f"Failed to add repo root to sys.path: {exc}")

from codebase.functions import transformation_analysis_utils as core
from codebase.configuration import workflow_config as workflow_cfg
from codebase.functions import leap_api, leap_exports
from codebase.functions.analysis_input_write_dispatcher import (
    get_analysis_input_write_mode,
)
from codebase.configuration.config import (
    BRANCH_DEMAND_CATEGORY,
    BRANCH_DEMAND_TECHNOLOGY,
)
from codebase.utilities import workflow_common
from codebase.mappings.canonical_loaders import (
    build_code_to_display_name,
    load_canonical_sheet,
)

LEAP_API_AVAILABLE = leap_api.is_available()

# ---------------------------------------------------------------------------
# Workflow identity
# ---------------------------------------------------------------------------

SHEET_NAME = workflow_cfg.TRANSFORMATION_WORKFLOW_SHEET_NAME
EXPORT_FILENAME_PREFIX = "electricity_heat_interim"
EXPORT_FILENAME_TEMPLATE = "electricity_heat_interim_{economy}_{scenario}.xlsx"
EXPORT_FILENAME_FALLBACK = "electricity_heat_interim_export.xlsx"
DEFAULT_SCENARIOS = list(workflow_cfg.TRANSFORMATION_WORKFLOW_DEFAULT_SCENARIOS)
EXPORT_ID_LOOKUP_PATH = REPO_ROOT / "data" / "full model export.xlsx"

# ---------------------------------------------------------------------------
# Module definitions
# ---------------------------------------------------------------------------

# Each key is the LEAP sector title and process name.
# sub1sectors: 9th-data sub1sector codes to aggregate for projections.
# esto_flows: ESTO flow codes to aggregate for historical/base-year data.
# output_labels: LEAP output-fuel leaves to retain when a module has no data.
INTERIM_MODULES: dict[str, dict] = {
    "Electricity interim": {
        "sub1sectors": ["09_01_electricity_plants"],
        "esto_flows": [
            "09.01.01 Electricity plants",
            "09.02.01 Electricity plants",
        ],
        "output_labels": ["Electricity"],
    },
    "CHP interim": {
        "sub1sectors": ["09_02_chp_plants"],
        "esto_flows": [
            "09.01.02 CHP plants",
            "09.02.02 CHP plants",
        ],
        "output_labels": ["Electricity", "Heat"],
    },
    "Heat plant interim": {
        "sub1sectors": ["09_x_heat_plants"],
        "esto_flows": [
            "09.01.03 Heat plants",
            "09.02.03 Heat plants",
        ],
        "output_labels": ["Heat"],
    },
}

APPROVED_POWER_INTERIM_SUB1SECTORS = frozenset(
    {
        "09_01_electricity_plants",
        "09_02_chp_plants",
        "09_x_heat_plants",
    }
)
FORBIDDEN_POWER_INTERIM_SUB1SECTORS = frozenset(
    {
        "18_01_electricity_plants",
        "18_02_chp_plants",
        "19_01_chp_plants",
        "19_02_heat_plants",
    }
)


def validate_power_interim_sub1sectors(sub1sectors: Iterable[str]) -> list[str]:
    """Return validated 9th transformation sectors or reject unsafe sources."""
    selected = [str(value).strip() for value in sub1sectors]
    forbidden = sorted(set(selected) & FORBIDDEN_POWER_INTERIM_SUB1SECTORS)
    unknown = sorted(set(selected) - APPROVED_POWER_INTERIM_SUB1SECTORS)
    if forbidden or unknown:
        details = []
        if forbidden:
            details.append(f"forbidden source-role sectors={forbidden}")
        if unknown:
            details.append(f"unapproved sectors={unknown}")
        raise ValueError("Invalid interim power sector selection: " + "; ".join(details))
    return selected

ALL_POWER_SUB1SECTORS: list[str] = [
    code
    for module_cfg in INTERIM_MODULES.values()
    for code in module_cfg["sub1sectors"]
]

ALL_POWER_ESTO_FLOWS: list[str] = [
    code
    for module_cfg in INTERIM_MODULES.values()
    for code in module_cfg["esto_flows"]
]

# Use the full model export as the branch template, but only inspect the
# interim-module fuel branches so unrelated model rows cannot fail this check.
POWER_INTERIM_REFERENCE_WORKBOOK_PATH = REPO_ROOT / "data" / "full model export.xlsx"
POWER_INTERIM_REFERENCE_SHEET_NAME = "Export"
POWER_INTERIM_FUEL_VALIDATION_REPORT_PATH = (
    REPO_ROOT / "outputs" / "electricity_heat_interim" / "power_interim_fuel_validation_report.csv"
)

# Labels that are useful for diagnosing a mismatch but should not be emitted as
# feedstock/output branch fuel names.
POWER_INTERIM_NEVER_OUTPUT_LABELS: frozenset[str] = frozenset({
    "Total",
    "Total Renewables",
    "Modern renewables",
    "Petroleum products",
    "Coal",
    "Coal products",
    "Gas",
    "Solid biomass",
    # "Solar" is NOT here: the raw "Solar" label (from 12_solar / 12_solar_unallocated)
    # is remapped to "Solar nonspecified" by _safe_power_interim_display_label before
    # any NEVER_OUTPUT check, so adding it here would be dead code.
})

POWER_INTERIM_ALLOWED_WORKBOOK_ONLY_LABELS: frozenset[str] = frozenset({
    "Electricity",
    "Heat",
    "Tide wave ocean",
    "Geothermal",
    "Natural gas liquids",
})

_ESTO_PRODUCT_TO_NINTH_FUEL: dict[str, str] | None = None
_POWER_INTERIM_DISPLAY_NAME_MAP: dict[str, str] | None = None

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _truthy_flag(value: object) -> bool:
    """Return True for common spreadsheet truthy values."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y", "t"}


def _normalize_economy_code(value: object) -> str:
    """Return comparable economy code text without underscores."""
    return str(value).replace("_", "").strip()


def _normalize_label_text(value: object) -> str:
    """Return label text with repeated whitespace collapsed."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return " ".join(str(value).strip().split())


def _year_cols_between(year_cols: list, min_year: int | None = None, max_year: int | None = None) -> list[int]:
    """Return year columns inside the requested inclusive range."""
    selected: list[int] = []
    for year in year_cols:
        year_int = int(year)
        if min_year is not None and year_int < min_year:
            continue
        if max_year is not None and year_int > max_year:
            continue
        selected.append(year_int)
    return selected


def _zero_years_outside_range(
    df: pd.DataFrame,
    year_cols: list,
    min_year: int | None = None,
    max_year: int | None = None,
) -> pd.DataFrame:
    """Keep rows intact but zero year columns outside the requested source window."""
    out = df.copy()
    keep_years = set(_year_cols_between(year_cols, min_year=min_year, max_year=max_year))
    for year in year_cols:
        year_int = int(year)
        if year_int not in keep_years and year in out.columns:
            out[year] = 0.0
    return out


def _load_esto_product_to_ninth_fuel() -> dict[str, str]:
    """Load product-to-9th-fuel mappings from the canonical workbook."""
    global _ESTO_PRODUCT_TO_NINTH_FUEL
    if _ESTO_PRODUCT_TO_NINTH_FUEL is not None:
        return _ESTO_PRODUCT_TO_NINTH_FUEL

    mapping: dict[str, str] = {}

    ninth_to_esto_df = load_canonical_sheet(
        "ninth fuel to esto product",
        ("9th_fuel", "esto_product"),
        dtype=str,
    ).fillna("")
    for _, row in ninth_to_esto_df.iterrows():
        esto_label = _normalize_label_text(row["esto_product"])
        ninth_label = str(row["9th_fuel"]).strip()
        # A few aggregate ESTO products intentionally have multiple 9th
        # counterparts. Preserve the workbook's stable first-row choice, which
        # matches the previous loader's deterministic precedence.
        if esto_label and ninth_label and esto_label not in mapping:
            mapping[esto_label] = ninth_label

    aggregate_mappings = {
        label: ninth
        for label, ninth in mapping.items()
        if "." not in label.split(" ", 1)[0]
    }
    all_esto_labels = [
        _normalize_label_text(row["esto_product"])
        for _, row in ninth_to_esto_df.iterrows()
        if _normalize_label_text(row.get("esto_product", ""))
    ]
    for esto_label in all_esto_labels:
        if not esto_label or esto_label in mapping:
            continue
        code = esto_label.split(" ", 1)[0]
        if "." not in code:
            continue
        parent_code = code.split(".", 1)[0]
        parent_match = next(
            (
                ninth
                for aggregate_label, ninth in aggregate_mappings.items()
                if aggregate_label.startswith(parent_code + " ")
            ),
            "",
        )
        if parent_match:
            mapping[esto_label] = parent_match

    _ESTO_PRODUCT_TO_NINTH_FUEL = mapping
    return _ESTO_PRODUCT_TO_NINTH_FUEL


def _drop_esto_subtotals(df: pd.DataFrame) -> pd.DataFrame:
    """Drop rows flagged as subtotals in the ESTO data."""
    out = df.copy()
    if "is_subtotal" in out.columns:
        out = out[~out["is_subtotal"].map(_truthy_flag)].copy()
    return out


def _drop_ninth_projection_subtotals(df: pd.DataFrame) -> pd.DataFrame:
    """Drop 9th rows flagged as projection subtotals."""
    out = df.copy()
    if "subtotal_results" in out.columns:
        out = out[~out["subtotal_results"].map(_truthy_flag)].copy()
    return out


def _map_esto_products_to_ninth_fuels(df: pd.DataFrame) -> pd.DataFrame:
    """Add fuel columns to ESTO rows using canonical product mappings."""
    if df.empty:
        return df.copy()
    if "products" not in df.columns:
        raise ValueError("ESTO module rows are missing the products column.")

    product_to_ninth = _load_esto_product_to_ninth_fuel()
    out = df.copy()
    products = out["products"].map(_normalize_label_text)
    out["products"] = products
    out["subfuels"] = products.map(product_to_ninth).fillna(products)
    out["fuels"] = out["subfuels"]

    unmapped = sorted(products[(products != "") & ~products.isin(product_to_ninth)].unique())
    if unmapped:
        print(
            "[WARN] ESTO product(s) missing 9th fuel mapping; keeping ESTO label: "
            + ", ".join(unmapped[:20])
            + (" ..." if len(unmapped) > 20 else "")
        )
    return out


def _load_power_interim_display_name_map() -> dict[str, str]:
    """Load canonical code-to-display-name mappings for interim fuel branches."""
    global _POWER_INTERIM_DISPLAY_NAME_MAP
    if _POWER_INTERIM_DISPLAY_NAME_MAP is not None:
        return _POWER_INTERIM_DISPLAY_NAME_MAP

    # Some source codes intentionally appear more than once for branch-specific
    # labels. The shared builder preserves sheet order and returns the same stable
    # first match used by this path historically; its conflict table is for QA.
    # Include explicitly non-output aggregate labels so the existing
    # POWER_INTERIM_NEVER_OUTPUT_LABELS guard can still identify and suppress
    # Coal/Gas/Petroleum-product subtotal rows.
    mapping, _conflicts = build_code_to_display_name(include_excluded=True)

    _POWER_INTERIM_DISPLAY_NAME_MAP = mapping
    return _POWER_INTERIM_DISPLAY_NAME_MAP


def _safe_power_interim_display_label(label: object) -> str:
    """Return a display label, keeping raw codes when no mapping exists."""
    text = _normalize_label_text(label)
    if not text:
        return ""
    mapping = _load_power_interim_display_name_map()
    resolved = mapping.get(text, text)
    # Both the aggregate "Solar" label (12_solar with no subfuel) and "Unallocated Solar"
    # (12_solar_unallocated) represent unspecified solar input — map to "Solar nonspecified"
    # so they write to the real LEAP branch rather than being suppressed.
    if resolved in ("Solar", "Unallocated Solar"):
        return "Solar nonspecified"
    return resolved


def _select_module_rows(
    data: pd.DataFrame,
    economy: str,
    sub1sectors: list[str],
) -> pd.DataFrame:
    """Return non-subtotal 9th-data rows matching sub1sector codes for one economy."""
    sub1sectors = validate_power_interim_sub1sectors(sub1sectors)
    if "sub1sectors" not in data.columns or "economy" not in data.columns:
        return data.iloc[0:0]
    # Economy codes may include underscores; normalize before comparing.
    norm_economy = _normalize_economy_code(economy)
    mask = (
        data["economy"].map(_normalize_economy_code) == norm_economy
    ) & (
        data["sub1sectors"].isin(sub1sectors)
    )
    return _drop_ninth_projection_subtotals(data[mask]).copy()


def _select_esto_module_rows(
    data: pd.DataFrame,
    economy: str,
    esto_flows: list[str],
) -> pd.DataFrame:
    """Return non-subtotal ESTO rows matching flow codes for one economy."""
    if "flows" not in data.columns or "economy" not in data.columns:
        return data.iloc[0:0]
    norm_economy = _normalize_economy_code(economy)
    mask = (
        data["economy"].map(_normalize_economy_code) == norm_economy
    ) & (
        data["flows"].fillna("").astype(str).str.strip().isin(esto_flows)
    )
    return _map_esto_products_to_ninth_fuels(_drop_esto_subtotals(data[mask]))


def _combine_module_source_rows(
    economy: str,
    sub1sectors: list[str],
    esto_flows: list[str],
) -> tuple[pd.DataFrame, list[int]]:
    """Return ESTO historical/base rows plus 9th projection rows for a module."""
    esto_rows = _select_esto_module_rows(core.esto_data, economy, esto_flows)
    ninth_rows = _select_module_rows(core.ninth_data, economy, sub1sectors)

    all_year_cols = sorted(
        set(int(year) for year in core.esto_year_cols)
        | set(int(year) for year in core.ninth_year_cols)
    )
    source_frames: list[pd.DataFrame] = []

    if not esto_rows.empty:
        esto_work = esto_rows.copy()
        for year in all_year_cols:
            if year not in esto_work.columns:
                esto_work[year] = 0.0
        esto_work = _zero_years_outside_range(
            esto_work,
            all_year_cols,
            max_year=core.BASE_YEAR,
        )
        esto_work["_source_priority"] = 0
        source_frames.append(esto_work)

    if not ninth_rows.empty:
        ninth_work = ninth_rows.copy()
        for year in all_year_cols:
            if year not in ninth_work.columns:
                ninth_work[year] = 0.0
        ninth_work = _zero_years_outside_range(
            ninth_work,
            all_year_cols,
            min_year=core.PROJECTION_START_YEAR,
        )
        ninth_work["_source_priority"] = 1
        source_frames.append(ninth_work)

    if not source_frames:
        return core.ninth_data.iloc[0:0].copy(), all_year_cols

    combined = pd.concat(source_frames, ignore_index=True, sort=False)
    combined = combined.copy()  # defragment before column assignments to avoid PerformanceWarning
    combined["_fuel_label"] = core.get_fuel_labels(combined).fillna("").astype(str).str.strip()
    key_cols = ["economy", "_fuel_label"]
    year_cols = [year for year in all_year_cols if year in combined.columns]
    non_year_cols = [
        col for col in combined.columns
        if col not in year_cols and col not in {"_source_priority"}
    ]
    first_values = (
        combined.sort_values("_source_priority")
        .groupby(key_cols, dropna=False)[non_year_cols]
        .first()
        .reset_index(drop=True)
    )
    totals = (
        combined.groupby(key_cols, dropna=False)[year_cols]
        .sum()
        .reset_index(drop=True)
    )
    output = pd.concat([first_values, totals], axis=1)
    output = output.drop(columns=["_fuel_label"], errors="ignore")
    return output, all_year_cols


def _build_power_interim_source_fuel_catalog(
    economies: Iterable[str] | None = None,
) -> dict[str, set[str]]:
    """Return the strict source-derived fuel set for each interim module."""
    economy_list = list(economies or core.ECONOMIES_TO_ANALYZE)
    catalog: dict[str, set[str]] = {module: set() for module in INTERIM_MODULES}
    for economy in economy_list:
        for module_name, module_cfg in INTERIM_MODULES.items():
            module_rows, year_cols = _combine_module_source_rows(
                economy=economy,
                sub1sectors=module_cfg["sub1sectors"],
                esto_flows=module_cfg["esto_flows"],
            )
            if module_rows.empty:
                continue
            totals, _ = core.summarize_fuel_totals(
                module_rows,
                year_cols,
                core.YEAR_START_FOR_ANALYSIS,
                allow_all_years_fallback=False,
            )
            feedstock_totals = totals[totals < 0]
            for label in feedstock_totals.index:
                if pd.isna(label):
                    continue
                label_text = _normalize_label_text(label)
                if not label_text or abs(float(feedstock_totals.get(label, 0.0))) <= 1e-12:
                    continue
                display_label = _safe_power_interim_display_label(label_text)
                if not display_label or display_label in POWER_INTERIM_NEVER_OUTPUT_LABELS:
                    continue
                catalog[module_name].add(display_label)
    return catalog


def _build_power_interim_workbook_fuel_catalog(
    workbook_path: Path | str = POWER_INTERIM_REFERENCE_WORKBOOK_PATH,
) -> dict[str, set[str]]:
    """Return the fuel branch names present in the reference workbook."""
    workbook_df = pd.read_excel(
        workbook_path,
        sheet_name=POWER_INTERIM_REFERENCE_SHEET_NAME,
        header=2,
        dtype=str,
    ).fillna("")
    path_mask = workbook_df["Branch Path"].astype(str).str.contains(
        r"\\(?:Output Fuels|Feedstock Fuels)\\",
        regex=True,
    )
    filtered = workbook_df[path_mask].copy()
    filtered["module"] = filtered["Branch Path"].astype(str).str.extract(r"Transformation\\([^\\]+)")
    filtered["fuel_name"] = filtered["Branch Path"].astype(str).str.extract(
        r"\\(?:Output Fuels|Feedstock Fuels)\\(.+)$"
    )

    catalog: dict[str, set[str]] = {module: set() for module in INTERIM_MODULES}
    for module_name, module_df in filtered.groupby("module"):
        if module_name not in catalog:
            continue
        values = {
            _normalize_label_text(value)
            for value in module_df["fuel_name"].tolist()
            if _normalize_label_text(value)
        }
        catalog[module_name] = values
    return catalog


def _classify_power_interim_workbook_only_label(label: str) -> str:
    """Return a coarse workbook-only classification for review output."""
    normalized = _normalize_label_text(label)
    if not normalized:
        return "ignore"
    if normalized in POWER_INTERIM_ALLOWED_WORKBOOK_ONLY_LABELS:
        return "allowed_extra"
    if normalized in POWER_INTERIM_NEVER_OUTPUT_LABELS:
        return "should_not_output"
    lowered = normalized.lower()
    if lowered.startswith("total"):
        return "should_not_output"
    if lowered in {"modern renewables", "solar", "solid biomass", "coal", "gas"}:
        return "should_not_output"
    return "review_or_add"


def _classify_power_interim_missing_label(label: str) -> str:
    """Return a coarse missing-label classification for review output."""
    normalized = _normalize_label_text(label)
    if not normalized:
        return "ignore"
    if normalized in POWER_INTERIM_NEVER_OUTPUT_LABELS:
        return "should_not_output"
    lowered = normalized.lower()
    if lowered.startswith("total"):
        return "should_not_output"
    if lowered in {"modern renewables", "solar", "solid biomass", "coal", "gas"}:
        return "should_not_output"
    if "products" in lowered:
        return "should_not_output"
    if "unallocated" in lowered or "nonspecified" in lowered:
        return "review_or_add"
    return "named_fuel"


def validate_power_interim_fuel_coverage(
    economies: Iterable[str] | None = None,
    workbook_path: Path | str = POWER_INTERIM_REFERENCE_WORKBOOK_PATH,
    report_path: Path | str | None = POWER_INTERIM_FUEL_VALIDATION_REPORT_PATH,
    raise_on_mismatch: bool = True,
) -> pd.DataFrame:
    """Compare source-derived power fuels against the reference interim workbook."""
    source_catalog = _build_power_interim_source_fuel_catalog(economies=economies)
    workbook_catalog = _build_power_interim_workbook_fuel_catalog(workbook_path=workbook_path)

    rows: list[dict[str, str]] = []
    for module_name in INTERIM_MODULES:
        source_set = source_catalog.get(module_name, set())
        workbook_set = workbook_catalog.get(module_name, set())

        missing = sorted(source_set - workbook_set)
        workbook_only = sorted(workbook_set - source_set)

        for label in missing:
            rows.append({
                "module": module_name,
                "fuel_name": label,
                "status": "missing_from_workbook",
                "classification": _classify_power_interim_missing_label(label),
            })
        for label in workbook_only:
            rows.append({
                "module": module_name,
                "fuel_name": label,
                "status": "workbook_only",
                "classification": _classify_power_interim_workbook_only_label(label),
            })

    report_df = pd.DataFrame(rows, columns=["module", "fuel_name", "status", "classification"])

    if report_path is not None:
        report_path_obj = Path(report_path)
        report_path_obj.parent.mkdir(parents=True, exist_ok=True)
        report_df.to_csv(report_path_obj, index=False)

    missing_df = report_df[report_df["status"] == "missing_from_workbook"].copy()
    workbook_only_df = report_df[report_df["status"] == "workbook_only"].copy()
    should_not_output_df = workbook_only_df[workbook_only_df["classification"] == "should_not_output"].copy()
    review_or_add_df = workbook_only_df[workbook_only_df["classification"] == "review_or_add"].copy()

    print("\n==== Power interim fuel validation ====")
    if missing_df.empty:
        print("Missing from workbook: none")
    else:
        print("Missing from workbook:")
        for module_name in INTERIM_MODULES:
            module_df = missing_df[missing_df["module"] == module_name]
            if module_df.empty:
                continue
            print(f"- {module_name}: {', '.join(module_df['fuel_name'].tolist())}")

    if review_or_add_df.empty:
        print("Workbook-only fuels to review/add: none")
    else:
        print("Workbook-only fuels to review/add:")
        for module_name in INTERIM_MODULES:
            module_df = review_or_add_df[review_or_add_df["module"] == module_name]
            if module_df.empty:
                continue
            print(f"- {module_name}: {', '.join(module_df['fuel_name'].tolist())}")

    if should_not_output_df.empty:
        print("Workbook-only fuels that should not be outputted: none")
    else:
        print("Workbook-only fuels that should not be outputted:")
        for module_name in INTERIM_MODULES:
            module_df = should_not_output_df[should_not_output_df["module"] == module_name]
            if module_df.empty:
                continue
            print(f"- {module_name}: {', '.join(module_df['fuel_name'].tolist())}")

    fatal_df = report_df[
        (report_df["status"] == "missing_from_workbook")
        | (
            (report_df["status"] == "workbook_only")
            & (report_df["classification"] != "allowed_extra")
        )
    ].copy()
    if raise_on_mismatch and not fatal_df.empty:
        raise ValueError(
            "Power interim fuel coverage does not match the reference workbook. "
            f"Report written to {report_path}."
        )

    return report_df


def _build_total_output_series(
    timeseries: pd.DataFrame,
    output_labels: Iterable[str],
    export_base: int,
    export_final: int,
) -> pd.Series:
    """Return combined output series (all positive fuels) over the export year range."""
    export_years = list(range(export_base, export_final + 1))
    total = pd.Series({year: 0.0 for year in export_years}, dtype=float)
    for label in output_labels:
        label_series = core.ensure_full_year_series(
            core.get_label_timeseries(timeseries, label),
            export_base,
            export_final,
        ).clip(lower=0.0)
        total = total.add(label_series, fill_value=0.0)
    return total


def _build_interim_process_record(
    economy: str,
    sector_title: str,
    process_name: str,
    sub1sectors: list[str],
    esto_flows: list[str],
    output_labels: list[str] | None = None,
) -> dict | None:
    """Return a process record for one interim module.

    Aggregates ESTO rows through the base year and 9th-data rows for projections.
    Positive flows become output_values entries (one per output fuel).
    Negative flows become feedstock inputs.
    Efficiency = total_output / total_input across covered sub-sectors.
    Exogenous capacity = total output energy (Million GJ/year = PJ/year).
    """
    module_rows, year_cols = _combine_module_source_rows(
        economy=economy,
        sub1sectors=sub1sectors,
        esto_flows=esto_flows,
    )

    if module_rows.empty:
        print(
            f"{sector_title} ({economy}): no ESTO/9th rows found for covered "
            f"ESTO flows {esto_flows} and sub1sectors {sub1sectors}; writing zero skeleton."
        )
        return core.build_zero_skeleton_record(
            economy, sector_title, process_name, output_labels,
            core.EXPORT_BASE_YEAR, core.EXPORT_FINAL_YEAR,
        )

    if not core.has_required_columns(
        module_rows,
        [["flows", "products"], ["flows", "subfuels", "fuels"], ["fuels", "subfuels"]],
        sector_title,
    ):
        print(f"{sector_title} ({economy}): missing required columns; skipping.")
        return None

    totals, _ = core.summarize_fuel_totals(
        module_rows, year_cols, core.YEAR_START_FOR_ANALYSIS, allow_all_years_fallback=True
    )
    timeseries, _ = core.summarize_fuel_timeseries(
        module_rows, year_cols, core.YEAR_START_FOR_ANALYSIS, allow_all_years_fallback=True
    )

    negative = totals[totals < 0]
    positive = totals[totals > 0]

    # Drop aggregate-category feedstock labels (e.g. "Petroleum products",
    # "Coal", "Gas") that are subtotals of the specific fuels already present.
    # Including them in the total input denominator causes feedstock shares to
    # sum to <100% in LEAP because no branch is ever written for them.
    aggregate_feedstocks = [
        lbl for lbl in negative.index
        if _safe_power_interim_display_label(lbl) in POWER_INTERIM_NEVER_OUTPUT_LABELS
    ]
    if aggregate_feedstocks:
        print(
            f"{sector_title} ({economy}): dropping aggregate feedstock label(s) "
            f"before share computation: "
            + ", ".join(str(l) for l in aggregate_feedstocks)
        )
        negative = negative.drop(index=aggregate_feedstocks)

    aggregate_outputs = [
        lbl for lbl in positive.index
        if _safe_power_interim_display_label(lbl) in POWER_INTERIM_NEVER_OUTPUT_LABELS
    ]
    if aggregate_outputs:
        print(
            f"{sector_title} ({economy}): dropping aggregate output label(s) "
            f"before output/capacity computation: "
            + ", ".join(str(l) for l in aggregate_outputs)
        )
        positive = positive.drop(index=aggregate_outputs)

    if negative.empty or positive.empty:
        print(
            f"{sector_title} ({economy}): missing input/output balance; "
            f"writing zero skeleton."
        )
        return core.build_zero_skeleton_record(
            economy, sector_title, process_name, output_labels,
            core.EXPORT_BASE_YEAR, core.EXPORT_FINAL_YEAR,
        )

    export_base = core.EXPORT_BASE_YEAR
    export_final = core.EXPORT_FINAL_YEAR
    export_years = list(range(export_base, export_final + 1))

    # Output values: one entry per positive fuel.
    # Electricity interim -> electricity only.
    # CHP interim -> electricity + heat.
    # Heat plant interim -> heat only.
    output_values: dict[str, dict] = {}
    for label in positive.index:
        label_series = core.ensure_full_year_series(
            core.get_label_timeseries(timeseries, label),
            export_base,
            export_final,
        ).clip(lower=0.0)
        if float(label_series.abs().sum()) <= 1e-12:
            continue
        output_values[label] = core.series_to_year_dict(label_series, export_base, export_final)

    if not output_values:
        print(
            f"{sector_title} ({economy}): no non-zero output series in export "
            "years; writing zero skeleton."
        )
        return core.build_zero_skeleton_record(
            economy, sector_title, process_name, output_labels,
            export_base, export_final,
        )

    input_series_map, zero_sum_labels = core.build_input_series_map(
        timeseries, list(negative.index), export_base, export_final,
    )
    if zero_sum_labels:
        core.log_dropped_input_fuels(economy, process_name, zero_sum_labels, export_base, export_final)
    if not input_series_map:
        print(
            f"[WARN] {sector_title} ({economy}): no valid feedstock series after "
            f"normalization; writing zero skeleton."
        )
        return core.build_zero_skeleton_record(
            economy, sector_title, process_name,
            list(output_values.keys()), export_base, export_final,
        )

    total_input_series = core.build_total_input_series(input_series_map, export_years)
    total_output_series = _build_total_output_series(
        timeseries, output_values.keys(), export_base, export_final
    )

    zero_loss = pd.Series({year: 0.0 for year in export_years}, dtype=float)
    efficiency_series = core.compute_efficiency_by_year(
        total_output_series, total_input_series, zero_loss
    )

    # Remap labels to canonical LEAP branch names (e.g. "Unallocated Solar" →
    # "Solar nonspecified") before keying feedstock_values / feedstock_shares.
    # If two source labels collapse to the same display name, sum their series.
    remapped_input_series: dict[str, "pd.Series"] = {}
    for label, series in input_series_map.items():
        display = _safe_power_interim_display_label(label)
        if not display or display in POWER_INTERIM_NEVER_OUTPUT_LABELS:
            continue
        if display in remapped_input_series:
            remapped_input_series[display] = remapped_input_series[display] + series
        else:
            remapped_input_series[display] = series

    feedstock_values = {
        label: core.series_to_year_dict(series, export_base, export_final)
        for label, series in remapped_input_series.items()
    }

    feedstock_shares: dict[str, dict] = {}
    for idx, (label, input_series) in enumerate(remapped_input_series.items()):
        share_series = core.build_input_share_series(
            input_series, total_input_series, fallback_to_one=(idx == 0),
        )
        feedstock_shares[label] = core.series_to_year_dict(share_series, export_base, export_final)

    output_summary = ", ".join(
        f"{core.map_code_label(lab, core.code_to_name_mapping)} ({positive[lab]:.2f})"
        for lab in positive.index
    )
    input_total = float(abs(negative.sum()))
    print(
        f"{sector_title} ({economy}): outputs [{output_summary}], "
        f"total input {input_total:.2f} PJ, {len(input_series_map)} feedstocks"
    )

    record = core.build_process_record(
        economy=economy,
        sector_title=sector_title,
        process_name=process_name,
        output_values=output_values,
        feedstock_values=feedstock_values,
        efficiency=core.series_to_year_dict(efficiency_series, export_base, export_final),
        auxiliary_ratios={},
        loss_values={},
        loss_total=0.0,
        feedstock_shares=feedstock_shares,
    )
    # Match transformation capacity exports: total output in PJ is equivalent
    # to Million GJ/year for Exogenous Capacity.
    total_output_by_year = core.series_to_year_dict(total_output_series, export_base, export_final)
    record["historical_production_by_year"] = dict(total_output_by_year)
    record["exogenous_capacity_by_year"] = dict(total_output_by_year)
    record["capacity_units"] = "Gigajoules/Year"
    record["capacity_scale"] = "Million"
    return record


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_electricity_heat_interim_rows(
    economies: Iterable[str] | None = None,
) -> list[dict]:
    """Build process records for all three interim modules across economies."""
    economy_list = list(economies or core.ECONOMIES_TO_ANALYZE)
    rows: list[dict] = []
    for economy in economy_list:
        print(f"\n==== Power interim modules ({economy}) ====")
        for module_name, module_cfg in INTERIM_MODULES.items():
            record = _build_interim_process_record(
                economy,
                sector_title=module_name,
                process_name=module_name,
                sub1sectors=module_cfg["sub1sectors"],
                esto_flows=module_cfg["esto_flows"],
                output_labels=module_cfg.get("output_labels"),
            )
            if record is not None:
                rows.append(record)
    return rows


def get_all_power_sector_feedstocks(
    economies: Iterable[str] | None = None,
    aggregate: bool = False,
) -> "pd.DataFrame":
    """Return a catalog of feedstock fuels consumed by each interim module across economies.

    Parameters
    ----------
    economies:
        Economies to scan. Defaults to core.ECONOMIES_TO_ANALYZE.
    aggregate:
        If False (default), returns one row per economy × module × fuel.
        If True, collapses to one row per module × fuel with total PJ and economy count.

    Columns (non-aggregated):
        economy, module, fuel_label, fuel_name, total_pj, in_ninth, in_esto

    Columns (aggregated):
        module, fuel_label, fuel_name, total_pj, economy_count, economies, in_ninth, in_esto

    in_ninth: fuel has non-zero consumption in the base/historical years (< PROJECTION_START_YEAR).
    in_esto:  fuel has non-zero consumption in ESTO projection years (>= PROJECTION_START_YEAR).
    """
    economy_list = list(economies or core.ECONOMIES_TO_ANALYZE)
    rows: list[dict] = []
    for economy in economy_list:
        for module_name, module_cfg in INTERIM_MODULES.items():
            module_rows, year_cols = _combine_module_source_rows(
                economy,
                module_cfg["sub1sectors"],
                module_cfg["esto_flows"],
            )
            if module_rows.empty:
                continue
            if not core.has_required_columns(
                module_rows,
                [["flows", "products"], ["flows", "subfuels", "fuels"], ["fuels", "subfuels"]],
                "feedstock catalog",
            ):
                continue
            totals_all, _ = core.summarize_fuel_totals(
                module_rows, year_cols, core.YEAR_START_FOR_ANALYSIS, allow_all_years_fallback=True
            )
            totals_proj, _ = core.summarize_fuel_totals(
                module_rows, year_cols, core.PROJECTION_START_YEAR, allow_all_years_fallback=False
            )
            feedstocks = totals_all[totals_all < 0]
            for label, value in feedstocks.items():
                label_str = str(label)
                proj_total = float(totals_proj.get(label, 0.0))
                all_total = float(value)
                rows.append({
                    "economy": economy,
                    "module": module_name,
                    "fuel_label": label_str,
                    "fuel_name": _safe_power_interim_display_label(label_str),
                    "total_pj": round(abs(all_total), 4),
                    "in_ninth": bool(abs(all_total - proj_total) > 1e-6),
                    "in_esto": bool(abs(proj_total) > 1e-6),
                })

    if not rows:
        return pd.DataFrame(
            columns=["economy", "module", "fuel_label", "fuel_name", "total_pj", "in_ninth", "in_esto"]
        )

    df = pd.DataFrame(rows)

    if aggregate:
        summary = (
            df.groupby(["module", "fuel_label", "fuel_name"])
            .agg(
                total_pj=("total_pj", "sum"),
                economy_count=("economy", "nunique"),
                economies=("economy", lambda x: ", ".join(sorted(set(x)))),
                in_ninth=("in_ninth", "max"),
                in_esto=("in_esto", "max"),
            )
            .reset_index()
            .sort_values(["module", "total_pj"], ascending=[True, False])
            .reset_index(drop=True)
        )
        return summary

    return df.sort_values(["module", "fuel_label", "economy"]).reset_index(drop=True)


def print_all_power_sector_feedstocks(
    economies: Iterable[str] | None = None,
) -> "pd.DataFrame":
    """Print and return the aggregated feedstock catalog, grouped by module."""
    df = get_all_power_sector_feedstocks(economies=economies, aggregate=True)
    if df.empty:
        print("No power sector feedstocks found.")
        return df
    for module_name in INTERIM_MODULES:
        module_df = df[df["module"] == module_name]
        if module_df.empty:
            continue
        leap_branch_prefix = (
            f"Transformation\\{module_name}\\Processes\\{module_name}\\Feedstock Fuels\\"
        )
        print(
            f"\n{'='*70}\n"
            f"{module_name} — {len(module_df)} feedstock fuel(s)\n"
            f"{'='*70}"
        )
        print(
            module_df[["fuel_label", "fuel_name", "total_pj", "economy_count", "economies"]]
            .to_string(index=False)
        )
        print(f"\nExpected LEAP branch prefix:\n  {leap_branch_prefix}<fuel_name>")
    return df


def build_interim_branch_catalog(
    economies: Iterable[str] | None = None,
) -> pd.DataFrame:
    """Build a branch-path catalog for build_aux_fuel_zero_rows.

    Scans all economies for feedstock fuels in each interim module and returns
    a dataframe with columns 'fuel_group' and 'branch_path' covering every
    fuel seen across any economy.  Passing this to save_transformation_export
    causes build_aux_fuel_zero_rows to zero out any fuel branch not written for
    a given economy, which clears stale LEAP values.
    """
    all_economies = list(economies or sorted(
        e for e in core.ninth_data["economy"].unique()
        if not str(e).startswith("00_")
    ))
    feedstock_df = get_all_power_sector_feedstocks(economies=all_economies, aggregate=False)

    catalog_rows: list[dict] = []
    for module_name in INTERIM_MODULES:
        module_fuels = feedstock_df[feedstock_df["module"] == module_name]
        seen_fuel_names: set[str] = set()
        for fuel_name in module_fuels["fuel_name"].unique():
            # fuel_name is already resolved through _safe_power_interim_display_label
            # in get_all_power_sector_feedstocks, so the same branch names are used here
            # (e.g. "Solar nonspecified" not "Unallocated Solar") and aggregate labels
            # like "Petroleum products" are already normalized before this check.
            if not fuel_name or fuel_name in POWER_INTERIM_NEVER_OUTPUT_LABELS:
                continue
            if fuel_name in seen_fuel_names:
                continue
            seen_fuel_names.add(fuel_name)
            branch_path = "\\".join([
                "Transformation",
                module_name,
                "Processes",
                module_name,
                "Feedstock Fuels",
                fuel_name,
            ])
            catalog_rows.append({"fuel_group": "Feedstock Fuels", "branch_path": branch_path})

    # Include every template feedstock leaf, even if no current economy has data
    # for it. These explicit zero rows clear stale LEAP values after a patch.
    template_df = pd.read_excel(
        POWER_INTERIM_REFERENCE_WORKBOOK_PATH,
        sheet_name=POWER_INTERIM_REFERENCE_SHEET_NAME,
        header=2,
        dtype=str,
    ).fillna("")
    existing_paths = {str(row["branch_path"]) for row in catalog_rows}
    for branch_path in template_df["Branch Path"].astype(str):
        if not any(
            branch_path.startswith(
                f"Transformation\\{module_name}\\Processes\\{module_name}\\Feedstock Fuels\\"
            )
            for module_name in INTERIM_MODULES
        ):
            continue
        if branch_path in existing_paths:
            continue
        catalog_rows.append(
            {"fuel_group": "Feedstock Fuels", "branch_path": branch_path}
        )
        existing_paths.add(branch_path)

    if not catalog_rows:
        return pd.DataFrame(columns=["fuel_group", "branch_path"])
    return pd.DataFrame(catalog_rows)


def format_export_filename(economy_label: str, scenarios: Sequence[str]) -> str:
    """Format the workbook filename for the interim export."""
    return leap_exports.build_workbook_filename(
        economy_label=economy_label,
        scenarios=scenarios,
        template=EXPORT_FILENAME_TEMPLATE,
        fallback_template=EXPORT_FILENAME_FALLBACK,
    )


def assemble_electricity_heat_interim_workbook(
    economies: Iterable[str] | None = None,
    scenarios: Sequence[str] | None = None,
    export_output_dir: Path | str | None = None,
    id_lookup_path: Path | str | None = EXPORT_ID_LOOKUP_PATH,
) -> list[Path]:
    """Build rows for all three interim modules, write one LEAP workbook per economy."""
    economy_list = list(economies or core.ECONOMIES_TO_ANALYZE)
    scenario_list = workflow_common.normalize_workflow_scenarios(scenarios, DEFAULT_SCENARIOS)
    output_dir_path = Path(export_output_dir or core.EXPORT_OUTPUT_DIR)
    output_dir_path.mkdir(parents=True, exist_ok=True)

    validate_power_interim_fuel_coverage(economies=economy_list, raise_on_mismatch=False)

    # Build catalog once from ALL APEC economies so every known feedstock fuel
    # is zero-cleared for economies that lack data for it.
    branch_catalog = build_interim_branch_catalog()
    in_scope = set(INTERIM_MODULES.keys())

    exported_paths: list[Path] = []
    for economy in economy_list:
        rows = build_electricity_heat_interim_rows(economies=[economy])
        if not rows:
            print(f"No electricity/heat interim rows for {economy}; skipping.")
            continue
        core.consolidate_transformation_output_rows(
            rows,
            include_output_series=core.INCLUDE_OUTPUT_SERIES_IN_LEAP_EXPORT,
            use_output_targets=False,
        )
        export_filename = format_export_filename(economy, scenario_list)
        export_path = core.save_transformation_export(
            rows,
            core.EXPORT_REGION,
            core.EXPORT_BASE_YEAR,
            core.EXPORT_FINAL_YEAR,
            core.code_to_name_mapping,
            str(output_dir_path),
            export_filename,
            core.EXPORT_MODEL_NAME,
            scenario_list,
            id_lookup_path=id_lookup_path,
            full_branch_catalog_df=branch_catalog,
            in_scope_sector_titles=in_scope,
        )
        if export_path:
            exported_paths.append(Path(export_path))
    return exported_paths


def find_electricity_heat_interim_workbook(
    directory: Path | str | None = None, filename: str | None = None
) -> Path:
    """Return a candidate interim workbook path."""
    directory_path = Path(directory or core.EXPORT_OUTPUT_DIR)
    return leap_exports.find_workbook(
        directory=directory_path,
        prefix=EXPORT_FILENAME_PREFIX,
        filename=filename,
    )


def list_export_scenarios(export_path: Path) -> list[str]:
    """Return the Scenario column values in declaration order."""
    return leap_exports.list_scenarios(export_path, sheet_name=SHEET_NAME)


def import_electricity_heat_interim_workbook_to_leap(
    export_directory: Path | str | None = None,
    filename: str | None = None,
    scenario_to_run: str | None = None,
    region: str | None = None,
    include_current_accounts: bool = False,
    create_branches: bool = True,
    fill_branches: bool = True,
    raise_on_missing_branch: bool = False,
) -> Path:
    """Connect to LEAP and import the interim workbook."""
    export_path = find_electricity_heat_interim_workbook(export_directory, filename)
    target_region = region or core.EXPORT_REGION
    return leap_api.import_workbook(
        export_path=export_path,
        sheet_name=SHEET_NAME,
        scenario=scenario_to_run,
        region=target_region,
        create_branches=create_branches,
        fill_branches=fill_branches,
        include_current_accounts=include_current_accounts,
        default_branch_type=(
            BRANCH_DEMAND_CATEGORY,
            BRANCH_DEMAND_CATEGORY,
            BRANCH_DEMAND_TECHNOLOGY,
        ),
        raise_on_missing_branch=raise_on_missing_branch,
    )


def run_electricity_heat_interim_export_and_import(
    economies: Iterable[str] | None = None,
    scenarios: Sequence[str] | None = None,
    include_leap_import: bool = False,
    import_scenario: str | Sequence[str] | None = None,
    region: str | None = None,
    create_branches: bool = True,
    fill_branches: bool = True,
    id_lookup_path: Path | str | None = EXPORT_ID_LOOKUP_PATH,
    **export_kwargs,
) -> list[Path]:
    """Run exports and optionally push the interim workbook into LEAP."""
    exports = assemble_electricity_heat_interim_workbook(
        economies=economies,
        scenarios=scenarios,
        export_output_dir=export_kwargs.get("export_output_dir"),
        id_lookup_path=export_kwargs.get("id_lookup_path", id_lookup_path),
    )
    if not exports or not include_leap_import:
        return exports
    scenario_list = workflow_common.normalize_workflow_scenarios(scenarios, DEFAULT_SCENARIOS)
    scenario_choices = workflow_common.resolve_import_scenarios(scenario_list, import_scenario)
    if get_analysis_input_write_mode() == "api" and not LEAP_API_AVAILABLE:
        print("[INFO] LEAP API unavailable; skipping interim branch creation/fill.")
        return exports
    first_workbook = True
    for workbook_path in exports:
        for index, scenario_choice in enumerate(scenario_choices):
            import_electricity_heat_interim_workbook_to_leap(
                export_directory=workbook_path.parent,
                filename=workbook_path.name,
                scenario_to_run=scenario_choice,
                region=region or core.EXPORT_REGION,
                include_current_accounts=(index == 0),
                create_branches=create_branches and first_workbook and index == 0,
                fill_branches=fill_branches,
            )
        first_workbook = False
    return exports


# ---------------------------------------------------------------------------
# Notebook / standalone runtime
# ---------------------------------------------------------------------------

NOTEBOOK_SCENARIOS = [ "Target", "Current Accounts"]#"Reference",
NOTEBOOK_INCLUDE_LEAP_IMPORT = (
    LEAP_API_AVAILABLE if get_analysis_input_write_mode() == "api" else True
)
def _default_notebook_economies() -> list[str]:
    """Return notebook economies without forcing data loading at import time."""
    if core.ninth_data is None or "economy" not in core.ninth_data.columns:
        return list(core.ECONOMIES_TO_ANALYZE)
    return sorted(
        e for e in core.ninth_data["economy"].unique()
        if not str(e).startswith("00_")
    )


NOTEBOOK_ECONOMIES = _default_notebook_economies()


def run_with_notebook_config() -> list[Path]:
    """Run the interim export/import with the editable notebook constants."""
    return run_electricity_heat_interim_export_and_import(
        economies=NOTEBOOK_ECONOMIES,
        scenarios=NOTEBOOK_SCENARIOS,
        include_leap_import=NOTEBOOK_INCLUDE_LEAP_IMPORT,
    )


if __name__ == "__main__":
    run_with_notebook_config()

    # ---------------------------------------------------------------------------
    # DEV: Feedstock catalog CSV export
    # Flip SAVE_FEEDSTOCK_CATALOG_CSV to True once to write the catalog, then
    # flip back to False.  Output files land in outputs/electricity_heat_interim/.
    # ---------------------------------------------------------------------------
    SAVE_FEEDSTOCK_CATALOG_CSV = False  # ← flip to True to regenerate

    if SAVE_FEEDSTOCK_CATALOG_CSV:
        _catalog_dir = REPO_ROOT / "outputs" / "electricity_heat_interim"
        _catalog_dir.mkdir(parents=True, exist_ok=True)

        _all_individual_economies = sorted(
            e for e in core.ninth_data["economy"].unique()
            if not str(e).startswith("00_")
        )

        _agg_path = _catalog_dir / "power_sector_feedstock_catalog_aggregated.csv"
        _agg_df = get_all_power_sector_feedstocks(economies=_all_individual_economies, aggregate=True)
        _agg_df.to_csv(_agg_path, index=False)
        print(f"[INFO] Saved aggregated feedstock catalog -> {_agg_path}")

        _detail_path = _catalog_dir / "power_sector_feedstock_catalog_by_economy.csv"
        _detail_df = get_all_power_sector_feedstocks(economies=_all_individual_economies, aggregate=False)
        _detail_df.to_csv(_detail_path, index=False)
        print(f"[INFO] Saved economy-level feedstock catalog -> {_detail_path}")

        print_all_power_sector_feedstocks()
#%%
