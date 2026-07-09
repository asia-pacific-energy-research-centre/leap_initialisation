# Supply Reconciliation Results Update Execution Prompt

## Short Version

Run `codebase/supply_reconciliation_workflow.py` with `_PRESET_RESULTS_UPDATE`,
`THROW_ERROR_AFTER_RUN = True`, the single economy provided in the agent chat,
and the requested scenario scope. By default, use all three scenarios. If the
user explicitly asks for only `Current Accounts` and one other scenario, run
exactly those two and nothing else. Launch it detached so it survives tool
timeouts, poll at a fixed cadence without disturbing it, and produce a final
report that distinguishes genuinely-completed outputs from stale files left
over from earlier runs.

## Objective

Execute a targeted `results_update` pass for the provided economy, let deferred
validation errors accumulate without aborting the run early, and end with an
accurate, timestamped account of what succeeded, what was flagged, and what
needs follow-up. Do not broaden scope to other economies unless the user
explicitly asks.

## Before starting

1. Read `AGENTS.md` and any files it references, especially the workflow
   timing history section and the 10-minute polling guidance.
2. Run `git status --short` and preserve all existing unrelated changes. Never
   stage or discard them as part of this task.
3. Confirm the target commit is present (`git log --oneline -1` /
   `git rev-parse HEAD`).
4. Confirm no previous workflow Python process is already running
   (`Get-Process python` / equivalent) before launching a new one.
5. Record the starting commit, the exact configuration in force, the start
   time, and the exact launch command before you run anything.
6. Confirm the upstream LEAP balance-export prerequisite exists for the
   requested economy. The results-update path reads the economy's balance
   workbook under `data/leap balances exports/<economy>/`. The extractor
   accepts LEAP energy-balance workbooks with `EBal|...`, `Energy Balance...`,
   or plain four-digit year sheet names (for example `2060` and `2059`). If
   the workbook is missing or the sheets are unreadable, stop and regenerate
   the LEAP export first.

## Run configuration

- `ACTIVE_PRESET = _PRESET_RESULTS_UPDATE`
- `THROW_ERROR_AFTER_RUN = True`
- `CAPACITY_UNMET_PASS_MODE = "results_update"`
- `RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT = False`
- `RUN_ELECTRICITY_HEAT_INTERIM = False`
- `OTHER_LOSS_OWN_USE_PROXY_STAGE = "second"`
- `RUN_PREFLIGHT_COMPRESSED_RESULTS_UPDATE = True`
- `RUN_PREFLIGHT_COMPRESSED_PROJECTION = True`
- `ECONOMIES = ["<provided economy>"]`
- `SCENARIOS = ["Target", "Reference", "Current Accounts"]` by default.
  If the user explicitly asks for only `Current Accounts` and one other
  scenario, use exactly those two and nothing else.
- The requested economy must already have a readable LEAP balance export
  workbook in `data/leap balances exports/<economy>/`. The workbook is the
  source of truth for the update pass. A `mapping_status.xlsx` dashboard file is
  not required for this run.
- Previously reviewed canonical mapping exceptions are not expected to block
  this run if the workbook already carries the reviewed flags. Treat new or
  unreviewed mapping/subtotal issues as blockers; treat known reviewed rows as
  diagnostics.

Read the config values out of the file rather than assuming they are already
set this way. If they differ, edit them and note exactly what changed.

## Launching so it survives tool timeouts

Do not launch inline and wait. This run may still take a long time because it
includes LEAP recalculation and per-economy export generation. Launch detached
with stdout/stderr redirected to **new, uniquely timestamped files**; never
overwrite a previous run’s logs.

- Interpreter: `C:\Users\Work\miniconda3\python.exe`
- Script: `codebase\supply_reconciliation_workflow.py`
- Redirect stdout to `outputs/logs/supply_reconciliation_results_update_console_<TS>.log`
- Redirect stderr to `outputs/logs/supply_reconciliation_results_update_console_<TS>.err.log`
- Note: the workflow also tees its own stdout to
  `outputs/logs/supply_reconciliation_workflow.log` internally. This file is
  overwritten each run, so treat the timestamped console log as the durable
  record and the internal log as a live-tail convenience only.
- Record the PID and a small metadata file (`start_time`, `pid`, `commit`,
  `stdout`/`stderr` paths, `launch_command`) alongside the logs, following the
  naming convention already used in `outputs/logs/`.

## Polling

Follow `AGENTS.md`: do not poll more often than every 10 minutes once the run
is healthy. It is fine to check more frequently only when you have a specific
reason to expect termination imminently.

At each poll, check and record:

- Process state: `Get-Process -Id <PID>` (alive/terminated) and CPU time.
- Latest stage / current economy / current scenario: read the tail of the
  console log.
- New warnings/errors since the last poll: grep the stderr log and the stdout
  log for tracebacks, `BaselineSeedValidationError`, and `[WARN] Deferred error`.
- New outputs: list the expected per-economy combined workbook and any updated
  export files, sorted or filtered by modification timestamp against the run’s
  start time, not just by existence.

Do not stop a healthy process merely to inspect it. Let it run uninterrupted
between polls.

## Timing / duration tracking

Do not hand-instrument timing. Use the workflow’s own timing output:

- `outputs/leap_exports/supply_reconciliation/supporting_files/runtime/workflow_stage_timings.csv`
  for stage-level start/end timestamps and durations.
- `[TIMING] ... | <stage> | <Xh Ym Z.Zs>` lines in the console/workflow log for
  a live view before the CSV exists.
- `WorkflowTimer.write_csv()` also writes a timestamped copy under a `history/`
  subfolder next to the main timing CSV.

## If the workflow fails or reports deferred errors

1. Preserve the complete logs; do not truncate or overwrite them.
2. Get the complete traceback for every failure. For per-economy failures, read
   the specific `rule_findings.csv` under
   `outputs/leap_exports/supply_reconciliation/workbooks/supporting_files/baseline_seed_validation/`.
3. For the consolidated check, read
   `outputs/leap_exports/supply_reconciliation/supporting_files/baseline_seed_validation/baseline_seed_<date>_consolidated_rule_findings.csv`
   and the paired `_consolidated_issue_groups.csv` when present.
4. Classify each failure:
   - infrastructure/logging
   - diagnostic-only output
   - data/configuration
   - export validation
   - calculation/domain logic
5. For every SEED-rule violation, read
   `codebase/functions/baseline_seed_validation.py` to understand exactly what
   that rule checks.
6. Distinguish a genuine code bug from a genuine data/mapping/design decision.
   Do not apply a speculative fix to the latter. Document it clearly with
   evidence and flag it for a human decision instead.
7. Only restart the economy that actually needs it. If the target economy
   succeeded and only validation/output follow-up remains, do not rerun other
   economies.

## Status classification

For the requested economy, classify the result as one of:

- **Completed successfully** — a fresh output workbook from this run, with no
  deferred error attached to it.
- **Completed with warnings** — a fresh output workbook from this run, but
  flagged by a non-blocking issue.
- **Export failed** — no fresh workbook was written this run.
- **Attempted but incomplete** — started but the process terminated before the
  economy’s export step finished.
- **Not attempted** — never reached before termination.

A workbook existing on disk does not by itself prove the current run completed
it. Always check the modification timestamp against this run’s start time.

## Final report

Provide:

- Starting and ending commit hashes.
- Every launch/restart command used, verbatim.
- All log paths with timestamps.
- Start/end time and duration for the run.
- Status of the requested economy, and of each requested scenario if the run
  was split that way.
- Output paths for successful files.
- Grouped warnings separated clearly from deferred errors, validation failures,
  and any fatal errors.
- For every issue: its confirmed root cause and supporting evidence.
- Exact code changes made, if any, with file paths and line numbers, tests
  added, tests run, and commit hash.
- Unresolved issues and any follow-up needed before the output is trusted for
  LEAP import.
- Final `git status --short`.
- Confirmation that no workflow process remains running.

## Notes

- This repo is notebook-first; do not restructure the workflow script while
  executing this task.
- Never rename or move outputs outside the repo’s standard workflow folders
  (`outputs/leap_exports/supply_reconciliation/...`, `outputs/logs/...`).
- Never overwrite a previous run’s logs or outputs; always use a new timestamp.
- Do not disable or loosen validation to get past a failure unless it is
  demonstrably incorrect.
- If the user explicitly asks for only `Current Accounts` and one other
  scenario, use exactly that pair and do not include the third scenario.
