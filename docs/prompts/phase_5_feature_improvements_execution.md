# Phase 5 - feature improvements: execution plan

Type: implementation brief. Status: active, scoped 2026-07-21.

## Short version

Phase 5 is three **independently shippable** features that share nothing but a
prerequisite. Do not treat them as one workstream.

| Feature | Ships alone? | Blocked by |
|---|---|---|
| **5A** Convergence diagnostics and run history | yes - largely built, needs fingerprints + retention | nothing |
| **5B** Aggregated demand output improvements | yes | needs a modelling decision on output shape |
| **5C** Per-economy parallelism | **no** | Phase 4 B2/B3 (shared mutable globals) |

5A and 5B can start now. 5C must not start before Phase 4 removes the
module-global state mirroring, and even then its scope is *workbook-mode*
parallelism only - see the LEAP API section, which is the part most likely to
be over-promised.

## 5A - convergence diagnostics and run history

### Current state (already built)

More exists than `AGENTS.md` implies. Measured 2026-07-21:

- `codebase/supply_reconciliation_history.py` (583 LOC) owns
  `CONVERGENCE_CSV_COLUMNS` (with `run_id` first), `load_convergence_csv`
  (inserts blank `run_id` for legacy files), `_latest_convergence_run_id`,
  `rollback_last_capacity_unmet_pass`, `trim_capacity_unmet_pass_deltas`,
  `trim_convergence_csv_to_pass`, `remove_convergence_run`,
  `clear_convergence_csv`, `_build_results_signature`, and the capacity-unmet
  state read/write pair.
- `codebase/functions/capacity_unmet_convergence_diagnostics.py` (385 LOC)
  provides `build_capacity_unmet_run_diagnostics()` (per-fuel start/end gap,
  allocation split by lever, unresolved flag; writes
  `capacity_unmet_run_diagnostics_<run_id>.csv`) and
  `compare_capacity_unmet_runs()` (latest-two comparison, warns on differing
  `mode` / `iteration_run_mode`).
- Guarded by `tests/test_capacity_unmet_convergence_diagnostics.py` and
  `tests/test_convergence_csv_cleanup.py`.

### Gaps worth closing

1. **Run ids identify the run but not what it ran.** A `run_id` is a UTC
   timestamp token (`capacity_unmet_<UTC>`). Nothing in the convergence row
   records the **commit**, the **preset**, the **economy/scenario scope**, or
   the **input fingerprints** (ESTO CSV, 9th CSV, resolved export template).
   `_build_results_signature` exists but is used for pass-state comparison, not
   stamped into history. Consequence: two rows that differ can differ because
   the model changed, the data changed, or the code changed, and the CSV cannot
   distinguish them. This is the single highest-value 5A change.
   Note the timing-history convention already solves the same problem by
   encoding `{run_type}_{commit7}` in the filename - reuse that idea, do not
   invent a second one.
2. **`compare_capacity_unmet_runs()` is latest-two only.** Comparing a run
   against a named earlier run is the operation a modeller actually wants after
   a deliberate revert.
3. **No retention policy.** The convergence CSV grows unbounded across the full
   21-economy fleet; removal helpers exist but nothing prunes. Deletion is
   destructive and must be opt-in.
4. **Fingerprint drift mid-run is undetected.** The presets scoped review
   already asks for this ([15] item 4, design goal 4): if a data or template
   fingerprint changes while a run is in flight, the result should be flagged
   invalid rather than certified.

### Decisions needed

| # | Decision | Recommendation |
|---|---|---|
| D5A.1 | Add fingerprint columns to `capacity_unmet_convergence.csv`, or write a sibling run-manifest file keyed by `run_id`? | **Sibling manifest.** Widening the CSV changes a schema that existing history and `load_convergence_csv` depend on; a manifest is additive and cannot break old readers |
| D5A.2 | What is fingerprinted? | commit7, preset name, economies, scenarios, pass mode, and `(size, mtime_ns)` of the ESTO CSV, 9th CSV, and each resolved export template - reuse `workflow_utils._csv_source_signature`'s convention |
| D5A.3 | Retention default | **Never auto-delete.** Provide `prune_convergence_history(keep_runs=N, dry_run=True)` defaulting to dry-run |
| D5A.4 | Does a mid-run fingerprint change raise, or warn-and-flag? | Warn and mark the manifest `certified=False`; raising mid-fleet-run would destroy hours of work |

### Commits

1. `codex: record a run manifest beside convergence history` - manifest writer
   + test; no change to the CSV.
2. `codex: compare capacity-unmet runs by explicit run id` - extend
   `compare_capacity_unmet_runs(run_id_a=, run_id_b=)`, keep latest-two default.
3. `codex: add opt-in convergence history pruning` - dry-run default.
4. `codex: flag runs whose inputs changed mid-run` - D5A.4.

### Tests and acceptance

- A legacy convergence CSV (no `run_id`) still loads and still compares.
- Manifest round-trips; a changed source signature is detected.
- Pruning with `dry_run=True` writes nothing and reports exactly what it would
  remove; `keep_runs` never removes the latest run.
- Acceptance: given two run ids, a modeller can answer "did the model change or
  did the inputs change?" from artifacts alone.

### Safe now?

**Yes, all of 5A** - it touches `supply_reconciliation_history.py` and the
diagnostics module, neither of which is edited by the fleet run. Do not delete
or prune any history file while the run is live.

## 5B - aggregated demand output improvements

### Current state

`codebase/aggregated_demand_workflow.py` (1,846 LOC) writes
`Demand\All demand aggregated` and, separately, a detailed-demand zeroing
workbook. Measured:

- `DEFAULT_EXPORT_FILENAME_TEMPLATE = "aggregated_demand_{economy}_{scenario}.xlsx"`
  - **no encoding of which demand branches are included**, which is the whole
  point of improvement 1.
- `_SECTOR_SHORT_CODES` (`:283`) already maps sector codes to short tokens
  (`IND`, `TR`, `OTH`, `MFG`, ...) and `:324` already consumes them - so the
  vocabulary for filename IDs exists and must be reused, not re-invented.
- Exclusion semantics that must be preserved:
  `DEMAND_SHARE_VARIABLES` (never zeroed - LEAP enforces shares summing to
  100), `DEMAND_AGGREGATED_BRANCH_PREFIX`,
  `DEMAND_OTHER_LOSS_OWN_USE_BRANCH_PREFIX`, `OWN_USE_SECTORS`,
  `TD_LOSSES_SECTORS`, `TD_LOSSES_EXCLUDE_FUEL`.
- Cache: the workflow uses **selective-column** reads of the 9th CSV via
  `workflow_utils.load_ninth_outlook_csv(usecols=...)`, which has its own cache
  entry keyed by `(path, usecols)`. `docs/work_queue.md` [15] and the
  aggregated-demand scoped review both record that this is deliberate and must
  not be swapped for a full-frame cache without measurement.

### The three sub-features, separately shippable

**5B.1 Per-sector filename IDs.** Encode the included-branch subset in the
filename using `_SECTOR_SHORT_CODES`. Output-contract change: downstream
consumers must be checked. Known consumers to verify before changing the
default: `patch_baseline_seeds` (`aggregated_demand` module),
`supply_results_saver.build_aggregated_demand_workbooks_for_results_supply`,
and any notebook/manual step in the guide. **Recommendation: add the ID as an
opt-in template, keep the current default filename, until every consumer is
confirmed.**

**5B.2 Pre-generate all unique subset combinations.** The combinatorial space
is large; generating all subsets blindly is wrong. Restrict to subsets the
modeller can actually select - i.e. one file per "sector becomes ready for
replacement" step, which is a linear sequence, not a power set. This needs a
modelling decision (D5B.2) before implementation.

**5B.3 Record individual branch contributions inside the aggregate file.** The
most useful of the three and the least risky: it adds a supporting sheet or
sidecar rather than changing the LEAP-imported sheet. **Constraint: the LEAP
import sheet must not gain rows or columns**, or the seed changes. Put
contributions on a clearly separate sheet, and keep `AGENTS.md`'s output
clarity rule in mind (primary outputs narrow; detail in `extra_detail`).

### Decisions needed

| # | Decision | Recommendation |
|---|---|---|
| D5B.1 | Change the default filename, or add opt-in IDs? | **Opt-in first**, flip the default only after consumers are confirmed |
| D5B.2 | What subset family is generated in 5B.2? | Ask the modeller. Propose: the linear "sectors migrated so far" sequence, not the power set |
| D5B.3 | Contributions on a separate sheet or a sidecar CSV? | **Separate sheet** in the same workbook - the modeller's stated need is to subtract without another file |
| D5B.4 | Do contributions need to reconcile exactly to the aggregate? | Yes, and assert it in a test - a contribution table that does not sum to the aggregate is worse than none |

### Cache memory measurement (required before any loader change)

Do not change loader behaviour without these numbers, recorded in the
aggregated-demand scoped review:

- cold and warm wall-clock for one economy and for the 21-economy fleet;
- peak RSS with the selective cache vs a full-frame cache;
- the exact `usecols` sets requested across a full run (how many distinct cache
  entries exist, and their combined footprint - N selective frames can exceed
  one full frame);
- invalidation behaviour after a source refresh.

The 9th CSV is ~275 MB; under 5C this multiplies by worker count. Measure
before, not after.

### Tests and acceptance

- Tiny ESTO/9th fixtures: sector inclusion, own-use/T&D exclusion, base-year to
  projection transition.
- Share variables are never zeroed; aggregate branches are never zeroed.
- Contributions sum to the aggregate per economy/scenario/fuel/year (D5B.4).
- Filename IDs are stable and reversible (ID -> subset round-trip).
- Real-run: one economy, before/after, aggregate totals and LEAP branch keys
  identical while the LEAP import sheet is unchanged.

### Safe now?

**Yes for measurement, fixtures and 5B.3 design.** No, for changing the default
filename or the emitted workbook while the fleet run is producing seeds from
this workflow.

## 5C - per-economy parallelism

### The claim to check first

`AGENTS.md` says "the scripts are independent per economy and can run in
parallel with minimal changes." **That is not currently true**, and the reason
is Phase 4's finding: the reconciliation modules share mutable module-level
state (`_sync_extracted_runtime_state`, `_sync_results_saver_overrides`,
run-scoped `OUTPUT_DIR` / `RUN_OUTPUT_LABEL` / `CAPACITY_UNMET_STATE_PATH`
rebound at runtime). Two economies in one interpreter would interleave those
globals. **Threads are unsafe; this is not a tuning question.**

### A parallel path already exists, and it is the unsafe kind

Found 2026-07-21, after this brief was first written:
`supply_reconciliation_config.PARALLEL_ECONOMY_WORKERS: int = 0` is consumed at
`supply_results_saver.py:3526`, which - when the value exceeds 1 - runs
per-economy export generation under a **`concurrent.futures.ThreadPoolExecutor`**
(`:3529`), sharing one interpreter and therefore one copy of every mirrored
module global. It aggregates per-economy exceptions into
`_economy_export_errors` and continues, which is the right failure policy
(matches D5C.4).

**The only thing preventing harm today is that the default is 0.** Treat this
as live risk, not as a head start:

- **Do not raise `PARALLEL_ECONOMY_WORKERS` above 1 before Phase 4 B2/B3.**
  Worth an explicit guard: refuse values > 1 with a message pointing at [17]
  and this brief, rather than leaving a foot-gun switched off by convention.
- The `_run_one_economy` / `_collect_economy_result` decomposition it already
  has is genuinely useful and should be **kept** - it is the natural worker
  boundary for a process pool. Reuse it; convert the executor, do not rewrite
  the seam.
- Whether threads are safe for the *export generation* step specifically, as
  opposed to a whole run, deserves its own measurement rather than assumption:
  the answer depends on whether `_run_one_economy` touches any mirrored global.
  Determine that before deciding whether the existing thread path can simply be
  deleted or must be preserved behind the same guard.

### Process isolation

- Use processes, one economy per process, `spawn` start method (Windows has no
  `fork`; do not write code that only works under `fork`).
- Each worker re-imports the workflow and constructs its own run context, so
  the parent must pass **explicit** economy, scenario, preset and output label -
  never rely on inherited globals.
- Prerequisite: Phase 4 commits B2 and B3. The acceptance test for those
  ("two run contexts in one interpreter without interference") is exactly the
  precondition 5C needs.

### Output-directory collisions - the concrete list

Per-economy outputs are already separated, but these are **shared** and will
collide:

| Shared artifact | Collision | Mitigation |
|---|---|---|
| `capacity_unmet_convergence.csv` (single append-target) | interleaved/lost appends | write per-worker CSVs, merge in the parent at the end |
| capacity-unmet state JSON (`CAPACITY_UNMET_STATE_PATH`) | last-writer-wins | key by economy, or keep per-worker and merge |
| `supporting_files/runtime/` timing CSV + `history/` | concurrent writes, and `load_history_summary` averaging partial runs | per-worker file, parent merge; do not let workers write history |
| `archive_config_dir_once_per_day` | N processes racing the same archive | do it once in the parent before fan-out |
| single-file combine (`supply_results_saver`) and cross-economy verification artifacts | inherently cross-economy | parent-only, after all workers finish |
| `economy_locks/` | none - this is the mitigation | see below |

`codebase/utilities/economy_run_lock.py` already provides exactly the right
primitive: cross-process, file-based, PID-aware, with a Windows-correct
liveness probe (`OpenProcess`, because `os.kill(pid, 0)` is not valid on
Windows). It is already used by `supply_reconciliation_workflow.py:1080` and
`patch_baseline_seeds.py:1088`. **Build 5C on it; do not write a second lock.**

### Cache safety

`workflow_utils._csv_cache` is a plain module-level dict, so under `spawn` each
worker gets its own - correct, but **memory multiplies**. The 9th CSV alone is
~275 MB before selective-column narrowing. Before choosing a worker count:
measure peak RSS per worker (5B's measurement covers this) and pick N from
measured headroom, not from CPU count. Do not add a shared-memory cache; a
read-only frame shared across processes is a large project with its own
correctness risks and no evidence it is needed.

### LEAP / API limitations - do not over-promise

- The LEAP COM API is **decommissioned in this repo**, structurally: guards
  were decoupled and toggles default False, locked by
  `tests/test_leap_api_decommissioned.py` (`work_queue.md`, "Landed
  2026-07-16"). Runs are workbook-mode.
- Therefore **5C parallelises workbook production only.** Do not write, plan,
  or document parallel LEAP API writes. LEAP is a single-instance desktop
  application driven over COM against one area at a time; there is no evidence
  it is safe to drive concurrently, and this brief does not assert that it is.
- If the API is ever re-enabled, `work_queue.md` [6] (`leap_core`
  share-normalization divergence) must be converged **first**, and parallel API
  use would need its own separate evidence.
- The LEAP *import* step therefore stays serial and parent-side.

### Failure aggregation

`workflow_common` deferred errors (`THROW_ERROR_AFTER_RUN`,
`get_deferred_errors`, `raise_deferred_errors`) are module-global per process.
Under 5C each worker collects its own, and the parent must merge them,
preserving the current end-of-run behaviour: **every failure surfaces, nothing
is silently dropped, one exception is raised at the end** (see
`_run_with_config_locked`'s combined preflight + deferred-error raise). A
worker that dies without reporting (segfault, OOM, killed) must be reported as
a failure by the parent, not treated as success - non-zero exit or missing
result sentinel both count.

### Reproducibility

- Row order in any merged CSV must be deterministic: merge by sorting on
  (economy, scenario, pass, ...) in the parent, never by arrival order.
- `run_id` should be minted **once in the parent** and shared by all workers,
  so one fleet run is one run id (this is also what makes 5A's manifest
  meaningful).
- A serial run and a parallel run over the same economies must produce
  identical seeds. That is the acceptance test.

### Decisions needed

| # | Decision | Recommendation |
|---|---|---|
| D5C.1 | Worker pool mechanism | `concurrent.futures.ProcessPoolExecutor` with `spawn`; avoid a bespoke process manager |
| D5C.2 | Worker count default | **1 (serial) by default**, opt-in `N` from measured RSS headroom. Never default to CPU count on a machine that also runs LEAP |
| D5C.3 | Shared-artifact strategy | per-worker files + deterministic parent merge, for every row in the collision table |
| D5C.4 | Does a single worker failure abort the fleet? | **No** - continue, aggregate, raise once at the end, matching current deferred-error behaviour |
| D5C.5 | Is `run_id` minted per fleet or per economy? | per fleet, in the parent |

### Commits (only after Phase 4 B2/B3)

1. `codex: make reconciliation run context constructible per economy` (may be
   Phase 4's final commit rather than 5C's first).
2. `codex: write convergence and timing artifacts per worker`.
3. `codex: add deterministic parent-side artifact merge`.
4. `codex: add opt-in per-economy process pool` - default 1.
5. `codex: aggregate worker failures without dropping any`.

### Tests and acceptance

- Two-economy parallel run vs the same two economies serially: **identical
  seeds** (branch key sets, row counts, values), identical merged convergence
  rows after sorting.
- A worker forced to fail: fleet completes, failure appears in the aggregated
  report, exit is non-zero.
- A worker killed abruptly: reported as failure, not success.
- Locks: a second fleet run over an overlapping economy set is refused.
- No test may require LEAP.
- Acceptance: measured wall-clock improvement on a real multi-economy run, with
  peak RSS recorded, **and** seed-identity evidence. Speed without identity is
  not acceptance.

### Safe now?

**No.** 5C must not be implemented while the fleet run is live (it changes the
run's own machinery) and must not start before Phase 4 B2/B3. Design work,
measurement, and the collision inventory are safe now.

## Cross-cutting safety boundaries

- Do not change modelling behaviour anywhere in Phase 5. These are output,
  diagnostics, and execution-topology features.
- Seed contents must not change. Every feature here has an "identical seed"
  acceptance test for that reason.
- Preset semantics, output paths (other than 5B's opt-in filename), log lines,
  and existing run history remain contracts (see the Phase 4 brief).
- Never auto-delete run history.
- Do not touch `supply_reconciliation_workflow.py` while the fleet run holds
  it.

## Documentation to update on completion

- `AGENTS.md` Phase 5 section - in particular remove "can run in parallel with
  minimal changes", which is not supported by the current code.
- `docs/supply_reconciliation_workflow_guide.md` - the convergence/run-history
  section (extend with the manifest), the "All demand aggregated output
  improvements" section, and a new parallelism section describing the
  workbook-mode-only scope.
- `docs/prompts/aggregated_demand_scoped_review.md` - record the cache
  measurements and D5B answers.
- `docs/work_queue.md` roadmap entry [16].
- `AGENTS.md` "Workflow Timing History" - if per-worker timing files change how
  history is written or averaged.
