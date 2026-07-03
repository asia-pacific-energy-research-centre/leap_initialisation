# Balance-demand conservation check

## Decision

The check is independently useful. Its reference side is produced by
`aggregated_demand_workflow.py`, which filters raw ESTO and 9th Outlook demand
and conserves each 9th source-pair total while allocating aggregate fuels. Its
resolved side is produced separately from balance `comparison_long` rows and
`mapping_status`, including mapping, rollup/augmentation, and source selection.

The comparison unit is:

`economy + scenario + sector_context + esto_product + year`

`reference_total` is the sum of aggregated-demand rows in that unit.
`resolved_total` is the sum of the rows actually selected by the reconciliation
demand path in the same unit. The diagnostic reports resolved minus reference.

## Comparison surface

- Include actionable demand rows for the configured scenarios and years.
- Compare after both paths have applied the same deliberate sector exclusions.
- Do not pass subtotal rows. The aggregated projection path already removes
  `subtotal_results` rows; the resolved input must use its leaf/actionable rows.
- Do not pass aggregate fuel labels such as `Total`, which are sector rollups
  rather than actionable fuels.
- A missing row, an unexpected resolved row, or an absolute difference above
  the configured tolerance is a mismatch. Reviewed exclusions are absent from
  both inputs and are not mismatches.

The check is diagnostic-only. It should not block a run until real `20_USA`
baseline-seed and results-update outputs establish an appropriate tolerance and
confirm that the two paths use identical sector-exclusion settings.

## Pass-specific interpretation

- `baseline_seed`: compare aggregated-demand reference totals with the
  projection-only mapping result. This is independent because the two paths
  perform separate filtering, mapping, and aggregation even though both start
  from 9th Outlook data.
- `results_update`: compare the same reference totals with demand selected from
  the real LEAP balance export path. Differences can represent model results as
  well as mapping loss, so the diagnostic must retain sector and product context.

The implementation is in
`codebase/functions/balance_demand_conservation.py`. It accepts prepared tables
rather than re-reading mapping inputs, which avoids making the diagnostic depend
on the rules it is checking. The current mapping-fix worktree also modifies the
shared producer/consumer files, so automatic workflow wiring is intentionally
deferred until those changes are committed or otherwise stabilized.

## Remaining ambiguity

`results_update` may legitimately diverge from the ESTO/9th reference if LEAP
demand has been changed by the modeller. Before making the check blocking, the
workflow needs an explicit decision on whether such divergence is expected and,
if so, whether the conservation reference should instead be the pre-mapping LEAP
sector/fuel total from the same export.
