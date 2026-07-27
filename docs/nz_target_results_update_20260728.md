# 12_NZ Target results-update run — 2026-07-28

## Status

The requested full-horizon Target-only update was run from merged `master` and
is **conclusively blocked by a reviewed mapping decision**, not by the supplied
LEAP workbook. No correction workbook from this run should be trusted or
imported.

The exact input was:

`data/leap balances exports - testing/12_NZ/full model output all years 23072026 TGT.xlsx`

The workbook is 700,652 bytes, contains the 2022–2060 horizon, and passed the
required LEAP balance detail check as `Level 2+` (sample child row:
`Heat plant interim`).

## Execution record

- Run label: `UPDATE_12_NZ_TGT_FULL_20260728_013647`
- Code commit at launch: `bf7c9549d8818da871f6623a6c932303d75cbdf6`
- Interpreter: `C:\Users\Work\miniconda3\python.exe`
- Start: `2026-07-28T01:38:55.090266+09:00`
- End: `2026-07-28T01:40:57.412329+09:00`
- Duration: 122.322 seconds
- Process exit: failed
- Metadata:
  `outputs/leap_exports/supply_reconciliation/supporting_files/runtime/nz_target_results_update_20260728_013647.metadata.json`
- Standard output:
  `outputs/leap_exports/supply_reconciliation/supporting_files/runtime/nz_target_results_update_20260728_013647.stdout.log`
- Standard error:
  `outputs/leap_exports/supply_reconciliation/supporting_files/runtime/nz_target_results_update_20260728_013647.stderr.log`
- Run directory:
  `outputs/leap_exports/supply_reconciliation/results_update/runs/UPDATE_12_NZ_TGT_FULL_20260728_013647`

The run did not reach the normal timing-CSV or final-workbook stages.

## Blocking decision

The canonical ninth mapping validation found two active
subtotal-to-non-subtotal mismatches:

| LEAP sector | LEAP fuel | Ninth sector | Ninth fuel |
|---|---|---|---|
| Transport non road/Freight non road/Rail | Coal tar | `15_03_rail` | `02_coal_products` |
| Transport non road/Freight non road/Rail | Hydrogen | `15_03_rail` | `16_x_hydrogen` |

The machine-readable review file is:

`outputs/leap_exports/supply_reconciliation/supporting_files/checks/subtotal_flag_blocking_mismatches_leap_combined_ninth.csv`

Resolving this requires deciding whether each relationship is:

1. an authored mapping defect that should be changed in `leap_mappings`; or
2. an intentional subtotal mismatch that should be explicitly approved in the
   `subtotal_mismatch_allowed` sheet of
   `leap_mappings/config/mapping_issue_exception_sets.xlsx`.

The update workflow must not choose between those interpretations
automatically. The failure was therefore classified as "proven unable to run"
for this input and mapping state.

This blocker is specific to the results-update balance comparison. It does not
make the projection-only baseline-seed workflow unsafe, so the separately
authorised non-provisional-template baseline-seed run may proceed.

## Secondary faults found and fixed

Commit `fbf397f` (`codex: harden targeted results-update preflights`) fixes
three independent problems exposed before or after the mapping gate:

1. Target-only compressed preflight runs no longer require a Reference balance
   workbook.
2. The preflight reference template is resolved from the current USA
   non-provisional template filename instead of the retired literal
   `leap_export_template 20_USA.xlsx`.
3. A deliberately deferred mapping failure now returns schema-safe empty
   tables, preventing the misleading secondary `mapping_status is missing
   required columns` exception.

Verification after the fixes: 175 tests passed and 5 opt-in integration tests
were skipped.

These fixes remove unrelated orchestration failures but do not bypass or
auto-approve the two mapping decisions above, so rerunning the full NZ update
before those decisions are reviewed would not be useful.

