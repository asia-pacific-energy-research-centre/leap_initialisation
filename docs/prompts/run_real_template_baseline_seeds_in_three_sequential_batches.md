# Run real-template baseline seeds in three sequential batches

## Objective

Run the full-horizon `baseline_seed` workflow for every economy that currently
has a real, economy-owned (non-`_COMP_GEN`) LEAP export template. Run one batch
at a time and one economy at a time. Verify and expose each batch's final seed
files before starting the next batch.

Use a scheduled monitor every 30 minutes after the first process starts. Do not
poll manually between scheduled checks and do not provide routine unchanged
status updates.

## Repository and required starting state

Work only in:

`C:\Users\Work\github\leap_initialisation`

Use `master`. Before starting:

1. Confirm the working tree is clean.
2. Confirm `master` contains merge commit `e136ce3` and the underlying changes:
   - `c003856` - shared transformation process boundary;
   - `877fffe` - legacy refining workflow retirement and real-template scope.
3. Confirm no Python process is already running
   `codebase/supply_reconciliation_workflow.py` or a replacement batch launcher.
4. Inspect economy locks under
   `outputs\leap_exports\supply_reconciliation\supporting_files\runtime\economy_locks`.
   Never clear a lock until its recorded PID is confirmed dead.
5. Resolve every batch economy through
   `find_leap_export_template()` and require `is_provisional == False`.
6. Confirm `codebase/supply_reconciliation_config.py` still has
   `PARALLEL_ECONOMY_WORKERS = 0`. Do not change it above zero.
7. Use `C:\Users\Work\miniconda3\python.exe`.

Do not run the APEC aggregate and do not include any `_COMP_GEN` economy.

## Required batch order

Run these batches strictly in this order:

1. **Batch 1 - priority outputs:** `01_AUS`, `20_USA`, `05_PRC`
2. **Batch 2:** `02_BD`, `10_MAS`, `11_MEX`, `12_NZ`
3. **Batch 3:** `13_PNG`, `15_PHL`, `19_THA`, `21_VN`

The order inside each batch is mandatory. The workflow may receive the whole
batch list, but its economy export loop must remain sequential.

## Run isolation and labels

Use `LEAP_WORKER_SNAPSHOT_JSON`; do not edit module-level `ECONOMIES` or
`RUN_OUTPUT_LABEL` literals.

Create unique timestamped labels:

- `SEED_REAL_BATCH1_AUS_USA_PRC_<YYYYMMDD_HHMMSS>`
- `SEED_REAL_BATCH2_BD_MAS_MEX_NZ_<YYYYMMDD_HHMMSS>`
- `SEED_REAL_BATCH3_PNG_PHL_THA_VN_<YYYYMMDD_HHMMSS>`

Each snapshot must contain:

```json
{
  "economies": ["...ordered batch economies..."],
  "run_output_label": "...unique label...",
  "test_horizon_base_year_plus_one": false
}
```

`test_horizon_base_year_plus_one` must be `false`: these are useful
full-horizon seeds, not two-year smoke tests.

Launch exactly one hidden background process with PowerShell `Start-Process`.
Inherit the snapshot environment and redirect stdout and stderr to distinct
timestamped files beside the batch runtime outputs. Use `-WindowStyle Hidden`.
The child command must be:

```text
C:\Users\Work\miniconda3\python.exe
codebase\supply_reconciliation_workflow.py
```

After launch, inspect it using `Get-CimInstance Win32_Process` and confirm the
pinned interpreter, correct script, and only one active batch workflow process.
Then clear the parent shell's `LEAP_WORKER_SNAPSHOT_JSON`; the child retains its
inherited copy.

Do not use `parallel_economy_runner.py`, `ThreadPoolExecutor`, multiple
terminals, or overlapping batch processes.

## Scheduled 30-minute monitoring

Once Batch 1 is confirmed active, use the Codex schedule/automation feature to
create one recurring 30-minute monitor. Do not emulate scheduling with `sleep`,
a long blocking shell call, or frequent manual polling.

At every scheduled check:

1. Identify the active batch from its process command line, log paths, and run
   label. Never launch a duplicate while any active/replacement process exists.
2. Read only the latest relevant stdout/stderr tail.
3. Check expected log/output modification times or sizes for progress.
4. If progressing normally, remain quiet until the next scheduled check.
5. If failed or stalled:
   - diagnose from logs and artifacts;
   - preserve logs and material partial outputs;
   - make only the smallest clear safe fix;
   - commit the fix separately;
   - rerun only the affected batch with a new unique label;
   - continue the same scheduled loop.
6. Never skip a failed producer, deferred error, preflight failure, validation
   finding, missing economy, or missing final seed.
7. Stop and ask the user for a modelling/mapping decision, uncertain overwrite,
   persistent file lock, or authority outside this prompt.

Poll no more often than every 30 minutes. Notify the user only for:

- verified batch completion, including ready seed paths;
- a genuine blocker;
- verified completion of all batches.

Delete the recurring monitor after all three batches are verified.

## Batch verification gate

Do not start the next batch until every economy in the current batch passes:

1. The process exited successfully with no unhandled exception, failed
   producer, deferred-error summary, or failed compressed preflight.
2. The batch has its own directory under
   `outputs\leap_exports\supply_reconciliation\baseline_seed\runs\<RUN_LABEL>`.
3. Exactly one current final
   `leap_import_baseline_seed_<economy>_*.xlsx` exists per batch economy.
4. No final filename contains `_PRELIM`.
5. Full horizon is present: Current Accounts 2022; Reference and Target
   2023-2060.
6. Scenario, region, template-ID, logical-key, share-total,
   process-efficiency, producer-coverage, and final seed validations completed.
   Review consolidated rule findings and issue groups, not only the exit code.
7. Stock Changes and Statistical Differences rows remain when supplied, even
   where template IDs remain intentionally unresolved for later template work.
   Their existence must not abort the run.
8. Non-specified own-use `Activity Level` has blank `Scale`, not `%`.
9. Process Efficiency uses gross output divided by feedstock. Capacity and
   Output Share use net deliverable output after same-module auxiliary use.
   Confirm no negative deliverable outputs.
10. For AUS 2022 Oil Refining, spot-check approximately:
    - gross output `551.001808 PJ`;
    - feedstock `552.471099 PJ`;
    - Process Efficiency `99.734051%`;
    - same-module auxiliary `39.030023 PJ`;
    - net deliverable capacity basis `511.971785 PJ`.
11. If code changes, run focused tests and validation before rerunning. Never
    modify code merely to hide a genuine validation finding.

After the gate passes, report the ready seed paths and then launch the next
batch. Do not wait for additional approval unless a blocker or modelling choice
was found.

## Efficiency and restart rules

- Keep `TRANSFORMATION_SUPPLY_CACHE_ENABLED = True`.
- Preserve completed batch output directories.
- Never reuse a run label or write into an existing run directory.
- If a batch fails after producing some economies, first determine whether the
  supported resume behavior can safely reuse verified completed exports.
  Otherwise rerun the whole batch under a new label; never splice uncertain
  partial outputs into the next batch.
- Batch 1 is complete only when AUS, USA, and PRC all pass.
- Batch 2 is complete only when all four of its economies pass.
- Do not start Batch 3 until Batch 2 passes.

## Final report

Report:

- all three final run labels;
- final seed path for every economy;
- template filename and confirmation it was non-provisional;
- scenario/year coverage;
- validation summary and non-blocking warnings;
- fixes and commits, if any;
- confirmation execution was fully sequential;
- confirmation the recurring monitor was deleted.

