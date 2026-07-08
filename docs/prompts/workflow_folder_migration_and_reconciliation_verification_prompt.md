# Workflow Folder Migration and Reconciliation Verification Prompt

## Short Version

You are working in the repository:
C:\Users\Work\github\leap_initialisation

Task:
Run the workflow script:
C:\Users\Work\github\leap_initialisation\codebase\supply_reconciliation_workflow.py

Run mode:
- Use `_PRESET_BASELINE_SEED`
- Set `THROW_ERROR_AFTER_RUN = True`

Economies:
- ECONOMIES_RUN_ORDER:
  [
    "21_VN", "20_USA", "19_THA", "05_PRC", "13_PNG", "15_PHL", "12_NZ",
    "11_MEX", "10_MAS", "02_BD", "01_AUS",
    "03_CDA", "04_CHL", "06_HKC", "07_INA", "08_JPN", "09_ROK",
    "14_PE", "16_RUS", "17_SGP", "18_CT"
  ]

Scenarios:
- SCENARIOS = ["Target", "Reference", "Current Accounts"]

Execution rules:
- Run one economy at a time.
- Do not stop early on validation errors.
- Continue through all economies unless the workflow itself cannot proceed safely.
- Let the workflow collect issues and raise only at the end when `THROW_ERROR_AFTER_RUN = True` so that we can prodcue the full output in C:\Users\Work\github\leap_initialisation\outputs\leap_exports\supply_reconciliation ( such as leap_import_baseline_seed_20_USA_20260706.csv)
- Record warnings and non-fatal issues as they occur.
- Preserve outputs and logs in the normal workflow locations.
- Do not rename or move outputs outside the repo’s standard workflow folders.

Polling / monitoring:
- Follow the repo’s run conventions.
- Once the workflow is running, do not poll more frequently than every 20 minutes.
- If the run is healthy, use the workflow’s normal progress output and only check at sensible intervals.
- If a stall is suspected, note it in the report rather than force-stopping unless absolutely necessary.

Logging / reporting:
- Track start and end time for each economy.
- Track start and end time for each scenario if available.
- Track warnings, non-fatal issues, and fatal errors.
- At the end, produce a concise report with:
  - which economies completed successfully
  - which economies had warnings
  - which economies had errors
  - a summary of the main grouped issues
  - any economies or scenarios needing follow-up

## Objective

Move every active workflow entrypoint in `codebase/` into a dedicated
`codebase/workflows/` folder, leaving only
`codebase/supply_reconciliation_workflow.py` at the top level of `codebase/`.

At the same time, fully test `codebase/supply_reconciliation_workflow.py`
end-to-end so the refactor is not accepted unless the main reconciliation flow
still runs correctly after all import and path updates.

## Why this matters

The root `codebase/` folder currently mixes the main reconciliation workflow
with many other workflow entrypoints. That makes the repo harder to scan and
increases the chance that people run the wrong script by accident.

The main reconciliation workflow is the central workflow in this repo and
should remain the only workflow file at the root. Everything else should be
grouped under `codebase/workflows/` so the active entrypoint surface is clearer.

## Scope

Move the following workflow entrypoints out of the root `codebase/` folder and
into `codebase/workflows/`:

- `aggregated_demand_workflow.py`
- `baseline_seed_comparison_workflow.py`
- `electricity_heat_interim_workflow.py`
- `hydrogen_transformation_workflow.py`
- `minor_demand_workflow.py` if still retained in active form, or keep it in
  `codebase/archive/` if it is already considered legacy
- `other_loss_own_use_proxy_workflow.py`
- `outlook_mapping_maintenance_workflow.py` if it still exists in this repo
- `refining_workflow.py`
- `supply_workflow.py`
- `transfers_workflow.py`
- `transformation_entry.py`
- `transformation_workflow.py`

Do not move:

- `codebase/supply_reconciliation_workflow.py`

Also update any direct import sites, notebook helpers, tests, scripts, docs, and
smoke-test commands that reference the old root-level module paths.

## Important constraint

This is not just a file move.

Every module that imports these workflows, or is imported by them, must be
updated to the new module paths. Any stale root-level import strings should be
treated as part of the migration work, not deferred cleanup.

## Required verification

### 1. End-to-end reconciliation test

Run a full verification of `codebase/supply_reconciliation_workflow.py`.

Requirements:

- Use the real workflow, not a unit-test stub.
- Let it run to completion.
- Verify that the full workflow still resolves imports and produces its expected
  outputs after the move.
- Capture and report any breakage introduced by the path changes.
If the workflow is too expensive to rerun in full for every iteration, run the
most complete practical verification and explicitly state what was and was not
covered.

### 2. Import/update verification

Confirm that:

- no code still imports the moved workflows from their old root-level paths;
- the new `codebase/workflows/` import paths are used consistently;
- the tests that reference moved workflows still pass;
- docs and prompt files do not point at obsolete root-level paths unless they
  are intentionally describing the migration history.

### 3. Test suite checks

At minimum, run targeted tests for:

- `tests/test_supply_reconciliation_capacity_unmet_iterative.py`
- `tests/test_supply_reconciliation_everything_combiner.py`
- `tests/test_iterative_pass_archive_simulation.py`
- `tests/test_minor_demand_workflow.py` if `minor_demand_workflow.py` remains in scope
- any workflow-specific tests that directly import a moved module

If any root-level import is preserved temporarily for compatibility, record that
explicitly and explain why it must remain.

## Expected implementation shape

Use a compatibility-first migration:

1. Create `codebase/workflows/` as a package.
2. Move one workflow at a time.
3. Update import sites in the repo.
4. Keep temporary shims at old paths only if needed to avoid breaking callers
   while the migration is in progress.
5. Remove shims once all internal and test references are updated.

Prefer to move the least coupled workflows first and leave the most coupled
modules until the import graph is stable.

## Suggested Move Order

Use this order unless the dependency audit shows a better constraint:

1. `baseline_seed_comparison_workflow.py`
2. `minor_demand_workflow.py` if it is still considered active rather than archive-only
3. `hydrogen_transformation_workflow.py`
4. `supply_workflow.py`
5. `transformation_entry.py`
6. `refining_workflow.py`
7. `transfers_workflow.py`
8. `aggregated_demand_workflow.py`
9. `electricity_heat_interim_workflow.py`
10. `other_loss_own_use_proxy_workflow.py`
11. `transformation_workflow.py`
12. `outlook_mapping_maintenance_workflow.py` if it is still retained in active form

Keep `supply_reconciliation_workflow.py` at the root throughout.

## File-By-File Candidate Notes

### Good first candidates

- `baseline_seed_comparison_workflow.py`: usually a self-contained comparison tool.
- `transformation_entry.py`: thin orchestration wrapper.
- `hydrogen_transformation_workflow.py`: typically a narrower variant of the main transformation flow.

### Medium-risk candidates

- `supply_workflow.py`
- `refining_workflow.py`
- `transfers_workflow.py`
- `aggregated_demand_workflow.py`
- `electricity_heat_interim_workflow.py`
- `other_loss_own_use_proxy_workflow.py`

### Higher-risk candidates

- `transformation_workflow.py`
- `outlook_mapping_maintenance_workflow.py` if still active
- `minor_demand_workflow.py` if not already archived

For each candidate, record:

- current import sites
- direct test coverage
- doc references
- whether a temporary shim is needed
- whether the move should wait until the main reconciliation workflow is fully
  verified

## Things to record in the migration notes

Document every code path that had to change because of the move:

- direct imports in Python modules
- test imports
- notebook helper imports
- CLI / smoke-test commands
- docs references
- any archive or legacy exceptions
- whether the module now lives under `codebase/workflows/` or `codebase/archive/`

If a workflow is intentionally excluded from the move, record the reason.

## Acceptance criteria

The refactor is done only when all of the following are true:

- `codebase/supply_reconciliation_workflow.py` still works end-to-end
- the moved workflows are accessible from `codebase/workflows/`
- no stale root-level imports remain for the moved workflows
- tests pass
- the repo clearly shows that `supply_reconciliation_workflow.py` is the only
  workflow entrypoint left at the root of `codebase/`

## Notes

- This repo is notebook-first, so preserve notebook-safe execution patterns.
- Do not rewrite workflow logic while moving files unless the migration requires
  a small compatibility fix.
- Be explicit about any workflow that is now legacy/archive instead of active.
