# Supply reconciliation package migration plan

**Status:** feasibility confirmed; implementation intentionally deferred while a
full reconciliation process is running.  
**Worktree:** `C:\Users\Work\github\worktrees\leap_initialisation_reconciliation_package`  
**Branch:** `codex/reconciliation-package-migration`

## Decision

The reconciliation modules can be moved out of the `codebase/` root without
running the full 21-economy workflow during the refactor. Keep
`codebase/supply_reconciliation_workflow.py` at the root as the notebook-facing
entry point and move its implementation modules into a dedicated
`codebase/supply_reconciliation/` package.

The branch should remain unmerged after targeted verification. A production
workflow run is a later release gate, not part of the mechanical file move.

## Proposed package

Move the current root-level modules:

- `supply_reconciliation_config.py` -> `supply_reconciliation/config.py`
- `supply_reconciliation_allocation.py` -> `supply_reconciliation/allocation.py`
- `supply_reconciliation_history.py` -> `supply_reconciliation/history.py`
- `supply_reconciliation_balance_tables.py` -> `supply_reconciliation/balance_tables.py`
- `supply_reconciliation_results.py` -> `supply_reconciliation/results.py`
- `supply_reconciliation_utils.py` -> `supply_reconciliation/utils.py`

Also move the reconciliation-specific supporting modules currently mixed into
`codebase/functions/`:

- `supply_preflight.py` -> `supply_reconciliation/preflight.py`
- `supply_reconciliation_tables.py` -> `supply_reconciliation/tables.py`
- `supply_demand_mapping.py` -> `supply_reconciliation/demand_mapping.py`
- `supply_leap_io.py` -> `supply_reconciliation/leap_io.py`
- `supply_results_saver.py` -> `supply_reconciliation/results_saver.py`
- `capacity_unmet_convergence_diagnostics.py` -> `supply_reconciliation/convergence.py`
- `results_update_preview.py` -> `supply_reconciliation/results_update_preview.py`
- `parallel_economy_runner.py` -> `supply_reconciliation/parallel_runner.py`
- `parallel_economy_merge.py` -> `supply_reconciliation/parallel_merge.py`

Leave generic supply infrastructure such as `supply_data_pipeline.py`,
`supply_assets.py`, and `patch_baseline_seeds.py` in `codebase/functions/`.
Those modules serve workflows outside the reconciliation package even though
they call into it.

Use a deliberately small `supply_reconciliation/__init__.py`. Do not eagerly
re-export the subsystem because these modules already have circular imports and
module-level configuration state.

## Feasibility evidence

The move is mechanically possible, but it must be atomic within the branch:

- The six named implementation modules contain about 5,800 lines; the proposed
  reconciliation-specific supporting modules contain about 17,000 more.
- Live code and tests contain 99 direct references to the root-level
  reconciliation module paths across 30 files.
- Live code and tests contain 91 direct references to the proposed supporting
  module paths across 27 files.
- `allocation.py` and `history.py` intentionally use late imports to break a
  cycle, and `allocation.py` lazily imports the root workflow for compatibility.
  Relocation does not make that cycle worse if every target is updated in the
  same change.
- The preset broadcast scans loaded `codebase.*` modules. New
  `codebase.supply_reconciliation.*` module names still satisfy that rule.
- `parallel_economy_runner.py` deliberately launches the root workflow script
  by path. Keeping the workflow entry point at its current location preserves
  the subprocess contract.
- `config.py` currently calculates `REPO_ROOT` with
  `Path(__file__).resolve().parents[1]`; after the move it must use
  `parents[2]`. `history.py` has a matching repository-CWD calculation that
  must also be adjusted.
- Characterization tests read source files by their current paths and enumerate
  module names explicitly. These are expected migration edits, not behavior
  changes.

## Main risks

1. **Duplicated module state.** Temporary shims that import or star-re-export
   implementations can create a second module namespace. That is unsafe for
   config globals, monkeypatch targets, and allocation state. Prefer an atomic
   internal import update and no long-lived root shims.
2. **String-based monkeypatch targets.** Several tests patch fully qualified
   module strings. A normal import smoke test does not detect every stale patch
   target, so the targeted test set is required.
3. **Path depth changes.** The repository-root and subprocess-CWD calculations
   must be reviewed wherever they depend on `__file__`.
4. **Documentation history.** Active guides and check-registry paths should be
   updated. Archived prompts may retain old paths when they clearly describe
   historical structure.
5. **External notebooks.** Repository search cannot find imports in notebooks
   or scripts outside this checkout. The migration handoff must list the old and
   new import paths for human review.

## Implementation sequence

1. Create `codebase/supply_reconciliation/__init__.py`.
2. Move the six root-level implementation modules together and update all live
   imports, late imports, path calculations, tests, and active docs.
3. Run import/characterization checks before moving supporting modules.
4. Move the reconciliation-specific supporting modules together, then update
   generic callers such as `patch_baseline_seeds.py`.
5. Search live code and tests for every obsolete module path. Do not rewrite
   archived historical text solely to make the grep empty.
6. Commit the verified migration on this branch and leave it unmerged until the
   deferred workflow gate is run.

## Verification without a full model run

The migration can be checked to a useful confidence level without generating
new baseline seeds:

1. Compile/import every moved module and collect the affected tests.
2. Run the Phase 4 characterization and state-forwarding tests.
3. Run module-attribute, worker-snapshot, parallel-runner fake-worker, and
   parallel-merge tests.
4. Run the targeted reconciliation allocation, preflight, LEAP I/O, result
   saver, history, and results-update-preview unit tests.
5. Run `scripts/check_preset_forwarding.py`.
6. Confirm the subprocess runner still resolves
   `codebase/supply_reconciliation_workflow.py`.
7. Confirm no active Python process was used as verification and no workflow
   output was created by the migration tests.

Do not run the repository-wide suite blindly: the current work queue records
that it can exceed 20 minutes and fan out multi-gigabyte Python subprocesses.
Use the bounded targeted set first.

## Deferred release gate

Before merging to `master`, run the established shortest representative
reconciliation smoke (one economy and the test horizon) and compare its
post-boundary workbook with a known-good artifact. Keep the full-horizon,
multi-economy run for the next useful production-output boundary, as requested.
Record the deferred full run explicitly in the branch handoff if the package
migration is merged before that production run is available.

