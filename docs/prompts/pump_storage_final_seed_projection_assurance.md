# Pump-storage own-use projections: final baseline-seed assurance

## Objective

Make the pump-storage own-use projection method demonstrably reliable in the
**final baseline-seed workbook**, not merely in an intermediate proxy workbook.
Implement a narrowly scoped fix only if the investigation shows that the
final-seed boundary is dropping or changing the intended rows.

The intended method is already documented in
`docs/initialisation_flow_estimation_methods.md`: when every supplied 9th
projection value for `10.01.13 Pump storage plants` is structurally zero, carry
the ESTO base-year own-use energy forward at a constant rate.

## Important evidence from the latest USA run

Inspect this exact output before changing code:

```text
outputs/leap_exports/supply_reconciliation/baseline_seed/runs/run_b9bffd/
leap_import_baseline_seed_20_USA_20260825.xlsx
```

The workbook's `LEAP` sheet has the usual three-row preamble; row 3 is the
header.  It contains these two different kinds of records:

1. The **parent** branch
   `Demand\Other loss and own use\Pump storage plants`, Activity Level, is zero
   for Reference and Target.  This is intentional.  It prevents the parent
   branch from producing energy in addition to the Electricity child branch.
   Do **not** make this parent non-zero.
2. The **energy-bearing child** branch
   `Demand\Other loss and own use\Pump storage plants\Electricity` has both
   Activity Level and Final Energy Intensity rows for Reference and Target.
   In the saved final seed, their product is 21.700289 PJ in each of 2023,
   2030, 2042, 2043, 2050, and 2060 (and should be so throughout 2023--2060).
   Its 2022 Reference/Target entries are zero; Current Accounts retains the
   2022 base value.

Therefore, the original observation that the run "only created Current
Accounts" is likely caused by looking at the parent row rather than the
Electricity child row.  Do not assume a defect without reproducing this
comparison.  If a downstream LEAP result nevertheless has zero projected
pump-storage own use, identify the downstream boundary and demonstrate it.

The run's intermediate evidence is under:

```text
outputs/leap_exports/supply_reconciliation/baseline_seed/runs/run_b9bffd/
supporting_files/other_loss_own_use_proxy/20_USA/
```

`proxy_activity_intensity_detail.csv` records
`target_fallback_reason = esto_base_year_carried_forward_ninth_projection_all_zero`
for the USA pump-storage Electricity row.  The workflow log also reports the
base-year activity backfill from 2023 for `pump_storage_plants`.

## Code routes to audit

- `codebase/other_loss_own_use_proxy_workflow.py` — pump-storage proxy config.
- `codebase/functions/other_loss_own_use_proxy_utils.py` — structural-zero
  carry-forward and LEAP export-row construction.
- `codebase/functions/patch_baseline_seeds.py` — how the losses/own-use
  workbook replaces the `Demand\Other loss and own use\` rows in a seed.
- `codebase/supply_reconciliation_workflow.py` and the relevant seed-combining
  helpers — how the full run writes its final per-economy seed.

## Work required

1. Trace a USA pump-storage record from ESTO base data through the proxy detail
   table, the generated proxy LEAP-import workbook, and the final per-economy
   baseline seed.  At every boundary, compare branch path, variable, scenario,
   years, and expression values.
2. Determine whether there is an actual loss/change at the final-seed boundary.
   If there is none, add an integration-level regression test or focused
   validator that proves the final seed contains the intended child rows.  This
   must test the saved final workbook, not just an in-memory proxy dataframe.
3. If there is a real defect, fix the smallest responsible boundary and add the
   same end-to-end regression.  Do not use a manual workbook patch as the
   production solution.
4. Ensure the structural-zero carry-forward is applied only for configured
   pump-storage own-use rows, and that a non-zero 9th projection continues to
   use the 9th-driven method.
5. Verify the economies with ESTO 2022 pump-storage own-use data: `01_AUS`,
   `03_CDA`, `08_JPN`, `10_ROK`, `16_RUS`, `18_CT`, and `20_USA`.  Treat
   `02_BD` as Brunei Darussalam, not Bangladesh, if it appears in any economy
   lookup.

## Acceptance criteria

- In the final USA baseline seed, Reference and Target each have exactly one
  Activity Level row and one Final Energy Intensity row for
  `Demand\Other loss and own use\Pump storage plants\Electricity`.
- For each projected year 2023--2060, the product of those two expressions is
  21.700289 PJ within a small floating-point tolerance.  The final expressions
  may vary individually because the workflow uses a changing activity proxy;
  their product is the invariant.
- Current Accounts preserves the 2022 observed value, while Reference/Target
  have zero in 2022 under the current export convention.
- The parent `Pump storage plants` Activity Level remains zero for
  Reference/Target and is explicitly asserted as such; it is not a substitute
  for the Electricity child row.
- No unrelated `Demand\Other loss and own use\` rows are changed.
- A test demonstrates both paths: all-zero 9th projections use the ESTO
  carry-forward, while a non-zero 9th projection does not.
- Update `docs/initialisation_flow_estimation_methods.md` only if the
  implementation method or its final-seed behavior changes.  Otherwise add a
  concise note only where it genuinely improves the documentation.

## Verification and handoff

Run the focused tests you add plus the existing other-loss/own-use test module.
Report a compact before/after table for the final USA seed showing the parent
row and child-row effective energy at 2022, 2023, 2030, and 2060.  Preserve
unrelated worktree changes and commit only the implementation, tests, and
documentation you authored.
