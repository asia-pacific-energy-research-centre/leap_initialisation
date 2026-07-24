# Task: explore fully fixing the transformation patcher (rewire onto the workbook producer)

This prompt is a handoff to explore — and, if the evidence supports it, implement —
the fix needed to safely ungate transformation-module patching in
`codebase/functions/patch_baseline_seeds.py`.

## Background — read this first, do not re-derive it from scratch

`run_patch()` raises `NotImplementedError` for every module with `auto_sector_keys`
set in `MODULE_REGISTRY` (`oil_refineries`, `lng`, `hydrogen`, `gas_processing`,
`coal_transformation`, `petrochemical`, `charcoal`, `biofuels`,
`nonspecified_transformation`, `transformation`). This gate is **settled and
correct as of 2026-07-21** — see `docs/work_queue.md` item **[1]** and the
`transformation-patch-gate-reassessment` memory. Do not treat "the gate seems
overly cautious" as a starting hypothesis; it was tested and holds.

The definitive evidence: `codebase/scrapbook/transformation_ungate_equivalence_harness.py`
ran the real patcher (bypassing only the `NotImplementedError` check) against a
fresh, current-rules `12_NZ` seed and diffed POST-write output against POST-write
output (both sides crossed `prepare_seed_rows_for_write`, so the comparison is
apples-to-apples). Verdict: **DEFECT** — 1209 rows dropped, 21 rows invented, 72
non-benign value changes. Failure classes seen: single-output selection flips
(e.g. Gas to liquids Output Share `Gas and diesel oil` 100→0 / `Kerosene` 0→100),
dropped split-target rows (e.g. BKB and PB plants Export/Import Target rows the
real workbook producer emits but the patch path omits), and invented rows
(Hydrogen transformation `Smr wo ccs` capacity/efficiency rows with no basis in
the full run).

**Root cause, already diagnosed and not in question:** the patcher's
transformation path uses `_collect_auto_regen`
(`codebase/functions/patch_baseline_seeds.py:641-728`), a simplified
reimplementation that calls `build_transformation_log_rows` +
`build_aux_fuel_zero_rows` + `build_export_from_log_rows` directly. This is
**not** the same code path as the real transformation-export producer,
`save_transformation_exports_with_split_targets`
(`codebase/functions/supply_leap_io.py:575-759`), which additionally applies
split-target logic, single-output selection, and other rules `_collect_auto_regen`
never runs. The two diverge, and `_collect_auto_regen`'s output is what gets
written into patched seeds.

**Why this matters right now:** we just root-caused and fixed a live data bug
(case-sensitive branch-path collisions in `build_aux_fuel_zero_rows`, see the
`.casefold()` change in `transformation_record_builder.py` — check `git log` /
`git diff` for the exact commit) that corrupted `Feedstock Fuel Share` values
across at least 5 economies' live baseline-seed exports (AUS, BD, MAS, MEX, USA).
Because the transformation patch gate is closed, those economies cannot be
spot-patched — they need a full `baseline_seed`/`results_update` re-run, which is
slow. A working, ungated transformation patcher would make future fixes like this
one cheap to roll out. That is the motivation for this task, not a requirement —
do not weaken correctness to save time.

## Objective

Explore whether the transformation patch path can be rewired onto the real
workbook producer (the pattern already used for the `transfers` module — see
`_run_source_workflow`'s `"transfers"` branch, `patch_baseline_seeds.py:770-801`,
and `_collect_from_workbooks`, `patch_baseline_seeds.py:595-638`), and — only if
the evidence supports it — implement that rewire and re-prove correctness with
the same equivalence harness used to establish the gate.

This is explicitly an **explore-first** task. Do not commit to an implementation
before you understand why `_collect_auto_regen` and
`save_transformation_exports_with_split_targets` disagree; the disagreement may
turn out to be more than a "call the other function" fix.

### Step 1 — Understand the divergence precisely

Before touching code, read both paths side by side:

- `_collect_auto_regen` (`patch_baseline_seeds.py:641-728`)
- `save_transformation_exports_with_split_targets`
  (`codebase/functions/supply_leap_io.py:575-759`) and whatever it calls that
  `_collect_auto_regen` skips (split-target application, single-output
  selection, etc. — trace the call chain, don't guess)

Map out, concretely, every step the real producer performs that
`_collect_auto_regen` does not, and vice versa. Use the 12_NZ harness defect
list above as your test cases: for each of the three failure classes (changed
value, dropped row, invented row), find the specific code path in the real
producer responsible for the correct behavior and confirm `_collect_auto_regen`
truly lacks it (don't assume from the diff alone).

### Step 2 — Assess the workbook-based pattern's fit

The `transfers` module's approach (`patch_baseline_seeds.py:770-801`) is:
`_run_source_workflow("transfers", ...)` calls the real producer
(`save_transfer_exports_with_supply_overrides`) to write per-economy workbooks
to `WORKBOOKS_DIR`, then `_collect_from_workbooks` (`patch_baseline_seeds.py:595-638`)
reads those files back in as the patch source, keyed by `workbook_glob` in
`ModuleConfig`.

Determine whether the same pattern works for transformation:

- Can `save_transformation_exports_with_split_targets` be called per-economy
  (or per-sector) to write standalone workbooks the way the transfers producer
  does, without requiring inputs that only exist mid-way through a full
  `baseline_seed` run (e.g. a populated `reconciliation_table`, supply-side
  overrides, or other cross-module state)? Read its full signature and
  docstring, and check how it's called from the real workflow
  (`grep -rn "save_transformation_exports_with_split_targets"`) to see what
  callers currently supply.
- Does one workbook per economy make sense, or does the transformation output
  need to be split per auto-regen sector key (`oil_refineries`, `lng`, etc.) to
  preserve the existing `MODULE_REGISTRY` granularity (separate strip_prefixes
  per module, so patching just `lng` doesn't touch `oil_refineries` rows)?
  `_derive_prefixes` (`patch_baseline_seeds.py:917-924`) and each module's
  `strip_prefixes` may need to stay sector-scoped even if one shared workbook
  is produced.
- If a genuine input dependency blocks a clean standalone call (e.g. it needs
  the reconciliation table from a real run), find out whether an empty/baseline
  reconciliation table (matching what `_run_source_workflow`'s `"transfers"`
  branch does with `pd.DataFrame()`) is a valid substitute, or whether that
  changes transformation's behavior in a way that would itself be a defect.

### Step 3 — If viable, implement

Only proceed here if Step 1-2 give you a concrete, well-understood rewire plan —
not a "probably works" guess.

1. Add a `"transformation"` (and/or per-sector) branch to `_run_source_workflow`
   that calls `save_transformation_exports_with_split_targets` and writes
   workbooks to `WORKBOOKS_DIR`, following the `"transfers"` branch as the
   template.
2. Update the relevant `MODULE_REGISTRY` entries (`oil_refineries`, `lng`,
   `hydrogen`, `gas_processing`, `coal_transformation`, `petrochemical`,
   `charcoal`, `biofuels`, `nonspecified_transformation`, `transformation`) to
   use `workbook_glob` instead of `auto_sector_keys`, matching the workbook-based
   modules' shape.
3. Remove `_collect_auto_regen` only once nothing references it, or leave it in
   place with a comment explaining it's superseded, if removing it is riskier
   than keeping dead code around briefly — use judgment, but don't leave two
   live code paths that claim to do the same thing.
4. Do **not** delete the `auto_sector_keys` gate check
   (`patch_baseline_seeds.py:1084-1089`) until Step 4 passes.

### Step 4 — Re-prove correctness

1. Regenerate a fresh baseline seed for at least `12_NZ` and `20_USA` with
   current code (the same "notebook-safe workflow" prior agents used — do not
   invent a new command-line path; check `docs/work_queue.md` and
   `docs/supply_reconciliation_workflow_guide.md` for the established process).
   A seed older than the last transformation-rules change is not valid evidence
   — check `TRANSFORMATION_RULES_CHANGED` in
   `codebase/scrapbook/transformation_ungate_equivalence_harness.py` and bump it
   if your rewire itself changes transformation output (it may, if it fixes real
   defects like the dropped/invented rows above).
2. Update `codebase/scrapbook/transformation_ungate_equivalence_harness.py` if
   needed so it bypasses your new code path correctly, then run it:
   `python codebase/scrapbook/transformation_ungate_equivalence_harness.py 12_NZ 20_USA`
3. Require **PASS** (zero dropped rows, zero invented rows, zero non-benign
   value changes) before removing the gate. `STALE-SEED` or `BLOCKED` are
   inconclusive, not evidence — diagnose and fix the seed, don't reinterpret the
   gate.
4. If you get DEFECT, that is a valid and useful outcome: document exactly what
   still diverges and why (same three failure classes as before), keep the gate,
   and hand off with precise findings rather than forcing a PASS.

### Step 5 — If it passes, ungate correctly

Only after a genuine PASS:

1. Remove `auto_sector_keys` from the now-fixed `MODULE_REGISTRY` entries.
2. Remove or narrow the `NotImplementedError` check
   (`patch_baseline_seeds.py:1084-1089`) so it only fires for modules that are
   still genuinely unsafe (there should be none left, but don't delete the
   mechanism itself in case a future module needs it).
3. Update `docs/supply_reconciliation_workflow_guide.md:239` (the "Patchable
   today" list) and `docs/check_registry.md` hotspot 4 to reflect the new state.
4. Update `docs/work_queue.md` item [1] with the new verdict and evidence,
   replacing "⛔ SETTLED 2026-07-21: gate STAYS" with the corrected status.
5. Run the full test suite (`python -m pytest tests/ -q`) and specifically
   `tests/test_check_registry.py` and any patcher-specific tests
   (`grep -rln "patch_baseline_seeds" tests/`).

## What "explore" means if the answer turns out to be "not viable"

If Step 1-2 reveal that `save_transformation_exports_with_split_targets` cannot
be cleanly called outside a full run (e.g. it has hard dependencies on live
reconciliation state that can't be faithfully stubbed), that is a legitimate
and useful conclusion. In that case:

- Do not force a workaround that reintroduces the same class of defect through
  a different mechanism.
- Document precisely what blocks the rewire (the specific input, the specific
  call site, why a stub/default isn't equivalent).
- Update `docs/work_queue.md` item [1] with this finding so the next person
  doesn't redo Step 1-2 from scratch.
- Consider and report on whether a narrower alternative is worth pursuing —
  e.g. ungating only the modules that don't hit the blocking dependency (if the
  defect classes above vary per module), rather than all-or-nothing.

## Guardrails

- Read `docs/prompts/transformation_final_handoff_and_verification_prompt.md`
  for the tone and rigor expected on this specific gate (it documents the
  earlier raw-vs-seed measurement trap — do not repeat it: always diff
  POST-write vs POST-write).
- Never diff raw producer output against a finished seed — the seed writer
  (`prepare_seed_rows_for_write`) does canonical share completion and
  cross-scenario borrowing that manufactures false differences if only one side
  crosses it.
- Let any long-running regeneration workflow finish; do not interrupt it. See
  the `long_workflow_polling` memory — poll infrequently, don't babysit.
- Keep measurement (Step 1-2), implementation (Step 3), and verification +
  documentation (Step 4-5) in separate, coherent commits.
- Do not alter unrelated `_PRESET_PATCH_BASELINE_SEEDS` blocks or other
  modules' `MODULE_REGISTRY` entries.
- Never use destructive Git commands (`git reset --hard`, `git checkout --`,
  force push) to resolve conflicts or clean up.
- Do not claim the gate is fixed based on unit tests alone — the only
  acceptable evidence is the equivalence harness against a fresh, current-rules
  seed.

## Deliverables

Report:

1. Whether the rewire is viable, with the specific evidence from Step 1-2.
2. If implemented: the harness verdict (PASS/DEFECT/STALE-SEED/BLOCKED) for
   each economy tested, with full diff counts.
3. If PASS and ungated: which modules are now safely patchable, and the
   updated `docs/work_queue.md` / `docs/supply_reconciliation_workflow_guide.md`
   / `docs/check_registry.md` state.
4. If not viable or still DEFECT: the precise blocking reason, retained gate,
   and updated documentation so this doesn't need re-diagnosing later.
5. Tests and workflows run, and final `git status --short`.
