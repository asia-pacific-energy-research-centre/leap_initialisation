# AUS 2022 balance-export investigation findings

## Scope and provenance

This investigation used the read-only workbook:

```text
C:\Users\Work\github\leap_initialisation\data\leap balances exports - testing\01_AUS\2022.xlsx
```

Workbook metadata reports area `AUS clean slate 17_07_dan_check_send`,
scenario `Reference`, year `2022`, units `Petajoule`, one `Energy Balance`
sheet, and minimum detail `Level 2+` (sample child row:
`Heat plant interim`).

The numeric comparator was
`data/00APEC_2024_low_with_subtotals.csv`, economy `01AUS`, year 2022.
No future-year 9th value was used as a 2022 numeric comparator.

The compared post-boundary seed was:

```text
C:\Users\Work\github\leap_initialisation\outputs\leap_exports\supply_reconciliation\baseline_seed\leap_import_baseline_seed_01_AUS_20260727.xlsx
```

It was generated at 13:39 on 2026-07-27. The LEAP balance workbook was
exported at 19:01. Commit `778f649`, which fixes the thermal-coal producer
defect below, was committed at 17:33. The LEAP export therefore reflects the
pre-fix seed while current code contains the fix.

## Comparison summary

The corrected diagnostic produced 193 direct ESTO-pair comparison rows:

| Count | Rows |
| --- | ---: |
| Value mismatches at the diagnostic tolerance | 102 |
| Rows missing from LEAP | 0 |
| Rows with no valid raw ESTO comparator | 36 |
| Unmapped LEAP rows in supporting diagnostics | 107 |
| Total-balance check failures | 3 |
| Direct one-to-one comparison rows | 193 |
| Aggregate/shared rows unsafe for a future direct update | 0 |
| Material rows (`absolute_difference_pj >= 1`) | 67 |

The 107 unmapped rows are dominated by hierarchy totals and LEAP-specific
branches, not 107 proven mapping defects. They include `Total` fuel rows, LEAP
transformation subtotals, `All demand aggregated` branches, and own-use/loss
branches. Parents and children coexist, so their absolute values are not
additive.

All three total checks currently fail at inconsistent comparison boundaries.
In particular, LEAP `Total Final Energy Demand` includes
`Other loss and own use`, while ESTO flow 13 does not.

## Ranked discrepancy clusters

The 67 material rows were reviewed as the following evidence clusters.
Unlisted row-level differences remain `unresolved` in the review CSV.

| Rank | Material evidence | Primary classification | Owner | Finding / next action |
| --- | --- | --- | --- | --- |
| 1 | Anthracite imports and TPES are each about `+985.171 PJ`; Other bituminous production is `-657.521 PJ`; Other bituminous TPES is `-616.478 PJ`; Sub-bituminous production and TPES are each `-387.480 PJ` | `baseline_seed_generation_bug` | Electricity/heat interim producer | The pre-fix seed wrote 47.010% of Electricity interim feedstock to Anthracite and 0% to the two real coal products. Current code preserves the real ESTO products. Regenerate/import/recalculate/export to verify. |
| 2 | Ten material flow-13 rows, led by Natural gas `+424.163 PJ`, Electricity `+175.954 PJ`, and Gas/diesel oil `+125.943 PJ` | `diagnostic_bug` | Mapping/comparison boundary | LEAP `Total Final Energy Demand` equals `All demand aggregated + Other loss and own use`; it is not a direct comparator for ESTO flow 13. Define a rollup-aware boundary before updates. |
| 3 | LPG exports `-169.504 PJ`, LPG imports `+157.551 PJ`, electricity imports `+60.981 PJ`, electricity exports `-57.664 PJ`, plus associated TPES rows | `leap_model_behavior` (inferred, not fresh-cycle verified) | Supply plus transformation dispatch | The seed sets Resources targets, while LEAP closes shortfalls and exports transformation surpluses. Review shortfall/surplus settings and module order before changing targets. |
| 4 | Coke oven coke imports `+115.211 PJ`, Coke oven coke TPES `+85.403 PJ`, and Coking coal TPES `+80.464 PJ` | `unresolved` | Transformation methodology | Blast-furnace rows embed own-use in efficiency and also write auxiliary use. A modeller decision is required on whether losses belong in efficiency, auxiliary use, or a module-specific split. |
| 5 | Crude-oil TPES `+174.680 PJ`, crude-oil imports `+170.737 PJ`, refinery crude input `-81.152 PJ`, and refinery product differences | `unresolved` | Refining plus LEAP dispatch | Compare the Current Accounts refining producer record, post-boundary seed, and recalculated output; decide whether the capacity heuristic should reproduce raw 2022 throughput exactly. |
| 6 | Remaining supply, own-use, and small transformation rows | `unresolved` | Owner in review CSV | Compare the named producer row with the post-boundary seed and recalculated LEAP branch. Percentage alone is not used for priority. |

## Proven thermal-coal lineage

```text
ESTO 09.01.01 Electricity plants, 2022
  01.02 Other bituminous coal  -577.784550 PJ
  01.03 Sub-bituminous coal    -396.447334 PJ
  01.04 Anthracite                0.000000 PJ

pre-fix electricity/heat interim producer workbook
  Anthracite Feedstock Fuel Share             47.0100004785%
  Other bituminous coal Feedstock Fuel Share   0%
  Sub bituminous coal Feedstock Fuel Share     0%

post-boundary seed
  preserves those pre-fix producer shares

LEAP recalculation/export
  Electricity interim Anthracite input       -985.170862 PJ
  Resources Anthracite imports                986.479160 PJ

current code after 778f649
  preserves all three raw ESTO product labels before combining source rows
```

The old producer collapsed the aggregate 9th fuel `01_x_thermal_coal` onto the
first display label, Anthracite. Current code keeps the three ESTO products
separate and splits future aggregate projections using the base-year profile.
Focused coverage is in
`tests/test_electricity_heat_interim_thermal_coal_split.py`.

No new producer fix was added because `778f649` already contains it. A
real-data code-side check confirmed that current code retains the three AUS
2022 values above.

## Diagnostic fixes made

### Direct Reference-only workbook input

The diagnostic and notebook now accept one explicit workbook per economy.
Scenario, year, and units are read from workbook metadata. Direct input does
not resolve or fabricate a Target workbook and validates Level 2+ first.

The shared balance utility now resolves legacy default REF/TGT paths lazily,
so importing it does not require unrelated USA files.

Regression coverage:

- `test_direct_reference_workbook_uses_metadata_without_target`;
- `test_direct_workbook_metadata_rejects_unsupported_units`; and
- `test_economy_diagnostic_rejects_level1_before_conversion`.

### Missing raw ESTO pair is not numeric zero

`pull_base_year_value` returned `0.0` when both exact and fallback pairs were
absent. Synthetic rows such as
`09.08.01 Coke ovens (including own use)` therefore looked like physical ESTO
zeros. It now returns unavailable (`NaN`).

| Diagnostic result | Before | After |
| --- | ---: | ---: |
| Value mismatches | 116 | 102 |
| Comparator-unavailable rows | 22 | 36 |
| Material rows (`>= 1 PJ`) | 75 | 67 |

Fourteen false-zero comparisons moved to comparator-unavailable. Coke ovens /
Coke oven coke, for example, changed from LEAP `62.127 PJ` versus ESTO `0` to
unavailable until the maintained own-use rollup is applied.

Regression coverage:

- `test_missing_base_pair_is_unavailable_instead_of_zero`.

### Human review output and counts

The diagnostic now writes `leap_balance_source_review.csv`, retaining every raw
comparison field and adding explicit LEAP row/fuel labels, materiality,
preliminary owner/classification, evidence, and next action. The summary
separately counts mismatches, missing sides, unmapped rows, total failures,
direct comparisons, and unsafe aggregate comparisons.

## Unresolved decisions and stop conditions

No canonical mapping, modelling assumption, source data, or LEAP area was
changed. These decisions require user/modeller direction:

1. Define the correct comparison boundary for LEAP
   `Total Final Energy Demand` versus ESTO flows 10, 12, and 13.
2. Decide whether transformation own-use/loss is embedded in Process
   Efficiency, supplied through Auxiliary Fuel Use, or split by module.
3. Decide whether base-year Resources trade should reproduce ESTO exactly or
   remain a LEAP balancing result after transformation dispatch.

## Verification and manual next step

- Real workbook detail: `Level 2+`.
- Metadata: Reference / 2022 / Petajoule / one sheet.
- Synthetic direct-workbook, Reference-only, and Level 1 tests.
- Failing-before/passing-after missing-comparator test.
- Focused tests: 14 passed.
- Real AUS comparison before and after the diagnostic fix.
- Real AUS ESTO check of current thermal-coal label preservation.

A fresh LEAP cycle has **not** been performed. The thermal-coal correction is
confirmed only before LEAP. Exact next step:

1. generate a fresh AUS baseline seed with current code;
2. import it into the intended AUS LEAP area;
3. recalculate;
4. export Reference 2022 at Level 2 or higher; and
5. rerun this direct-workbook diagnostic.
