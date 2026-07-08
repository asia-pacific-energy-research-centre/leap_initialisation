#%%
"""Tests for auditable export-log duplicate aggregation."""

import pandas as pd

from codebase.functions.leap_excel_io import finalise_export_df


def _row(branch: str, measure: str, value: float) -> dict[str, object]:
    return {
        "Branch_Path": branch,
        "Scenario": "Reference",
        "Measure": measure,
        "Units": "%" if measure.endswith("Share") else "Petajoule",
        "Scale": "Share" if measure.endswith("Share") else "",
        "Per...": "",
        "Date": 2023,
        "Value": value,
    }


def test_duplicate_diagnostics_classify_contributions_and_validate_share_parent() -> None:
    parent = "Transformation\\Plant\\Output Fuels"
    log = pd.DataFrame([
        _row(f"{parent}\\Fuel A", "Output Share", 30.0),
        _row(f"{parent}\\Fuel A", "Output Share", 20.0),
        _row(f"{parent}\\Fuel B", "Output Share", 50.0),
        _row("Resources\\Primary\\Gas", "Imports", 1.0),
        _row("Resources\\Primary\\Gas", "Imports", 2.0),
    ])

    result = finalise_export_df(
        log,
        scenario="Reference",
        region="United States",
        base_year=2023,
        final_year=2023,
    )

    contributions = result.attrs["duplicate_export_contributions"]
    assert set(contributions["duplicate_type"]) == {
        "expected_share_contribution",
        "unexpected_non_share_duplicate",
    }
    assert result.attrs["invalid_share_totals"].empty


def test_share_diagnostic_flags_parent_total_not_equal_to_100() -> None:
    parent = "Transformation\\Plant\\Output Fuels"
    log = pd.DataFrame([
        _row(f"{parent}\\Fuel A", "Output Share", 30.0),
        _row(f"{parent}\\Fuel A", "Output Share", 20.0),
        _row(f"{parent}\\Fuel B", "Output Share", 40.0),
    ])

    result = finalise_export_df(
        log,
        scenario="Reference",
        region="United States",
        base_year=2023,
        final_year=2023,
    )

    invalid = result.attrs["invalid_share_totals"]
    assert len(invalid) == 1
    assert invalid.iloc[0]["share_total"] == 90.0


#%%
