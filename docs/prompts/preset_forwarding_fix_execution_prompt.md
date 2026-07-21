# Preset forwarding fix - execution prompt (T1 / work_queue [17])

Type: implementation + single-economy verification prompt.
Status: active, opened 2026-07-21. **Current priority.**
Register entry: T1 in [`initialisation_refactor_continuation.md`](initialisation_refactor_continuation.md)
Full detail: `docs/work_queue.md` [17]

## Short version

Two preset overrides never reach the module that reads them, so the
supply/transformation zero-reset and the demand-zeroing workbooks have been
silently off in every recent baseline seed while the log said they were on.
Fix the delivery mechanism first in commits that provably change nothing, then
flip the behaviour on in one isolated commit, then verify with a
**single-economy** before/after check. Do not run a fleet run.

## Context - why this is being done now, out of phase order

The current phase of work in this repository is **Phase 2, configuration
standardisation** (`work_queue.md` [14]). This task belongs to **Phase 4**
territory - it is the mechanism that Phase 4's state-injection work
(register thread T3) will eventually replace wholesale.

It is being **brought forward** because it is not a refactor: it is an active
production defect.

- The intent is unambiguous. Both flags are set in `_PRESET_BASELINE_SEED` with
  the comment `# overrides config default`, and
  `supply_reconciliation_config.py:1096` is itself commented
  `# PRESET-CONTROLLED DEFAULT: both active presets replace this value.`
  The mechanism meant to replace it does not.
- The effect reaches output: the zero-reset and the demand-zeroing workbooks
  are the double-count and stale-value guards.
- It has been true for **every recent baseline seed**, including the `01_AUS`
  seed used as evidence elsewhere, and the run log actively misreported it.

So: fix the defect now, at minimum scope, without trying to do Phase 4's job.
**Do not start the state-injection refactor inside this task.** Route through
the existing `_broadcast_config_overrides` if that is the smaller change; leave
the architecture to T3.

## The defect, verified

`_PRESET_BASELINE_SEED` sets these on `codebase/supply_reconciliation_workflow.py`;
they are absent from `_sync_results_saver_overrides`'s hand-maintained list, so
`codebase/functions/supply_results_saver.py` keeps its own `import *` copy of
the config default:

| Name | Wrapper (preset) | Config default | `supply_results_saver` |
| --- | --- | --- | --- |
| `RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT` | `True` | `False` | **`False`** |
| `ZERO_OTHER_DEMAND_BRANCHES_FROM_EXPORT` | `True` | `False` | **`False`** |

Neither `_sync_results_saver_overrides()` nor `_broadcast_config_overrides()`
delivers them: the broadcast at `supply_reconciliation_workflow.py:574` carries
only `CAPACITY_UNMET_PASS_MODE` plus refreshed paths, and
`globals().update(ACTIVE_PRESET)` (`:894`) is not followed by a broadcast.

**Verify all of this yourself before changing anything** - line numbers are
point-in-time. Reproduce with an import-only check comparing the three values,
and confirm that calling `_sync_results_saver_overrides()` does not fix them.

### What actually changes when the flags are delivered

Live today (workbook mode, LEAP import disabled):

1. `supply_results_saver.py:3223` - `reset_supply_and_transformation_import_export_to_zero(...)`
   currently skipped, so Import/Export/target values are not zeroed before
   filling. **The substantive one.**
2. `:3655` - `build_other_demand_zeroing_workbooks(...)` currently skipped; no
   demand-zeroing workbooks are produced at all.

Currently inert, do not chase: `:2853` (appends Current Accounts in reset mode -
the run scenarios already include it) and the five
`... or RUN_RESET_...` clauses at `:3695-3743` (inside the disabled
`INCLUDE_LEAP_IMPORT` block; the LEAP API is decommissioned).

Four further names sit in the same hole but do **not** currently diverge:
`USE_AGGREGATED_DEMAND_AS_DUMMY`, `WRITE_AGGREGATED_DEMAND_WORKBOOK`,
`AGGREGATED_DEMAND_EXCLUDED_SECTORS`, `AGGREGATED_DEMAND_USE_SECTOR_BRANCHES`.
`supply_reconciliation_tables` has the same hole for the first and third. Fix
the mechanism for all of them; only two change behaviour.

## Decision already taken - do not reopen

**The presets are right** (user, 2026-07-21). The zero-reset and demand zeroing
are wanted; the delivered `False` is the defect. Seed contents will change for
every economy, and that is accepted. Options "accept current behaviour" and
"re-review reset scope" are closed.

## Preconditions

- **No long run may be in flight.** Check before starting: no economy locks
  under `outputs/leap_exports/supply_reconciliation/supporting_files/runtime/economy_locks/`,
  no run-sized Python process, and the newest run log not still growing.
- `git status --short` - expect a temporary `RUN_OUTPUT_LABEL` edit in
  `supply_reconciliation_workflow.py` and untracked `node_modules/`. **Both
  belong to the operator. Do not stage, revert, or "tidy" either.** If the
  label needs changing for the verification run, ask first.
- `tests/test_reconciliation_state_forwarding.py` (`a279615`) exists and pins
  the defect with three strict xfails plus `KNOWN_UNFORWARDED` /
  `KNOWN_STALE_FORWARDED_NAMES`. Read it before editing - it is the oracle for
  steps 1-3.

## Sequence - five commits, in this order

### Commit 1 - deliver the overrides (mechanism only, provably inert)

Make preset overrides actually reach the extracted modules. **Pin the two
divergent names to their current *effective* values** (i.e. keep the delivered
behaviour `False`) so this commit demonstrably changes no output.

Prefer routing through `_broadcast_config_overrides` - it walks `sys.modules`
and sets only attributes a module already defines, so it cannot go stale the way
the 37-name list does. Extending the hand list is acceptable only if the
broadcast route proves larger than this task's scope; say which you chose and
why.

Update `tests/test_reconciliation_state_forwarding.py`: the forwarding tests
should now pass for the mechanism, while the two behaviour xfails remain until
commit 4.

**Evidence required:** an import-level check showing every preset key that a
target module reads now agrees across wrapper and target, and that the two
divergent names are still `False` on both sides.

### Commit 2 - make the toggles line report effective values

`supply_reconciliation_workflow.py:~1159` prints the *wrapper's* values. In the
failed fleet run's log, line 4293 printed
`RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT=True` and line 4294 printed
`Reset reminder: ... is DISABLED`. **This is why the defect survived weeks
unnoticed.**

Print what the consumers hold. Keep the existing key names - run-review prompts
read this line. Do **not** delete the `[WARN] Reset reminder` line; it is
currently the only honest signal.

### Commit 3 - remove the dead forwarding entry

`TRANSFORMATION_SUPPLY_CACHE_PATH` is in the forwarding list
(`supply_reconciliation_workflow.py:~419`) but defined nowhere in `codebase/`.
`_sync_results_saver_overrides` guards each push with `if name in globals()`,
so it is a silent no-op. Remove it and its `KNOWN_STALE_FORWARDED_NAMES` pin.

### Commit 4 - flip the behaviour on. ISOLATED. NEVER BUNDLED

Remove the pins from commit 1 so the preset values take effect: the zero-reset
runs and demand-zeroing workbooks are produced. Un-`xfail` the corresponding
tests.

This is the only commit in this task that changes output. If a later seed diff
appears, this is the single commit to revert.

### Commit 5 - record the verification evidence

Documentation-only: the before/after measurements, in `work_queue.md` [17], and
the register entry closed.

## Verification - single economy, not a fleet run

Recommended economy: **`01_AUS`** (real template, and `70a6c88` provides a clean
reference seed). `12_NZ` is an acceptable alternative.

1. Produce a baseline-seed run for the chosen economy at **commit 3** (mechanism
   fixed, behaviour unchanged). Confirm it matches the existing reference seed -
   **this is the proof that commits 1-3 are inert.** If it does not match, stop:
   something in the mechanism fix changed behaviour and must be understood
   before commit 4.
2. Run again at **commit 4**.
3. Compare **post-boundary on both sides**: branch-path key sets, row counts,
   per economy/scenario/fuel totals. Report the tolerance used.

**Expect real differences at step 3.** The point is not that nothing changed -
it is that the changes are the *intended* ones and nothing else moved:

- supply/transformation Import/Export/target values reset to zero before
  filling;
- demand-zeroing rows present where previously absent;
- **no** unexplained change to transformation processes, supply production, or
  own-use values.

Classify every difference before declaring success. An unexplained difference is
a stop-and-report, not a rounding note.

Also confirm from the run log that the toggles line and the reset reminder now
**agree** - that is commit 2's acceptance test.

## Out of scope - do not do these here

- Phase 4 state injection (register T3). Related, larger, separately planned.
- The demand-zeroing / active-sector gap (register T6 G2). It is unblocked *by*
  this task, not part of it.
- Any preset value change other than making the existing ones take effect.
- Relaunching the fleet run (register T11) - that follows a successful
  verification, on the operator's say-so.
- Touching `leap_mappings`.

## Stop and ask the user when

- the step-1 baseline does **not** reproduce the reference seed;
- the commit-4 diff contains a difference you cannot attribute to the reset or
  the demand zeroing;
- the verification appears to need more than one economy;
- `RUN_OUTPUT_LABEL` needs changing for the verification run;
- a long run turns out to be in flight.

## Deliverables

- Five commit hashes, with the inert/behaviour split clearly stated.
- The before/after comparison table, with tolerance and classified differences.
- Confirmation the log's toggles line and reset reminder now agree.
- `work_queue.md` [17] and the register's T1 entry updated and closed.
- A statement of what is now unblocked (expected: register T6 G2, and T11 once
  the operator is ready).
