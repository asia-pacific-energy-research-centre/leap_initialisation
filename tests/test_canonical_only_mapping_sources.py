"""Guards against reintroducing legacy master-config mapping reads."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from codebase.utilities.master_config import (
    OUTLOOK_MAPPINGS_MASTER_PATH,
    RUNTIME_TABLE_DIR,
    read_config_table,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_legacy_ninth_pairs_filename_resolves_to_canonical_workbook() -> None:
    pairs = read_config_table(
        REPO_ROOT / "config" / "ninth_pairs_to_esto_pairs.xlsx",
        dtype=str,
    ).fillna("")
    sector = pairs[pairs["9th_sector"].eq("10_01_17_nonspecified_own_uses")]

    other_products = sector[sector["9th_fuel"].eq("07_x_other_petroleum_products")]
    unallocated = sector[sector["9th_fuel"].eq("07_petroleum_products_unallocated")]

    assert set(other_products["esto_product"]) == {"07.17 Other products"}
    assert set(unallocated["esto_product"]) == {"07.99 PetProd nonspecified"}


def test_projection_modules_point_directly_to_canonical_pairs_sheet() -> None:
    from codebase.functions import supply_assets, supply_data_pipeline, transformation_analysis_utils

    expected = (OUTLOOK_MAPPINGS_MASTER_PATH, "ninth_pairs_to_esto_pairs")
    assert supply_assets.NINTH_TO_ESTO_MAPPING_PATH == expected
    assert supply_data_pipeline.NINTH_TO_ESTO_MAPPING_PATH == expected
    assert transformation_analysis_utils.NINTH_TO_ESTO_MAPPING_PATH == expected


def test_supply_sector_config_uses_canonical_product_columns() -> None:
    from codebase.functions.supply_config_builder import build_supply_sector_config

    config = build_supply_sector_config(
        [OUTLOOK_MAPPINGS_MASTER_PATH],
        exclude_prefixes=["19", "20", "21"],
    )

    assert "07.99 PetProd nonspecified" in config
    assert config["07.99 PetProd nonspecified"]["fuel_name"] == "PetProd nonspecified"


def test_production_allocator_keeps_other_products_separate_from_unallocated() -> None:
    from codebase.functions.ninth_projection_mapping import build_esto_projection_table

    ninth = pd.DataFrame([
        {
            "scenarios": "reference", "economy": "20_USA",
            "sectors": "10_losses_and_own_use", "sub1sectors": "10_01_own_use",
            "sub2sectors": "10_01_17_nonspecified_own_uses", "sub3sectors": "x", "sub4sectors": "x",
            "fuels": "07_petroleum_products", "subfuels": "07_x_other_petroleum_products",
            "subtotal_results": False, 2023: -10.0,
        },
        {
            "scenarios": "reference", "economy": "20_USA",
            "sectors": "10_losses_and_own_use", "sub1sectors": "10_01_own_use",
            "sub2sectors": "10_01_17_nonspecified_own_uses", "sub3sectors": "x", "sub4sectors": "x",
            "fuels": "07_petroleum_products", "subfuels": "07_petroleum_products_unallocated",
            "subtotal_results": False, 2023: -20.0,
        },
    ])
    esto = pd.DataFrame([
        {"economy": "20USA", "flows": "10.01.17 Non-specified own uses", "products": "07.17 Other products", 2022: 1.0},
        {"economy": "20USA", "flows": "10.01.17 Non-specified own uses", "products": "07.99 PetProd nonspecified", 2022: 1.0},
    ])

    projection, _diagnostics = build_esto_projection_table(
        ninth_data=ninth,
        esto_data=esto,
        mapping_path=(OUTLOOK_MAPPINGS_MASTER_PATH, "ninth_pairs_to_esto_pairs"),
        base_year=2022,
        projection_years=[2023],
        strict_conservation=True,
    )
    values = dict(zip(projection["esto_product"], projection[2023]))
    assert values["07.17 Other products"] == -10.0
    assert values["07.99 PetProd nonspecified"] == -20.0


def test_operational_tables_are_standalone_and_not_master_config() -> None:
    expected = {
        "ESTO_subtotal_mapping.csv",
        "leap_explicit_reassignments.csv",
        "leap_results_sheet_map.csv",
        "leap_x_hierarchy_overrides.csv",
        "ninth_sector_fuel_pairs.csv",
        "synthetic_reference_rows.csv",
    }
    assert expected.issubset({path.name for path in RUNTIME_TABLE_DIR.glob("*.csv")})


def test_python_runtime_has_no_master_config_workbook_path() -> None:
    offenders: list[str] = []
    for path in (REPO_ROOT / "codebase").rglob("*.py"):
        if "mapping_code" in path.parts or "archive" in path.parts:
            continue
        text = path.read_text(encoding="utf-8-sig")
        compact = text.replace("\\", "/").lower()
        if "config/master_config.xlsx" in compact:
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []
