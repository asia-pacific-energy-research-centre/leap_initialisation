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

The row-level register is published outside the hidden worktree at:

```text
C:\Users\Work\github\leap_initialisation\outputs\leap_exports\supply_reconciliation\supporting_files\baseline_seed_balance_diagnostics\01_AUS_2022\aus_2022_mismatch_issue_register.csv
```

It contains all 102 mismatches, orders the 67 material rows first, assigns
stable `AUS-2022-NNN` identifiers, and records the evidence status, owner,
decision question, and exact next check for each row. The complete 193-row
comparison is published beside it as `aus_2022_balance_source_review.csv`.
The six-row `aus_2022_issue_cluster_summary.csv` is the working queue for
reviewing the causal clusters one at a time.

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
| 4 | Coke oven coke imports `+115.211 PJ`, Coke oven coke TPES `+85.403 PJ`, and Coking coal TPES `+80.464 PJ` | `confirmed_formula_defect_plus_scope_decision` | Transformation methodology | LEAP defines efficiency as output/feedstock and excludes auxiliary fuels. The current producer uses output/(feedstock + own use) while also writing own use as auxiliary fuel. Remove confirmed auxiliaries from the efficiency denominator; the remaining decision is which ESTO rows belong to each process/module. |
| 5 | Crude-oil TPES `+174.680 PJ`, crude-oil imports `+170.737 PJ`, refinery crude input `-81.152 PJ`, and refinery product differences | `unresolved` | Refining plus LEAP dispatch | Compare the Current Accounts refining producer record, post-boundary seed, and recalculated output; decide whether the capacity heuristic should reproduce raw 2022 throughput exactly. |
| 6 | All seven `10.01.17 Non-specified own uses` rows are almost exactly 1/100 of the ESTO magnitude in LEAP; four exceed 1 PJ | `confirmed_leap_branch_scale_mismatch` | Other-loss/own-use proxy | The seed's activity × intensity equals the ESTO target, but the existing LEAP leaf Activity Level is interpreted as a percentage/share. Choose Total Energy or convert to the tree's activity-share convention, then verify one fuel. |
| 7 | Remaining supply and small transformation rows | `unresolved` | Owner in issue register | Compare the named producer row with the post-boundary seed and recalculated LEAP branch. Percentage alone is not used for priority. |

## Transformation efficiency and own-use finding

The earlier “modelling decision” is now two separate matters.

First, LEAP's local manual is unambiguous:

- process efficiency is total output energy divided by feedstock energy;
- auxiliary fuels are subsidiary/own-use consumption; and
- auxiliary-fuel energy is not included in process efficiency.

Current transformation code instead calculates:

```text
efficiency = output / (feedstock + own-use/loss)
```

and exports the same own-use/loss rows as `Auxiliary Fuel Use`. For the AUS
blast-furnace record:

```text
ESTO 09.08.02 coke oven coke feedstock       41.930999 PJ
ESTO 09.08.02 blast furnace gas output       16.775000 PJ
ESTO 10.01.07 blast furnace gas own use      16.775000 PJ
ESTO 10.01.07 natural gas own use             4.522644 PJ
ESTO 10.01.07 electricity own use             0.438241 PJ

seed Process Efficiency                      26.348078 %
seed Auxiliary Fuel Use, blast furnace gas    1.000000 PJ/PJ
seed Auxiliary Fuel Use, natural gas           0.269606 PJ/PJ
seed Auxiliary Fuel Use, electricity           0.026125 PJ/PJ
```

The exported efficiency is `16.775 / (41.930999 + 21.735885)`. Under LEAP's
definition, confirmed auxiliary rows must not be in that denominator. This is
a formula defect, not an open choice.

The modelling decision that remains is the ownership/scope of each ESTO
`10.01` row:

1. process auxiliary fuel;
2. same-module own use met from module outputs;
3. separate demand/proxy own use; or
4. a conversion loss represented in another LEAP variable.

That classification must be explicit per transformation module. In
particular, LEAP notes that own use met from the module's outputs is internal
and will not appear in an Energy Balance report, so verification must use
LEAP's transformation Inputs and Outputs reports as well as the balance.

The separate non-specified-own-use proxy has a different defect. Its seed
writes, for Natural gas, Activity `1138.400705` and Final Energy Intensity
`0.0150397526 PJ`, whose product is the correct `17.121265 PJ`. LEAP reports
`0.17121265 PJ`, exactly 1/100. The existing leaf Activity Level is therefore
being treated as a percentage/share, not the absolute unspecified-unit
activity assumed by the producer.

## Current Accounts-only 2022 seed feasibility

A Current Accounts-only output is structurally supported by the final seed
writer:

- `SCENARIOS = ["Current Accounts"]` is accepted;
- Current Accounts transformation exports are already clipped to the base
  year;
- baseline-seed validation already requires only 2022 for Current Accounts;
  and
- the existing AUS seed contains 1,793 Current Accounts rows versus 5,451
  rows across all three scenarios, so the final workbook would contain about
  67% fewer rows.

This is not yet a true base-year fast path. The full runner still:

- runs the compressed projection preflight unless disabled;
- loads and builds 9th-projection demand, transformation, and supply inputs;
- prepares projection reconciliation tables even when no projected scenario
  is requested; and
- writes the optional consolidated verification workbook.

Historical one-economy, three-scenario timings have a median total of
`1,067.8 s` (`17.8 min`). The median stages are:

| Stage | Median |
| --- | ---: |
| Generate LEAP import workbooks | 621.9 s |
| Build transformation and supply inputs | 200.5 s |
| Write per-economy combined workbooks | 87.9 s |
| Write consolidated run workbook | 35.2 s |

There is no measured one-scenario history yet. A configuration-only Current
Accounts run should materially reduce workbook rows and scenario loops, but it
will not remove the roughly 200-second projection-input build on a cache miss.
A simple row-scaling estimate is roughly 9–11 minutes, not a threefold speedup;
this estimate must be replaced by a measured dry run.

A genuine fast path should be an explicit preset, not an ad hoc source edit:

1. one economy and `SCENARIOS = ["Current Accounts"]`;
2. base and final year both 2022;
3. compressed projection preflight off;
4. lazy ESTO-only demand, transformation, and supply builders;
5. no projection reconciliation/conservation paths;
6. optional consolidated verification workbook off; and
7. a distinct cache key and output label.

The safe implementation criterion is exact equality of every Current Accounts
row against the Current Accounts slice from a normal three-scenario run. No
baseline-seed run was launched during this investigation.

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
2. Classify each transformation own-use/loss row as process auxiliary,
   same-module own use, separate demand/proxy use, or another LEAP loss
   variable. Confirmed auxiliaries must be excluded from Process Efficiency.
3. Decide whether base-year Resources trade should reproduce ESTO exactly or
   remain a LEAP balancing result after transformation dispatch.
4. Choose Total Energy versus activity-share-compatible expressions for the
   non-specified-own-use demand proxy.

## Verification and manual next step

- Real workbook detail: `Level 2+`.
- Metadata: Reference / 2022 / Petajoule / one sheet.
- Synthetic direct-workbook, Reference-only, and Level 1 tests.
- Failing-before/passing-after missing-comparator test.
- Focused tests: 14 passed.
- Real AUS comparison before and after the diagnostic fix.
- Real AUS ESTO check of current thermal-coal label preservation.

A fresh LEAP cycle has **not** been performed. Investigation should proceed
through the issue register before that cycle. When the selected producer and
diagnostic corrections are ready, the exact verification step is:

1. generate a fresh AUS baseline seed with current code;
2. import it into the intended AUS LEAP area;
3. recalculate;
4. export Reference 2022 at Level 2 or higher; and
5. rerun this direct-workbook diagnostic.
