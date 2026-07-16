"""Contract tests: the LEAP COM API is decommissioned and must stay that way.

The API is blocked repo-wide (functions/leap_api_guard.LEAP_API_BLOCKED) because
of a known LEAP API bug. The skeleton is retained in case a future LEAP release
fixes it, but nothing may silently re-enable or attempt API use in the meantime.

If a future LEAP release does fix the bug, this whole module is the deliberate
gate to revisit: clearing LEAP_API_BLOCKED will fail these tests on purpose.
"""
from __future__ import annotations

import pytest

from codebase.functions import leap_api, leap_api_guard


def test_leap_api_is_blocked():
    assert leap_api_guard.LEAP_API_BLOCKED is True
    assert leap_api_guard.is_leap_api_allowed() is False


def test_ensure_leap_api_allowed_raises():
    with pytest.raises(RuntimeError, match="LEAP API usage is disabled"):
        leap_api_guard.ensure_leap_api_allowed("test")


def test_leap_api_reports_unavailable():
    """is_available() must be False while blocked, regardless of win32com."""
    assert leap_api.is_available() is False


def test_connect_to_leap_raises_rather_than_touching_com():
    from codebase.functions.leap_core import connect_to_leap

    with pytest.raises(RuntimeError, match="LEAP API usage is disabled"):
        connect_to_leap()


@pytest.mark.parametrize(
    "flag",
    [
        "LEAP_IMPORT_SUPPLY_TO_LEAP",
        "LEAP_IMPORT_TRANSFORMATION_TO_LEAP",
        "LEAP_IMPORT_TRANSFERS_TO_LEAP",
    ],
)
def test_leap_import_toggles_default_off(flag):
    """These defaulted True, so every run attempted an API import and warned."""
    from codebase import supply_reconciliation_config

    assert getattr(supply_reconciliation_config, flag) is False, (
        f"{flag} must stay False while the LEAP API is decommissioned; "
        "see supply_reconciliation_config LEAP import controls."
    )


def test_api_import_guards_are_not_coupled_to_write_mode():
    """The skip must depend on API availability, not ANALYSIS_INPUT_WRITE_MODE.

    Regression guard: these guards used to read
    `get_analysis_input_write_mode() == "api" and not leap_api.is_available()`,
    which is False in workbook mode -- so workbook-mode runs fell through and
    attempted every API import anyway.
    """
    import inspect

    from codebase.functions import supply_leap_io

    source = inspect.getsource(supply_leap_io)
    assert 'get_analysis_input_write_mode() == "api" and not leap_api.is_available()' not in source
    assert "if not leap_api.is_available():" in source


def test_api_import_entry_points_short_circuit():
    """Every API import entry point returns empty without touching the API."""
    from codebase.functions import supply_leap_io

    result = supply_leap_io.run_results_linked_leap_import(
        supply_export_paths=[],
        transformation_export_paths=[],
        scenarios=["Reference"],
    )
    assert result == {
        "supply_imported": [],
        "transformation_imported": [],
        "transfer_imported": [],
    }
