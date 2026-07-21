# Phase 4 - monolith decomposition: execution plan

Type: implementation brief. Status: active, re-scoped 2026-07-21.

## Short version

`AGENTS.md` describes Phase 4 as splitting a 13,628-LOC
`supply_reconciliation_workflow.py` into four modules, and rewriting a
2,923-LOC own-use proxy. **Both premises are stale.** The four-way split has
already happened (the file is 1,253 LOC and the extracted modules exist), and
the own-use proxy has already been decomposed to 1,770 LOC over a 2,343-LOC
utils module.

What is actually left is the part the split deferred: it was performed as a
**textual extraction with a shared-mutable-global backchannel**, not as an
interface split. Phase 4's real job is to retire that backchannel, and to deal
with the module that quietly became the new largest orchestrator -
`codebase/functions/supply_results_saver.py` (4,024 LOC). This is also the
hard prerequisite for Phase 5 parallelism.

## Current-state evidence

### The split already landed

Measured 2026-07-21 (`wc -l`):

| Module | LOC | Notes |
|---|---|---|
| `codebase/supply_reconciliation_workflow.py` | 1,253 | orchestrator + notebook preset block |
| `codebase/supply_reconciliation_config.py` | 1,121 | sentinels, caps, paths - the AGENTS.md target, delivered |
| `codebase/supply_reconciliation_allocation.py` | 1,799 | capacity-unmet algorithm - delivered |
| `codebase/supply_reconciliation_history.py` | 583 | run history / convergence - delivered |
| `codebase/supply_reconciliation_balance_tables.py` | 1,670 | not in the AGENTS.md plan; exists |
| `codebase/supply_reconciliation_results.py` | 417 | not in the plan; exists |
| `codebase/supply_reconciliation_utils.py` | 188 | not in the plan; exists |
| **`codebase/functions/supply_results_saver.py`** | **4,024** | **the actual remaining monolith** |

`supply_reconciliation_workflow.py:340` labels its own compatibility shims
"Backwards-compatible wrappers for names extracted during the Phase 4 split",
so the split is self-documented as done.

### The defect the split left behind

Three mechanisms keep the extracted modules coupled through module globals:

1. **Star re-export.** `supply_reconciliation_workflow.py:65` does
   `from codebase.supply_reconciliation_config import *`, explicitly so that
   "call sites in this file remain unchanged". The same star import appears in
   `allocation`, `history`, `results` and `balance_tables`. Every module
   therefore holds its *own copy* of every config constant.

2. **Manual global mirroring.** Because those are copies, the workflow has to
   push mutations outward by hand:
   - `_sync_extracted_runtime_state()` (`:353`) copies 4 runtime accumulators
     and 5 config names onto `_srt`, `_sra`, `_srh`, `_srs`;
   - `_sync_results_saver_overrides()` (`:381`) forwards a hand-maintained list
     of **~30 names** - functions *and* config flags *and* output paths - onto
     `supply_results_saver`;
   - `_refresh_extracted_runtime_state()` (`:428`) copies the accumulators back.

3. **Mutable run-scoped globals.** `RUN_OUTPUT_LABEL`, `OUTPUT_DIR`,
   `RESULTS_RUNTIME_DIR`, `CAPACITY_UNMET_STATE_PATH` and the pass mode are
   rebound at runtime by `_refresh_output_paths_for_current_pass_mode()`
   (`:562`) and then re-mirrored.

Consequences that matter, in order:

- **Correctness is maintained by a list.** Any newly extracted name that is not
  added to the ~30-name list is silently not forwarded. This is the same shape
  of failure as the `073c489` routing bypass recorded in `work_queue.md` [7]
  (fix landed, production no-op for a day, tests green throughout).
- **The process is the unit of isolation.** Two economies cannot run in the
  same interpreter with different output labels. This is the concrete reason
  Phase 5 parallelism must be process-based, not thread-based.
- **Tests monkeypatch the wrapper**, and the sync functions exist to make that
  work, so the coupling is load-bearing for the current test suite. It cannot
  simply be deleted.

### The own-use proxy is already decomposed

`other_loss_own_use_proxy_workflow.py` is 1,770 LOC (not 2,923) with a clear
internal structure: a config block (`PROXY_CONFIG` from `:333`, built by
`make_proxy_config` at `:260`), a loader layer (`:739-876`), a calculation
layer (`:894-1311`), an assembly layer (`assemble_proxy_workbook`, `:1360`),
and a notebook block (`:1721`). 54 helpers already live in
`codebase/functions/other_loss_own_use_proxy_utils.py` (2,343 LOC).
The "rewrite from scratch" recommendation in `AGENTS.md` was written against
the pre-decomposition file and should be retired.

## Dependencies and blockers

- **Hard blocker while the fleet run is active:** the working tree carries a
  temporary `RUN_OUTPUT_LABEL` in `supply_reconciliation_workflow.py:859`.
  Nothing in this phase may edit that file until the run completes and the
  label is restored to `"auto"`. Every stage below is ordered accordingly.
- `docs/work_queue.md` [15] item 4
  (`supply_reconciliation_presets_scoped_review.md`) owns the preset model.
  Phase 4 must not change preset values; it may only change *where they live*
  after that review reports.
- The own-use proxy work is governed by
  `docs/prompts/other_loss_own_use_proxy_scoped_review.md`. Phase 4 supplies
  the decision framework (below); the scoped review supplies the inventory.
- `tests/test_baseline_seed_writer_validation.py` has 3 known intentional
  failures (`BASELINE_SEED_VALIDATION_BLOCKING_FINDINGS_ARE_WARNINGS = True`).
  Do not read them as regressions; do not "fix" them here.

## Extraction boundaries, derived from dependencies not line counts

Ranked by coupling, highest value first:

**B1 - the config surface (highest value, lowest risk).**
The star imports mean nobody can tell which of the ~1,121 LOC of config each
module actually uses. Measure it: for each of the five star-importing modules,
enumerate the config names it actually references. Expect a small fraction.
That measurement *is* the interface.

**B2 - the runtime accumulators.**
`_CAPACITY_UNMET_RUNTIME_{CAPACITY_ADDITIONS,PRIMARY_ADDITIONS,EXPORT_ADJUSTMENTS,PASS_SUMMARY}`
are four mutable dicts shared by mirroring. They are one cohesive object: a
per-run allocation ledger. This is the single highest-leverage extraction -
turning them into one explicitly-passed object removes the need for
`_sync_extracted_runtime_state` and `_refresh_extracted_runtime_state`
entirely, and directly unblocks Phase 5.

**B3 - run-scoped paths.**
`OUTPUT_DIR`, `RESULTS_RUNTIME_DIR`, `RESULTS_CHECKS_DIR`,
`RESULTS_SINGLE_FILE_ARCHIVE_DIR`, `CAPACITY_UNMET_STATE_PATH`,
`RUN_OUTPUT_LABEL` and the pass mode form a second cohesive object: a run
context. Same treatment, same payoff.

**B4 - `supply_results_saver.py` (4,024 LOC).**
It receives ~20 of the ~30 forwarded names, i.e. it is the module most tightly
bound to workflow globals. Do not attempt to split it before B2 and B3 land -
its size is a symptom of the injection style, and splitting it first would
multiply the number of modules needing mirrored state.

**B5 - the notebook preset block.** Owned by [15] item 4, not by this phase.

## Decisions needed before implementation

| # | Decision | Options | Recommendation |
|---|---|---|---|
| D4.1 | Injection style for B2/B3 | (a) explicit parameter object passed down; (b) a single shared `RunContext` module-level singleton; (c) keep mirroring, add a test that the ~30-name list is complete | **(a)**, staged behind (c). (c) is a cheap immediate safety net; (b) reproduces the current defect with better naming |
| D4.2 | Retire the star imports? | yes, per module, after B1 measurement / no | Yes, but **only after** the measurement, and one module per commit |
| D4.3 | Is `supply_results_saver.py` split in this phase or deferred? | split now / defer to a follow-on | **Defer.** Land B2+B3 first, re-measure, then decide with real coupling numbers |
| D4.4 | Own-use proxy: incremental or rewrite? | see framework below | **Incremental.** The rewrite premise was retired by the decomposition that already happened |
| D4.5 | Target LOC for the orchestrator | keep AGENTS.md's <500 / drop the target | **Drop the numeric target.** 1,253 LOC is mostly the preset block and the log/preflight orchestration, both of which are contracts. LOC is not the defect; shared mutable state is |

### D4.4 decision framework (own-use proxy: incremental vs rewrite)

Rewrite only if **all four** hold. Measure, do not estimate:

1. **No usable seam.** The module cannot be cut into loader / calculation /
   assembly layers without a change to the output workbook.
   *Measured: false.* Those three layers already exist as contiguous regions.
2. **Output contract is fully characterized.** Fixtures cover every enabled
   `PROXY_CONFIG` process and every fallback path in the scoped review's
   deliverable 2. *Measured: not yet true* - so a rewrite today has no oracle
   to be checked against, which is the strongest argument against it.
3. **The existing logic is not the specification.** If `PROXY_CONFIG` and the
   fallback ladder *are* the model specification (the scoped review says treat
   them as such), a rewrite must reproduce them exactly, so it buys nothing.
   *Measured: they are the specification.*
4. **Incremental extraction would cost more than one rewrite.** With 54 helpers
   already extracted, marginal extraction cost is low.

Conclusion: **incremental**, and it is gated behind characterization tests, not
behind Phase 4 sequencing. Record this in the scoped review when it reports.

## Characterization tests - before any code moves

Nothing in the staged sequence may start until these exist. They are cheap,
safe during the fleet run, and are the only thing that makes the later commits
revertible with confidence.

1. **Forwarding completeness test.** Assert that every name in
   `_sync_results_saver_overrides`'s list exists on both the wrapper and the
   target module, and - the part that catches the real bug - that no
   config/flag name read by `supply_results_saver` at module scope is absent
   from the list. This is the immediate safety net (D4.1 option (c)) and should
   land first regardless of anything else.
2. **Config-surface snapshot.** For each star-importing module, snapshot the
   set of config names it references (B1 measurement), committed as a test
   fixture so an accidental widening is visible.
3. **Run-context snapshot.** For each preset, assert the resolved
   `OUTPUT_DIR`, `RESULTS_RUNTIME_DIR`, `CAPACITY_UNMET_STATE_PATH`, pass mode
   and run-label behaviour. Presets are contracts (see [15] item 4).
4. **Convergence CSV schema test.** Pin `CONVERGENCE_CSV_COLUMNS` and the
   legacy-file behaviour (`load_convergence_csv` inserts a blank `run_id` for
   files that predate it). Existing history must stay readable.
5. **Public-callable smoke tests.** `run_with_config()`,
   `run_results_linked_transformation_supply_workflow()`,
   `run_results_linked_supply_workflow()`, `build_supply_overrides()` and the
   `patch_baseline_seeds` entry keep their signatures and remain importable
   from `codebase.supply_reconciliation_workflow`.

## Staged sequence of small commits

*(1-3 are safe during the fleet run; 4 onward are not - see the table at the
end.)*

1. **`codex: test forwarding completeness of workflow overrides`**
   Characterization test 1. No production code change.
2. **`codex: snapshot the reconciliation config surface`**
   Characterization tests 2-4. Records the B1 measurement in this file.
3. **`codex: characterize reconciliation public callables`**
   Characterization test 5.
4. **`codex: introduce an explicit capacity-unmet allocation ledger`**
   B2. Introduce the ledger object; have the four globals become views onto it
   so the existing mirroring still works; no call-site change yet.
5. **`codex: pass the allocation ledger explicitly through the pass functions`**
   B2 completion. `_run_capacity_unmet_iterative_pass` and
   `_run_capacity_unmet_iterative_balanced_pass` take and return the ledger.
   Delete `_refresh_extracted_runtime_state` once nothing reads the mirrors.
6. **`codex: introduce a run context for reconciliation output paths`**
   B3, same two-step pattern (introduce, then thread, then delete the mirror).
7. **`codex: replace star imports in <module>`** - one commit per module,
   guided by the commit-2 measurement.
8. **Re-measure and re-decide D4.3** before touching `supply_results_saver.py`.

## Safety boundaries - what must not change

These are contracts, not implementation details:

- **Public callables and notebook-first use.** `run_with_config()` stays the
  entry point; the `#%%` cell structure and the editable preset block stay
  where a modeller expects them; module remains importable with arbitrary CWD
  (`REPO_ROOT` + `_resolve()` pattern, per `AGENTS.md`).
- **Preset semantics.** `_PRESET_BASELINE_SEED`, `_PRESET_RESULTS_UPDATE`,
  `_PRESET_PATCH_BASELINE_SEEDS` resolve to exactly the same effective
  configuration. Phase 4 may relocate, never re-value.
- **Output paths and filenames**, including `RUN_OUTPUT_LABEL` semantics
  (`"auto"` vs an explicit label) and the per-pass-mode directory refresh.
- **Log output.** `_workflow_log_path()`, the `_TeeWriter` behaviour, and the
  `[INFO] run_with_config toggles: ...` line are read by humans and by run
  review prompts. Keep the toggle line's key names.
- **Existing run history.** `capacity_unmet_convergence.csv` and the
  capacity-unmet state JSON must stay readable, including legacy rows without
  `run_id`. Timing history filenames
  (`workflow_stage_timings_..._{run_type}_{commit7}.csv`) must keep parsing in
  `load_history_summary`.
- **The transformation patch gate stays.** `work_queue.md` [1] is settled:
  the harness returned DEFECT. Do not remove `auto_sector_keys` or the
  `NotImplementedError` gate as "cleanup".
- **Economy run locks.** `economy_run_locks` wraps the run; do not move the
  lock boundary inward or outward.
- **Per-economy template routing.** Never reintroduce a pinned
  `id_lookup_path` default (`work_queue.md` [7]; guarded by
  `tests/test_standalone_export_id_lookup_routing.py`).

## Real-run equivalence evidence

Unit tests cannot prove this phase safe. Required before declaring it done:

1. **One-economy post-boundary seed comparison.** Run `_PRESET_BASELINE_SEED`
   for one real-template economy (`01_AUS` or `12_NZ`) before and after the
   staged commits. Compare **post-boundary on both sides** (recorded trap: never
   diff raw export output against a finished seed). Require: identical branch
   path key set, identical row count, values equal within 1e-9 relative.
2. **Preset resolution diff.** The commit-3 snapshot must be byte-identical
   before and after.
3. **Log diff.** The `[INFO] run_with_config toggles:` line identical.
4. **History continuity.** A convergence CSV written before the change is still
   readable, and a new run appends without schema change.

## Acceptance criteria

- `_sync_extracted_runtime_state`, `_refresh_extracted_runtime_state` and the
  ~30-name forwarding list are gone, or - if D4.1 lands only the safety net -
  fully covered by a test that fails when a name is missed.
- No module-level mutable state is shared between the reconciliation modules by
  mirroring.
- Two different run contexts can be constructed in one interpreter without
  interfering (the Phase 5 precondition, testable without running LEAP).
- All contracts above unchanged; equivalence evidence recorded.
- D4.1-D4.5 answered in writing here.

## Rollback

Commits 1-3 are test-only. Commits 4-7 are each a single seam and each keeps
the previous mechanism working until its final step, so `git revert` of one
commit restores a consistent state. If a seed diff appears, revert to the last
commit that passed the one-economy comparison and re-measure before
investigating - do not attempt a forward fix on a diverged seed.

## Documentation to update on completion

- `AGENTS.md` - the Phase 4 section and the LOC table in "Current state (from
  codebase review, June 2026)" are both stale and must be rewritten from
  measurement, not edited in place.
- `docs/supply_reconciliation_workflow_guide.md` "Planned improvements" - it
  already records the split as complete (~637 LOC, now 1,253); correct the
  figure and add the state-injection outcome.
- `docs/work_queue.md` roadmap entry [16].
- `docs/prompts/other_loss_own_use_proxy_scoped_review.md` - record the D4.4
  outcome (incremental, with the four-test rationale).
- `docs/check_registry.md` if any check moves module.

## Safe now vs must wait

| Safe while the fleet run continues | Must wait for the run to finish and the label to be restored |
|---|---|
| Commits 1-3 (tests only; they import the module but do not edit it) | Commits 4-8 (all touch `supply_reconciliation_workflow.py` or its imports) |
| B1 config-surface measurement | Any one-economy equivalence run |
| Own-use proxy characterization fixtures (separate files) | Own-use proxy extraction commits |
| Answering D4.1-D4.5 | - |

Note: importing `codebase.supply_reconciliation_workflow` in a test while the
fleet run is live is safe (no shared writable state at import), but **do not
call `run_with_config()`** - it acquires economy run locks and would contend
with the live run.
