#%%
"""Tests for shared 9th-bucket allocation in the supply value path.

Several ESTO products map to one coarse 9th fuel code (e.g. 02.01..02.08 all
map to 02_coal_products). Two defects are covered here:

1. select_fuel_rows: codes like 01_x_thermal_coal collapse to the bare
   ('01',) numeric prefix (segment extraction stops at "x"), so prefix
   matching alone also grabbed 01_01_coking_coal and every sibling subfuel.
   Exact code equality must win before prefix matching.
2. build_supply_value_by_year: without allocation, every product sharing a
   bucket received the full bucket series (an N-fold overcount). With a
   NinthBucketAllocator, each product gets its base-year ESTO share and the
   sibling series sum back to the bucket total.
"""

import pandas as pd

from codebase.functions.supply_value_series import (
    build_ninth_bucket_allocator,
    build_supply_value_by_year,
    select_fuel_rows,
)


def _ninth_df() -> pd.DataFrame:
    rows = [
        # Shared thermal-coal bucket: production and imports series.
        {"economy": "20_USA", "sectors": "01_production", "fuels": "01_coal",
         "subfuels": "01_x_thermal_coal", 2022: 100.0, 2023: 110.0},
        {"economy": "20_USA", "sectors": "02_imports", "fuels": "01_coal",
         "subfuels": "01_x_thermal_coal", 2022: 40.0, 2023: 44.0},
        # Sibling subfuels that the _x_ prefix bug used to swallow.
        {"economy": "20_USA", "sectors": "01_production", "fuels": "01_coal",
         "subfuels": "01_01_coking_coal", 2022: 7.0, 2023: 8.0},
        {"economy": "20_USA", "sectors": "01_production", "fuels": "01_coal",
         "subfuels": "01_05_lignite", 2022: 3.0, 2023: 4.0},
        # Second economy with no ESTO base-year rows (equal-split fallback).
        {"economy": "02_BD", "sectors": "01_production", "fuels": "01_coal",
         "subfuels": "01_x_thermal_coal", 2022: 10.0, 2023: 12.0},
    ]
    return pd.DataFrame(rows)


def _esto_df() -> pd.DataFrame:
    rows = [
        {"economy": "20_USA", "flows": "01 Production",
         "products": "01.02 Other bituminous coal", 2022: 30.0},
        {"economy": "20_USA", "flows": "01 Production",
         "products": "01.03 Sub-bituminous coal", 2022: 10.0},
        {"economy": "20_USA", "flows": "02 Imports",
         "products": "01.02 Other bituminous coal", 2022: 20.0},
        {"economy": "20_USA", "flows": "02 Imports",
         "products": "01.03 Sub-bituminous coal", 2022: 60.0},
    ]
    return pd.DataFrame(rows)


def _fuel_config() -> dict[str, dict[str, object]]:
    return {
        "01.01 Coking coal": {
            "fuel_label_esto": "01.01 Coking coal",
            "fuel_code_ninth": "01_01_coking_coal",
            "fuel_name": "Coking coal",
        },
        "01.02 Other bituminous coal": {
            "fuel_label_esto": "01.02 Other bituminous coal",
            "fuel_code_ninth": "01_x_thermal_coal",
            "fuel_name": "Other bituminous coal",
        },
        "01.03 Sub-bituminous coal": {
            "fuel_label_esto": "01.03 Sub-bituminous coal",
            "fuel_code_ninth": "01_x_thermal_coal",
            "fuel_name": "Sub bituminous coal",
        },
    }


def test_exact_code_match_precedes_prefix_match() -> None:
    data = _ninth_df()
    matched = select_fuel_rows(
        data, "01_x_thermal_coal", "01.02 Other bituminous coal",
        fuel_name="Other bituminous coal",
    )
    assert sorted(matched["subfuels"].unique()) == ["01_x_thermal_coal"]
    # Specific sibling codes are unaffected.
    coking = select_fuel_rows(
        data, "01_01_coking_coal", "01.01 Coking coal", fuel_name="Coking coal"
    )
    assert sorted(coking["subfuels"].unique()) == ["01_01_coking_coal"]


def test_shared_bucket_split_by_base_year_esto_shares() -> None:
    data = _ninth_df()
    fuel_config = _fuel_config()
    allocator = build_ninth_bucket_allocator(
        data, fuel_config, None, _esto_df(), 2022
    )
    assert allocator is not None

    def series(fuel_key: str, flow_key: str, flow_value: str) -> dict[int, float]:
        return build_supply_value_by_year(
            data, [2022, 2023], "20_USA", fuel_config[fuel_key],
            flow_key, flow_value, 2022, 2023, bucket_allocator=allocator,
        )

    # Production shares from ESTO base year: 30/40 and 10/40.
    assert series("01.02 Other bituminous coal", "production", "01_production") == {
        2022: 75.0, 2023: 82.5,
    }
    assert series("01.03 Sub-bituminous coal", "production", "01_production") == {
        2022: 25.0, 2023: 27.5,
    }
    # Imports use their own flow's base-year shares (20/80 and 60/80).
    assert series("01.02 Other bituminous coal", "imports", "02_imports") == {
        2022: 10.0, 2023: 11.0,
    }
    # A product with its own 1:1 code is untouched.
    assert series("01.01 Coking coal", "production", "01_production") == {
        2022: 7.0, 2023: 8.0,
    }


def test_sibling_series_sum_back_to_bucket_total() -> None:
    data = _ninth_df()
    fuel_config = _fuel_config()
    allocator = build_ninth_bucket_allocator(
        data, fuel_config, None, _esto_df(), 2022
    )
    totals = {2022: 0.0, 2023: 0.0}
    for fuel_key in ("01.02 Other bituminous coal", "01.03 Sub-bituminous coal"):
        values = build_supply_value_by_year(
            data, [2022, 2023], "20_USA", fuel_config[fuel_key],
            "production", "01_production", 2022, 2023,
            bucket_allocator=allocator,
        )
        for year, value in values.items():
            totals[year] += value
    assert totals == {2022: 100.0, 2023: 110.0}


def test_equal_split_fallback_when_no_base_year_rows() -> None:
    data = _ninth_df()
    fuel_config = _fuel_config()
    allocator = build_ninth_bucket_allocator(
        data, fuel_config, None, _esto_df(), 2022
    )
    # 02_BD has no ESTO base-year rows, so the two siblings split equally.
    values = build_supply_value_by_year(
        data, [2022, 2023], "02_BD", fuel_config["01.02 Other bituminous coal"],
        "production", "01_production", 2022, 2023, bucket_allocator=allocator,
    )
    assert values == {2022: 5.0, 2023: 6.0}


def test_allocator_not_built_for_esto_style_data() -> None:
    esto_style = _esto_df()  # has a "flows" column, no "sectors"
    assert build_ninth_bucket_allocator(
        esto_style, _fuel_config(), None, _esto_df(), 2022
    ) is None


def test_no_allocator_preserves_legacy_behavior() -> None:
    data = _ninth_df()
    fuel_config = _fuel_config()
    values = build_supply_value_by_year(
        data, [2022, 2023], "20_USA", fuel_config["01.02 Other bituminous coal"],
        "production", "01_production", 2022, 2023,
    )
    assert values == {2022: 100.0, 2023: 110.0}


#%%
