from __future__ import annotations

import pandas as pd

from codebase.functions.export_zero_fill import zero_data_expression, zero_fill_unset_rows


def _universe() -> pd.DataFrame:
    return pd.DataFrame([
        {"Branch Path": "Demand\\A", "Variable": "Activity Level", "Scenario": "Target", "Region": "USA", "Units": "PJ"},
        {"Branch Path": "Demand\\B", "Variable": "Activity Level", "Scenario": "Target", "Region": "USA", "Units": "PJ"},
        {"Branch Path": "Demand\\All demand aggregated\\C", "Variable": "Activity Level", "Scenario": "Target", "Region": "USA", "Units": "PJ"},
        {"Branch Path": "Demand\\A", "Variable": "Sales Share", "Scenario": "Target", "Region": "USA", "Units": "%"},
    ])


def test_zero_fill_only_returns_unset_keys_with_data_style() -> None:
    written = _universe().iloc[[0]].copy()
    result = zero_fill_unset_rows(
        written, _universe(), include_prefixes=("Demand\\",),
        variables=("Activity Level",), scenarios=("Target",), only_unset=True,
        region="United States", expression=lambda scenario: zero_data_expression(
            scenario, base_year=2022, final_year=2024,
        ),
    )
    assert result["Branch Path"].tolist() == ["Demand\\B", "Demand\\All demand aggregated\\C"]
    assert result["Expression"].tolist() == ["Data(2022, 0.0, 2023, 0.0, 2024, 0.0)"] * 2


def test_zero_fill_supports_blanket_constant_zero_with_exclusions() -> None:
    result = zero_fill_unset_rows(
        None, _universe(), include_prefixes=("Demand\\",),
        exclude_prefixes=("Demand\\All demand aggregated\\",),
        exclude_variables=("Sales Share",), only_unset=False,
        region="United States", expression="0", metadata_columns=("Units",),
    )
    assert result["Branch Path"].tolist() == ["Demand\\A", "Demand\\B"]
    assert result["Expression"].tolist() == ["0", "0"]
    assert result["Units"].tolist() == ["PJ", "PJ"]


def test_current_accounts_zero_expression_stays_single_year() -> None:
    assert zero_data_expression("Current Accounts", base_year=2022, final_year=2024) == "Data(2022,0.0)"
