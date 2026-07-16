#%%
"""Process Efficiency fill in build_aux_fuel_zero_rows.

Every transformation process branch this workflow owns gets an explicit
Process Efficiency (default 100.0 Percent) unless it was set this run.  A
process that has Exogenous Capacity > 0 but no efficiency is a data error:
build_aux_fuel_zero_rows raises, or defers via THROW_ERROR_AFTER_RUN.
"""

import pandas as pd
import pytest

from codebase.functions import transformation_record_builder as rb
from codebase.utilities import workflow_common

PROCESS = (
    "Transformation\\Refinery and blending transfers\\Processes\\"
    "Refinery and blending transfers"
)
SECTOR_TITLE = "Refinery and blending transfers"
SCENARIOS = ["Current Accounts", "Target", "Reference"]
BASE_YEAR, FINAL_YEAR = 2022, 2024


def _catalog() -> pd.DataFrame:
    return pd.DataFrame(
        [{"fuel_group": "Feedstock Fuels", "branch_path": PROCESS + "\\Feedstock Fuels\\Crude"}]
    )


def _feedstock_row(scenario: str = "Target") -> dict:
    return {
        "Measure": "Feedstock Fuel Share",
        "Scenario": scenario,
        "Branch_Path": PROCESS + "\\Feedstock Fuels\\Crude",
        "Value": 100.0,
        "Date": 2023,
    }


def _capacity_row(value: float, scenario: str = "Target") -> dict:
    return {
        "Measure": "Exogenous Capacity",
        "Scenario": scenario,
        "Branch_Path": PROCESS,
        "Value": value,
        "Date": 2023,
    }


def _efficiency_rows(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["Measure"] == "Process Efficiency"]


def _build(existing: list[dict], titles=frozenset({SECTOR_TITLE})) -> list[dict]:
    return rb.build_aux_fuel_zero_rows(
        existing,
        _catalog(),
        SCENARIOS,
        BASE_YEAR,
        FINAL_YEAR,
        in_scope_sector_titles=set(titles),
    )


@pytest.fixture(autouse=True)
def _reset_defer_flag():
    """Keep the deferred-error registry isolated between tests."""
    saved = workflow_common.THROW_ERROR_AFTER_RUN
    workflow_common.clear_deferred_errors()
    yield
    workflow_common.THROW_ERROR_AFTER_RUN = saved
    workflow_common.clear_deferred_errors()


def test_unset_efficiency_defaults_to_100_across_scenarios() -> None:
    eff = _efficiency_rows(_build([_feedstock_row()]))

    assert eff, "expected Process Efficiency fill rows"
    assert all(r["Branch_Path"] == PROCESS for r in eff)
    assert {r["Value"] for r in eff} == {100.0}
    assert all(r["Units"] == rb.DEFAULT_EFFICIENCY_UNITS for r in eff)
    # Projected years for TGT/REF, base year for Current Accounts.
    assert {r["Date"] for r in eff if r["Scenario"] == "Current Accounts"} == {BASE_YEAR}
    assert {r["Date"] for r in eff if r["Scenario"] == "Target"} == {2023, 2024}
    assert {r["Scenario"] for r in eff} == set(SCENARIOS)


def test_explicitly_set_efficiency_is_not_overwritten() -> None:
    existing = [
        _feedstock_row(),
        {
            "Measure": "Process Efficiency",
            "Scenario": "Target",
            "Branch_Path": PROCESS,
            "Value": 90.0,
            "Date": 2023,
        },
    ]
    eff = _efficiency_rows(_build(existing))

    # Target already has efficiency this run -> no fill row for it.
    assert [r for r in eff if r["Scenario"] == "Target"] == []
    # Other scenarios are still filled.
    assert {r["Scenario"] for r in eff} == {"Current Accounts", "Reference"}


def test_capacity_present_but_no_efficiency_raises() -> None:
    workflow_common.THROW_ERROR_AFTER_RUN = False
    with pytest.raises(ValueError, match="Exogenous Capacity"):
        _build([_feedstock_row(), _capacity_row(5.0)])


def test_capacity_error_is_deferrable_and_skips_placeholder() -> None:
    workflow_common.THROW_ERROR_AFTER_RUN = True
    eff = _efficiency_rows(_build([_feedstock_row(), _capacity_row(5.0)]))

    # One deferred error recorded, no immediate raise.
    assert len(workflow_common.get_deferred_errors()) == 1
    # The capacitied scenario gets NO placeholder efficiency row...
    assert [r for r in eff if r["Scenario"] == "Target"] == []
    # ...but scenarios without capacity are still filled at 100.0.
    assert {r["Scenario"] for r in eff} == {"Current Accounts", "Reference"}
    assert {r["Value"] for r in eff} == {100.0}


def test_zero_capacity_does_not_trigger_error() -> None:
    workflow_common.THROW_ERROR_AFTER_RUN = False
    eff = _efficiency_rows(_build([_feedstock_row(), _capacity_row(0.0)]))

    # Zero capacity is fine -> Target still gets the 100.0 default.
    assert {r["Date"] for r in eff if r["Scenario"] == "Target"} == {2023, 2024}
    assert {r["Value"] for r in eff} == {100.0}
