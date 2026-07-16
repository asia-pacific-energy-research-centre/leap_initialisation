from __future__ import annotations

import pandas as pd
import pytest

from codebase import other_loss_own_use_proxy_workflow as workflow
from codebase.functions.other_loss_own_use_proxy_utils import build_proxy_source_coverage_gaps


def _coal_config() -> dict[str, object]:
    return workflow.PROXY_CONFIG[0]


def test_proxy_source_coverage_gaps_are_filtered_to_requested_economy() -> None:
    esto = pd.DataFrame([
        {
            "economy": "20USA",
            "economy_key": "20_USA",
            "flows": "10.99 Test own use",
            "products": "01.01 Coking coal",
            "is_subtotal": False,
            2022: 1.0,
        },
        {
            "economy": "01AUS",
            "economy_key": "01_AUS",
            "flows": "10.98 Different own use",
            "products": "02.01 Coke oven coke",
            "is_subtotal": False,
            2022: 2.0,
        },
    ])

    gaps = build_proxy_source_coverage_gaps(
        esto_data=esto,
        ninth_data=pd.DataFrame(),
        configs=[],
        economy="20_USA",
        base_year=2022,
        final_year=2060,
    )

    assert len(gaps) == 1
    assert gaps.iloc[0]["source_code"] == "10.99 Test own use"


def test_source_coverage_uses_nested_target_sector_config() -> None:
    """Configured 9th target sectors must not become false-positive gaps."""
    config = workflow.make_proxy_config(
        enabled=True,
        process_key="electricity_chp_and_heat_plants",
        process_label="Electricity, CHP and heat plants",
        esto_target_flows=["10.01.01 Electricity, CHP and heat plants"],
        ninth_target_sectors=["10_01_01_electricity_chp_and_heat_plants"],
    )
    ninth = pd.DataFrame([
        {
            "economy_key": "02_BD",
            "scenarios": "target",
            "sectors": "10_01_01_electricity_chp_and_heat_plants",
            "sub1sectors": "x",
            "sub2sectors": "x",
            "sub3sectors": "x",
            "sub4sectors": "x",
            "fuels": "17_electricity",
            "subfuels": "x",
            "subtotal_layout": False,
            "subtotal_results": False,
            2023: -20.0,
        }
    ])

    gaps = build_proxy_source_coverage_gaps(
        esto_data=pd.DataFrame(),
        ninth_data=ninth,
        configs=[config],
        economy="02_BD",
        base_year=2022,
        final_year=2023,
    )

    assert gaps.empty


def test_proxy_config_scaffolds_all_own_use_children() -> None:
    expected = {
        "10_01_01_electricity_chp_and_heat_plants",
        "10_01_02_gas_works_plants",
        "10_01_03_liquefaction_regasification_plants",
        "10_01_04_gastoliquids_plants",
        "10_01_05_coke_ovens",
        "10_01_06_coal_mines",
        "10_01_07_blast_furnaces",
        "10_01_08_patent_fuel_plants",
        "10_01_09_bkb_pb_plants",
        "10_01_10_liquefaction_plants_coal_to_oil",
        "10_01_11_oil_refineries",
        "10_01_12_oil_and_gas_extraction",
        "10_01_13_pump_storage_plants",
        "10_01_14_nuclear_industry",
        "10_01_15_charcoal_production_plants",
        "10_01_16_gasification_plants_for_biogases",
        "10_01_17_nonspecified_own_uses",
        "10_01_18_ccs",
        "10_02_transmission_and_distribution_losses",
    }
    actual = {
        sector
        for cfg in workflow.PROXY_CONFIG
        for sector in cfg["target_sources"]["ninth"]["sector_codes"]
    }

    assert actual == expected
    disabled = {cfg["process_key"] for cfg in workflow.PROXY_CONFIG if not cfg.get("enabled")}
    assert "ccs" in disabled
    assert "oil_refineries" in disabled
    assert disabled == {
        "gas_works_plants", "gas_to_liquids_plants", "coke_ovens", "blast_furnaces",
        "patent_fuel_plants", "bkb_pb_plants", "liquefaction_plants_coal_to_oil",
        "oil_refineries", "charcoal_production_plants", "ccs",
    }


def test_09_08_configs_use_detailed_ninth_activity_before_parent_fallback() -> None:
    expected = {
        "coke_ovens": ("09_08_01_coke_ovens", ["02_01_coke_oven_coke", "02_03_coke_oven_gas", "02_07_coal_tar"]),
        "blast_furnaces": ("09_08_02_blast_furnaces", ["02_04_blast_furnace_gas"]),
        "patent_fuel_plants": ("09_08_03_patent_fuel_plants", ["02_06_patent_fuel"]),
        "bkb_pb_plants": ("09_08_04_bkb_pb_plants", ["02_08_bkb_pb"]),
        "liquefaction_plants_coal_to_oil": (
            "09_08_05_liquefaction_coal_to_oil",
            ["07_09_lpg", "07_03_naphtha", "07_07_gas_diesel_oil", "07_08_fuel_oil", "07_x_other_petroleum_products"],
        ),
    }
    configs = {cfg["process_key"]: cfg for cfg in workflow.PROXY_CONFIG if cfg["process_key"] in expected}

    assert set(configs) == set(expected)
    for process_key, (sector, subfuels) in expected.items():
        ninth = configs[process_key]["activity_sources"]["ninth"]
        assert ninth["sector_codes"] == [sector]
        assert ninth["subfuels"] == subfuels


def test_projected_ninth_activity_keeps_layout_subtotal_rows() -> None:
    cfg = workflow.make_proxy_config(
        enabled=True,
        process_key="test",
        process_label="Test",
        activity_label="Test",
        esto_activity_flows=["09.08.02 Blast furnaces"],
        ninth_activity_sectors=["09_08_coal_transformation"],
        activity_value_mode="positive_only",
        esto_target_flows=[],
        ninth_target_sectors=[],
    )
    ninth = pd.DataFrame(
        [
            {
                "economy_key": "20_USA",
                "sectors": "09_total_transformation_sector",
                "sub1sectors": "09_08_coal_transformation",
                "sub2sectors": "x",
                "sub3sectors": "x",
                "sub4sectors": "x",
                "fuels": "02_coal_products",
                "subfuels": "x",
                "subtotal_layout": True,
                "subtotal_results": False,
                2023: 12.0,
            },
            {
                "economy_key": "20_USA",
                "sectors": "09_total_transformation_sector",
                "sub1sectors": "09_08_coal_transformation",
                "sub2sectors": "09_08_02_blast_furnaces",
                "sub3sectors": "x",
                "sub4sectors": "x",
                "fuels": "02_coal_products",
                "subfuels": "x",
                "subtotal_layout": False,
                "subtotal_results": False,
                2023: 0.0,
            },
        ]
    )

    series = workflow.build_ninth_proxy_activity_series(
        ninth_data=ninth,
        economy="20_USA",
        config=cfg,
        base_year=2022,
        final_year=2023,
    )

    assert series[2023] == 12.0


def test_ninth_projection_activity_is_zero_when_esto_activity_subsector_absent() -> None:
    cfg = workflow.make_proxy_config(
        enabled=True,
        process_key="test",
        process_label="Test",
        activity_label="Test",
        esto_activity_flows=["09.08.02 Blast furnaces"],
        esto_activity_exact_products=["02.04 Blast furnace gas"],
        ninth_activity_sectors=["09_08_coal_transformation"],
        activity_value_mode="positive_only",
        esto_target_flows=[],
        ninth_target_sectors=[],
    )
    esto = pd.DataFrame(
        [
            {
                "economy": "20USA",
                "economy_key": "20_USA",
                "flows": "09.08.01 Coke ovens",
                "products": "02.01 Coke oven coke",
                2022: 1.0,
            }
        ]
    )
    ninth = pd.DataFrame(
        [
            {
                "economy_key": "20_USA",
                "sectors": "09_total_transformation_sector",
                "sub1sectors": "09_08_coal_transformation",
                "sub2sectors": "x",
                "sub3sectors": "x",
                "sub4sectors": "x",
                "fuels": "02_coal_products",
                "subfuels": "x",
                "subtotal_layout": True,
                "subtotal_results": False,
                2023: 12.0,
            }
        ]
    )

    series = workflow.build_proxy_activity_series(
        esto_data=esto,
        ninth_data=ninth,
        economy="20_USA",
        config=cfg,
        base_year=2022,
        final_year=2023,
    )

    assert series[2022] == 0.0
    assert series[2023] == 0.0


def test_ninth_activity_falls_back_to_parent_when_child_activity_is_zero() -> None:
    cfg = workflow.make_proxy_config(
        enabled=True,
        process_key="test",
        process_label="Test",
        activity_label="Test",
        esto_activity_flows=["09.08.02 Blast furnaces"],
        esto_activity_exact_products=["02.04 Blast furnace gas"],
        ninth_activity_sectors=["09_08_02_blast_furnaces"],
        ninth_activity_fuels=["02_coal_products"],
        ninth_activity_subfuels=["02_04_blast_furnace_gas"],
        activity_value_mode="positive_only",
        esto_target_flows=[],
        ninth_target_sectors=[],
    )
    ninth = pd.DataFrame(
        [
            {
                "economy_key": "20_USA",
                "sectors": "09_total_transformation_sector",
                "sub1sectors": "09_08_coal_transformation",
                "sub2sectors": "x",
                "sub3sectors": "x",
                "sub4sectors": "x",
                "fuels": "02_coal_products",
                "subfuels": "x",
                "subtotal_layout": True,
                "subtotal_results": False,
                2023: 12.0,
            },
            {
                "economy_key": "20_USA",
                "sectors": "09_total_transformation_sector",
                "sub1sectors": "09_08_coal_transformation",
                "sub2sectors": "09_08_02_blast_furnaces",
                "sub3sectors": "x",
                "sub4sectors": "x",
                "fuels": "02_coal_products",
                "subfuels": "02_04_blast_furnace_gas",
                "subtotal_layout": False,
                "subtotal_results": False,
                2023: 0.0,
            },
        ]
    )

    series, fallback = workflow.build_ninth_proxy_activity_series_with_fallback(
        ninth_data=ninth,
        economy="20_USA",
        config=cfg,
        base_year=2022,
        final_year=2023,
    )

    assert series[2023] == 12.0
    assert fallback is not None
    assert fallback["original_ninth_activity_sectors"] == "09_08_02_blast_furnaces"
    assert fallback["fallback_ninth_activity_sectors"] == "09_08_coal_transformation"


def test_activity_source_fallback_report_requires_esto_activity() -> None:
    cfg = workflow.make_proxy_config(
        enabled=True,
        process_key="test",
        process_label="Test",
        activity_label="Test",
        esto_activity_flows=["09.08.02 Blast furnaces"],
        esto_activity_exact_products=["02.04 Blast furnace gas"],
        ninth_activity_sectors=["09_08_02_blast_furnaces"],
        ninth_activity_fuels=["02_coal_products"],
        ninth_activity_subfuels=["02_04_blast_furnace_gas"],
        activity_value_mode="positive_only",
        esto_target_flows=[],
        ninth_target_sectors=[],
    )
    esto = pd.DataFrame(
        [
            {
                "economy": "20USA",
                "economy_key": "20_USA",
                "flows": "09.08.02 Blast furnaces",
                "products": "02.04 Blast furnace gas",
                2022: 5.0,
            }
        ]
    )
    ninth = pd.DataFrame(
        [
            {
                "economy_key": "20_USA",
                "sectors": "09_total_transformation_sector",
                "sub1sectors": "09_08_coal_transformation",
                "sub2sectors": "x",
                "sub3sectors": "x",
                "sub4sectors": "x",
                "fuels": "02_coal_products",
                "subfuels": "x",
                "subtotal_layout": True,
                "subtotal_results": False,
                2023: 12.0,
            },
            {
                "economy_key": "20_USA",
                "sectors": "09_total_transformation_sector",
                "sub1sectors": "09_08_coal_transformation",
                "sub2sectors": "09_08_02_blast_furnaces",
                "sub3sectors": "x",
                "sub4sectors": "x",
                "fuels": "02_coal_products",
                "subfuels": "02_04_blast_furnace_gas",
                "subtotal_layout": False,
                "subtotal_results": False,
                2023: 0.0,
            },
        ]
    )

    report = workflow.build_activity_source_fallback_report(
        esto_data=esto,
        ninth_data=ninth,
        economy="20_USA",
        configs=[cfg],
        base_year=2022,
        final_year=2023,
    )

    assert len(report) == 1
    assert report.iloc[0]["fallback_ninth_activity_sectors"] == "09_08_coal_transformation"
    assert report.iloc[0]["fallback_activity_total"] == 12.0


def test_drop_ninth_parent_fuel_rows_when_child_rows_exist() -> None:
    df = pd.DataFrame(
        [
            {
                "scenarios": "reference",
                "economy": "20_USA",
                "sectors": "01_production",
                "sub1sectors": "x",
                "sub2sectors": "x",
                "sub3sectors": "x",
                "sub4sectors": "x",
                "fuels": "01_coal",
                "subfuels": "01_01_coking_coal",
                2023: 10.0,
            },
            {
                "scenarios": "reference",
                "economy": "20_USA",
                "sectors": "01_production",
                "sub1sectors": "x",
                "sub2sectors": "x",
                "sub3sectors": "x",
                "sub4sectors": "x",
                "fuels": "01_coal",
                "subfuels": "x",
                2023: 10.0,
            },
            {
                "scenarios": "reference",
                "economy": "20_USA",
                "sectors": "01_production",
                "sub1sectors": "x",
                "sub2sectors": "x",
                "sub3sectors": "x",
                "sub4sectors": "x",
                "fuels": "17_electricity",
                "subfuels": "x",
                2023: 5.0,
            },
        ]
    )

    out = workflow._drop_ninth_parent_fuel_rows(df)

    assert len(out) == 2
    assert out[2023].sum() == 15.0
    assert "17_electricity" in set(out["fuels"])


def test_coal_proxy_activity_uses_esto_base_and_ninth_projection() -> None:
    esto = pd.DataFrame(
        [
            {
                "economy": "20USA",
                "economy_key": "20_USA",
                "flows": "01 Production",
                "products": "01.01 Coking coal",
                2022: 100.0,
            },
            {
                "economy": "20USA",
                "economy_key": "20_USA",
                "flows": "01 Production",
                "products": "02.01 Coke oven coke",
                2022: 20.0,
            },
            {
                "economy": "20USA",
                "economy_key": "20_USA",
                "flows": "01 Production",
                "products": "07.01 Motor gasoline",
                2022: 999.0,
            },
        ]
    )
    ninth = pd.DataFrame(
        [
            {
                "economy_key": "20_USA",
                "sectors": "01_production",
                "sub1sectors": "x",
                "sub2sectors": "x",
                "sub3sectors": "x",
                "sub4sectors": "x",
                "fuels": "01_coal",
                "subfuels": "01_01_coking_coal",
                2023: 200.0,
            },
            {
                "economy_key": "20_USA",
                "sectors": "01_production",
                "sub1sectors": "x",
                "sub2sectors": "x",
                "sub3sectors": "x",
                "sub4sectors": "x",
                "fuels": "02_coal_products",
                "subfuels": "x",
                2023: 30.0,
            },
            {
                "economy_key": "20_USA",
                "sectors": "01_production",
                "sub1sectors": "x",
                "sub2sectors": "x",
                "sub3sectors": "x",
                "sub4sectors": "x",
                "fuels": "07_petroleum_products",
                "subfuels": "07_01_motor_gasoline",
                2023: 999.0,
            },
        ]
    )

    activity = workflow.build_proxy_activity_series(
        esto_data=esto,
        ninth_data=ninth,
        economy="20_USA",
        config=_coal_config(),
        base_year=2022,
        final_year=2023,
    )

    assert activity == {2022: 120.0, 2023: 230.0}


def test_detail_table_calculates_abs_target_over_activity() -> None:
    esto = pd.DataFrame(
        [
            {
                "economy": "20USA",
                "economy_key": "20_USA",
                "flows": "01 Production",
                "products": "01.01 Coking coal",
                2022: 100.0,
            },
            {
                "economy": "20USA",
                "economy_key": "20_USA",
                "flows": "10.01.06 Coal mines",
                "products": "17 Electricity",
                2022: -5.0,
            },
        ]
    )
    ninth = pd.DataFrame(
        [
            {
                "economy_key": "20_USA",
                "sectors": "01_production",
                "sub1sectors": "x",
                "sub2sectors": "x",
                "sub3sectors": "x",
                "sub4sectors": "x",
                "fuels": "01_coal",
                "subfuels": "01_01_coking_coal",
                2023: 200.0,
            },
            {
                "economy_key": "20_USA",
                "sectors": "10_losses_and_own_use",
                "sub1sectors": "10_01_own_use",
                "sub2sectors": "10_01_06_coal_mines",
                "sub3sectors": "x",
                "sub4sectors": "x",
                "fuels": "17_electricity",
                "subfuels": "x",
                2023: -8.0,
            },
        ]
    )

    detail = workflow.build_proxy_detail_table(
        esto_data=esto,
        ninth_data=ninth,
        economy="20_USA",
        configs=[_coal_config()],
        base_year=2022,
        final_year=2023,
    )

    by_year = {int(row.year): row for row in detail.itertuples(index=False)}
    assert by_year[2022].target_energy == 5.0
    assert by_year[2022].intensity == 0.05
    assert by_year[2023].target_energy == 8.0
    assert by_year[2023].intensity == 0.04


def test_target_energy_ignores_ninth_fuels_not_seen_in_esto_target() -> None:
    esto = pd.DataFrame(
        [
            {
                "economy": "20USA",
                "economy_key": "20_USA",
                "flows": "10.01.06 Coal mines",
                "products": "17 Electricity",
                2022: -5.0,
            },
        ]
    )
    ninth = pd.DataFrame(
        [
            {
                "economy_key": "20_USA",
                "sectors": "10_losses_and_own_use",
                "sub1sectors": "10_01_own_use",
                "sub2sectors": "10_01_06_coal_mines",
                "sub3sectors": "x",
                "sub4sectors": "x",
                "fuels": "17_electricity",
                "subfuels": "x",
                2023: -8.0,
            },
            {
                "economy_key": "20_USA",
                "sectors": "10_losses_and_own_use",
                "sub1sectors": "10_01_own_use",
                "sub2sectors": "10_01_06_coal_mines",
                "sub3sectors": "x",
                "sub4sectors": "x",
                "fuels": "08_gas",
                "subfuels": "08_03_gas_works_gas",
                2023: -99.0,
            },
        ]
    )

    target = workflow.build_target_energy_long(
        esto_data=esto,
        ninth_data=ninth,
        economy="20_USA",
        config=_coal_config(),
        base_year=2022,
        final_year=2023,
        fuel_mapping_lookup={"esto": {}, "ninth": {}},
    )

    assert set(target["fuel_branch_label"]) == {"Electricity"}
    assert int(target[target["source_dataset"].eq("ninth")]["target_energy"].sum()) == 8


def test_target_energy_allows_ninth_fuels_seen_in_esto_other_economies() -> None:
    esto = pd.DataFrame(
        [
            {
                "economy": "20USA",
                "economy_key": "20_USA",
                "flows": "10.01.06 Coal mines",
                "products": "17 Electricity",
                2022: -5.0,
            },
            {
                "economy": "01AUS",
                "economy_key": "01_AUS",
                "flows": "10.01.06 Coal mines",
                "products": "08.03 Gas works gas",
                2022: -1.0,
            },
        ]
    )
    ninth = pd.DataFrame(
        [
            {
                "economy_key": "20_USA",
                "sectors": "10_losses_and_own_use",
                "sub1sectors": "10_01_own_use",
                "sub2sectors": "10_01_06_coal_mines",
                "sub3sectors": "x",
                "sub4sectors": "x",
                "fuels": "08_gas",
                "subfuels": "08_03_gas_works_gas",
                2023: -9.0,
            },
        ]
    )

    target = workflow.build_target_energy_long(
        esto_data=esto,
        ninth_data=ninth,
        economy="20_USA",
        config=_coal_config(),
        base_year=2022,
        final_year=2023,
        fuel_mapping_lookup={"esto": {}, "ninth": {}},
    )

    assert "Gas works gas" in set(target["fuel_branch_label"])
    assert int(target[target["fuel_branch_label"].eq("Gas works gas")]["target_energy"].sum()) == 9


def test_target_energy_keeps_zero_rows_for_fuels_seen_in_esto_other_economies() -> None:
    esto = pd.DataFrame(
        [
            {
                "economy": "20USA",
                "economy_key": "20_USA",
                "flows": "10.01.06 Coal mines",
                "products": "08.03 Gas works gas",
                2022: 0.0,
            },
            {
                "economy": "01AUS",
                "economy_key": "01_AUS",
                "flows": "10.01.06 Coal mines",
                "products": "08.03 Gas works gas",
                2022: -1.0,
            },
        ]
    )
    ninth = pd.DataFrame(columns=["economy_key", "sectors", "sub1sectors", "sub2sectors", "sub3sectors", "sub4sectors", "fuels", "subfuels", 2023])

    target = workflow.build_target_energy_long(
        esto_data=esto,
        ninth_data=ninth,
        economy="20_USA",
        config=_coal_config(),
        base_year=2022,
        final_year=2023,
        fuel_mapping_lookup={"esto": {}, "ninth": {}},
    )

    assert set(target["fuel_branch_label"]) == {"Gas works gas"}
    assert float(target["target_energy"].sum()) == 0.0


def test_proxy_log_rows_include_zero_target_fuel_branches_by_default() -> None:
    detail = pd.DataFrame(
        [
            {
                "process_label": "Transmission and distribution losses",
                "leap_process_label": "Transmission and distribution loss",
                "fuel_branch_label": "Natural gas",
                "year": 2022,
                "proxy_activity": 100.0,
                "target_energy": 0.0,
                "intensity": 0.0,
            },
        ]
    )

    rows = workflow.build_proxy_log_rows(detail, scenario="Target")

    assert any(row["Branch_Path"].endswith("\\Transmission and distribution loss\\Natural gas") for row in rows)
    assert all("\\Other sector\\" not in row["Branch_Path"] for row in rows)
    assert any(
        row["Branch_Path"] == "Demand\\Other loss and own use\\Transmission and distribution loss\\Natural gas"
        for row in rows
    )
    assert any(
        row["Branch_Path"] == "Demand\\Other loss and own use"
        and row["Measure"] == workflow.ACTIVITY_VARIABLE
        and row["Value"] == 0.0
        for row in rows
    )
    assert any(
        row["Branch_Path"] == "Demand\\Other loss and own use\\Transmission and distribution loss"
        and row["Measure"] == workflow.ACTIVITY_VARIABLE
        and row["Value"] == 0.0
        for row in rows
    )
    assert any(
        row["Branch_Path"] == "Demand\\Other loss and own use\\Transmission and distribution loss\\Natural gas"
        and row["Measure"] == workflow.ACTIVITY_VARIABLE
        for row in rows
    )
    intensity_rows = [row for row in rows if row["Measure"] == workflow.INTENSITY_VARIABLE]
    assert intensity_rows
    assert {row["Units"] for row in intensity_rows} == {"Petajoule"}


def test_proxy_log_rows_sum_parent_activity_from_fuel_children() -> None:
    detail = pd.DataFrame(
        [
            {
                "process_label": "Blast furnaces",
                "leap_process_label": "Blast furnaces",
                "fuel_branch_label": "Coal",
                "year": 2022,
                "proxy_activity": 10.0,
                "target_energy": 1.0,
                "intensity": 0.1,
            },
            {
                "process_label": "Blast furnaces",
                "leap_process_label": "Blast furnaces",
                "fuel_branch_label": "Natural gas",
                "year": 2022,
                "proxy_activity": 20.0,
                "target_energy": 2.0,
                "intensity": 0.1,
            },
            {
                "process_label": "Coal mines",
                "leap_process_label": "Coal mines",
                "fuel_branch_label": "Electricity",
                "year": 2022,
                "proxy_activity": 5.0,
                "target_energy": 1.0,
                "intensity": 0.2,
            },
        ]
    )

    rows = workflow.build_proxy_log_rows(detail, scenario="Target")
    parent_activity = {
        row["Branch_Path"]: row["Value"]
        for row in rows
        if row["Measure"] == workflow.ACTIVITY_VARIABLE
        and row["Date"] == 2022
        and row["Branch_Path"]
        in {
            "Demand\\Other loss and own use",
            "Demand\\Other loss and own use\\Blast furnaces",
            "Demand\\Other loss and own use\\Coal mines",
        }
    }

    assert parent_activity["Demand\\Other loss and own use"] == 0.0
    assert parent_activity["Demand\\Other loss and own use\\Blast furnaces"] == 0.0
    assert parent_activity["Demand\\Other loss and own use\\Coal mines"] == 0.0


def test_output_fuel_validation_flags_fuels_not_nonzero_in_esto() -> None:
    esto_2024 = pd.DataFrame(
        [
            {
                "economy": "01AUS",
                "economy_key": "01_AUS",
                "flows": "10.01.06 Coal mines",
                "products": "17 Electricity",
                "is_subtotal": False,
                2022: -1.0,
            },
        ]
    )
    esto_2025 = esto_2024.rename(columns={2022: 2023}).copy()
    detail = pd.DataFrame(
        [
            {
                "process_key": "coal_mines",
                "process_label": "Coal mines",
                "fuel_branch_label": "Electricity",
            },
            {
                "process_key": "coal_mines",
                "process_label": "Coal mines",
                "fuel_branch_label": "Natural gas",
            },
        ]
    )

    out = workflow.build_output_fuel_esto_validation(
        esto_data=esto_2024,
        detail_df=detail,
        configs=[_coal_config()],
        base_year=2022,
        fuel_mapping_lookup={"esto": {}, "ninth": {}},
        validation_esto_tables=[
            ("00APEC_2024_low_with_subtotals.csv", esto_2024),
            ("00APEC_2025_low_with_subtotals.csv", esto_2025),
        ],
    )

    statuses = dict(zip(out["fuel_branch_label"], out["status"], strict=False))
    assert statuses["Electricity"] == "matched_all_validation_files"
    assert statuses["Natural gas"] == "missing_from_validation_file"


def test_output_fuel_validation_requires_both_final_year_snapshots() -> None:
    esto_2024 = pd.DataFrame(
        [
            {
                "economy": "01AUS",
                "flows": "10.01.06 Coal mines",
                "products": "17 Electricity",
                "is_subtotal": False,
                2022: -1.0,
            },
        ]
    )
    esto_2025 = pd.DataFrame(
        [
            {
                "economy": "01AUS",
                "flows": "10.01.06 Coal mines",
                "products": "17 Electricity",
                "is_subtotal": False,
                2023: 0.0,
            },
        ]
    )
    detail = pd.DataFrame(
        [
            {
                "process_key": "coal_mines",
                "process_label": "Coal mines",
                "fuel_branch_label": "Electricity",
            },
        ]
    )

    out = workflow.build_output_fuel_esto_validation(
        esto_data=esto_2024,
        detail_df=detail,
        configs=[_coal_config()],
        fuel_mapping_lookup={"esto": {}, "ninth": {}},
        validation_esto_tables=[
            ("2024_snapshot", esto_2024),
            ("2025_snapshot", esto_2025),
        ],
    )

    row = out.iloc[0]
    assert row["status"] == "missing_from_validation_file"
    assert row["missing_validation_files"] == "2025_snapshot"


def test_output_fuel_validation_can_scope_to_selected_economy() -> None:
    esto_2024 = pd.DataFrame(
        [
            {
                "economy": "01AUS",
                "flows": "10.01.06 Coal mines",
                "products": "17 Electricity",
                "is_subtotal": False,
                2022: -1.0,
            },
            {
                "economy": "20USA",
                "flows": "10.01.06 Coal mines",
                "products": "17 Electricity",
                "is_subtotal": False,
                2022: 0.0,
            },
        ]
    )
    esto_2025 = esto_2024.rename(columns={2022: 2023}).copy()
    detail = pd.DataFrame(
        [
            {
                "process_key": "coal_mines",
                "process_label": "Coal mines",
                "fuel_branch_label": "Electricity",
            },
        ]
    )

    economy_out = workflow.build_output_fuel_esto_validation(
        esto_data=esto_2024,
        detail_df=detail,
        configs=[_coal_config()],
        economy="20_USA",
        fuel_mapping_lookup={"esto": {}, "ninth": {}},
        validation_esto_tables=[("2024_snapshot", esto_2024), ("2025_snapshot", esto_2025)],
        output_fuel_scope="economy",
    )
    structure_out = workflow.build_output_fuel_esto_validation(
        esto_data=esto_2024,
        detail_df=detail,
        configs=[_coal_config()],
        economy="20_USA",
        fuel_mapping_lookup={"esto": {}, "ninth": {}},
        validation_esto_tables=[("2024_snapshot", esto_2024), ("2025_snapshot", esto_2025)],
        output_fuel_scope="all_economies",
    )

    assert economy_out["status"].iloc[0] == "missing_from_validation_file"
    assert economy_out["validation_economy"].iloc[0] == "20_USA"
    assert structure_out["status"].iloc[0] == "matched_all_validation_files"
    assert structure_out["validation_economy"].iloc[0] == "all_economies"


def test_filter_detail_to_validated_output_fuels() -> None:
    detail = pd.DataFrame(
        [
            {"process_key": "coal_mines", "fuel_branch_label": "Electricity", "year": 2022},
            {"process_key": "coal_mines", "fuel_branch_label": "Natural gas", "year": 2022},
        ]
    )
    validation = pd.DataFrame(
        [
            {
                "process_key": "coal_mines",
                "fuel_branch_label": "Electricity",
                "status": "matched_all_validation_files",
            },
            {
                "process_key": "coal_mines",
                "fuel_branch_label": "Natural gas",
                "status": "missing_from_validation_file",
            },
        ]
    )

    out = workflow.filter_detail_to_validated_output_fuels(detail, validation)

    assert set(out["fuel_branch_label"]) == {"Electricity"}


def test_merge_export_ids_adds_key_columns() -> None:
    export_df = pd.DataFrame(
        [
            {
                "Branch Path": "Demand\\Other loss and own use\\Coal mines",
                "Variable": "Activity Level",
                "Scenario": "Target",
                "Region": "United States",
                "Expression": "Data(2022,1)",
            },
        ]
    )
    key_table = pd.DataFrame(
        [
            {
                "BranchID": 1,
                "VariableID": 2,
                "ScenarioID": 3,
                "RegionID": 4,
                "Branch Path": "Demand\\Other loss and own use\\Coal mines",
                "Variable": "Activity Level",
                "Scenario": "Target",
                "Region": "United States",
            },
        ]
    )

    out = workflow.merge_export_ids(export_df, export_key_table=key_table)

    assert out[["BranchID", "VariableID", "ScenarioID", "RegionID"]].iloc[0].tolist() == [1, 2, 3, 1]
    assert out.columns[:4].tolist() == ["BranchID", "VariableID", "ScenarioID", "RegionID"]


def test_merge_export_ids_raises_for_unexpected_rows() -> None:
    export_df = pd.DataFrame(
        [
            {
                "Branch Path": "Demand\\Other loss and own use\\Coal mines",
                "Variable": "Activity Level",
                "Scenario": "Target",
                "Region": "United States",
                "Expression": "Data(2022,1)",
            },
        ]
    )
    key_table = pd.DataFrame(
        columns=[
            "BranchID",
            "VariableID",
            "ScenarioID",
            "RegionID",
            "Branch Path",
            "Variable",
            "Scenario",
            "Region",
        ]
    )

    result = workflow.merge_export_ids(export_df, export_key_table=key_table)
    assert result.empty, "Unmatched rows should be dropped, leaving an empty result"


def test_add_zero_rows_for_unset_values() -> None:
    export_df = pd.DataFrame(
        [
            {
                "Branch Path": "Demand\\Other loss and own use\\Coal mines\\Electricity",
                "Variable": "Activity Level",
                "Scenario": "Target",
                "Region": "United States",
                "Scale": "",
                "Units": "Unspecified Unit",
                "Per...": "",
                "Expression": "Data(2022,1.0)",
                "Level 1": "Demand",
                "Level 2": "Other loss and own use",
                "Level 3": "Coal mines",
                "Level 4": "Electricity",
            },
        ]
    )
    key_table = pd.DataFrame(
        [
            {
                "BranchID": 1,
                "VariableID": 2027,
                "ScenarioID": 3,
                "RegionID": 1,
                "Branch Path": "Demand\\Other loss and own use\\Coal mines\\Electricity",
                "Variable": "Activity Level",
                "Scenario": "Target",
                "Region": "United States",
            },
            {
                "BranchID": 1,
                "VariableID": 2040,
                "ScenarioID": 3,
                "RegionID": 1,
                "Branch Path": "Demand\\Other loss and own use\\Coal mines\\Electricity",
                "Variable": "Final Energy Intensity",
                "Scenario": "Target",
                "Region": "United States",
            },
            {
                "BranchID": 1,
                "VariableID": 776,
                "ScenarioID": 3,
                "RegionID": 1,
                "Branch Path": "Demand\\Other loss and own use\\Coal mines\\Electricity",
                "Variable": "Demand Cost",
                "Scenario": "Target",
                "Region": "United States",
            },
        ]
    )

    out = workflow.add_zero_rows_for_unset_values(
        export_df,
        export_key_table=key_table,
        base_year=2022,
        final_year=2024,
    )

    assert len(out) == 2
    zero_row = out[out["Variable"].eq("Final Energy Intensity")].iloc[0]
    assert zero_row["Expression"] == "Data(2022, 0.0, 2023, 0.0, 2024, 0.0)"
    assert "Demand Cost" not in set(out["Variable"])


def test_add_export_id_sheet_can_keep_only_id_sheet(tmp_path) -> None:
    workbook = tmp_path / "out.xlsx"
    export_key = tmp_path / "keys.xlsx"
    export_df = pd.DataFrame(
        [
            {
                "Branch Path": "Demand\\Other loss and own use\\Coal mines",
                "Variable": "Activity Level",
                "Scenario": "Target",
                "Region": "United States",
                "Expression": "Data(2022,1)",
            },
        ]
    )
    key_table = pd.DataFrame(
        [
            {"BranchID": "", "VariableID": "", "ScenarioID": "", "RegionID": "", "Branch Path": "Area:", "Variable": "Test", "Scenario": "Ver:", "Region": "2"},
            {"BranchID": pd.NA, "VariableID": pd.NA, "ScenarioID": pd.NA, "RegionID": pd.NA, "Branch Path": pd.NA, "Variable": pd.NA, "Scenario": pd.NA, "Region": pd.NA},
            {
                "BranchID": "BranchID",
                "VariableID": "VariableID",
                "ScenarioID": "ScenarioID",
                "RegionID": "RegionID",
                "Branch Path": "Branch Path",
                "Variable": "Variable",
                "Scenario": "Scenario",
                "Region": "Region",
            },
            {
                "BranchID": 1,
                "VariableID": 2,
                "ScenarioID": 3,
                "RegionID": 4,
                "Branch Path": "Demand\\Other loss and own use\\Coal mines",
                "Variable": "Activity Level",
                "Scenario": "Target",
                "Region": "United States",
            },
        ]
    )
    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        pd.DataFrame({"x": [1]}).to_excel(writer, sheet_name="LEAP", index=False)
    with pd.ExcelWriter(export_key, engine="openpyxl") as writer:
        key_table.to_excel(writer, sheet_name="Export", index=False, header=False)

    workflow.add_export_id_sheet(
        workbook,
        export_df,
        export_key_workbook_path=export_key,
        output_sheet_name="LEAP_WITH_IDS",
        keep_only_id_sheet=True,
        include_zero_rows_for_unset_values=False,
    )

    xls = pd.ExcelFile(workbook)
    assert xls.sheet_names == ["LEAP_WITH_IDS"]
    raw = pd.read_excel(workbook, sheet_name="LEAP_WITH_IDS", header=None, nrows=1)
    assert raw.iloc[0, 0:4].fillna("").tolist() == ["", "", "", ""]
    assert [str(value) for value in raw.iloc[0, 4:8].tolist()] == ["Area:", workflow.EXPORT_MODEL_NAME, "Ver:", "2"]


def test_fuel_branch_labels_use_sentence_case_and_mapping_lookup() -> None:
    label = workflow._format_fuel_branch_label(
        "07_07_gas_diesel_oil",
        source_name="ninth",
        fuel_mapping_lookup={"esto": {}, "ninth": {"07_07_gas_diesel_oil": "Gas and diesel oil"}},
    )

    assert label == "Gas and diesel oil"
    assert workflow._format_fuel_branch_label("07_09_lpg", fuel_mapping_lookup={"esto": {}, "ninth": {}}) == "LPG"


def test_strict_guardrail_raises_on_zero_activity_with_positive_target() -> None:
    esto = pd.DataFrame(
        [
            {
                "economy": "20USA",
                "economy_key": "20_USA",
                "flows": "10.01.06 Coal mines",
                "products": "17 Electricity",
                2022: -5.0,
            }
        ]
    )
    ninth = pd.DataFrame(columns=["economy_key", "sectors", "sub1sectors", "sub2sectors", "sub3sectors", "sub4sectors", "fuels", "subfuels", 2023])

    with pytest.raises(ValueError, match="proxy_activity == 0 while target_energy > 0"):
        workflow.build_proxy_detail_table(
            esto_data=esto,
            ninth_data=ninth,
            economy="20_USA",
            configs=[_coal_config()],
            base_year=2022,
            final_year=2022,
        )


def test_non_strict_guardrail_reports_zero_activity_with_positive_target() -> None:
    esto = pd.DataFrame(
        [
            {
                "economy": "20USA",
                "economy_key": "20_USA",
                "flows": "10.01.06 Coal mines",
                "products": "17 Electricity",
                2022: -5.0,
            }
        ]
    )
    ninth = pd.DataFrame(columns=["economy_key", "sectors", "sub1sectors", "sub2sectors", "sub3sectors", "sub4sectors", "fuels", "subfuels", 2023])

    detail = workflow.build_proxy_detail_table(
        esto_data=esto,
        ninth_data=ninth,
        economy="20_USA",
        configs=[_coal_config()],
        base_year=2022,
        final_year=2022,
        strict_proxy_activity_target_consistency=False,
    )
    issues = workflow.build_proxy_activity_target_consistency_issues(detail)

    assert float(detail["proxy_activity"].iloc[0]) == 0.0
    assert float(detail["intensity"].iloc[0]) == 0.0
    assert len(issues) == 1
    assert issues.iloc[0]["issue_type"] == "positive_target_energy_with_zero_proxy_activity"


def test_post_initialisation_intensity_uses_first_valid_nonzero_anchor() -> None:
    cfg = workflow.make_proxy_config(
        enabled=True,
        process_key="test",
        process_label="Test",
        activity_label="Test activity",
        esto_activity_flows=["01 Production"],
        esto_activity_exact_products=["01.01 Coking coal"],
        ninth_activity_sectors=["01_production"],
        ninth_activity_subfuels=["01_01_coking_coal"],
        activity_value_mode="positive_only",
        esto_target_flows=["10.01.06 Coal mines"],
        ninth_target_sectors=["10_01_06_coal_mines"],
    )
    esto = pd.DataFrame(
        [
            {
                "economy": "20USA",
                "economy_key": "20_USA",
                "flows": "01 Production",
                "products": "01.01 Coking coal",
                2022: 100.0,
            },
            {
                "economy": "20USA",
                "economy_key": "20_USA",
                "flows": "10.01.06 Coal mines",
                "products": "01.01 Coking coal",
                2022: 0.0,
            },
            {
                "economy": "01AUS",
                "economy_key": "01_AUS",
                "flows": "10.01.06 Coal mines",
                "products": "01.01 Coking coal",
                2022: -1.0,
            },
        ]
    )
    ninth = pd.DataFrame(
        [
            {
                "economy_key": "20_USA",
                "sectors": "01_production",
                "sub1sectors": "x",
                "sub2sectors": "x",
                "sub3sectors": "x",
                "sub4sectors": "x",
                "fuels": "01_coal",
                "subfuels": "01_01_coking_coal",
                "subtotal_layout": False,
                "subtotal_results": False,
                2023: 100.0,
                2024: 200.0,
            },
            {
                "economy_key": "20_USA",
                "sectors": "10_01_06_coal_mines",
                "sub1sectors": "x",
                "sub2sectors": "x",
                "sub3sectors": "x",
                "sub4sectors": "x",
                "fuels": "01_coal",
                "subfuels": "01_01_coking_coal",
                "subtotal_layout": False,
                "subtotal_results": False,
                2023: -5.0,
                2024: -20.0,
            },
        ]
    )

    detail = workflow.build_proxy_detail_table(
        esto_data=esto,
        ninth_data=ninth,
        economy="20_USA",
        configs=[cfg],
        base_year=2022,
        final_year=2024,
        intensity_mode="post_initialisation_anchored_intensity",
    )

    projected = detail[detail["source_dataset"].eq("ninth")].sort_values("year")
    assert projected["anchor_year"].tolist() == [2023, 2023]
    assert projected["intensity"].tolist() == [0.05, 0.05]
    assert set(projected["intensity_mode"]) == {"post_initialisation_anchored_intensity"}


def test_load_leap_balance_activity_table_reads_selected_fuels(tmp_path) -> None:
    workbook = tmp_path / "balance.xlsx"
    sheet = pd.DataFrame(
        [
            ["Scenario: Target, Year: 2023, Units: Petajoule", None, None, None],
            [None, "Coking coal", "Other bituminous coal", "Electricity"],
            ["Production", 10.0, 20.0, 999.0],
            ["Imports", 1.0, 2.0, 3.0],
        ]
    )
    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        sheet.to_excel(writer, sheet_name="EBal|2023", index=False, header=False)

    out = workflow.load_leap_balance_activity_table(
        workbook,
        balance_rows=["Production"],
        fuels=["Coking coal", "Other bituminous coal"],
    )

    assert len(out) == 2
    assert set(out["fuel_label"]) == {"Coking coal", "Other bituminous coal"}
    assert out["value"].sum() == 30.0


def test_leap_balance_activity_mode_uses_explicit_fuel_set() -> None:
    leap_activity = pd.DataFrame(
        [
            {"year": 2022, "balance_row": "Production", "fuel_label": "Coking coal", "value": 10.0},
            {"year": 2022, "balance_row": "Production", "fuel_label": "Other bituminous coal", "value": 20.0},
            {"year": 2022, "balance_row": "Production", "fuel_label": "Electricity", "value": 999.0},
            {"year": 2023, "balance_row": "Production", "fuel_label": "Coking coal", "value": 5.0},
        ]
    )

    series = workflow.build_leap_balance_proxy_activity_series(
        leap_balance_activity=leap_activity,
        config=_coal_config(),
        base_year=2022,
        final_year=2023,
    )

    assert series == {2022: 30.0, 2023: 5.0}


def test_leap_balance_activity_value_mode_positive_only() -> None:
    cfg = workflow.make_proxy_config(
        process_key="test",
        process_label="Test",
        esto_target_flows=[],
        ninth_target_sectors=[],
        leap_balance_rows=["Pumped hydro"],
        leap_balance_fuel_set="electricity_output",
        activity_value_mode="positive_only",
    )
    leap_activity = pd.DataFrame(
        [
            {"year": 2023, "balance_row": "Pumped hydro", "fuel_label": "Electricity", "value": 50.0},
            {"year": 2023, "balance_row": "Pumped hydro", "fuel_label": "Electricity", "value": -30.0},
        ]
    )

    series = workflow.build_leap_balance_proxy_activity_series(
        leap_balance_activity=leap_activity,
        config=cfg,
        base_year=2023,
        final_year=2023,
    )

    assert series == {2023: 50.0}


def test_leap_balance_activity_value_mode_negative_abs() -> None:
    cfg = workflow.make_proxy_config(
        process_key="test",
        process_label="Test",
        esto_target_flows=[],
        ninth_target_sectors=[],
        leap_balance_rows=["Pumped hydro"],
        leap_balance_fuel_set="electricity_output",
        activity_value_mode="negative_abs",
    )
    leap_activity = pd.DataFrame(
        [
            {"year": 2023, "balance_row": "Pumped hydro", "fuel_label": "Electricity", "value": 50.0},
            {"year": 2023, "balance_row": "Pumped hydro", "fuel_label": "Electricity", "value": -30.0},
        ]
    )

    series = workflow.build_leap_balance_proxy_activity_series(
        leap_balance_activity=leap_activity,
        config=cfg,
        base_year=2023,
        final_year=2023,
    )

    assert series == {2023: 30.0}


def test_missing_leap_balance_fuel_returns_empty_without_error(tmp_path) -> None:
    workbook = tmp_path / "balance_missing_fuel.xlsx"
    sheet = pd.DataFrame(
        [
            ["Scenario: Target, Year: 2023, Units: Petajoule", None],
            [None, "Electricity"],
            ["Gas works plants", 10.0],
        ]
    )
    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        sheet.to_excel(writer, sheet_name="EBal|2023", index=False, header=False)

    out = workflow.load_leap_balance_activity_table(
        workbook,
        balance_rows=["Gas works plants"],
        fuels=["Gas works gas"],
    )

    assert out.empty


def test_pump_storage_config_uses_pumped_hydro_leap_row() -> None:
    cfg = next(item for item in workflow.PROXY_CONFIG if item["process_key"] == "pump_storage_plants")

    assert cfg["activity_sources"]["leap_balance"]["balance_rows"] == ["Pumped hydro"]
    assert cfg["activity_sources"]["leap_balance"]["fuel_set"] == "electricity_output"
    assert cfg["activity_sources"]["leap_balance"]["value_mode"] == "positive_only"


def _liquefaction_config() -> dict[str, object]:
    return next(
        item
        for item in workflow.PROXY_CONFIG
        if item["process_key"] == "liquefaction_regasification_plants"
    )


def _lng_trade_ninth_rows(subfuel: str, imports_value: float, exports_value: float) -> list[dict[str, object]]:
    shared = {
        "economy_key": "01_AUS",
        "sub1sectors": "x",
        "sub2sectors": "x",
        "sub3sectors": "x",
        "sub4sectors": "x",
        "fuels": "08_gas",
        "subfuels": subfuel,
        "subtotal_layout": False,
        "subtotal_results": False,
    }
    return [
        {**shared, "sectors": "02_imports", 2023: imports_value},
        {**shared, "sectors": "03_exports", 2023: exports_value},
    ]


def test_liquefaction_activity_falls_back_to_abs_lng_imports_plus_exports() -> None:
    cfg = _liquefaction_config()
    esto = pd.DataFrame(
        [
            {
                "economy": "01AUS",
                "economy_key": "01_AUS",
                "flows": "02 Imports",
                "products": "08.02 LNG",
                2022: 5.0,
            },
            {
                "economy": "01AUS",
                "economy_key": "01_AUS",
                "flows": "03 Exports",
                "products": "08.02 LNG",
                2022: -10.0,
            },
        ]
    )
    ninth = pd.DataFrame(_lng_trade_ninth_rows("08_02_lng", 3.0, -20.0))

    series, fallback = workflow.build_proxy_activity_series_with_fallback(
        esto_data=esto,
        ninth_data=ninth,
        economy="01_AUS",
        config=cfg,
        base_year=2022,
        final_year=2023,
    )

    assert series[2022] == 15.0
    assert series[2023] == 23.0
    assert fallback is not None
    assert fallback["fallback_key"] == "lng_imports_exports_abs"
    assert fallback["fallback_reason"] == "configured_activity_all_zero_used_alternative_source"
    assert fallback["fallback_esto_activity_flows"] == "02 Imports; 03 Exports"


def test_liquefaction_activity_second_fallback_uses_natural_gas_production_imports() -> None:
    cfg = _liquefaction_config()
    # No ESTO LNG trade rows: tier 1 is zero in ESTO base years, which also
    # zeroes its 9th projection (consistency rule), so tier 2 must win.
    esto = pd.DataFrame(
        [
            {
                "economy": "01AUS",
                "economy_key": "01_AUS",
                "flows": "01 Production",
                "products": "08.01 Natural gas",
                2022: 7.0,
            },
            {
                "economy": "01AUS",
                "economy_key": "01_AUS",
                "flows": "02 Imports",
                "products": "08.01 Natural gas",
                2022: 2.0,
            },
        ]
    )
    ninth = pd.DataFrame(
        [
            *_lng_trade_ninth_rows("08_02_lng", 3.0, -20.0),
            {
                "economy_key": "01_AUS",
                "sectors": "01_production",
                "sub1sectors": "x",
                "sub2sectors": "x",
                "sub3sectors": "x",
                "sub4sectors": "x",
                "fuels": "08_gas",
                "subfuels": "08_01_natural_gas",
                "subtotal_layout": False,
                "subtotal_results": False,
                2023: 11.0,
            },
        ]
    )

    series, fallback = workflow.build_proxy_activity_series_with_fallback(
        esto_data=esto,
        ninth_data=ninth,
        economy="01_AUS",
        config=cfg,
        base_year=2022,
        final_year=2023,
    )

    assert series[2022] == 9.0
    assert series[2023] == 11.0
    assert fallback is not None
    assert fallback["fallback_key"] == "natural_gas_production_imports_abs"
    assert fallback["fallback_level"] == 2


def test_activity_series_when_configured_proxy_is_nonzero_skips_fallback() -> None:
    cfg = _liquefaction_config()
    esto = pd.DataFrame(
        [
            {
                "economy": "01AUS",
                "economy_key": "01_AUS",
                "flows": "09.06.02 Liquefaction/regasification plants",
                "products": "08.02 LNG",
                2022: 4.0,
            },
            {
                "economy": "01AUS",
                "economy_key": "01_AUS",
                "flows": "02 Imports",
                "products": "08.02 LNG",
                2022: 100.0,
            },
        ]
    )

    series, fallback = workflow.build_proxy_activity_series_with_fallback(
        esto_data=esto,
        ninth_data=pd.DataFrame(_lng_trade_ninth_rows("08_02_lng", 0.0, 0.0)),
        economy="01_AUS",
        config=cfg,
        base_year=2022,
        final_year=2023,
    )

    assert series[2022] == 4.0
    assert fallback is None


def test_pump_storage_activity_falls_back_to_hydro_output() -> None:
    cfg = next(item for item in workflow.PROXY_CONFIG if item["process_key"] == "pump_storage_plants")
    ninth = pd.DataFrame(
        [
            {
                "economy_key": "01_AUS",
                "sectors": "09_total_transformation_sector",
                "sub1sectors": "09_01_electricity_plants",
                "sub2sectors": "09_01_05_hydro",
                "sub3sectors": "x",
                "sub4sectors": "x",
                "fuels": "17_electricity",
                "subfuels": "17_electricity",
                "subtotal_layout": False,
                "subtotal_results": False,
                2023: 12.0,
            }
        ]
    )

    series, fallback = workflow.build_proxy_activity_series_with_fallback(
        esto_data=pd.DataFrame(columns=["economy", "economy_key", "flows", "products", 2022]),
        ninth_data=ninth,
        economy="01_AUS",
        config=cfg,
        base_year=2022,
        final_year=2023,
    )

    assert series[2023] == 12.0
    assert fallback is not None
    assert fallback["fallback_key"] == "hydro_electricity_output_positive"


def test_fallback_report_includes_alternative_source_fallbacks() -> None:
    cfg = _liquefaction_config()
    esto = pd.DataFrame(
        [
            {
                "economy": "01AUS",
                "economy_key": "01_AUS",
                "flows": "02 Imports",
                "products": "08.02 LNG",
                2022: 5.0,
            },
        ]
    )
    ninth = pd.DataFrame(_lng_trade_ninth_rows("08_02_lng", 3.0, -20.0))

    report = workflow.build_activity_source_fallback_report(
        esto_data=esto,
        ninth_data=ninth,
        economy="01_AUS",
        configs=[cfg],
        base_year=2022,
        final_year=2023,
    )

    assert len(report) == 1
    row = report.iloc[0]
    assert row["process_key"] == "liquefaction_regasification_plants"
    assert row["fallback_reason"] == "configured_activity_all_zero_used_alternative_source"
    assert row["fallback_key"] == "lng_imports_exports_abs"


def test_leap_balance_liquefaction_fallback_chain() -> None:
    cfg = _liquefaction_config()
    lng_trade_activity = pd.DataFrame(
        [
            {"year": 2023, "balance_row": "Imports", "fuel_label": "LNG", "value": 5.0},
            {"year": 2023, "balance_row": "Exports", "fuel_label": "LNG", "value": -10.0},
        ]
    )

    series = workflow.build_leap_balance_proxy_activity_series(
        leap_balance_activity=lng_trade_activity,
        config=cfg,
        base_year=2023,
        final_year=2023,
    )

    assert series == {2023: 15.0}

    natural_gas_activity = pd.DataFrame(
        [
            {"year": 2023, "balance_row": "Production", "fuel_label": "Natural gas", "value": 7.0},
            {"year": 2023, "balance_row": "Imports", "fuel_label": "Natural gas", "value": 2.0},
        ]
    )

    series = workflow.build_leap_balance_proxy_activity_series(
        leap_balance_activity=natural_gas_activity,
        config=cfg,
        base_year=2023,
        final_year=2023,
    )

    assert series == {2023: 9.0}


def test_nonspecified_own_use_uses_total_transformation_throughput() -> None:
    cfg = next(item for item in workflow.PROXY_CONFIG if item["process_key"] == "nonspecified_own_uses")
    fuel_set = cfg["activity_sources"]["leap_balance"]["fuel_set"]

    assert cfg["enabled"] is True
    assert cfg["activity_sources"]["leap_balance"]["balance_rows"] == ["Total transformation sector"]
    assert fuel_set == "production_with_electricity"
    assert "Electricity" in workflow.LEAP_BALANCE_FUEL_SETS[fuel_set]


def test_transmission_distribution_losses_uses_production_including_electricity() -> None:
    cfg = next(item for item in workflow.PROXY_CONFIG if item["process_key"] == "transmission_and_distribution_losses")
    fuel_set = cfg["activity_sources"]["leap_balance"]["fuel_set"]

    assert cfg["enabled"] is True
    assert cfg["leap_process_label"] == "Transmission and distribution loss"
    assert cfg["target_sources"]["esto"]["flows"] == ["10.02 Transmission and distribution losses"]
    assert cfg["target_sources"]["esto"]["exclude_products"] == []
    assert cfg["target_sources"]["ninth"]["sector_codes"] == ["10_02_transmission_and_distribution_losses"]
    assert cfg["target_sources"]["ninth"]["exclude_fuels"] == []
    assert cfg["target_sources"]["ninth"]["exclude_subfuels"] == []
    assert cfg["activity_sources"]["esto"]["flows"] == ["01 Production"]
    assert cfg["activity_sources"]["esto"]["exclude_products"] == []
    assert cfg["activity_sources"]["ninth"]["sector_codes"] == ["01_production"]
    assert cfg["activity_sources"]["ninth"]["exclude_fuels"] == []
    assert cfg["activity_sources"]["ninth"]["exclude_subfuels"] == []
    assert cfg["activity_sources"]["leap_balance"]["balance_rows"] == ["Production"]
    assert fuel_set == "production_with_electricity"
    assert "Electricity" in workflow.LEAP_BALANCE_FUEL_SETS[fuel_set]
    assert "Peat" in workflow.LEAP_BALANCE_FUEL_SETS[fuel_set]
    assert "Tide wave ocean" in workflow.LEAP_BALANCE_FUEL_SETS[fuel_set]


def test_transmission_distribution_target_includes_electricity_and_heat() -> None:
    cfg = next(item for item in workflow.PROXY_CONFIG if item["process_key"] == "transmission_and_distribution_losses")
    esto = pd.DataFrame(
        [
            {
                "economy": "20USA",
                "economy_key": "20_USA",
                "flows": "10.02 Transmission and distribution losses",
                "products": "17 Electricity",
                2022: -1.0,
            },
            {
                "economy": "20USA",
                "economy_key": "20_USA",
                "flows": "10.02 Transmission and distribution losses",
                "products": "18 Heat",
                2022: -2.0,
            },
        ]
    )
    ninth = pd.DataFrame(
        [
            {
                "economy_key": "20_USA",
                "sectors": "10_losses_and_own_use",
                "sub1sectors": "10_02_transmission_and_distribution_losses",
                "sub2sectors": "x",
                "sub3sectors": "x",
                "sub4sectors": "x",
                "fuels": "17_electricity",
                "subfuels": "x",
                2023: -3.0,
            },
            {
                "economy_key": "20_USA",
                "sectors": "10_losses_and_own_use",
                "sub1sectors": "10_02_transmission_and_distribution_losses",
                "sub2sectors": "x",
                "sub3sectors": "x",
                "sub4sectors": "x",
                "fuels": "18_heat",
                "subfuels": "x",
                2023: -4.0,
            },
        ]
    )

    target = workflow.build_target_energy_long(
        esto_data=esto,
        ninth_data=ninth,
        economy="20_USA",
        config=cfg,
        base_year=2022,
        final_year=2023,
        fuel_mapping_lookup={"esto": {}, "ninth": {}},
    )

    assert set(target["fuel_branch_label"]) == {"Electricity", "Heat"}
    assert set(target["source_dataset"]) == {"esto", "ninth"}
    assert set(target["leap_process_label"]) == {"Transmission and distribution loss"}


def test_fuel_set_verification_flags_missing_activity_fuel() -> None:
    cfg = workflow.make_proxy_config(
        process_key="test",
        process_label="Test",
        esto_target_flows=[],
        ninth_target_sectors=[],
        esto_activity_flows=["09.12 Non-specified transformation"],
        esto_activity_exact_products=["07.09 LPG", "07.11 Ethane"],
        leap_balance_fuel_set="gas_to_liquids_output",
        activity_value_mode="positive_only",
    )
    esto = pd.DataFrame(
        [
            {
                "flows": "09.12 Non-specified transformation",
                "products": "07.09 LPG",
                2022: 1.0,
            },
            {
                "flows": "09.12 Non-specified transformation",
                "products": "07.11 Ethane",
                2022: 2.0,
            },
        ]
    )
    ninth = pd.DataFrame(columns=["sectors", "sub1sectors", "sub2sectors", "sub3sectors", "sub4sectors", "fuels", "subfuels", 2023])

    out = workflow.build_proxy_fuel_set_verification(
        esto_data=esto,
        ninth_data=ninth,
        configs=[cfg],
    )

    missing = out[out["status"] == "missing_from_leap_fuel_set"]
    assert set(missing["fuel_label"]) == {"Ethane"}


def test_fuel_set_verification_uses_mapping_lookup() -> None:
    cfg = workflow.make_proxy_config(
        process_key="test",
        process_label="Test",
        esto_target_flows=[],
        ninth_target_sectors=[],
        ninth_activity_sectors=["01_production"],
        ninth_activity_fuels=["01_coal"],
        ninth_activity_subfuels=["01_x_thermal_coal"],
        leap_balance_fuel_set="coal_primary_and_products",
        activity_value_mode="positive_only",
    )
    esto = pd.DataFrame()
    ninth = pd.DataFrame(
        [
            {
                "sectors": "01_production",
                "sub1sectors": "x",
                "sub2sectors": "x",
                "sub3sectors": "x",
                "sub4sectors": "x",
                "fuels": "01_coal",
                "subfuels": "01_x_thermal_coal",
                2023: 1.0,
            }
        ]
    )

    out = workflow.build_proxy_fuel_set_verification(
        esto_data=esto,
        ninth_data=ninth,
        configs=[cfg],
        fuel_mapping_lookup={"ninth": {"01_x_thermal_coal": "Other bituminous coal"}},
    )

    matched = out[out["status"] == "matched"]
    assert "Other bituminous coal" in set(matched["fuel_label"])
    assert "mapped_by_leap_mappings" in set(matched["mapping_status"])


def test_activity_source_gap_warning_when_esto_proxy_exists_but_ninth_is_zero() -> None:
    cfg = workflow.make_proxy_config(
        enabled=True,
        process_key="test",
        process_label="Test",
        activity_label="Test activity",
        esto_activity_flows=["09.99 Test"],
        esto_activity_exact_products=["02.04 Blast furnace gas"],
        ninth_activity_sectors=["09_08_02_blast_furnaces"],
        ninth_activity_fuels=["02_coal_products"],
        ninth_activity_subfuels=["02_04_blast_furnace_gas"],
        activity_value_mode="positive_only",
        esto_target_flows=["10.01.07 Blast furnaces"],
        ninth_target_sectors=["10_01_07_blast_furnaces"],
    )
    esto = pd.DataFrame(
        [
            {
                "economy": "20USA",
                "economy_key": "20_USA",
                "flows": "09.99 Test",
                "products": "02.04 Blast furnace gas",
                2022: 5.0,
            }
        ]
    )
    ninth = pd.DataFrame(
        [
            {
                "economy_key": "20_USA",
                "sectors": "09_total_transformation_sector",
                "sub1sectors": "09_08_coal_transformation",
                "sub2sectors": "09_08_02_blast_furnaces",
                "sub3sectors": "x",
                "sub4sectors": "x",
                "fuels": "02_coal_products",
                "subfuels": "02_04_blast_furnace_gas",
                2023: 0.0,
                2024: 0.0,
            }
        ]
    )

    warnings = workflow.build_activity_source_gap_warnings(
        esto_data=esto,
        ninth_data=ninth,
        economy="20_USA",
        configs=[cfg],
        base_year=2022,
        final_year=2024,
    )

    assert len(warnings) == 1
    row = warnings.iloc[0]
    assert row["process_key"] == "test"
    assert row["warning_type"] == "esto_activity_nonzero_ninth_activity_all_zero"
    assert row["esto_activity_total"] == 5.0
    assert row["ninth_activity_total"] == 0.0


# --- Base-year activity backfill + base-year-scoped strict consistency ---------


def test_backfill_base_year_copies_first_nonzero_projection_value() -> None:
    from codebase.functions.other_loss_own_use_proxy_utils import (
        _backfill_base_year_activity_from_projection,
    )

    series = {2020: 0.0, 2021: 0.0, 2022: 0.0, 2023: 0.0, 2024: 5.0, 2025: 7.0}
    out, donor = _backfill_base_year_activity_from_projection(series, base_year=2022)
    assert donor == 2024
    assert out[2022] == 5.0
    # Pre-base years are deliberately left at zero.
    assert out[2020] == 0.0 and out[2021] == 0.0
    # Input series is not mutated.
    assert series[2022] == 0.0


def test_backfill_base_year_noop_when_base_year_nonzero_or_all_zero() -> None:
    from codebase.functions.other_loss_own_use_proxy_utils import (
        _backfill_base_year_activity_from_projection,
    )

    nonzero, donor = _backfill_base_year_activity_from_projection(
        {2022: 3.0, 2023: 5.0}, base_year=2022
    )
    assert donor is None and nonzero[2022] == 3.0

    all_zero, donor = _backfill_base_year_activity_from_projection(
        {2022: 0.0, 2023: 0.0}, base_year=2022
    )
    assert donor is None and all_zero[2022] == 0.0


def _consistency_detail(rows: list[tuple[int, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "economy": "01_AUS",
                "process_key": "pump_storage_plants",
                "process_label": "Pump storage plants",
                "fuel_branch_label": "Electricity",
                "year": year,
                "proxy_activity": activity,
                "target_energy": target,
                "source_dataset": "esto",
                "activity_source_mode": "esto_ninth",
                "intensity_mode": "target_matching_initialisation",
                "anchor_year": pd.NA,
            }
            for year, activity, target in rows
        ]
    )


def test_strict_consistency_ignores_pre_base_year_rows(tmp_path) -> None:
    # Pre-base-year positive-target/zero-activity rows never reach the LEAP
    # import: they are written to the issues CSV but must not raise.
    detail = _consistency_detail([(1990, 0.0, 1.2), (2000, 0.0, 1.3), (2022, 4.0, 1.1)])
    issues_path = tmp_path / "issues.csv"

    issues = workflow.validate_proxy_activity_target_consistency(
        detail,
        strict=True,
        issues_path=issues_path,
        blocking_min_year=2022,
    )

    assert issues["year"].tolist() == [1990, 2000]
    saved = pd.read_csv(issues_path)
    assert saved["year"].tolist() == [1990, 2000]


def test_strict_consistency_still_raises_for_base_year_and_projection_rows(tmp_path) -> None:
    detail = _consistency_detail([(1990, 0.0, 1.2), (2022, 0.0, 1.1), (2030, 0.0, 2.0)])
    issues_path = tmp_path / "issues.csv"

    with pytest.raises(ValueError, match="2 row\(s\).*at or after base year 2022"):
        workflow.validate_proxy_activity_target_consistency(
            detail,
            strict=True,
            issues_path=issues_path,
            blocking_min_year=2022,
        )
    # Evidence (all rows, including pre-base) is on disk before the raise.
    saved = pd.read_csv(issues_path)
    assert saved["year"].tolist() == [1990, 2022, 2030]


def test_strict_consistency_without_min_year_keeps_original_behaviour() -> None:
    detail = _consistency_detail([(1990, 0.0, 1.2)])
    with pytest.raises(ValueError, match="1 row\(s\)"):
        workflow.validate_proxy_activity_target_consistency(detail, strict=True)


# --- Alternative-source fallback: coverage-ranked tier selection ---------------


def _fallback_selection_harness(monkeypatch, tier_series: dict[str, dict[int, float]]):
    """Route build_proxy_activity_series to canned series keyed by esto flows."""
    import codebase.functions.other_loss_own_use_proxy_utils as utils

    tiers = [
        {
            "fallback_key": f"tier_{name}",
            "activity_label": f"Tier {name}",
            "esto": {"flows": [name], "value_mode": "absolute"},
            "ninth": {"sector_codes": [name], "value_mode": "absolute"},
        }
        for name in tier_series
    ]
    monkeypatch.setitem(utils.ESTO_NINTH_ACTIVITY_FALLBACKS, "test_proc", tiers)

    def _fake_series(*, esto_data, ninth_data, economy, config, base_year, final_year):
        flows = config["activity_sources"]["esto"].get("flows", [])
        if flows and flows[0] in tier_series:
            return dict(tier_series[flows[0]])
        return {2022: 0.0, 2023: 0.0}  # configured series: all zero

    monkeypatch.setattr(utils, "build_proxy_activity_series", _fake_series)
    config = {
        "process_key": "test_proc",
        "process_label": "Test process",
        "activity_label": "Test activity",
        "activity_sources": {"esto": {"flows": ["configured"]}, "ninth": {"sector_codes": []}},
    }
    return utils, config


def test_fallback_prefers_tier_with_more_projection_coverage(monkeypatch) -> None:
    utils, config = _fallback_selection_harness(
        monkeypatch,
        {
            "hist_only": {2020: 5.0, 2022: 5.0, 2023: 0.0, 2024: 0.0},
            "truncated": {2020: 1.0, 2022: 1.0, 2023: 1.0, 2024: 0.0},
            "full": {2020: 2.0, 2022: 2.0, 2023: 2.0, 2024: 2.0},
        },
    )

    series, info = utils.build_proxy_activity_series_with_fallback(
        esto_data=None, ninth_data=None, economy="09_ROK",
        config=config, base_year=2022, final_year=2024,
    )

    assert info is not None and info["fallback_key"] == "tier_full"
    assert info["fallback_level"] == 3
    assert series[2024] == 2.0


def test_fallback_keeps_earliest_tier_on_coverage_tie(monkeypatch) -> None:
    utils, config = _fallback_selection_harness(
        monkeypatch,
        {
            "first_full": {2022: 1.0, 2023: 1.0, 2024: 1.0},
            "second_full": {2022: 9.0, 2023: 9.0, 2024: 9.0},
        },
    )

    _, info = utils.build_proxy_activity_series_with_fallback(
        esto_data=None, ninth_data=None, economy="01_AUS",
        config=config, base_year=2022, final_year=2024,
    )

    assert info is not None and info["fallback_key"] == "tier_first_full"


def test_fallback_returns_configured_series_when_no_tier_has_values(monkeypatch) -> None:
    utils, config = _fallback_selection_harness(
        monkeypatch,
        {"dead": {2022: 0.0, 2023: 0.0}},
    )

    series, info = utils.build_proxy_activity_series_with_fallback(
        esto_data=None, ninth_data=None, economy="01_AUS",
        config=config, base_year=2022, final_year=2024,
    )

    assert info is None
    assert all(value == 0.0 for value in series.values())


def test_liquefaction_chain_includes_combined_gas_trade_tier() -> None:
    from codebase.functions.other_loss_own_use_proxy_utils import (
        ESTO_NINTH_ACTIVITY_FALLBACKS,
    )

    chain = ESTO_NINTH_ACTIVITY_FALLBACKS["liquefaction_regasification_plants"]
    combined = next(t for t in chain if t["fallback_key"] == "gas_trade_combined_abs")
    # Both legs accept both product labels so an ESTO-vs-9th labeling
    # disagreement (natural gas vs LNG) cannot zero the tier.
    assert set(combined["esto"]["include_exact_products"]) == {
        "08.01 Natural gas",
        "08.02 LNG",
    }
    assert set(combined["ninth"]["subfuels"]) == {"08_01_natural_gas", "08_02_lng"}
