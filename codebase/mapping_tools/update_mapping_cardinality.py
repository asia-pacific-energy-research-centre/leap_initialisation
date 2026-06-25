#%%
"""
Update mapping cardinality columns in outlook_mappings_master.xlsx.

This workflow creates missing rollup-rule sheets, applies active rollup rules,
updates raw/effective cardinality columns on the maintained mapping sheets, and
writes QA tables for unresolved many-to-many relationships.
"""

#%%
from pathlib import Path
import shutil
import sys

import pandas as pd

#%%
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from codebase.mapping_tools.mapping_rollups import (  # noqa: E402
    MAPPING_SHEET_CONFIGS,
    active_mask,
    active_rollup_rules,
    build_all_effective_mappings,
    build_qa_tables,
    build_relationship_rows,
    ensure_individual_mapping_exception_sheet,
    ensure_rollup_sheets,
    read_individual_mapping_exceptions,
    read_rollup_rules,
    replace_sheet_with_dataframe,
    normalise_key,
    rollup_columns_for_sheet,
    value_matches,
)

#%%
MAPPING_WORKBOOK_PATH = Path(r"C:\Users\Work\github\leap_mappings\config\outlook_mappings_master.xlsx")
ESTO_ORIGINAL_DATA_PATH = REPO_ROOT / "data" / "00APEC_2025_low_with_subtotals.csv"
NINTH_ORIGINAL_DATA_PATH = REPO_ROOT / "data" / "merged_file_energy_ALL_20251106.csv"
NINTH_BALANCE_COVERAGE_DATA_PATH = REPO_ROOT / "data" / "merged_file_energy_00_APEC_20251106.csv"
LEAP_ORIGINAL_EXPORT_PATH = REPO_ROOT / "data" / "full model export.xlsx"
OUTPUT_DIR = REPO_ROOT / "results" / "mapping_relationships"
QA_DIR = OUTPUT_DIR / "qa"

RUN_UPDATE_MAPPING_CARDINALITY = True
FAIL_ON_MANY_TO_MANY_AFTER_ROLLUP = False
MAPPING_BALANCE_COVERAGE_TOLERANCE_PJ = 1e-6
MAPPING_BALANCE_COVERAGE_YEARS = ("2022",)

MAPPING_BALANCE_COVERAGE_SPECS = [
    {
        "check_name": "total_primary_supply",
        "esto_component_prefixes": ["01", "02", "03"],
        "esto_expected_prefixes": ["07"],
        "ninth_component_prefixes": ["01", "02", "03"],
        "ninth_expected_prefixes": ["07"],
    },
    {
        "check_name": "total_transformation",
        "esto_component_prefixes": ["09."],
        "esto_expected_prefixes": ["09."],
        "ninth_component_prefixes": ["09_"],
        "ninth_expected_prefixes": ["09_"],
    },
    {
        "check_name": "total_final_energy_consumption",
        "esto_component_prefixes": ["14", "15", "16"],
        "esto_expected_prefixes": ["13"],
        "ninth_component_prefixes": ["14", "15", "16"],
        "ninth_expected_prefixes": ["13"],
    },
    {
        "check_name": "international_transport",
        "esto_component_prefixes": ["04", "05"],
        "esto_expected_prefixes": ["04", "05"],
        "ninth_component_prefixes": ["04", "05"],
        "ninth_expected_prefixes": ["04", "05"],
    },
    {
        "check_name": "transfers",
        "esto_component_prefixes": ["08."],
        "esto_expected_prefixes": ["08."],
        "ninth_component_prefixes": ["08_"],
        "ninth_expected_prefixes": ["08_"],
    },
    {
        "check_name": "losses_and_own_use",
        "esto_component_prefixes": ["10.01.", "10.02"],
        "esto_expected_prefixes": ["10.01.", "10.02"],
        "ninth_component_prefixes": ["10_01_", "10_02"],
        "ninth_expected_prefixes": ["10_01_", "10_02"],
    },
    {
        "check_name": "non_energy_use",
        "esto_component_prefixes": ["17."],
        "esto_expected_prefixes": ["17."],
        "ninth_component_prefixes": ["17"],
        "ninth_expected_prefixes": ["17"],
    },
    {
        "check_name": "total_final_consumption",
        "esto_component_prefixes": ["13", "17."],
        "esto_expected_prefixes": ["12"],
        "ninth_component_prefixes": ["13", "17"],
        "ninth_expected_prefixes": ["12"],
    },
]

MAPPING_BALANCE_CATEGORY_COVERAGE_SPECS = [
    {
        "check_name": "category_01_production",
        "esto_component_prefixes": ["01"],
        "esto_expected_prefixes": ["01"],
        "ninth_component_prefixes": ["01"],
        "ninth_expected_prefixes": ["01"],
    },
    {
        "check_name": "category_02_imports",
        "esto_component_prefixes": ["02"],
        "esto_expected_prefixes": ["02"],
        "ninth_component_prefixes": ["02"],
        "ninth_expected_prefixes": ["02"],
    },
    {
        "check_name": "category_03_exports",
        "esto_component_prefixes": ["03"],
        "esto_expected_prefixes": ["03"],
        "ninth_component_prefixes": ["03"],
        "ninth_expected_prefixes": ["03"],
    },
    {
        "check_name": "category_04_marine_bunkers",
        "esto_component_prefixes": ["04"],
        "esto_expected_prefixes": ["04"],
        "ninth_component_prefixes": ["04"],
        "ninth_expected_prefixes": ["04"],
    },
    {
        "check_name": "category_05_aviation_bunkers",
        "esto_component_prefixes": ["05"],
        "esto_expected_prefixes": ["05"],
        "ninth_component_prefixes": ["05"],
        "ninth_expected_prefixes": ["05"],
    },
    {
        "check_name": "category_08_transfers",
        "esto_component_prefixes": ["08."],
        "esto_expected_prefixes": ["08."],
        "ninth_component_prefixes": ["08_"],
        "ninth_expected_prefixes": ["08_"],
    },
    {
        "check_name": "category_09_transformation",
        "esto_component_prefixes": ["09."],
        "esto_expected_prefixes": ["09."],
        "ninth_component_prefixes": ["09_"],
        "ninth_expected_prefixes": ["09_"],
    },
    {
        "check_name": "category_10_losses_own_use",
        "esto_component_prefixes": ["10.01.", "10.02"],
        "esto_expected_prefixes": ["10.01.", "10.02"],
        "ninth_component_prefixes": ["10_01_", "10_02"],
        "ninth_expected_prefixes": ["10_01_", "10_02"],
    },
    {
        "check_name": "category_13_total_final_energy",
        "esto_component_prefixes": ["13"],
        "esto_expected_prefixes": ["13"],
        "ninth_component_prefixes": ["13"],
        "ninth_expected_prefixes": ["13"],
    },
    {
        "check_name": "category_14_industry",
        "esto_component_prefixes": ["14"],
        "esto_expected_prefixes": ["14"],
        "ninth_component_prefixes": ["14"],
        "ninth_expected_prefixes": ["14"],
    },
    {
        "check_name": "category_15_transport",
        "esto_component_prefixes": ["15"],
        "esto_expected_prefixes": ["15"],
        "ninth_component_prefixes": ["15"],
        "ninth_expected_prefixes": ["15"],
    },
    {
        "check_name": "category_16_other",
        "esto_component_prefixes": ["16"],
        "esto_expected_prefixes": ["16"],
        "ninth_component_prefixes": ["16"],
        "ninth_expected_prefixes": ["16"],
    },
    {
        "check_name": "category_17_non_energy",
        "esto_component_prefixes": ["17."],
        "esto_expected_prefixes": ["17."],
        "ninth_component_prefixes": ["17"],
        "ninth_expected_prefixes": ["17"],
    },
]


#%%
def _load_esto_product_labels(path: Path) -> set[str]:
    """Return normalized ESTO product labels from the source ESTO table."""
    if not path.exists():
        print(f"[WARN] ESTO source data not found, skipping label presence check: {path}")
        return set()
    products = pd.read_csv(path, usecols=["products"])["products"].dropna().astype(str).str.strip()
    return {normalise_key(value) for value in products if str(value).strip()}


def _load_ninth_fuel_labels(path: Path) -> set[str]:
    """Return normalized 9th fuel labels from fuels and subfuels columns."""
    if not path.exists():
        print(f"[WARN] 9th source data not found, skipping label presence check: {path}")
        return set()
    columns = pd.read_csv(path, nrows=0).columns.tolist()
    usecols = [column for column in ["fuels", "subfuels"] if column in columns]
    if not usecols:
        return set()
    data = pd.read_csv(path, usecols=usecols, low_memory=False).fillna("")
    labels: set[str] = set()
    for column in usecols:
        for value in data[column].astype(str).str.strip().drop_duplicates():
            if value and value.lower() != "x":
                labels.add(normalise_key(value))
    return labels


def _load_leap_fuel_labels(path: Path) -> set[str]:
    """Return normalized LEAP branch leaf labels from the model export workbook."""
    if not path.exists():
        print(f"[WARN] LEAP model export not found, skipping raw LEAP label presence check: {path}")
        return set()
    try:
        data = pd.read_excel(path, sheet_name="Export", header=2, usecols=["Branch Path"], dtype=object).fillna("")
    except Exception as exc:
        print(f"[WARN] Could not read LEAP model export labels from {path}: {exc}")
        return set()
    labels: set[str] = set()
    for path_value in data["Branch Path"].astype(str).str.strip().drop_duplicates():
        parts = [part.strip() for part in path_value.replace("/", "\\").split("\\") if part.strip()]
        if parts:
            labels.add(normalise_key(parts[-1]))
    return labels


def _bool_from_source(value: object) -> bool:
    """Interpret common boolean/subtotal flag values from source files."""
    text = str(value or "").strip().lower()
    return text in {"1", "true", "t", "yes", "y"}


def _code_matches_any_prefix(value: object, prefixes: list[str]) -> bool:
    """Return True when a balance label starts with any configured code prefix."""
    text = str(value or "").strip().lower()
    return any(text.startswith(prefix.lower()) for prefix in prefixes)


def _product_is_total(value: object) -> bool:
    """Return True for Total fuel/product labels."""
    text = " ".join(str(value or "").strip().lower().replace("_", " ").split())
    return text == "total" or text.endswith(" total") or text in {"19 total", "19_total"}


def _join_limited(values: pd.Series, limit: int = 30) -> str:
    """Join unique category labels with a cap to keep QA rows readable."""
    unique = sorted({str(value).strip() for value in values if str(value).strip()})
    shown = unique[:limit]
    suffix = f"|...(+{len(unique) - limit})" if len(unique) > limit else ""
    return "|".join(shown) + suffix


def _top_level_balance_category(dataset: str, value: object) -> str:
    """Collapse detailed balance labels to the top-level balance category."""
    text = str(value or "").strip()
    key = text.lower()
    if not text:
        return ""
    if dataset == "ESTO":
        prefix_map = {
            "01": "01 Production",
            "02": "02 Imports",
            "03": "03 Exports",
            "04": "04 International marine bunkers",
            "05": "05 International aviation bunkers",
            "06": "06 Stock changes",
            "07": "07 Total primary energy supply",
            "08": "08 Transfers",
            "09": "09 Transformation",
            "10": "10 Losses & own use",
            "11": "11 Statistical discrepancy",
            "12": "12 Total final consumption",
            "13": "13 Total final energy consumption",
            "14": "14 Industry sector",
            "15": "15 Transport sector",
            "16": "16 Other sector",
            "17": "17 Non-energy use",
        }
        code = key.split()[0].split(".")[0]
        return prefix_map.get(code, text)
    prefix_map = {
        "01": "01_production",
        "02": "02_imports",
        "03": "03_exports",
        "04": "04_international_marine_bunkers",
        "05": "05_international_aviation_bunkers",
        "06": "06_stock_changes",
        "07": "07_total_primary_energy_supply",
        "08": "08_transfers",
        "09": "09_total_transformation_sector",
        "10": "10_losses_and_own_use",
        "11": "11_statistical_discrepancy",
        "12": "12_total_final_consumption",
        "13": "13_total_final_energy_consumption",
        "14": "14_industry_sector",
        "15": "15_transport_sector",
        "16": "16_other_sector",
        "17": "17_nonenergy_use",
    }
    code = key.split("_", 1)[0]
    return prefix_map.get(code, text)


def _top_level_categories(dataset: str, values: pd.Series) -> list[str]:
    """Return sorted top-level category labels for source rows used in a check."""
    return sorted(
        {
            _top_level_balance_category(dataset, value)
            for value in values
            if _top_level_balance_category(dataset, value)
        }
    )


def _detail_categories(values: pd.Series) -> list[str]:
    """Return sorted detailed category labels for source rows used in a check."""
    return sorted({str(value).strip() for value in values if str(value).strip()})


def _leading_code(value: object) -> str:
    """Return the leading coded part of an ESTO label such as '07.01 Motor gasoline'."""
    text = str(value or "").strip()
    if not text:
        return ""
    return text.split(maxsplit=1)[0]


def _infer_esto_product_subtotal_flags(products: pd.Series) -> pd.Series:
    """Infer ESTO product subtotal rows from parent product codes and total labels."""
    product_codes = products.map(_leading_code)
    unique_codes = {code for code in product_codes if code}

    def is_product_subtotal(product: object) -> bool:
        text = str(product or "").strip()
        code = _leading_code(text)
        if not text or not code:
            return False
        if "total" in text.lower():
            return True
        return any(other != code and other.startswith(f"{code}.") for other in unique_codes)

    return products.map(is_product_subtotal)


def _load_esto_subtotal_lookup(path: Path) -> dict[tuple[str, str], bool]:
    """Return ESTO flow/product pair subtotal flags."""
    if not path.exists():
        print(f"[WARN] ESTO source data not found, skipping subtotal alignment check: {path}")
        return {}
    columns = pd.read_csv(path, nrows=0).columns.tolist()
    required = ["flows", "products", "is_subtotal"]
    if any(column not in columns for column in required):
        print(f"[WARN] ESTO source data missing {required}, skipping subtotal alignment check: {path}")
        return {}
    data = pd.read_csv(path, usecols=required).fillna("")
    lookup: dict[tuple[str, str], bool] = {}
    for row in data.itertuples(index=False):
        flow = str(getattr(row, "flows", "")).strip()
        product = str(getattr(row, "products", "")).strip()
        if not flow or not product:
            continue
        key = (normalise_key(flow), normalise_key(product))
        lookup[key] = lookup.get(key, False) or _bool_from_source(getattr(row, "is_subtotal", ""))
    return lookup


def _last_non_x(values: list[object]) -> str:
    """Return the deepest nonblank, non-x hierarchy label."""
    chosen = ""
    for value in values:
        text = str(value or "").strip()
        if text and text.lower() != "x":
            chosen = text
    return chosen


def _load_ninth_subtotal_lookup(path: Path) -> dict[tuple[str, str], bool]:
    """Return 9th sector/fuel pair subtotal flags, including parent hierarchy labels."""
    if not path.exists():
        print(f"[WARN] 9th source data not found, skipping subtotal alignment check: {path}")
        return {}
    columns = pd.read_csv(path, nrows=0).columns.tolist()
    sector_cols = [column for column in ["sectors", "sub1sectors", "sub2sectors", "sub3sectors", "sub4sectors"] if column in columns]
    fuel_cols = [column for column in ["fuels", "subfuels"] if column in columns]
    subtotal_cols = [column for column in ["subtotal_layout", "subtotal_results"] if column in columns]
    usecols = [*sector_cols, *fuel_cols, *subtotal_cols]
    if not sector_cols or not fuel_cols:
        return {}
    data = pd.read_csv(path, usecols=usecols, low_memory=False).fillna("")
    lookup: dict[tuple[str, str], bool] = {}
    for row in data.itertuples(index=False):
        row_dict = row._asdict()
        sectors = [str(row_dict.get(column, "")).strip() for column in sector_cols]
        fuels = [str(row_dict.get(column, "")).strip() for column in fuel_cols]
        deepest_sector = _last_non_x(sectors)
        deepest_fuel = _last_non_x(fuels)
        subtotal_flag = any(_bool_from_source(row_dict.get(column, "")) for column in subtotal_cols)
        for sector in sectors:
            if not sector or sector.lower() == "x":
                continue
            for fuel in fuels:
                if not fuel or fuel.lower() == "x":
                    continue
                hierarchy_parent = sector != deepest_sector or fuel != deepest_fuel
                key = (normalise_key(sector), normalise_key(fuel))
                lookup[key] = lookup.get(key, False) or subtotal_flag or hierarchy_parent
    return lookup


def _load_leap_subtotal_lookup_from_effective_tables(
    effective_tables: dict[str, pd.DataFrame],
) -> dict[tuple[str, str], bool]:
    """Infer LEAP pair subtotal flags from the active mapping hierarchy."""
    leap_pairs: list[tuple[str, str]] = []
    for table in effective_tables.values():
        if table.empty:
            continue
        work = table.copy()
        for flow_col, product_col, system_col in [
            ("rolled_source_flow", "rolled_source_product", "source_system"),
            ("rolled_target_flow", "rolled_target_product", "target_system"),
        ]:
            for column in [flow_col, product_col, system_col]:
                if column not in work.columns:
                    work[column] = ""
                work[column] = work[column].fillna("").astype(str).str.strip()
            mask = (
                active_mask(work)
                & work[system_col].eq("LEAP")
                & work[flow_col].ne("")
                & work[product_col].ne("")
            )
            leap_pairs.extend(
                (str(flow).strip(), str(product).strip())
                for flow, product in work.loc[mask, [flow_col, product_col]]
                .drop_duplicates()
                .itertuples(index=False, name=None)
            )
    path_values = {flow for flow, _product in leap_pairs}
    lookup: dict[tuple[str, str], bool] = {}
    for flow, product in leap_pairs:
        normalized_flow = flow.strip().replace("\\", "/")
        prefix = f"{normalized_flow}/"
        flow_has_descendant = any(
            other != flow and other.strip().replace("\\", "/").startswith(prefix)
            for other in path_values
        )
        product_key = normalise_key(product)
        product_is_subtotal = product_key == "total" or product_key.startswith("total ")
        lookup[(normalise_key(flow), product_key)] = flow_has_descendant or product_is_subtotal
    return lookup


def load_original_label_sets(
    esto_data_path: Path = ESTO_ORIGINAL_DATA_PATH,
    ninth_data_path: Path = NINTH_ORIGINAL_DATA_PATH,
    leap_export_path: Path = LEAP_ORIGINAL_EXPORT_PATH,
) -> dict[str, set[str]]:
    """Load normalized source labels used by original-label-presence QA."""
    return {
        "esto_product": _load_esto_product_labels(esto_data_path),
        "ninth_fuel": _load_ninth_fuel_labels(ninth_data_path),
        "raw_leap_fuel_name": _load_leap_fuel_labels(leap_export_path),
    }


def load_subtotal_lookups(
    effective_tables: dict[str, pd.DataFrame],
    esto_data_path: Path = ESTO_ORIGINAL_DATA_PATH,
    ninth_data_path: Path = NINTH_ORIGINAL_DATA_PATH,
) -> dict[str, dict[tuple[str, str], bool]]:
    """Load pair-level subtotal flags for subtotal-alignment QA."""
    return {
        "LEAP": _load_leap_subtotal_lookup_from_effective_tables(effective_tables),
        "NINTH": _load_ninth_subtotal_lookup(ninth_data_path),
        "ESTO": _load_esto_subtotal_lookup(esto_data_path),
    }


def _year_columns(frame: pd.DataFrame, selected_years: tuple[str, ...] | None = None) -> list[str]:
    """Return 4-digit year columns."""
    years = [column for column in frame.columns if str(column).strip().isdigit() and len(str(column).strip()) == 4]
    if selected_years is None:
        return years
    selected = {str(year) for year in selected_years}
    return [year for year in years if str(year) in selected]


def _active_pair_set(
    effective_tables: dict[str, pd.DataFrame],
    *,
    use_case: str,
    system: str,
) -> set[tuple[str, str]]:
    """Return normalized active flow/product pairs for one use case and source/target system."""
    table = effective_tables.get(use_case, pd.DataFrame()).copy()
    if table.empty:
        return set()
    if system == "source":
        flow_col = "rolled_source_flow"
        product_col = "rolled_source_product"
    else:
        flow_col = "rolled_target_flow"
        product_col = "rolled_target_product"
    for column in [flow_col, product_col]:
        if column not in table.columns:
            table[column] = ""
        table[column] = table[column].fillna("").astype(str).str.strip()
    mask = active_mask(table) & table[flow_col].ne("") & table[product_col].ne("")
    return {
        (normalise_key(flow), normalise_key(product))
        for flow, product in table.loc[mask, [flow_col, product_col]].drop_duplicates().itertuples(index=False, name=None)
    }


def _mapping_pair_sets_for_balance_coverage(
    effective_tables: dict[str, pd.DataFrame],
) -> list[dict[str, object]]:
    """Return dataset-specific mapping pair sets to check for balance coverage."""
    return [
        {
            "dataset": "ESTO",
            "mapping_set": "leap_combined_esto",
            "rollup_sheet": "esto_rollup_rules",
            "rollup_context": "leap_to_esto",
            "pairs": _active_pair_set(
                effective_tables,
                use_case="leap_to_esto_balance_conversion",
                system="target",
            ),
        },
        {
            "dataset": "NINTH",
            "mapping_set": "leap_combined_ninth",
            "rollup_sheet": "ninth_rollup_rules",
            "rollup_context": "leap_to_ninth",
            "pairs": _active_pair_set(
                effective_tables,
                use_case="leap_to_ninth_comparison",
                system="target",
            ),
        },
        {
            "dataset": "NINTH",
            "mapping_set": "ninth_pairs_to_esto_pairs_source_ninth",
            "rollup_sheet": "ninth_rollup_rules",
            "rollup_context": "ninth_to_esto",
            "pairs": _active_pair_set(
                effective_tables,
                use_case="ninth_to_esto_balance_conversion",
                system="source",
            ),
        },
        {
            "dataset": "ESTO",
            "mapping_set": "ninth_pairs_to_esto_pairs_target_esto",
            "rollup_sheet": "esto_rollup_rules",
            "rollup_context": "ninth_to_esto",
            "pairs": _active_pair_set(
                effective_tables,
                use_case="ninth_to_esto_balance_conversion",
                system="target",
            ),
        },
    ]


def _coverage_rollup_projection_lookup(
    *,
    rollup_rules: dict[str, pd.DataFrame] | None,
    rollup_sheet_name: str,
    rollup_context: str,
    mapped_pairs: set[tuple[str, str]],
) -> dict[tuple[str, str], dict[str, object]]:
    """
    Build raw->rolled pair replacements for coverage QA.

    A replacement is only allowed when the rolled pair is present in the active
    mapped pair set. This prevents configured-but-unused rollups from hiding
    real missing source categories.
    """
    if not rollup_rules or not rollup_sheet_name or rollup_sheet_name not in rollup_rules:
        return {}
    rules = active_rollup_rules(rollup_rules.get(rollup_sheet_name, pd.DataFrame()), rollup_context)
    if rules.empty:
        return {}
    columns = rollup_columns_for_sheet(rollup_sheet_name)
    lookup: dict[tuple[str, str], dict[str, object]] = {}
    for _, rule in rules.iterrows():
        input_flow = str(rule.get(columns["input_flow"], "") or "").strip()
        input_product = str(rule.get(columns["input_product"], "") or "").strip()
        rolled_flow = str(rule.get(columns["rolled_flow"], "") or "").strip() or input_flow
        rolled_product = str(rule.get(columns["rolled_product"], "") or "").strip() or input_product
        rolled_key = (normalise_key(rolled_flow), normalise_key(rolled_product))
        if rolled_key not in mapped_pairs:
            continue
        lookup[(normalise_key(input_flow), normalise_key(input_product))] = {
            "pair": rolled_key,
            "flow_label": rolled_flow,
            "product_label": rolled_product,
        }
    return lookup


def _project_pair_for_coverage(
    *,
    flow: object,
    product: object,
    projection_lookup: dict[tuple[str, str], dict[str, object]],
) -> tuple[str, str]:
    """Return rolled replacement pair for coverage, or the raw pair."""
    raw_key = (normalise_key(flow), normalise_key(product))
    # Exact pair first, then flow-only wildcard rules.
    if raw_key in projection_lookup:
        return projection_lookup[raw_key]["pair"]  # type: ignore[return-value]
    wildcard_key = (normalise_key(flow), "")
    if wildcard_key in projection_lookup:
        rolled_flow, rolled_product = projection_lookup[wildcard_key]["pair"]  # type: ignore[index]
        return (rolled_flow, normalise_key(product) if not rolled_product else rolled_product)
    return raw_key


def _project_flow_label_for_coverage(
    *,
    flow: object,
    product: object,
    projection_lookup: dict[tuple[str, str], dict[str, object]],
) -> str:
    """Return effective flow label after coverage-only rollup projection."""
    raw_key = (normalise_key(flow), normalise_key(product))
    if raw_key in projection_lookup:
        return str(projection_lookup[raw_key].get("flow_label", "") or flow).strip()
    wildcard_key = (normalise_key(flow), "")
    if wildcard_key in projection_lookup:
        return str(projection_lookup[wildcard_key].get("flow_label", "") or flow).strip()
    return str(flow or "").strip()


def _row_pairs_after_coverage_rollup(
    *,
    sectors: list[str],
    fuels: list[str],
    projection_lookup: dict[tuple[str, str], dict[str, object]],
) -> set[tuple[str, str]]:
    """Return source row hierarchy pairs after coverage-only rollup projection."""
    out: set[tuple[str, str]] = set()
    for sector in sectors:
        for fuel in fuels:
            out.add(
                _project_pair_for_coverage(
                    flow=sector,
                    product=fuel,
                    projection_lookup=projection_lookup,
                )
            )
    return out


def _row_flow_labels_after_coverage_rollup(
    *,
    sectors: list[str],
    fuels: list[str],
    projection_lookup: dict[tuple[str, str], dict[str, object]],
) -> set[str]:
    """Return effective flow labels after coverage-only rollup projection."""
    out: set[str] = set()
    for sector in sectors:
        for fuel in fuels:
            out.add(
                _project_flow_label_for_coverage(
                    flow=sector,
                    product=fuel,
                    projection_lookup=projection_lookup,
                )
            )
    return {value for value in out if value}


def _summarise_balance_coverage_groups(
    detail: pd.DataFrame,
    *,
    dataset: str,
    mapping_set: str,
    check_name: str,
    check_level: str,
    component_prefixes: list[str],
    expected_prefixes: list[str],
    mapped_covered_categories: list[str],
    source_expected_categories: list[str],
    mapped_covered_detail_categories: list[str],
    missing_detail_categories: list[str],
    tolerance_pj: float,
) -> dict[str, object]:
    """Summarize group-level coverage differences into one QA row."""
    if detail.empty:
        return {
            "dataset": dataset,
            "mapping_set": mapping_set,
            "check_name": check_name,
            "check_level": check_level,
            "status": "missing_source_rows",
            "failed_group_count": 0,
            "max_abs_difference_pj": pd.NA,
            "scenario_with_max_difference": "",
            "source_expected_total_pj": pd.NA,
            "mapped_covered_total_pj": pd.NA,
            "difference_percent": pd.NA,
            "source_expected_categories": _join_limited(pd.Series(source_expected_categories, dtype="object")),
            "mapped_covered_categories": _join_limited(pd.Series(mapped_covered_categories, dtype="object")),
            "mapped_covered_detail_categories": _join_limited(pd.Series(mapped_covered_detail_categories, dtype="object")),
            "missing_detail_categories": _join_limited(pd.Series(missing_detail_categories, dtype="object")),
            "details": "No source rows found for this coverage check.",
        }
    work = detail.copy()
    work["difference_pj"] = pd.to_numeric(work["mapped_component_total_pj"], errors="coerce").fillna(0.0) - pd.to_numeric(work["expected_total_pj"], errors="coerce").fillna(0.0)
    work["abs_difference_pj"] = work["difference_pj"].abs()
    failures = work[work["abs_difference_pj"].gt(tolerance_pj)].copy()
    worst = work.sort_values("abs_difference_pj", ascending=False).iloc[0]
    expected_total = float(worst["expected_total_pj"])
    difference_pj = float(worst["difference_pj"])
    difference_percent = pd.NA if abs(expected_total) <= tolerance_pj else (difference_pj / expected_total) * 100.0
    status = "pass" if failures.empty else "fail"
    return {
        "dataset": dataset,
        "mapping_set": mapping_set,
        "check_name": check_name,
        "check_level": check_level,
        "status": status,
        "failed_group_count": int(len(failures)),
        "max_abs_difference_pj": float(worst["abs_difference_pj"]),
        "scenario_with_max_difference": str(worst.get("scenario", "")),
        "source_expected_total_pj": expected_total,
        "mapped_covered_total_pj": float(worst["mapped_component_total_pj"]),
        "difference_percent": difference_percent,
        "source_expected_categories": _join_limited(pd.Series(source_expected_categories, dtype="object")),
        "mapped_covered_categories": _join_limited(pd.Series(mapped_covered_categories, dtype="object")),
        "mapped_covered_detail_categories": _join_limited(pd.Series(mapped_covered_detail_categories, dtype="object")),
        "missing_detail_categories": _join_limited(pd.Series(missing_detail_categories, dtype="object")),
        "details": (
            "Mapped component rows match source direct total rows within tolerance."
            if status == "pass"
            else "Mapped component rows do not add up to source direct total rows for at least one economy/scenario/year."
        ),
    }


def _build_esto_mapping_balance_coverage(
    source_path: Path,
    mapping_pair_sets: list[dict[str, object]],
    *,
    tolerance_pj: float,
    selected_years: tuple[str, ...] | None,
    rollup_rules: dict[str, pd.DataFrame] | None,
) -> list[dict[str, object]]:
    """Build ESTO mapping coverage summary rows."""
    if not source_path.exists():
        return []
    source_sets = [item for item in mapping_pair_sets if item["dataset"] == "ESTO"]
    if not source_sets:
        return []
    header = pd.read_csv(source_path, nrows=0)
    years = _year_columns(header, selected_years)
    if not years:
        return []
    optional_cols = [column for column in ["is_subtotal"] if column in header.columns]
    usecols = ["economy", "flows", "products", *optional_cols, *years]
    data = pd.read_csv(source_path, usecols=usecols).fillna("")
    for column in ["economy", "flows", "products"]:
        data[column] = data[column].astype(str).str.strip()
    data["_pair_key"] = list(zip(data["flows"].map(normalise_key), data["products"].map(normalise_key)))
    data["_is_flow_subtotal"] = data["is_subtotal"].map(_bool_from_source) if "is_subtotal" in data.columns else False
    data["_is_product_subtotal"] = _infer_esto_product_subtotal_flags(data["products"])
    data["_is_subtotal"] = data["_is_flow_subtotal"].astype(bool) | data["_is_product_subtotal"].astype(bool)
    year_long = data.melt(
        id_vars=[
            "economy",
            "flows",
            "products",
            "_pair_key",
            "_is_flow_subtotal",
            "_is_product_subtotal",
            "_is_subtotal",
        ],
        value_vars=years,
        var_name="year",
        value_name="value",
    )
    year_long["year"] = pd.to_numeric(year_long["year"], errors="coerce").astype("Int64")
    year_long["value"] = pd.to_numeric(year_long["value"], errors="coerce").fillna(0.0)
    year_long["economy"] = "00_APEC"
    year_long["scenario"] = ""
    rows: list[dict[str, object]] = []
    for mapping_set in source_sets:
        mapped_pairs = set(mapping_set["pairs"])
        projection_lookup = _coverage_rollup_projection_lookup(
            rollup_rules=rollup_rules,
            rollup_sheet_name=str(mapping_set.get("rollup_sheet", "")),
            rollup_context=str(mapping_set.get("rollup_context", "")),
            mapped_pairs=mapped_pairs,
        )
        year_long["_coverage_pair_key"] = [
            _project_pair_for_coverage(
                flow=flow,
                product=product,
                projection_lookup=projection_lookup,
            )
            for flow, product in year_long[["flows", "products"]].itertuples(index=False, name=None)
        ]
        year_long["_coverage_flow_label"] = [
            _project_flow_label_for_coverage(
                flow=flow,
                product=product,
                projection_lookup=projection_lookup,
            )
            for flow, product in year_long[["flows", "products"]].itertuples(index=False, name=None)
        ]
        specs = [
            *[(spec, "aggregate") for spec in MAPPING_BALANCE_COVERAGE_SPECS],
            *[(spec, "category") for spec in MAPPING_BALANCE_CATEGORY_COVERAGE_SPECS],
        ]
        for spec, check_level in specs:
            component_source = year_long[
                year_long["flows"].map(lambda value: _code_matches_any_prefix(value, spec["esto_component_prefixes"]))
                & ~year_long["_is_subtotal"].astype(bool)
            ].copy()
            component = component_source[component_source["_coverage_pair_key"].isin(mapped_pairs)].copy()
            total = year_long[
                year_long["flows"].map(lambda value: _code_matches_any_prefix(value, spec["esto_expected_prefixes"]))
                & ~year_long["_is_subtotal"].astype(bool)
            ].copy()
            if total.empty:
                total = year_long[
                    year_long["flows"].map(lambda value: _code_matches_any_prefix(value, spec["esto_expected_prefixes"]))
                    & ~year_long["_is_flow_subtotal"].astype(bool)
                ].copy()
            mapped_covered_categories = _top_level_categories("ESTO", component["_coverage_flow_label"])
            source_expected_categories = _top_level_categories("ESTO", total["_coverage_flow_label"])
            mapped_covered_detail_categories = _detail_categories(component["_coverage_flow_label"])
            source_component_detail_categories = _detail_categories(component_source["_coverage_flow_label"])
            missing_detail_categories = sorted(
                set(source_component_detail_categories) - set(mapped_covered_detail_categories)
            )
            component_grouped = component.groupby(["economy", "scenario", "year"], as_index=False)["value"].sum().rename(columns={"value": "mapped_component_total_pj"})
            total_grouped = total.groupby(["economy", "scenario", "year"], as_index=False)["value"].sum().rename(columns={"value": "expected_total_pj"})
            detail = total_grouped.merge(component_grouped, on=["economy", "scenario", "year"], how="left")
            detail["mapped_component_total_pj"] = pd.to_numeric(detail.get("mapped_component_total_pj", 0.0), errors="coerce").fillna(0.0)
            rows.append(
                _summarise_balance_coverage_groups(
                    detail,
                    dataset="ESTO",
                    mapping_set=str(mapping_set["mapping_set"]),
                    check_name=str(spec["check_name"]),
                    check_level=check_level,
                    component_prefixes=list(spec["esto_component_prefixes"]),
                    expected_prefixes=list(spec["esto_expected_prefixes"]),
                    mapped_covered_categories=mapped_covered_categories,
                    source_expected_categories=source_expected_categories,
                    mapped_covered_detail_categories=mapped_covered_detail_categories,
                    missing_detail_categories=missing_detail_categories,
                    tolerance_pj=tolerance_pj,
                )
            )
    return rows


def _build_ninth_mapping_balance_coverage(
    source_path: Path,
    mapping_pair_sets: list[dict[str, object]],
    *,
    tolerance_pj: float,
    selected_years: tuple[str, ...] | None,
    rollup_rules: dict[str, pd.DataFrame] | None,
) -> list[dict[str, object]]:
    """Build 9th mapping coverage summary rows."""
    if not source_path.exists():
        return []
    source_sets = [item for item in mapping_pair_sets if item["dataset"] == "NINTH"]
    if not source_sets:
        return []
    header = pd.read_csv(source_path, nrows=0)
    years = _year_columns(header, selected_years)
    if not years:
        return []
    sector_cols = [column for column in ["sectors", "sub1sectors", "sub2sectors", "sub3sectors", "sub4sectors"] if column in header.columns]
    fuel_cols = [column for column in ["fuels", "subfuels"] if column in header.columns]
    subtotal_cols = [column for column in ["subtotal_layout", "subtotal_results"] if column in header.columns]
    usecols = ["economy", "scenarios", *sector_cols, *fuel_cols, *subtotal_cols, *years]
    data = pd.read_csv(source_path, usecols=usecols, low_memory=False).fillna("")
    data = data.rename(columns={"scenarios": "scenario"})
    for column in ["economy", "scenario", *sector_cols, *fuel_cols]:
        data[column] = data[column].astype(str).str.strip()
    data["_deepest_sector"] = data[sector_cols].apply(lambda row: _last_non_x(row.tolist()), axis=1)
    data["_deepest_fuel"] = data[fuel_cols].apply(lambda row: _last_non_x(row.tolist()), axis=1)
    if subtotal_cols:
        data["_is_subtotal"] = data[subtotal_cols].apply(
            lambda row: any(_bool_from_source(value) for value in row.tolist()),
            axis=1,
        )
    else:
        data["_is_subtotal"] = False

    row_sector_fuel_values: list[tuple[list[str], list[str]]] = []
    for row in data[[*sector_cols, *fuel_cols]].itertuples(index=False, name=None):
        row_dict = dict(zip([*sector_cols, *fuel_cols], row))
        sectors = [str(row_dict.get(column, "")).strip() for column in sector_cols if str(row_dict.get(column, "")).strip().lower() not in {"", "x"}]
        fuels = [str(row_dict.get(column, "")).strip() for column in fuel_cols if str(row_dict.get(column, "")).strip().lower() not in {"", "x"}]
        row_sector_fuel_values.append((sectors, fuels))
    data["_row_sector_fuel_values"] = row_sector_fuel_values

    year_long = data.melt(
        id_vars=["economy", "scenario", "_deepest_sector", "_deepest_fuel", "_row_sector_fuel_values", "_is_subtotal"],
        value_vars=years,
        var_name="year",
        value_name="value",
    )
    year_long["year"] = pd.to_numeric(year_long["year"], errors="coerce").astype("Int64")
    year_long["value"] = pd.to_numeric(year_long["value"], errors="coerce").fillna(0.0)
    rows: list[dict[str, object]] = []
    for mapping_set in source_sets:
        mapped_pairs = set(mapping_set["pairs"])
        projection_lookup = _coverage_rollup_projection_lookup(
            rollup_rules=rollup_rules,
            rollup_sheet_name=str(mapping_set.get("rollup_sheet", "")),
            rollup_context=str(mapping_set.get("rollup_context", "")),
            mapped_pairs=mapped_pairs,
        )
        year_long["_row_pairs"] = year_long["_row_sector_fuel_values"].map(
            lambda values: _row_pairs_after_coverage_rollup(
                sectors=values[0],
                fuels=values[1],
                projection_lookup=projection_lookup,
            )
        )
        year_long["_coverage_sector_labels"] = year_long["_row_sector_fuel_values"].map(
            lambda values: _row_flow_labels_after_coverage_rollup(
                sectors=values[0],
                fuels=values[1],
                projection_lookup=projection_lookup,
            )
        )
        specs = [
            *[(spec, "aggregate") for spec in MAPPING_BALANCE_COVERAGE_SPECS],
            *[(spec, "category") for spec in MAPPING_BALANCE_CATEGORY_COVERAGE_SPECS],
        ]
        for spec, check_level in specs:
            component_source = year_long[
                year_long["_deepest_sector"].map(lambda value: _code_matches_any_prefix(value, spec["ninth_component_prefixes"]))
                & ~year_long["_is_subtotal"].astype(bool)
            ].copy()
            mapped_component_mask = component_source["_row_pairs"].map(
                lambda row_pairs: bool(row_pairs & mapped_pairs)
            ).astype(bool)
            component = component_source[mapped_component_mask].copy()
            total = year_long[
                year_long["_deepest_sector"].map(lambda value: _code_matches_any_prefix(value, spec["ninth_expected_prefixes"]))
                & ~year_long["_is_subtotal"].astype(bool)
            ].copy()
            mapped_covered_labels = pd.Series(
                sorted({label for labels in component["_coverage_sector_labels"] for label in labels}),
                dtype="object",
            )
            source_expected_labels = pd.Series(
                sorted({label for labels in total["_coverage_sector_labels"] for label in labels}),
                dtype="object",
            )
            source_component_labels = pd.Series(
                sorted({label for labels in component_source["_coverage_sector_labels"] for label in labels}),
                dtype="object",
            )
            mapped_covered_categories = _top_level_categories("NINTH", mapped_covered_labels)
            source_expected_categories = _top_level_categories("NINTH", source_expected_labels)
            mapped_covered_detail_categories = _detail_categories(mapped_covered_labels)
            source_component_detail_categories = _detail_categories(source_component_labels)
            missing_detail_categories = sorted(
                set(source_component_detail_categories) - set(mapped_covered_detail_categories)
            )
            group_cols = ["economy", "scenario", "year"]
            component_grouped = component.groupby(group_cols, as_index=False)["value"].sum().rename(columns={"value": "mapped_component_total_pj"})
            total_grouped = total.groupby(group_cols, as_index=False)["value"].sum().rename(columns={"value": "expected_total_pj"})
            detail = total_grouped.merge(component_grouped, on=group_cols, how="left")
            detail["mapped_component_total_pj"] = pd.to_numeric(detail.get("mapped_component_total_pj", 0.0), errors="coerce").fillna(0.0)
            rows.append(
                _summarise_balance_coverage_groups(
                    detail,
                    dataset="NINTH",
                    mapping_set=str(mapping_set["mapping_set"]),
                    check_name=str(spec["check_name"]),
                    check_level=check_level,
                    component_prefixes=list(spec["ninth_component_prefixes"]),
                    expected_prefixes=list(spec["ninth_expected_prefixes"]),
                    mapped_covered_categories=mapped_covered_categories,
                    source_expected_categories=source_expected_categories,
                    mapped_covered_detail_categories=mapped_covered_detail_categories,
                    missing_detail_categories=missing_detail_categories,
                    tolerance_pj=tolerance_pj,
                )
            )
    return rows


def build_mapping_balance_coverage_qa(
    effective_tables: dict[str, pd.DataFrame],
    *,
    esto_data_path: Path = ESTO_ORIGINAL_DATA_PATH,
    ninth_data_path: Path = NINTH_BALANCE_COVERAGE_DATA_PATH,
    tolerance_pj: float = MAPPING_BALANCE_COVERAGE_TOLERANCE_PJ,
    selected_years: tuple[str, ...] | None = MAPPING_BALANCE_COVERAGE_YEARS,
    rollup_rules: dict[str, pd.DataFrame] | None = None,
) -> pd.DataFrame:
    """
    Check whether mapped original-dataset components add up to source total rows.

    This is an early mapping-coverage check, separate from LEAP result balance
    checks. It verifies active mapping sets against the original ESTO and 9th
    datasets for TPES, transformation, and total final consumption style totals.
    """
    mapping_pair_sets = _mapping_pair_sets_for_balance_coverage(effective_tables)
    rows = [
        *_build_esto_mapping_balance_coverage(
            esto_data_path,
            mapping_pair_sets,
            tolerance_pj=tolerance_pj,
            selected_years=selected_years,
            rollup_rules=rollup_rules,
        ),
        *_build_ninth_mapping_balance_coverage(
            ninth_data_path,
            mapping_pair_sets,
            tolerance_pj=tolerance_pj,
            selected_years=selected_years,
            rollup_rules=rollup_rules,
        ),
    ]
    columns = [
        "dataset",
        "mapping_set",
        "check_level",
        "check_name",
        "status",
        "failed_group_count",
        "max_abs_difference_pj",
        "scenario_with_max_difference",
        "source_expected_total_pj",
        "mapped_covered_total_pj",
        "difference_percent",
        "source_expected_categories",
        "mapped_covered_categories",
        "mapped_covered_detail_categories",
        "missing_detail_categories",
        "details",
    ]
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns).sort_values(
        ["status", "dataset", "mapping_set", "check_level", "check_name"],
        ascending=[True, True, True, True, True],
    ).reset_index(drop=True)


def update_mapping_cardinality(
    mapping_workbook_path: Path,
    qa_dir: Path,
    fail_on_many_to_many_after_rollup: bool = False,
) -> dict[str, object]:
    """Update workbook cardinality columns and write rollup/cardinality QA."""
    backup_dir = mapping_workbook_path.parent / "archive"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{mapping_workbook_path.stem}.before_rollup_cardinality_{pd.Timestamp.now():%Y%m%d_%H%M%S}{mapping_workbook_path.suffix}"
    shutil.copy2(mapping_workbook_path, backup_path)

    ensure_rollup_sheets(mapping_workbook_path)
    ensure_individual_mapping_exception_sheet(mapping_workbook_path)
    rollup_rules = read_rollup_rules(mapping_workbook_path)
    effective_tables, rollup_qa = build_all_effective_mappings(mapping_workbook_path, include_reverse=True)
    relationship_df = build_relationship_rows(effective_tables)
    individual_mapping_exceptions = read_individual_mapping_exceptions(mapping_workbook_path)
    valid_labels_by_name = load_original_label_sets()
    subtotal_lookup_by_system = load_subtotal_lookups(effective_tables)
    mapping_balance_coverage = build_mapping_balance_coverage_qa(effective_tables, rollup_rules=rollup_rules)
    qa_tables = build_qa_tables(
        effective_tables,
        relationship_df,
        rollup_qa,
        individual_mapping_exceptions,
        valid_labels_by_name,
        subtotal_lookup_by_system,
        mapping_balance_coverage,
    )
    qa_dir.mkdir(parents=True, exist_ok=True)

    for config in MAPPING_SHEET_CONFIGS:
        if config.get("is_reverse"):
            continue
        effective_df = effective_tables[config["use_case"]].copy()
        replace_cols = [
            "source_sheet",
            "source_row_number",
            "use_case",
            "source_system",
            "target_system",
        ]
        effective_df = effective_df.drop(columns=[column for column in replace_cols if column in effective_df.columns])
        replace_sheet_with_dataframe(mapping_workbook_path, config["source_sheet"], effective_df)

    for qa_name, qa_df in qa_tables.items():
        qa_df.to_csv(qa_dir / f"{qa_name}.csv", index=False)

    many_to_many_after = qa_tables["qa_many_to_many_after_rollup"]
    print(f"Updated workbook: {mapping_workbook_path}")
    print(f"Backup workbook: {backup_path}")
    print(f"Wrote QA files to: {qa_dir}")
    print(f"Many-to-many before rollup rows: {len(qa_tables['qa_many_to_many_before_rollup']):,}")
    print(f"Many-to-many after rollup rows: {len(many_to_many_after):,}")
    print(f"Individual mapping consistency rows: {len(qa_tables['qa_individual_mapping_consistency']):,}")
    print(f"Original label presence rows: {len(qa_tables['qa_original_label_presence']):,}")
    print(f"Subtotal alignment rows: {len(qa_tables['qa_subtotal_alignment']):,}")
    print(f"Mapping balance coverage rows: {len(qa_tables['qa_mapping_balance_coverage']):,}")
    print(f"Rollup rules used: {len(qa_tables['qa_rollup_rules_used']):,}")
    print(f"Ambiguous rollup matches: {len(qa_tables['qa_rollup_rules_ambiguous']):,}")

    if not many_to_many_after.empty:
        message = (
            "High severity: unresolved many-to-many mappings remain after rollup. "
            f"Review {qa_dir / 'qa_many_to_many_after_rollup.csv'}."
        )
        if fail_on_many_to_many_after_rollup:
            raise ValueError(message)
        print(message)

    return {
        "mapping_workbook": str(mapping_workbook_path),
        "backup_workbook": str(backup_path),
        "qa_dir": str(qa_dir),
        "many_to_many_before_rollup_rows": int(len(qa_tables["qa_many_to_many_before_rollup"])),
        "many_to_many_after_rollup_rows": int(len(many_to_many_after)),
        "individual_mapping_consistency_rows": int(len(qa_tables["qa_individual_mapping_consistency"])),
        "original_label_presence_rows": int(len(qa_tables["qa_original_label_presence"])),
        "subtotal_alignment_rows": int(len(qa_tables["qa_subtotal_alignment"])),
        "mapping_balance_coverage_rows": int(len(qa_tables["qa_mapping_balance_coverage"])),
        "rollup_rules_used_rows": int(len(qa_tables["qa_rollup_rules_used"])),
        "ambiguous_rollup_rows": int(len(qa_tables["qa_rollup_rules_ambiguous"])),
    }


#%%
try:
    if __name__ == "__main__" and RUN_UPDATE_MAPPING_CARDINALITY:
        UPDATE_RESULT = update_mapping_cardinality(
            mapping_workbook_path=MAPPING_WORKBOOK_PATH,
            qa_dir=QA_DIR,
            fail_on_many_to_many_after_rollup=FAIL_ON_MANY_TO_MANY_AFTER_ROLLUP,
        )
except Exception as exc:
    print("Mapping cardinality update failed.")
    print(f"Error: {exc}")
    raise

#%%
