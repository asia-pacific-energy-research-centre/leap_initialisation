"""Focused tests for the independent balance-demand conservation diagnostic."""

#%%

import pandas as pd
import pytest

from codebase.functions.balance_demand_conservation import (
    build_balance_demand_conservation_diagnostics,
)


def _rows(value_column: str, values: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "economy": "20_USA",
                "scenario": "Reference",
                "sector_context": "Industry",
                "esto_product": product,
                "year": 2030,
                value_column: value,
            }
            for product, value in zip(["07.01 Motor gasoline", "08.01 Natural gas"], values)
        ]
    )


def test_conservation_diagnostic_passes_equal_independent_totals():
    diagnostics = build_balance_demand_conservation_diagnostics(
        reference_rows=_rows("reference_total", [10.0, 20.0]),
        resolved_rows=_rows("resolved_total", [10.0, 20.0]),
    )

    assert not diagnostics["is_mismatch"].any()
    assert diagnostics["difference"].tolist() == pytest.approx([0.0, 0.0])


def test_conservation_diagnostic_catches_value_and_missing_row_mismatches():
    reference = _rows("reference_total", [10.0, 20.0])
    resolved = _rows("resolved_total", [9.0, 20.0]).iloc[[0]].copy()

    diagnostics = build_balance_demand_conservation_diagnostics(reference, resolved)
    statuses = diagnostics.set_index("esto_product")["status"].to_dict()

    assert statuses == {
        "07.01 Motor gasoline": "value_mismatch",
        "08.01 Natural gas": "missing_resolved",
    }


def test_conservation_diagnostic_aggregates_mapping_augmentation_duplicates():
    reference = _rows("reference_total", [10.0, 20.0]).iloc[[0]].copy()
    resolved = pd.concat(
        [
            _rows("resolved_total", [4.0, 0.0]).iloc[[0]],
            _rows("resolved_total", [6.0, 0.0]).iloc[[0]],
        ],
        ignore_index=True,
    )

    diagnostics = build_balance_demand_conservation_diagnostics(reference, resolved)

    assert diagnostics.loc[0, "resolved_total"] == pytest.approx(10.0)
    assert diagnostics.loc[0, "status"] == "match"


def test_conservation_diagnostic_rejects_negative_tolerance():
    with pytest.raises(ValueError, match="non-negative"):
        build_balance_demand_conservation_diagnostics(
            _rows("reference_total", [10.0, 20.0]),
            _rows("resolved_total", [10.0, 20.0]),
            tolerance_pj=-1.0,
        )


#%%
