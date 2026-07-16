"""Repo-wide severity policy for the 9th->ESTO projection conservation check.

The check lives in `ninth_projection_mapping` (`build_esto_projection_table` /
`allocate_ninth_projection_to_esto`, via `strict_conservation=True`) and raises
`ValueError` when an allocation no longer conserves the 9th source totals.

Producers used to disagree about what a failure *meant*:

- supply (`supply_assets`), aggregated demand, and transformation asset-prep
  passed `strict_conservation=True` and let the error propagate -> blocked.
- transformation's scenario projection (`transformation_workflow`) caught the
  error, warned, and silently re-ran non-strict -> warned.
- transfers passed `strict_conservation=False` -> never checked at all.

`PROJECTION_STRICT_CONSERVATION = True` was also defined twice (in
`transformation_analysis_utils` and `supply_assets`) and kept in manual sync by a
comment. That asymmetry was drift, not design.

Policy (decided 2026-07-16): **a conservation failure is a WARNING by default**
-- long runs must not halt on it -- and every producer behaves identically. Set
`CONSERVATION_FAILURES_ARE_ERRORS = True` to make them raise instead.

This module deliberately imports nothing beyond stdlib so any producer can use it
without risking an import cycle.
"""
from __future__ import annotations

from typing import Callable, TypeVar

# PRESET-CONTROLLED DEFAULT. Override per run from the presets in
# supply_reconciliation_workflow.py, e.g.:
#     conservation_policy.CONSERVATION_FAILURES_ARE_ERRORS = True
#
# False -> log "[WARN] <producer>: strict conservation check failed ..." and
#          proceed with the non-strict allocation.
# True  -> let the ValueError propagate and stop the run.
CONSERVATION_FAILURES_ARE_ERRORS = False

T = TypeVar("T")


def conservation_failures_are_errors() -> bool:
    """Return the active policy, read at call time so presets can override it."""
    return bool(CONSERVATION_FAILURES_ARE_ERRORS)


def build_with_conservation_policy(producer: str, build: Callable[..., T]) -> T:
    """Run ``build(strict_conservation=...)`` under the repo-wide severity policy.

    ``build`` must accept a ``strict_conservation`` keyword. The check is always
    attempted with conservation on; only the handling of a failure differs, so
    callers never choose the severity themselves.

    Parameters
    ----------
    producer:
        Short label used in the warning, e.g. "supply projection".
    build:
        Callable taking ``strict_conservation`` and returning the built result.
    """
    if conservation_failures_are_errors():
        return build(strict_conservation=True)
    try:
        return build(strict_conservation=True)
    except ValueError as exc:
        print(
            f"[WARN] {producer}: strict conservation check failed; proceeding "
            f"with the non-strict allocation: {exc}"
        )
        return build(strict_conservation=False)
