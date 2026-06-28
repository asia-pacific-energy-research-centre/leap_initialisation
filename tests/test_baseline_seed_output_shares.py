#%%
"""Regression tests for safe baseline-seed Output Share generation and patching."""

import pandas as pd
import pytest

from codebase.functions import transformation_record_builder as builder
from codebase.functions.patch_baseline_seeds import _deduplicate_rows_safely


def _record(sector: str, output_values: dict) -> dict:
    return {
        "economy": "05_PRC",
        "sector_title": sector,
        "process_name": sector,
        "output_values": output_values,
    }


def _identity_mapping(record: dict) -> dict:
    labels = [record["sector_title"], *record["output_values"].keys()]
    return {label: label for label in labels}


def test_transfers_unallocated_uses_genuine_output_profile_not_alphabetical_100():
    records = [_record(
        "Transfers unallocated",
        {
            "Additives and oxygenates": {2022: 0.0, 2023: 20.0, 2024: 40.0},
            "LPG": {2022: 0.0, 2023: 80.0, 2024: 60.0},
        },
    )]

    lookup = builder._build_output_share_lookup(records, _identity_mapping(records[0]), 2022, 2024)
    shares = builder._normalize_output_shares_for_export(
        lookup[("05_PRC", "Transfers unallocated")], 2022, 2024
    )

    assert shares["Additives and oxygenates"] == {2022: 20.0, 2023: 20.0, 2024: 40.0}
    assert shares["LPG"] == {2022: 80.0, 2023: 80.0, 2024: 60.0}
    assert all(sum(values[year] for values in shares.values()) == pytest.approx(100.0) for year in range(2022, 2025))


def test_chp_interim_projection_years_use_electricity_and_heat_values():
    records = [_record(
        "CHP interim",
        {
            "Electricity": {2022: 0.0, 2023: 30.0, 2024: 25.0},
            "Heat": {2022: 0.0, 2023: 70.0, 2024: 75.0},
        },
    )]

    lookup = builder._build_output_share_lookup(records, _identity_mapping(records[0]), 2022, 2024)
    shares = builder._normalize_output_shares_for_export(
        lookup[("05_PRC", "CHP interim")], 2022, 2024
    )

    assert set(shares["Electricity"]) == {2022, 2023, 2024}
    assert shares["Electricity"][2022] == pytest.approx(30.0)
    assert shares["Heat"][2024] == pytest.approx(75.0)
    assert all(sum(values[year] for values in shares.values()) == pytest.approx(100.0) for year in range(2022, 2025))


def test_all_zero_chp_preserves_zero_profile_for_capacity_gated_completion():
    records = [_record(
        "CHP interim",
        {"Electricity": {2022: 0.0, 2023: 0.0}, "Heat": {2022: 0.0, 2023: 0.0}},
    )]
    lookup = builder._build_output_share_lookup(
        records, _identity_mapping(records[0]), 2022, 2023
    )
    assert lookup[("05_PRC", "CHP interim")] == {
        "Electricity": {2022: 0.0, 2023: 0.0},
        "Heat": {2022: 0.0, 2023: 0.0},
    }


def test_patch_deduplicates_identical_rows_but_rejects_zero_vs_100_conflict():
    base = {
        "Branch Path": "Transformation\\CHP interim\\Output Fuels\\Electricity",
        "Variable": "Output Share",
        "Scenario": "Target",
        "Region": "China",
    }
    identical = pd.DataFrame([{**base, "Expression": "Data(2023,30)"}, {**base, "Expression": "Data(2023, 30.0)"}])
    resolved = _deduplicate_rows_safely(identical)
    assert len(resolved) == 1

    conflict = pd.DataFrame([{**base, "Expression": "Data(2023,0)"}, {**base, "Expression": "Data(2023,100)"}])
    with pytest.raises(ValueError, match="refusing to guess"):
        _deduplicate_rows_safely(conflict)


#%%
