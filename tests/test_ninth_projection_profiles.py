import pandas as pd
import pytest
from pathlib import Path

from codebase.functions.ninth_projection_mapping import (
    build_esto_projection_table,
    build_economy_specific_child_flow_profiles,
    build_ninth_projection_series,
    _build_parent_child_reconciliation_diagnostics,
)
from codebase.functions.esto_data_utils import add_all_economy_total


def _own_use_ninth_row(fuel: str, value_2023: float, value_2030: float) -> dict:
    return {
        "economy": "05_PRC",
        "scenarios": "target",
        "sectors": "10_losses_and_own_use",
        "sub1sectors": "10_01_own_use",
        "sub2sectors": "10_01_02_gas_works_plants",
        "sub3sectors": "x",
        "sub4sectors": "x",
        "fuels": fuel,
        "subfuels": "x",
        "subtotal_results": False,
        2023: value_2023,
        2030: value_2030,
    }


def test_transformation_owned_all_zero_own_use_carries_signed_base_energy(tmp_path) -> None:
    """PRC gas-works own-use structural zeros retain all four known fuels."""
    candidates = {
        "02 Coal products": -1.163344,
        "08.03 Gas works gas": -0.264522,
        "17 Electricity": -69.472800,
        "18 Heat": -49.066621,
    }
    esto = pd.DataFrame([
        {"economy": "05PRC", "flows": "10.01.02 Gas works plants", "products": product,
         "is_subtotal": False, 2022: value}
        for product, value in candidates.items()
    ])
    ninth = pd.DataFrame([
        _own_use_ninth_row("02_coal_products", 0.0, 0.0),
        _own_use_ninth_row("08_03_gas_works_gas", 0.0, 0.0),
        _own_use_ninth_row("17_electricity", 0.0, 0.0),
        _own_use_ninth_row("18_heat", 0.0, 0.0),
    ])
    mapping_path = tmp_path / "mapping.xlsx"
    pd.DataFrame([
        {"ninth_sector": "10_01_02_gas_works_plants", "ninth_fuel": fuel,
         "esto_flow": "10.01.02 Gas works plants", "esto_product": product}
        for fuel, product in [
            ("02_coal_products", "02 Coal products"),
            ("08_03_gas_works_gas", "08.03 Gas works gas"),
            ("17_electricity", "17 Electricity"),
            ("18_heat", "18 Heat"),
        ]
    ]).to_excel(mapping_path, index=False)

    projection, diagnostics = build_esto_projection_table(
        ninth, esto, mapping_path, base_year=2022, projection_years=[2023, 2030],
        scenario="target", fill_missing_ninth_sectors=True,
        transformation_owned_loss_flows={"10.01.02 Gas works plants": "Gas works plants"},
    )

    projected = projection.set_index("esto_product")
    for product, value in candidates.items():
        assert projected.loc[product, [2023, 2030]].tolist() == pytest.approx([value, value])
    carried = diagnostics[diagnostics["diagnostic_type"].eq(
        "transformation_own_use_ninth_projection_all_zero"
    )]
    assert len(carried) == 4
    assert set(carried["provenance"]) == {"esto_base_year_carry_forward"}


def test_transformation_own_use_nonzero_ninth_and_proxy_flow_are_unchanged(tmp_path) -> None:
    esto = pd.DataFrame([
        {"economy": "05PRC", "flows": "10.01.02 Gas works plants", "products": "17 Electricity", "is_subtotal": False, 2022: -10.0},
        {"economy": "05PRC", "flows": "10.01.03 Liquefaction/regasification plants", "products": "18 Heat", "is_subtotal": False, 2022: -20.0},
        {"economy": "05PRC", "flows": "10.01.02 Gas works plants", "products": "18 Heat", "is_subtotal": False, 2022: 0.0},
    ])
    ninth = pd.DataFrame([
        _own_use_ninth_row("17_electricity", 0.0, -15.0),
        {**_own_use_ninth_row("18_heat", 0.0, 0.0), "sub2sectors": "10_01_03_liquefaction_regasification_plants"},
    ])
    mapping_path = tmp_path / "mapping.xlsx"
    pd.DataFrame([
        {"ninth_sector": "10_01_02_gas_works_plants", "ninth_fuel": "17_electricity", "esto_flow": "10.01.02 Gas works plants", "esto_product": "17 Electricity"},
        {"ninth_sector": "10_01_03_liquefaction_regasification_plants", "ninth_fuel": "18_heat", "esto_flow": "10.01.03 Liquefaction/regasification plants", "esto_product": "18 Heat"},
        {"ninth_sector": "10_01_02_gas_works_plants", "ninth_fuel": "18_heat", "esto_flow": "10.01.02 Gas works plants", "esto_product": "18 Heat"},
    ]).to_excel(mapping_path, index=False)

    projection, diagnostics = build_esto_projection_table(
        ninth, esto, mapping_path, base_year=2022, projection_years=[2023, 2030],
        scenario="target", fill_missing_ninth_sectors=True,
        transformation_owned_loss_flows={"10.01.02 Gas works plants": "Gas works plants"},
    )

    values = projection.set_index(["esto_flow", "esto_product"])
    assert values.loc[("10.01.02 Gas works plants", "17 Electricity"), [2023, 2030]].tolist() == pytest.approx([0.0, -15.0])
    assert values.loc[("10.01.03 Liquefaction/regasification plants", "18 Heat"), [2023, 2030]].tolist() == pytest.approx([0.0, 0.0])
    assert ("10.01.02 Gas works plants", "18 Heat") not in values.index
    assert not diagnostics.get("diagnostic_type", pd.Series(dtype=str)).eq(
        "transformation_own_use_ninth_projection_all_zero"
    ).any()


def test_coal_and_refinery_owned_own_use_flows_are_eligible_for_flat_carry(tmp_path) -> None:
    esto = pd.DataFrame([
        {"economy": "01AUS", "flows": "10.01.05 Coke ovens", "products": "17 Electricity", "is_subtotal": False, 2022: -3.0},
        {"economy": "01AUS", "flows": "10.01.11 Oil refineries", "products": "08.01 Natural gas", "is_subtotal": False, 2022: -4.0},
    ])
    ninth = pd.DataFrame([
        {**_own_use_ninth_row("17_electricity", 0.0, 0.0), "economy": "01_AUS", "sub2sectors": "10_01_05_coke_ovens"},
        {**_own_use_ninth_row("08_01_natural_gas", 0.0, 0.0), "economy": "01_AUS", "sub2sectors": "10_01_11_oil_refineries"},
    ])
    mapping_path = tmp_path / "mapping.xlsx"
    pd.DataFrame([
        {"ninth_sector": "10_01_05_coke_ovens", "ninth_fuel": "17_electricity", "esto_flow": "10.01.05 Coke ovens", "esto_product": "17 Electricity"},
        {"ninth_sector": "10_01_11_oil_refineries", "ninth_fuel": "08_01_natural_gas", "esto_flow": "10.01.11 Oil refineries", "esto_product": "08.01 Natural gas"},
    ]).to_excel(mapping_path, index=False)

    projection, _ = build_esto_projection_table(
        ninth, esto, mapping_path, base_year=2022, projection_years=[2023, 2030],
        scenario="target", fill_missing_ninth_sectors=True,
        transformation_owned_loss_flows={
            "10.01.05 Coke ovens": "Coke ovens",
            "10.01.11 Oil refineries": "Oil Refining",
        },
    )

    values = projection.set_index("esto_flow")
    assert values.loc["10.01.05 Coke ovens", [2023, 2030]].tolist() == pytest.approx([-3.0, -3.0])
    assert values.loc["10.01.11 Oil refineries", [2023, 2030]].tolist() == pytest.approx([-4.0, -4.0])


def test_projection_series_accepts_string_year_headers() -> None:
    ninth_pairs = pd.DataFrame(
        [
            {
                "economy_key": "01AUS",
                "ninth_sector": "01_production",
                "ninth_fuel": "01_01_coking_coal",
                "2023": 12.0,
            }
        ]
    )

    result = build_ninth_projection_series(ninth_pairs, [2023])

    assert 2023 in result.columns
    assert result.loc[0, 2023] == pytest.approx(12.0)


def test_child_flow_profiles_are_built_per_economy_and_keep_signed_values() -> None:
    esto = pd.DataFrame(
        [
            {
                "economy": "01AUS",
                "flows": "09.08.01 Coke ovens",
                "products": "02.01 Coke oven coke",
                "is_subtotal": False,
                "2022": 300.0,
            },
            {
                "economy": "01AUS",
                "flows": "09.08.02 Blast furnaces",
                "products": "02.01 Coke oven coke",
                "is_subtotal": False,
                "2022": -180.0,
            },
            {
                "economy": "05PRC",
                "flows": "09.08.01 Coke ovens",
                "products": "02.01 Coke oven coke",
                "is_subtotal": False,
                "2022": 900.0,
            },
            {
                "economy": "01AUS",
                "flows": "09.08.01 Coke ovens",
                "products": "02.01 Coke oven coke",
                "is_subtotal": True,
                "2022": 999.0,
            },
        ]
    )

    profiles = build_economy_specific_child_flow_profiles(esto, 2022)

    assert set(profiles["economy_key"]) == {"01AUS", "05PRC"}
    aus = profiles[profiles["economy_key"].eq("01AUS")]
    assert set(aus["base_value"]) == {300.0, -180.0}
    assert set(aus["base_value_abs"]) == {300.0, 180.0}
    assert (profiles["profile_parent_flow"] == "09.08 Coal transformation").all()


def test_child_flow_profiles_require_current_run_esto_columns() -> None:
    esto = pd.DataFrame(
        {
            "economy": ["01AUS"],
            "flows": ["09.08.01 Coke ovens"],
            "products": ["02.01 Coke oven coke"],
        }
    )

    with pytest.raises(KeyError, match="2022"):
        build_economy_specific_child_flow_profiles(esto, 2022)


def test_projection_without_economy_base_values_remains_unallocated_with_context(
    tmp_path,
) -> None:
    esto = pd.DataFrame(
        [
            {
                "economy": "20USA",
                "flows": "09.08 Coal transformation",
                "products": "02.01 Coke oven coke",
                "is_subtotal": False,
                "2021": 10.0,
                "2022": 0.0,
            },
            {
                "economy": "20USA",
                "flows": "09.08.01 Coke ovens",
                "products": "02.01 Coke oven coke",
                "is_subtotal": False,
                "2021": 6.0,
                "2022": 0.0,
            },
            {
                "economy": "20USA",
                "flows": "09.08.05 Liquefaction (coal to oil)",
                "products": "02.04 Coal tar",
                "is_subtotal": False,
                "2021": 4.0,
                "2022": 0.0,
            },
            {
                # Another economy has a base-year value. It must not become an
                # APEC fallback allocation profile for the United States.
                "economy": "01AUS",
                "flows": "09.08 Coal transformation",
                "products": "02.01 Coke oven coke",
                "is_subtotal": False,
                "2021": 100.0,
                "2022": 100.0,
            },
        ]
    )
    ninth = pd.DataFrame(
        [
            {
                "economy": "20_USA",
                "scenarios": "reference",
                "sectors": "09_total_transformation_sector",
                "sub1sectors": "09_08_coal_transformation",
                "sub2sectors": "x",
                "sub3sectors": "x",
                "sub4sectors": "x",
                "fuels": "02_coal_products",
                "subfuels": "x",
                "subtotal_results": False,
                2023: 50.0,
            }
        ]
    )
    mapping_path = tmp_path / "mapping.xlsx"
    pd.DataFrame(
        [
            {
                "ninth_sector": "09_08_coal_transformation",
                "ninth_fuel": "02_coal_products",
                "esto_flow": "09.08 Coal transformation",
                "esto_product": "02.01 Coke oven coke",
            }
        ]
    ).to_excel(mapping_path, index=False)

    projection, diagnostics = build_esto_projection_table(
        ninth,
        esto,
        mapping_path,
        base_year=2022,
        projection_years=[2023],
        sign_stable_flows="all",
    )

    assert projection.empty
    summary = diagnostics[
        diagnostics["diagnostic_type"].eq(
            "unallocated_no_economy_base_year"
        )
    ]
    assert len(summary) == 1
    assert summary.iloc[0]["share_source"] == (
        "unallocated_no_economy_base_year"
    )

    context = diagnostics[
        diagnostics["diagnostic_type"].eq("unallocated_projection_context")
    ]
    assert set(context["diagnostic_record_type"]) == {
        "unallocated_target_mapping",
        "unallocated_projection",
        "historical_flow_family",
    }
    unallocated_values = context[
        context["diagnostic_record_type"].eq("unallocated_projection")
    ]
    assert unallocated_values[["year", "value"]].to_dict("records") == [
        {"year": 2023, "value": 50.0}
    ]
    historical = context[
        context["diagnostic_record_type"].eq("historical_flow_family")
    ]
    assert set(historical["esto_flow"]) == {
        "09.08 Coal transformation",
        "09.08.01 Coke ovens",
        "09.08.05 Liquefaction (coal to oil)",
    }
    assert set(historical["esto_product"]) == {
        "02.01 Coke oven coke",
        "02.04 Coal tar",
    }
    assert set(historical["year"]) == {2021, 2022}


def test_gas_projection_without_parent_or_child_base_values_is_unallocated(
    tmp_path,
) -> None:
    esto = pd.DataFrame(
        [
            {
                "economy": "20USA",
                "flows": "09.06 Gas processing plants",
                "products": "08.01 Natural gas",
                "is_subtotal": True,
                "2022": 0.0,
            },
            {
                "economy": "20USA",
                "flows": "09.06.01 Gas works plants",
                "products": "08.01 Natural gas",
                "is_subtotal": False,
                "2022": 0.0,
            },
        ]
    )
    ninth = pd.DataFrame(
        [
            {
                "economy": "20_USA",
                "scenarios": "reference",
                "sectors": "09_total_transformation_sector",
                "sub1sectors": "09_06_gas_processing_plants",
                "sub2sectors": "x",
                "sub3sectors": "x",
                "sub4sectors": "x",
                "fuels": "08_01_natural_gas",
                "subfuels": "x",
                "subtotal_results": True,
                2023: 25.0,
            }
        ]
    )
    mapping_path = tmp_path / "mapping.xlsx"
    pd.DataFrame(
        [
            {
                "ninth_sector": "09_06_gas_processing_plants",
                "ninth_fuel": "08_01_natural_gas",
                "esto_flow": "09.06 Gas processing plants",
                "esto_product": "08.01 Natural gas",
            }
        ]
    ).to_excel(mapping_path, index=False)

    projection, diagnostics = build_esto_projection_table(
        ninth,
        esto,
        mapping_path,
        base_year=2022,
        projection_years=[2023],
        sign_stable_flows="all",
    )

    assert projection.empty
    unallocated = diagnostics[
        diagnostics["diagnostic_type"].eq(
            "unallocated_no_economy_base_year"
        )
    ]
    assert len(unallocated) == 1
    assert unallocated.iloc[0]["flow_family"] == "09.06"
    context = diagnostics[
        diagnostics["diagnostic_type"].eq("unallocated_projection_context")
    ]
    projected = context[
        context["diagnostic_record_type"].eq("unallocated_projection")
    ]
    assert projected.iloc[0]["value"] == pytest.approx(25.0)


def test_parent_projection_preserves_mixed_signed_child_profile(tmp_path) -> None:
    esto = pd.DataFrame(
        [
            {
                "economy": "01AUS",
                "flows": "09.08 Coal transformation",
                "products": "02.01 Coke oven coke",
                "is_subtotal": False,
                "2022": 120.0,
            },
            {
                "economy": "01AUS",
                "flows": "09.08.01 Coke ovens",
                "products": "02.01 Coke oven coke",
                "is_subtotal": False,
                "2022": 300.0,
            },
            {
                "economy": "01AUS",
                "flows": "09.08.02 Blast furnaces",
                "products": "02.01 Coke oven coke",
                "is_subtotal": False,
                "2022": -180.0,
            },
        ]
    )
    ninth = pd.DataFrame(
        [
            {
                "economy": "01_AUS",
                "scenarios": "reference",
                "sectors": "09_total_transformation_sector",
                "sub1sectors": "09_08_coal_transformation",
                "sub2sectors": "x",
                "sub3sectors": "x",
                "sub4sectors": "x",
                "fuels": "02_coal_products",
                "subfuels": "x",
                "subtotal_results": False,
                2023: 120.0,
            }
        ]
    )
    mapping = pd.DataFrame(
        [
            {
                "ninth_sector": "09_08_coal_transformation",
                "ninth_fuel": "02_coal_products",
                "esto_flow": "09.08 Coal transformation",
                "esto_product": "02.01 Coke oven coke",
            }
        ]
    )
    mapping_path = tmp_path / "mapping.xlsx"
    mapping.to_excel(mapping_path, index=False)

    projection, diagnostics = build_esto_projection_table(
        ninth,
        esto,
        mapping_path,
        base_year=2022,
        projection_years=[2023],
        sign_stable_flows="all",
    )

    values = projection.set_index("esto_flow")[2023].to_dict()
    assert values["09.08.01 Coke ovens"] == pytest.approx(300.0)
    assert values["09.08.02 Blast furnaces"] == pytest.approx(-180.0)
    assert sum(values.values()) == pytest.approx(120.0)
    assert diagnostics.empty


def test_coal_parent_without_subtotal_uses_net_child_product_weights(tmp_path) -> None:
    """Coke output and blast-furnace input must not inflate a parent share."""
    esto = pd.DataFrame(
        [
            {
                "economy": "01AUS",
                "flows": "09.08.01 Coke ovens",
                "products": "02.01 Coke oven coke",
                "is_subtotal": False,
                "2022": 300.0,
            },
            {
                "economy": "01AUS",
                "flows": "09.08.02 Blast furnaces",
                "products": "02.01 Coke oven coke",
                "is_subtotal": False,
                "2022": -180.0,
            },
            {
                "economy": "01AUS",
                "flows": "09.08.01 Coke ovens",
                "products": "02.03 Coke oven gas",
                "is_subtotal": False,
                "2022": 80.0,
            },
        ]
    )
    ninth = pd.DataFrame(
        [
            {
                "economy": "01_AUS",
                "scenarios": "reference",
                "sectors": "09_total_transformation_sector",
                "sub1sectors": "09_08_coal_transformation",
                "sub2sectors": "x",
                "sub3sectors": "x",
                "sub4sectors": "x",
                "fuels": "02_coal_products",
                "subfuels": "x",
                "subtotal_results": False,
                2023: 200.0,
            }
        ]
    )
    mapping_path = tmp_path / "mapping.xlsx"
    pd.DataFrame(
        [
            {
                "ninth_sector": "09_08_coal_transformation",
                "ninth_fuel": "02_coal_products",
                "esto_flow": "09.08 Coal transformation",
                "esto_product": "02.01 Coke oven coke",
            },
            {
                "ninth_sector": "09_08_coal_transformation",
                "ninth_fuel": "02_coal_products",
                "esto_flow": "09.08 Coal transformation",
                "esto_product": "02.03 Coke oven gas",
            },
        ]
    ).to_excel(mapping_path, index=False)

    projection, diagnostics = build_esto_projection_table(
        ninth,
        esto,
        mapping_path,
        base_year=2022,
        projection_years=[2023],
        sign_stable_flows="all",
    )

    values = projection.set_index(["esto_flow", "esto_product"])[2023].to_dict()
    assert values[("09.08.01 Coke ovens", "02.01 Coke oven coke")] == pytest.approx(300.0)
    assert values[("09.08.02 Blast furnaces", "02.01 Coke oven coke")] == pytest.approx(-180.0)
    assert values[("09.08.01 Coke ovens", "02.03 Coke oven gas")] == pytest.approx(80.0)
    assert sum(values.values()) == pytest.approx(200.0)
    assert diagnostics.empty


def test_parent_child_reconciliation_diagnostic_reports_mismatch() -> None:
    source = pd.DataFrame(
        [{
            "economy_key": "01AUS",
            "ninth_sector": "09_08_coal_transformation",
            "ninth_fuel": "02_coal_products",
            2023: 100.0,
        }]
    )
    allocated = pd.DataFrame(
        [
            {
                "economy_key": "01AUS",
                "ninth_sector": "09_08_coal_transformation",
                "ninth_fuel": "02_coal_products",
                "esto_flow": "09.08.01 Coke ovens",
                2023: 60.0,
            },
            {
                "economy_key": "01AUS",
                "ninth_sector": "09_08_coal_transformation",
                "ninth_fuel": "02_coal_products",
                "esto_flow": "09.08.02 Blast furnaces",
                2023: 30.0,
            },
        ]
    )
    diagnostics = _build_parent_child_reconciliation_diagnostics(
        source, allocated, [2023]
    )
    assert len(diagnostics) == 1
    row = diagnostics.iloc[0]
    assert row["diagnostic_type"] == "parent_child_reconciliation_mismatch"
    assert row["parent_value"] == pytest.approx(100.0)
    assert row["allocated_child_value"] == pytest.approx(90.0)
    assert row["reconciliation_error"] == pytest.approx(-10.0)


def test_net_zero_child_profile_is_explicitly_diagnosed(tmp_path) -> None:
    esto = pd.DataFrame(
        [
            {
                "economy": "01AUS",
                "flows": "09.08 Coal transformation",
                "products": "02.01 Coke oven coke",
                "is_subtotal": False,
                "2022": 0.0,
            },
            {
                "economy": "01AUS",
                "flows": "09.08.01 Coke ovens",
                "products": "02.01 Coke oven coke",
                "is_subtotal": False,
                "2022": 100.0,
            },
            {
                "economy": "01AUS",
                "flows": "09.08.02 Blast furnaces",
                "products": "02.01 Coke oven coke",
                "is_subtotal": False,
                "2022": -100.0,
            },
        ]
    )
    ninth = pd.DataFrame(
        [
            {
                "economy": "01_AUS",
                "scenarios": "reference",
                "sectors": "09_total_transformation_sector",
                "sub1sectors": "09_08_coal_transformation",
                "sub2sectors": "x",
                "sub3sectors": "x",
                "sub4sectors": "x",
                "fuels": "02_coal_products",
                "subfuels": "x",
                "subtotal_results": False,
                2023: 50.0,
            }
        ]
    )
    mapping_path = tmp_path / "mapping.xlsx"
    pd.DataFrame(
        [
            {
                "ninth_sector": "09_08_coal_transformation",
                "ninth_fuel": "02_coal_products",
                "esto_flow": "09.08 Coal transformation",
                "esto_product": "02.01 Coke oven coke",
            }
        ]
    ).to_excel(mapping_path, index=False)

    projection, diagnostics = build_esto_projection_table(
        ninth,
        esto,
        mapping_path,
        base_year=2022,
        projection_years=[2023],
        sign_stable_flows="all",
    )

    values = projection.set_index("esto_flow")[2023].to_dict()
    assert values["09.08.01 Coke ovens"] == pytest.approx(50.0)
    assert values["09.08.02 Blast furnaces"] == pytest.approx(0.0)
    assert "coal_child_profile_net_zero" in set(diagnostics["diagnostic_type"])
    if "share_source" in diagnostics.columns:
        assert not diagnostics["share_source"].astype(str).eq("apec").any()


def test_gas_parent_residual_only_fills_a_missing_base_year_active_child(tmp_path) -> None:
    esto = pd.DataFrame(
        [
            {"economy": "01AUS", "flows": "09.06 Gas processing plants", "products": "08.01 Natural gas", "is_subtotal": True, "2022": 100.0},
            {"economy": "01AUS", "flows": "09.06.01 Gas works plants", "products": "08.01 Natural gas", "is_subtotal": False, "2022": 60.0},
            {"economy": "01AUS", "flows": "09.06.03 Natural gas blending plants", "products": "08.01 Natural gas", "is_subtotal": False, "2022": 40.0},
        ]
    )
    ninth = pd.DataFrame(
        [
            {"economy": "01_AUS", "scenarios": "reference", "sectors": "09_total_transformation_sector", "sub1sectors": "09_06_gas_processing_plants", "sub2sectors": "x", "sub3sectors": "x", "sub4sectors": "x", "fuels": "08_01_natural_gas", "subfuels": "x", "subtotal_results": True, 2023: 100.0},
            {"economy": "01_AUS", "scenarios": "reference", "sectors": "09_total_transformation_sector", "sub1sectors": "09_06_gas_processing_plants", "sub2sectors": "09_06_01_gas_works_plants", "sub3sectors": "x", "sub4sectors": "x", "fuels": "08_01_natural_gas", "subfuels": "x", "subtotal_results": False, 2023: 60.0},
        ]
    )
    mapping_path = tmp_path / "mapping.xlsx"
    pd.DataFrame(
        [
            {"ninth_sector": "09_06_gas_processing_plants", "ninth_fuel": "08_01_natural_gas", "esto_flow": "09.06 Gas processing plants", "esto_product": "08.01 Natural gas"},
            {"ninth_sector": "09_06_01_gas_works_plants", "ninth_fuel": "08_01_natural_gas", "esto_flow": "09.06.01 Gas works plants", "esto_product": "08.01 Natural gas"},
        ]
    ).to_excel(mapping_path, index=False)

    projection, diagnostics = build_esto_projection_table(
        ninth, esto, mapping_path, base_year=2022, projection_years=[2023], sign_stable_flows="all"
    )

    values = projection.set_index("esto_flow")[2023].to_dict()
    assert values["09.06.01 Gas works plants"] == pytest.approx(60.0)
    assert values["09.06.03 Natural gas blending plants"] == pytest.approx(40.0)
    assert "09.06 Gas processing plants" not in values
    assert "gas_parent_residual_allocated" in set(diagnostics["diagnostic_type"])


def test_gas_parent_residual_without_a_missing_base_year_active_child_raises(tmp_path) -> None:
    esto = pd.DataFrame(
        [
            {"economy": "01AUS", "flows": "09.06 Gas processing plants", "products": "08.01 Natural gas", "is_subtotal": True, "2022": 100.0},
            {"economy": "01AUS", "flows": "09.06.01 Gas works plants", "products": "08.01 Natural gas", "is_subtotal": False, "2022": 100.0},
        ]
    )
    ninth = pd.DataFrame(
        [
            {"economy": "01_AUS", "scenarios": "reference", "sectors": "09_total_transformation_sector", "sub1sectors": "09_06_gas_processing_plants", "sub2sectors": "x", "sub3sectors": "x", "sub4sectors": "x", "fuels": "08_01_natural_gas", "subfuels": "x", "subtotal_results": True, 2023: 100.0},
            {"economy": "01_AUS", "scenarios": "reference", "sectors": "09_total_transformation_sector", "sub1sectors": "09_06_gas_processing_plants", "sub2sectors": "09_06_01_gas_works_plants", "sub3sectors": "x", "sub4sectors": "x", "fuels": "08_01_natural_gas", "subfuels": "x", "subtotal_results": False, 2023: 60.0},
        ]
    )
    mapping_path = tmp_path / "mapping.xlsx"
    pd.DataFrame(
        [
            {"ninth_sector": "09_06_gas_processing_plants", "ninth_fuel": "08_01_natural_gas", "esto_flow": "09.06 Gas processing plants", "esto_product": "08.01 Natural gas"},
            {"ninth_sector": "09_06_01_gas_works_plants", "ninth_fuel": "08_01_natural_gas", "esto_flow": "09.06.01 Gas works plants", "esto_product": "08.01 Natural gas"},
        ]
    ).to_excel(mapping_path, index=False)

    with pytest.raises(ValueError, match="Gas processing parent residual has no base-year-active missing child"):
        build_esto_projection_table(
            ninth, esto, mapping_path, base_year=2022, projection_years=[2023], sign_stable_flows="all"
        )


@pytest.mark.parametrize(
    ("base_year", "projection_year"),
    [(2021, 2022), (2022, 2023), (2023, 2024)],
)
def test_protected_single_target_with_zero_configured_base_year_is_kept(
    tmp_path,
    base_year: int,
    projection_year: int,
) -> None:
    esto = pd.DataFrame(
        [
            {
                "economy": "01AUS",
                "flows": "09.06.02 Liquefaction/regasification plants",
                "products": "08.01 Natural gas",
                "is_subtotal": False,
                str(base_year): 0.0,
            }
        ]
    )
    ninth = pd.DataFrame(
        [
            {
                "economy": "01_AUS",
                "scenarios": "reference",
                "sectors": "09_total_transformation_sector",
                "sub1sectors": "09_06_gas_processing_plants",
                "sub2sectors": "09_06_02_liquefaction_regasification_plants",
                "sub3sectors": "x",
                "sub4sectors": "x",
                "fuels": "08_01_natural_gas",
                "subfuels": "x",
                "subtotal_results": False,
                projection_year: -125.0,
            }
        ]
    )
    mapping_path = tmp_path / "mapping.xlsx"
    pd.DataFrame(
        [
            {
                "ninth_sector": "09_06_02_liquefaction_regasification_plants",
                "ninth_fuel": "08_01_natural_gas",
                "esto_flow": "09.06.02 Liquefaction/regasification plants",
                "esto_product": "08.01 Natural gas",
            }
        ]
    ).to_excel(mapping_path, index=False)

    projection, diagnostics, provenance = build_esto_projection_table(
        ninth,
        esto,
        mapping_path,
        base_year=base_year,
        projection_years=[projection_year],
        sign_stable_flows="all",
        return_allocation_provenance=True,
    )

    assert projection.iloc[0][projection_year] == pytest.approx(-125.0)
    assert provenance.iloc[0]["share"] == pytest.approx(1.0)
    assert provenance.iloc[0]["share_source"] == "single_target_no_base_year"
    assert not diagnostics["diagnostic_type"].astype(str).eq(
        "unallocated_no_economy_base_year"
    ).any()


def test_zero_gas_parent_does_not_reverse_direct_child_projection_by_default(tmp_path) -> None:
    esto = pd.DataFrame(
        [
            {"economy": "01AUS", "flows": "09.06 Gas processing plants", "products": "08.01 Natural gas", "is_subtotal": True, "2022": 100.0},
            {"economy": "01AUS", "flows": "09.06.02 Liquefaction/regasification plants", "products": "08.01 Natural gas", "is_subtotal": False, "2022": 60.0},
            {"economy": "01AUS", "flows": "09.06.03 Natural gas blending plants", "products": "08.01 Natural gas", "is_subtotal": False, "2022": 40.0},
        ]
    )
    ninth = pd.DataFrame(
        [
            {"economy": "01_AUS", "scenarios": "reference", "sectors": "09_total_transformation_sector", "sub1sectors": "09_06_gas_processing_plants", "sub2sectors": "x", "sub3sectors": "x", "sub4sectors": "x", "fuels": "08_01_natural_gas", "subfuels": "x", "subtotal_results": True, 2023: 0.0},
            {"economy": "01_AUS", "scenarios": "reference", "sectors": "09_total_transformation_sector", "sub1sectors": "09_06_gas_processing_plants", "sub2sectors": "09_06_02_liquefaction_regasification_plants", "sub3sectors": "x", "sub4sectors": "x", "fuels": "08_01_natural_gas", "subfuels": "x", "subtotal_results": False, 2023: 60.0},
        ]
    )
    mapping_path = tmp_path / "mapping.xlsx"
    pd.DataFrame(
        [
            {"ninth_sector": "09_06_gas_processing_plants", "ninth_fuel": "08_01_natural_gas", "esto_flow": "09.06 Gas processing plants", "esto_product": "08.01 Natural gas"},
            {"ninth_sector": "09_06_02_liquefaction_regasification_plants", "ninth_fuel": "08_01_natural_gas", "esto_flow": "09.06.02 Liquefaction/regasification plants", "esto_product": "08.01 Natural gas"},
        ]
    ).to_excel(mapping_path, index=False)

    projection, diagnostics = build_esto_projection_table(
        ninth, esto, mapping_path, base_year=2022, projection_years=[2023], sign_stable_flows="all"
    )

    values = projection.set_index("esto_flow")[2023].to_dict()
    assert values == {"09.06.02 Liquefaction/regasification plants": pytest.approx(60.0)}
    assert "parent_child_reconciliation_mismatch" in set(
        diagnostics["diagnostic_type"]
    )

    filled, diagnostics = build_esto_projection_table(
        ninth,
        esto,
        mapping_path,
        base_year=2022,
        projection_years=[2023],
        sign_stable_flows="all",
        fill_missing_ninth_sectors=True,
    )
    filled_values = filled.set_index("esto_flow")[2023].to_dict()
    assert filled_values["09.06.02 Liquefaction/regasification plants"] == pytest.approx(60.0)
    assert filled_values["09.06.03 Natural gas blending plants"] == pytest.approx(40.0)
    assert "missing_ninth_sector_fill_applied" in set(diagnostics["diagnostic_type"])


def test_gas_parent_residual_without_any_active_child_profile_is_skipped(tmp_path) -> None:
    esto = pd.DataFrame(
        [
            {"economy": "13PNG", "flows": "09.06 Gas processing plants", "products": "07.09 LPG", "is_subtotal": True, "2022": 100.0},
            {"economy": "01AUS", "flows": "09.06.01 Gas works plants", "products": "08.01 Natural gas", "is_subtotal": False, "2022": 1.0},
        ]
    )
    ninth = pd.DataFrame(
        [
            {"economy": "13_PNG", "scenarios": "reference", "sectors": "09_total_transformation_sector", "sub1sectors": "09_06_gas_processing_plants", "sub2sectors": "x", "sub3sectors": "x", "sub4sectors": "x", "fuels": "07_09_lpg", "subfuels": "x", "subtotal_results": True, 2023: 100.0},
        ]
    )
    mapping_path = tmp_path / "mapping.xlsx"
    pd.DataFrame(
        [
            {"ninth_sector": "09_06_gas_processing_plants", "ninth_fuel": "07_09_lpg", "esto_flow": "09.06 Gas processing plants", "esto_product": "07.09 LPG"},
        ]
    ).to_excel(mapping_path, index=False)

    projection, diagnostics = build_esto_projection_table(
        ninth, esto, mapping_path, base_year=2022, projection_years=[2023], sign_stable_flows="all"
    )

    assert projection.empty
    assert "gas_parent_residual_no_active_child_profile" in set(diagnostics["diagnostic_type"])


def _general_gas_fill_fixture(tmp_path: Path, *, parent_2023: float = 200.0):
    esto = pd.DataFrame(
        [
            {"economy": "01AUS", "flows": "09.06 Gas processing plants", "products": "08.01 Natural gas", "is_subtotal": True, "2022": 100.0},
            {"economy": "01AUS", "flows": "09.06.02 Liquefaction/regasification plants", "products": "08.01 Natural gas", "is_subtotal": False, "2022": 30.0},
            {"economy": "01AUS", "flows": "09.06.03 Natural gas blending plants", "products": "08.01 Natural gas", "is_subtotal": False, "2022": 70.0},
        ]
    )
    ninth = pd.DataFrame(
        [
            {"economy": "01_AUS", "scenarios": "reference", "sectors": "09_total_transformation_sector", "sub1sectors": "09_06_gas_processing_plants", "sub2sectors": "x", "sub3sectors": "x", "sub4sectors": "x", "fuels": "08_01_natural_gas", "subfuels": "x", "subtotal_results": True, 2023: parent_2023},
            {"economy": "01_AUS", "scenarios": "reference", "sectors": "09_total_transformation_sector", "sub1sectors": "09_06_gas_processing_plants", "sub2sectors": "09_06_02_liquefaction_regasification_plants", "sub3sectors": "x", "sub4sectors": "x", "fuels": "08_01_natural_gas", "subfuels": "x", "subtotal_results": False, 2023: 80.0},
        ]
    )
    mapping_path = tmp_path / "general_mapping.xlsx"
    pd.DataFrame(
        [
            {"ninth_sector": "09_06_gas_processing_plants", "ninth_fuel": "08_01_natural_gas", "esto_flow": "09.06 Gas processing plants", "esto_product": "08.01 Natural gas"},
            {"ninth_sector": "09_06_02_liquefaction_regasification_plants", "ninth_fuel": "08_01_natural_gas", "esto_flow": "09.06.02 Liquefaction/regasification plants", "esto_product": "08.01 Natural gas"},
        ]
    ).to_excel(mapping_path, index=False)
    return esto, ninth, mapping_path


def test_general_missing_child_augments_parent_and_preserves_direct_child(tmp_path: Path) -> None:
    esto, ninth, mapping_path = _general_gas_fill_fixture(tmp_path)

    projection, diagnostics = build_esto_projection_table(
        ninth,
        esto,
        mapping_path,
        base_year=2022,
        projection_years=[2023],
        fill_missing_ninth_sectors=True,
        owner_workflow="transformation_workflow",
        strict_conservation=True,
    )

    values = projection.set_index("esto_flow")[2023].to_dict()
    assert values["09.06.02 Liquefaction/regasification plants"] == pytest.approx(80.0)
    assert values["09.06.03 Natural gas blending plants"] == pytest.approx(186.66666666666669)
    assert sum(values.values()) == pytest.approx(266.66666666666669)
    fill = diagnostics[diagnostics["diagnostic_type"].eq("missing_ninth_sector_fill_applied")]
    assert set(fill["allocation_method"]) == {"parent_augmented_for_protected_children"}
    assert fill.iloc[0]["owner_workflow"] == "transformation_workflow"
    assert fill.iloc[0]["residual_value"] == pytest.approx(186.66666666666669)
    assert fill.iloc[0]["allocation_share"] == pytest.approx(1.0)
    assert fill.iloc[0]["conservation_error"] == pytest.approx(0.0)
    assert fill.iloc[0]["duplicate_output_count"] == 0
    assert fill.iloc[0]["inferred_parent_value"] == pytest.approx(266.66666666666669)
    assert fill.iloc[0]["reconstructed_parent_value"] == pytest.approx(266.66666666666669)


def test_general_missing_child_carries_base_year_when_parent_has_no_projection(tmp_path: Path) -> None:
    esto, ninth, mapping_path = _general_gas_fill_fixture(tmp_path, parent_2023=0.0)
    ninth = ninth[ninth["subtotal_results"].eq(True)].copy()

    projection, diagnostics = build_esto_projection_table(
        ninth,
        esto,
        mapping_path,
        base_year=2022,
        projection_years=[2023],
        fill_missing_ninth_sectors=True,
        owner_workflow="transformation_workflow",
    )

    values = projection.set_index("esto_flow")[2023].to_dict()
    assert values == {
        "09.06.02 Liquefaction/regasification plants": pytest.approx(30.0),
        "09.06.03 Natural gas blending plants": pytest.approx(70.0),
    }
    fill = diagnostics[diagnostics["diagnostic_type"].eq("missing_ninth_sector_fill_applied")]
    assert set(fill["allocation_method"]) == {"base_year_constant"}
    assert set(fill["base_year_continuity_error"]) == {0.0}


def test_subtotal_parent_anchor_keeps_gas_blending_when_lng_starts_later(tmp_path: Path) -> None:
    """The scenario ESTO table excludes subtotal parents, but allocation needs one."""
    anchor_esto = pd.DataFrame(
        [
            {"economy": "20USA", "flows": "09.06 Gas processing plants", "products": "08.01 Natural gas", "is_subtotal": True, "2022": 46.94349},
            {"economy": "20USA", "flows": "09.06.03 Natural gas blending plants", "products": "08.01 Natural gas", "is_subtotal": False, "2022": 46.94349},
            {"economy": "20USA", "flows": "09.06.02 Liquefaction/regasification plants", "products": "08.01 Natural gas", "is_subtotal": False, "2022": 0.0},
        ]
    )
    filtered_esto = anchor_esto.loc[~anchor_esto["is_subtotal"]].copy()
    ninth = pd.DataFrame(
        [
            {"economy": "20_USA", "scenarios": "target", "sectors": "09_total_transformation_sector", "sub1sectors": "09_06_gas_processing_plants", "sub2sectors": "x", "sub3sectors": "x", "sub4sectors": "x", "fuels": "08_gas", "subfuels": "08_01_natural_gas", "subtotal_results": False, 2023: 0.0},
            {"economy": "20_USA", "scenarios": "target", "sectors": "09_total_transformation_sector", "sub1sectors": "09_06_gas_processing_plants", "sub2sectors": "09_06_03_natural_gas_blending_plants", "sub3sectors": "x", "sub4sectors": "x", "fuels": "08_gas", "subfuels": "08_01_natural_gas", "subtotal_results": False, 2023: 0.0},
            {"economy": "20_USA", "scenarios": "target", "sectors": "09_total_transformation_sector", "sub1sectors": "09_06_gas_processing_plants", "sub2sectors": "09_06_02_liquefaction_regasification_plants", "sub3sectors": "x", "sub4sectors": "x", "fuels": "08_gas", "subfuels": "08_01_natural_gas", "subtotal_results": False, 2023: -100.0},
        ]
    )
    mapping_path = tmp_path / "mapping.xlsx"
    pd.DataFrame(
        [
            {"ninth_sector": "09_06_gas_processing_plants", "ninth_fuel": "08_01_natural_gas", "esto_flow": "09.06 Gas processing plants", "esto_product": "08.01 Natural gas"},
            {"ninth_sector": "09_06_02_liquefaction_regasification_plants", "ninth_fuel": "08_01_natural_gas", "esto_flow": "09.06.02 Liquefaction/regasification plants", "esto_product": "08.01 Natural gas"},
        ]
    ).to_excel(mapping_path, index=False)

    projection, diagnostics = build_esto_projection_table(
        ninth,
        filtered_esto,
        mapping_path,
        base_year=2022,
        projection_years=[2023],
        scenario="target",
        sign_stable_flows="all",
        fill_missing_ninth_sectors=True,
        owner_workflow="transformation_workflow",
        allocation_anchor_esto_data=anchor_esto,
    )

    values = projection.set_index("esto_flow")[2023].to_dict()
    assert values["09.06.02 Liquefaction/regasification plants"] == pytest.approx(-100.0)
    assert values["09.06.03 Natural gas blending plants"] == pytest.approx(46.94349)
    fill = diagnostics[diagnostics["diagnostic_type"].eq("missing_ninth_sector_fill_applied")]
    assert set(fill["allocation_method"]) == {"base_year_constant"}


def test_general_missing_child_infers_parent_from_surviving_child(tmp_path: Path) -> None:
    esto, ninth, mapping_path = _general_gas_fill_fixture(tmp_path, parent_2023=0.0)
    # The parent is unavailable, but one child has a real 9th projection.  It
    # must remain untouched while its missing sibling scales with it.
    ninth.loc[ninth["sub2sectors"].eq("09_06_02_liquefaction_regasification_plants"), 2023] = 90.0

    projection, diagnostics = build_esto_projection_table(
        ninth,
        esto,
        mapping_path,
        base_year=2022,
        projection_years=[2023],
        fill_missing_ninth_sectors=True,
        owner_workflow="transformation_workflow",
    )

    values = projection.set_index("esto_flow")[2023].to_dict()
    assert values["09.06.02 Liquefaction/regasification plants"] == pytest.approx(90.0)
    assert values["09.06.03 Natural gas blending plants"] == pytest.approx(210.0)
    fill = diagnostics[diagnostics["diagnostic_type"].eq("missing_ninth_sector_fill_applied")]
    assert set(fill["allocation_method"]) == {"inferred_parent_from_protected_children"}
    assert fill.iloc[0]["inferred_parent_value"] == pytest.approx(300.0)
    assert fill.iloc[0]["reconstructed_parent_value"] == pytest.approx(300.0)


def test_general_parent_without_projected_children_splits_all_children(tmp_path: Path) -> None:
    esto, ninth, mapping_path = _general_gas_fill_fixture(tmp_path, parent_2023=200.0)
    ninth = ninth[ninth["subtotal_results"].eq(True)].copy()

    projection, diagnostics = build_esto_projection_table(
        ninth,
        esto,
        mapping_path,
        base_year=2022,
        projection_years=[2023],
        fill_missing_ninth_sectors=True,
        owner_workflow="transformation_workflow",
    )

    values = projection.set_index("esto_flow")[2023].to_dict()
    assert values == {
        "09.06.02 Liquefaction/regasification plants": pytest.approx(60.0),
        "09.06.03 Natural gas blending plants": pytest.approx(140.0),
    }
    fill = diagnostics[diagnostics["diagnostic_type"].eq("missing_ninth_sector_fill_applied")]
    assert set(fill["allocation_method"]) == {"parent_base_year_share"}


def test_coal_zero_parent_uses_surviving_child_to_reconstruct_missing_sibling(tmp_path: Path) -> None:
    esto = pd.DataFrame([
        {"economy": "01AUS", "flows": "09.08 Coal transformation", "products": "02.01 Coke oven coke", "is_subtotal": True, "2022": 100.0},
        {"economy": "01AUS", "flows": "09.08.01 Coke ovens", "products": "02.01 Coke oven coke", "is_subtotal": False, "2022": 30.0},
        {"economy": "01AUS", "flows": "09.08.02 Blast furnaces", "products": "02.01 Coke oven coke", "is_subtotal": False, "2022": 70.0},
    ])
    ninth = pd.DataFrame([
        {"economy": "01_AUS", "scenarios": "reference", "sectors": "09_total_transformation_sector", "sub1sectors": "09_08_coal_transformation", "sub2sectors": "x", "sub3sectors": "x", "sub4sectors": "x", "fuels": "02_01_coke_oven_coke", "subfuels": "x", "subtotal_results": True, 2023: 0.0},
        {"economy": "01_AUS", "scenarios": "reference", "sectors": "09_total_transformation_sector", "sub1sectors": "09_08_coal_transformation", "sub2sectors": "09_08_01_coke_ovens", "sub3sectors": "x", "sub4sectors": "x", "fuels": "02_01_coke_oven_coke", "subfuels": "x", "subtotal_results": False, 2023: 90.0},
    ])
    mapping_path = tmp_path / "coal_mapping.xlsx"
    pd.DataFrame([
        {"ninth_sector": "09_08_coal_transformation", "ninth_fuel": "02_01_coke_oven_coke", "esto_flow": "09.08 Coal transformation", "esto_product": "02.01 Coke oven coke"},
        {"ninth_sector": "09_08_01_coke_ovens", "ninth_fuel": "02_01_coke_oven_coke", "esto_flow": "09.08.01 Coke ovens", "esto_product": "02.01 Coke oven coke"},
    ]).to_excel(mapping_path, index=False)

    projection, diagnostics = build_esto_projection_table(
        ninth,
        esto,
        mapping_path,
        base_year=2022,
        projection_years=[2023],
        sign_stable_flows="all",
        fill_missing_ninth_sectors=True,
        owner_workflow="transformation_workflow",
    )

    values = projection.set_index("esto_flow")[2023].to_dict()
    assert values["09.08.01 Coke ovens"] == pytest.approx(90.0)
    assert values["09.08.02 Blast furnaces"] == pytest.approx(210.0)
    fill = diagnostics[diagnostics["diagnostic_type"].eq("missing_ninth_sector_fill_applied")]
    assert set(fill["allocation_method"]) == {"inferred_parent_from_protected_children"}


def test_gas_fill_flag_off_keeps_legacy_parent_residual_result(tmp_path: Path) -> None:
    esto, ninth, mapping_path = _general_gas_fill_fixture(tmp_path)

    projection, diagnostics = build_esto_projection_table(
        ninth,
        esto,
        mapping_path,
        base_year=2022,
        projection_years=[2023],
        fill_missing_ninth_sectors=False,
        owner_workflow="transformation_workflow",
    )

    assert projection.set_index("esto_flow")[2023].to_dict() == {
        "09.06.02 Liquefaction/regasification plants": pytest.approx(80.0),
        "09.06.03 Natural gas blending plants": pytest.approx(120.0),
    }
    assert not diagnostics.get("diagnostic_type", pd.Series(dtype=object)).eq(
        "missing_ninth_sector_fill_applied"
    ).any()


def test_general_missing_child_wrong_owner_does_not_fill(tmp_path: Path) -> None:
    esto, ninth, mapping_path = _general_gas_fill_fixture(tmp_path)

    projection, _ = build_esto_projection_table(
        ninth,
        esto,
        mapping_path,
        base_year=2022,
        projection_years=[2023],
        fill_missing_ninth_sectors=True,
        owner_workflow="supply_workflow",
    )

    assert projection.set_index("esto_flow")[2023].to_dict() == {
        "09.06.02 Liquefaction/regasification plants": pytest.approx(80.0),
        "09.06.03 Natural gas blending plants": pytest.approx(120.0),
    }


def test_general_missing_children_with_zero_signed_profile_remain_unallocated(tmp_path: Path) -> None:
    esto, ninth, mapping_path = _general_gas_fill_fixture(tmp_path)
    esto.loc[esto["flows"].eq("09.06.02 Liquefaction/regasification plants"), "2022"] = 30.0
    esto.loc[esto["flows"].eq("09.06.03 Natural gas blending plants"), "2022"] = -30.0
    ninth = ninth[ninth["subtotal_results"].eq(True)].copy()

    projection, diagnostics = build_esto_projection_table(
        ninth,
        esto,
        mapping_path,
        base_year=2022,
        projection_years=[2023],
        fill_missing_ninth_sectors=True,
        owner_workflow="transformation_workflow",
    )

    assert projection.empty
    unallocated = diagnostics[
        diagnostics["diagnostic_type"].eq("missing_ninth_sector_fill_unallocated")
    ]
    assert len(unallocated) == 1
    assert unallocated.iloc[0]["allocation_method"] == "unallocated_signed_profile_net_zero"
    assert unallocated.iloc[0]["residual_value"] == pytest.approx(200.0)


def test_gas_carry_forward_preserves_net_zero_handoff_beside_new_lng_projection(
    tmp_path: Path,
) -> None:
    """USA-shaped gas works/blending history must survive new LNG activity."""
    esto = pd.DataFrame([
        {"economy": "20USA", "flows": "09.06 Gas processing plants", "products": "01.05 Lignite", "is_subtotal": True, "2022": -71.766956},
        {"economy": "20USA", "flows": "09.06 Gas processing plants", "products": "08.01 Natural gas", "is_subtotal": True, "2022": 46.943490},
        {"economy": "20USA", "flows": "09.06 Gas processing plants", "products": "08.03 Gas works gas", "is_subtotal": True, "2022": 0.0},
        {"economy": "20USA", "flows": "09.06.01 Gas works plants", "products": "01.05 Lignite", "is_subtotal": False, "2022": -71.766956},
        {"economy": "20USA", "flows": "09.06.01 Gas works plants", "products": "08.03 Gas works gas", "is_subtotal": False, "2022": 46.943101},
        # Projection merging retains future-only LNG child rows as explicit
        # zeros in the ESTO-shaped table. They must not block the historical
        # blending carry-forward.
        {"economy": "20USA", "flows": "09.06.02 Liquefaction/regasification plants", "products": "08.01 Natural gas", "is_subtotal": False, "2022": 0.0},
        {"economy": "20USA", "flows": "09.06.02 Liquefaction/regasification plants", "products": "08.02 LNG", "is_subtotal": False, "2022": 0.0},
        {"economy": "20USA", "flows": "09.06.03 Natural gas blending plants", "products": "08.03 Gas works gas", "is_subtotal": False, "2022": -46.943101},
        {"economy": "20USA", "flows": "09.06.03 Natural gas blending plants", "products": "08.01 Natural gas", "is_subtotal": False, "2022": 46.943490},
    ])
    ninth_rows = []
    for fuel, value in [
        ("01_05_lignite", 0.0),
        ("08_01_natural_gas", 0.0),
        ("08_02_lng", 0.0),
        ("08_03_gas_works_gas", 0.0),
    ]:
        ninth_rows.append({"economy": "20_USA", "scenarios": "target", "sectors": "09_total_transformation_sector", "sub1sectors": "09_06_gas_processing_plants", "sub2sectors": "x", "sub3sectors": "x", "sub4sectors": "x", "fuels": fuel, "subfuels": "x", "subtotal_results": False, 2023: value})
    ninth_rows.extend([
        {"economy": "20_USA", "scenarios": "target", "sectors": "09_total_transformation_sector", "sub1sectors": "09_06_gas_processing_plants", "sub2sectors": "09_06_01_gas_works_plants", "sub3sectors": "x", "sub4sectors": "x", "fuels": "01_coal", "subfuels": "01_05_lignite", "subtotal_results": False, 2023: 0.0},
        {"economy": "20_USA", "scenarios": "target", "sectors": "09_total_transformation_sector", "sub1sectors": "09_06_gas_processing_plants", "sub2sectors": "09_06_01_gas_works_plants", "sub3sectors": "x", "sub4sectors": "x", "fuels": "08_gas", "subfuels": "08_03_gas_works_gas", "subtotal_results": False, 2023: 0.0},
        {"economy": "20_USA", "scenarios": "target", "sectors": "09_total_transformation_sector", "sub1sectors": "09_06_gas_processing_plants", "sub2sectors": "09_06_03_natural_gas_blending_plants", "sub3sectors": "x", "sub4sectors": "x", "fuels": "08_gas", "subfuels": "08_01_natural_gas", "subtotal_results": False, 2023: 0.0},
        {"economy": "20_USA", "scenarios": "target", "sectors": "09_total_transformation_sector", "sub1sectors": "09_06_gas_processing_plants", "sub2sectors": "09_06_03_natural_gas_blending_plants", "sub3sectors": "x", "sub4sectors": "x", "fuels": "08_gas", "subfuels": "08_03_gas_works_gas", "subtotal_results": False, 2023: 0.0},
        {"economy": "20_USA", "scenarios": "target", "sectors": "09_total_transformation_sector", "sub1sectors": "09_06_gas_processing_plants", "sub2sectors": "09_06_02_liquefaction_regasification_plants", "sub3sectors": "x", "sub4sectors": "x", "fuels": "08_gas", "subfuels": "08_01_natural_gas", "subtotal_results": False, 2023: -100.0},
        {"economy": "20_USA", "scenarios": "target", "sectors": "09_total_transformation_sector", "sub1sectors": "09_06_gas_processing_plants", "sub2sectors": "09_06_02_liquefaction_regasification_plants", "sub3sectors": "x", "sub4sectors": "x", "fuels": "08_gas", "subfuels": "08_02_lng", "subtotal_results": False, 2023: 100.0},
    ])
    mapping_path = tmp_path / "usa_gas_mapping.xlsx"
    pd.DataFrame([
        {"ninth_sector": "09_06_gas_processing_plants", "ninth_fuel": "01_05_lignite", "esto_flow": "09.06 Gas processing plants", "esto_product": "01.05 Lignite"},
        {"ninth_sector": "09_06_gas_processing_plants", "ninth_fuel": "08_01_natural_gas", "esto_flow": "09.06 Gas processing plants", "esto_product": "08.01 Natural gas"},
        {"ninth_sector": "09_06_gas_processing_plants", "ninth_fuel": "08_03_gas_works_gas", "esto_flow": "09.06 Gas processing plants", "esto_product": "08.03 Gas works gas"},
        {"ninth_sector": "09_06_01_gas_works_plants", "ninth_fuel": "01_05_lignite", "esto_flow": "09.06.01 Gas works plants", "esto_product": "01.05 Lignite"},
        {"ninth_sector": "09_06_01_gas_works_plants", "ninth_fuel": "08_03_gas_works_gas", "esto_flow": "09.06.01 Gas works plants", "esto_product": "08.03 Gas works gas"},
        {"ninth_sector": "09_06_03_natural_gas_blending_plants", "ninth_fuel": "08_01_natural_gas", "esto_flow": "09.06.03 Natural gas blending plants", "esto_product": "08.01 Natural gas"},
        {"ninth_sector": "09_06_03_natural_gas_blending_plants", "ninth_fuel": "08_03_gas_works_gas", "esto_flow": "09.06.03 Natural gas blending plants", "esto_product": "08.03 Gas works gas"},
        {"ninth_sector": "09_06_02_liquefaction_regasification_plants", "ninth_fuel": "08_01_natural_gas", "esto_flow": "09.06.02 Liquefaction/regasification plants", "esto_product": "08.01 Natural gas"},
        {"ninth_sector": "09_06_02_liquefaction_regasification_plants", "ninth_fuel": "08_02_lng", "esto_flow": "09.06.02 Liquefaction/regasification plants", "esto_product": "08.02 LNG"},
    ]).to_excel(mapping_path, index=False)

    projection, diagnostics = build_esto_projection_table(
        pd.DataFrame(ninth_rows), esto, mapping_path, base_year=2022,
        projection_years=[2023], scenario="target", sign_stable_flows="all",
        fill_missing_ninth_sectors=True, owner_workflow="transformation_workflow",
    )

    values = projection.set_index(["esto_flow", "esto_product"])[2023].to_dict()
    assert values[("09.06.01 Gas works plants", "01.05 Lignite")] == pytest.approx(-71.766956)
    assert values[("09.06.01 Gas works plants", "08.03 Gas works gas")] == pytest.approx(46.943101)
    assert values[("09.06.03 Natural gas blending plants", "08.03 Gas works gas")] == pytest.approx(-46.943101)
    assert values[("09.06.03 Natural gas blending plants", "08.01 Natural gas")] == pytest.approx(46.943490)
    assert values[("09.06.02 Liquefaction/regasification plants", "08.01 Natural gas")] == pytest.approx(-100.0)
    assert values[("09.06.02 Liquefaction/regasification plants", "08.02 LNG")] == pytest.approx(100.0)
    assert not diagnostics["diagnostic_type"].eq(
        "missing_ninth_sector_fill_unallocated"
    ).any()


def test_apec_aggregate_is_a_stress_fixture_not_a_production_fallback() -> None:
    repo = Path(__file__).resolve().parents[1]
    ninth_path = repo / "data" / "9th merged_file_energy_00_APEC_20251106.csv"
    esto_path = repo / "data" / "00APEC_2025_low_with_subtotals.csv"
    mapping_path = (
        repo.parent
        / "leap_mappings"
        / "config"
        / "outlook_mappings_master.xlsx"
    )
    if not ninth_path.exists() or not esto_path.exists() or not mapping_path.exists():
        pytest.skip("APEC aggregate validation inputs are not available")

    ninth = pd.read_csv(
        ninth_path,
        usecols=[
            "economy", "scenarios", "sectors", "sub1sectors", "sub2sectors",
            "sub3sectors", "sub4sectors", "fuels", "subfuels",
            "subtotal_results", "2023", "2030", "2050",
        ],
        low_memory=False,
    )
    for year in (2023, 2030, 2050):
        source_column = str(year)
        ninth[year] = pd.to_numeric(ninth[source_column], errors="coerce").fillna(0.0)
        ninth = ninth.drop(columns=[source_column])

    esto = pd.read_csv(
        esto_path,
        usecols=["economy", "flows", "products", "is_subtotal", "2022"],
        low_memory=False,
    )
    esto = add_all_economy_total(esto, ["2022"], economy_label="00_APEC")
    projection, diagnostics = build_esto_projection_table(
        ninth,
        esto,
        (mapping_path, "ninth_pairs_to_esto_pairs"),
        base_year=2022,
        projection_years=[2023, 2030, 2050],
        scenario="reference",
        sign_stable_flows="all",
    )

    coal = projection[
        projection["esto_flow"].astype(str).str.startswith("09.08.")
    ]
    assert set(coal["esto_flow"]) == {
        "09.08.01 Coke ovens",
        "09.08.02 Blast furnaces",
        "09.08.03 Patent fuel plants",
        "09.08.04 BKB/PB plants",
        "09.08.05 Liquefaction (coal to oil)",
    }
    assert not diagnostics["diagnostic_type"].eq("conservation_mismatch").any()
