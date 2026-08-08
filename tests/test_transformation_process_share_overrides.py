"""Regression tests for transformation process-share overrides."""

from __future__ import annotations

import pandas as pd
import pytest

from codebase.functions import supply_leap_io


def test_unmapped_hydrogen_output_keeps_zero_smr_at_zero_share(monkeypatch) -> None:
    """Hydrogen outputs without ESTO labels still define process activity."""
    monkeypatch.setattr(supply_leap_io, "_use_legacy_trade_split_mode", lambda: False)

    records = [
        {
            "economy": "11_MEX",
            "sector_title": "Hydrogen transformation",
            "process_name": "Electrolysers",
            "output_values": {
                "Hydrogen": {2023: 0.100368576},
                "Ammonia": {2023: 0.000124098},
            },
        },
        {
            "economy": "11_MEX",
            "sector_title": "Hydrogen transformation",
            "process_name": "SMR with CCS",
            "output_values": {
                "Hydrogen": {2023: 0.0},
                "Ammonia": {2023: 0.0},
            },
            "is_zero_skeleton": True,
        },
    ]

    updated = supply_leap_io.apply_transformation_target_overrides_for_scenario(
        records,
        pd.DataFrame(),
        pd.DataFrame(),
        "Target",
    )

    assert updated[0]["process_share_by_year"][2023] == pytest.approx(100.0)
    assert updated[1]["process_share_by_year"][2023] == pytest.approx(0.0)
