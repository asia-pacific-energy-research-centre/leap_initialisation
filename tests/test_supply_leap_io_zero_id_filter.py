"""Regression checks for final baseline-seed zero-ID filtering."""

import pandas as pd

from codebase.supply_reconciliation.leap_io import _drop_zero_only_unmatched_transformation_rows


def test_final_writer_drops_zero_only_unmatched_transformation_rows() -> None:
    rows = pd.DataFrame(
        [
            {
                "BranchID": -1,
                "Branch Path": "Transformation\\Gas works plants\\Processes\\Gas works plants\\Auxiliary Fuels\\Anthracite",
                2024: 0.0,
                2025: 0.0,
            },
            {
                "BranchID": -1,
                "Branch Path": "Transformation\\Gas works plants\\Processes\\Gas works plants\\Auxiliary Fuels\\Sub bituminous coal",
                2024: 0.2,
                2025: 0.0,
            },
            {
                "BranchID": 10,
                "Branch Path": "Transformation\\Gas works plants",
                2024: 0.0,
                2025: 0.0,
            },
        ]
    )

    result = _drop_zero_only_unmatched_transformation_rows(rows)

    assert result.index.tolist() == [1, 2]
