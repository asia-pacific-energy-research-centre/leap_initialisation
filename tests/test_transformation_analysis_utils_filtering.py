"""Focused tests for transformation source-row filtering."""

#%%

import pandas as pd

from codebase.functions.transformation_analysis_utils import filter_total_energy_rows


def test_filter_total_energy_rows_uses_is_subtotal_for_products():
    df = pd.DataFrame(
        [
            {"products": "08 Gas", "is_subtotal": True, 2022: 100.0},
            {"products": "17 Electricity", "is_subtotal": False, 2022: 917.279418},
            {"products": "18 Heat", "is_subtotal": False, 2022: 25.0},
        ]
    )

    result = filter_total_energy_rows(df)

    assert result["products"].tolist() == ["17 Electricity", "18 Heat"]
    assert result[2022].sum() == 942.279418


def test_filter_total_energy_rows_uses_conservative_product_fallback_without_is_subtotal():
    df = pd.DataFrame(
        [
            {"products": "01 Coal", 2022: 1.0},
            {"products": "02 Coal products", 2022: 2.0},
            {"products": "06 Crude oil & NGL", 2022: 6.0},
            {"products": "07 Petroleum products", 2022: 7.0},
            {"products": "08 Gas", 2022: 8.0},
            {"products": "09 Nuclear", 2022: 9.0},
            {"products": "10 Hydro", 2022: 10.0},
            {"products": "12 Solar", 2022: 12.0},
            {"products": "14 Wind", 2022: 14.0},
            {"products": "15 Solid biomass", 2022: 15.0},
            {"products": "16 Others", 2022: 16.0},
            {"products": "17 Electricity", 2022: 17.0},
            {"products": "18 Heat", 2022: 18.0},
            {"products": "19 Total", 2022: 19.0},
            {"products": "20 Total Renewables", 2022: 20.0},
            {"products": "21 Modern renewables", 2022: 21.0},
        ]
    )

    result = filter_total_energy_rows(df)

    assert result["products"].tolist() == [
        "09 Nuclear",
        "10 Hydro",
        "14 Wind",
        "17 Electricity",
        "18 Heat",
    ]


#%%
