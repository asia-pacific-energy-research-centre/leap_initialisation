from __future__ import annotations

import pandas as pd
import pytest

from codebase.functions import supply_branch_classification as branch_classification
from codebase.functions import supply_config_builder
from codebase.functions import supply_export_rows
from codebase.functions import supply_value_series


def test_supply_value_series_selects_esto_products_by_numeric_prefix() -> None:
    df = pd.DataFrame(
        {
            "economy": ["20_USA", "20_USA", "20_USA"],
            "flows": ["02 Imports", "03 Exports", "02 Imports"],
            "products": ["17 Electricity", "17.01 Solar", "01 Coal"],
            2022: [1.0, -2.0, 3.0],
        }
    )

    fuel_rows = supply_value_series.select_fuel_rows(
        df,
        fuel_code_ninth=None,
        fuel_label_esto="17 Electricity",
    )
    flow_rows = supply_value_series.select_flow_rows(
        fuel_rows,
        economy="20_USA",
        flow_value="02 Imports",
    )

    assert fuel_rows["products"].tolist() == ["17 Electricity", "17.01 Solar"]
    assert flow_rows[2022].tolist() == [1.0]


def test_supply_value_series_normalizes_export_signs_and_projection_years() -> None:
    data = pd.DataFrame(
        {
            "economy": ["20_USA"],
            "flows": ["03 Exports"],
            "products": ["01 Coal"],
            2022: [-4.0],
        }
    )
    projection_lookup = pd.DataFrame(
        [{2030: -8.0, 2031: 9.0}],
        index=pd.MultiIndex.from_tuples(
            [("20USA", "03 Exports", "01 Coal")],
            names=["economy", "flows", "products"],
        ),
    )
    fuel_config = {"fuel_label_esto": "01 Coal", "fuel_code_ninth": "01_coal"}

    values = supply_value_series.build_supply_value_by_year(
        data,
        year_cols=[2022],
        economy="20_USA",
        fuel_config=fuel_config,
        flow_key="exports",
        flow_value="03 Exports",
        base_year=2022,
        final_year=2030,
        projection_lookup=projection_lookup,
        projection_years=[2030, 2031],
    )

    assert values[2022] == pytest.approx(4.0)
    assert values[2030] == pytest.approx(8.0)
    assert 2031 not in values


def test_supply_export_rows_coerces_values_and_builds_log_rows() -> None:
    year_map = supply_export_rows.coerce_value_by_year(2.5, 2022, 2024)

    rows = supply_export_rows.build_year_rows(
        branch_path="Resources\\Primary\\Coal",
        measure="Imports",
        scenario="Reference",
        value_by_year=year_map,
        units="Petajoule",
        scale="",
        per_value="",
    )

    assert year_map == {2022: 2.5, 2023: 2.5, 2024: 2.5}
    assert rows[0]["Branch_Path"] == "Resources\\Primary\\Coal"
    assert [row["Date"] for row in rows] == [2022, 2023, 2024]
    assert [row["Value"] for row in rows] == [2.5, 2.5, 2.5]


def test_supply_export_rows_current_accounts_override_falls_back_to_reference() -> None:
    overrides = {
        "Reference": {
            "01 Coal": {
                "imports": {2022: 1.0, 2023: 2.0, 2025: 99.0},
            }
        }
    }
    fuel_entry = {"fuel_label_esto": "01 Coal", "fuel_name": "Coal"}

    resolved = supply_export_rows._resolve_supply_override(
        overrides,
        scenario="Current Accounts",
        fuel_key="01 Coal",
        fuel_entry=fuel_entry,
        flow_key="imports",
        base_year=2022,
        final_year=2023,
    )

    assert resolved == {2022: 1.0, 2023: 2.0}


def test_supply_config_builder_maps_labels_and_updates_config() -> None:
    mapping = {"01 Coal": "Coal", "17 Electricity": "Electricity"}
    config = {
        "01 Coal": {"fuel_label_esto": "01 Coal", "fuel_name": "01 Coal"},
        "02 Imports": {"fuel_label_esto": "02 Imports", "fuel_name": "02 Imports"},
    }

    updated = supply_config_builder.apply_code_to_name_mapping(config, mapping)

    assert supply_config_builder.map_code_label("17 Electricity", mapping) == "Electricity"
    assert updated["01 Coal"]["fuel_name"] == "Coal"
    assert updated["02 Imports"]["fuel_name"] == "02 Imports"


def test_supply_branch_classification_normalizes_lookup_names_and_fallback_roots() -> None:
    assert (
        branch_classification._normalize_supply_lookup_fuel_name("17 Electricity")
        == "electricity"
    )
    assert branch_classification._classify_supply_root_for_product("17 Electricity") == "secondary"
    assert branch_classification._classify_supply_root_for_product("01 Coal") == "primary"
    assert (
        branch_classification._normalize_supply_branch_path_for_lookup(
            "Resources\\Secondary\\17 Electricity"
        )
        == "resources\\secondary\\electricity"
    )
