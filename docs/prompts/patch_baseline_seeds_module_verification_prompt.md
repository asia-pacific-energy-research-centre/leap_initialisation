# Task: Verify (and fix) the remaining patch_baseline_seeds modules against the full workflow

## Context — what has already been done

`codebase/functions/patch_baseline_seeds.py` was audited and partially fixed on 2026-07-08 (uncommitted changes in the working tree). The **"transfers" module is fully verified**: its regen was rewired to go through `save_transfer_exports_with_supply_overrides` (codebase/functions/supply_leap_io.py) with an empty reconciliation table — the exact export path the full run uses — and a backup→patch→diff→restore check on 01_AUS (whose transfer config had not changed since the last full run) showed the patch reproduces the full workflow's seed rows **exactly** (573/573 rows, zero row or value differences).

Fixes already in place that the remaining modules inherit:
- `run_patch` raises on failure (per-economy `RuntimeError` summary, `ValueError` on unknown module, `NotImplementedError` for unwired regens) instead of printing.
- `_run_source_workflow` returns the exact workbook paths it wrote and `_collect_from_workbooks(files=...)` reads only those — never glob for freshly-regenerated data, stale workbooks from earlier runs conflict.
- Regen paths call `core.prepare_transformation_assets()` (explicit-init; module-level `esto_data` is None until then).
- `run_patch` rewrites `Region` per economy via `get_region_for_economy(tok)` before patching (source workbooks all carry the `GLOBAL_REGION` placeholder "United States"; the full run's seed combiner does the same rewrite at supply_leap_io.py ~line 1628).
- `_find_header_row` drops blank spacer header columns (duplicate NaN labels broke `resolve_logical_duplicates`).
- `MODULE_REGISTRY["transfers"].strip_prefix_source` resolves strip prefixes at runtime from `transfers_workflow.get_transfer_sector_titles()`; contract test `test_transfers_patch_scope_covers_every_transfer_process_title` in tests/test_baseline_seed_comparison_workflow.py.

## The lesson from transfers (why the other modules are suspect)

The full run does NOT export module workbooks with the standalone module workflows. It layers extra, load-bearing data on top via `apply_transformation_target_overrides_for_scenario` (supply_leap_io.py ~line 315–547), **which runs even with an empty reconciliation table**:
1. **Exogenous Capacity / Historical Production seeding** = process output totals × `CAPACITY_CONSTRAINT_FACTOR` (Current Accounts). Missing this left a patched process with zero capacity against ~7,050 PJ of output.
2. **Zero Import/Export Target resets** on output fuels (`CAPACITY_CLEAR_OUTPUT_TRADE_TARGETS`).
3. **Catalog zero-fill** from `_build_transformation_supply_fuel_catalog_df` (supply_results_saver.py — full model export **plus** the LEAP fuel-branch probe CSV). The patcher's older `_load_catalog()` (full-model-export only) produced a smaller skeleton set and different share tie-breaks.

Assume every unverified module misses one or more of these layers until proven otherwise.

## Goal

For each remaining module, either (a) prove patch output is row-for-row equivalent to what the full workflow wrote into the seeds, fixing the patcher until it is, or (b) explicitly conclude the module is not safely patchable and make it raise with a clear message. Then update the verdict comment above `_PRESET_PATCH_BASELINE_SEEDS` in codebase/supply_reconciliation_workflow.py (~line 649). Do NOT uncomment/enable the preset itself.

## The verification recipe (used for transfers — reuse it)

For a module M and an economy E whose config for M has not changed since the last full run (seeds are `outputs/leap_exports/supply_reconciliation/leap_import_baseline_seed_{E}_*.xlsx`):

1. Copy E's seed to a backup file outside the seed directory.
2. In a `try/finally` that **always restores the backup**, run `run_patch(M, [E], run_workflow=True)`.
3. Diff the module-owned rows (filter by the module's branch prefixes) before vs after, keyed on `(Branch Path, Variable, Scenario)` — not Region, and parse `Data(year,value,...)` expressions numerically.
4. Classify differences:
   - **Benign** (seed-pipeline normalizations): float rounding; scenario-year trimming (Current Accounts keeps only the base year, Reference/Target start at base+1); canonical share-group completion (e.g. single-process Process Share → 100).
   - **Everything else is a defect**: rows only-in-before (patch drops full-run data), rows only-in-after (patch invents rows), real value differences.
5. Pass = 0 only-in-before, 0 only-in-after, 0 non-benign value differences.

Practical notes:
- Each fresh Python process spends ~3–4 min in `prepare_transformation_assets()` loading reference tables. Batch steps into one script per run.
- Run `run_patch` directly from a script; going through `supply_reconciliation_workflow.run_with_config()` redirects stdout to a log wrapper that has swallowed output before.
- All seeds carry ~369 pre-existing template-validation warnings each (BranchID −1 on `Demand\All demand aggregated` fuels; Black liquor 2531 vs 2540). Ignore these; they are not patch-caused.
- The validation guards (`_assert_atomic_canonical_share_groups`, `resolve_logical_duplicates`, `prepare_seed_rows_for_write`) raise loudly — treat their failures as diagnostics pointing at a missing full-run layer, not as noise to suppress.
- Some economies have no data for a given module (e.g. 05_PRC/06_HKC/07_INA/10_MAS/15_PHL/16_RUS/17_SGP/19_THA have no transfer rows at all). Pick a verification economy that has module data. Do not use 20_USA for transfers comparisons — its config changed on 2026-07-08 (merged into "Transfers unallocated") and its seed was already re-patched.
- Don't leave regen artifacts with non-standard filenames in `outputs/leap_exports/supply_reconciliation/workbooks/` (a previous combined-scenario file caused duplicate-row conflicts; it was deleted).
- Consider committing a generalized harness (module, economy, prefix-regex parameters) under `codebase/scrapbook/` so this check is repeatable.

## Modules to review, with known suspects

### 1. Transformation auto-regen sectors — highest priority, near-certain gaps
`oil_refineries`, `lng`, `hydrogen`, `gas_processing`, `coal_transformation`, `petrochemical`, `charcoal`, `biofuels`, `nonspecified_transformation`, and the combined `"transformation"`.
- `_collect_auto_regen` builds records from ESTO and calls `build_transformation_log_rows` directly. It **bypasses `apply_transformation_target_overrides_for_scenario` entirely** (no capacity/production seeding, no trade-target resets) and uses the smaller `_load_catalog()` instead of `_build_transformation_supply_fuel_catalog_df`.
- The full run exports these sectors via `save_transformation_exports_with_split_targets` (supply_leap_io.py ~line 562) with `in_scope_sector_titles = get_analyzed_sector_titles() − get_transfer_sector_titles()` (producer ownership — transfers branches are excluded to avoid duplicate keys; see supply_leap_io.py ~line 724).
- Likely fix shape (mirroring transfers): route the regen through `save_transformation_exports_with_split_targets` with an empty reconciliation table and empty target rows, rather than trying to make `_collect_auto_regen` imitate it. Check how it behaves with `reconciliation_table=pd.DataFrame()` — it prints "baseline seed; exporting without supply-link overrides" and proceeds.
- Note `refining_workflow.py` also post-processes refining Exogenous Capacity from Historical Production — check whether that step runs inside or after the export path the full run uses for `oil_refineries`.

### 2. power_interim
- Patcher regen: `electricity_heat_interim_workflow.assemble_electricity_heat_interim_workbook`.
- Full run: `build_electricity_heat_interim_workbooks_for_results_supply` (supply_leap_io). Diff what that wrapper adds. The interim workflow does some of its own capacity handling (~line 883), so the gap may be smaller — let the equivalence diff decide.
- Strip prefixes are hardcoded `_tf("Electricity interim", "CHP interim", "Heat plant interim")` — confirm they cover every title the workflow can emit (same drift risk the transfers module had).

### 3. aggregated_demand
- Patcher calls `save_aggregated_demand_as_leap_workbook` with defaults. The run config options are NOT threaded through: `AGGREGATED_DEMAND_EXCLUDED_SECTORS`, `AGGREGATED_DEMAND_USE_SECTOR_BRANCHES`, `exclude_own_use_td_losses`. If the last full run used non-defaults, the patch diverges silently.
- The combiner also keys workbook filenames on `_sector_exclusion_suffix` — mismatched suffixes mean the combiner and patcher disagree about which file is current.
- The full run wrapper is `build_aggregated_demand_workbooks_for_results_supply` (supply_leap_io) — compare against it.
- Separately owned: the demand-zeroing workbook (`ZERO_OTHER_DEMAND_BRANCHES_FROM_EXPORT`). Confirm the patch's strip scope (`Demand\All demand aggregated\` only — guarded by an existing test) cannot touch it.

### 4. losses_own_use — currently blocked, has an extra latent bug
- Regen is unwired and now raises `NotImplementedError` (output depends on `OTHER_LOSS_OWN_USE_PROXY_STAGE` "first" vs "second", which the patcher can't know). Decide: wire it with an explicit stage parameter, or keep it manual-only.
- **Latent bug even in manual mode**: `strip_prefixes=[]` means prefixes are derived from the *source* rows (`_derive_prefixes`). Any branch present in the old seed but absent from the fresh source workbook is silently left stale — the exact bug class the transfers module had. Fix before allowing even `run_workflow=False` use.

### 5. supply — probably not patchable; confirm and gate
- Regen unwired (raises). `Resources\` rows are the most reconciliation-entangled output in the seeds. Recommendation from the transfers audit: conclude explicitly whether patching supply can ever reproduce the full run, and if not, remove it from the registry or make it raise unconditionally with an explanation.

## Deliverables

1. Per module: verdict (verified / fixed-and-verified / not patchable) with the equivalence-diff numbers as evidence.
2. Fixes in `patch_baseline_seeds.py` (and minimal, backwards-compatible passthroughs elsewhere if needed, as was done for `assemble_transfer_workbook`).
3. Contract tests for any prefix-coverage or option-threading fix, alongside the existing ones in tests/test_baseline_seed_comparison_workflow.py.
4. Updated verdict comment above `_PRESET_PATCH_BASELINE_SEEDS` in supply_reconciliation_workflow.py. Keep the preset commented out.
5. All seeds left byte-identical to their pre-task state (restore from backups) — except where the user explicitly asks to keep a patched seed.
6. Run: tests/test_baseline_seed_comparison_workflow.py, tests/test_baseline_seed_canonical_groups.py, tests/test_baseline_seed_output_shares.py, tests/test_module_attribute_contracts.py.

## Hard constraints

- Never modify a seed without the automatic pre-patch archive plus your own backup; always restore in `finally`.
- Do not enable `_PRESET_PATCH_BASELINE_SEEDS` or touch other `_PRESET_*` blocks.
- Do not "fix" the ~369 pre-existing validation warnings as part of this task — note them and move on.
- If a module's equivalence check cannot pass without replaying reconciliation state that only a full run produces, say so explicitly and gate the module rather than approximating.
