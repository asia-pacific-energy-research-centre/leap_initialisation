Work in:

C:\Users\Work\github\leap_initialisation

Operate autonomously. Do not ask questions during execution; stop and report when user judgment is required. If a blocking ambiguity requires user judgment, record it and provide a final report stating the exact decision required.

Objective

Safely manage a long-running LEAP initialisation workflow:

1. Run the complete regression suite.
2. Run the full production workflow for `20_USA`.
3. If `20_USA` succeeds, run the workflow for all configured economies.
4. Fix only small, unambiguous mechanical code defects.
5. Stop on domain, mapping, configuration, balance, or data problems.
6. Preserve sufficient durable state to recover after context compaction or interruption.

Read first

Read and follow:

- `AGENTS.md`
- `docs/supply_reconciliation_workflow_guide.md`
- `docs/special_rules_and_design_decisions.md`
- `C:\Users\Work\.codex\AGENTS_BALANCE_TABLES.md`
- `C:\Users\Work\.codex\AGENTS_LEAP_EXPORT.md`

Environment

Use:

C:\Users\Work\miniconda3\python.exe

Do not use PowerShell’s `python` or `py` aliases.

The production workflow is expected to use workbook write mode. LEAP Desktop should not need to be running.

Managed runtime folder

Use:

outputs/leap_exports/supply_reconciliation/supporting_files/runtime/managed_runs/

Maintain the durable journal at:

outputs/leap_exports/supply_reconciliation/supporting_files/runtime/managed_runs/managed_run_notes.md

Store temporary runners and timestamped stdout/stderr logs in this same managed runtime folder.

Durable-state rule

The journal and managed logs are authoritative. Chat history alone is not authoritative after suspected context loss.

Update `managed_run_notes.md`:

- at the beginning of the task;
- after the regression gate;
- before launching an expensive workflow;
- after every mechanical fix;
- after every focused test;
- after every managed workflow completion;
- when identifying a blocker;
- before the final report.

Each update must record:

- timestamp;
- current phase;
- last completed command;
- latest test result;
- active managed PID, if any;
- full managed command line, if any;
- managed log path;
- configured economies and scenarios;
- next safe action;
- whether it is safe to launch another workflow;
- known blockers;
- files changed during this task;
- latest verified outputs.

If context is compacted, lost, or resumed later, do nothing else until you read:

1. `managed_run_notes.md`;
2. the latest relevant managed workflow log;
3. current `git status --short`;
4. recorded PID and command line;
5. current output timestamps.

Reconstruct the last verified state before continuing.

Context-continuity sentinel

Every assistant-authored natural-language progress message and final report must begin with exactly:

Dear Finn,

This is a continuity sentinel for detecting context drift, compaction, or loss of task state.

Tool calls and raw tool outputs are not assistant-authored natural-language progress messages.

If a user-visible assistant message does not begin with `Dear Finn,`:

1. Record the incident in `managed_run_notes.md`.
2. Do not stop, kill, or interrupt an active managed workflow solely because of the formatting failure.
3. Reconstruct state from:
   - `managed_run_notes.md`;
   - the latest managed workflow log;
   - recorded managed PID and full command line;
   - current `git status --short`;
   - current output timestamps.
4. If the safe state can be confidently reconstructed, continue from the documented next safe action.
5. If it cannot be confidently reconstructed:
   - do not launch another workflow;
   - do not terminate unrelated processes;
   - if an active managed workflow is safely identified, allow it to reach its endpoint;
   - record the last verified state;
   - provide a final report beginning with `Dear Finn,`.

A context warning never bypasses the regression gate. Do not launch an expensive workflow unless the durable journal confirms that the complete regression suite passed during this task and no source or test changes have invalidated that result.

Repository safety

The working tree contains substantial existing user and agent changes.

At the beginning:

1. Run `git status --short`.
2. Record all existing changed and untracked files.
3. Treat those changes as pre-existing unless proven otherwise.
4. Preserve them.

Do not:

- commit;
- stage files;
- reset;
- restore;
- revert;
- discard changes with `git checkout`;
- broadly reformat files;
- delete existing outputs or logs;
- include unrelated changes in a patch.

Before editing a file:

1. Inspect its existing targeted diff.
2. Record whether it was already modified.
3. Identify the exact lines required for the fix.
4. Make the smallest possible change.
5. Record the change in the journal.

Several Python files contain UTF-8 BOMs. Source-analysis tools must read Python files using `encoding="utf-8-sig"`.

Inspection discipline

- Use `rg` for source and symbol searches.
- Use targeted diffs rather than whole-file diffs.
- Tail logs rather than reading them fully.
- Do not print large DataFrames, CSVs, Excel sheets, or logs.
- Use schemas, counts, summaries, and at most 10 representative records.
- Do not open large output workbooks merely to verify their existence.

Initial state reconstruction

Before launching tests or workflows:

1. Read the durable journal if it exists.
2. Run `git status --short`.
3. Check for previous managed Python processes.
4. Identify processes by PID and full command line, not executable name alone.
5. Inspect existing managed-log filenames and timestamps.
6. Determine whether a previous run completed.
7. Do not launch a duplicate workflow.
8. Do not kill an unidentified process.

If the safe state is ambiguous before any workflow starts:

1. Record the ambiguity.
2. Do not launch the workflow.
3. Produce a final report explaining:
   - the last verified state;
   - the conflicting evidence;
   - the exact user decision needed.

Regression gate

Confirm these tests exist:

- `tests/test_module_attribute_contracts.py`
- `tests/test_preflight_smoke.py`

Run the complete normal suite without enabling the opt-in compressed-preflight smoke test:

& 'C:\Users\Work\miniconda3\python.exe' -m pytest -q

The historical result was approximately 289 passed and 6 skipped, but the current suite is authoritative.

The gate passes only when there are no failing tests. Explicitly skipped tests are acceptable.

After it passes, record in the journal:

- command;
- timestamp;
- passed, failed, and skipped counts;
- current Git state;
- `REGRESSION_GATE_PASSED = True`;
- whether it is safe to launch `20_USA`.

Do not launch an expensive workflow if tests fail.

If tests fail:

1. Diagnose each failure.
2. Apply only permitted mechanical fixes.
3. Run focused tests.
4. Run the complete suite again.
5. Proceed only after it passes.

Workflow configuration

Run the real full-horizon production workflow, not compressed preflight.

Before each workflow launch, record the observed values of:

- `workflow.RUN_MODE`;
- the active preset name;
- `workflow.SCENARIOS`;
- `workflow.ECONOMIES`;
- `workflow.get_analysis_input_write_mode()`;
- whether patch-only mode is active;
- `workflow.SCRAPE_LEAP_RESULTS`;
- `workflow.RUN_PREFLIGHT_COMPRESSED_PROJECTION`;
- `workflow.KEEP_PC_AWAKE_WHILE_RUNNING`.

Determine the active preset name by comparing `workflow.ACTIVE_PRESET` with named preset objects in the module. If it cannot be identified unambiguously, record that and stop.

Expected production configuration

For a full baseline-seed production run, require:

- `RUN_MODE == "full"`;
- active preset is `_PRESET_BASELINE_SEED`;
- patch-only mode is false;
- analysis input write mode is `"workbook"`;
- `SCRAPE_LEAP_RESULTS is False`;
- `RUN_PREFLIGHT_COMPRESSED_PROJECTION is False`;
- scenarios match the repository’s configured production scenarios;
- `KEEP_PC_AWAKE_WHILE_RUNNING is True`.

For the pilot run:

- `ECONOMIES == ["20_USA"]`.

For the all-economy run:

- `ECONOMIES` must match the canonical configured economy list obtained from the repository.

If any observed value is inconsistent with these requirements:

1. Do not silently change it, except for the explicitly authorized runtime overrides below.
2. Record the observed value and expected value.
3. Stop and report the configuration ambiguity.

Authorized runtime overrides

After importing the workflow module, the runner may set only:

```python
workflow.ECONOMIES = requested_economies
workflow.RUN_PREFLIGHT_COMPRESSED_PROJECTION = False
workflow.SCRAPE_LEAP_RESULTS = False
workflow.KEEP_PC_AWAKE_WHILE_RUNNING = True
Do not change scenarios, years, mappings, presets, validation behavior, or modelling configuration.
Use:
import codebase.supply_reconciliation_workflow as workflow

workflow.ECONOMIES = ["20_USA"]
workflow.RUN_PREFLIGHT_COMPRESSED_PROJECTION = False
workflow.SCRAPE_LEAP_RESULTS = False
workflow.KEEP_PC_AWAKE_WHILE_RUNNING = True

result = workflow.run_with_config()
Use run_with_config() because it synchronizes workflow configuration and logging.
Managed runner
If a temporary runner is needed:
Create it under:
outputs/leap_exports/supply_reconciliation/supporting_files/runtime/managed_runs/

Make it notebook-compatible:
summary comment at the top;
#%% at the top and bottom;
functions rather than classes;
explicit parameters;
hard-coded notebook-style run variables;
no argparse.

Launch it with:
C:\Users\Work\miniconda3\python.exe

Redirect stdout and stderr to a new timestamped log in the managed runtime folder.

Record the runner path, command, PID, and log path.

Do not commit the runner.

Process management and polling
Run only one workflow process at a time.
After launch:
Record the managed PID.
Record its full command line.
Record the start time.
Set next_poll_at to 10 minutes after launch.
Poll the active process no more frequently than once every 10 minutes.
At each scheduled poll, inspect only:
whether the exact managed PID remains active;
exit code if completed;
final 20–40 log lines;
whether explicitly expected output timestamps advanced;
latest workflow stage visible in that log tail.
Then schedule the next poll 10 minutes later.
Between scheduled polls, do not inspect:
process state;
logs;
CPU or memory;
output timestamps;
output files.
Do not send artificial progress updates between polls.
If a true 10-minute non-polling wait is unavailable:
Use the longest available blocking or yielded wait.
Repeat waits as necessary.
Do not query process state, logs, CPU, memory, or outputs until the scheduled 10-minute poll time.
If the process tool directly reports completion, handle it immediately. A direct completion notification is not an extra poll.
Silence is not evidence of failure.
Never launch another workflow while the managed PID remains active.
If a tool timeout leaves the child alive, continue managing the same PID. Do not launch a replacement.
Never terminate a process without matching both its PID and full command line. Never terminate unrelated Python, Jupyter, Excel, LEAP, or user processes.
Managed log and journal entries
For each run, record:
runner and command;
PID and full command line;
economies;
scenarios;
configuration observations;
start and end time;
duration;
exit code;
last successful stage;
exception type and concise traceback;
explicitly reported primary outputs;
fix, retry, or blocker.
Mechanical-fix boundary
A defect may be fixed autonomously only when all conditions hold:
A traceback identifies a specific code-contract defect.
Intended behavior is unambiguous from definitions, imports, call sites, tests, or immediately adjacent working code.
The fix does not change energy, mapping, reconciliation, allocation, scenario, capacity, transformation, supply, demand, or LEAP-model semantics.
The patch is local and small.
A focused test can verify it.
Permitted examples:
missing import;
incorrect local import path;
clearly misplaced module attribute;
undefined symbol that was demonstrably moved;
missing standard-library import;
clear circular-import fix using an established late-import pattern;
import-time workflow execution requiring an existing entry-point guard;
narrow repository-root or path-normalization defect;
runner, logging, or managed-process defect;
UTF-8 BOM handling in source inspection;
function-signature mismatch where all call sites prove one contract.
Column and schema fixes
A column-name fix is permitted only when:
The traceback proves that a specific column is missing.
The exact intended column name is demonstrated by at least one of:the same DataFrame’s schema;
a directly relevant test fixture;
immediately adjacent working code handling the same table.

The change does not reinterpret or remap domain data.
Do not infer a column mapping merely because names appear semantically similar.
Mechanical-fix procedure
For each permitted fix:
Confirm the failed workflow process exited.
Record the failure.
Inspect directly relevant definitions and call sites.
Inspect the target file’s existing diff.
Confirm intended behavior from repository evidence.
Add or update a focused regression test where practical.
Apply the smallest patch.
Record files and lines changed.
Run the focused test.
Run the directly related test module.
Run tests/test_module_attribute_contracts.py for import, name, or ownership failures.
Retry the failed workflow from the beginning unless a verified resumable checkpoint exists.
The initial full-suite result is invalidated when source code or tests change. Before launching or relaunching an expensive workflow after such a change, run the complete suite again and record the new passing gate.
Human-review boundary
Do not autonomously change:
canonical mapping workbooks;
mapping rows or targets;
rollups or subtotal rules;
hierarchy or cardinality logic;
reconciliation allocation behavior;
capacity-unmet logic;
production caps;
import/export balancing;
surplus or shortfall rules;
transformation rules;
fuel or sector relationships;
scenario interpretation;
energy signs or balance equations;
LEAP branches, variables, expressions, IDs, or model structure;
baseline-seed semantics;
missing data treatment;
validation thresholds or validation bypasses;
broad architecture or performance behavior.
Also stop if:
multiple plausible fixes exist;
a domain assumption is required;
a production patch would exceed approximately 30 changed lines or span more than three production files, unless it is a repetitive correction of one proven mechanical defect.
Data and validation failures
A validation failure is not automatically a code defect.
For mapping, seed, balance, workbook, branch, fuel, sector, capacity, convergence, or model-data failures:
Record the exact message.
Record economy and stage.
Record affected file and identifiers.
Include at most 10 representative records.
Do not change underlying data.
Do not weaken validation.
Stop the affected workflow and report the blocker.
Run sequence
Phase 1 — regression gate
Reconstruct durable state.
Run the complete suite.
Continue only after recording a passing result.
Phase 2 — 20_USA
Verify and record configuration.
Run the full production workflow for ["20_USA"].
Apply permitted mechanical fixes and retest when necessary.
Stop on a domain or data problem.
Phase 3 — all economies
Proceed only if the journal confirms 20_USA succeeded.
Obtain the canonical economy list from existing workflow configuration.
Verify and record configuration.
Run the same production workflow for all configured economies.
Do not silently skip a failed economy.
Stop and report a domain or data failure.
Expected primary outputs
Do not invent expected output paths.
Treat an output as a primary expected output only when it is:
explicitly reported by the workflow as a primary/final output;
returned by run_with_config();
documented as a primary output in the workflow guide;
recorded by an existing workflow completion or validation function.
For every expected primary output:
Record its exact path.
Confirm it exists.
Confirm it is non-empty.
Confirm its modification time corresponds to the current run.
Use existing validation metadata where available.
Do not open large workbooks in full merely to verify success.
Run success requires:
exit code zero;
no fatal traceback;
expected primary outputs verified;
managed PID exited;
journal updated.
Test policy
Run the complete suite at the start.
Run focused tests after every mechanical fix.
Before an expensive retry, rerun the complete suite if source code or tests changed.
At the end, run the complete suite again only if source code or tests changed since the latest recorded complete passing suite.
Do not rerun the full suite at the end when no source or test files changed.
Progress messages
Send concise messages only for meaningful events:
regression gate completed;
workflow launched;
a scheduled poll found material progress or an error;
workflow completed;
mechanical fix completed;
blocker found;
context reconstruction performed;
final report.
Every such message must begin with:
Dear Finn,
Final report
The final report must begin with:
Dear Finn,
Include:
last verified phase;
initial regression result;
latest valid complete-suite result;
observed workflow configuration;
20_USA duration, exit code, and outcome;
all-economy duration, exit code, and outcome;
completed economies;
failed economy and stage, if applicable;
mechanical fixes and focused tests;
unresolved blockers;
primary output paths verified;
managed log paths;
journal path;
confirmation of managed PID status;
initial and final git status --short;
pre-existing changes versus task changes;
any context-sentinel incidents;
whether state recovery succeeded;
exact recommended next action.
Do not claim success merely because the process ran for a long time.
---

# ADDENDUM — Session state and learnings (written 2026-07-03 by the managing agent; authoritative alongside the journal)

Read this before starting. The durable journal at
`outputs/leap_exports/supply_reconciliation/supporting_files/runtime/managed_runs/managed_run_notes.md`
holds the full chronological record; reconstruct state from it first.

## Current run state (as of 2026-07-03 ~01:26)

- Phase 1 (regression gate): PASSED repeatedly; current baseline is
  **292 passed, 6 skipped** (3 new tests in `tests/test_zero_skeleton_scenario_borrowing.py`).
- Phase 2 (20_USA): attempt 5 IN FLIGHT — managed PID 40480, log
  `managed_runs/managed_run_20_USA_20260703_0120.log`, launched via
  `managed_runs/managed_runner_20_usa.py`. Attempts 1–4 failed and were fixed
  in sequence (see journal): mapping subtotal validation → duplicate mapping
  rows → producer-ownership duplicate keys (SEED-001/002, 173→0) → hydrogen
  scenario coverage (SEED-010, 47→9→fix). Expect ~35–40 min per attempt.
- Phase 3 (all economies): NOT started. Requires journal-confirmed 20_USA success.

## Environment learnings (do these, don't rediscover them)

- Run pytest as `& 'C:\Users\Work\miniconda3\python.exe' -m pytest -q --ignore=tmp`.
  `tmp/pytest` is an access-denied artifact directory that breaks collection.
  Do not delete or re-ACL it.
- Two unrelated user processes run `run_mapping_pipeline.py` in `leap_mappings`
  (PIDs 21620, 26116 at session start). NEVER touch them. They rewrite
  `leap_mappings/config/outlook_mappings_master.xlsx` (last seen 17:42) — mapping
  validation results can shift between runs because of this.
- The managed runner re-verifies expected production config at import time and
  applies ONLY the authorized overrides. Reuse it. For phase 3, copy it to a new
  runner with `REQUESTED_ECONOMIES` = the canonical 21-economy list from
  `workflow.ECONOMIES` (verify against the module, don't hardcode blindly).

## User decisions made this session (Finn, 2026-07-02/03 — do not re-litigate)

1. Subtotal mismatches in the mapping workbook are minor; runs must not block on
   them. Implemented properly (not a blanket waiver): the validator in
   `codebase/utilities/energy_balance_template_extractor.py` now prefers AUTHORED
   subtotal flags and honors the reviewed exception sheet
   `leap_mappings/config/mapping_issue_exception_sets.xlsx::subtotal_mismatch_allowed`.
   Computed-vs-authored disagreements go to CSVs under
   `outputs/leap_exports/supply_reconciliation/supporting_files/checks/` (not blocking).
   The env var `LEAP_INIT_ALLOW_SUBTOTAL_MISMATCH` exists but is RETIRED from the runner.
2. Fully identical duplicate mapping rows (18 in `leap_combined_ninth`, likely from
   the concurrent maintenance run) are dropped losslessly when
   `LEAP_INIT_DROP_EXACT_DUPLICATE_MAPPINGS=1` (set in the runner; user-authorized).
   Key-duplicates with DIFFERING content still block — do not waive those.
   CSV of the 18: `managed_runs/leap_combined_ninth_dropped_duplicate_rows_20260702.csv`.
3. Producer ownership: transfer-adjacent modules (Refinery and blending transfers,
   Upstream liquids transfers) belong to the transfers workbook ONLY. Implemented in
   `codebase/functions/supply_leap_io.py` (tier-2 zero-fill scopes no longer union).
4. USA Target-scenario hydrogen = 0 is a LEGITIMATE modelling decision (9th data is
   correct). Zero activity must not break scenario coverage (SEED-010).
5. Zero-activity completion is STANDARD behavior, not module-specific:
   `build_zero_skeleton_record` emits the full key set (zero output series, inert
   efficiency placeholder).
6. Cross-scenario borrowing (both implemented): all-zero share groups borrow the
   donor scenario's genuine profile (Reference > Current Accounts > Target,
   nearest-year, renormalized to 100, still gated on explicit zero capacity) before
   any synthetic anchor — in `complete_canonical_share_groups`; zero-skeleton records
   borrow efficiency/auxiliary/own-use measures from a donor scenario via
   `borrow_zero_skeleton_measures` — wired in `save_transformation_exports_with_split_targets`.
   Documented in INIT-003 (docs/special_rules_and_design_decisions.md).

## Task changes on disk (uncommitted; preserve, do not revert)

- `codebase/utilities/energy_balance_template_extractor.py` — authored-flag +
  exception-set subtotal validation; env-gated duplicate drop; diagnostic CSVs.
- `codebase/functions/supply_leap_io.py` — producer ownership scopes; all-scenario
  record collection + borrow step in the transformation export writer.
- `codebase/functions/transformation_record_builder.py` — complete zero skeletons
  (is_zero_skeleton marker) + borrow_zero_skeleton_measures().
- `codebase/functions/transformation_sector_analysis.py` — hydrogen: zero skeletons
  on the all-output-series-zero path (other sectors keep skip behavior).
- `codebase/functions/transformation_analysis_utils.py` — re-export of
  borrow_zero_skeleton_measures.
- `codebase/functions/baseline_seed_validation.py` — pass-0 donor profiles +
  cross-scenario share borrowing; SHARE_DONOR_SCENARIO_PRIORITY.
- `tests/test_zero_skeleton_scenario_borrowing.py` — NEW (3 tests).
- `docs/special_rules_and_design_decisions.md` — INIT-003 rule + history updated.
- `codebase/functions/supply_preflight.py` — PRE-EXISTING modification (not ours).

## Watch items for the remainder of the run

- If attempt 5 fails with new SEED findings, check first whether the module's
  analysis path skips records on zero data (no skeleton written) — hydrogen was
  fixed; LNG/gas-processing have some remaining skip guards. Electricity/CHP/heat
  interim and transfers are scenario-symmetric by construction (no risk).
- Subtotal diagnostic CSVs (508 esto / 692 ninth computed-vs-authored rows) are for
  later mapping review in leap_mappings — not blockers.
- On 20_USA success: verify primary outputs per the base prompt, journal, then
  proceed to Phase 3 with a full fresh regression gate ONLY if source changed.
- SEED-010/SEED-001 for OTHER economies may reveal new cases; same diagnosis
  pattern applies (findings CSV next to the combined workbook under
  `workbooks/supporting_files/baseline_seed_validation/`).

## Update 2026-07-03 ~02:00 (attempt 5 outcome)

- Attempt 5 cleared SEED-010 but exposed a phantom process: HYDROGEN_PROCESS_CONFIG
  enables 09_13_02_smr_wo_ccs, which has NO branch in the LEAP model. The all-zero
  skeleton fallback emitted rows for it (SEED-003/004/007/011, 33 findings).
- Fix: `codebase/functions/supply_leap_io.py` now drops zero-skeleton records whose
  process branch is absent from the full-model catalog (prefix match on
  Transformation\{sector}\Processes\{process}), logged as [INFO].
- Attempt 6 pending fresh gate (pytest_full_suite_20260703_0156.log).
