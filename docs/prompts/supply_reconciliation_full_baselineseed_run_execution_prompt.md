# Supply Reconciliation Full Run Execution Prompt

## Short Version

Run `codebase/supply_reconciliation_workflow.py` with `_PRESET_BASELINE_SEED`,
`THROW_ERROR_AFTER_RUN = True`, all 21 economies in `ECONOMIES_RUN_ORDER`, and
all three scenarios. Launch it detached so it survives tool timeouts, poll at
a fixed cadence without disturbing it, and produce a final report that
distinguishes genuinely-completed economies (fresh timestamps from *this* run)
from stale files left over from a previous run.

## Objective

Execute a full baseline-seed run across every configured economy and scenario,
let deferred validation errors accumulate without aborting the run early, and
end with an accurate, timestamped account of what succeeded, what was flagged,
and what needs follow-up — without guessing at fixes for genuine data/mapping
issues along the way.

## Before starting

1. Read `AGENTS.md` and any files it references (in particular the workflow
   timing history section and the 10-minute polling guidance).
2. Run `git status --short` and preserve all existing unrelated changes —
   never stage or discard them as part of this task.
3. Confirm the target commit is present (`git log --oneline -1` /
   `git rev-parse HEAD`).
4. Confirm no previous workflow Python process is already running
   (`Get-Process python` / equivalent) before launching a new one.
5. Record the starting commit, the exact configuration in force, the start
   time, and the exact launch command before you run anything.

## Run configuration

- `ACTIVE_PRESET = _PRESET_BASELINE_SEED`
- `THROW_ERROR_AFTER_RUN = True`
- `RUN_PREFLIGHT_COMPRESSED_PROJECTION = True` (compressed preflight against
  `00_APEC` runs first; treat a preflight failure as informative, not fatal,
  since `THROW_ERROR_AFTER_RUN` defers it too)
- `PARALLEL_ECONOMY_WORKERS = 0` — confirm this before assuming "one economy
  at a time"; if it's ever `> 1`, economies run concurrently via
  `ThreadPoolExecutor` and per-economy timestamps will interleave
- `ECONOMIES_RUN_ORDER`:

  ```python
  ["21_VN", "20_USA", "19_THA", "05_PRC", "13_PNG", "15_PHL", "12_NZ",
   "11_MEX", "10_MAS", "02_BD", "01_AUS", "03_CDA", "04_CHL", "06_HKC",
   "07_INA", "08_JPN", "09_ROK", "14_PE", "16_RUS", "17_SGP", "18_CT"]
  ```

- `SCENARIOS = ["Target", "Reference", "Current Accounts"]`

Read the config values out of the file rather than assuming they're already
set this way — if they differ, edit them and note exactly what changed.

## Launching so it survives tool timeouts

Do not launch inline and wait — this run takes several hours. Launch detached
with stdout/stderr redirected to **new, uniquely timestamped files**; never
overwrite a previous run's logs.

- Interpreter: `C:\Users\Work\miniconda3\python.exe`
- Script: `codebase\supply_reconciliation_workflow.py`
- Redirect stdout to `outputs/logs/supply_reconciliation_console_<TS>.log`
- Redirect stderr to `outputs/logs/supply_reconciliation_console_<TS>.err.log`
- Note: the workflow *also* tees its own stdout to
  `outputs/logs/supply_reconciliation_workflow.log` internally — this file is
  overwritten each run, so treat the timestamped console log as the durable
  record and the internal log as a live-tail convenience only.
- Record the PID and a small metadata file (`start_time`, `pid`, `commit`,
  `stdout`/`stderr` paths, `launch_command`) alongside the logs, following the
  naming convention already used in `outputs/logs/` (e.g.
  `supply_reconciliation_<TS>.pid`, `supply_reconciliation_<TS>_run_metadata.txt`).

## Polling

Follow `AGENTS.md`: **do not poll more often than every 10 minutes** once the
run is healthy (this repo's own instruction is stricter than a flat 20
minutes — defer to it). It is fine to check more frequently (a few minutes)
only when you have specific reason to expect termination imminently (e.g. the
last economy just finished and the run is in its final consolidation/write
stage) — don't do this speculatively.

At each poll, check and record:

- **Process state** — `Get-Process -Id <PID>` (alive/terminated) and CPU time
  (a climbing CPU time confirms real work even when stdout hasn't produced a
  new line recently; a flat CPU time across a poll interval is the real stall
  signal, not silence in the log).
- **Latest stage / current economy / current scenario** — read the tail of
  the console log.
- **New warnings/errors** since the last poll — grep the stderr log and the
  stdout log for tracebacks, `BaselineSeedValidationError`, and
  `[WARN] Deferred error`.
- **New outputs** — list `combined_st_*.xlsx` (or the equivalent per-economy
  workbook) **sorted or filtered by modification timestamp against the
  run's start time**, not just by existence. Files from a previous failed
  run persist on disk and will still be present; only a timestamp newer than
  this run's launch time proves the current run actually rewrote them.

Do not stop a healthy process merely to inspect it. Let it run uninterrupted
between polls.

## Timing / duration tracking

Do not hand-instrument timing — the workflow already writes this. Use:

- `outputs/leap_exports/supply_reconciliation/supporting_files/runtime/workflow_stage_timings.csv`
  for stage-level start/end timestamps and durations (setup, load balance
  demand inputs, generate LEAP import workbooks, write per-economy combined
  workbooks, write consolidated run workbook, total, etc.) — this is written
  once at the end of the run.
- `[TIMING] ... | <stage> | <Xh Ym Z.Zs>` lines in the console/workflow log
  for a live view before the CSV exists.
- Per-economy timestamps: cross-reference file-modification times of
  `combined_st_*.xlsx` (or equivalent) against the run's start time, per the
  polling section above — the workflow does not print an explicit
  per-economy "start"/"end" timestamp pair, so file mtimes are the most
  reliable proxy for "when did economy X finish."
- `WorkflowTimer.write_csv()` also writes a timestamped copy under a
  `history/` subfolder next to the main timing CSV — useful for comparing
  this run's stage durations against prior runs of the same economy/scenario
  count (see `AGENTS.md`'s "Workflow Timing History" section).

## If the workflow fails or reports deferred errors

1. Preserve the complete logs; do not truncate or overwrite them.
2. Get the complete traceback for every failure — do not patch based on the
   final error message alone. For per-economy failures, read the specific
   `rule_findings.csv` under
   `outputs/leap_exports/supply_reconciliation/workbooks/supporting_files/baseline_seed_validation/`.
   For the consolidated check, read
   `outputs/leap_exports/supply_reconciliation/supporting_files/baseline_seed_validation/baseline_seed_<date>_consolidated_rule_findings.csv`
   and the paired `_consolidated_issue_groups.csv`.
3. Classify each failure:
   - infrastructure/logging
   - diagnostic-only output
   - data/configuration
   - export validation
   - calculation/domain logic
4. For each SEED-rule violation, read
   `codebase/functions/baseline_seed_validation.py` to understand exactly
   what that rule checks (`SEED-003`, `SEED-004`, `SEED-008`, `SEED-009`,
   `SEED-010`, `SEED-011`, `SEED-012`, etc. are all distinct checks with
   distinct meanings — do not assume two different rule IDs share a root
   cause without confirming).
5. Distinguish a genuine code bug (clear, narrow, general fix — implement it,
   add a regression test, run relevant tests, commit only the fix hunks with
   a `codex:` message, preserving unrelated uncommitted changes) from a
   genuine data/mapping/design decision (e.g. an output fuel with no
   corresponding LEAP branch in `data/full model export.xlsx`, or a producer
   workflow's zero-output convention not yet reconciled with a validator's
   expectations). **Do not apply a speculative fix to the latter** — document
   it clearly with evidence (the specific rows/branches/values from the
   findings CSV) and flag it for a human decision instead.
6. Only restart economies that actually need it. If N of 21 economies
   genuinely succeeded (fresh timestamps from this run) and only one or two
   failed, do not rerun the whole 21-economy set — use
   `SKIP_ECONOMIES_WITH_EXISTING_EXPORTS = True` (or a temporary
   `ECONOMIES = [...]` override) to retry only the failed/unattempted
   economies, with a new timestamped log, and revert the temporary override
   afterward.

## Status classification (be precise)

For each of the 21 economies, classify as one of:

- **Completed successfully** — fresh per-economy workbook from this run, no
  deferred error attached to it.
- **Completed with warnings** — fresh per-economy workbook from this run,
  but flagged by the consolidated producer-coverage check or similar
  non-blocking-to-the-file-itself issue.
- **Export failed** — no fresh per-economy workbook was written this run
  (check timestamps, not just existence — a stale file from a previous run
  does not count as success).
- **Attempted but incomplete** — started but the process terminated (or was
  interrupted) before the economy's export step finished.
- **Not attempted** — never reached in `ECONOMIES_RUN_ORDER` before
  termination.

A workbook existing on disk does not by itself prove the current run
completed it — always check the modification timestamp against this run's
start time.

## Final report

Provide:

- Starting and ending commit hashes.
- Every launch/restart command used, verbatim.
- All log paths (stdout, stderr, workflow log) with their timestamps.
- Start/end time and duration for the run (and for any restart).
- Status of every economy × scenario, using the classification above.
- Output paths for successful economies.
- Grouped warnings (mapping mismatches, metadata mismatches, proxy coverage
  gaps, duplicate export rows, unresolved `BranchID=-1` rows — these are
  expected/benign across most runs) separated clearly from deferred errors,
  validation failures, and any fatal errors.
- For every issue: its confirmed root cause and the supporting evidence
  (findings CSV rows, code references) — not just the exception message.
- Exact code changes made (if any), with file paths and line numbers, tests
  added, tests run, and commit hash.
- Which economies were rerun after a fix, and why.
- Unresolved issues and which economies need human follow-up before their
  outputs are trusted for LEAP import.
- Final `git status --short`.
- Confirmation that no workflow process remains running.

## Notes

- This repo is notebook-first; do not restructure the workflow script while
  executing this task.
- Never rename or move outputs outside the repo's standard workflow folders
  (`outputs/leap_exports/supply_reconciliation/...`, `outputs/logs/...`).
- Never overwrite a previous run's logs or outputs; always use a new
  timestamp.
- Do not disable or loosen validation to "get past" a failure unless it is
  demonstrably incorrect — see the diagnose-fix-restart guidance above.

## Targeted retry after a partial failure

Once a full run leaves only a small number of economies unresolved (export
failed / not attempted), do not rerun all 21 economies to pick them up — retry
only what actually needs it, and only after the underlying fix has genuinely
been made.

Worked example — retrying `12_NZ` after the 2026-07-08 run:

```text
Run: C:\Users\Work\github\leap_initialisation\codebase\supply_reconciliation_workflow.py

Context: On 2026-07-08 a full 21-economy baseline-seed run completed (commit ef1b3d7,
logs outputs/logs/supply_reconciliation_console_20260708_001446.log/.err.log). 20 of 21
economies succeeded with valid outputs. Only 12_NZ failed its per-economy export, due to:
  1. SEED-003/SEED-011: a "Gas to liquids plants\Output Fuels\Other hydrocarbons" branch
     that doesn't exist in data/full model export.xlsx (LEAP only has Kerosene/Gas and
     diesel oil/Other products branches for GTL output).
  2. SEED-010: 16 findings where "Transformation\LNG regasification\..." branches are
     missing Target-scenario coverage for 12_NZ specifically.
A related consolidated SEED-012 "producer coverage" issue also flagged 8 other economies
(05_PRC, 06_HKC, 07_INA, 10_MAS, 15_PHL, 16_RUS, 17_SGP, 19_THA) because transfers_workflow
intentionally writes no output file when an economy has zero nonzero transfer flows
(codebase/transfers_workflow.py:648-650) and the SEED-012 check
(check_producer_coverage in codebase/functions/baseline_seed_validation.py) has no
tolerance for a legitimately-empty producer. No fix was applied for either issue — they were left as design/mapping
decisions for the user.

Before running:
1. Confirm the code fix(es) for the 12_NZ GTL branch mapping / LNG regasification gap,
   and (if addressed) the transfers_workflow / SEED-012 producer-coverage handling, are
   committed on this branch. Read the diff to confirm what changed.
2. Read AGENTS.md and referenced instruction files if not already familiar with this run.
3. Run `git status --short` and preserve all existing unrelated changes.
4. Confirm no previous workflow Python process is running.

Configuration for this retry:
- Temporarily set ECONOMIES = ["12_NZ"] in codebase/supply_reconciliation_workflow.py
  (overriding ECONOMIES = ECONOMIES_RUN_ORDER), OR keep the full ECONOMIES_RUN_ORDER and
  set SKIP_ECONOMIES_WITH_EXISTING_EXPORTS = True in _PRESET_BASELINE_SEED so the other
  20 already-valid economies are skipped and reused as-is.
- Keep THROW_ERROR_AFTER_RUN = True, _PRESET_BASELINE_SEED active, SCENARIOS =
  ["Target", "Reference", "Current Accounts"], and the compressed preflight enabled.
- Use C:\Users\Work\miniconda3\python.exe.
- Note whichever config override you use (ECONOMIES vs SKIP_ECONOMIES_WITH_EXISTING_EXPORTS)
  so it can be reverted to the original full-run config afterward before any future full run.

Launch the workflow detached (new timestamped stdout/stderr logs, don't overwrite prior
logs), record the PID and metadata file, and poll every 10-20 minutes per AGENTS.md until
it reaches a terminal state (this should be much faster than a full 21-economy run since
only 12_NZ is being processed).

On completion:
- If 12_NZ succeeds: confirm outputs/leap_exports/supply_reconciliation/
  leap_import_baseline_seed_12_NZ_<date>.xlsx and combined_st_12_NZ_*.xlsx were written,
  check for any new deferred errors, and revert the temporary ECONOMIES/
  SKIP_ECONOMIES_WITH_EXISTING_EXPORTS override back to the original full-run config.
- If 12_NZ still fails: get the full traceback, compare the new findings CSV against the
  2026-07-08 one to see if the fix addressed the reported rule violations, and report back
  rather than attempting another speculative fix.
- Report: launch command, log paths, start/end time and duration, final status, whether
  the config override was reverted, and final git status --short.
```

Generalize this pattern for any future partial-failure retry:

1. Name the specific prior run (date, commit, log paths) and the specific
   economies that failed or were flagged, with their rule IDs and evidence —
   don't just say "retry the failed ones."
2. Require confirmation that a real fix (not a config toggle) has been
   committed before retrying — a retry with unchanged code and unchanged
   source data will reproduce the identical result.
3. Use either a temporary `ECONOMIES = [...]` override or
   `SKIP_ECONOMIES_WITH_EXISTING_EXPORTS = True` to avoid rerunning economies
   that already succeeded — state which one was used and revert it
   afterward.
4. Always use a new timestamped log for the retry; never reuse or append to
   the original run's log.
5. On completion, compare the new findings CSV against the original one to
   confirm the specific reported rule violations are actually gone, not just
   that the process exited cleanly.

## Post-run: explore and clear the consolidated rule findings (all economies)

The goal of the next full baseline-seed run is not just 21 written workbooks —
it is a run whose consolidated findings are fully explained, with every
finding either fixed at its root cause or explicitly accepted with a reason.
We want the consolidated findings cleared out for all economies, over as many
run/review iterations as that takes.

Division of labour — this matters: clearing findings depends on data, mapping,
and methodology decisions that only the user can make. The agent running this
prompt must NOT apply those fixes itself — no editing mappings, source data,
validation rules, `validation_exceptions`, or workflow config to make findings
go away. The agent's deliverable for each iteration is the diagnosis: a
findings summary and a per-root-cause decision table (see below) that the user
acts on manually. Reruns happen only after the user has made their changes and
asked for one.

Configuration for this run:

- Confirm `BASELINE_SEED_VALIDATION_BLOCKING_FINDINGS_ARE_WARNINGS = True` in
  `codebase/configuration/workflow_config.py` before launching, so a blocking
  finding downgrades to a warning instead of stopping the run — we want the
  complete findings picture across all 21 economies in one pass, not a run
  that halts at the first blocked economy.
- Be aware of what this flag does to the CSVs (see the INIT-005 known
  deviation in `docs/special_rules_and_design_decisions.md`): findings that
  would have been blocking are rewritten to `severity=warning` /
  `blocking=False` before being written. Therefore, when exploring, do NOT
  filter on `blocking == True` — analyze ALL rows and group by `rule_id`.
  Only SEED-012 (producer coverage) bypasses this downgrade and keeps
  `blocking=True`, because it is generated by the combine step itself rather
  than by `prepare_seed_rows_for_write`.
- This flag also means workbooks are written even for economies with
  unresolved violations — do not present those workbooks as
  LEAP-import-ready; the findings review below decides that.

After the run completes, explore the findings:

1. Open the consolidated outputs for this run's stamp under
   `outputs/leap_exports/supply_reconciliation/supporting_files/baseline_seed_validation/`:
   `baseline_seed_<stamp>_consolidated_rule_findings.csv` and
   `baseline_seed_<stamp>_consolidated_issue_groups.csv`.
2. Summarize findings by `rule_id` × `economy` × `source_workflow` (counts),
   and list distinct `message` values per rule. SEED-012 messages now name
   the concrete workbook paths and why each was rejected (does not exist on
   disk / matched this economy but failed to read / exists only for other
   economies), and carry the paths in the `source_file` column — use that to
   separate environment/path problems from genuine coverage gaps.
3. For every rule that fired, identify the root cause with evidence (findings
   rows plus code/data references), the same way the diagnose-fix-restart
   guidance above requires. Known prior causes to check first: the 12_NZ GTL
   branch mapping (SEED-003/011), LNG regasification Target coverage
   (SEED-010), transfers_workflow intentionally writing no file for
   zero-transfer economies (SEED-012), and share-group completion
   (SEED-006/007/008).
4. Produce a decision table for the user — one row per root cause, with: the
   rule ID(s) and economies affected, the evidence, the proposed remedy
   (data/mapping change, code change, or accept-with-reason via
   `validation_exceptions`), and what decision is needed from the user. Do
   not apply any of these remedies yourself; the user makes the changes
   manually and then requests the next run (per the targeted-retry pattern
   above when only some economies need it).
5. The exit condition — reached across iterations, not necessarily this run —
   is a run whose consolidated rule findings CSV is empty (or contains only
   findings the user has explicitly accepted) for all 21 economies. Once that
   is reached, remind the user that
   `BASELINE_SEED_VALIDATION_BLOCKING_FINDINGS_ARE_WARNINGS` is due for
   review — with zero findings it no longer has any effect, and reverting it
   to `False` restores the INIT-005 guarantee for future runs. That revert is
   also the user's call, not the agent's.
6. Include the findings summary (per rule × economy) and the decision table
   in the run report.
