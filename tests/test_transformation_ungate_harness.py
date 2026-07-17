"""Tests for the [1] ungate harness's difference classifier.

The classifier is the load-bearing part: if it labels a real value change
"benign", the harness greenlights removing the transformation patch gate on top
of an actual defect. These tests exist mainly to pin the cases where "benign" is
tempting and wrong.
"""

from __future__ import annotations

import pytest

from pathlib import Path

from codebase.scrapbook.transformation_ungate_equivalence_harness import (
    TRANSFORMATION_RULES_CHANGED,
    _classify,
    _parse_expression,
    seed_is_too_old_to_compare,
)


def test_refuses_a_seed_older_than_the_current_transformation_rules():
    """A 20260715 seed predates 8c32504's multi_output default, so it disagrees
    with current code BY DESIGN. Diffing it would report that intended
    correction as a patcher defect -- the same class of error as the gate's
    original evidence. Refuse instead."""
    reason = seed_is_too_old_to_compare(Path("leap_import_baseline_seed_20_USA_20260715.xlsx"))
    assert reason is not None
    assert "20260715" in reason
    assert TRANSFORMATION_RULES_CHANGED in reason


def test_accepts_a_seed_built_with_current_rules():
    assert seed_is_too_old_to_compare(
        Path("leap_import_baseline_seed_20_USA_20260717.xlsx")
    ) is None


def test_accepts_a_seed_stamped_exactly_on_the_rules_change():
    assert seed_is_too_old_to_compare(
        Path(f"leap_import_baseline_seed_20_USA_{TRANSFORMATION_RULES_CHANGED}.xlsx")
    ) is None


def test_refuses_rather_than_assumes_when_the_date_is_unreadable():
    """An undated seed must not be assumed current -- that assumption is exactly
    how a stale comparison would slip through."""
    reason = seed_is_too_old_to_compare(Path("leap_import_baseline_seed_20_USA.xlsx"))
    assert reason is not None
    assert "cannot read a date" in reason


def test_parses_series_numerically_not_textually():
    """1 vs 1.0 vs 1.000000 is the same number; the recipe requires numeric
    comparison so float formatting is not reported as a difference."""
    assert _parse_expression("Data(2023,1)") == {2023: 1.0}
    assert _parse_expression("Data(2023, 1.000000)") == {2023: 1.0}
    assert _classify("Data(2023,1)", "Data(2023, 1.000000)")[0] == "same"


def test_scalar_and_interp_forms_are_handled():
    assert _parse_expression("0") == {0: 0.0}
    assert _parse_expression("Interp(2023, 5)") == {2023: 5.0}
    assert _parse_expression("Unlimited") == "unlimited"
    assert _classify("Unlimited", "Unlimited")[0] == "same"
    assert _classify("Unlimited", "0")[0] == "DEFECT"


def test_real_value_change_is_a_defect():
    verdict, detail = _classify("Data(2023,10)", "Data(2023,11)")
    assert verdict == "DEFECT"
    assert "2023" in detail


def test_float_noise_below_tolerance_is_not_a_defect():
    assert _classify("Data(2023,1.0)", "Data(2023,1.0000000001)")[0] == "same"


def test_dropping_a_zero_year_is_benign():
    """Scenario-year trimming of zero-valued years changes nothing real."""
    verdict, _ = _classify("Data(2023,5, 2024,0)", "Data(2023,5)")
    assert verdict == "benign"


def test_dropping_a_NONZERO_year_is_a_defect_not_trimming():
    """The trap: 'scenario-year trimming' is benign only when the dropped years
    are zero. A dropped nonzero year is silent data loss wearing trimming's
    clothes -- exactly the shape this repo keeps getting bitten by."""
    verdict, detail = _classify("Data(2023,5, 2024,7)", "Data(2023,5)")
    assert verdict == "DEFECT"
    assert "2024" in detail


def test_adding_a_NONZERO_year_is_a_defect():
    verdict, detail = _classify("Data(2023,5)", "Data(2023,5, 2024,7)")
    assert verdict == "DEFECT"
    assert "2024" in detail


def test_adding_a_zero_year_is_benign():
    assert _classify("Data(2023,5)", "Data(2023,5, 2024,0)")[0] == "benign"


def test_unparseable_expression_is_never_silently_equal():
    """An expression the parser cannot read must not be assumed equal."""
    verdict, _ = _classify("Data(2023,abc)", "Data(2023,5)")
    assert verdict == "DEFECT"


@pytest.mark.parametrize("same", ["Data(2023,0)", "0", "Unlimited", "Data(2023,1, 2024,2)"])
def test_identical_expressions_are_same(same):
    assert _classify(same, same)[0] == "same"
