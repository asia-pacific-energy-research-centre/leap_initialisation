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

1. Finish Phase 4 T2 characterization coverage: config-surface snapshot,
   run-context snapshot, convergence schema/legacy compatibility, and public
   callable smoke tests. The initial forwarding-characterisation checkpoint is
   already complete.
2. Phase 5 demand safeguards: G1 must route the seed-patch path through
   active-branch resolution; G2 must ensure demand-zeroing excludes active
   detailed sectors. G2 becomes mandatory before the first detailed demand
   sector handover.
3. Phase 3 canonical mapping hardening: schema and rollup contracts, retirement
   of the obsolete name-consolidation path, canonical ownership, and deferred
   equivalence evidence. Mapping decisions still owned by `leap_mappings`
   require its owner where the briefs say so.
4. Phase 5A convergence history: additive per-run manifests and fingerprints,
   explicit run-id comparison, opt-in dry-run retention, and input-change
   certification. Never auto-delete history.
5. Phase 4 B2/B3 explicit injection: replace shared mutable allocation and
   run-path globals, then remove star imports one module at a time. Re-measure
   `supply_results_saver` coupling before deciding any further split.
6. Own-use proxy assurance: add fixtures for the five currently untested
   enabled processes. This is a coverage/model review, not a rewrite.
7. Only then design process-based per-economy parallelism: per-worker timing
   and convergence artifacts, deterministic parent merge, and an opt-in pool
   defaulting to one worker.

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
