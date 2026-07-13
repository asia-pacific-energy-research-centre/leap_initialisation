# Split `supply_reconciliation` Outputs by Pass Mode

## Objective

`codebase/supply_reconciliation_workflow.py` currently writes both
`baseline_seed` and `results_update` passes into the same flat directory tree
under `outputs/leap_exports/supply_reconciliation/`, with no directory-level
signal for which preset produced a given file. The per-economy combined
workbook is even named `leap_import_baseline_seed_<economy>_<date>.xlsx`
regardless of which preset wrote it — that name is a historical artifact, not
a claim about pass mode, and it caused real confusion when reviewing results
from a `results_update` run (see conversation context: a fresh `results_update`
output was momentarily misread as a stale baseline-seed leftover because nothing
in the path or name distinguished them).

Fix this by writing outputs to two parallel subtrees based on
`CAPACITY_UNMET_PASS_MODE`:

- `outputs/leap_exports/supply_reconciliation/baseline_seed/...` when
  `CAPACITY_UNMET_PASS_MODE == "baseline_seed"`
- `outputs/leap_exports/supply_reconciliation/results_update/...` when
  `CAPACITY_UNMET_PASS_MODE == "results_update"`

Everything that currently lives under
`outputs/leap_exports/supply_reconciliation/` (workbooks/, supporting_files/,
preflight_compressed_projection/, the top-level `supply_recon_run_*.xlsx`
single-file workbook, and the `leap_import_baseline_seed_*.xlsx` per-economy
files) should move one level deeper into the matching subtree. Do **not**
rename the `leap_import_baseline_seed_*.xlsx` filename pattern itself in this
pass — the directory split is the fix; renaming the file too is a separate
decision the user hasn't made yet, and `patch_baseline_seeds.py`/
`baseline_seed_comparison_workflow.py` glob on that exact pattern.

## Before starting

1. Read `AGENTS.md` in full, and the timing-history section specifically —
   this change affects `WorkflowTimer.write_csv()` output paths too (see
   Task 5 below), and the timing history filenames encode run metadata that
   downstream averaging logic depends on.
2. Run `git status --short` and preserve all unrelated in-progress changes
   (there are known uncommitted changes to `other_loss_own_use_proxy_utils.py`,
   `supply_reconciliation_workflow.py`, and `leap_balance_export_resolver.py`
   as of 2026-07-13 — do not stage, discard, or conflict with them; rebase
   your edits to `supply_reconciliation_workflow.py` around the existing diff
   rather than reverting it).
3. Confirm no supply_reconciliation workflow process is currently running
   (`Get-Process python`) before doing any live-run verification.

## What to change

### 1. Root path constants — `codebase/supply_reconciliation_config.py`

This is the center of the change. Today:

- `OUTPUT_DIR = INTEGRATED_LEAP_EXPORTS_ROOT` (line ~152), where
  `INTEGRATED_LEAP_EXPORTS_ROOT` is defined in
  `codebase/utilities/output_paths.py:19` as
  `LEAP_EXPORTS_ROOT / "supply_reconciliation"`.
- `EXPORT_OUTPUT_DIR = OUTPUT_DIR / "workbooks"` (line ~158)
- `TRANSFORMATION_EXPORT_OUTPUT_DIR = EXPORT_OUTPUT_DIR` (line ~160)
- `RESULTS_SINGLE_FILE_ARCHIVE_DIR`, `RESULTS_CHECKS_DIR`,
  `RESULTS_RUNTIME_DIR` (lines ~235-237), all `OUTPUT_DIR / "supporting_files" / ...`

Change `OUTPUT_DIR` to be computed from `CAPACITY_UNMET_PASS_MODE`:

```python
_PASS_MODE_SUBDIR = {
    "baseline_seed": "baseline_seed",
    "results_update": "results_update",
}
OUTPUT_DIR = INTEGRATED_LEAP_EXPORTS_ROOT / _PASS_MODE_SUBDIR[CAPACITY_UNMET_PASS_MODE]
```

Confirm `CAPACITY_UNMET_PASS_MODE` is already defined/imported before this
point in the module (it's unpacked from the active preset in
`supply_reconciliation_workflow.py` via `globals().update(ACTIVE_PRESET)` —
verify the import order so `supply_reconciliation_config.py` sees the correct
value at the time `OUTPUT_DIR` is computed; this may require moving the
`OUTPUT_DIR` computation to be lazy (a function) rather than a module-level
constant if config is imported before the preset is unpacked. Check current
import order in `codebase/supply_reconciliation_workflow.py` around line 63
(`from codebase.supply_reconciliation_config import *`) versus where
`ACTIVE_PRESET` is unpacked (line ~804) before deciding whether a plain
constant is safe or whether `OUTPUT_DIR` needs to become
`get_output_dir()`/a property. If it must become a function, every
downstream consumer of `OUTPUT_DIR`/`EXPORT_OUTPUT_DIR`/etc. as a bare
import-star name needs updating to call it instead — trace this carefully,
it's the highest-risk part of this task.

Everything downstream (`EXPORT_OUTPUT_DIR`, `TRANSFORMATION_EXPORT_OUTPUT_DIR`,
`RESULTS_SINGLE_FILE_ARCHIVE_DIR`, `RESULTS_CHECKS_DIR`, `RESULTS_RUNTIME_DIR`)
derives from `OUTPUT_DIR` already, so fixing the root should cascade
automatically — but verify each one is still computed *after* `OUTPUT_DIR`
resolves to the mode-specific path, not cached from an earlier import.

### 2. `run_preflight_compressed_projection` — `codebase/functions/supply_preflight.py:1268`

This one hardcodes its own root instead of taking an `output_dir` parameter:

```python
preflight_root = _resolve(OUTPUT_DIR) / "preflight_compressed_projection"  # line ~1282
```

Once `OUTPUT_DIR` is mode-aware (Task 1), this should cascade for free — but
note the preflight step always runs against the `00_APEC` aggregate
regardless of `ECONOMIES`, and per the most recent run
(2026-07-13, PID 58440) `preflight_compressed_projection` for `00_APEC`
routinely fails on `results_update` presets with a `FileNotFoundError`
(00_APEC has no real LEAP balance export) — this is a pre-existing,
unrelated issue. Do not attempt to fix it as part of this task; just confirm
the preflight output directory itself lands in the correct
`results_update`/`baseline_seed` subtree when the preflight runs far enough
to write anything.

### 3. `write_per_economy_combined_workbooks` — `codebase/functions/supply_leap_io.py:1521`

Takes `output_dir: Path | str = OUTPUT_DIR` as a keyword default — once Task 1
lands, this default should already resolve correctly as long as the function
is called (from `supply_results_saver.py:3684-3695`) without an explicit
override. Verify the caller doesn't pass a stale/pre-resolved path captured
at import time.

The archival logic at `supply_leap_io.py:1982-1985` — which moves any
existing `leap_import_baseline_seed_{econ_token}_*.xlsx` into `archive/`
before writing a fresh one — should now naturally only see files from the
same pass-mode subtree, which is a secondary benefit of this change (today,
a `results_update` run's write can't distinguish an existing
`baseline_seed` file from a genuine same-mode leftover).

### 4. Other writers under the tree — all resolve via `output_dir` params already

These all take `output_dir` (or `supply_workbook_dir`/`aggregated_demand_dir`)
parameters defaulting to `EXPORT_OUTPUT_DIR`/`OUTPUT_DIR`, called from
`codebase/functions/supply_results_saver.py`. Confirm each cascades correctly
once Task 1 is done — do not add new parameters to these unless Task 1's
`OUTPUT_DIR` fix turns out to require becoming a function (see the note in
Task 1), in which case every one of these default arguments needs to change
from `output_dir=OUTPUT_DIR` to `output_dir=get_output_dir()` (or similar) at
each call site in `supply_results_saver.py`:

- `save_transformation_exports_with_split_targets` — `supply_leap_io.py:568`,
  called at `supply_results_saver.py:3335`
- `save_transfer_exports_with_supply_overrides` — `supply_leap_io.py:741`,
  called at `supply_results_saver.py:3345`
- `save_combined_supply_transformation_export` — `supply_leap_io.py:916`,
  called at `supply_results_saver.py:3369` (per-economy) and `:3702` (top-level)
- `build_electricity_heat_interim_workbooks_for_results_supply` —
  `supply_leap_io.py:1194`, called at `supply_results_saver.py:3361`
- `build_aggregated_demand_workbooks_for_results_supply` —
  `supply_leap_io.py:1277`, called at `supply_results_saver.py:3397`
- `save_results_linked_single_workbook` (writes the top-level
  `supply_recon_run_*.xlsx`) — `supply_results_saver.py:1251`, called at
  `supply_results_saver.py:3729` with `output_dir=OUTPUT_DIR`

**Explicitly out of scope**: `build_other_loss_own_use_proxy_workbooks_for_results_supply`
(`supply_leap_io.py:1087`) delegates to
`codebase/other_loss_own_use_proxy_workflow.py:assemble_proxy_workbook`, whose
output root is `GLOBAL_EXPORT_OUTPUT_DIR` =
`STANDALONE_LEAP_EXPORTS_ROOT` (`codebase/configuration/workflow_config.py:71`)
— this writes to `outputs/leap_exports/standalone/`, a completely different
tree, not `outputs/leap_exports/supply_reconciliation/`. Leave this alone;
it's not part of the path this task is fixing, and folding it in would
silently expand scope beyond what was asked.

### 5. Timing history — `WorkflowTimer.write_csv()`

Per `AGENTS.md`'s "Workflow Timing History" section,
`outputs/leap_exports/supply_reconciliation/supporting_files/runtime/` (via
`RESULTS_RUNTIME_DIR`) holds `workflow_stage_timings.csv` and a `history/`
subfolder of timestamped copies used by `load_history_summary()` for
run-time averaging (already filtered by `run_type` — `"full"` vs
`"preflight"` — and by economy/scenario count). Once `RESULTS_RUNTIME_DIR`
moves under the mode-specific subtree, **each mode's timing history starts
fresh** (baseline_seed runs and results_update runs are different
`run_type`-adjacent workloads anyway, so this is probably correct behavior,
not a regression — but confirm `load_history_summary()` doesn't have a
hardcoded absolute path assumption that breaks when the `runtime/` directory
moves one level deeper). Do not attempt to migrate old history files between
the two new subtrees; let each start clean.

### 6. Read-side consumers — must move in lockstep or accept a mode argument

These currently hardcode the flat pre-split path and will silently miss files
(not error — silently find nothing or find stale files) if left unchanged:

- `codebase/functions/patch_baseline_seeds.py:79` —
  `BASELINE_SEED_DIR = REPO_ROOT / "outputs" / "leap_exports" / "supply_reconciliation"`,
  globbed at `:1055` (`BASELINE_SEED_DIR.glob("leap_import_baseline_seed_*.xlsx")`).
  Given the name, this should almost certainly only look under the new
  `baseline_seed/` subtree — but read `patch_baseline_seeds.py`'s module
  docstring and `run_patch()` carefully first: confirm it is never used
  against `results_update` output before hardcoding it to the
  `baseline_seed/` subtree. Also check the `seed_dir` parameter at
  `patch_baseline_seeds.py:469` (`seed_dir.glob("leap_import_baseline_seed_*.xlsx")`)
  — trace its default/callers to see if it needs the same fix or already
  receives an explicit path.
- `codebase/baseline_seed_comparison_workflow.py:764-765` —
  `CANDIDATE_SEED_DIR = REPO_ROOT / "outputs" / "leap_exports" / "supply_reconciliation"`,
  with `COMPARISON_OUTPUT_DIR` derived from it, and `SEED_FILE_PATTERN`
  defined at `:48-49`. Read this script's purpose first — if it's meant to
  compare a `results_update` run's output against the prior `baseline_seed`
  pass (a plausible use case given the name), it may need **both** subtree
  paths as separate inputs rather than one root that should just be
  redirected. Do not guess; if the intent is ambiguous from the code, flag it
  for the user rather than picking one subtree arbitrarily.
- `codebase/scrapbook/backfill_level_cols_20260603.py:24` — one-off scrapbook
  script tied to a specific date-stamped file pattern
  (`leap_import_baseline_seed_*_20260603.xlsx`). This is throwaway/historical
  — leave it alone unless it's actively re-run; confirm with a quick check of
  its last-modified date and don't spend time on it otherwise.
- `c:\Users\Work\github\leap_dashboard\codebase\common_esto_dashboard_workflow.py:157`
  — hardcoded absolute path to
  `...\supply_reconciliation\supporting_files\runtime\capacity_unmet_convergence.csv`.
  This is in the **leap_dashboard repo**, a separate working directory. Per
  `AGENTS.md` routing rules, dashboard-side fixes belong in that repo, but
  this file will break (silently produce no data, most likely) once the
  runtime path moves. Fix this reference too — it reads
  `results_update`-style convergence diagnostics, so it almost certainly
  wants the `results_update/` subtree, but confirm by reading how the
  dashboard uses this file before hardcoding the new path.

## Migration of existing files

Do not attempt to auto-migrate every existing file in
`outputs/leap_exports/supply_reconciliation/` into the new subtrees — many are
stale from a mix of past `baseline_seed` and `results_update` runs, and
`outputs/` is very likely gitignored, so this isn't a tracked-file migration.
Leave existing flat-tree files where they are (they'll simply age out of
relevance) and let the next run of each preset populate the new subtree
fresh. Note this explicitly in your summary so the user knows old files at
the flat root are now orphaned, not deleted.

## Verification

1. Run a small compressed/preflight-only or single-economy dry run of each
   preset (baseline_seed and results_update) if time and LEAP availability
   allow, confirming outputs land under
   `outputs/leap_exports/supply_reconciliation/baseline_seed/` and
   `.../results_update/` respectively. If a live LEAP-backed run isn't
   practical in this task, at minimum trace the code path statically
   (`python -c` import + inspect resolved `OUTPUT_DIR`/`EXPORT_OUTPUT_DIR`
   values for both preset configurations) and say so explicitly rather than
   claiming a live-run verification that didn't happen.
2. Confirm `patch_baseline_seeds.py` and `baseline_seed_comparison_workflow.py`
   still resolve to sensible (non-empty, correct-mode) directories after the
   change — a smoke import/dry-run of their glob logic against whatever
   fresh output exists is enough; a full patch run is not required for this
   task.
3. Grep the full `codebase/` tree one more time after your edits for any
   remaining hardcoded `"supply_reconciliation"` path string literals that
   your changes may have missed (the initial research pass covered `codebase/`
   in `leap_initialisation` and `leap_dashboard`, but re-check
   `leap_mappings` too in case a mapping-side script grew a dependency since
   the last commit).

## Final report

Provide:

- Every file changed, with the specific line(s) and before/after path logic.
- Confirmation of how `OUTPUT_DIR` ended up being computed (module-level
  constant vs. lazy function) and why, given the import-order finding in
  Task 1.
- The decision made for `baseline_seed_comparison_workflow.py` (single
  redirected root vs. dual-subtree input) and the reasoning.
- Whether `patch_baseline_seeds.py`'s `seed_dir` parameter at line 469 needed
  a fix, and what you found tracing its callers.
- Any hardcoded path references found in `leap_mappings` during the final
  grep pass that weren't in the original research.
- Full `git status --short` and a summary distinguishing changes in
  `leap_initialisation` from the `leap_dashboard` fix (separate commits are
  appropriate if the user asks to commit, since these are different repos).
