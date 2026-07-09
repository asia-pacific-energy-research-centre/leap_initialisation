# Prompt: update the 20_USA resume companion after balance-demand fixes land

Paste this into a fresh chat once `docs/balance_demand_mapping_fixes_prompt.md`
has been implemented (or to check whether it has).

---

Work in `C:\Users\Work\github\leap_initialisation`.

## Objective

Determine whether the work described in
`docs/balance_demand_mapping_fixes_prompt.md` is complete, and if so, produce
an updated resume-launch companion prompt for the 20_USA managed run. Do not
implement any of the fixes yourself in this task, and do not launch the
managed workflow. This task is preparation only.

## Step 1 — check completion status

Read `docs/balance_demand_mapping_fixes_prompt.md` in full, then verify
against the actual repository state:

1. `git status --short` — confirm the expected source files from that prompt
   show as modified: at minimum `codebase/functions/supply_demand_mapping.py`,
   `codebase/functions/baseline_seed_validation.py`, a new module under
   `codebase/configuration/` holding `KNOWN_LEAP_LABEL_EXCEPTIONS`, and
   `docs/special_rules_and_design_decisions.md`.
2. Confirm `KNOWN_LEAP_LABEL_EXCEPTIONS` exists and is wired into both the
   demand-mapping join and the `-1` branch/variable ID rescue pass in
   `baseline_seed_validation.py`, per that prompt's Fix 1.
3. Confirm the general rollup-fallback resolver exists in
   `codebase/functions/supply_demand_mapping.py`, is implemented at the
   `_build_augmented_balance_demand_mapping_workbook` layer (not only inside
   the real-LEAP-export path), and consumes all three rollup sheets
   (`leap_rollup_rules`, `esto_rollup_rules`, `ninth_rollup_rules`) rather
   than only `leap_rollup_rules`, per that prompt's Fix 2.
4. Confirm focused tests exist and pass for both fixes, including the
   specific test required by Fix 2 that calls
   `_build_projection_only_mapping_status` (or
   `load_balance_demand_inputs` with
   `allow_projection_only_without_balance_exports=True`) directly and
   asserts the previously-missing Freight road/Passenger road rows are now
   present — this is the path `baseline_seed` actually uses, and is distinct
   from the real-LEAP-export path.
5. Confirm `docs/special_rules_and_design_decisions.md` has a new entry (or
   entries) documenting all four fixes (the two made earlier in the
   originating conversation — baseline_seed always uses projection-only
   demand, and `Total` fuel rows excluded from demand-mapping checks — plus
   the two from that prompt), per that prompt's documentation requirement.

If any of this is incomplete or ambiguous, stop here and report exactly
what's missing. Do not proceed to Step 2, and do not attempt to finish the
implementation yourself unless explicitly asked in a follow-up.

## Step 2 — run a fresh regression gate

If Step 1 confirms the work is complete:

1. Run the complete suite fresh:
   `& 'C:\Users\Work\miniconda3\python.exe' -m pytest -q --ignore=tmp`
2. Record the exact passed/failed/skipped counts and duration. Do not reuse
   any previously-cached gate number from an earlier session — this is a
   new gate specific to this new source state.
3. If anything fails, stop and report; do not proceed to Step 3.

## Step 3 — write the updated resume companion

Read the existing companion at
`docs/managed_leap_initialisation_resume_20_usa_prompt.md` in full — it is
the template for structure and tone (it in turn is a companion to
`docs/managed_leap_initialisation_run_prompt.md`, which should also be read).
Both were written before the balance-demand mapping fixes existed, so its
"Current source decisions and fixes" and "Working-tree state expected at
handoff" sections are stale and must be replaced, not merely appended to.

Produce a new version (either overwrite the existing file or write a new
dated companion file — match whatever naming convention seems least
confusing given the existing `..._resume_20_usa_prompt.md` name; use
judgement) that:

1. Keeps the same overall structure: immediate objective, current verified
   regression gate, launch instructions, current source decisions and
   fixes, working-tree state expected at handoff, failure boundary, and the
   `Dear Finn,` context-continuity sentinel requirement — all copied from
   the existing companion's conventions.
2. Replaces the regression-gate section with the fresh gate from Step 2
   (exact command, counts, duration, log path if one was produced).
3. Replaces the "Current source decisions and fixes" list to include, in
   addition to whatever was already there, four new bullets covering:
   - `baseline_seed` always uses projection-only demand regardless of
     whether a real LEAP balance export exists for the economy
     (`load_balance_demand_inputs` in `supply_demand_mapping.py`).
   - `Total` fuel-label rows are excluded from demand-mapping relevance
     checks (`DEMAND_NON_ACTIONABLE_FUEL_EXACT_MATCHES` in
     `supply_reconciliation_config.py`).
   - The `KNOWN_LEAP_LABEL_EXCEPTIONS` mechanism (temporary LEAP-model
     spelling bridge, currently one entry for Black liqour/Black liquor,
     with the `-1` branch/variable ID rescue pass in
     `baseline_seed_validation.py`) — note explicitly that this is temporary
     and should be revisited once the LEAP model itself is corrected.
   - The general rollup-fallback resolver in `supply_demand_mapping.py`,
     consuming all three rollup sheets, implemented at the augmentation
     layer so both `baseline_seed` (projection-only) and `results_update`
     (real export) benefit — proven via the Freight road/Passenger road
     "Road" rollup case but not scoped to it.
4. Replaces the "Working-tree state expected at handoff" file list with the
   actual current `git status --short` output from this session (do not
   copy the old list forward).
5. Does not change the launch-instruction mechanics, polling rules, or
   failure-boundary language from the base prompt unless something in this
   task specifically requires it — this task only refreshes the
   state-specific sections.

## Do not

- Do not launch the managed workflow.
- Do not implement any remaining part of `balance_demand_mapping_fixes_prompt.md`.
- Do not commit, stage, reset, or discard anything.
- Do not delete the old companion file without checking — prefer to confirm
  with the user whether to overwrite in place or version it, if that isn't
  already obvious from repository convention.
