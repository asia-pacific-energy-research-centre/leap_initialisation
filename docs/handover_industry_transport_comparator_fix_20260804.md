# Handover: Industry and Transport Non-Road Comparator Fix

Date: 2026-08-04

Repository: `C:\Users\Work\github\leap_initialisation`

## User request

Fix the 2023 Target balance-review comparator values for `All demand aggregated/Industry` and `All demand aggregated/Transport non road`. LEAP values are confirmed correct. Treat rounding differences at or below `0.01%` as matches. Do not run the full update process.

## Confirmed baseline output

Workbook: `C:\Users\Work\github\leap_initialisation\outputs\leap_exports\supply_reconciliation\supporting_files\baseline_seed_balance_diagnostics\usa_tgt0408_review_20260804_2023_retry\comparison_workbooks\balance_review_20_USA_tgt_2023.xlsx`

CSV: `C:\Users\Work\github\leap_initialisation\outputs\leap_exports\supply_reconciliation\supporting_files\baseline_seed_balance_diagnostics\usa_tgt0408_review_20260804_2023_retry\leap_balance_source_differences.csv`

Baseline 2023 totals:

| Group | LEAP PJ | Comparator PJ | Difference PJ |
|---|---:|---:|---:|
| Industry | 11,858.988763 | 6,122.149625 | 5,736.839138 |
| Transport non-road | 4,922.614046 | 1,195.319522 | 3,697.896178 |
| Road | 21,676.825800 | 21,676.801786 | 0.024014 |
| International transport | 1,976.295790 | 1,976.292541 | 0.003249 |

Total-balance checks passed with zero failures.

## Industry root cause

The canonical projection alias path reconstructs the Industry ESTO parent from incomplete/duplicated detailed allocations.

Direct raw 9th query:

```text
economy = 20_USA
scenario = target
sectors = 14_industry_sector
fuels = 17_electricity
subtotal_results = False
```

returns `3068.32603756`, matching LEAP `3068.33`. The canonical comparator returned `2279.118978`, omitting `789.207059`.

Mapping workbook: `C:\Users\Work\github\leap_mappings\config\outlook_mappings_master.xlsx`, sheet `ninth_pairs_to_esto_pairs`.

Relevant mapping: `14_industry_sector / 17_electricity -> 14 Industry sector / 17 Electricity`, with both pair-subtotal flags true.

Do not simply sum all canonical ESTO descendants: a previous attempt changed Industry to approximately `12928.14 PJ`, proving that some coal/product rows are over-counted. Use a direct 9th lookup keyed by `mapping_status` / `ninth_fuel_code`.

## Transport non-road root cause

The visible ESTO selector is `15.01,15.03-15.06 Transport non-road`. ESTO contains only the parent `15 Transport sector` row, so the canonical alias has no component rows and returns zero for several fuels.

Sum these raw 9th sector prefixes, using non-subtotal rows (`subtotal_results == False`):

```text
15_01, 15_03, 15_04, 15_05, 15_06
```

Match `fuels`/`subfuels` against `ninth_fuel_code`. The `15_05_pipeline_transport` natural-gas value is essential; a previous attempt missed it and produced about `3727.30 PJ` instead of `4922.61 PJ`.

## Rounding rule

Treat a row as a match when `absolute_difference <= existing PJ tolerance` OR `abs(difference_percent) <= 0.01`. For zero/near-zero source values retain the absolute PJ tolerance.

The working file currently contains `DEFAULT_ROUNDING_TOLERANCE_PERCENT = 0.01`; verify it before editing because other uncommitted work has been active in the same file.

## Relevant code

Primary module: `codebase/functions/baseline_seed_balance_diagnostics.py`.

Key functions: `apply_canonical_projection_comparators`, `build_leap_source_difference_table`, and `run_economy_balance_diagnostic`.

Canonical allocator: `codebase/functions/ninth_projection_mapping.py`.

## Attempts and failure mode

Replacing Industry aliases with detailed descendants over-counted products. Direct transport selector rows improved some fuels but missed `15_05` natural gas. Repeated calls to `pull_projection_series` / `pull_projection_series_from_descendants` against the full 9th frame caused review runs to terminate after normal subtotal warnings, before writing a workbook. A direct post-processing override was attempted but was not verified and is not active in the production preview path.

The next implementation should create one vectorised lookup table from the already-loaded, economy/scenario-scoped `comparison["ninth_df"]`. Do not call full-frame pull functions inside a loop over difference rows.

## Safer implementation plan

1. Preserve all refining-related edits and inspect `git diff` before changing anything.
2. Scope `ninth_df` once to `20_USA` and `Target`.
3. Build mapping rows from `mapping_status` keyed by `esto_flow`, `esto_product`, `sector_code_9th`, and `ninth_fuel_code`.
4. Aggregate raw 9th values once by sector family, fuel code, and year: Industry uses `14_industry_sector`; non-road uses the five `15_*` prefixes above.
5. Merge direct values onto the final difference table and recompute difference, percentage, status, mismatch flag, and correction value.
6. Add tests for Industry, pipeline natural gas, the 0.01% rounding rule, and a substantive mismatch.

## Verification

```powershell
C:\Users\Work\miniconda3\python.exe -m py_compile codebase/functions/baseline_seed_balance_diagnostics.py
C:\Users\Work\miniconda3\python.exe -m pytest -q tests/test_baseline_seed_balance_diagnostics_workflow.py
```

Run review-only with the existing `run_balance_update_workflow(..., preset=_PRESET_REVIEW_ONLY, ...)` entry point. Expected verified result: Industry source approximately `11858.99 PJ`, non-road source approximately `4922.61 PJ`, and no Road/International mismatch rows under 0.01%.

Do not report success unless the regenerated CSV/workbook confirms those values.

## Current working-tree caution

There are unrelated/refining-related uncommitted changes. Do not reset or broadly restore files. Preserve the existing edits in `balance_review_workbook_builder.py`, `baseline_seed_balance_diagnostics.py`, `ninth_projection_mapping.py`, `supply_leap_io.py`, `transformation_record_builder.py`, and the modified tests/docs. Only stage files belonging to a verified comparator fix.
