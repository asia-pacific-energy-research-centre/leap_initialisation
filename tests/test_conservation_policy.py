"""Contract tests for the unified projection conservation severity policy.

Policy: a conservation failure is a WARNING by default and every producer
behaves identically; CONSERVATION_FAILURES_ARE_ERRORS=True makes them raise.
"""
from __future__ import annotations

import pytest

from codebase.functions import conservation_policy
from codebase.functions.conservation_policy import build_with_conservation_policy


@pytest.fixture(autouse=True)
def _reset_policy(monkeypatch):
    monkeypatch.setattr(conservation_policy, "CONSERVATION_FAILURES_ARE_ERRORS", False)


def test_default_is_warn_not_error():
    assert conservation_policy.CONSERVATION_FAILURES_ARE_ERRORS is False


def test_check_is_attempted_strict_first():
    seen = []

    def build(*, strict_conservation):
        seen.append(strict_conservation)
        return "ok"

    assert build_with_conservation_policy("p", build) == "ok"
    assert seen == [True], "the check must always be attempted with conservation on"


def test_failure_warns_and_retries_non_strict(capsys):
    seen = []

    def build(*, strict_conservation):
        seen.append(strict_conservation)
        if strict_conservation:
            raise ValueError("totals drifted")
        return "non-strict result"

    result = build_with_conservation_policy("supply projection", build)

    assert result == "non-strict result"
    assert seen == [True, False], "must retry non-strict after a strict failure"
    out = capsys.readouterr().out
    assert "[WARN]" in out
    assert "supply projection" in out
    assert "totals drifted" in out


def test_errors_mode_raises_and_does_not_retry(monkeypatch):
    monkeypatch.setattr(conservation_policy, "CONSERVATION_FAILURES_ARE_ERRORS", True)
    seen = []

    def build(*, strict_conservation):
        seen.append(strict_conservation)
        raise ValueError("totals drifted")

    with pytest.raises(ValueError, match="totals drifted"):
        build_with_conservation_policy("p", build)
    assert seen == [True], "errors mode must not silently retry non-strict"


def test_policy_is_read_at_call_time(monkeypatch):
    """Presets flip the module global at run time, so it must not be captured."""
    monkeypatch.setattr(conservation_policy, "CONSERVATION_FAILURES_ARE_ERRORS", True)
    assert conservation_policy.conservation_failures_are_errors() is True
    monkeypatch.setattr(conservation_policy, "CONSERVATION_FAILURES_ARE_ERRORS", False)
    assert conservation_policy.conservation_failures_are_errors() is False


def test_non_valueerror_is_never_swallowed():
    def build(*, strict_conservation):
        raise RuntimeError("something else broke")

    with pytest.raises(RuntimeError, match="something else broke"):
        build_with_conservation_policy("p", build)


def test_supply_no_longer_defines_a_duplicate_strictness_flag():
    """PROJECTION_STRICT_CONSERVATION was defined twice and manually kept in sync."""
    from codebase.functions import supply_assets

    assert not hasattr(supply_assets, "PROJECTION_STRICT_CONSERVATION")


@pytest.mark.parametrize(
    "module_name",
    [
        "codebase.aggregated_demand_workflow",
        "codebase.transfers_workflow",
        "codebase.transformation_workflow",
        "codebase.functions.supply_assets",
    ],
)
def test_producers_route_through_the_shared_policy(module_name):
    """Every migrated producer defers severity to the shared helper."""
    import importlib

    module = importlib.import_module(module_name)
    assert hasattr(module, "build_with_conservation_policy"), (
        f"{module_name} must import build_with_conservation_policy rather than "
        "choosing strict_conservation itself"
    )
