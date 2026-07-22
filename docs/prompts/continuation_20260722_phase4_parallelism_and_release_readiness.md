# Continuation prompt — Phase 4, safe parallelism, and release readiness

Status: active handoff created 2026-07-22. Read this file first, then
`docs/current_execution_roadmap.md`, `docs/work_queue.md`, and the detailed
Phase 4 brief before editing code.

## Where the previous session stopped

The workflow has just completed a sequence of tested, committed safety and
refactor changes. The working tree was clean before the overnight run launch.
Do not assume the overnight full-horizon run succeeded: inspect its uniquely
labelled log, output directory, process state, and restored configuration.

Recent commits, oldest to newest, are:

- `ce88455` — aggregate compressed preflight now routes only `00_APEC` to its
  aggregate source files. This reduced preflight from roughly 36 minutes to
  8–9 minutes in AUS two-year verification.
- `072242a` — G2 demand-zeroing safeguard; branches removed from an aggregate
  placeholder are not zeroed as well.
- `3bf0e43`, `6ebb3c3`, `f571945` — Phase 4 B2 allocation ledger introduced,
  threaded through both capacity-unmet passes, then its reverse wrapper mirror
  removed. Legacy underscored module views remain only for direct legacy calls
  and monkeypatch compatibility.
- `50ae012`, `d557dab`, `4a7e4ce`, `cf13e04` — Phase 4 B3 immutable
  `ReconciliationRunContext`, results-saver path injection, remaining output
  family injection, and preflight context injection.

Focused verification completed before the overnight run:

- B2 ledger/threading/mirror suites: 90 tests passed.
- Initial B3 context suite: 91 tests passed.
- Saver-context suite: 113 passed, 5 skipped.
- Remaining saver paths: 24 passed.
- Preflight context suite: 68 passed, 5 skipped.
- Final G2 two-year AUS run: compressed preflight 8m54s; main run 24m28s;
  aggregate zeroing skipped, no demand-zeroing workbook (expected), timing
  history tagged `y2022-2023-n2`, and config restored.

## Overnight run in progress / first-morning check

The user requested a sequential full-horizon baseline-seed run only for the
economies with real templates rather than `_COMP_GEN` templates:

```python
["12_NZ", "01_AUS", "20_USA", "02_BD"]
```

It must run with an explicit dated output label and `TEST_HORIZON_BASE_YEAR_PLUS_ONE=False`.
Read `docs/prompts/supply_reconciliation_full_baselineseed_run_execution_prompt.md`
for the run procedure and inspect its recorded timestamped logs/metadata.

Important run rules:

- Do not interrupt a healthy run. Poll only every 30 minutes as requested.
- Do not commit or edit Python workflow modules while it runs; lazy imports can
  create a mixed-version process.
- Verify the pinned interpreter is `C:\Users\Work\miniconda3\python.exe`.
- At completion restore `ECONOMIES = ECONOMIES_RUN_ORDER`,
  `RUN_OUTPUT_LABEL = "auto"`, and the normal two-year default
  `TEST_HORIZON_BASE_YEAR_PLUS_ONE = True`.
- If it fails, preserve logs and findings. Repair/relaunch only a clear,
  narrow, general code defect related to the recent work; otherwise leave the
  diagnosis for the user. Never loosen validation or patch mapping/data
  decisions merely to obtain files.

## Immediate engineering priority after the run

The agreed priority is **bounded process-based economy parallelism before the
eventual release fleet**, not a complete cleanup of every Phase 4 concern.
Never enable shared-interpreter/thread parallelism. The current
`supply_results_saver.py` deliberately rejects `PARALLEL_ECONOMY_WORKERS > 0`;
that guard must remain until a new safe implementation is proven.

First, assess what B3 still leaves global:

1. `_refresh_output_paths_for_current_pass_mode()` and compressed-preflight
   compatibility code still apply/restore global config overrides.
2. `supply_preflight._broadcast_config_overrides()` remains a broad
   compatibility mechanism; it must not be casually deleted.
3. Star-imported config copies and the source-file module literal `ECONOMIES`
   remain unsafe for simultaneous processes if a worker can late-import the
   changed source file.

Design the minimum safe boundary:

1. Give each worker an immutable, explicit configuration snapshot (economy,
   scenario/preset, run label, run context, paths, test horizon), passed at
   process launch rather than editing `supply_reconciliation_workflow.py`.
2. Each worker writes isolated logs, locks, timing history, convergence
   artifacts, and output directories. Define a deterministic parent merge and
   collision rules before implementation.
3. Add tests proving two worker snapshots cannot cross-read `ECONOMIES`, label,
   paths, or preflight state.
4. Implement process-based—not thread-based—parallel execution behind an
   opt-in worker count defaulting to one.
5. Verify sequential equivalence first, then a deliberately controlled
   two-economy **two-year** smoke test. Do not run concurrent full-horizon
   economies first.

Only after that succeeds should parallelism be used for a future retained
full-horizon fleet. Re-measure `supply_results_saver` coupling afterward;
splitting it is deferred unless evidence requires it.

## Full-horizon output follow-up: clearing stale LEAP values and template readiness

The successful four-real-template full-horizon run is retained at
`baseline_seed/runs/SEED_4REAL_TEMPLATES_FULL_20260722`. Its zero validation
findings do not mean every template/import contract is complete. Inspect these
diagnostics before declaring the outputs fully LEAP-import-ready:

- `supporting_files/checks/supply_reconciliation_unmatched_id_rows.csv`:
  six `02_BD` rows, covering two absent feedstock branches (Coke oven gas and
  Other products) across three scenarios.
- `supporting_files/checks/supply_reconciliation_metadata_mismatches.csv`:
  six `20_USA` non-specified-own-use Electricity metadata cells (generated
  Units/Scale disagree with the reference Share/% contract).
- `supporting_files/checks/supply_reconciliation_config_mapping_mismatches.csv`:
  91 configuration/reference metadata mismatches (units and `per`).

Build a template-readiness audit from the full-horizon generated output:
classify every requested-but-absent branch as non-zero required, zero-only
structural, or intentional suppression. A non-zero requested branch requires
a real template migration/BranchID; it must never be hidden by a zero row.
For an always-zero structural branch, decide explicitly whether the branch
belongs in every intended-identical template or should be an approved
suppression. Use the same audit to establish the authoritative Units/Scale/
`per` metadata contract before changing producers or config.

### Important [18] design correction to decide and implement

Current [18] behaviour emits a separate
`supply_transformation_zeroing_{economy}.xlsx` file with explicit zero rows,
imported before the main workbook. It does **not** modify the template file,
but it is a second import artifact rather than explicit zero rows in the
baseline seed. The user has specified the preferred end state: when a branch
has no explicitly generated baseline value, the baseline seed itself should
carry an explicit zero so importing that seed clears an old LEAP-area value.

Treat that as a new output-affecting design/implementation task. Do not simply
append every conceivable template branch: derive the exact eligible branch
scope from the per-economy template and preserve all explicitly generated
values. Prove with an A/B test that generated values are unchanged, previously
unset eligible branches are explicit zeroes in the baseline seed, and no
unrelated branch/scenario/year is introduced. Revisit whether the companion
zeroing workbook remains necessary only after that evidence exists.

## Product-readiness critical path beyond parallelism

1. In `leap_mappings`, complete M2: connect the pipeline to
   `outlook_mappings_master.xlsx` and apply Stage-1 rollups. This is the
   cross-repo blocker for real comparison data and canonical mapping-driven
   downstream outputs.
2. Validate the mapping pipeline on real economies, then move this workflow
   from legacy mapping workbooks to the canonical master.
3. Complete only output-affecting scoped modelling reviews (aggregated demand,
   refining, own-use proxy, presets) as explicit decisions.
4. Obtain/validate real per-economy templates and trustworthy seeds. Do not
   regard regeneration against `_COMP_GEN` templates as independent evidence.
5. Do a deliberate release-level full-horizon verification on representative
   economies, then produce useful fleet outputs using unique labels.

## Active documentation

- `docs/current_execution_roadmap.md` is the current operational ordering.
- `docs/work_queue.md` records traps and outstanding work; update it when a
  decision or phase boundary changes.
- `docs/prompts/phase_4_monolith_decomposition_execution.md` is the B2/B3
  detailed contract.
- `docs/prompts/phase_5_feature_improvements_execution.md` owns G1/G2;
  both are implemented and verified, so archive/update that prompt only after
  confirming its remaining sections are complete.

Commit every coherent, tested change with a `codex:` prefix. Do not commit
temporary run configuration. Once a prompt is fully complete, move it from
`docs/prompts/` to `docs/archive/` with its findings/status record.
