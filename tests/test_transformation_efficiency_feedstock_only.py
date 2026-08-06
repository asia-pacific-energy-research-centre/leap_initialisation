"""Regression tests for feedstock-only LEAP process efficiency."""

#%%

import pandas as pd
import pytest

from codebase.functions import supply_leap_io, supply_preflight
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


def test_oil_refining_uses_one_gross_output_basis_for_leap_boundary() -> None:
    """Refinery outputs and auxiliary ratios share the gross capacity basis."""
    gross_output = 551.001809
    feedstock = 552.471099
    own_use = {
        "Refinery gas": 25.581888,
        "Petroleum coke": 3.237736,
        "Other products": 10.210399,
    }
    external_auxiliary = {
        "Natural gas": 3.620941,
        "Electricity": 2.097260,
    }
    output_values = {
        "Motor gasoline": {2022: 431.971786},
        "Refinery gas": {2022: own_use["Refinery gas"]},
        "Petroleum coke": {2022: own_use["Petroleum coke"]},
        "Other products": {2022: 90.210399},
    }
    auxiliary_energy = {**own_use, **external_auxiliary}

    record = build_process_record(
        economy="01_AUS",
        sector_title="Oil Refining",
        process_name="Oil Refining",
        output_values=output_values,
        feedstock_values={"Crude oil and refinery feedstocks": {2022: feedstock}},
        efficiency={2022: 0.0},
        auxiliary_ratios={
            label: {2022: value / gross_output}
            for label, value in auxiliary_energy.items()
        },
        loss_values={
            label: {2022: value}
            for label, value in auxiliary_energy.items()
        },
        loss_total=sum(auxiliary_energy.values()),
    )

    assert sum(values[2022] for values in record["gross_output_values"].values()) == pytest.approx(
        gross_output
    )
    assert sum(values[2022] for values in record["output_values"].values()) == pytest.approx(
        gross_output
    )
    assert sum(
        values[2022] for values in record["deliverable_output_values"].values()
    ) == pytest.approx(gross_output - sum(own_use.values()))
    assert record["output_values"]["Refinery gas"][2022] == pytest.approx(
        own_use["Refinery gas"]
    )
    assert record["output_values"]["Petroleum coke"][2022] == pytest.approx(
        own_use["Petroleum coke"]
    )
    assert record["output_values"]["Other products"][2022] == pytest.approx(90.210399)
    assert record["efficiency"][2022] == pytest.approx(gross_output / feedstock)
    assert record["auxiliary_ratios"]["Natural gas"][2022] == pytest.approx(
        external_auxiliary["Natural gas"] / gross_output
    )
    assert record["process_boundary_status"] == "gross_output_with_separate_auxiliary_use"

    # LEAP applies Output Share and Auxiliary Fuel Use to the same process
    # output basis. Their combined balance must therefore reconstruct the
    # source 09.07 output plus the separate 10.01.11 own-use row fuel by fuel.
    all_fuels = sorted(set(output_values) | set(auxiliary_energy))
    for fuel in all_fuels:
        modeled_output = gross_output * (
            record["output_values"].get(fuel, {}).get(2022, 0.0) / gross_output
        )
        modeled_auxiliary = gross_output * (
            record["auxiliary_ratios"].get(fuel, {}).get(2022, 0.0)
        )
        expected_balance = (
            output_values.get(fuel, {}).get(2022, 0.0)
            - auxiliary_energy.get(fuel, 0.0)
        )
        assert modeled_output - modeled_auxiliary == pytest.approx(expected_balance)


def test_non_overlapping_auxiliary_fuels_leave_process_record_unchanged() -> None:
    record = build_process_record(
        economy="01_AUS",
        sector_title="Electricity generation",
        process_name="Gas turbine",
        output_values={"Electricity": {2022: 40.0}},
        feedstock_values={"Natural gas": {2022: 80.0}},
        efficiency={2022: 0.5},
        auxiliary_ratios={"Diesel": {2022: 0.05}},
        loss_values={"Diesel": {2022: 2.0}},
        loss_total=2.0,
    )

    assert record["output_values"] == {"Electricity": {2022: 40.0}}
    assert record["auxiliary_ratios"] == {"Diesel": {2022: 0.05}}
    assert record["process_boundary_status"] == "no_output_auxiliary_overlap"


@pytest.mark.parametrize(
    ("sector_title", "output_label", "auxiliary_label"),
    [
        ("Blast furnaces", "Blast furnace gas", "Blast furnace gas"),
        ("Coke ovens", "Coke oven gas", "Coke oven gas"),
        ("LNG regasification", "Natural gas", "Natural gas"),
    ],
)
def test_overlapping_transformation_output_and_auxiliary_use_keep_gross_basis(
    sector_title: str,
    output_label: str,
    auxiliary_label: str,
) -> None:
    """All overlapping modules need the same LEAP balance boundary as refining."""
    gross_output = 100.0
    auxiliary_energy = 25.0
    record = build_process_record(
        economy="20_USA",
        sector_title=sector_title,
        process_name=sector_title,
        output_values={output_label: {2023: gross_output}},
        feedstock_values={"Feedstock": {2023: 125.0}},
        efficiency={2023: 0.0},
        auxiliary_ratios={auxiliary_label: {2023: auxiliary_energy / gross_output}},
        loss_values={auxiliary_label: {2023: auxiliary_energy}},
        loss_total=auxiliary_energy,
    )

    assert record["output_values"][output_label][2023] == pytest.approx(gross_output)
    assert record["deliverable_output_values"][output_label][2023] == pytest.approx(75.0)
    assert record["auxiliary_ratios"][auxiliary_label][2023] == pytest.approx(0.25)
    assert record["process_boundary_status"] == "gross_output_with_separate_auxiliary_use"
    assert (
        record["output_values"][output_label][2023]
        - record["auxiliary_ratios"][auxiliary_label][2023] * gross_output
    ) == pytest.approx(75.0)


def test_refinery_capacity_uses_deliverable_output_and_preserves_runtime_additions(
    monkeypatch,
    tmp_path,
) -> None:
    gross_output = 100.0
    record = build_process_record(
        economy="01_AUS",
        sector_title="Oil Refining",
        process_name="Oil Refining",
        output_values={"Motor gasoline": {2022: 80.0}, "Refinery gas": {2022: 20.0}},
        feedstock_values={"Crude oil": {2022: 110.0}},
        efficiency={2022: 0.0},
        auxiliary_ratios={"Refinery gas": {2022: 20.0 / gross_output}},
        loss_values={"Refinery gas": {2022: 20.0}},
        loss_total=20.0,
    )
    monkeypatch.setattr(supply_leap_io, "_use_capacity_like_mode", lambda: True)
    monkeypatch.setattr(supply_leap_io, "_use_legacy_trade_split_mode", lambda: False)
    monkeypatch.setattr(
        supply_leap_io,
        "_leap_export_template_for_economy",
        lambda economy: tmp_path / "aus.xlsx",
    )
    monkeypatch.setattr(
        supply_preflight,
        "_configured_reset_module_names",
        lambda template_path=None: {"oil refining"},
    )
    monkeypatch.setattr(
        supply_preflight,
        "_configured_reset_output_fuel_labels_by_module",
        lambda module_names, template_path=None: {
            "oil refining": ["Motor gasoline", "Refinery gas"]
        },
    )
    monkeypatch.setattr(
        supply_leap_io,
        "_lookup_runtime_capacity_additions_for_record",
        lambda **kwargs: {2022: 5.0},
    )

    updated = supply_leap_io.apply_transformation_target_overrides_for_scenario(
        [record],
        pd.DataFrame(),
        pd.DataFrame(),
        "Current Accounts",
    )[0]

    # LEAP meets refinery auxiliary fuel from module outputs, so it grosses
    # deliverable production up itself. Capacity excludes same-module own use,
    # then adds runtime capacity; historical production is not exported.
    assert updated["exogenous_capacity_by_year"][2022] == pytest.approx(85.0)
    assert "historical_production_by_year" not in updated


def test_auxiliary_above_matching_output_preserves_excess_as_external() -> None:
    record = build_process_record(
        economy="01_AUS",
        sector_title="Coke ovens",
        process_name="Coke ovens",
        output_values={"Coke oven gas": {2022: 10.0}, "Coke": {2022: 10.0}},
        feedstock_values={"Coking coal": {2022: 30.0}},
        efficiency={2022: 2.0 / 3.0},
        auxiliary_ratios={"Coke oven gas": {2022: 0.75}},
        loss_values={"Coke oven gas": {2022: 15.0}},
        loss_total=15.0,
    )

    assert record["output_values"]["Coke oven gas"][2022] == pytest.approx(10.0)
    assert record["same_module_auxiliary_values"]["Coke oven gas"][2022] == pytest.approx(10.0)
    assert record["external_auxiliary_energy_values"]["Coke oven gas"][2022] == pytest.approx(5.0)
    assert record["auxiliary_ratios"]["Coke oven gas"][2022] == pytest.approx(0.75)
    assert record["process_boundary_status"] == "gross_output_with_separate_auxiliary_use"


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
