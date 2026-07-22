# Supply reconciliation runtime profiling — execution prompt

Type: investigation and low-risk instrumentation prompt. Status: active.

## Objective

Identify why a single-economy baseline-seed run spends roughly 15 minutes in
`generate LEAP import workbooks`, then land only the measurement needed to make
the next optimisation decision. Do not optimise based on inference alone.

## Measured baseline — 2026-07-22

Two successful `01_AUS` compressed-preflight runs provide the current baseline:

| Stage | Typical duration | Share of total |
| --- | ---: | ---: |
| Generate LEAP import workbooks | 15.1–15.5 min | ~56% |
| Build transformation and supply inputs | 7.0–7.8 min | ~28% |
| Load balance-demand inputs | ~2.3 min | ~9% |
| All remaining stages | ~2.5 min | ~9% |

Timing files:

- `outputs/leap_exports/supply_reconciliation/baseline_seed/runs/SEED_01_AUS_CLEANCHECK_20260722/supporting_files/runtime/workflow_stage_timings.csv`
- `outputs/leap_exports/supply_reconciliation/baseline_seed/runs/SEED_01_AUS_ZEROING_ACTIVE_20260722/supporting_files/runtime/workflow_stage_timings.csv`

## Scope

1. Read `AGENTS.md`, especially “Running the supply reconciliation workflow”,
   before invoking anything.
2. Read `docs/work_queue.md` and
   `docs/prompts/session_handoff_20260722.md` for current run safety.
3. Trace the work inside `generate LEAP import workbooks` in
   `codebase/functions/supply_results_saver.py`.
4. Add narrow `WorkflowTimer` sub-stage timings around each real producer and
   merge/write operation in that stage. Suggested boundaries include supply,
   transformation, transfers, electricity/heat, own-use proxy, aggregated
   demand, demand zeroing, fuel-catalog construction, and per-economy workbook
   assembly. Use the actual code boundaries; do not invent empty timers.
5. Add a focused test only if the timing API or output schema changes. Existing
   workflow output must remain bit-for-bit equivalent apart from timing rows.
6. Commit the instrumentation as one small, output-inert commit.
7. Run one **single-economy** compressed-preflight profile only after the main
   agent confirms no other workflow run is active. Set a unique output label;
   do not commit temporary `ECONOMIES`, `RUN_OUTPUT_LABEL`, or preflight edits.
8. Report the ranked sub-stage timings and a specific next optimisation target.

## Explicit non-goals

- Do not run a fleet or concurrent-economy workflow.
- Do not edit `ECONOMIES` or `RUN_OUTPUT_LABEL` while another workflow process
  is live. `supply_preflight` can late-import the edited source.
- Do not optimise, refactor, add caching, alter output files, or remove checks
  in this task. This is measurement first.
- Do not touch the active supply/transformation zeroing work unless explicitly
  asked; it is being verified independently.

## Likely follow-up options — decide only after evidence

1. Cache repeated LEAP-template reads, keyed by file signature with an explicit
   notebook cache-clear function.
2. Stop writing intermediate XLSX files that are immediately reread and merged;
   retain only the required human-facing artifacts and merge dataframes in
   memory.
3. Introduce an explicitly labelled iteration mode that suppresses only
   non-gating diagnostics. The final verification must always retain full
   preflight/import-readiness checks.
4. Pursue economy-level process parallelism only after per-process config
   overrides and Phase 4 state injection make it safe.

## Acceptance criteria

- The timing CSV identifies the major components inside the current 15-minute
  stage.
- No seed, consolidated workbook, balance table, or LEAP-import artifact
  content changes due to instrumentation.
- The report names one measured bottleneck and recommends the smallest next
  experiment.
