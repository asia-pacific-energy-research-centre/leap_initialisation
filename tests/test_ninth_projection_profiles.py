import pandas as pd
import pytest
from pathlib import Path

from codebase.functions.ninth_projection_mapping import (
    build_esto_projection_table,
    build_economy_specific_child_flow_profiles,
)
from codebase.functions.esto_data_utils import add_all_economy_total


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
