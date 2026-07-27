"""Regression tests for feedstock-only LEAP process efficiency."""

#%%

import pandas as pd
import pytest

from codebase.functions.transformation_record_builder import (
    build_process_record,
    build_transformation_log_rows,
)
from codebase.functions.transformation_series_utils import (
    compute_efficiency_by_year,
    compute_efficiency_from_value_maps,
)


def test_efficiency_series_uses_feedstock_without_auxiliary_energy() -> None:
    output = pd.Series({2022: 16.775})
    feedstock = pd.Series({2022: 41.930999})

    efficiency = compute_efficiency_by_year(output, feedstock)

    assert efficiency.loc[2022] == pytest.approx(16.775 / 41.930999)


def test_process_record_overrides_legacy_efficiency_with_exported_feedstocks() -> None:
    """The shared record boundary protects every transformation module."""
    record = build_process_record(
        economy="01_AUS",
        sector_title="Blast furnaces",
        process_name="Blast furnaces",
        output_values={"Blast furnace gas": {2022: 16.775}},
        feedstock_values={"Coke oven coke": {2022: 41.930999}},
        # This is the old output/(feedstock+own-use) result and must not survive.
        efficiency={2022: 16.775 / (41.930999 + 21.735885)},
        auxiliary_ratios={
            "Blast furnace gas": {2022: 1.0},
            "Natural gas": {2022: 0.2696061997019374},
            "Electricity": {2022: 0.026124649776453058},
        },
        loss_values={
            "Blast furnace gas": {2022: -16.775},
            "Natural gas": {2022: -4.522644},
            "Electricity": {2022: -0.438241},
        },
        loss_total=21.735885,
        feedstock_shares={"Coke oven coke": {2022: 1.0}},
    )

    assert record["efficiency"][2022] == pytest.approx(16.775 / 41.930999)
    assert record["auxiliary_ratios"]["Blast furnace gas"][2022] == pytest.approx(1.0)

    rows = build_transformation_log_rows(
        [record],
        scenario="Current Accounts",
        region="Australia",
        base_year=2022,
        final_year=2022,
        code_to_name_mapping={
            label: label
            for label in (
                "Blast furnaces",
                "Blast furnace gas",
                "Natural gas",
                "Electricity",
                "Coke oven coke",
            )
        },
    )
    efficiency_row = next(row for row in rows if row["Measure"] == "Process Efficiency")
    assert efficiency_row["Value"] == pytest.approx((16.775 / 41.930999) * 100.0)


def test_multiple_exported_feedstocks_are_summed_in_denominator() -> None:
    efficiency = compute_efficiency_from_value_maps(
        {"Output A": {2022: 30.0}, "Output B": {2022: 10.0}},
        {"Feedstock A": {2022: 60.0}, "Feedstock B": {2022: 20.0}},
    )

    assert efficiency[2022] == pytest.approx(0.5)


def test_zero_skeleton_preserves_explicit_placeholder_efficiency() -> None:
    record = build_process_record(
        economy="01_AUS",
        sector_title="Test module",
        process_name="Inactive process",
        output_values={"Output": {2022: 0.0}},
        feedstock_values={"Feedstock": {2022: 0.0}},
        efficiency={2022: 1.0},
        auxiliary_ratios={},
        loss_values={},
        loss_total=0.0,
    )

    assert record["efficiency"][2022] == pytest.approx(1.0)


#%%
