from __future__ import annotations

import pandas as pd

from codebase.functions import supply_export_builder


def test_format_scenario_label_for_filename_strips_non_alphanumeric_characters() -> None:
    label = supply_export_builder.format_scenario_label_for_filename(
        ["Current Accounts", "Reference+", "Target case"]
    )

    assert label == "CurrentAccounts_Reference_Targetcase"


def test_get_region_for_economy_uses_apec_map_and_fallback() -> None:
    assert supply_export_builder.get_region_for_economy("12_NZ") == "New Zealand"
    assert supply_export_builder.get_region_for_economy("20USA") == "United States"
    assert supply_export_builder.get_region_for_economy("unknown") == "United States"


def test_build_supply_log_rows_creates_rows_from_tiny_esto_dataset(
    monkeypatch,
) -> None:
    data = pd.DataFrame(
        {
            "economy": ["20_USA", "20_USA"],
            "flows": ["02 Imports", "03 Exports"],
            "products": ["01 Coal", "01 Coal"],
            2022: [4.0, -2.0],
        }
    )
    fuel_config = {
        "01 Coal": {
            "fuel_label_esto": "01 Coal",
            "fuel_name": "Coal",
        }
    }
    measures = [
        {"name": "Imports", "flow_key": "imports", "units": "Petajoule", "per": ""},
        {"name": "Exports", "flow_key": "exports", "units": "Petajoule", "per": ""},
    ]

    monkeypatch.setattr(
        supply_export_builder,
        "_get_supply_branch_roots_for_entry",
        lambda fuel_key, fuel_entry: [["Resources", "Primary"]],
    )
    monkeypatch.setattr(
        supply_export_builder,
        "_supply_branch_exists_in_export_source",
        lambda branch_path: True,
    )

    rows = supply_export_builder.build_supply_log_rows(
        data=data,
        year_cols=[2022],
        economy="20_USA",
        fuel_config=fuel_config,
        flow_codes=supply_export_builder.FLOW_CODES_BY_DATASET["esto"],
        scenario_names=["Reference"],
        base_year=2022,
        final_year=2022,
        supply_measures=measures,
    )

    values_by_measure = {row["Measure"]: row["Value"] for row in rows}

    assert {row["Branch_Path"] for row in rows} == {"Resources\\Primary\\Coal"}
    assert {row["Scenario"] for row in rows} == {"Reference"}
    assert values_by_measure == {"Imports": 4.0, "Exports": 2.0}
