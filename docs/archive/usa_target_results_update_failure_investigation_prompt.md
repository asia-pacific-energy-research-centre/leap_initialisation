# Investigate the USA Target Results-Update Run Failure

## Objective

Diagnose why the real workbook-mode supply reconciliation `results_update` run
for `20_USA` / `Target` stopped during compressed projection preflight without
writing a Python traceback or timing CSV. Do not guess. Preserve evidence and
identify a confirmed cause or a short, evidence-backed list of remaining
possibilities.

## Scope

- Repository: `C:\Users\Work\github\leap_initialisation`
- Workflow: `codebase\supply_reconciliation_workflow.py`
- Economy: `20_USA`
- Scenario: `Target`
- Automatic run folder:
  `outputs\leap_exports\supply_reconciliation\results_update\runs\UPDATE_20_USA_TGT`
- Do not run any other economy.
- Do not run LEAP API imports. This is a workbook-mode investigation.

## Important background

The failed attempt started on 2026-07-15 and wrote these partial projection
preflight artifacts before stopping:

- `preflight_compressed_projection/checks/supply_reconciliation_augmented_balance_demand_mappings.xlsx`
- `preflight_compressed_projection/checks/supply_reconciliation_balance_demand_conservation.csv`
- `preflight_compressed_projection/checks/supply_reconciliation_balance_demand_conservation_breakdown.csv`
- `preflight_compressed_projection/checks/supply_reconciliation_balance_demand_conservation_lineage.csv`
  (approximately 130 MB)
- `preflight_compressed_projection/runtime/compressed_sources/...`

The launcher stdout/stderr and workflow log were empty, no timing CSV was
written, and no Windows Application Error event was found. This suggests an
abrupt termination or resource problem, but that is not yet proven.

## Safety rules

1. Read the repository `AGENTS.md` and its referenced global instructions.
2. Run `git status --short` first. Preserve existing changes. Do not reset,
   discard, or commit another person's edits.
3. Check economy locks in
   `outputs/leap_exports/supply_reconciliation/supporting_files/runtime/economy_locks/`.
   Do not run if `20_USA.lock` belongs to a live process.
4. If a long workflow run is launched, run it in the background and poll no
   more than once every 10 minutes. Do not kill a healthy run.
5. Do not change modelling assumptions, mappings, validation rules, or
   `THROW_ERROR_AFTER_RUN` merely to make the run finish.
6. Do not delete partial output folders. They are evidence.

## Investigation steps

### 1. Inspect the failed run

- List all files under `UPDATE_20_USA_TGT` with size and modified time.
- Read any launcher logs and the workflow log.
- Check whether `workflow_stage_timings.csv`, a state JSON, combined workbook,
  or final results workbook exists and whether it is fresh.
- Inspect Windows Application and Windows Error Reporting events around the
  run time. Record "none found" if that is the result.
- Check available RAM, committed memory, free disk space, and the size of the
  partial CSV files. Do not infer an out-of-memory failure without evidence.

### 2. Reproduce the smallest useful failure

Use this exact notebook-style configuration in a short diagnostic runner:

```python
import codebase.supply_reconciliation_workflow as workflow

workflow.ECONOMIES = ["20_USA"]
workflow.SCENARIOS = ["Target"]
workflow.RUN_MODE = "full"
workflow.RUN_OUTPUT_LABEL = "USA_TGT_DIAGNOSTIC"
workflow.__dict__.update(workflow._PRESET_RESULTS_UPDATE)
workflow.RUN_PREFLIGHT_COMPRESSED_PROJECTION = True
workflow.RUN_PREFLIGHT_COMPRESSED_RESULTS_UPDATE = False
workflow.PREFLIGHT_COMPRESSED_PROJECTION_ONLY = True
workflow.PREFLIGHT_COMPRESSED_FAIL_FAST = True
workflow.run_with_config()
```

Run it with unbuffered output (`python -u`) and redirect stdout and stderr to
new timestamped files under that diagnostic run folder. This is deliberately a
projection-preflight-only run: it should reveal the failure without launching
the full results-update pass.

If it fails, preserve the complete traceback and stop. Do not start a second
full run until the failure is understood.

### 3. If the diagnostic preflight succeeds

Report that the original termination was not reproduced. Then inspect the
differences between the original launcher and this diagnostic launch (Python
arguments, output redirection, process lifetime, available resources). Only
then propose a controlled next run.

### 4. If a code defect is confirmed

Make the smallest fix directly related to the confirmed defect. Add clear
comments where the failure was non-obvious. Run a focused verification. Commit
only your own files with a `codex:` commit message.

## Deliverable

Write a concise findings note containing:

- Exact commands/configuration used.
- Run folder and log paths.
- Whether `20_USA` was locked and by which process.
- Confirmed root cause, or explicitly labelled unconfirmed hypotheses.
- The last successful workflow stage and evidence for it.
- Resource and Windows-event observations.
- Any code change, test/verification, and commit hash.
- A recommendation: retry full update, fix first, or seek a human decision.

