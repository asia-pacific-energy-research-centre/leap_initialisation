"""Focused tests for transformation output conservation v1."""

#%%

import pandas as pd
import pytest

from codebase.functions.transformation_conservation import (
    build_raw_transformation_output_reference,
    build_transformation_output_conservation,
)


def _reference(value=10.0):
    return pd.DataFrame([{
        "economy": "20_USA", "scenario": "Reference",
        "transformation_module": "__all_transformation_outputs__", "output_fuel": "__all_fuels__",
        "year": 2022, "source_system": "ESTO", "source_module": "09.07 Refineries",
        "source_fuel": "07 Petroleum products", "value": value, "included": True,
        "inclusion_reason": "positive_leaf_transformation_output", "exclusion_reason": "",
        "value_classification": "exact", "mapping_status": "exact_aggregated", "source_row_id": "raw-1",
    }])


def _record(value=10.0):
    return {"economy": "20_USA", "sector_title": "Refineries", "process_name": "Refinery",
            "output_values": {"Petroleum products": {2022: value}},
            "feedstock_values": {"Crude oil": {2022: -20.0}}}


def test_equal_output_passes_and_breakdown_reproduces_headline():
    totals, breakdown, _ = build_transformation_output_conservation(_reference(), {"Reference": [_record()]})
    assert totals.loc[0, "status"] == "match"
    assert breakdown["breakdown_remainder"].abs().max() == pytest.approx(0.0)


@pytest.mark.parametrize("records, expected_reason", [([], "missing_produced"), ([_record(), _record()], "value_difference")])
def test_dropped_or_duplicated_output_is_reported(records, expected_reason):
    totals, _, _ = build_transformation_output_conservation(_reference(), {"Reference": records})
    assert totals.loc[0, "is_mismatch"]
    assert totals.loc[0, "reason"] == expected_reason


def test_negative_inputs_and_zero_skeletons_do_not_enter_outputs():
    record = _record()
    record["output_values"]["Skeleton"] = {2022: 0.0}
    totals, _, lineage = build_transformation_output_conservation(_reference(), {"Reference": [record]})
    assert totals.loc[0, "produced_total"] == pytest.approx(10.0)
    assert not (lineage.get("source_fuel", pd.Series(dtype=str)) == "Crude oil").any()


def test_raw_reference_drops_subtotal_parent_and_negative_feedstock():
    esto = pd.DataFrame([
        {"economy": "20USA", "flows": "09 Transformation", "products": "07 Products", "is_subtotal": False, 2022: 10.0},
        {"economy": "20USA", "flows": "09.07 Refineries", "products": "07.01 Gasoline", "is_subtotal": False, 2022: 10.0},
        {"economy": "20USA", "flows": "09.07 Refineries", "products": "06 Crude", "is_subtotal": False, 2022: -20.0},
    ])
    ninth = pd.DataFrame(columns=["economy", "sectors", "fuels", "scenarios", 2023])
    reference = build_raw_transformation_output_reference(esto, ninth, ["20_USA"], ["Reference"], 2022, 2022)
    included = reference[reference.included]
    assert included["value"].sum() == pytest.approx(10.0)
    assert (reference.exclusion_reason == "subtotal_or_structural_aggregate").any()
    assert (reference.exclusion_reason == "non_positive_input_or_zero").any()


def test_raw_reference_normalizes_economy_and_maps_current_accounts_to_reference():
    esto = pd.DataFrame([
        {"economy": "20_USA", "flows": "09.07 Refineries", "products": "07.01 Gasoline", "is_subtotal": False, 2022: 4.0},
    ])
    ninth = pd.DataFrame([
        {"economy": "20_USA", "scenarios": "reference", "sectors": "09_07_refineries", "fuels": "07_petroleum_products", "subtotal_results": False, 2023: 5.0},
        {"economy": "20_USA", "scenarios": "target", "sectors": "09_07_refineries", "fuels": "07_petroleum_products", "subtotal_results": False, 2023: 6.0},
    ])

    reference = build_raw_transformation_output_reference(
        esto, ninth, ["20_USA"], ["Reference", "Target", "Current Accounts"], 2022, 2023
    )

    totals = reference[reference.included].groupby(["scenario", "year"])["value"].sum()
    assert totals[("Reference", 2022)] == pytest.approx(4.0)
    assert totals[("Target", 2022)] == pytest.approx(4.0)
    assert totals[("Current Accounts", 2022)] == pytest.approx(4.0)
    assert totals[("Reference", 2023)] == pytest.approx(5.0)
    assert totals[("Current Accounts", 2023)] == pytest.approx(5.0)
    assert totals[("Target", 2023)] == pytest.approx(6.0)


def test_inactive_power_modules_remain_in_scope_audit_but_not_reference_total():
    esto = pd.DataFrame([
        {"economy": "20USA", "flows": "09.01.01 Electricity plants", "products": "17 Electricity", "is_subtotal": False, 2022: 7.0},
        {"economy": "20USA", "flows": "09.07 Refineries", "products": "07.01 Gasoline", "is_subtotal": False, 2022: 3.0},
    ])
    ninth = pd.DataFrame(columns=["economy", "sectors", "fuels", "scenarios", 2023])

    reference = build_raw_transformation_output_reference(
        esto, ninth, ["20_USA"], ["Reference"], 2022, 2022,
        include_power_outputs=False,
    )

    assert reference[reference.included].value.sum() == pytest.approx(3.0)
    power = reference[reference.source_module.str.contains("Electricity plants")].iloc[0]
    assert not power.included
    assert power.exclusion_reason == "module_not_built_in_active_workflow"


def test_fan_out_is_retained_once_per_contribution_and_classified_honestly():
    records = [_record(5.0), _record(5.0)]
    totals, _, lineage = build_transformation_output_conservation(_reference(), {"Reference": records})
    assert totals.loc[0, "produced_total"] == pytest.approx(10.0)
    assert set(lineage[lineage.stage == "produced"].mapping_status) == {"fan_out_source_link_not_retained"}


def test_empty_comparison_fails():
    with pytest.raises(ValueError, match="empty"):
        build_transformation_output_conservation(pd.DataFrame(columns=_reference().columns), {})


#%%
