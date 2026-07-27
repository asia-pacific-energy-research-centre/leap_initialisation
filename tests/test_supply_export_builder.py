from __future__ import annotations

import pandas as pd

from codebase.functions import supply_export_builder
from codebase.functions.leap_excel_io import finalise_export_df


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
        lambda fuel_key, fuel_entry, source_path=None: [["Resources", "Primary"]],
    )
    monkeypatch.setattr(
        supply_export_builder,
        "_supply_branch_exists_in_export_source",
        lambda branch_path, source_path=None: True,
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


def test_build_supply_log_rows_records_nonzero_esto_stock_and_statistical_values(
    monkeypatch,
) -> None:
    """Regression guard for the main goal: a nonzero ESTO stock-change or
    statistical-discrepancy value must show up in Current Accounts output,
    and must NOT be projected into Reference/Target (left at 0 there)."""
    esto_data = pd.DataFrame(
        {
            "economy": ["20_USA", "20_USA", "20_USA", "20_USA"],
            "flows": [
                "02 Imports",
                "06 Stock changes",
                "11 Statistical discrepancy",
                "11 Statistical discrepancy",
            ],
            "products": ["01 Coal", "01 Coal", "01 Coal", "02 Crude oil"],
            2022: [4.0, -1.5, 0.75, 0.0],
        }
    )
    fuel_config = {
        "01 Coal": {"fuel_label_esto": "01 Coal", "fuel_name": "Coal"},
        "02 Crude oil": {"fuel_label_esto": "02 Crude oil", "fuel_name": "Crude oil"},
    }

    monkeypatch.setattr(
        supply_export_builder,
        "_get_supply_branch_roots_for_entry",
        lambda fuel_key, fuel_entry, source_path=None: [["Resources", "Primary"]],
    )
    monkeypatch.setattr(
        supply_export_builder,
        "_supply_branch_exists_in_export_source",
        lambda branch_path, source_path=None: True,
    )

    rows = supply_export_builder.build_supply_log_rows(
        data=esto_data,
        year_cols=[2022],
        economy="20_USA",
        fuel_config=fuel_config,
        flow_codes=supply_export_builder.FLOW_CODES_BY_DATASET["esto"],
        scenario_names=["Current Accounts", "Reference", "Target"],
        base_year=2022,
        final_year=2022,
        supply_measures=[],
        esto_data=esto_data,
        esto_year_cols=[2022],
    )

    by_key = {
        (row["Branch_Path"], row["Measure"], row["Scenario"]): row["Value"] for row in rows
    }

    # Nonzero ESTO actuals land in Current Accounts, sign preserved.
    assert by_key[("Stock Changes\\Primary\\Coal", "Stock Change", "Current Accounts")] == -1.5
    assert (
        by_key[
            ("Statistical Differences\\Primary\\Coal", "Statistical Differences", "Current Accounts")
        ]
        == 0.75
    )
    # A zero ESTO actual still produces a Current Accounts row, just at 0.
    assert (
        by_key[
            (
                "Statistical Differences\\Primary\\Crude oil",
                "Statistical Differences",
                "Current Accounts",
            )
        ]
        == 0.0
    )
    # Projected scenarios are left at 0 regardless of the ESTO actual.
    assert by_key[("Stock Changes\\Primary\\Coal", "Stock Change", "Reference")] == 0.0
    assert by_key[("Stock Changes\\Primary\\Coal", "Stock Change", "Target")] == 0.0
    assert (
        by_key[
            ("Statistical Differences\\Primary\\Coal", "Statistical Differences", "Reference")
        ]
        == 0.0
    )


def test_nonzero_esto_stock_and_statistical_values_survive_to_the_finished_export(
    monkeypatch,
) -> None:
    """End-to-end guard: a nonzero ESTO stock-change/statistical-discrepancy
    value must still be present, with its sign intact, in the pivoted export
    the LEAP import file is built from -- not just in the raw log rows."""
    esto_data = pd.DataFrame(
        {
            "economy": ["20_USA", "20_USA"],
            "flows": ["06 Stock changes", "11 Statistical discrepancy"],
            "products": ["01 Coal", "01 Coal"],
            2022: [-1.5, 0.75],
        }
    )
    fuel_config = {"01 Coal": {"fuel_label_esto": "01 Coal", "fuel_name": "Coal"}}

    monkeypatch.setattr(
        supply_export_builder,
        "_get_supply_branch_roots_for_entry",
        lambda fuel_key, fuel_entry, source_path=None: [["Resources", "Primary"]],
    )
    monkeypatch.setattr(
        supply_export_builder,
        "_supply_branch_exists_in_export_source",
        lambda branch_path, source_path=None: True,
    )

    rows = supply_export_builder.build_supply_log_rows(
        data=esto_data,
        year_cols=[2022],
        economy="20_USA",
        fuel_config=fuel_config,
        flow_codes=supply_export_builder.FLOW_CODES_BY_DATASET["esto"],
        scenario_names=["Current Accounts", "Reference", "Target"],
        base_year=2022,
        final_year=2022,
        supply_measures=[],
        esto_data=esto_data,
        esto_year_cols=[2022],
    )

    log_df = pd.DataFrame(rows).rename(columns={"Value": "Value"})
    export_df = finalise_export_df(
        log_df,
        scenario="Current Accounts, Reference, Target",
        region="United States",
        base_year=2022,
        final_year=2022,
    )

    current_accounts = export_df[export_df["Scenario"] == "Current Accounts"].set_index(
        ["Branch Path", "Variable"]
    )[2022]
    assert current_accounts[("Stock Changes\\Primary\\Coal", "Stock Change")] == -1.5
    assert (
        current_accounts[
            ("Statistical Differences\\Primary\\Coal", "Statistical Differences")
        ]
        == 0.75
    )


def test_balance_adjustment_rows_are_created_without_template_branches(
    monkeypatch,
) -> None:
    data = pd.DataFrame(
        {
            "economy": ["01_AUS", "01_AUS"],
            "flows": ["06 Stock changes", "11 Statistical discrepancy"],
            "products": ["01 Coal", "01 Coal"],
            2022: [-3.5, 1.25],
        }
    )
    fuel_config = {
        "01 Coal": {
            "fuel_label_esto": "01 Coal",
            "fuel_name": "Coal",
        }
    }
    measures = [
        {
            "name": "Stock Changes",
            "flow_key": "stock_changes",
            "units": "Petajoule",
            "per": "",
            "top_level_root": "Stock Changes",
        },
        {
            "name": "Statistical Differences",
            "flow_key": "statistical_discrepancy",
            "units": "Petajoule",
            "per": "",
            "top_level_root": "Statistical Differences",
        },
    ]

    monkeypatch.setattr(
        supply_export_builder,
        "_get_supply_branch_roots_for_entry",
        lambda fuel_key, fuel_entry, source_path=None: [["Resources", "Primary"]],
    )
    monkeypatch.setattr(
        supply_export_builder,
        "_supply_branch_exists_in_export_source",
        lambda branch_path, source_path=None: False,
    )

    rows = supply_export_builder.build_supply_log_rows(
        data=data,
        year_cols=[2022],
        economy="01_AUS",
        fuel_config=fuel_config,
        flow_codes=supply_export_builder.FLOW_CODES_BY_DATASET["esto"],
        scenario_names=["Current Accounts"],
        base_year=2022,
        final_year=2022,
        supply_measures=measures,
    )

    assert {
        (row["Branch_Path"], row["Measure"], row["Value"])
        for row in rows
    } == {
        ("Stock Changes\\Primary\\Coal", "Stock Changes", -3.5),
        (
            "Statistical Differences\\Primary\\Coal",
            "Statistical Differences",
            1.25,
        ),
    }
