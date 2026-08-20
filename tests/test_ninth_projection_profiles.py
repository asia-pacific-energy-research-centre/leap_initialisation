import pandas as pd
import pytest
from pathlib import Path

from codebase.functions.ninth_projection_mapping import (
    build_esto_projection_table,
    build_economy_specific_child_flow_profiles,
    build_ninth_projection_series,
    drop_ninth_parent_fuel_rows,
    filter_ninth_projection_rows,
    _build_parent_child_reconciliation_diagnostics,
)
from codebase.functions.esto_data_utils import add_all_economy_total


def test_ninth_fuel_parent_rollup_is_excluded_but_leaf_fuels_and_sector_parents_remain() -> None:
    common = {
        "scenarios": "reference",
        "economy": "10_MAS",
        "sectors": "09_total_transformation_sector",
        "sub1sectors": "09_06_gas_processing_plants",
        "sub2sectors": "09_06_02_liquefaction_regasification_plants",
        "sub3sectors": "x",
        "sub4sectors": "x",
        "subtotal_results": False,
        2022: 1.0,
    }
    ninth = pd.DataFrame([
        {**common, "fuels": "08_gas", "subfuels": "x", 2022: -579.888547},
        {**common, "fuels": "08_gas", "subfuels": "08_01_natural_gas", 2022: -1678.672339},
        {**common, "fuels": "08_gas", "subfuels": "08_02_lng", 2022: 1098.783792},
        {**common, "fuels": "17_electricity", "subfuels": "x", 2022: -12.0},
        # A sector parent is a separate hierarchy concern and must be retained.
        {**common, "sub2sectors": "x", "fuels": "08_gas", "subfuels": "08_01_natural_gas", 2022: -2000.0},
    ])

    result = drop_ninth_parent_fuel_rows(ninth)

    assert not ((result["fuels"] == "08_gas") & (result["subfuels"] == "x")).any()
    assert set(result.loc[result["fuels"] == "08_gas", "subfuels"]) == {"08_01_natural_gas", "08_02_lng"}
    assert (result["fuels"] == "17_electricity").any()
    assert ((result["sub2sectors"] == "x") & (result["subfuels"] == "08_01_natural_gas")).any()


def test_projection_filter_removes_fuel_parent_rollups_after_subtotal_filtering() -> None:
    ninth = pd.DataFrame([
        {
            "scenarios": "reference", "economy": "10_MAS",
            "sectors": "09_total_transformation_sector",
            "sub1sectors": "09_06_gas_processing_plants",
            "sub2sectors": "09_06_02_liquefaction_regasification_plants",
            "fuels": "08_gas", "subfuels": "x", "subtotal_results": False, 2023: -10.0,
        },
        {
            "scenarios": "reference", "economy": "10_MAS",
            "sectors": "09_total_transformation_sector",
            "sub1sectors": "09_06_gas_processing_plants",
            "sub2sectors": "09_06_02_liquefaction_regasification_plants",
            "fuels": "08_gas", "subfuels": "08_01_natural_gas", "subtotal_results": False, 2023: -10.0,
        },
        {
            "scenarios": "reference", "economy": "10_MAS",
            "sectors": "09_total_transformation_sector",
            "sub1sectors": "09_06_gas_processing_plants",
            "sub2sectors": "09_06_02_liquefaction_regasification_plants",
            "fuels": "08_gas", "subfuels": "08_02_lng", "subtotal_results": True, 2023: 10.0,
        },
    ])

    result = filter_ninth_projection_rows(ninth)

    assert result[["fuels", "subfuels"]].to_dict("records") == [
        {"fuels": "08_gas", "subfuels": "08_01_natural_gas"}
    ]


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
