# Initialisation refactor - continuation and open-thread register

Type: continuation / handoff register. Status: active, opened 2026-07-21.

## Purpose

This file exists so that starting `[17]` does not cause everything else agreed
on 2026-07-21 to be forgotten. It is the **single index of open threads** from
that session: what was decided, what is still open, what order to take things
in, and which findings are recorded nowhere else.

## How to execute from this register

- **T1** has its own prompt:
  [`preset_forwarding_fix_execution_prompt.md`](preset_forwarding_fix_execution_prompt.md).
  It is the current priority.
- **Every other thread** is executed via
  [`initialisation_refactor_thread_execution_prompt.md`](initialisation_refactor_thread_execution_prompt.md)
  - one thread per session, with the phase framing and evidence standards it
  carries.

It is deliberately an index, not a duplicate. Detail lives in:

- `docs/work_queue.md` [16] (roadmap), [17] (the priority defect)
- `docs/prompts/phase_3_canonical_mapping_migration_execution.md`
- `docs/prompts/phase_4_monolith_decomposition_execution.md`
- `docs/prompts/phase_5_feature_improvements_execution.md`
- `docs/prompts/other_loss_own_use_proxy_scoped_review.md`

**Update this file whenever a thread closes.** When every thread is closed or
re-homed, archive it per `docs/prompts/AGENTS.md`.

## Standing safety rules (apply to every thread below)

1. **While a long run is in flight, commit documentation and new test files
   only.** A code commit landing mid-run can kill it via mixed module versions -
   this destroyed the 2026-07-21 fleet run 78 minutes in. See the trap entry in
   `work_queue.md`. A clean `git status` at launch does not protect you.
2. One issue per commit; `codex:` message convention.
3. Verification runs need a clean tree.
4. Never diff raw export output against a finished seed - compare
   post-boundary on both sides.
5. Never reintroduce a pinned `id_lookup_path` / template default.
6. Do not chase the known pre-existing test failures listed in `work_queue.md`.
7. Python is `/c/Users/Work/miniconda3/python.exe` via the Bash tool. Several
   `codebase/*.py` files carry a UTF-8 BOM - read as `utf-8-sig` for any AST or
   text tooling.

## Immediate state (2026-07-21, end of session)

- **The 21-economy fleet run FAILED** at 16:36, no seeds produced, killed by the
  mid-run commit hazard above. It must be relaunched - but **not before [17] is
  fixed**, since [17] changes seed contents anyway.
- The working tree still carries a temporary `RUN_OUTPUT_LABEL`
  (`SEED_21ECON_POST_TEMPLATE_REFRESH_20260721_151747`) in
  `supply_reconciliation_workflow.py`, pointing at the failed run's directory.
  **It must be reset to `"auto"` or a fresh label before relaunch**, or the new
  run writes into the dead run's folder. It is the user's edit - confirm before
  changing.
- Nothing holds `supply_reconciliation_workflow.py` any more. Phase 4 and [17]
  work are unblocked.

**Update, 2026-07-21 evening.** [17] steps 1-3 are committed (`3928a7b`,
`857b6e4`, `2017ef4`); the behaviour flip is paused. Two facts worth carrying
forward:

- **Another session committed to `codebase/` during this one** (`16e4a26`,
  `2ffd09c`, 17:57-17:58). Standing safety rule 1 covers a *live run*; this is
  the adjacent hazard - concurrent commits make any before/after measurement
  unattributable even with no run in flight. That is why T1's verification was
  paused rather than run.
- **A second pre-existing test failure exists** and was not on the "do not
  chase" list: `tests/test_leap_export_template_resolver.py::
  test_read_area_from_real_usa_template`. Confirmed failing at `2713a51`, i.e.
  before any [17] work. Full suite at that point: 2 failed, 788 passed,
  11 skipped, 6 xfailed, 12 subtests passed.

## Thread register

### T1 - [17] preset forwarding defect. CODE COMPLETE, MEASUREMENT OUTSTANDING

**Update, later on 2026-07-21: step 4 resumed on the user's explicit
authorisation and the flip has landed.** The four commits are:

| Commit | What | Output-affecting |
|---|---|---|
| `3928a7b` | deliver preset overrides to the modules that read them | no (pinned) |
| `857b6e4` | make the `run_with_config` toggles line report effective values | no |
| `2017ef4` | remove the dead `TRANSFORMATION_SUPPLY_CACHE_PATH` forwarding | no |
| step 4 below | empty `_PRESET_BROADCAST_PINS` - the flip | **YES. Revert this one alone.** |

`scripts/check_preset_forwarding.py` now reports zero disagreeing readers and
zero stale copies. `tests/test_reconciliation_state_forwarding.py`: 60 passed,
0 xfailed - all three strict xfails resolved and un-marked in the flip commit,
which was mandatory rather than optional (being `strict=True`, they would have
failed the suite as unexpected passes).

**The single-economy before/after comparison has NOT been run.** It is the
substance of the task and it remains open. It needs a fresh `RUN_OUTPUT_LABEL`,
which is the operator's to give - the working tree still carries the dead fleet
run's label. Two fresh runs are required (before = flip commit reverted or the
flags forced `False`; after = flip commit), compared **post-boundary on both
sides**: branch-path key sets, row counts, per economy/scenario/fuel totals,
tolerance stated. Never use `SEED_21ECON` as a reference.

Expect exactly two differences - supply/transformation Import/Export/target
values zeroed before filling, and demand-zeroing workbooks present where the
live run directory has none. Anything else is a stop-and-report.

See [17]'s "Correction: the defect is wider than this entry first said" for the
measured blast radius: nine modules held a stale copy of the flags, but only
`supply_results_saver` gates behaviour on them. `supply_preflight` changes one
log line, and the compressed *projection* preflight is **not** insulated from
the flip (only the results-update one pins the flag `False`).

The prior pause rationale below still stands as a caution and is retained.

### T1 (historical) - why step 4 was paused earlier

Decision settled: **the presets are right**; fix forwarding so the zero-reset
and demand zeroing take effect, accepting that seed contents change for every
economy. Verify with a **single-economy** before/after check, not a fleet run.

**Steps 1-3 landed 2026-07-21** (`3928a7b`, `857b6e4`, `2017ef4`) and are
deliberately inert: `_broadcast_preset_overrides()` now delivers preset keys to
the modules that read them, but the two flags that change output are withheld
by `_PRESET_BROADCAST_PINS`. Behaviour is unchanged from before the work.

**Step 4 is paused by user decision**, not by anything technical: other
sessions were committing to `codebase/` concurrently (`16e4a26`, `2ffd09c`
landed mid-task), and a before/after seed comparison is only attributable
against a still tree. **Resume when commits to `codebase/` have stopped.**

To resume: empty `_PRESET_BROADCAST_PINS`, drop the three now-stale
`xfail(strict=True)` markers in `tests/test_reconciliation_state_forwarding.py`
in the same commit, and run the three-point A/B in `work_queue.md` [17].
**Do not use the `70a6c88` reference seed as the baseline** - 21 commits and a
template refresh sit between it and this work; [17] explains the replacement.

Do not bundle the mechanism fix (steps 1-3) with the behaviour flip (step 4).

### T2 - Phase 4 characterization tests. PARTLY DONE

- Commit 1 **done** (`a279615`): forwarding-completeness test, 53 passed +
  3 strict xfails pinning the [17] defect.
- **Still to do:** config-surface snapshot per star-importing module;
  run-context snapshot per preset; convergence CSV schema pin; public-callable
  smoke tests. All test-only and safe at any time.
- Un-`xfail` the three strict xfails as T1 resolves them.

### T3 - Phase 4 state injection (B2 + B3). NOT STARTED

D4.1 decided: **explicit injection** (option (a)). B2 = capacity-unmet
allocation ledger; B3 = run context for output paths. Two-step pattern each
(introduce alongside, then thread through, then delete the mirror). Then remove
star imports one module per commit. **Then re-decide D4.3**
(`supply_results_saver.py`, 4,024 LOC) with fresh coupling numbers.

Prefer routing through `_broadcast_config_overrides` (walks `sys.modules`,
cannot go stale) over extending the 37-name hand list.

**Blocks T7 (parallelism).** Do T2 first.

### T4 - Phase 3 canonical mapping. NOT STARTED

Decided: **D3.1 retire** the `unified_name_lookup` consolidation API;
**D3.2 exclude** `IS_LEAP_ROLLUP_NAME` rows from display-name resolution, with
**recursive** component expansion (a rollup's components may themselves be
rollups) sourced from the leap_mappings rollup-rule sheets.

Commits: (1) pin canonical sheet schemas; (2) contract-test the three rollup
sheets; (3) retire the consolidation API; (4) exclude rollup labels
**[output-affecting, never bundle]**; (5) move legacy workbooks to
`config/legacy/`; (6) record equivalence evidence.

Commits 1-3 and 5 are safe alongside anything. Commit 4 needs a quiet tree.

**Still open: D3.3** (retire `config/master_config.xlsx` and
`config/leap_mappings.xlsx` - recommend move to `config/legacy/`), **D3.4**
(who owns rollup-rule reading - recommend a frozen column contract here),
**D3.5** (equivalence tolerance - proposed: key sets exactly equal, totals
within 1e-6 relative).

### T5 - Phase 5A convergence and run history. NOT STARTED, self-contained

Four commits: run manifest beside convergence history; compare runs by explicit
run id; opt-in pruning (`dry_run=True` default, never auto-delete); flag runs
whose inputs changed mid-run.

**Open: D5A.1** - sidecar manifest vs widening `capacity_unmet_convergence.csv`.
Recommendation: **manifest** (purely additive, cannot break existing readers,
and old runs would otherwise carry blank columns). D5A.2-4 have recommendations
in the Phase 5 brief and need only confirmation.

Safe at any time; touches only history/diagnostics modules.

### T6 - Phase 5B aggregated demand. PARTLY BLOCKED

5B.1 (filename IDs) and the any-order capability are **already built** -
`_sector_exclusion_suffix`, `resolve_active_branch_excluded_sectors`,
`_infer_active_demand_branch_groups`. 5B.2 (pre-generate subsets) is
**dropped**.

What remains:

- **G1** - the `aggregated_demand` seed patch passes only the manual exclusion
  list and never calls the resolver, so a patch cannot express "Industry just
  became real". Small, high value, not blocked.
- **G2 - the dangerous one, BLOCKED on T1.** `build_demand_zeroing_rows` has no
  concept of an active sector: it zeros every non-share `Demand\` branch except
  the placeholder, share variables, and the own-use prefix. So declaring a
  sector active drops it from the placeholder *and* zeros its detailed
  branches - silent energy loss, reachable from a full run, not just a patch.
  Latent only because `DETAILED_DEMAND_BRANCHES_ACTIVE` is `None`.
  **The first handed-over demand sector triggers it.** Blocked because no
  zeroing workbooks are produced at all until [17] is fixed.
  Fix shape: one resolved list feeds both halves, plus a test that no branch is
  both dropped from the placeholder and zeroed.
- **5B.3** - record individual branch contributions inside the aggregate file,
  on a separate sheet. The LEAP import sheet must not gain rows or columns.
- **Cache measurement** before touching the selective-column loader: cold/warm
  runtime, peak RSS, distinct `usecols` sets, invalidation after refresh.

**Open: D5B.3** (contributions on a separate sheet - recommended) and
**D5B.4** (contributions must reconcile exactly to the aggregate - recommend
yes, asserted in a test).

### T7 - Phase 5C per-economy parallelism. BLOCKED on T3

Scope is **workbook-mode only**. Do not plan or document parallel LEAP API
writes - the API is decommissioned and locked by
`tests/test_leap_api_decommissioned.py`.

**Urgent sub-item - DONE.** `PARALLEL_ECONOMY_WORKERS` already existed and
already drove a **`ThreadPoolExecutor`** over economies, sharing the mirrored
globals; it was safe only because the default is 0. The guard now lives in
`supply_results_saver._resolve_parallel_economy_workers`, refusing values > 1
and pointing at [17] and the Phase 5 brief, pinned by
`tests/test_parallel_economy_workers_guard.py`. Output-inert: the shipped
default is 0, so no run changes behaviour.

What the plan got slightly wrong: the guard belongs at the *consumption* point,
not on the config assignment. The dial is also reachable through
`_sync_results_saver_overrides` forwarding, so a config-side assert would not
have caught a wrapper-set value. Two shapes the plan did not mention and the
tests now pin: a non-`int` value degrades to serial rather than raising, and
`True` (an `int` in Python) must not read as one worker.

Remove the guard only as part of T7 proper, after T3.

Keep the existing `_run_one_economy` / `_collect_economy_result` seam - it is
the natural process-pool boundary. Convert the executor; do not rewrite the seam.

**Open: D5C.2** - worker-count default. Recommendation: **1 (serial), opt-in,
chosen from measured peak RSS**, never CPU count (the 9th CSV is ~275 MB per
worker, and this machine also runs LEAP).

### T8 - own-use proxy. RE-SCOPED, no structural work

D4.4 resolved by inspection: the module is healthy (19 uniform declarative
`PROXY_CONFIG` entries; only 3 oversized functions; 1 TODO in 4,113 lines).
`AGENTS.md`'s "internally tangled, rewrite may be cleaner" is obsolete.

**The real gap is coverage shape**, recorded in the scoped review: five
*enabled* processes are not named in the tests at all -
`electricity_chp_and_heat_plants`, `oil_and_gas_extraction`,
`nuclear_industry`, `gasification_plants_for_biogases`,
`transmission_and_distribution_losses` - while three of the four most-tested
processes are *disabled*. Build fixtures for those five, largest-volume first.

Optional, low priority: split `assemble_proxy_workbook` (356 lines/43 branches).

**Not established:** that the proxy's *numbers* are right. That is a modelling
review, separate from both of the above.

### T9 - documentation corrections. NOT STARTED

`AGENTS.md` "Planned workflow improvements" is materially stale and actively
misleads scoping:

- the LOC table (claims `supply_reconciliation_workflow.py` is 13,628 LOC; it is
  1,253) and the own-use figure (2,923; it is 1,770);
- Phase 3 (claims M2 blocks it; M2 is done and the migration landed);
- Phase 4 (claims the split is pending; it landed);
- Phase 5 (claims parallelism needs "minimal changes"; it does not);
- "Mapping file inconsistency" bullets (all three claims are out of date).

Also: `docs/supply_reconciliation_workflow_guide.md` "Planned improvements"
cites ~637 LOC for a file that is now 1,253, and
`docs/canonical_mapping_migration_notes.md` still describes C5 as BLOCKED when
the electricity/heat interim reads are now canonical.

Do these as each phase completes, not as one sweep, so the corrections carry
measured numbers rather than guesses.

### T10 - question for the mapping owner (leap_mappings). OPEN

Is `IS_LEAP_ROLLUP_NAME` set on **every** rollup label in `leap_display_names`,
or only on those noticed so far? If incomplete, T4 commit 4's filter is
necessary but not sufficient, and a cross-check against the rollup sheets'
rolled-pair columns is the stronger test. **Read-only in that repo - report the
obligation, do not edit it.**

### T11 - relaunch the fleet run. AFTER T1

Only after T1's single-economy check passes. Reset `RUN_OUTPUT_LABEL` first.
Poll no more than every 10 minutes. **Commit nothing but docs and new tests
while it runs.**

## Suggested order

1. **T1** ([17]) - agreed next task.
2. ~~**T7's guard** on `PARALLEL_ECONOMY_WORKERS`~~ - DONE, live hazard removed.
3. **T2** remaining characterization tests - unblocks T3 safely.
4. **T6 G1**, then **T6 G2** once T1 lands.
5. **T4** commits 1-3, 5 (safe anytime; can interleave with anything above).
6. **T3** state injection, then re-decide D4.3.
7. **T5** whenever convenient - fully self-contained.
8. **T8** fixtures when the proxy next matters.
9. **T7** proper, after T3.
10. **T9** incrementally; **T10** whenever the mapping owner is available;
    **T11** after T1.

## Decisions still needed from the user

| Ref | Question | Recommendation |
|---|---|---|
| D3.3 | Retire `master_config.xlsx` / `leap_mappings.xlsx` from `config/`? | Move to `config/legacy/`, do not delete yet |
| D3.4 | Who owns rollup-rule reading? | Frozen column contract + test in this repo |
| D3.5 | Equivalence tolerance | Key sets exactly equal; totals within 1e-6 relative |
| D4.3 | Split `supply_results_saver.py`? | Defer until after B2/B3, then re-measure |
| D4.5 | Keep the <500 LOC orchestrator target? | Drop it - LOC was never the defect |
| D5A.1 | Manifest vs wider convergence CSV | Manifest |
| D5B.3 | Contributions: separate sheet or sidecar? | Separate sheet in the same workbook |
| D5B.4 | Must contributions reconcile to the aggregate? | Yes, asserted by test |
| D5C.2 | Worker-count default | 1, opt-in, from measured RSS |
| T10 | Is `IS_LEAP_ROLLUP_NAME` complete? | Mapping owner to answer |

None of these block T1.
