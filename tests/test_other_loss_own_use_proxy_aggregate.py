"""Tests for aggregate-economy proxy inputs used by compressed preflight."""

import pandas as pd

from codebase.other_loss_own_use_proxy_workflow import _append_aggregate_economy_rows


def test_append_aggregate_economy_rows_sums_members_by_balance_key():
    source = pd.DataFrame(
        {
            "economy": ["01AUS", "02BD"],
            "economy_key": ["01_AUS", "02_BD"],
            "flows": ["10.03 Own use", "10.03 Own use"],
            "products": ["01 Coal", "01 Coal"],
            2022: [-2.0, -3.0],
            2023: [-4.0, -6.0],
        }
    )

    result = _append_aggregate_economy_rows(source, economy_label="00_APEC")
    aggregate = result[result["economy_key"].eq("00_APEC")]

    assert len(aggregate) == 1
    assert aggregate.iloc[0][2022] == -5.0
    assert aggregate.iloc[0][2023] == -10.0
    assert aggregate.iloc[0]["economy"] == "00_APEC"
