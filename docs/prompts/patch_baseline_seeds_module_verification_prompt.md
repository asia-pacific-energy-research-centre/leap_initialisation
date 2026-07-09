# Task: Patch and verify baseline seed modules

Use this prompt when working on `codebase/functions/patch_baseline_seeds.py` or
when refreshing baseline seed files from module-specific workbooks.

## Current Context

`patch_baseline_seeds.py` supports patching a single module into the existing
`leap_import_baseline_seed_{econ}_*.xlsx` files without running the full supply
reconciliation workflow.

Do not call `supply_reconciliation_workflow.run_with_config()` for these tasks.
Call the patcher directly.

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

## Module Verification Goal

For each module, either:

1. prove the patch output is row-for-row equivalent to what the full workflow
   wrote into the seeds, fixing the patcher until it is; or
2. explicitly conclude the module is not safely patchable and make it raise with
   a clear message.

Then update the verdict comment above `_PRESET_PATCH_BASELINE_SEEDS` in
`codebase/supply_reconciliation_workflow.py`. Do not enable the preset itself.

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

These remain suspect until verified. Check whether the patch path reproduces the
full workflow layers:

- Exogenous Capacity / Historical Production seeding
- output-fuel Import Target / Export Target resets
- full catalog zero-fill from the same catalog source used by the full run

If equivalence fails, prefer routing regeneration through the same full-workflow
export helper rather than reimplementing its behavior in the patcher.

### aggregated_demand

Check that run configuration options are threaded through:

- `AGGREGATED_DEMAND_EXCLUDED_SECTORS`
- `AGGREGATED_DEMAND_USE_SECTOR_BRANCHES`
- `exclude_own_use_td_losses`

Confirm the patcher's strip scope stays limited to:

```text
Demand\All demand aggregated\
```

### losses_own_use

Currently blocked/manual unless explicitly wired with the correct proxy stage.
Do not silently infer whether the proxy stage is `"first"` or `"second"`.

Before allowing manual `run_workflow=False` patching, fix strip-prefix behavior
so stale old rows are removed even when absent from the fresh source workbook.

### supply

Likely not safely patchable without full reconciliation state. Confirm and gate
with a clear message rather than approximating resource rows.

## Deliverables For A Verification Task

1. Per-module verdict: verified, fixed-and-verified, or not patchable.
2. Equivalence-diff numbers as evidence.
3. Minimal fixes in `patch_baseline_seeds.py` or the owning workflow.
4. Contract tests for prefix coverage, option threading, or canonical naming.
5. Updated verdict comment above `_PRESET_PATCH_BASELINE_SEEDS`.
6. Seeds restored to pre-task state unless the user explicitly asked to keep
   patched seeds.
7. Final `validate_seed_files()` result and `git status --short`.

Suggested tests:

```powershell
C:\Users\Work\miniconda3\python.exe -m pytest tests\test_baseline_seed_comparison_workflow.py
C:\Users\Work\miniconda3\python.exe -m pytest tests\test_baseline_seed_canonical_groups.py
C:\Users\Work\miniconda3\python.exe -m pytest tests\test_baseline_seed_output_shares.py
C:\Users\Work\miniconda3\python.exe -m pytest tests\test_module_attribute_contracts.py
```

## Hard Constraints

- Preserve unrelated working-tree changes.
- Never modify seeds during verification without a backup and `finally` restore.
- Do not enable `_PRESET_PATCH_BASELINE_SEEDS`.
- Do not touch unrelated `_PRESET_*` blocks.
- Do not broaden patch scope beyond the requested module.
- If equivalence requires full reconciliation state, gate the module instead of
  approximating.
