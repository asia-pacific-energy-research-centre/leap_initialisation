import pandas as pd

from codebase.functions.esto_data_utils import (
    _match_code_prefix,
    add_all_economy_total,
    build_dataset_map,
    filter_reference_scenario,
    normalize_year_columns,
    resolve_dataset,
    sum_years,
)


def test_match_code_prefix_handles_dot_and_underscore_codes() -> None:
    assert _match_code_prefix("09.06.01 Coke ovens", "09_06")
    assert _match_code_prefix("09_06_01_coke_ovens", "09.06")
    assert not _match_code_prefix("10.01.01 Transfers", "09.06")


def test_normalize_year_columns_converts_year_like_column_names() -> None:
    df = pd.DataFrame({"economy": ["20_USA"], "2022": [1.0], "2030": [2.0]})

    normalized, year_cols = normalize_year_columns(df)

    assert year_cols == [2022, 2030]
    assert 2022 in normalized.columns
    assert 2030 in normalized.columns


def test_filter_reference_scenario_keeps_reference_rows_only() -> None:
    df = pd.DataFrame(
        {
            "scenarios": ["Reference", "Target", "reference"],
            "value": [1.0, 2.0, 3.0],
        }
    )

    filtered = filter_reference_scenario(df, "test")

    assert filtered["value"].tolist() == [1.0, 3.0]


def test_add_all_economy_total_appends_grouped_total_rows() -> None:
    df = pd.DataFrame(
        {
            "economy": ["01_AUS", "02_BD"],
            "products": ["17 Electricity", "17 Electricity"],
            2022: [1.0, 2.0],
            2030: [3.0, 4.0],
        }
    )

    result = add_all_economy_total(df, [2022, 2030], economy_label="ALL")
    total = result[result["economy"].eq("ALL")].iloc[0]

    assert total["products"] == "17 Electricity"
    assert total[2022] == 3.0
    assert total[2030] == 7.0


def test_dataset_map_and_sum_helpers() -> None:
    df = pd.DataFrame({2022: [1.0, 2.0], 2030: [3.0, 4.0]})
    dataset_map = build_dataset_map(df, [2022], df, [2030], df, [2022, 2030])

    data, years = resolve_dataset(dataset_map, "matt")

    assert data is df
    assert years == [2022, 2030]
    assert sum_years(data, years) == 10.0
