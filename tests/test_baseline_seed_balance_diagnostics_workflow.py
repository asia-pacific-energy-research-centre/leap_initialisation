from contextlib import contextmanager
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import Workbook

import codebase.functions.baseline_seed_balance_diagnostics as diagnostics
from codebase.supply_reconciliation import balance_tables


def _comparison_rows(
    *,
    scenario: str,
    year: int,
    leap_value: float | None,
    source: str,
    source_value: float | None,
) -> pd.DataFrame:
    rows = []
    for source_name, value in [("leap", leap_value), (source, source_value)]:
        rows.append(
            {
                "economy": "20_USA",
                "scenario": scenario,
                "sheet": "09.06 Gas processing plants",
                "measure": "Energy balance (PJ)",
                "fuel_label": "08.01 Natural gas",
                "source": source_name,
                "year": year,
                "value": value,
            }
        )
    return pd.DataFrame(rows)


def _mapping_status(*, ninth_pairs: list[tuple[str, str]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "sheet": "09.06 Gas processing plants",
                "measure": "Energy balance (PJ)",
                "fuel_label": "08.01 Natural gas",
                "esto_flow": "09.06 Gas processing plants",
                "esto_product": "08.01 Natural gas",
                "sector_code_9th": sector,
                "ninth_fuel_code": fuel,
            }
            for sector, fuel in ninth_pairs
        ]
    )


def _leap_long(*, components: list[tuple[str, str]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "sheet_name": "09.06 Gas processing plants",
                "measure": "Energy balance (PJ)",
                "fuel_label": "08.01 Natural gas",
                "leap_sector_name": sector,
                "leap_fuel_name": fuel,
            }
            for sector, fuel in components
        ]
    )


def _write_balance_workbook(
    path: Path,
    *,
    scenario: str = "Reference",
    year: int = 2022,
    units: str = "Petajoule",
    include_level2: bool = True,
) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Energy Balance"
    sheet.append(['Energy Balance for Area "Test"', None])
    sheet.append([f"Scenario: {scenario}, Year: {year}, Units: {units}", None])
    sheet.append([None, "Electricity"])
    sheet.append(["Production", 1.0])
    if include_level2:
        sheet.append(["  Child production", 1.0])
    workbook.save(path)


def test_projection_difference_marks_cardinality_and_correction() -> None:
    table = diagnostics.build_leap_source_difference_table(
        comparison_long=_comparison_rows(
            scenario="Reference",
            year=2023,
            leap_value=12.0,
            source="projection",
            source_value=10.0,
        ),
        mapping_status=_mapping_status(
            ninth_pairs=[
                ("09_06_gas_processing_plants", "08_01_natural_gas"),
                ("09_06_gas_processing_plants", "08_02_lng"),
            ]
        ),
        leap_long=_leap_long(
            components=[
                ("Gas processing/Input", "Natural gas"),
                ("Gas processing/Output", "Natural gas"),
            ]
        ),
        economy="20_USA",
        years=[2023],
        scenarios=["Reference"],
    )

    assert len(table) == 1
    row = table.iloc[0]
    assert row["reference_source"] == "9th Outlook"
    assert row["difference_pj"] == pytest.approx(2.0)
    assert row["correction_to_match_source_pj"] == pytest.approx(-2.0)
    assert row["difference_percent"] == pytest.approx(20.0)
    assert row["status"] == "value_mismatch"
    assert bool(row["is_mismatch"]) is True
    assert row["leap_component_count"] == 2
    assert row["ninth_pair_count"] == 2
    assert row["ninth_pair_max_esto_claimants"] == 1
    assert row["comparison_grain"] == "aggregate_many_leap_to_many_ninth"
    assert bool(row["update_allocation_required"]) is True
    assert row["update_allocation_reason"] == (
        "multiple_leap_components_share_the_esto_pair;"
        "esto_pair_sums_multiple_ninth_pairs"
    )


def test_direct_demand_comparators_use_declared_non_road_components() -> None:
    difference_table = pd.DataFrame(
        [
            {
                "scenario": "Target",
                "comparison_branch_path": "All demand aggregated/Industry",
                "esto_flow": "14 Industry sector",
                "esto_product": "17 Electricity",
                "year": 2023,
                "leap_value_pj": 10.0,
                "source_value_pj": 8.0,
                "reference_source": "9th Outlook",
                "status": "value_mismatch",
            },
            {
                "scenario": "Target",
                "comparison_branch_path": "All demand aggregated/Transport non road",
                "esto_flow": "15.01,15.03-15.06 Transport non-road",
                "esto_product": "08.01 Natural gas",
                "year": 2023,
                "leap_value_pj": 15.0,
                "source_value_pj": 0.0,
                "reference_source": "9th Outlook",
                "status": "value_mismatch",
            },
        ]
    )
    ninth_df = pd.DataFrame(
        [
            {"economy": "20_USA", "scenarios": "target", "sectors": "14_industry_sector", "sub1sectors": "x", "fuels": "17_electricity", "subfuels": "x", "subtotal_results": False, "2023": 10.0},
            *[
                {"economy": "20_USA", "scenarios": "target", "sectors": "15_transport_sector", "sub1sectors": sector, "sub2sectors": "15_01_01_passenger" if sector == "15_01_domestic_air_transport" else "x", "fuels": "08_01_natural_gas", "subfuels": "x", "subtotal_results": "False", "2023": value}
                for sector, value in [("15_01_domestic_air_transport", 1.0), ("15_03_rail", 2.0), ("15_04_domestic_navigation", 3.0), ("15_05_pipeline_transport", 4.0), ("15_06_nonspecified_transport", 5.0)]
            ],
            {"economy": "20_USA", "scenarios": "target", "sectors": "15_transport_sector", "sub1sectors": "15_02_road", "fuels": "08_01_natural_gas", "subfuels": "x", "subtotal_results": False, "2023": 99.0},
        ]
    )

    result = diagnostics._override_direct_demand_sources(
        difference_table=difference_table,
        ninth_df=ninth_df,
        economy="20_USA",
        base_year=2022,
        tolerance_pj=1e-6,
        mapping_pairs_path=diagnostics.DEFAULT_MAPPING_PAIRS_PATH,
    )

    assert result.loc[1, "source_value_pj"] == pytest.approx(15.0)
    assert result.loc[1, "reference_source"] == "9th Outlook (direct demand detail)"


def test_direct_base_demand_comparators_use_declared_transport_components() -> None:
    difference_table = pd.DataFrame(
        [
            {
                "scenario": "Target",
                "comparison_branch_path": "All demand aggregated/Road",
                "esto_flow": "15.02 Road",
                "esto_product": "07.08 Fuel oil",
                "year": 2022,
                "leap_value_pj": 3.994348,
                "source_value_pj": 0.0,
                "reference_source": "ESTO",
                "status": "value_mismatch",
            },
            {
                "scenario": "Target",
                "comparison_branch_path": "All demand aggregated/Transport non road",
                "esto_flow": "15.01,15.03-15.06 Transport non-road",
                "esto_product": "07.01 Motor gasoline",
                "year": 2022,
                "leap_value_pj": 406.926,
                "source_value_pj": 91.675324,
                "reference_source": "ESTO",
                "status": "value_mismatch",
            },
        ]
    )
    base_df = pd.DataFrame(
        [
            {"economy": "05PRC", "flows": "15.02 Road", "products": "07.08 Fuel oil", "is_subtotal": "False", "2022": 3.994348},
            {"economy": "05PRC", "flows": "15.03 Rail", "products": "07.01 Motor gasoline", "is_subtotal": "False", "2022": 5.799383},
            {"economy": "05PRC", "flows": "15.04 Domestic navigation", "products": "07.01 Motor gasoline", "is_subtotal": "False", "2022": 91.675324},
            {"economy": "05PRC", "flows": "15.05 Pipeline transport", "products": "07.01 Motor gasoline", "is_subtotal": "False", "2022": 0.052172},
            {"economy": "05PRC", "flows": "15.06 Non-specified transport", "products": "07.01 Motor gasoline", "is_subtotal": "False", "2022": 309.398970},
            {"economy": "05PRC", "flows": "15 Transport sector", "products": "07.01 Motor gasoline", "is_subtotal": "True", "2022": 999.0},
        ]
    )

    result = diagnostics._override_direct_base_demand_sources(
        difference_table=difference_table,
        base_df=base_df,
        economy="05_PRC",
        base_year=2022,
        tolerance_pj=1e-6,
    )

    assert result.loc[0, "source_value_pj"] == pytest.approx(3.994348)
    assert result.loc[1, "source_value_pj"] == pytest.approx(406.925849)
    assert set(result["status"]) == {"match"}
    assert set(result["reference_source"]) == {"ESTO (direct demand components)"}


def test_transmission_parent_and_loss_branch_remain_distinct() -> None:
    assert balance_tables._normalize_conventional_sector_name(
        "Transmission and Distribution"
    ) == "Transmission and Distribution"
    assert balance_tables._normalize_conventional_sector_name(
        "Transmission and distribution loss"
    ) == "Transmission and distribution loss"


@pytest.mark.parametrize(
    ("source_value", "expected_status"),
    [(99.995, "match"), (99.0, "value_mismatch")],
)
def test_difference_table_uses_point_zero_one_percent_rounding_rule(
    source_value: float,
    expected_status: str,
) -> None:
    table = diagnostics.build_leap_source_difference_table(
        comparison_long=_comparison_rows(
            scenario="Target",
            year=2023,
            leap_value=100.0,
            source="projection",
            source_value=source_value,
        ),
        mapping_status=_mapping_status(
            ninth_pairs=[("09_06_gas_processing_plants", "08_01_natural_gas")]
        ),
        economy="20_USA",
        years=[2023],
        scenarios=["Target"],
    )

    assert table.iloc[0]["status"] == expected_status


def test_base_year_uses_esto_and_matches_across_economy_code_formats() -> None:
    comparison = _comparison_rows(
        scenario="Target",
        year=2022,
        leap_value=5.0,
        source="base",
        source_value=5.0,
    )
    comparison.loc[comparison["source"].eq("base"), "economy"] = "20USA"
    table = diagnostics.build_leap_source_difference_table(
        comparison_long=comparison,
        mapping_status=_mapping_status(
            ninth_pairs=[("09_06_gas_processing_plants", "08_01_natural_gas")]
        ),
        leap_long=_leap_long(components=[("Gas processing", "Natural gas")]),
        economy="20_USA",
        years=[2022],
        scenarios=["Target"],
    )

    row = table.iloc[0]
    assert row["reference_source"] == "ESTO"
    assert row["status"] == "match"
    assert row["comparison_grain"] == "direct_leap_to_esto_pair"
    assert bool(row["update_allocation_required"]) is False


def test_full_leap_path_keeps_aggregated_buildings_source_separate() -> None:
    """A detailed Buildings comparator must not inflate the aggregate branch."""
    comparison = pd.DataFrame(
        [
            {
                "economy": "01_AUS",
                "scenario": "Target",
                "sheet": "Buildings",
                "measure": "Energy balance (PJ)",
                "fuel_label": "Electricity",
                "comparison_branch_path": "All demand aggregated/Buildings",
                "source": "leap",
                "year": 2022,
                "value": 481.326603,
            },
            {
                "economy": "01_AUS",
                "scenario": "Target",
                "sheet": "Buildings",
                "measure": "Energy balance (PJ)",
                "fuel_label": "Electricity",
                "comparison_branch_path": "All demand aggregated/Buildings",
                "source": "base",
                "year": 2022,
                "value": 481.326603,
            },
            {
                "economy": "01_AUS",
                "scenario": "Target",
                "sheet": "Buildings",
                "measure": "Energy balance (PJ)",
                "fuel_label": "Electricity",
                "comparison_branch_path": "Buildings/Services",
                "source": "leap",
                "year": 2022,
                "value": 0.0,
            },
            {
                "economy": "01_AUS",
                "scenario": "Target",
                "sheet": "Buildings",
                "measure": "Energy balance (PJ)",
                "fuel_label": "Electricity",
                "comparison_branch_path": "Buildings/Services",
                "source": "base",
                "year": 2022,
                "value": 231.877955,
            },
        ]
    )
    mapping_status = pd.DataFrame(
        [
            {
                "sheet": "Buildings",
                "measure": "Energy balance (PJ)",
                "fuel_label": "Electricity",
                "comparison_branch_path": "All demand aggregated/Buildings",
                "esto_flow": "16.01-16.02 Buildings",
                "esto_product": "17 Electricity",
                "sector_code_9th": "",
                "ninth_fuel_code": "",
            },
            {
                "sheet": "Buildings",
                "measure": "Energy balance (PJ)",
                "fuel_label": "Electricity",
                "comparison_branch_path": "Buildings/Services",
                "esto_flow": "16.01 Commercial and public services",
                "esto_product": "17 Electricity",
                "sector_code_9th": "",
                "ninth_fuel_code": "",
            },
        ]
    )

    table = diagnostics.build_leap_source_difference_table(
        comparison_long=comparison,
        mapping_status=mapping_status,
        economy="01_AUS",
        years=[2022],
        scenarios=["Target"],
    )

    aggregate = table.loc[
        table["comparison_branch_path"].eq("All demand aggregated/Buildings")
    ].iloc[0]
    assert aggregate["source_value_pj"] == pytest.approx(481.326603)
    assert aggregate["status"] == "match"


def test_international_demand_compares_positive_bunker_magnitude() -> None:
    comparison = _comparison_rows(
        scenario="Reference",
        year=2022,
        leap_value=25.0,
        source="base",
        source_value=-25.0,
    )
    comparison["sheet"] = "International transport"
    comparison["fuel_label"] = "07.08 Fuel oil"
    mapping_status = pd.DataFrame(
        [
            {
                "sheet": "International transport",
                "measure": "Energy balance (PJ)",
                "fuel_label": "07.08 Fuel oil",
                "esto_flow": "04-05 International transport (bunkers)",
                "esto_product": "07.08 Fuel oil",
                "sector_code_9th": "04_international_marine_bunkers",
                "ninth_fuel_code": "07_08_fuel_oil",
                "leap_sector_name_full_path": (
                    "All demand aggregated/International transport"
                ),
                "mapped_leap_sector_name": "International transport",
                "raw_leap_fuel_name": "Fuel oil",
            }
        ]
    )

    table = diagnostics.build_leap_source_difference_table(
        comparison_long=comparison,
        mapping_status=mapping_status,
        leap_long=None,
        economy="20_USA",
        years=[2022],
        scenarios=["Reference"],
    )

    row = table.iloc[0]
    assert row["sheet"] == "International transport"
    assert row["source_value_pj"] == pytest.approx(25.0)
    assert row["difference_pj"] == pytest.approx(0.0)
    assert row["status"] == "match"


def test_aggregated_international_demand_compares_positive_bunker_magnitude() -> None:
    comparison = _comparison_rows(
        scenario="Target",
        year=2022,
        leap_value=74.1253,
        source="base",
        source_value=-74.125251,
    )
    comparison["sheet"] = "esto__04__-05_International_transport__bunkers"
    comparison["fuel_label"] = "Kerosene type jet fuel"
    comparison["comparison_branch_path"] = (
        "All demand aggregated/International transport"
    )
    mapping_status = pd.DataFrame(
        [
            {
                "sheet": "esto__04__-05_International_transport__bunkers",
                "measure": "Energy balance (PJ)",
                "fuel_label": "Kerosene type jet fuel",
                "comparison_branch_path": (
                    "All demand aggregated/International transport"
                ),
                "esto_flow": "04-05 International transport (bunkers)",
                "esto_product": "07.05 Kerosene type jet fuel",
                "sector_code_9th": "",
                "ninth_fuel_code": "",
            }
        ]
    )

    table = diagnostics.build_leap_source_difference_table(
        comparison_long=comparison,
        mapping_status=mapping_status,
        economy="01_AUS",
        years=[2022],
        scenarios=["Target"],
        tolerance_pj=0.001,
    )

    row = table.iloc[0]
    assert row["source_value_pj"] == pytest.approx(74.125251)
    assert row["difference_pj"] == pytest.approx(0.000049)
    assert row["status"] == "match"


def test_transfer_preserves_signed_leap_balance_mismatch() -> None:
    comparison = _comparison_rows(
        scenario="Reference",
        year=2022,
        leap_value=-1.967001,
        source="base",
        source_value=1.967001,
    )
    comparison["sheet"] = "esto__08__Transfers"
    comparison["fuel_label"] = "Bitumen"
    mapping_status = pd.DataFrame(
        [
            {
                "sheet": "esto__08__Transfers",
                "measure": "Energy balance (PJ)",
                "fuel_label": "Bitumen",
                "esto_flow": "08 Transfers",
                "esto_product": "07.14 Bitumen",
                "sector_code_9th": "",
                "ninth_fuel_code": "",
            }
        ]
    )

    table = diagnostics.build_leap_source_difference_table(
        comparison_long=comparison,
        mapping_status=mapping_status,
        economy="20_USA",
        years=[2022],
        scenarios=["Reference"],
    )

    row = table.iloc[0]
    assert row["leap_value_pj"] == pytest.approx(-1.967001)
    assert row["source_value_pj"] == pytest.approx(1.967001)
    assert row["difference_pj"] == pytest.approx(-3.934002)
    assert row["status"] == "value_mismatch"
    assert bool(row["is_mismatch"]) is True


def test_statistical_differences_compares_opposite_source_sign() -> None:
    comparison = _comparison_rows(
        scenario="Target",
        year=2022,
        leap_value=-93.528088,
        source="base",
        source_value=93.528088,
    )
    comparison["sheet"] = "esto__11__Statistical_discrepancy"
    comparison["fuel_label"] = "Crude oil"
    mapping_status = pd.DataFrame(
        [
            {
                "sheet": "esto__11__Statistical_discrepancy",
                "measure": "Energy balance (PJ)",
                "fuel_label": "Crude oil",
                "esto_flow": "11 Statistical discrepancy",
                "esto_product": "06.01 Crude oil",
                "sector_code_9th": "",
                "ninth_fuel_code": "",
                "leap_sector_name_full_path": "Statistical Differences",
                "mapped_leap_sector_name": "Statistical Differences",
                "raw_leap_fuel_name": "Crude oil",
            }
        ]
    )

    table = diagnostics.build_leap_source_difference_table(
        comparison_long=comparison,
        mapping_status=mapping_status,
        economy="01_AUS",
        years=[2022],
        scenarios=["Target"],
    )

    row = table.iloc[0]
    assert row["source_value_pj"] == pytest.approx(-93.528088)
    assert row["difference_pj"] == pytest.approx(0.0)
    assert row["status"] == "match"


def test_base_year_backfills_mapped_pair_when_comparison_row_is_empty() -> None:
    comparison = _comparison_rows(
        scenario="Reference",
        year=2022,
        leap_value=3.994348,
        source="base",
        source_value=None,
    )
    comparison["sheet"] = "Road"
    comparison["fuel_label"] = "07.08 Fuel oil"
    mapping_status = pd.DataFrame(
        [
            {
                "sheet": "Road",
                "measure": "Energy balance (PJ)",
                "fuel_label": "07.08 Fuel oil",
                "esto_flow": "15.02 Road",
                "esto_product": "07.08 Fuel oil",
                "sector_code_9th": "15_02_road",
                "ninth_fuel_code": "07_08_fuel_oil",
            }
        ]
    )
    base_df = pd.DataFrame(
        [
            {
                "economy": "05PRC",
                "flows": "15.02 Road",
                "products": "07.08 Fuel oil",
                "2022": 3.994348,
            }
        ]
    )

    table = diagnostics.build_leap_source_difference_table(
        comparison_long=comparison,
        mapping_status=mapping_status,
        leap_long=None,
        base_df=base_df,
        economy="05_PRC",
        years=[2022],
        scenarios=["Reference"],
    )

    row = table.iloc[0]
    assert row["source_value_pj"] == pytest.approx(3.994348)
    assert row["status"] == "match"


def test_base_year_does_not_backfill_ambiguous_multi_pair_cell() -> None:
    comparisons = []
    for sheet in [
        "esto__09_06_02_01__Liquefaction",
        "esto__09_06_02_02__Regasification",
    ]:
        comparison = _comparison_rows(
            scenario="Reference",
            year=2022,
            leap_value=-3292.703662,
            source="base",
            source_value=None,
        )
        comparison["sheet"] = sheet
        comparison["fuel_label"] = "LNG"
        comparisons.append(comparison)
    comparison = pd.concat(comparisons, ignore_index=True)
    mapping_status = pd.DataFrame(
        [
            {
                "sheet": sheet,
                "measure": "Energy balance (PJ)",
                "fuel_label": "LNG",
                "esto_flow": esto_flow,
                "esto_product": "08.02 LNG",
                "sector_code_9th": "",
                "ninth_fuel_code": "",
            }
            for sheet, esto_flow in [
                (
                    "esto__09_06_02_01__Liquefaction",
                    "09.06.02.01 Liquefaction",
                ),
                (
                    "esto__09_06_02_02__Regasification",
                    "09.06.02.02 Regasification",
                ),
            ]
        ]
    )
    leap_long = pd.DataFrame(
        [
            {
                "sheet_name": sheet,
                "measure": "Energy balance (PJ)",
                "fuel_label": "LNG",
                "leap_sector_name": "LNG regasification/Regasification",
                "leap_fuel_name": "LNG",
            }
            for sheet in [
                "esto__09_06_02_01__Liquefaction",
                "esto__09_06_02_02__Regasification",
            ]
        ]
    )
    base_df = pd.DataFrame(
        [
            {
                "economy": "05PRC",
                "flows": "09.06.02.02 Regasification",
                "products": "08.02 LNG",
                "2022": -3292.703662,
            }
        ]
    )

    table = diagnostics.build_leap_source_difference_table(
        comparison_long=comparison,
        mapping_status=mapping_status,
        leap_long=leap_long,
        base_df=base_df,
        economy="05_PRC",
        years=[2022],
        scenarios=["Reference"],
    )

    assert len(table) == 2
    assert table["source_value_pj"].isna().all()
    assert set(table["status"]) == {"reference_unavailable"}


def test_single_target_reassigned_base_pair_is_expected_zero() -> None:
    comparison = _comparison_rows(
        scenario="Reference",
        year=2022,
        leap_value=3.994348,
        source="base",
        source_value=None,
    )
    comparison["sheet"] = "Road"
    comparison["fuel_label"] = "07.08 Fuel oil"
    mapping_status = pd.DataFrame(
        [
            {
                "sheet": "Road",
                "measure": "Energy balance (PJ)",
                "fuel_label": "07.08 Fuel oil",
                "esto_flow": "15.02 Road",
                "esto_product": "07.08 Fuel oil",
                "sector_code_9th": "15_02_road",
                "ninth_fuel_code": "07_08_fuel_oil",
            }
        ]
    )
    reassignment_status = pd.DataFrame(
        [
            {
                "dataset": "base_df",
                "matched_rows": 1,
                "source_esto_flow": "15.02 Road",
                "source_esto_product": "07.08 Fuel oil",
                "target_esto_flow": "15.06 Non-specified transport",
                "target_esto_product": "07.08 Fuel oil",
            }
        ]
    )

    table = diagnostics.build_leap_source_difference_table(
        comparison_long=comparison,
        mapping_status=mapping_status,
        leap_long=None,
        reassignment_status=reassignment_status,
        economy="05_PRC",
        years=[2022],
        scenarios=["Reference"],
    )

    row = table.iloc[0]
    assert row["source_value_pj"] == 0.0
    assert row["status"] == "value_mismatch"


def test_oil_refining_base_comparator_adds_only_configured_own_use_flow() -> None:
    comparison = _comparison_rows(
        scenario="Reference",
        year=2022,
        leap_value=-8.0,
        source="base",
        source_value=-5.0,
    )
    comparison["sheet"] = "09.07 Oil refineries"
    comparison["fuel_label"] = "08.01 Natural gas"
    mapping_status = pd.DataFrame(
        [
            {
                "sheet": "09.07 Oil refineries",
                "measure": "Energy balance (PJ)",
                "fuel_label": "08.01 Natural gas",
                "esto_flow": "09.07 Oil refineries",
                "esto_product": "08.01 Natural gas",
                "sector_code_9th": "",
                "ninth_fuel_code": "",
            }
        ]
    )
    base_df = pd.DataFrame(
        [
            {
                "economy": "01AUS",
                "flows": "10.01.11 Oil refineries",
                "products": "08.01 Natural gas",
                "is_subtotal": False,
                "2022": -3.0,
            },
            {
                "economy": "01AUS",
                "flows": "10.01.12 Petrochemical industry",
                "products": "08.01 Natural gas",
                "is_subtotal": False,
                "2022": -99.0,
            },
        ]
    )

    table = diagnostics.build_leap_source_difference_table(
        comparison_long=comparison,
        mapping_status=mapping_status,
        leap_long=None,
        base_df=base_df,
        economy="01_AUS",
        years=[2022],
        scenarios=["Reference"],
    )

    row = table.iloc[0]
    assert row["source_value_pj"] == pytest.approx(-8.0)
    assert row["difference_pj"] == pytest.approx(0.0)
    assert row["status"] == "match"


def test_lng_projection_comparator_does_not_absorb_demand_owned_own_use() -> None:
    natural_gas = _comparison_rows(
        scenario="Reference",
        year=2023,
        leap_value=-110.0,
        source="projection",
        source_value=-100.0,
    )
    natural_gas["sheet"] = "09.06.02.01 Liquefaction"
    natural_gas["fuel_label"] = "08.01 Natural gas"
    electricity = _comparison_rows(
        scenario="Reference",
        year=2023,
        leap_value=-2.0,
        source="projection",
        source_value=None,
    )
    electricity["sheet"] = "09.06.02.01 Liquefaction"
    electricity["fuel_label"] = "17 Electricity"
    comparison = pd.concat([natural_gas, electricity], ignore_index=True)
    mapping_status = pd.DataFrame(
        [
            {
                "sheet": "09.06.02.01 Liquefaction",
                "measure": "Energy balance (PJ)",
                "fuel_label": product,
                "esto_flow": "09.06.02.01 Liquefaction",
                "esto_product": product,
                "sector_code_9th": "09_06_02_liquefaction_regasification_plants",
                "ninth_fuel_code": product,
            }
            for product in ["08.01 Natural gas", "17 Electricity"]
        ]
    )
    projection_tables = pd.DataFrame(
        [
            {
                "scenario": "Reference",
                "esto_flow": "10.01.03 Liquefaction/regasification plants",
                "esto_product": "08.01 Natural gas",
                "2023": -10.0,
            },
            {
                "scenario": "Reference",
                "esto_flow": "10.01.03 Liquefaction/regasification plants",
                "esto_product": "17 Electricity",
                "2023": -2.0,
            },
        ]
    )

    table = diagnostics.build_leap_source_difference_table(
        comparison_long=comparison,
        mapping_status=mapping_status,
        leap_long=None,
        projection_tables=projection_tables,
        economy="20_USA",
        years=[2023],
        scenarios=["Reference"],
    )

    indexed = table.set_index("esto_product")
    assert indexed.loc["08.01 Natural gas", "source_value_pj"] == pytest.approx(
        -100.0
    )
    assert pd.isna(indexed.loc["17 Electricity", "source_value_pj"])
    assert set(table["transformation_auxiliary_comparison_status"]) == {""}
    assert indexed.loc["08.01 Natural gas", "status"] == "value_mismatch"
    assert indexed.loc["17 Electricity", "status"] == "reference_unavailable"


def test_lng_parent_projection_alias_requires_exactly_one_visible_child() -> None:
    projection = pd.DataFrame(
        [
            {
                "scenario": "Reference",
                "esto_flow": "09.06.02 Liquefaction/regasification plants",
                "esto_product": "08.01 Natural gas",
                "2023": -100.0,
            }
        ]
    )
    liquefaction_only = pd.DataFrame(
        [{"esto_flow": "09.06.02.01 Liquefaction"}]
    )

    aliased = diagnostics._add_single_lng_child_projection_alias(
        projection_tables=projection,
        mapping_status=liquefaction_only,
    )

    assert set(aliased["esto_flow"]) == {
        "09.06.02 Liquefaction/regasification plants",
        "09.06.02.01 Liquefaction",
    }

    both_children = pd.DataFrame(
        [
            {"esto_flow": "09.06.02.01 Liquefaction"},
            {"esto_flow": "09.06.02.02 Regasification"},
        ]
    )
    not_aliased = diagnostics._add_single_lng_child_projection_alias(
        projection_tables=projection,
        mapping_status=both_children,
    )
    assert not_aliased["esto_flow"].tolist() == [
        "09.06.02 Liquefaction/regasification plants"
    ]


def test_direct_lng_fallback_uses_exact_projection_pairs_without_base_shares(
    tmp_path: Path,
) -> None:
    mapping_path = tmp_path / "pairs.csv"
    pd.DataFrame(
        [
            {
                "ninth_sector": "09_06_02_liquefaction_regasification_plants",
                "ninth_fuel": "08_01_natural_gas",
                "esto_flow": "09.06.02 Liquefaction/regasification plants",
                "esto_product": "08.01 Natural gas",
            },
            {
                "ninth_sector": "09_06_02_liquefaction_regasification_plants",
                "ninth_fuel": "08_02_lng",
                "esto_flow": "09.06.02 Liquefaction/regasification plants",
                "esto_product": "08.02 LNG",
            },
        ]
    ).to_csv(mapping_path, index=False)
    ninth = pd.DataFrame(
        [
            {
                "economy": "20_USA",
                "scenarios": "target",
                "sub2sectors": "09_06_02_liquefaction_regasification_plants",
                "fuels": "08_gas",
                "subfuels": "08_01_natural_gas",
                "2023": -100.0,
            },
            {
                "economy": "20_USA",
                "scenarios": "target",
                "sub2sectors": "09_06_02_liquefaction_regasification_plants",
                "fuels": "08_gas",
                "subfuels": "08_02_lng",
                "2023": 100.0,
            },
        ]
    )

    fallback = diagnostics._add_direct_lng_projection_fallback(
        projection_tables=pd.DataFrame(),
        ninth_df=ninth,
        mapping_status=pd.DataFrame(
            [{"esto_flow": "09.06.02.01 Liquefaction"}]
        ),
        mapping_pairs_path=mapping_path,
        economy="20_USA",
        projection_years=[2023],
        scenarios=["Target"],
    )

    indexed = fallback.set_index("esto_product")
    assert set(fallback["esto_flow"]) == {"09.06.02.01 Liquefaction"}
    assert indexed.loc["08.01 Natural gas", "2023"] == pytest.approx(-100.0)
    assert indexed.loc["08.02 LNG", "2023"] == pytest.approx(100.0)


def test_shared_ninth_pair_across_esto_rows_requires_allocation() -> None:
    mapping_status = _mapping_status(
        ninth_pairs=[("09_06_gas_processing_plants", "08_01_natural_gas")]
    )
    shared = mapping_status.iloc[0].copy()
    shared["sheet"] = "02 Imports"
    shared["fuel_label"] = "06.08 Other hydrocarbons"
    shared["esto_flow"] = "02 Imports"
    shared["esto_product"] = "06.08 Other hydrocarbons"
    mapping_status = pd.concat(
        [mapping_status, shared.to_frame().T],
        ignore_index=True,
    )

    table = diagnostics.build_leap_source_difference_table(
        comparison_long=_comparison_rows(
            scenario="Reference",
            year=2023,
            leap_value=12.0,
            source="projection",
            source_value=10.0,
        ),
        mapping_status=mapping_status,
        leap_long=_leap_long(components=[("Gas processing", "Natural gas")]),
        economy="20_USA",
        years=[2023],
        scenarios=["Reference"],
    )

    row = table.iloc[0]
    assert row["ninth_pair_count"] == 1
    assert row["ninth_pair_max_esto_claimants"] == 2
    assert row["comparison_grain"] == "aggregate_shared_ninth_pair_across_esto_rows"
    assert bool(row["update_allocation_required"]) is True
    assert row["update_allocation_reason"] == (
        "ninth_pair_is_shared_by_multiple_esto_pairs"
    )


def test_canonical_projection_allocation_resolves_shared_ninth_pair() -> None:
    comparison = _comparison_rows(
        scenario="Reference",
        year=2023,
        leap_value=42.0,
        source="projection",
        source_value=100.0,
    )
    mapping_status = _mapping_status(
        ninth_pairs=[("09_06_gas_processing_plants", "08_01_natural_gas")]
    )
    shared = mapping_status.iloc[0].copy()
    shared["sheet"] = "02 Imports"
    shared["fuel_label"] = "06.08 Other hydrocarbons"
    shared["esto_flow"] = "02 Imports"
    shared["esto_product"] = "06.08 Other hydrocarbons"
    mapping_status = pd.concat(
        [mapping_status, shared.to_frame().T],
        ignore_index=True,
    )
    projection_tables = pd.DataFrame(
        [
            {
                "scenario": "Reference",
                "economy_key": "20USA",
                "esto_flow": "09.06 Gas processing plants",
                "esto_product": "08.01 Natural gas",
                2023: 40.0,
            },
            {
                "scenario": "Reference",
                "economy_key": "20USA",
                "esto_flow": "02 Imports",
                "esto_product": "06.08 Other hydrocarbons",
                2023: 60.0,
            },
        ]
    )
    provenance = pd.DataFrame(
        [
            {
                "scenario": "Reference",
                "year": 2023,
                "esto_flow": "09.06 Gas processing plants",
                "esto_product": "08.01 Natural gas",
                "allocation_method": "proportional_esto_base_year",
                "share_source": "economy",
            }
        ]
    )

    allocated, allocation_status = (
        diagnostics.apply_canonical_projection_comparators(
            comparison_long=comparison,
            mapping_status=mapping_status,
            projection_tables=projection_tables,
            allocation_provenance=provenance,
        )
    )
    table = diagnostics.build_leap_source_difference_table(
        comparison_long=allocated,
        mapping_status=mapping_status,
        leap_long=_leap_long(components=[("Gas processing", "Natural gas")]),
        projection_allocation_status=allocation_status,
        economy="20_USA",
        years=[2023],
        scenarios=["Reference"],
    )

    row = table.iloc[0]
    assert row["source_value_pj"] == pytest.approx(40.0)
    assert row["difference_pj"] == pytest.approx(2.0)
    assert bool(row["projection_allocation_complete"]) is True
    assert row["projection_target_pair_count"] == 1
    assert row["projection_matched_pair_count"] == 1
    assert row["projection_allocation_methods"] == (
        "proportional_esto_base_year"
    )
    assert row["comparison_grain"] == "canonical_allocated_ninth_to_esto_pair"
    assert bool(row["update_allocation_required"]) is False
    assert row["update_allocation_reason"] == ""


def test_canonical_projection_allocation_rolls_detailed_flows_to_parent() -> None:
    comparison = _comparison_rows(
        scenario="Reference",
        year=2023,
        leap_value=30.0,
        source="projection",
        source_value=500.0,
    )
    comparison["sheet"] = "Industry"
    comparison["fuel_label"] = "02.08 BKB/PB"
    mapping_status = pd.DataFrame(
        [
            {
                "sheet": "Industry",
                "measure": "Energy balance (PJ)",
                "fuel_label": "02.08 BKB/PB",
                "esto_flow": "14 Industry sector",
                "esto_product": "02.08 BKB/PB",
                "sector_code_9th": "14_industry_sector",
                "ninth_fuel_code": "02_coal_products",
            },
            {
                "sheet": "Industry",
                "measure": "Energy balance (PJ)",
                "fuel_label": "02.01 Coke oven coke",
                "esto_flow": "14 Industry sector",
                "esto_product": "02.01 Coke oven coke",
                "sector_code_9th": "14_industry_sector",
                "ninth_fuel_code": "02_coal_products",
            },
        ]
    )
    projection_tables = pd.DataFrame(
        [
            {
                "scenario": "Reference",
                "esto_flow": "14.01 Mining and quarrying",
                "esto_product": "02.08 BKB/PB",
                2023: 10.0,
            },
            {
                "scenario": "Reference",
                "esto_flow": "14.03.11 Non-specified industry",
                "esto_product": "02.08 BKB/PB",
                2023: 20.0,
            },
        ]
    )

    allocated, allocation_status = (
        diagnostics.apply_canonical_projection_comparators(
            comparison_long=comparison,
            mapping_status=mapping_status,
            projection_tables=projection_tables,
            allocation_provenance=pd.DataFrame(),
        )
    )
    table = diagnostics.build_leap_source_difference_table(
        comparison_long=allocated,
        mapping_status=mapping_status,
        leap_long=None,
        projection_allocation_status=allocation_status,
        economy="20_USA",
        years=[2023],
        scenarios=["Reference"],
    )

    row = table.iloc[0]
    assert row["source_value_pj"] == pytest.approx(30.0)
    assert row["difference_pj"] == pytest.approx(0.0)
    assert row["status"] == "match"
    assert bool(row["projection_allocation_complete"]) is True
    assert row["projection_target_pair_count"] == 1
    assert row["projection_matched_pair_count"] == 1
    assert row["comparison_grain"] == "canonical_allocated_ninth_to_esto_pair"
    assert bool(row["update_allocation_required"]) is False


def test_missing_reference_is_visible_but_not_called_a_mismatch() -> None:
    comparison = _comparison_rows(
        scenario="Reference",
        year=2023,
        leap_value=4.0,
        source="projection",
        source_value=None,
    )
    table = diagnostics.build_leap_source_difference_table(
        comparison_long=comparison,
        mapping_status=_mapping_status(ninth_pairs=[]),
        leap_long=_leap_long(components=[("Gas processing", "Natural gas")]),
        economy="20_USA",
        years=[2023],
        scenarios=["Reference"],
    )

    row = table.iloc[0]
    assert row["status"] == "reference_unavailable"
    assert bool(row["is_mismatch"]) is False
    assert pd.isna(row["difference_pj"])


def test_pre_base_historical_years_are_rejected_explicitly() -> None:
    with pytest.raises(ValueError, match="Pre-base historical years"):
        diagnostics._validate_years([2021, 2022], base_year=2022)


def test_economy_diagnostic_rejects_level1_before_conversion(
    monkeypatch,
    tmp_path: Path,
) -> None:
    level1_path = tmp_path / "level1.xlsx"
    _write_balance_workbook(level1_path, include_level2=False)
    monkeypatch.setattr(
        diagnostics,
        "_load_optional_json",
        lambda path: pytest.fail("conversion setup ran before detail validation"),
    )

    with pytest.raises(ValueError, match="at least Level 2 detail"):
        diagnostics.run_economy_balance_diagnostic(
            economy="01_AUS",
            years=None,
            scenarios=None,
            workbook_path=level1_path,
        )


def test_direct_reference_workbook_uses_metadata_without_target(
    monkeypatch,
    tmp_path: Path,
) -> None:
    direct_path = tmp_path / "2022.xlsx"
    _write_balance_workbook(direct_path)
    calls: dict[str, object] = {}

    def _fake_convert(**kwargs):
        calls.update(kwargs)
        return {
            "leap_long": pd.DataFrame(),
            "mapping_status": pd.DataFrame(),
            "issues": pd.DataFrame(),
            "total_balance_checks": pd.DataFrame(),
            "matching_diagnostics": pd.DataFrame(),
        }

    def _fake_build(**kwargs):
        return {"comparison_long": pd.DataFrame(), "mapping_status": pd.DataFrame()}

    @contextmanager
    def _fake_runtime_paths(**kwargs):
        yield _fake_build, _fake_convert

    monkeypatch.setattr(diagnostics, "_temporary_balance_runtime_paths", _fake_runtime_paths)
    monkeypatch.setattr(
        diagnostics,
        "_write_esto_axis_extraction_mapping_workbook",
        lambda **kwargs: kwargs["output_path"],
    )
    monkeypatch.setattr(
        diagnostics,
        "build_leap_source_difference_table",
        lambda **kwargs: pd.DataFrame(columns=diagnostics.DIFFERENCE_OUTPUT_COLUMNS),
    )

    result = diagnostics.run_economy_balance_diagnostic(
        economy="01_AUS",
        years=None,
        scenarios=None,
        workbook_path=direct_path,
    )

    assert result["years"] == [2022]
    assert result["scenarios"] == ["Reference"]
    assert result["ref_workbook_path"] == direct_path
    assert result["tgt_workbook_path"] is None
    assert calls["ref_workbook_path"] == direct_path
    assert calls["tgt_workbook_path"] is None
    assert calls["ref_sheet_name_filter"] == ["Energy Balance"]
    assert calls["tgt_sheet_name_filter"] is None


def test_direct_workbook_metadata_accepts_thousand_petajoule(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    direct_path = tmp_path / "2022.xlsx"
    _write_balance_workbook(
        direct_path,
        scenario="Target",
        units="Thousand Petajoule",
    )

    monkeypatch.setattr(
        diagnostics,
        "require_level2_balance_export_detail",
        lambda paths: list(paths),
    )

    def stop_after_preflight(
        *,
        codebook_path: Path,
        sheet_map_path: Path,
        exports_root: Path,
    ):
        raise RuntimeError("preflight passed")

    monkeypatch.setattr(
        diagnostics,
        "_temporary_balance_runtime_paths",
        stop_after_preflight,
    )

    with pytest.raises(RuntimeError, match="preflight passed"):
        diagnostics.run_economy_balance_diagnostic(
            economy="01_AUS",
            years=None,
            scenarios=None,
            workbook_path=direct_path,
        )


def test_direct_workbook_metadata_rejects_unsupported_units(tmp_path: Path) -> None:
    direct_path = tmp_path / "2022.xlsx"
    _write_balance_workbook(direct_path, units="British Thermal Unit")

    with pytest.raises(ValueError, match="Joule-family"):
        diagnostics.run_economy_balance_diagnostic(
            economy="01_AUS",
            years=None,
            scenarios=None,
            workbook_path=direct_path,
        )


def test_review_table_flags_non_comparable_total_final_energy_boundary() -> None:
    row = {column: "" for column in diagnostics.DIFFERENCE_OUTPUT_COLUMNS}
    row.update(
        {
            "esto_flow": "13 Total final energy consumption",
            "esto_product": "17 Electricity",
            "leap_sector_names": "Total final energy consumption",
            "leap_fuel_names": "Electricity",
            "absolute_difference_pj": 175.0,
            "status": "value_mismatch",
        }
    )

    review = diagnostics.build_balance_review_table(pd.DataFrame([row]))

    assert review.loc[0, "primary_classification"] == "diagnostic_bug"
    assert review.loc[0, "preliminary_owner"] == "mapping_or_diagnostic"
    assert bool(review.loc[0, "material_for_review"]) is True


def test_review_table_uses_imports_as_error_signal_and_protects_other_flows() -> None:
    rows = []
    for flow, sector in [
        ("02 Imports", "Imports"),
        ("01 Production", "Production"),
        ("03 Exports", "Exports"),
        ("07 Total primary energy supply", "Total Primary Supply"),
    ]:
        row = {column: "" for column in diagnostics.DIFFERENCE_OUTPUT_COLUMNS}
        row.update(
            {
                "economy": "01_AUS",
                "scenario": "Reference",
                "year": 2022,
                "esto_flow": flow,
                "esto_product": "01.04 Anthracite",
                "leap_sector_names": sector,
                "absolute_difference_pj": 10.0,
                "status": "value_mismatch",
                "update_allocation_required": False,
            }
        )
        rows.append(row)

    review = diagnostics.build_balance_review_table(pd.DataFrame(rows))
    indexed = review.set_index("esto_flow")

    imports = indexed.loc["02 Imports"]
    assert imports["balance_variable_role"] == "error_signal"
    assert bool(imports["allowed_to_change"]) is True
    assert imports["error_signal_name"] == "imports_gap"
    assert bool(imports["update_signal_eligible"]) is True
    assert bool(imports["requires_issue_review"]) is False

    for flow in ["01 Production", "03 Exports"]:
        protected = indexed.loc[flow]
        assert protected["balance_variable_role"] == "protected"
        assert protected["balance_contract_issue"] == "protected_flow_difference"
        assert bool(protected["update_signal_eligible"]) is False
        assert bool(protected["requires_issue_review"]) is True

    total = indexed.loc["07 Total primary energy supply"]
    assert total["balance_variable_role"] == "derived_check"
    assert total["balance_contract_issue"] == "derived_balance_difference"
    assert bool(total["requires_issue_review"]) is True


def test_review_marks_seed_process_and_affected_supply_fuels() -> None:
    rows = []
    for flow, sector, leap_value, source_value, status in [
        ("09.08.01 Coke ovens", "Coke ovens", -20.0, 0.0, "value_mismatch"),
        ("09.07 Oil refineries", "Oil Refining", -2.0, 0.0, "value_mismatch"),
        ("01 Production", "Production", 5.0, 4.0, "value_mismatch"),
        ("02 Imports", "Imports", 7.0, 6.0, "value_mismatch"),
        ("03 Exports", "Exports", -3.0, -2.0, "value_mismatch"),
    ]:
        row = {column: "" for column in diagnostics.DIFFERENCE_OUTPUT_COLUMNS}
        row.update(
            {
                "economy": "20_USA",
                "scenario": "Reference",
                "year": 2023,
                "esto_flow": flow,
                "esto_product": "02.01 Coke oven coke",
                "leap_sector_names": sector,
                "leap_fuel_names": "Coke oven coke",
                "leap_value_pj": leap_value,
                "source_value_pj": source_value,
                "difference_pj": leap_value - source_value,
                "absolute_difference_pj": abs(leap_value - source_value),
                "reference_source": "9th Outlook",
                "status": status,
                "update_allocation_required": False,
            }
        )
        rows.append(row)

    review = diagnostics.build_balance_review_table(pd.DataFrame(rows))
    indexed = review.set_index("esto_flow")
    transformation = indexed.loc["09.08.01 Coke ovens"]
    assert bool(transformation["no_direct_projection_comparator"]) is True
    assert transformation["primary_classification"] == "seed_or_carry_forward_process"
    assert transformation["balance_contract_issue"] == "no_direct_projection_comparator"
    assert bool(indexed.loc["09.07 Oil refineries", "no_direct_projection_comparator"]) is False

    for flow in ["01 Production", "02 Imports", "03 Exports"]:
        supply = indexed.loc[flow]
        assert bool(supply["affected_by_no_projection_transformation"]) is True
        assert supply["impact_source_transformation_flows"] == "09.08.01 Coke ovens"


def test_placeholder_scope_is_visible_but_not_silently_excluded() -> None:
    row = {column: "" for column in diagnostics.DIFFERENCE_OUTPUT_COLUMNS}
    row.update(
        {
            "economy": "01_AUS",
            "scenario": "Reference",
            "year": 2022,
            "esto_flow": "09.01.01,09.02.01 Electricity plants",
            "esto_product": "01.04 Anthracite",
            "leap_sector_names": "Electricity interim/Electricity interim",
            "absolute_difference_pj": 10.0,
            "status": "value_mismatch",
            "update_allocation_required": False,
        }
    )

    review = diagnostics.build_balance_review_table(pd.DataFrame([row]))

    assert bool(review.loc[0, "placeholder_scope"]) is True
    assert review.loc[0, "balance_contract_issue"] == "protected_flow_difference"
    assert bool(review.loc[0, "requires_issue_review"]) is True
    assert "not automatically excluded" in review.loc[0, "placeholder_scope_reason"]


def test_more_specific_rule_can_allow_a_non_import_error_signal() -> None:
    rules = diagnostics.load_balance_variable_rules()
    rules = pd.concat(
        [
            rules,
            pd.DataFrame(
                [
                    {
                        "economy": "01_AUS",
                        "scenario": "Reference",
                        "esto_product": "17 Electricity",
                        "esto_flow": "03 Exports",
                        "balance_variable_role": "error_signal",
                        "error_signal_name": "exports_gap",
                        "reason": "Reviewed product-specific exception.",
                        "enabled": True,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    row = {column: "" for column in diagnostics.DIFFERENCE_OUTPUT_COLUMNS}
    row.update(
        {
            "economy": "01_AUS",
            "scenario": "Reference",
            "year": 2022,
            "esto_flow": "03 Exports",
            "esto_product": "17 Electricity",
            "absolute_difference_pj": 10.0,
            "status": "value_mismatch",
            "update_allocation_required": False,
        }
    )

    review = diagnostics.build_balance_review_table(
        pd.DataFrame([row]),
        balance_variable_rules=rules,
    )

    assert review.loc[0, "balance_variable_role"] == "error_signal"
    assert review.loc[0, "error_signal_name"] == "exports_gap"
    assert bool(review.loc[0, "update_signal_eligible"]) is True


def test_diagnostic_counts_keep_missing_unmapped_and_total_failures_separate() -> None:
    differences = pd.DataFrame(
        [
            {
                "status": "value_mismatch",
                "comparison_grain": "direct_leap_to_esto_pair",
                "update_allocation_required": False,
            },
            {
                "status": "reference_unavailable",
                "comparison_grain": "direct_leap_to_esto_pair",
                "update_allocation_required": True,
            },
        ]
    )
    issues = pd.DataFrame(
        [
            {"reason": "missing_esto_pair", "severity": ""},
            {"reason": "total_balance_mapping_check", "severity": "error"},
        ]
    )

    counts = diagnostics.build_balance_diagnostic_counts(differences, issues)

    assert counts == {
        "value_mismatches": 1,
        "rows_missing_from_leap": 0,
        "rows_missing_from_comparator": 1,
        "unmapped_rows": 1,
        "total_balance_check_failures": 1,
        "direct_one_to_one_comparisons": 2,
        "aggregate_or_shared_unsafe_comparisons": 1,
    }


def test_supporting_issues_are_scoped_to_selected_years_and_scenarios() -> None:
    issues = pd.DataFrame(
        [
            {"scenario": "Reference", "year": 2023, "reason": "keep"},
            {"scenario": "Reference", "year": 2060, "reason": "wrong_year"},
            {"scenario": "Target", "year": 2023, "reason": "wrong_scenario"},
        ]
    )
    scoped = diagnostics._scope_rows_to_diagnostic_window(
        issues,
        years=[2023],
        scenarios=["Reference"],
    )

    assert scoped["reason"].tolist() == ["keep"]


def test_multi_economy_runner_writes_one_combined_table(monkeypatch, tmp_path: Path) -> None:
    def _fake_run_economy_balance_diagnostic(**kwargs):
        economy = kwargs["economy"]
        row = {column: "" for column in diagnostics.DIFFERENCE_OUTPUT_COLUMNS}
        row.update(
            {
                "economy": economy,
                "scenario": "Reference",
                "year": 2023,
                "leap_value_pj": 2.0,
                "source_value_pj": 1.0,
                "difference_pj": 1.0,
                "absolute_difference_pj": 1.0,
                "correction_to_match_source_pj": -1.0,
                "status": "value_mismatch",
                "is_mismatch": True,
                "update_allocation_required": False,
            }
        )
        return {
            "difference_table": pd.DataFrame([row]),
            "mapping_issues": pd.DataFrame(),
        }

    monkeypatch.setattr(
        diagnostics,
        "run_economy_balance_diagnostic",
        _fake_run_economy_balance_diagnostic,
    )
    result = diagnostics.run_baseline_seed_balance_diagnostics(
        economies=["01_AUS", "20_USA"],
        years=[2023],
        output_dir=tmp_path,
    )

    output = pd.read_csv(result["differences_path"])
    assert output["economy"].tolist() == ["01_AUS", "20_USA"]
    assert result["summary"]["comparison_rows"] == 2
    assert result["summary"]["mismatch_rows"] == 2
    assert result["mapping_issues_path"] is None
    assert result["review_path"].exists()


def test_temporary_runtime_paths_override_canonical_loader_workbook(
    tmp_path: Path,
) -> None:
    from codebase.mappings import canonical_loaders

    original = canonical_loaders.CANONICAL_WORKBOOK_PATH
    workbook = tmp_path / "outlook_mappings_master.xlsx"
    sheet_map = tmp_path / "runtime_tables" / "sheet_map.csv"
    sheet_map.parent.mkdir()

    with diagnostics._temporary_balance_runtime_paths(
        codebook_path=workbook,
        sheet_map_path=sheet_map,
        exports_root=tmp_path / "exports",
    ):
        assert canonical_loaders.CANONICAL_WORKBOOK_PATH == workbook

    assert canonical_loaders.CANONICAL_WORKBOOK_PATH == original


def test_mapping_issue_partition_ignores_totals_and_selected_aggregate_rows() -> None:
    issues = pd.DataFrame(
        [
            {
                "mapping_key_sector": "Other loss and own use/Coal mines",
                "mapping_key_fuel": "Total",
                "reason": "missing_esto_pair",
            },
            {
                "mapping_key_sector": "Total Transformation",
                "mapping_key_fuel": "Natural gas",
                "reason": "missing_esto_pair",
            },
            {
                "mapping_key_sector": "From Stocks",
                "mapping_key_fuel": "Natural gas",
                "reason": "missing_esto_pair",
            },
            {
                "mapping_key_sector": "Transmission and Distribution/Electricity",
                "mapping_key_fuel": "Electricity",
                "reason": "missing_esto_pair",
            },
        ]
    )

    active, ignored = diagnostics._partition_mapping_issues(issues)

    assert active["mapping_key_sector"].tolist() == ["From Stocks"]
    assert ignored["mapping_key_sector"].tolist() == [
        "Other loss and own use/Coal mines",
        "Total Transformation",
        "Transmission and Distribution/Electricity",
    ]
    assert ignored["diagnostic_disposition_reason"].str.len().gt(0).all()


def test_comparison_partition_ignores_selected_aggregate_boundaries() -> None:
    differences = pd.DataFrame(
        [
            {"leap_sector_names": "Total final energy consumption", "status": "value_mismatch"},
            {"leap_sector_names": "All demand aggregated", "status": "value_mismatch"},
            {"leap_sector_names": "All demand aggregated/Road", "status": "value_mismatch"},
            {"leap_sector_names": "Total Primary Supply", "status": "value_mismatch"},
        ]
    )

    active, ignored = diagnostics._partition_comparison_rows(differences)

    assert active["leap_sector_names"].tolist() == [
        "All demand aggregated/Road",
        "Total Primary Supply",
    ]
    assert ignored["leap_sector_names"].tolist() == [
        "Total final energy consumption",
        "All demand aggregated",
    ]


def test_all_demand_subtotal_flows_come_from_mapped_child_rows() -> None:
    mapping_status = pd.DataFrame(
        [
            {
                "leap_sector_name_full_path": "",
                "mapped_leap_sector_name": "All demand aggregated/Road",
                "esto_flow": "15.02 Road",
            },
            {
                "leap_sector_name_full_path": "All demand aggregated/Buildings",
                "esto_flow": "16.01-16.02 Buildings",
            },
            {
                "leap_sector_name_full_path": "LNG regasification/Regasification",
                "esto_flow": "09.06.02.01 Liquefaction",
            },
        ]
    )

    flows = diagnostics._all_demand_subtotal_comparator_flows(mapping_status)

    assert flows == {"15.02 Road", "16.01-16.02 Buildings"}


def test_aggregate_demand_comparator_splits_nonenergy_from_other_sector() -> None:
    mapping = pd.DataFrame(
        [
            {
                "leap_sector_name_full_path": "All demand aggregated/Other sector",
                "esto_flow": "16.03-16.05 Other sector (all demand aggregate)",
                "esto_product": "07.17 Other products",
            },
            {
                "leap_sector_name_full_path": "All demand aggregated/Buildings",
                "esto_flow": "16.01-16.02 Buildings",
                "esto_product": "07.17 Other products",
            },
        ]
    )
    adjusted = diagnostics._split_nonenergy_from_other_sector_comparator_mapping(
        mapping
    )
    other_selector = adjusted.loc[
        adjusted["leap_sector_name_full_path"].eq("All demand aggregated/Other sector"),
        "esto_flow",
    ].iloc[0]
    nonenergy_selector = adjusted.loc[
        adjusted["leap_sector_name_full_path"].eq("All demand aggregated/Non Energy Use"),
        "esto_flow",
    ].iloc[0]
    source = pd.DataFrame(
        [
            {
                "economy": "01AUS",
                "flows": "16.05 Non-specified others",
                "products": "07.17 Other products",
                "2022": 0.000641,
            },
            {
                "economy": "01AUS",
                "flows": "17 Non-energy use",
                "products": "07.17 Other products",
                "2022": 78.873358,
            },
        ]
    )

    assert other_selector == diagnostics.OTHER_SECTOR_COMPARATOR_FLOW
    assert nonenergy_selector == diagnostics.NONENERGY_COMPARATOR_FLOW
    assert adjusted.loc[1, "esto_flow"] == "16.01-16.02 Buildings"
    assert diagnostics.pull_base_year_value(
        source,
        base_year=2022,
        economy_code="01AUS",
        esto_flow=other_selector,
        esto_product="07.17 Other products",
    ) == pytest.approx(0.000641)
    assert diagnostics.pull_base_year_value(
        source,
        base_year=2022,
        economy_code="01AUS",
        esto_flow=nonenergy_selector,
        esto_product="07.17 Other products",
    ) == pytest.approx(78.873358)


def test_aggregate_demand_comparator_preserves_existing_nonenergy_mapping() -> None:
    mapping = pd.DataFrame(
        [
            {
                "leap_sector_name_full_path": "All demand aggregated/Other sector",
                "esto_flow": diagnostics.OTHER_SECTOR_COMPARATOR_FLOW,
                "esto_product": "07.17 Other products",
            },
            {
                "leap_sector_name_full_path": "All demand aggregated/Non Energy Use",
                "esto_flow": diagnostics.NONENERGY_COMPARATOR_FLOW,
                "esto_product": "07.17 Other products",
            },
        ]
    )

    adjusted = diagnostics._split_nonenergy_from_other_sector_comparator_mapping(mapping)

    pd.testing.assert_frame_equal(adjusted, mapping)


def test_esto_extraction_mapping_expands_transfer_rollup_components(
    tmp_path: Path,
) -> None:
    codebook_path = tmp_path / "mapping.xlsx"
    output_path = tmp_path / "extraction.xlsx"
    esto = pd.DataFrame(
        [
            {
                "leap_sector_name_full_path": "Transfers",
                "raw_leap_fuel_name": "Natural gas",
                "esto_flow": "08 Transfers",
                "esto_product": "08.01 Natural gas",
                "leap_is_subtotal": "True",
                "esto_pair_is_subtotal": "False",
                "duplicate_to_remove": "False",
                "esto_dataset_scope": "BOTH",
            },
            {
                "leap_sector_name_full_path": "NG Liquefaction/NG Liquefaction",
                "raw_leap_fuel_name": "Electricity",
                "esto_flow": "09.06.02.01 Liquefaction",
                "esto_product": "17 Electricity",
                "leap_is_subtotal": "False",
                "esto_pair_is_subtotal": "False",
                "duplicate_to_remove": "False",
                "esto_dataset_scope": "BOTH",
            },
        ]
    )
    ninth = pd.DataFrame(
        columns=[
            "leap_sector_name_full_path",
            "raw_leap_fuel_name",
            "sector_code_9th",
            "fuel_code_9th",
        ]
    )
    rollups = pd.DataFrame(
        [
            {
                "input_leap_sector_name_full_path": "Transfers unallocated",
                "input_raw_leap_fuel_name": "",
                "rolled_leap_sector_name_full_path": "Transfers",
                "rolled_raw_leap_fuel_name": "",
                "ROLLUP_MODE": "EXPANDING",
                "include": "True",
            },
            {
                "input_leap_sector_name_full_path": "Oil Refining",
                "input_raw_leap_fuel_name": "",
                "rolled_leap_sector_name_full_path": "Total transformation - no transfers",
                "rolled_raw_leap_fuel_name": "",
                "ROLLUP_MODE": "NON_EXPANDING",
                "include": "True",
            },
        ]
    )
    with pd.ExcelWriter(codebook_path) as writer:
        esto.to_excel(writer, sheet_name="leap_combined_esto", index=False)
        ninth.to_excel(writer, sheet_name="leap_combined_ninth", index=False)
        rollups.to_excel(writer, sheet_name="leap_rollup_rules", index=False)

    diagnostics._write_esto_axis_extraction_mapping_workbook(
        output_path=output_path,
        codebook_path=codebook_path,
    )
    extracted = pd.read_excel(
        output_path,
        sheet_name="leap_combined_esto",
        dtype=str,
    )

    assert "Transfers unallocated/Transfers unallocated" in set(
        extracted["leap_sector_name_full_path"]
    )
    transfer_alias = extracted[
        extracted["leap_sector_name_full_path"].eq(
            "Transfers unallocated/Transfers unallocated"
        )
    ]
    assert transfer_alias["esto_pair_is_subtotal"].tolist() == ["False"]
    assert transfer_alias["subtotal_mismatch_is_ok"].tolist() == ["True"]
    assert "Oil Refining/Oil Refining" not in set(
        extracted["leap_sector_name_full_path"]
    )
    lng_alias = extracted[
        extracted["leap_sector_name_full_path"].eq(
            "NG Liquefaction/Liquefaction"
        )
    ]
    assert lng_alias[["raw_leap_fuel_name", "esto_flow", "esto_product"]].to_dict(
        "records"
    ) == [
        {
            "raw_leap_fuel_name": "Electricity",
            "esto_flow": "09.06.02.01 Liquefaction",
            "esto_product": "17 Electricity",
        }
    ]
