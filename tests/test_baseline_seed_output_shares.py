#%%
"""Regression tests for safe baseline-seed Output Share generation and patching."""

import pandas as pd
import pytest

from codebase.functions import transformation_record_builder as builder
from codebase.functions.leap_excel_io import finalise_export_df
from codebase.functions.patch_baseline_seeds import _deduplicate_rows_safely


def _record(sector: str, output_values: dict) -> dict:
    return {
        "economy": "05_PRC",
        "sector_title": sector,
        "process_name": sector,
        "output_values": output_values,
    }


def _identity_mapping(record: dict) -> dict:
    labels = [record["sector_title"], *record["output_values"].keys()]
    return {label: label for label in labels}


def test_transfers_unallocated_uses_genuine_output_profile_not_alphabetical_100():
    records = [_record(
        "Transfers unallocated",
        {
            "Additives and oxygenates": {2022: 0.0, 2023: 20.0, 2024: 40.0},
            "LPG": {2022: 0.0, 2023: 80.0, 2024: 60.0},
        },
    )]

    lookup = builder._build_output_share_lookup(records, _identity_mapping(records[0]), 2022, 2024)
    shares = builder._normalize_output_shares_for_export(
        lookup[("05_PRC", "Transfers unallocated")], 2022, 2024
    )

    assert shares["Additives and oxygenates"] == {2022: 20.0, 2023: 20.0, 2024: 40.0}
    assert shares["LPG"] == {2022: 80.0, 2023: 80.0, 2024: 60.0}
    assert all(sum(values[year] for values in shares.values()) == pytest.approx(100.0) for year in range(2022, 2025))


def test_chp_interim_projection_years_use_electricity_and_heat_values():
    records = [_record(
        "CHP interim",
        {
            "Electricity": {2022: 0.0, 2023: 30.0, 2024: 25.0},
            "Heat": {2022: 0.0, 2023: 70.0, 2024: 75.0},
        },
    )]

    lookup = builder._build_output_share_lookup(records, _identity_mapping(records[0]), 2022, 2024)
    shares = builder._normalize_output_shares_for_export(
        lookup[("05_PRC", "CHP interim")], 2022, 2024
    )

    assert set(shares["Electricity"]) == {2022, 2023, 2024}
    assert shares["Electricity"][2022] == pytest.approx(30.0)
    assert shares["Heat"][2024] == pytest.approx(75.0)
    assert all(sum(values[year] for values in shares.values()) == pytest.approx(100.0) for year in range(2022, 2025))


def test_all_zero_chp_preserves_zero_profile_for_capacity_gated_completion():
    records = [_record(
        "CHP interim",
        {"Electricity": {2022: 0.0, 2023: 0.0}, "Heat": {2022: 0.0, 2023: 0.0}},
    )]
    lookup = builder._build_output_share_lookup(
        records, _identity_mapping(records[0]), 2022, 2023
    )
    assert lookup[("05_PRC", "CHP interim")] == {
        "Electricity": {2022: 0.0, 2023: 0.0},
        "Heat": {2022: 0.0, 2023: 0.0},
    }


def test_all_zero_single_output_share_is_anchored_at_100():
    records = [_record(
        "Heat plant interim",
        {"Heat": {2022: 0.0, 2023: 0.0}},
    )]
    lookup = builder._build_output_share_lookup(
        records, _identity_mapping(records[0]), 2022, 2023
    )
    shares = builder._normalize_output_shares_for_export(
        lookup[("05_PRC", "Heat plant interim")], 2022, 2023
    )

    assert shares == {"Heat": {2022: 100.0, 2023: 100.0}}


def test_all_zero_multi_output_share_group_is_anchored_at_100():
    records = [_record(
        "Coal transformation",
        {
            "Coke oven coke": {2022: 0.0, 2023: 0.0},
            "Coke oven gas": {2022: 0.0, 2023: 0.0},
        },
    )]
    lookup = builder._build_output_share_lookup(
        records, _identity_mapping(records[0]), 2022, 2023
    )
    shares = builder._normalize_output_shares_for_export(
        lookup[("05_PRC", "Coal transformation")], 2022, 2023
    )

    assert shares["Coke oven coke"] == {2022: 100.0, 2023: 100.0}
    assert shares["Coke oven gas"] == {2022: 0.0, 2023: 0.0}
    assert all(
        sum(values[year] for values in shares.values()) == pytest.approx(100.0)
        for year in range(2022, 2024)
    )


def test_auto_balance_is_not_the_inert_all_zero_share_anchor():
    output_shares = builder._normalize_output_shares_for_export(
        {"AUTO BALANCE": {2022: 0.0, 2023: 0.0}, "Naphtha": {2022: 0.0, 2023: 0.0}},
        2022,
        2023,
    )
    feedstock_shares = builder.prepare_feedstock_shares_for_export(
        feedstock_shares={},
        feedstock_values={},
        process_feedstock_labels=["AUTO BALANCE", "Naphtha"],
        base_year=2022,
        final_year=2023,
    )

    assert output_shares["AUTO BALANCE"] == {2022: 0.0, 2023: 0.0}
    assert output_shares["Naphtha"] == {2022: 100.0, 2023: 100.0}
    assert feedstock_shares["AUTO BALANCE"] == {2022: 0.0, 2023: 0.0}
    assert feedstock_shares["Naphtha"] == {2022: 100.0, 2023: 100.0}


def test_auto_balance_remains_a_valid_anchor_when_it_is_the_only_sibling():
    output_shares = builder._normalize_output_shares_for_export(
        {"AUTO BALANCE": {2022: 0.0, 2023: 0.0}}, 2022, 2023
    )
    feedstock_shares = builder.prepare_feedstock_shares_for_export(
        feedstock_shares={},
        feedstock_values={},
        process_feedstock_labels=["AUTO BALANCE"],
        base_year=2022,
        final_year=2023,
    )

    assert output_shares["AUTO BALANCE"] == {2022: 100.0, 2023: 100.0}
    assert feedstock_shares["AUTO BALANCE"] == {2022: 100.0, 2023: 100.0}


def test_genuine_auto_balance_profile_is_preserved():
    shares = builder._normalize_output_shares_for_export(
        {"AUTO BALANCE": {2022: 12.0, 2023: 12.0}}, 2022, 2023
    )

    assert shares["AUTO BALANCE"] == {2022: 100.0, 2023: 100.0}


def test_zero_fill_never_anchors_auto_balance():
    catalog = pd.DataFrame([
        {"fuel_group": "Feedstock Fuels", "branch_path": r"Transformation\Transfers unallocated\Processes\Transfers unallocated\Feedstock Fuels\AUTO BALANCE"},
        {"fuel_group": "Feedstock Fuels", "branch_path": r"Transformation\Transfers unallocated\Processes\Transfers unallocated\Feedstock Fuels\Naphtha"},
        {"fuel_group": "Output Fuels", "branch_path": r"Transformation\Transfers unallocated\Output Fuels\AUTO BALANCE"},
        {"fuel_group": "Output Fuels", "branch_path": r"Transformation\Transfers unallocated\Output Fuels\Naphtha"},
    ])
    rows = builder.build_aux_fuel_zero_rows(
        existing_rows=[],
        full_branch_catalog_df=catalog,
        scenarios=["Current Accounts"],
        base_year=2022,
        final_year=2022,
        in_scope_sector_titles={"Transfers unallocated"},
    )
    values = {(row["Branch_Path"], row["Measure"]): row["Value"] for row in rows}

    assert values[r"Transformation\Transfers unallocated\Processes\Transfers unallocated\Feedstock Fuels\AUTO BALANCE", "Feedstock Fuel Share"] == 0.0
    assert values[r"Transformation\Transfers unallocated\Processes\Transfers unallocated\Feedstock Fuels\Naphtha", "Feedstock Fuel Share"] == 100.0
    assert values[r"Transformation\Transfers unallocated\Output Fuels\AUTO BALANCE", "Output Share"] == 0.0
    assert values[r"Transformation\Transfers unallocated\Output Fuels\Naphtha", "Output Share"] == 100.0


def test_final_export_carries_valid_share_profile_over_explicit_zero_year():
    rows = []
    for fuel, base_value, projection_value in [
        ("Other hydrocarbons", 100.0, 0.0),
        ("Ethane", 0.0, 0.0),
    ]:
        for year, value in [(2022, base_value), (2023, projection_value)]:
            rows.append({
                "Branch_Path": f"Transformation\\Non specified transformation\\Output Fuels\\{fuel}",
                "Scenario": "Target",
                "Measure": "Output Share",
                "Units": "Share",
                "Scale": "%",
                "Per...": "",
                "Date": year,
                "Value": value,
            })

    export_df = finalise_export_df(
        pd.DataFrame(rows),
        "Target",
        "United States",
        2022,
        2023,
    )

    assert export_df.loc[
        export_df["Branch Path"].str.endswith("\\Other hydrocarbons"), 2023
    ].iloc[0] == pytest.approx(100.0)
    assert export_df.loc[
        export_df["Branch Path"].str.endswith("\\Ethane"), 2023
    ].iloc[0] == pytest.approx(0.0)


def test_patch_deduplicates_identical_rows_but_rejects_zero_vs_100_conflict():
    base = {
        "Branch Path": "Transformation\\CHP interim\\Output Fuels\\Electricity",
        "Variable": "Output Share",
        "Scenario": "Target",
        "Region": "China",
    }
    identical = pd.DataFrame([{**base, "Expression": "Data(2023,30)"}, {**base, "Expression": "Data(2023, 30.0)"}])
    resolved = _deduplicate_rows_safely(identical)
    assert len(resolved) == 1

    conflict = pd.DataFrame([{**base, "Expression": "Data(2023,0)"}, {**base, "Expression": "Data(2023,100)"}])
    with pytest.raises(ValueError, match="refusing to guess"):
        _deduplicate_rows_safely(conflict)


#%%
