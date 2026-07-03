# Balance-demand mapping fixes — implementation prompt

Work in `C:\Users\Work\github\leap_initialisation`. `leap_mappings` and
`leap_dashboard` are sibling repos at `C:\Users\Work\github\leap_mappings` and
`C:\Users\Work\github\leap_dashboard`.

## Background

During a 20_USA baseline_seed run, `supply_reconciliation_balance_demand_issues.csv`
surfaced 1384 `missing_esto_pair` rows that were also flagged demand-relevant,
hard-stopping the run (`BALANCE_DEMAND_FAIL_ON_MAPPING_ISSUES = True`). These
collapse into a few root causes, discussed and decided with Finn already. Two
fixes are already implemented; two remain. This prompt covers only the
remaining two, plus documentation for all four.

## Already implemented (verify intact, do not redo)

1. **Baseline seed always uses projection-only demand.**
   `codebase/functions/supply_demand_mapping.py::load_balance_demand_inputs`
   (around line 1194): when `allow_projection_only_without_balance_exports`
   is True (set by the caller specifically for the `baseline_seed` pass via
   `_is_capacity_unmet_baseline_seed_pass()` in
   `codebase/functions/supply_results_saver.py` around line 2697), every
   economy now unconditionally uses the 9th projection-only demand table,
   never a real LEAP balance export — even if one exists for that economy.
   Real LEAP exports are only compared during `results_update`.
2. **`Total` fuel rows are not demand-actionable.**
   `codebase/supply_reconciliation_config.py` has
   `DEMAND_NON_ACTIONABLE_FUEL_EXACT_MATCHES = ("total",)`, consumed by
   `_is_non_actionable_demand_fuel` in
   `codebase/functions/supply_demand_mapping.py` (around line 214). Rows
   whose fuel label is exactly `Total` (case-insensitive) are marked
   `demand_relevant = False`, basis `excluded_non_actionable_fuel` (this
   basis string, and the sibling flag `issue_fuel_is_non_actionable`, were
   renamed from `excluded_do_not_use_fuel` / `issue_fuel_is_do_not_use` — no
   external code or test depended on the old names; confirmed by grep).

Run `python -m pytest tests/ -k "demand or balance_demand or supply_reconciliation" -q`
before starting; it should pass (79 passed as of this writing) confirming
these two are intact.

## Fix 1 — known LEAP label exceptions + `-1` ID rescue pass

### Problem

`leap_combined_ninth`/`leap_combined_esto` (in
`leap_mappings/config/outlook_mappings_master.xlsx`) spell the top-level
Industry fuel `"Black liquor"` correctly. Every other canonical spelling in
this codebase — `ESTO_PRODUCT_LIST` in
`codebase/configuration/all_products_and_flows.py` (`'15.04 Black liqour'`),
`codebase/utilities/detailed_balance_from_esto.py`,
`codebase/functions/supply_branch_classification.py`,
`codebase/functions/other_loss_own_use_proxy_utils.py`, and LEAP's own raw
export — uses the typo `"Black liqour"`, matching the actual LEAP branch
name. That one correctly-spelled mapping row is the outlier, and it breaks
the exact-string join in the demand-comparison path.

Finn's explicit decision: **do not edit `outlook_mappings_master.xlsx`.**
This is a LEAP-model-side spelling issue that will eventually be corrected
in the LEAP model itself. Until then, handle it as a temporary, reviewable,
config-driven exception — not a silent workaround.

### Required design

1. **New shared config location**, in `codebase/configuration/` (not
   `supply_reconciliation_config.py`, which `baseline_seed_validation.py`
   does not currently import). Add something like:

   ```python
   # Fuel/sector labels not yet corrected in the live LEAP model. Each entry
   # means: treat `leap_label` as an alias of `mapping_label` when a join
   # against leap_combined_ninth/leap_combined_esto/the full-model-export
   # template would otherwise fail. Remove an entry once the LEAP model is
   # corrected and the alias stops firing (watch the rescue log).
   KNOWN_LEAP_LABEL_EXCEPTIONS: dict[str, str] = {
       "Black liqour": "Black liquor",
   }
   ```

   Confirm the right module: either a new small file (e.g.
   `codebase/configuration/known_leap_label_exceptions.py`) or an addition
   to an existing shared module in that folder — check
   `codebase/configuration/__init__.py` and existing import patterns first
   and follow the established convention rather than inventing a new one.

2. **Demand-mapping join site** (`codebase/functions/supply_demand_mapping.py`):
   apply the alias unconditionally, upfront, to the LEAP fuel-label column
   before it is joined against `leap_combined_ninth`/`leap_combined_esto`
   (i.e. wherever `leap_long`'s fuel label is established, before
   `_build_direct_demand_mapping_status` / `_build_augmented_balance_demand_mapping_workbook`
   consume it — trace the exact join point rather than assuming). This is
   safe to apply eagerly because it is a plain string-key join: the alias
   only affects keys that would not otherwise match anything (if the
   correctly-spelled variant already matched, it is not in the exceptions
   dict).

3. **Branch/Variable ID canonicalization site**
   (`codebase/functions/baseline_seed_validation.py`, the function around
   line 850 that replaces `BranchID`/`VariableID`/`ScenarioID`/`RegionID`
   with canonical values from the full-model-export template and leaves
   `-1` for unmatched keys — confirm its exact name by reading the file).
   Do **not** apply the alias upfront here; rewriting all branch-path text
   before the primary match risks disturbing rows that already resolve
   correctly. Instead, add a second, narrow pass **after** the existing
   lookup:
   - Select only rows where `BranchID` (and separately, `VariableID`) is
     `-1` after the normal lookup.
   - Apply `KNOWN_LEAP_LABEL_EXCEPTIONS` to the relevant key text for just
     those rows and recompute the normalized key.
   - Re-run the *same* `branch_ids`/`variable_ids` dict lookups (already
     built in that function) against the corrected key.
   - Only overwrite `BranchID`/`VariableID`/`Branch Path` for rows that flip
     from `-1` to a real match. Rows still `-1` afterward remain exactly as
     blocking as before.
   - Record which rows were rescued and by which exception entry (a column
     or an `[INFO]` log line is fine) so it is obvious the moment the LEAP
     model gets fixed and the alias stops being needed — that is the signal
     to delete the entry, not something that should silently persist
     forever.

4. Add focused tests: one for the demand-mapping alias substitution (a
   `"Black liqour"` fuel row now resolves to the same ninth/esto pair as
   `"Black liquor"`), and one for the `-1` rescue pass (a row that would be
   `-1` under the literal key resolves correctly via the exception, and a
   genuinely-unmatched row is untouched and stays `-1`). Later we wont have a `"Black liqour"` row in the LEAP export, so the test should shift to using a different alias so it remains valid after the LEAP model is corrected. If no alias is available, whether in the LEAP export or the configuration, the test can be skipped.

### Boundary

Do not expand `KNOWN_LEAP_LABEL_EXCEPTIONS` beyond the one documented entry
without checking with Finn first — this mechanism is for known, reviewed,
temporary LEAP-model spelling gaps, not a general fuzzy-matching layer.

## Fix 2 — general demand-rollup fallback (proven by the Road case)

### Problem

`leap_combined_ninth` has full leaf-level demand mappings for `Freight road`
and `Passenger road` (parent and every child branch, e.g.
`Freight road/Trucks/BEV heavy`), but `leap_combined_esto` has **zero rows**
at any level for either sector — this alone accounts for 1270 of the 1384
actionable rows.

`leap_rollup_rules` (same workbook) already declares the intended fix:

| input_leap_sector_name_full_path | rolled_raw_leap_fuel_name | parent_flow_label |
|---|---|---|
| Freight road | Road | Transport sector |
| Passenger road | Road | Transport sector |

And both combined sheets already have a **complete, pre-built target**
under a synthetic sector literally named `Road`:

- `leap_combined_esto`: 12 rows, `leap_sector_name_full_path = "Road"`,
  `esto_flow = "15.02 Road"`, one row per fuel (Motor gasoline, Kerosene,
  Gas and diesel oil, Fuel oil, LPG, Natural gas, Biogas, Biogasoline,
  Biodiesel, Hydrogen, Electricity, Efuel).
- `leap_combined_ninth`: the same 12 rows, `leap_sector_name_full_path =
  "Road"`, `ninth_sector = "15_02_road"`, matching fuel codes (e.g.
  `16_x_efuel`, `16_x_hydrogen` — identical to what `Freight road`/
  `Passenger road` already use individually).

Nothing needs to be authored in the mapping workbook. Finn's explicit
decision: **build this as a general rollup-resolution engine, not a
Road-specific special case.** `leap_rollup_rules`/`esto_rollup_rules`/
`ninth_rollup_rules` are maintained, reviewed sheets — every active row in
them (subject only to each row's own `include` flag and `rollup_context`,
using the same semantics as
`codebase/mapping_tools/mapping_rollups.py::active_rollup_rules`/
`context_applies`) is trusted as a legitimate equivalence. Do not add a
separate approval/allowlist layer beyond what those two fields already
express — Finn confirmed this explicitly rather than wanting a curated
subset.

### Required design

1. Use all three rollup sheets, not just `leap_rollup_rules`. There is no
   reason to special-case which axis gets rolled: `esto_rollup_rules` and
   `ninth_rollup_rules` cost nothing extra to include, and excluding them
   would mean writing extra filtering logic to keep them out — including
   all three is the simpler path, not the more complicated one.
   `codebase/mapping_tools/mapping_rollups.py` already implements exactly
   this: `read_rollup_rules` loads all three sheets, and
   `build_effective_mapping`/`apply_rollup_axis` roll the LEAP-side
   identity via `leap_rollup_rules` and the ESTO or ninth-side identity via
   `esto_rollup_rules`/`ninth_rollup_rules`, per axis, with cardinality
   tracking already built in. Reuse that machinery directly (or the
   smallest possible wrapper around it) rather than writing a second,
   parallel implementation that only reads `leap_rollup_rules`.
2. Wire this into `codebase/functions/supply_demand_mapping.py`
   (`_build_augmented_balance_demand_mapping_workbook`, or the direct
   `_build_direct_demand_mapping_status`/comparison-building path used by
   `load_balance_demand_inputs` — confirm the exact function that performs
   the ninth/esto pair lookup and is short of an ESTO pair for these rows):
   for any LEAP demand row whose `leap_sector_name_full_path` exactly
   matches (or is a descendant path of) an active rule's
   `input_leap_sector_name_full_path`, when no direct/leaf-level ESTO
   and/or ninth pair exists for that literal path and fuel, resolve the
   rolled target (LEAP side via `leap_rollup_rules`, then ESTO/ninth side
   via `esto_rollup_rules`/`ninth_rollup_rules` if the rolled LEAP identity
   still doesn't have a direct combined-sheet row) and look up **that**
   target. The Road case is the proof this works on the LEAP-rollup axis
   alone (blank `rolled_leap_sector_name_full_path` + `rolled_raw_leap_fuel_name
   = "Road"` resolves, in the combined sheets, to sector
   `leap_sector_name_full_path = "Road"` with the row's original fuel) —
   before generalizing, read enough of the sheet's other rollup rows (and
   the `Note` column, which documents blank-value conventions per row) to
   confirm this interpretation holds consistently, since the sheet appears
   to use both sector-level rollups (e.g. into `Coal transformation`) and
   this fuel-column-as-group-label pattern (e.g. into `Road`, `Transport`,
   `Total final consumption`) — the resolver needs to handle whichever
   patterns are actually present, not just the one this prompt happened to
   trace through manually.
3. Apply the same general resolver wherever an ESTO or ninth pair is
   missing, not just for transport — it should transparently pick up any
   other sector/fuel combination that has an active rollup rule (on any of
   the three sheets) and a matching pre-built rolled-target row in the
   combined sheets, present or future, without new code.
4. **Critical**: implement this at the augmentation layer
   (`_build_augmented_balance_demand_mapping_workbook`, which writes the
   augmented `leap_combined_esto`/`leap_combined_ninth` sheets), not only
   inside the real-LEAP-export path. `_build_projection_only_mapping_status`
   (the path `baseline_seed` now always uses, per the already-implemented
   fix above) reads the *same* augmented workbook and does a plain inner
   join between its ninth and esto sheets with **no issues/diagnostics at
   all** — unmatched rows (e.g. today's Freight road/Passenger road rows)
   are silently dropped, not reported. If the rollup fix is only wired into
   the real-export path, `baseline_seed` will stop hard-failing but will
   silently lose the same transport demand from its supply-sizing input —
   worse than today's loud failure, not better. Add a focused test that
   calls `_build_projection_only_mapping_status` directly (or
   `load_balance_demand_inputs` with `allow_projection_only_without_balance_exports=True`)
   and asserts the previously-missing Freight/Passenger road rows are now
   present in its output, not just in the real-export path's output.

   Fix 1 (the `KNOWN_LEAP_LABEL_EXCEPTIONS` alias) does **not** need this
   same treatment: `_build_projection_only_mapping_status` never reads
   LEAP's raw export text, only the mapping sheet's own (consistently
   correctly-spelled) `raw_leap_fuel_name` column joined against itself, so
   the Black liqour/Black liquor mismatch cannot occur on that path. Fix 1
   only needs to apply where LEAP's actual export is read (the
   `results_update`/real-balance-export path).
5. Verify: rebuild `supply_reconciliation_balance_demand_issues.csv` (or an
   equivalent focused check against `load_balance_demand_inputs`/
   `_annotate_balance_demand_issue_scope` for 20_USA) and report the full
   before/after `missing_esto_pair` count, not just the transport subset —
   the general engine may resolve other previously-unnoticed gaps too.
   Report exactly which rows (if any) still fail to resolve, with the
   specific rollup rule or missing rolled-target row that would be needed,
   rather than silently dropping unresolved rows.
6. Add focused tests: one exercising the Road case specifically (e.g.
   `Freight road/Trucks/BEV heavy | Electricity` resolves to the `Road`
   sector's ESTO pair when no sector-specific ESTO row exists), one
   exercising a second, different LEAP-rollup pattern from the sheet (e.g.
   one of the `Coal transformation` or `Total final consumption` rows) to
   prove the resolver isn't secretly Road-specific, and one exercising an
   `esto_rollup_rules` or `ninth_rollup_rules` row to prove those two
   sheets are actually consulted, not just loaded and ignored.
7. We should explore what other workflows in leap_initialisation might benefit from this same rollup-resolver logic, but
   that is a separate task. For now, only implement it in the demand-mapping
   path and add this as a follow-on backlog item for the next agent to investigate.

### Boundary

Do not add, remove, or edit any row in `outlook_mappings_master.xlsx`. This
fix is entirely code-side, consuming rollup rules and combined-sheet rows
that already exist.

### Coverage and gap-safety rule

This is the piece that prevents accidental data gaps.

1. Parent rows flagged `leap_is_subtotal = True` / `ninth_pair_is_subtotal = True`
   are not separate demand facts. They are aggregate containers whose values are
   already represented by their children.
2. The resolver must work from the leaf rows that already exist in the LEAP-side
   demand table. Do not infer missing leaf coverage from a parent total.
3. If a leaf row has no direct combined-sheet match, the code may try an active
   rollup rule and a pre-built rolled target row. If that still fails, the row
   must remain unresolved and be written to the diagnostics CSV. Do not fill the
   gap by summing children, copying the parent value, or silently dropping the
   row.
4. The safety check for this work is therefore:
   - leaf rows are enumerated explicitly,
   - rollup rules only rescue rows that already exist,
   - unresolved leaf rows stay visible in the CSV,
   - aggregate parent rows are only used as diagnostics to confirm the source
     hierarchy, not as a fallback mapping source.

If a missing mapping is genuinely uncovered by the active rollup rows and there
is no matching rolled target row in the combined sheets, stop and report it.
That is a real data gap, not something to paper over.

### Follow-on backlog for the next agent

The items below came out of the same discussion, but they are separate from the
two fixes above. Include them in the handoff prompt for the next agent so they
do not get lost:

1. Verify the earlier `KNOWN_LEAP_LABEL_EXCEPTIONS` fix directly, the same way
   the Road rollup was independently verified.
2. Correct the INIT-008 wording so it says the canonical bridge covers the
   granular leaf-level 9th codes, not the parent aggregate codes.
3. Refactor `codebase/utilities/energy_balance_template_extractor.py` so
   validation collects all issues into a CSV instead of aborting on the first
   failure. Match the `leap_mappings` coverage-check pattern.
4. Fix the `Transport non-road` versus `Transport non road` label mismatch in
   `LEAP_DEMAND_GROUP_ESTO_SECTOR_MAP`.
5. Remove the ad-hoc alias dictionary in `_infer_active_demand_branch_groups`
   and match directly against `LEAP_DEMAND_GROUP_ESTO_SECTOR_MAP` keys after
   normalizing case and whitespace.
6. Gate `_infer_active_demand_branch_groups` to `results_update` only.
   `baseline_seed` should use the static `DETAILED_DEMAND_BRANCHES_ACTIVE`
   list, because the projection-only sector table is not a reliable proxy for
   real LEAP state.
7. Empirically verify the distinct `sheet` values in the real
   `mapping_status` output.
8. Confirm whether `_run_capacity_unmet_iterative_balanced_pass` needs its own
   independently computed total-requirements figure, or whether it relies
   entirely on LEAP's recalculated balance.
9. Once the fixes land, refresh
    `docs/managed_leap_initialisation_resume_20_usa_prompt.md` in a fresh chat
    so the managed-run companion is no longer stale.

Note: 9 might be a large job and could be split into a separate task if it is too big to fit in the current agent's scope. The other items are small enough to be included in the same handoff, we think.

## Documentation requirement (all four fixes)

Add one new entry to `docs/special_rules_and_design_decisions.md`, next
available ID **INIT-008** (confirm nothing has taken that number since this
prompt was written), following the existing entry format (Status / Owner /
Type / Affected areas / Situation / Options / Current rule / Validation /
History). Cover all four fixes described in this prompt (the two already
implemented and the two built under it), since none of them are yet
documented there. Suggested split: either one entry titled something like
"Balance-demand mapping gaps: baseline_seed demand source, non-actionable
fuel rollups, known LEAP label exceptions, and the Road transport rollup",
or — if that reads as too many unrelated concerns for one entry — up to two
entries (e.g. one for the baseline_seed-vs-results_update demand source
split plus the Total exclusion, and a separate one for the known-label-
exceptions mechanism plus the Road rollup, since those two are more clearly
paired). Use judgement matching the existing document's granularity; do not
create more than two new entries for this work.

Each entry must record, in the `Current rule` / `Affected areas` sections:

- Exactly why the fix exists (root cause, not just symptom).
- The exact files/functions involved.
- For the known-label-exceptions mechanism: that it is temporary, keyed off
  `KNOWN_LEAP_LABEL_EXCEPTIONS`, and the removal condition (LEAP model
  corrected upstream, rescue log goes quiet).
- For the rollup fallback: that it is a general resolver over all active
  rows in `leap_rollup_rules`, `esto_rollup_rules`, and `ninth_rollup_rules`
  (gated only by each row's own `include`/`rollup_context` fields, no
  separate allowlist — Finn's explicit call, since those sheets are already
  maintained and reviewed), proven via the Road transport case but not
  scoped to it.

Also add a dated `History` line for today's date under each new/changed
entry, per the document's existing convention.

## Testing

- Run the focused tests for each fix as you build it.
- Run `python -m pytest tests/ -k "demand or balance_demand or supply_reconciliation or baseline_seed" -q`
  after both fixes are in.
- Run the complete suite (`python -m pytest -q --ignore=tmp`) before
  considering this done, and record the passed/failed/skipped counts.

## Boundary / stop conditions

- Do not edit `leap_mappings/config/outlook_mappings_master.xlsx` under any
  circumstance in this task.
- Do not expand `KNOWN_LEAP_LABEL_EXCEPTIONS` beyond the one documented
  entry without checking with Finn first. The rollup fallback, by contrast,
  is intentionally general — apply it to all active rows across all three
  rollup sheets, no separate approval needed per rule.
- If a genuinely new `missing_esto_pair` gap appears that no active rollup
  rule and pre-built rolled-target row can resolve (e.g. a fuel under
  `Freight road`/`Passenger road` not covered by the 12 `Road` rows, or a
  rollup rule whose declared target has no matching row in the combined
  sheets), stop and report it rather than inventing a mapping.
- Do not modify `docs/balance_demand_conservation_check_prompt.md` or any
  conservation-check-only logic unless a shared helper change is genuinely
  needed by both tasks. If a proposed edit would overlap with the
  conservation agent's work, stop and report the overlap instead of editing
  around it.
- Preserve all existing uncommitted working-tree changes; do not commit,
  stage, reset, or discard anything unless explicitly asked.
