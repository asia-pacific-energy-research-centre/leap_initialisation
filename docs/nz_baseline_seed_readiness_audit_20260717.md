# 12_NZ baseline-seed readiness audit — 2026-07-17

## Recommendation

**Conditional readiness: the shared catalog preflight passes; review the
zero-valued unresolved rows before import sign-off.** No nonzero unresolved-ID
rows were found in the current seed, and the current seed is
structurally/value-identical to the immediately preceding NZ seed. The findings
below are therefore warnings to resolve or accept explicitly, not evidence for
adding USA branches to NZ.

The gated full reconciliation run was not started as part of this audit.

## Inputs inspected

| Item | Path | Result |
|---|---|---|
| NZ template | `data/leap_export_templates/leap_export_template 12_NZ.xlsx` | Present; 8,318 export rows and 646 branch paths; Region is New Zealand |
| Current seed | `outputs/leap_exports/supply_reconciliation/baseline_seed/runs/SEED_12_NZ_TGT_REF_CA/leap_import_baseline_seed_12_NZ_20260717.xlsx` | 3,534 LEAP rows; 618 branch paths |
| Prior NZ seed | `outputs/leap_exports/supply_reconciliation/baseline_seed/runs/SEED_12_NZ_TGT_REF_CA/archive/leap_import_baseline_seed_12_NZ_20260717.xlsx` | Used as the comparison baseline |
| Shared fuel catalog | `outputs/leap_exports/supply_reconciliation/supporting_files/checks/leap_fuel_branch_catalog.csv` | Materialised from the template union; 6,191 catalog rows |

## Comparison result

The current and prior seed have the same 3,534 logical rows. There are no
added/removed keys and no changes in `Expression`, `BranchID`, `VariableID`,
`ScenarioID`, or `RegionID`. Metadata differs in `Units` for 330 rows and
`Scale` for 3 rows; these should be treated as metadata review findings rather
than routing regressions.

## Template and unresolved-ID findings

- The NZ template is selected by the canonical resolver and reports Region
  `New Zealand`.
- The seed has 156 rows with `BranchID=-1` and `VariableID=-1`.
- All 156 are zero-valued rows in the seed expressions, so there are no
  nonzero unresolved-ID rows blocking the seed on energy values.
- The unresolved rows are concentrated in the NZ-absent
  `Demand\\Other loss and own use\\Oil refineries` scope (123 rows) and the
  non-specified transformation scope (33 rows).
- The seed contains 32 branch paths absent from the NZ template, all belonging
  to the Oil refineries scope. These must remain diagnostics; do not borrow
  USA branches or add template exceptions without a modelling decision.
- The previously identified NZ
  `Demand\\Other loss and own use\\Non specified own uses\\Electricity` branch
  is present in the NZ template and is not part of this missing-template-path
  finding.

## Checks run

Focused readiness/template/catalog/reset suites passed: **93 passed, 5
skipped**. The skipped checks are existing opt-in/environment-dependent cases.

The NZ catalog preflight was then run against the materialised shared union:

- 26 scopes checked;
- 0 generated rows missing from the shared catalog;
- 868 catalog-only rows, which are expected because the catalog is a union and
  not an NZ-specific checklist.

## Next action

Review the zero-valued Oil refineries and non-specified transformation
findings, then make the explicit go/no-go decision for an authorized full run.
