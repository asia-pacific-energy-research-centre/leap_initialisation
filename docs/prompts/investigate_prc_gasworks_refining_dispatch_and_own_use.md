# Investigate PRC gas-works and refining fuel-balance differences

Type: exploration-first diagnostic prompt. Status: active. Created 2026-08-26.

## Objective

Find the exact cause of two apparently related LEAP-vs-9th fuel-balance
differences in the PRC Target baseline-seed result. Establish whether they
share a root cause, identify the smallest safe remedy for each, and explain
the evidence in plain language.

Do **not** make implementation changes in this task. Start read-only. If the
cause is not provable from the available artifacts, say exactly what was
proved, what remains uncertain, and the minimum next observation needed to
resolve it.

## User context and problem statement

The goal of the baseline-seed workflow is to allow one final, corrected seed
import before modelling assumptions begin. Before making any change, keep the
following distinction clear:

```text
gross transformation output -> Exogenous Capacity / intended process output
own use                     -> Auxiliary Fuel Use derived from gross output
feedstock                   -> Feedstock Fuel Share + Process Efficiency
```

Own use must not be added to the output-side capacity value. A module's
capacity, output shares, efficiency, and auxiliary-ratio denominator must use
one consistent process boundary. An Exogenous Capacity value is normally a
maximum, not necessarily an instruction for LEAP to dispatch that much.

### A. PRC gas works (`09.06.01` + `10.01.02`)

In the Target dashboard, the aggregate signed `09.06.01 Gas works plants
(including own use)` total is very close to the 9th target after 2022, but
the fuel-level lines differ materially. For example, in 2023 LEAP has less
coal and gas-works-gas output, but more natural-gas input; the signed fuel
differences largely cancel in the aggregate.

Observed values to independently verify:

| Measure | PRC Target 2023 (PJ) |
|---|---:|
| 9th gross gas-works-gas output | 771.109586 |
| seeded Gas works Exogenous Capacity | 771.109586 |
| LEAP reported gas-works-gas output | 704.408210 |
| 9th natural-gas own use (`10.01.02`) | -76.166185 |
| seed natural-gas Auxiliary Fuel Use | 0.098774787 PJ/PJ |
| 9th direct gas-works natural-gas input (`09.06.01`) | -391.733207 |
| 9th inclusive natural-gas input (`09.06.01 + 10.01.02`) | -467.899392 |

The equality
`771.109586 * 0.098774787 = 76.166185` shows that the seed's natural-gas
auxiliary ratio was intentionally derived from the 9th own-use projection at
the gross-output level. Do not misdiagnose this as the 9th having no own-use
projection. Electricity and heat own use fall to zero after 2022, but
natural-gas own use remains projected.

The question to answer is why LEAP's dispatched results do not reproduce the
fuel-by-fuel 9th projection even though capacity and the auxiliary ratio have
the correct source relationship. Test, rather than assume, whether the cause
is capacity utilisation, a missing activity/output driver, LEAP's treatment
of capacity, a process-boundary mismatch, fuel-share semantics, or results
mapping/presentation.

### B. Refining (`09.07` + `10.01.11`)

There is an approximately 10% refining difference. It is confirmed for PRC
and USA and may occur in any economy with an active refinery. It may involve
misbalanced 9th data, configuration, and/or fuels that are both refinery
outputs and refinery own use.

Important prior evidence: the historical USA Target 2022 problem mixed gross
Exogenous Capacity (34,101.290 PJ) with Output Shares and Auxiliary Fuel Use
ratios based on net deliverable output (33,055.857 PJ), creating an exact
gross/net inflation factor. The current code was changed to use a consistent
gross basis for refinery `09.07` output, capacity, output shares, efficiency,
and `10.01.11` auxiliary use. A fresh end-to-end LEAP result is still needed
to prove the current behaviour. Do not assume that this known gross/net bug
is the whole explanation for the current PRC discrepancy.

## Artifacts to inspect

Use these exact artifacts first. The dashboard archive is read-only evidence,
not an instruction to alter dashboard code.

1. Dashboard archive:
   `C:\Users\Work\Downloads\05_PRC_Target_dashboard_archive_260826_123917`
   - Dashboard: `dashboard\05PRC\dashboards\other_transformation.html`
   - Chart data: `dashboard\05PRC\chart_bundles\other_transformation__charts.json`
   - Comparison table:
     `dashboard\mapping_chain\common_esto_comparison_wide.csv`
   - Converted LEAP results:
     `dashboard\mapping_chain\leap_results_converted_to_esto.csv`
   - Raw LEAP results: `dashboard\mapping_chain\raw_leap_results.csv`

2. Latest PRC baseline seed:
   `outputs\leap_exports\supply_reconciliation\baseline_seed\leap_import_baseline_seed_05_PRC_20260826.xlsx`
   Read with `header=2`. Inspect the imported expressions, units, and
   denominators for both Gas works and Oil Refining.

3. Relevant source and design evidence:
   - `docs/work_queue.md` — especially item [30], refinery gross boundary.
   - `docs/initialisation_flow_estimation_methods.md` — sections on gas
     processing and `09.07` Oil refineries.
   - `docs/special_rules_and_design_decisions.md` — gross process boundary
     decision.
   - `docs/baseline_seed_rule_inventory.md` — SEED-C025.
   - `codebase/functions/transformation_sector_analysis.py`
   - `codebase/functions/transformation_analysis_utils.py`
   - `codebase/functions/transformation_record_builder.py`
   - `codebase/functions/supply_leap_io.py` and the LEAP-result conversion
     path used by the dashboard.

4. If needed for a controlled comparison, inspect the archived/fresh PRC
   baseline-seed run artifacts under:
   `outputs\leap_exports\supply_reconciliation\baseline_seed\runs\`

## Required investigation steps

1. Reproduce the PRC Target differences from the CSV tables, not chart pixels.
   Produce a concise year-by-year comparison for 2022, 2023, 2030, 2040, and
   2060, separately for:
   - `09.06.01` direct transformation;
   - `10.01.02` own use;
   - their inclusive dashboard rollup;
   - `09.07` direct refining;
   - `10.01.11` refinery own use;
   - their inclusive/net comparison boundary.

2. For gas works, trace every 2023 source value into the seed expressions and
   then into the LEAP result for at least coal, natural gas, gas works gas,
   and one minor fuel. Explicitly identify:
   - gross output/capacity;
   - actual LEAP activity/output;
   - process efficiency;
   - each feedstock share;
   - each non-zero auxiliary-fuel ratio and its denominator;
   - whether the dashboard mapping combines or suppresses any values.

3. Determine the precise LEAP semantics of the Gas works `Exogenous Capacity`
   variable in this template. Is it a hard maximum, a target, an input-
   throughput value, an output-capacity value, or something else? Do not infer
   this merely from its name. Use template metadata, LEAP documentation/local
   API evidence, or a minimal controlled LEAP experiment if available.

4. Test the following gas-works hypotheses, reporting evidence for or against
   each one:
   - Capacity is correct but is under-utilised because no explicit output
     requirement causes LEAP to dispatch it.
   - The capacity value has the wrong gross/net or output/input basis.
   - Feedstock shares or auxiliary fuel use are applied to a different
     denominator than the seed generator expects.
   - The LEAP-to-ESTO result conversion maps a gross result to a net 9th
     comparator (or vice versa).
   - The dashboard rollup is correct but hides a material offsetting
     fuel-composition error.

5. For refining, repeat the source -> seed -> LEAP result trace for a small
   set of material fuels, including at least one same-product refinery own-use
   fuel (for example refinery gas, ethane, or another material overlapping
   product) and one external auxiliary fuel. Establish whether the present
   difference is:
   - the already-known gross/net boundary issue;
   - an unutilised-capacity/output-target issue analogous to Gas works;
   - a source 9th imbalance;
   - a mapping/conversion issue; or
   - a combination, with quantified contribution from each cause.

6. Propose the smallest safe remedy for each process family. State the exact
   seed variable(s), source boundary, and validation that would change. Do not
   recommend a broad workflow refactor unless the evidence requires it.
   Include a recommendation for a small controlled LEAP test before any
   all-economy seed rewrite.

## Required deliverable

Write a concise findings document in `docs/` (not `docs/prompts/`) with:

1. an executive conclusion for Gas works and Refining;
2. a source-to-seed-to-result lineage table for each;
3. the exact numerical reconciliation of the material difference(s);
4. whether a single root cause is proven or ruled out;
5. the recommended fix, its expected effect, and focused regression tests;
6. an explicit **Unresolved / next evidence required** section if any part
   cannot be proven.

If the investigation reaches an implementation-ready conclusion, add a
separate narrowly scoped implementation plan to `docs/work_queue.md`; do not
implement it in the exploration task unless the user explicitly authorises
that follow-on work.

## Success criteria

The investigation is successful only if it can answer, with evidence:

- Why PRC Gas works has fuel-level differences while its aggregate balance
  nearly matches the 9th target.
- Whether the seeded capacity/output/own-use relationships are correct and
  whether LEAP applies them as expected.
- Whether the Refining discrepancy has the same cause, a known gross/net
  boundary cause, a different cause, or an unresolved combination.
- What exact change would make the baseline seed more faithful, or why a
  change should not yet be made.
