"""Guard tests for ``PARALLEL_ECONOMY_WORKERS``.

``supply_results_saver`` drives a ``ThreadPoolExecutor`` over economies, and
every worker shares the module's star-imported config globals (the mirrored
state that Phase 4 B2/B3 is meant to replace with explicit injection).  Two
economies in flight therefore read each other's settings and produce wrong
seeds with no error - the dial is safe today only because it defaults to 0.

These tests pin the refusal so the foot-gun cannot be armed by editing a
config line, and so that whoever removes the guard has to remove a test that
says why it was there.  See ``docs/work_queue.md`` [17], thread T7 in
``docs/prompts/initialisation_refactor_continuation.md``.
"""

import pytest

from codebase.functions.supply_results_saver import _resolve_parallel_economy_workers
from codebase import supply_reconciliation_config


@pytest.mark.parametrize("value", [0, 1])
def test_sequential_values_are_accepted(value):
    assert _resolve_parallel_economy_workers(value) == value


@pytest.mark.parametrize("value", [2, 5, 64])
def test_values_above_one_are_refused(value):
    with pytest.raises(RuntimeError) as excinfo:
        _resolve_parallel_economy_workers(value)
    message = str(excinfo.value)
    assert "PARALLEL_ECONOMY_WORKERS" in message
    # The message must point at the reason and the unblocking work, not just fail.
    assert "[17]" in message
    assert "phase_5_feature_improvements_execution" in message


@pytest.mark.parametrize("value", [None, "4", 2.0, [], object()])
def test_non_int_values_fall_back_to_sequential(value):
    """A malformed dial must degrade to serial, never to unguarded parallelism."""
    assert _resolve_parallel_economy_workers(value) == 0


def test_bool_is_not_treated_as_a_worker_count():
    """``True`` is an ``int`` in Python; it must not read as one worker by accident."""
    assert _resolve_parallel_economy_workers(True) == 0
    assert _resolve_parallel_economy_workers(False) == 0


def test_config_default_is_sequential():
    """The shipped default must stay inside the accepted range."""
    default = supply_reconciliation_config.PARALLEL_ECONOMY_WORKERS
    assert _resolve_parallel_economy_workers(default) in (0, 1)
