# Baseline-seed transfer projections — decision review for queue item [50]

## Objective

Turn the scenario-aware transfer fallback question into an explicit, testable
policy. Do not change production fallback behavior today without confirming
whether all-zero post-base-year data means “no projection supplied” or an
intentional forecast of zero.

## Existing evidence to validate

The queue records that transfer rows are currently built through
`_collect_transformation_and_transfer_rows` → `build_transfer_process_records`
without the 9th scenario, so absent future values become zero through the
horizon. In `data/merged_file_energy_ALL_20251106.csv`, non-zero post-2022
transfer values appeared only for four active economies (including `01_AUS`
and `20_USA`) under both scenarios. `02_BD`, `05_PRC`, `11_MEX`, `12_NZ`, and
`13_PNG` had non-zero 2022 values but no non-zero future transfer values; the
last two may be outside the current seed scope. Re-measure rather than treating
these notes as final data.

## Procedure

1. Trace the current call chain and identify exactly where scenario is lost,
   zero-fill is applied, and Current Accounts is formed. Confirm whether a
   matching `Reference`/`Target` value is available at the point the seed
   expression is assembled.
2. Produce a compact economy × scenario table for every active seed economy:
   2022 ESTO value, first/last post-2022 non-zero 9th value, count of post-base
   years, whether the projection is explicitly zero versus absent, and current
   output expression/fallback. Keep `02_BD` as Brunei Darussalam and do not
   confuse it with Bangladesh.
3. Check whether a transfer’s zero projection is ever intentional in a
   maintained source. Use source completeness/metadata where possible; lack of
   a non-zero value alone is not sufficient proof of missing data.
4. Compare three policies with at least one projected and one zero/absent case:
   - current zero-fill;
   - always carry forward 2022 where post-base values are all zero;
   - scenario-aware projection when supplied, then a clearly identified
     missing-projection carry-forward only when evidence says the projection is
     unavailable.
   Report future-year continuity and semantic risks rather than only row counts.

## Recommended decision shape

The likely safe direction is to pass the run scenario unconditionally, keep
explicit 9th values (including intentional zeros), and use a documented
ESTO-base-year carry-forward only for a separately detected
`projection_unavailable` state. The agent must either prove that availability
state can be detected reliably or recommend a human decision instead of
encoding “all zero” as missing.

Current Accounts remains historical/base-year only unless a separately
approved policy changes it.

## Deliverable

Write a one-page decision record with the scenario coverage table, policy
recommendation, affected economies, proposed availability criterion, and three
focused regression cases. End with exactly one of:

- `READY_FOR_NARROW_IMPLEMENTATION` — names the function signature, expected
  expression behavior, and test locations; or
- `HUMAN_SEMANTIC_DECISION_REQUIRED` — names the unresolved source meaning and
  the smallest evidence needed to decide it.

Do not edit mappings or dashboard code, and do not run a full baseline-seed
batch for this design review.
