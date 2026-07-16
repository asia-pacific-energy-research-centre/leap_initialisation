# 12_NZ baseline-seed hardening and readiness prompt

Type: staged implementation, verification, and gated single-economy run.

## Start gate

I would not run the full workflow until the hardening and readiness audit are
clean, unless you explicitly authorize that run too. If you do authorize it, I
can launch it in the background and only check progress at the required
10-minute cadence.

## Short version

Make every template authoritative for its own economy, beginning with the
reset-scope chain. Treat 12_NZ as a valid structural reference, not as a broken
copy of the USA template. Compare any fresh 12_NZ seed against the prior NZ
baseline seed after the final emit boundary, classify differences, and preserve
existing diagnostics for genuinely absent branches.

## Modelling direction

- A branch-path difference between NZ and USA is not itself an error.
- `_COMP_GEN` templates are not automatically more authoritative than an
  economy's resolved template.
- Never substitute USA paths or IDs for missing NZ branches.
- Existing validation remains the safety net: unresolved nonzero IDs block;
  zero unresolved rows remain review/warning findings as currently configured.
- Known USA-only transformation non-specified auxiliary-fuel values and missing
  NZ Demand/Other loss and own use branches are structural/data diagnostics to
  report, not reasons to make template fallback logic.

## Objective

Reach a documented go/no-go decision for one `12_NZ` baseline-seed run by:

1. removing USA-template leakage from reset scope and other live paths;
2. proving each economy uses its own resolved template and cache entry;
3. auditing current NZ inputs/workbooks/template readiness without a full run;
4. comparing a future fresh NZ seed to the prior NZ seed only after
   `prepare_seed_rows_for_write`; and
5. fixing only mechanical routing/compatibility defects found before the run.

## Stage 1: reset-scope chain

Investigate and migrate `supply_preflight` reset scope first.

- `_load_reset_scope_from_full_model_export` must accept an explicit template
  path (or economy resolved through the canonical resolver) and cache by the
  resolved source path.
- `_configured_reset_module_names`, `_configured_reset_fuel_labels`, and
  `_configured_reset_output_fuel_labels_by_module` must accept and pass through
  that template context.
- `reset_supply_and_transformation_import_export_to_zero` must partition work
  by economy when its input holds multiple economies, deriving each partition's
  scope from that economy's template. A single shared USA scope is insufficient.
- Thread context through `supply_results_saver`, `supply_leap_io`,
  `supply_reconciliation_workflow`, and other callers only where they actually
  decide reset scope. Preserve standalone legacy defaults only when no economy
  context is available.

Use synthetic USA/NZ-like template fixtures with deliberately different branch
sets. Prove no cache reuse crosses source paths and that the NZ reset scope does
not enumerate a USA-only branch.

## Stage 2: remaining live template routes

Audit every remaining `full model export.xlsx` default listed in
`docs/work_queue.md` item [7]. For each one, classify it as:

- must resolve per economy now;
- deliberate shared structural reference; or
- standalone-only compatibility default.

Migrate only the first class, in focused commits. Check callers as well as
function defaults: an explicit pinned `id_lookup_path` can bypass a correctly
routed helper.

Do not touch the `GLOBAL_REGION` decision or `fuel_catalog_preflight` question
without separate evidence; both are explicitly outside this prompt.

## Stage 3: 12_NZ readiness audit

Without running the full reconciliation workflow:

1. Resolve and inspect the NZ template and its structural branch universe.
2. Locate the most recent prior `leap_import_baseline_seed_12_NZ*.xlsx` and
   record its timestamp/path as the comparison baseline.
3. Run the applicable template/ID/branch readiness and focused preflight checks.
4. Inspect current producer artifacts only where they exist; missing artifacts
   are a readiness finding, not a reason to fabricate data.
5. Produce a concise diagnostic table with: category, branch/measure, whether
   it is USA-only/NZ-only/shared, value class (zero/nonzero where known), current
   validation outcome, and recommended action.

## Stage 4: gated baseline-seed run (only with explicit authorization)

Do not start this stage unless the user explicitly authorizes the 12_NZ run
after reviewing the hardening/readiness result.

- Use the current baseline-seed preset restricted to `ECONOMIES=["12_NZ"]`.
- Do not modify modelling settings merely to obtain a clean run.
- Launch in the background and poll at most once every 10 minutes.
- Let the workflow run to completion; do not interrupt it to inspect progress.
- Compare the finished, post-boundary seed with the recorded prior NZ seed on
  `(Branch Path, Variable, Scenario, Region, Expression)` plus IDs/metadata.
- Classify differences before changing code: intended routing correction,
  expected current-model correction, benign format/year-window change, or
  actionable regression.

## Constraints

- Run `git status --short` before every edit; stop if relevant files are dirty.
- One coherent commit per routing slice. Do not mix refactor, data change, and
  long-run verification in one commit.
- Do not add missing branches to LEAP, mappings, or templates in this task.
- Do not suppress SEED findings, downgrade diagnostics, or add broad exceptions
  merely because NZ lacks a USA branch.
- Never compare raw producer output with a completed seed; always compare
  post-`prepare_seed_rows_for_write` output.
- Use the economy-template resolver for all economy-specific paths.

## Verification

- Focused unit tests for reset scope source-path cache keys and multi-economy
  partitioning.
- Existing reset/preflight/template-resolver tests and `tests/test_check_registry.py`.
- `git diff --check` before each commit.
- No full workflow run until the explicit gate is met.

## Stop conditions

Stop and report instead of changing code if:

- the resolved NZ template is missing or cannot be read;
- a caller cannot receive economy/template context without changing workflow
  methodology;
- a discrepancy requires a modeller decision about branch existence or values;
- the old NZ seed cannot be located; or
- the readiness audit finds nonzero unresolved-ID rows.

## Deliverables

1. Focused routing commits with tests.
2. A 12_NZ readiness/audit note and the exact prior-seed comparison path.
3. A clear go/no-go recommendation for the authorized full run.
4. Post-run comparison findings only if Stage 4 is explicitly authorized.

## Update before use

Re-check the baseline-seed preset, 12_NZ template resolver path, existing NZ
seed filename, reset-scope callers, and all item-[7] constants with `rg` before
editing. Paths and callers are expected to change as the rollout progresses.
