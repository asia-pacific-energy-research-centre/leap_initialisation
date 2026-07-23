# Current execution roadmap

Status: active as of 2026-07-22. This is the operational roadmap for the
initialisation workflow. It complements the detailed thread briefs; where an
older handoff describes a prior state, this document is the current authority.

## Run policy and verification boundary

- Use a **single-economy, contiguous two-year horizon** (`BASE_YEAR` through
  `BASE_YEAR + 1`) for normal development, production iteration, and measured
  performance work. `TEST_HORIZON_BASE_YEAR_PLUS_ONE=True` is the default.
- Keep `RUN_PREFLIGHT_COMPRESSED_PROJECTION=True` for the final verification of
  an output-affecting change. It is allowed to disable that preflight during a
  deliberately limited implementation iteration, but never for the final
  verification: the preflight exercises the `00_APEC` aggregate-sentinel path.
- A full-horizon run is an explicit release/assurance or useful-output action,
  not routine iteration. Do it only after a sequence of two-year checks, for a
  representative validation set or to produce outputs that will be used.
- Do not run two economies concurrently from this working tree. Per-economy
  workflow locks exist, but `ECONOMIES` remains a source-file module literal
  that a late preflight import can re-read. Safe parallelism waits for the
  Phase 4 run-context work and per-process configuration overrides.
- Use a unique `RUN_OUTPUT_LABEL` for every retained test run; restore
  `ECONOMIES = ECONOMIES_RUN_ORDER` and `RUN_OUTPUT_LABEL = "auto"` when the
  run is over. Do not edit workflow code or configuration while a run is live.

## Completed safety foundation: [18] zeroing workbooks

The supply/transformation reset is now implemented as a separate,
template-based `supply_transformation_zeroing_{economy}.xlsx` workbook. This
replaces the unsafe workbook-mode in-memory wipe that removed values from the
main reconciliation table.

For each economy, import in this exact order into a populated LEAP area:

1. `supply_transformation_zeroing_{economy}.xlsx`
2. the generated main supply/transformation workbook

Reversing that order overwrites the generated values with zeroes. The main seed
and consolidated workbook must retain the generated values; the zeroing
workbook is the only reset artifact. The active implementation also scopes
reset masks through `RESET_SCOPE_SECTOR_TITLES` and accepts aggregate template
sentinels such as `00_APEC`.

Verification completed before adopting the mechanism:

- inert-builder run: baseline seed, consolidated workbook, and six balance
  tables matched the established `01_AUS` baseline exactly;
- enabled mechanism run: the separate zeroing workbook was emitted without
  changing those main artifacts;
- final preflight verification exercised the `00_APEC` sentinel path.

The next real populated-area import should still confirm the stated import
order in LEAP before using this mechanism for a full output delivery.

## Timing and measured optimisation loop

Workbook-generation substage timings landed in `6c76895`; use them to choose
the next optimisation rather than guessing. Timing history must be separated
by run horizon before comparing averages: record/filter `year_start`,
`year_end`, and `n_years`, retain compatibility with legacy history filenames,
and never mix two-year and full-horizon baselines.

For each optimisation:

1. Run one two-year `01_AUS` baseline with a unique label and compressed
   projection preflight enabled.
2. Rank measured substage times and choose only the dominant, evidenced cost.
3. Make one output-preserving change in its own commit.
4. Repeat the same two-year run and compare timing plus structural/output
   invariants.
5. Keep a full-horizon run for a later release/useful-output boundary, rather
   than repeating it during every implementation step.

The first likely class of work is a measured workbook I/O path (especially a
write -> reread -> merge cycle) or repeated template loading. It is not an
instruction to remove checks or add caching without a measured target.

## Remaining correctness and refactor work

Execute the detailed briefs in this order, with their tests and decision gates:

1. Phase 4 B2/B3 explicit injection is the immediate priority. B2's allocation
   ledger introduction, pass-function threading, and production export-reader
   injection are complete: the wrapper no longer mirrors allocation results
   back after a pass. The allocation module's underscored views remain only as
   a fallback for legacy direct callers and wrapper monkeypatch compatibility;
   they are not used by the normal results-saver path. B3 now starts with an
   explicit run context for output paths, output label, and pass mode. This is
   the minimum state-isolation boundary needed before parallel production runs
   are considered.
2. ✅ **Bounded process-based economy parallelism — landed and verified
   2026-07-23** (`9aab65b`). `supply_reconciliation_workflow._apply_worker_snapshot_overrides`
   reads an explicit per-process snapshot (economy, run label, test horizon)
   from `LEAP_WORKER_SNAPSHOT_JSON`, applied before the preset broadcast; a
   no-op when unset. `codebase/functions/parallel_economy_runner.py` launches
   one OS process per economy (never threads), bounded by `max_workers`
   (default 1), each with its own `run_output_label` — which reuses the
   existing `ReconciliationRunContext` path resolution to isolate every
   per-run artifact family (output dir, runtime dir, checks dir, iterative
   state, timing/convergence CSVs) without a new scoping mechanism. Verified:
   (a) sequential equivalence — one `01_AUS` two-year run through the new
   subprocess path matched the established `SEED_01_AUS_TWOYEAR_AGGSOURCE_20260722`
   baseline byte-for-byte (3,432 rows, 0 cell diffs, keyed on
   BranchID/VariableID/ScenarioID/RegionID); (b) a controlled two-economy
   concurrent smoke test (`01_AUS` + `12_NZ`, `max_workers=2`, two-year
   horizon) completed with both workers succeeding, zero cross-contamination
   (each seed's `Region` column held only its own economy), and `01_AUS`'s
   concurrent output identical (0 diffs) to its sequential run. A
   deterministic parent merge across more than one economy's outputs into a
   single consolidated artifact is **not yet built** — today each worker's
   outputs stand alone under its own label; that remains open before this is
   used for an unattended multi-economy fleet run.
3. Phase 3 canonical mapping hardening: schema and rollup contracts, retirement
   of the obsolete name-consolidation path, canonical ownership, and deferred
   equivalence evidence. Mapping decisions still owned by `leap_mappings`
   require its owner where the briefs say so.
4. Phase 5A convergence history: additive per-run manifests and fingerprints,
   explicit run-id comparison, opt-in dry-run retention, and input-change
   certification. Never auto-delete history.
5. Own-use proxy assurance: add fixtures for the five currently untested
   enabled processes. This is a coverage/model review, not a rewrite.

Completed on 2026-07-22: Phase 4 characterization coverage, G1/G2 demand
safeguards and their two-year AUS verification, the canonical mapping schema
contracts, convergence manifests, and own-use proxy fixtures. These remain
covered by their focused tests; they are not gates ahead of the parallelism
boundary above.

The authoritative detailed execution material remains:

- `docs/work_queue.md` [16] for the refactor/map backlog and [18] for the
  zeroing rationale;
- `docs/prompts/initialisation_refactor_continuation.md` for the thread
  register;
- `docs/prompts/phase_4_monolith_decomposition_execution.md` and
  `docs/prompts/phase_5_feature_improvements_execution.md` for phase gates;
- `docs/prompts/supply_reconciliation_runtime_profiling_execution.md` for the
  output-inert measurement task.

## Rollout and documentation hygiene

After the above changes have accumulated, run a deliberate full-horizon
validation for a small representative set (baseline seed, distinct
template/region routing, and a results-update economy when LEAP outputs are
available). Compare the established artifacts and confirm zeroing workbook
import order in a populated area. Then produce useful full-horizon outputs
sequentially with unique labels. Reconsider a fleet/process-parallel rollout
only after the state-injection prerequisite is complete.

When a prompt's work is implemented, tested, and committed, move that prompt
from `docs/prompts/` to `docs/archive/` with its findings/status material. Keep
historical handoffs intact as records, but do not use them as live state.
