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

`sector_context` is labelled `Demand rows included in conservation scope (see
lineage scope audit)`. The lineage output contains `source_scope` and
`actual_resolved_branch` rows showing what was included or excluded, why, and
the value contributed by each source flow or LEAP branch. Configured detailed-
sector exclusions are applied to both sides before comparison.

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

## Human-readable prototype outputs

The workflow now leaves the existing total comparison unchanged and writes two
additional CSV files beside it:

- `supply_reconciliation_balance_demand_conservation_breakdown.csv` explains
  each total difference in two steps. `source_to_expected_mapping` shows energy
  lost or gained while mapping raw demand. `expected_mapping_to_actual_resolved`
  then compares each mapped ESTO product with the value reconciliation consumed.
  Adding the `difference` column for one economy, scenario, and year reproduces
  the difference in the existing total CSV.
- `supply_reconciliation_balance_demand_conservation_lineage.csv` shows the
  underlying rows in three clearly labelled groups: `original_source`,
  `expected_mapped`, and `actual_resolved`. It also includes `source_scope`
  records for included/excluded ESTO or Ninth rows and
  `actual_resolved_branch` records for each LEAP branch contribution.

The breakdown exposes `expected_source_flows`, `excluded_source_flows`,
`included_leap_branches`, `excluded_leap_branches`, and compact branch/value
contribution strings. Subtotal exclusions remain in the detailed lineage but
are not presented as wholly excluded flows, because the same flow can have an
excluded subtotal row and included component rows.

The current workflow does not retain the link from every raw source row through
every allocation to its final resolved row. The lineage output says
`mapped_but_source_link_not_retained` instead of inventing that link. Product
rows identify their source system (`ESTO` in the base year and `NINTH` after
it), source fuel codes, allocation method, minimum/maximum applied share, and
value quality. `exact_direct` means no split was needed, `allocated` means an
explicit proportional share was used, and `estimated` means an equal-split
fallback was required. The resolved LEAP side carries the same fields from its
balance-mapping diagnostics. This prototype is intended to make the gaps
inspectable before deeper row-to-row linking is added.

## Pass-specific interpretation

- `baseline_seed`: compare raw pre-mapping ESTO/9th demand totals with the
  `demand_table` actually passed to `build_reconciliation_table`. The primary
  invariant is total energy by economy, scenario, sector context, and year.
  Product-level diagnostics are secondary because contextual allocation may
  legitimately redistribute aggregate source fuels across ESTO products.
- `results_update`: compare only the residual aggregated-demand placeholder.
  First infer the detailed sector branches present in the LEAP balance export,
  convert those branches to the established ESTO/9th exclusion list, and apply
  that same list to the reference and resolved surfaces. Detailed LEAP sector
  demand is deliberately absent from both sides; it is not expected to equal the
  ESTO/9th reference after modelling changes.

The implementation is in
`codebase/functions/balance_demand_conservation.py`. It accepts prepared tables
rather than re-reading mapping inputs, which avoids making the diagnostic depend
on the rules it is checking. Pass-specific adapters support a total-energy
surface and make the results-update exclusion of detailed LEAP rows explicit.

## Remaining ambiguity

The check remains diagnostic-only until it is exercised against a real
`20_USA` results-update pass. The active-sector inference and road-exclusion
deduplication are already tested in `tests/test_aggregated_demand_workflow.py`;
workflow wiring must reuse that exact effective exclusion list rather than
reconstructing it independently.

Separate checks have different scopes:

- Baseline supply source preservation will compare ESTO/9th production,
  imports, and exports before mapping with the final mapped baseline rows.
- Results update will not compare supply with ESTO/9th. Its supply-side check is
  reconciliation closure after adjustments: resolved supply must satisfy demand,
  transformation requirements, losses, and the other explicitly included balance
  terms within tolerance.

## Initial 20_USA baseline result

The first diagnostic run produced 79 economy/scenario/year rows and three
mismatches, all in base year 2022. Resolved demand is 58.097029 PJ below the raw
ESTO reference in Current Accounts, Reference, and Target. The aggregated-demand
workflow reports the corresponding dropped source products as `02 Coal products`,
`15 Solid biomass`, and `16 Others`; the latter two contribute the full observed
difference in the current 20_USA base-year demand rows. These remain visible as
diagnostic mismatches rather than being silently classified as expected exclusions.
