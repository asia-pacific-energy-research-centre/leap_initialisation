# Task: Patch and verify baseline seed modules

Use this prompt when working on `codebase/functions/patch_baseline_seeds.py` or
when refreshing baseline seed files from module-specific workbooks.

## Current Context and Finalisation Goal

`patch_baseline_seeds.py` supports patching one or more modules into the existing
`leap_import_baseline_seed_{econ}_*.xlsx` files without running the full supply
reconciliation workflow. The supply, transfers, and losses/own-use source
workflows are now wired and have passed representative end-to-end checks.

For final operational checks, exercise the preset entry point as well as the
direct `run_patch()` function. The preset must set
`RUN_MODE="patch_baseline_seeds"`, the requested `PATCH_MODULE` list,
`PATCH_ECONOMIES`, and `PATCH_RUN_WORKFLOW=True`.

Known verified/fixed areas:

- `transfers` has been verified against the full workflow path.
- `power_interim` has been fixed for the interim electricity/CHP/heat sectors:
  - The interim workflow now uses canonical fuel display names from
    `leap_mappings/config/outlook_mappings_master.xlsx` / `leap_display_names`.
  - The old local `POWER_INTERIM_AMBIGUOUS_DISPLAY_NAMES` override should not be
    restored.
  - `Black liquor` should remain canonical; do not reintroduce the old
    `Black liqour` branch spelling in power-interim output.
  - Zero-valued output fuels in the export-year window are skipped, which avoids
    noncanonical zero output rows such as `Electricity interim\Output Fuels\Hydrogen`
    for `05_PRC`.
  - No-data CHP and heat skeletons now emit zero output-fuel, import/export
    target, historical production, and exogenous capacity rows.
  - Atomic canonical share-group guards are expected to pass for freshly
    regenerated power-interim workbooks.
- `aggregated_demand` and `supply` have been spot-verified against the full-run
  seeds (see Module Notes for the row counts and dates).
- The transformation auto-regen sectors are GATED: `run_patch()` raises
  `NotImplementedError` for them. Refresh those through the full workflow only.
- `losses_own_use` is patchable and verified end-to-end (including the Brunei
  retry); see Module Notes.

Important operational lesson:

- When `run_workflow=True`, the patcher must patch from the exact workbook paths
  generated in that run.
- Do not glob the workbooks directory for fresh data if exact fresh paths are
  available. Older scenario-order files such as
  `electricity_heat_interim_20_USA_Current_Accounts_Reference_Target.xlsx` can
  collide with the current
  `electricity_heat_interim_20_USA_Reference_Target_Current_Accounts.xlsx`
  workbook and produce duplicate-key conflicts.

## Quick Power-Interim Refresh Prompt

Use this when the goal is simply to recreate all power-interim seed rows for all
economies and report readiness as files are made.

Task: Recreate power-interim baseline seed rows for all economies.

Before running:
1. Read AGENTS.md and referenced instruction files.
2. Run `git status --short`; preserve unrelated existing changes.
3. Confirm the current code includes the power-interim canonical-name fixes:
   - no `POWER_INTERIM_AMBIGUOUS_DISPLAY_NAMES` override
   - no `Black liquor` -> `Black liqour` remap in `electricity_heat_interim_workflow.py`
   - zero-valued output fuels are skipped before output rows are written
4. Close any open Excel seed/workbook files if locked.

Run the patcher directly. Do not run the full supply reconciliation workflow.

Use:

```powershell
@'
from codebase.functions.patch_baseline_seeds import run_patch

run_patch("power_interim", economies=None, run_workflow=True)
'@ | C:\Users\Work\miniconda3\python.exe -
```

Requirements:
- Patch only `power_interim`.
- Do not patch transfers, supply, aggregated_demand, losses_own_use, or broad
  transformation.
- Use `run_workflow=True` so fresh
  `electricity_heat_interim_{econ}_Reference_Target_Current_Accounts.xlsx`
  workbooks are generated first.
- As each seed file is successfully written, report:
  `[READY] {economy}: {seed_file_path}`
- If the stock patcher output is not enough for per-file readiness, wrap the
  patcher internals in Python and print `[READY]` immediately after each
  `_patch_one()` call succeeds.
- If wrapping internals, collect rows only from the fresh workbook paths from
  the current run. Do not glob stale workbook variants.
- After all economies finish, run `validate_seed_files()` and report the result.
- Report final `git status --short`.

## Finalisation Goal

Treat the patcher as an operational seed-refresh path, equivalent to the
baseline/full-workflow refresh for its owned branch prefixes. Final checks are:

1. run the preset path for representative economies and then the requested
   economy set;
2. confirm the module-owned rows are replaced without touching unrelated
   prefixes;
3. run `validate_seed_files()` after each module batch;
4. record known proxy coverage/share diagnostics separately from patch failures.

Update the verdict comment above `_PRESET_PATCH_BASELINE_SEEDS` in
`codebase/supply_reconciliation_workflow.py` once the final Brunei
losses/own-use retry completes. Do not enable the preset as the module default.

## Verification Recipe

For a module `M` and an economy `E` whose config for `M` has not changed since
the last full run:

1. Copy `E`'s seed to a backup file outside the seed directory.
2. In a `try/finally` that always restores the backup, run:

```powershell
@'
from codebase.functions.patch_baseline_seeds import run_patch

run_patch("MODULE_NAME", economies=["ECONOMY"], run_workflow=True)
'@ | C:\Users\Work\miniconda3\python.exe -
```

3. Diff the module-owned rows before vs after, filtering by the module's branch
   prefixes.
4. Key rows on `(Branch Path, Variable, Scenario)`; do not key on `Region`.
5. Parse `Data(year,value,...)` expressions numerically before comparing values.
6. Classify differences:
   - Benign: float rounding, scenario-year trimming, canonical share-group
     completion.
   - Defect: rows only before, rows only after, or real non-benign value
     differences.
7. Pass criteria: zero rows only before, zero rows only after, and zero
   non-benign value differences.

Practical notes:

- Fresh Python processes spend several minutes loading reference tables. Batch
  checks into one script when possible.
- Run patcher code directly from PowerShell/Python. Avoid the full workflow log
  wrapper for patch verification.
- Validation guards such as `_assert_atomic_canonical_share_groups`,
  `resolve_logical_duplicates`, and `prepare_seed_rows_for_write` are useful
  diagnostics. Do not suppress them.
- Pick an economy with module data. Some economies legitimately have no rows for
  a module.
- Do not leave non-standard workbook filenames in
  `outputs/leap_exports/supply_reconciliation/workbooks/` when a later patch run
  might glob them.

## Module Notes

### transfers

Status: verified.

The patcher regen goes through `save_transfer_exports_with_supply_overrides`
with an empty reconciliation table, matching the full workflow export path.
Runtime strip prefixes are resolved from
`transfers_workflow.get_transfer_sector_titles()`.

### power_interim

Status: fixed for the current baseline-seed refresh process.

Use:

```powershell
@'
from codebase.functions.patch_baseline_seeds import run_patch

run_patch("power_interim", economies=None, run_workflow=True)
'@ | C:\Users\Work\miniconda3\python.exe -
```

Expected generated workbooks:

```text
outputs/leap_exports/supply_reconciliation/workbooks/electricity_heat_interim_{econ}_Reference_Target_Current_Accounts.xlsx
```

Expected seed scope:

```text
Transformation\Electricity interim\
Transformation\CHP interim\
Transformation\Heat plant interim\
```

For `01_AUS`, spot-check:

```text
Transformation\CHP interim\Output Fuels\Electricity
Transformation\CHP interim\Output Fuels\Heat
  variables: Output Share, Import Target, Export Target

Transformation\CHP interim\Processes\CHP interim
  variables: Historical Production, Exogenous Capacity
```

These rows should exist after patching. Import/export target, historical
production, exogenous capacity, and the no-data heat output rows should be zero.
The no-data Electricity output share may be 100 where Electricity is the active
single output and Heat is zero.

Known pitfalls:

- Do not restore local fuel-name overrides. The canonical mapping workbook is
  the source of truth for display labels.
- Do not read stale scenario-order workbook variants when patching from existing
  files.
- A zero output fuel row is not a valid reason to add an output branch absent
  from the full-model template.

### transformation auto-regen sectors

Modules:

```text
oil_refineries
lng
hydrogen
gas_processing
coal_transformation
petrochemical
charcoal
biofuels
nonspecified_transformation
transformation
```

Status: GATED for now. `run_patch()` raises `NotImplementedError` for any module
with `auto_sector_keys` (i.e. every module above). Leave the gate in place until
the definitive test below passes — but note the gate's original rationale is now
in doubt.

Reassessment (2026-07-16): the gate's evidence ("20_USA: 7 process-efficiency /
auxiliary-fuel expression diffs") was almost certainly measured on the RAW output
of `save_transformation_exports_with_split_targets`, which skips
`prepare_seed_rows_for_write` — the seed writer the real patcher applies
(`patch_baseline_seeds.py:928-946`). Read-only diffs through the real write path
show:

- 01_AUS reproduces the seed with zero real value conflicts (only benign
  float-format / scenario-year-window differences).
- 20_USA's one apparent conflict (Hydrogen transformation Output Share, Target =
  all zeros in raw output) is the Reference→Target output-share fallback for a
  process with no Target source data. `complete_canonical_share_groups` inside
  `prepare_seed_rows_for_write` applies it; pushing the raw fresh rows through
  that step reproduces the seed's Target hydrogen shares byte-for-byte.
- Process-efficiency and auxiliary-fuel expressions now MATCH.

Definitive test before ungating (deferred — run when no full workflow is
active): run the REAL patcher on temp-copied 01_AUS + 20_USA seeds (bypass the
gate via `patch_baseline_seeds._run_patch_locked`), diff ALL transformation-owned
rows POST-write (never raw export vs finished seed — that manufactures false
diffs), and restore the backups in a `finally`. Pass criteria are the standard
Verification Recipe ones (zero rows-only-before/after, zero non-benign value
diffs). If both economies pass, remove the `auto_sector_keys` gate and update the
verdict comment. See `docs/check_registry.md` hotspot 4 and the
`transformation-patch-gate-reassessment` memory.

If revisiting the raw layers, the patch path must reproduce (before the seed
writer): Exogenous Capacity / Historical Production seeding, output-fuel Import /
Export Target resets, and full catalog zero-fill from the same catalog source as
the full run.

### aggregated_demand

Status: fixed and spot-verified (2026-07-10). Temp-copy patch checks against
current full-run baseline seeds reproduced aggregated-demand rows exactly for
01_AUS and 20_USA (420/420 rows, zero row/expression diffs for both).

What makes it correct — run configuration options are threaded through into fresh
workbook generation:

- `AGGREGATED_DEMAND_EXCLUDED_SECTORS`
- `AGGREGATED_DEMAND_USE_SECTOR_BRANCHES`
- `exclude_own_use_td_losses`

The patcher's strip scope stays limited to:

```text
Demand\All demand aggregated\
```

### losses_own_use

Operationally patchable through the wired proxy source workflow. The current
`auto` stage resolves the activity source from the pass configuration; record
that resolved mode in each run report. Proxy coverage gaps and pre-base-year
consistency notices are diagnostics to report, not reasons to suppress seed
validation.

Before allowing manual `run_workflow=False` patching, fix strip-prefix behavior
so stale old rows are removed even when absent from the fresh source workbook.

### supply

Status: patchable and spot-verified (2026-07-14). Wired through
`supply_workflow.assemble_supply_workbooks(export_output_dir=WORKBOOKS_DIR)` and
verified end-to-end for 20_USA in the patcher (seed restored after the check, so
this is a workflow-wiring verdict rather than a persisted seed change).

The shared 9th-bucket allocation and signed supply-quantity normalization must
stay active before refreshing seeds.

## Deliverables For A Finalisation Task

1. Final module verdicts and the representative economies used.
2. Equivalence/row-scope diff numbers where available.
3. Known diagnostics separated from patch failures.
4. Contract tests and the exact preset configuration used.
5. Updated verdict comment above `_PRESET_PATCH_BASELINE_SEEDS`.
6. Final `validate_seed_files()` result and `git status --short`.

Suggested tests:

```powershell
C:\Users\Work\miniconda3\python.exe -m pytest tests\test_baseline_seed_comparison_workflow.py
C:\Users\Work\miniconda3\python.exe -m pytest tests\test_baseline_seed_canonical_groups.py
C:\Users\Work\miniconda3\python.exe -m pytest tests\test_baseline_seed_output_shares.py
C:\Users\Work\miniconda3\python.exe -m pytest tests\test_module_attribute_contracts.py
```

## Hard Constraints

- Preserve unrelated working-tree changes.
- During controlled verification, back up and restore seeds in a `finally` block.
- For an explicitly requested refresh, retain patched seeds after validation.
- Do not touch unrelated `_PRESET_*` blocks.
- Do not broaden patch scope beyond the requested module.
- If equivalence requires full reconciliation state, gate the module instead of
  approximating.
