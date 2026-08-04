from pathlib import Path

import pandas as pd
import pytest

from codebase.utilities.leap_results_dashboard_balance import _load_active_balance_mapping_crosswalk
from codebase.utilities.leap_results_dashboard_utils import (
    apply_explicit_sector_reassignments,
    pull_base_year_value,
)


def test_active_balance_mapping_crosswalk_does_not_require_many_to_many_is_ok(tmp_path: Path) -> None:
    workbook = tmp_path / "leap_mappings.xlsx"
    esto = pd.DataFrame(
        [
            {
                "leap_sector_name_full_path": "Industry",
                "raw_leap_fuel_name": "Gas",
                "esto_flow": "14 Industry sector",
                "esto_product": "08.01 Natural gas",
                "pair_mapping_cardinality": "many_to_many",
                "leap_is_subtotal": False,
                "esto_pair_is_subtotal": False,
            }
        ]
    )
    ninth = pd.DataFrame(
        [
            {
                "leap_sector_name_full_path": "Industry",
                "raw_leap_fuel_name": "Gas",
                "ninth_sector": "16_01_commercial_and_public_services",
                "ninth_fuel": "08_gas",
                "pair_mapping_cardinality": "many_to_many",
                "leap_is_subtotal": False,
                "ninth_pair_is_subtotal": False,
            }
        ]
    )

    with pd.ExcelWriter(workbook) as writer:
        esto.to_excel(writer, sheet_name="leap_combined_esto", index=False)
        ninth.to_excel(writer, sheet_name="leap_combined_ninth", index=False)

    crosswalk = _load_active_balance_mapping_crosswalk(workbook)

    assert len(crosswalk) == 1
    assert "esto_many_to_many_is_ok" not in crosswalk.columns
    assert "ninth_many_to_many_is_ok" not in crosswalk.columns
    assert crosswalk.loc[0, "esto_pair_mapping_cardinality"] == "many_to_many"
    assert crosswalk.loc[0, "ninth_pair_mapping_cardinality"] == "many_to_many"


def test_missing_base_pair_is_unavailable_instead_of_zero() -> None:
    esto = pd.DataFrame(
        [
            {
                "economy": "01AUS",
                "flows": "09.08.01 Coke ovens",
                "products": "02.01 Coke oven coke",
                "2022": 62.127,
            }
        ]
    )

    value = pull_base_year_value(
        esto_df=esto,
        base_year=2022,
        economy_code="01AUS",
        esto_flow="09.08.01 Coke ovens (including own use)",
        esto_product="02.01 Coke oven coke",
    )

    assert pd.isna(value)


def test_base_rollup_label_sums_exact_component_flows_without_descendants() -> None:
    esto = pd.DataFrame(
        [
            {
                "economy": "05PRC",
                "flows": "16.01 Commercial and public services",
                "products": "17 Electricity",
                "2022": 10.0,
            },
            {
                "economy": "05PRC",
                "flows": "16.01.99 Commercial and public services unallocated",
                "products": "17 Electricity",
                "2022": 4.0,
            },
            {
                "economy": "05PRC",
                "flows": "16.02 Residential",
                "products": "17 Electricity",
                "2022": 20.0,
            },
        ]
    )

    value = pull_base_year_value(
        esto_df=esto,
        base_year=2022,
        economy_code="05PRC",
        esto_flow="16.01-16.02 Buildings",
        esto_product="17 Electricity",
    )

    assert value == 30.0


def test_base_rollup_label_counts_duplicate_exact_component_once() -> None:
    esto = pd.DataFrame(
        [
            {
                "economy": "20USA",
                "flows": "16.01 Commercial and public services",
                "products": "17 Electricity",
                "2022": 10.0,
            },
            {
                "economy": "20USA",
                "flows": "16.01 Synthetic duplicate",
                "products": "17 Electricity",
                "2022": 10.0,
            },
            {
                "economy": "20USA",
                "flows": "16.02 Residential",
                "products": "17 Electricity",
                "2022": 20.0,
            },
        ]
    )

    value = pull_base_year_value(
        esto_df=esto,
        base_year=2022,
        economy_code="20USA",
        esto_flow="16.01-16.02 Buildings",
        esto_product="17 Electricity",
    )

    assert value == 30.0


def test_base_rollup_prefers_reassigned_subtotal_over_duplicate_leaf() -> None:
    esto = pd.DataFrame(
        [
            {
                "economy": "20USA",
                "flows": "16.01.02 Commercial and public services unallocated",
                "products": "17 Electricity",
                "is_subtotal": True,
                "2022": 10.0,
            },
            {
                "economy": "20USA",
                "flows": "16.01.99 Commercial and public services unallocated",
                "products": "17 Electricity",
                "is_subtotal": False,
                "2022": 10.0,
            },
            {
                "economy": "20USA",
                "flows": "16.02 Residential",
                "products": "17 Electricity",
                "is_subtotal": False,
                "2022": 20.0,
            },
        ]
    )

    value = pull_base_year_value(
        esto_df=esto,
        base_year=2022,
        economy_code="20USA",
        esto_flow="16.01-16.02 Buildings",
        esto_product="17 Electricity",
    )

    assert value == 30.0


def test_base_rollup_label_expands_comma_separated_ranges() -> None:
    esto = pd.DataFrame(
        [
            {
                "economy": "05PRC",
                "flows": f"{flow} component",
                "products": "07.08 Fuel oil",
                "2022": value,
            }
            for flow, value in [
                ("15.01", 1.0),
                ("15.02", 100.0),
                ("15.03", 3.0),
                ("15.04", 4.0),
                ("15.05", 5.0),
                ("15.06", 6.0),
            ]
        ]
    )

    value = pull_base_year_value(
        esto_df=esto,
        base_year=2022,
        economy_code="05PRC",
        esto_flow="15.01,15.03-15.06 Transport non-road",
        esto_product="07.08 Fuel oil",
    )

    assert value == 19.0


def test_explicit_reassignment_status_retains_source_pair_for_diagnostics() -> None:
    base = pd.DataFrame(
        [
            {
                "economy": "05PRC",
                "flows": "15.02 Road",
                "products": "07.08 Fuel oil",
                "2022": 3.994348,
            }
        ]
    )
    rules = pd.DataFrame(
        [
            {
                "rule_name": "road_fuel_oil_to_nonspecified",
                "source_esto_flow": "15.02 Road",
                "source_esto_product": "07.08 Fuel oil",
                "target_esto_flow": "15.06 Non-specified transport",
                "target_esto_product": "07.08 Fuel oil",
            }
        ]
    )

    adjusted, _, status = apply_explicit_sector_reassignments(
        base_df=base,
        ninth_df=pd.DataFrame(),
        reassignments=rules,
    )

    assert pd.isna(pull_base_year_value(
        adjusted,
        base_year=2022,
        economy_code="05PRC",
        esto_flow="15.02 Road",
        esto_product="07.08 Fuel oil",
    ))
    assert pull_base_year_value(
        adjusted,
        base_year=2022,
        economy_code="05PRC",
        esto_flow="15.06 Non-specified transport",
        esto_product="07.08 Fuel oil",
    ) == pytest.approx(3.994348)
    base_status = status[status["dataset"].eq("base_df")].iloc[0]
    assert base_status["source_esto_flow"] == "15.02 Road"
    assert base_status["source_esto_product"] == "07.08 Fuel oil"
