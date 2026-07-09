# Balance-demand conservation check prompt

Work in `C:\Users\Work\github\leap_initialisation`.

This is a separate follow-on task from
`docs/balance_demand_mapping_fixes_prompt.md`. Do not treat it as part of the
mapping-fix prompt. Use it only when the mapping fixes are already underway or
complete and you want a dedicated agent to investigate conservation behavior.

## Objective

Design, implement, and verify a focused total-conservation check for the
balance-demand path.

The goal is to confirm that the demand rows used by the reconciliation workflow
still conserve the expected sector-branch totals after mapping, rollup, and
augmentation logic are applied.

This is not a mapping-gap repair task. It is a correctness check around whether
the resolved demand totals still match the reference totals that the workflow is
expected to preserve.

If the mapping-fix agent is still actively editing shared files, avoid touching
those same files unless the conservation check genuinely requires a small,
shared helper change. In that case, stop and flag the overlap before editing.

## Scope

Investigate the conservation question separately for:

1. `baseline_seed`, which uses the projection-only demand path.
2. `results_update`, which compares against the real LEAP export path.

The check should compare the demand reference totals produced by
`codebase/aggregated_demand_workflow.py` against the totals actually resolved by
the supply-reconciliation mapping path.

## Key questions to answer first

Before coding, answer these concretely:

1. Is there a separate reference path, or a separately computed conservation
   total, that the reconciliation path could violate?
2. What is the exact reference total for a sector-branch demand row?
3. Which rows are included in the conservation comparison?
4. How are subtotal rows handled?
5. What should count as a mismatch versus an expected exclusion?
6. Should the check be diagnostic-only, or should it block the run?

If the answer to question 1 is effectively "no", stop and report that the
check is not independently useful before coding further. Do not build a
self-comparison that only re-verifies the same values produced by the same
path.

Do not guess silently. If the answer is unclear from the code, inspect the
relevant workflow functions and document the decision.

## Expected work

1. First, identify and document the independent reference path or conservation
   total, if one exists.
2. Locate the path that builds the sector-branch demand totals in
   `codebase/aggregated_demand_workflow.py`.
3. Locate the path that consumes the mapped demand rows in the reconciliation
   workflow.
4. Define a narrow comparison surface that can be computed deterministically
   for at least one economy, ideally `20_USA`.
5. Add a focused diagnostic output that shows:
   - the reference total,
   - the resolved total,
   - the difference,
   - and the row or sector context.
6. Add tests that prove the check catches a real mismatch and passes on the
   intended good case.

## Boundary

Keep this work narrowly about conservation behavior.

Do not edit `docs/balance_demand_mapping_fixes_prompt.md` or expand this task
into the mapping-fix work. That prompt is for the separate mapping agent.

Do not:

1. Change mapping rules.
2. Add new rollup logic.
3. Rework subtotal semantics unless absolutely required to define the check.
4. Expand the scope into a general reconciliation refactor.

If the check turns out to require a larger design decision, stop and report the
decision point instead of quietly broadening the implementation.

## Useful references

1. `docs/balance_demand_mapping_fixes_prompt.md`
2. `docs/special_rules_and_design_decisions.md`
3. `codebase/aggregated_demand_workflow.py`
4. `codebase/functions/supply_demand_mapping.py`
5. `codebase/functions/supply_results_saver.py`

## Deliverable

By the end, the agent should leave behind:

1. A clear explanation of the conservation rule being checked.
2. The implemented check or diagnostic hook.
3. Focused tests.
4. A short summary of any remaining ambiguities.
