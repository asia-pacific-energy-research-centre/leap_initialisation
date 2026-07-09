# Prompt: Extend internal conservation verification to supply and transformation

## Goal in one sentence

Extend the now-working demand conservation pattern across `leap_initialisation` by upgrading baseline supply verification with breakdown and lineage outputs, then adding a transformation-v1 check that verifies built transformation output totals against independent ESTO/9th reference totals.

Work only in `leap_initialisation`. Do not modify `leap_mappings`. Do not change the values written to LEAP merely to make a diagnostic pass.

## Context and required interpretation

Demand conservation is now the reference implementation:

- Reference side: independent raw ESTO/9th target totals.
- Produced side: values this repository builds and would hand to LEAP.
- It does **not** compare against a LEAP balance readback.
- The totals diagnostic is the pass/fail artifact.
- Breakdown, lineage, scope audit, classifications, deterministic IDs, schema version, and compressed-year labels explain the result without inventing unavailable links.

Read before editing:

- `docs/balance_demand_conservation_check.md`
- `docs/demand_conservation_realignment_prompt.md`
- `docs/prompts/stop_balance_demand_parent_subtotal_double_count.md`
- `codebase/functions/balance_demand_conservation.py`
- `tests/test_balance_demand_conservation.py`

The same core question must govern supply and transformation:

> Do independently derived ESTO/9th reference totals equal the supply or transformation values this repository produces before LEAP?

This is internal conservation. It is not a convergence check, LEAP round-trip check, or results-update closure check.

## Scope and implementation order

Implement this in two stable phases, verifying Phase 1 before starting Phase 2.

1. Upgrade baseline supply source preservation.
2. Build transformation v1: output-total conservation.

Do not implement the full transformation input-output-loss identity in this change. Document that as v2 with the unresolved loss-boundary decisions stated explicitly.

---

## Phase 1: Supply conservation upgrade

### Current state to confirm

`codebase/functions/supply_conservation.py::build_baseline_supply_source_preservation` already compares:

- raw ESTO/9th production, import, and export totals;
- against mapped `supply_primary_table` and `supply_projection_table` totals;
- by `economy / flow / year`;
- using `tolerance_pj`, `status`, and `is_mismatch`.

It is wired from `codebase/functions/supply_results_saver.py` and currently writes:

`supply_reconciliation_baseline_supply_source_preservation.csv`

`build_results_update_closure_diagnostics` in the same module is a different check. Preserve it, but do not merge it into source preservation or use it as the produced side.

### Required supply changes

1. Preserve the existing headline totals output and its filename. Keep backward-compatible columns.

2. Refactor the supply check internally so its independent stages are inspectable:

   - raw reference rows from ESTO for the base year and 9th Outlook for projection years;
   - mapped/produced supply rows from `supply_primary_table` and `supply_projection_table`;
   - headline comparison grouped by `economy / flow / year`.

3. Add supply breakdown and lineage CSVs beside the totals diagnostic:

   - `supply_reconciliation_baseline_supply_source_preservation_breakdown.csv`
   - `supply_reconciliation_baseline_supply_source_preservation_lineage.csv`

4. Match the useful demand conventions rather than creating a second vocabulary:

   - deterministic content-derived row IDs;
   - a schema-version column;
   - `source_system`, source flow/product, produced ESTO product, year, and value;
   - honest `exact / allocated / estimated / excluded / untraceable` classification;
   - explicit inclusion/exclusion reasons;
   - no fabricated allocation shares or row links;
   - empty comparisons fail explicitly;
   - a breakdown remainder or equivalent self-check proving grouped breakdown differences reproduce the headline diagnostic.

5. Handle signs once and document them:

   - production and imports are positive supply;
   - raw exports may be negative in the balances, but the existing preservation comparison treats export magnitude as positive;
   - do not apply `abs()` broadly in a way that hides invalid signs.

6. Audit subtotal and aggregate-product handling on the reference side. Do not trust a subtotal flag blindly where structural hierarchy proves otherwise. Reuse a small generic helper from demand only if it is genuinely generic; otherwise keep the supply logic local and tested. Do not create a runtime dependency on `leap_mappings` result files.

7. Preserve exported-product scope. `find_exported_supply_products` and `included_esto_products` exist to keep the produced comparison aligned with branches actually written. The totals, scope audit, and lineage must make this boundary visible instead of silently dropping products.

### Supply acceptance criteria

Add focused tests in `tests/test_supply_conservation.py` proving:

- equal independent totals pass for production, imports, and exports;
- an unmapped/dropped product produces the correct headline mismatch and is localized in breakdown/lineage;
- exports use the documented sign convention exactly once;
- duplicate mapping or fan-out cannot count a raw source value more than once;
- excluded/unwritten aggregate products appear with an honest exclusion reason;
- breakdown differences reproduce headline differences with zero remainder;
- empty inputs fail rather than silently pass;
- existing results-update closure tests remain unchanged and green.

Run the smallest real `baseline_seed` preflight or existing baseline integration path that writes the supply preservation artifact. Do not run the full multi-hour workflow.

---

## Phase 2: Transformation v1 output conservation

### Design decision already made for this prompt

Ship **v1 as output-total conservation**:

> Compare positive transformation output energy in raw ESTO/9th transformation sectors against the output energy represented by the transformation process records/tables this repository builds before LEAP export.

This is intentionally narrower than checking thermodynamic or accounting efficiency. It establishes whether transformation output was dropped, duplicated, or mis-mapped while building LEAP inputs.

The later v2 identity is:

`feedstock input + applicable auxiliary/loss energy -> output through configured efficiency`

Do not implement v2 here because the boundary between embedded losses and `other_loss_own_use_proxy` must first be specified module by module.

### Current transformation surfaces to trace

Confirm the actual data flow before coding. Relevant starting points include:

- `codebase/transformation_workflow.py::build_transformation_rows`
- `codebase/transformation_workflow.py::build_transformation_validation_table`
- `codebase/functions/transformation_analysis.py`
- `codebase/functions/transformation_analysis_utils.py`
- `build_transformation_balance_table`
- `build_transformation_sector_table`
- `build_transformation_trade_target_rows`
- the transformation wiring in `codebase/functions/supply_results_saver.py`

Identify which produced structure is closest to what is actually exported. Do not compare a reference against another aggregation of the same raw rows and call it independent.

### Required transformation changes

1. Add a focused module, preferably:

   `codebase/functions/transformation_conservation.py`

2. Build an independent raw reference for positive transformation outputs:

   - ESTO base year: transformation-sector flow rows, positive output values only;
   - 9th projection: corresponding transformation-sector rows, positive output values only;
   - exclude subtotal/aggregate rows using the same hierarchy-aware discipline as demand and supply;
   - preserve source module/flow, source fuel, scenario, economy, year, value, and scope reason.

3. Build the produced side from the final pre-export transformation process records or tables, before LEAP readback. Confirm and document how output fuels and modules are represented and how scenario rows are generated.

4. Define the headline comparison at the narrowest reliable shared grain. Target:

   `economy / scenario / transformation_module / output_fuel / year`

If raw ESTO/9th modules cannot be mapped one-to-one at that grain, use a documented comparison group and retain the finer rows in lineage. Do not silently force incompatible module definitions together.

5. Write three diagnostics beside the existing reconciliation checks:

   - `supply_reconciliation_transformation_output_conservation.csv`
   - `supply_reconciliation_transformation_output_conservation_breakdown.csv`
   - `supply_reconciliation_transformation_output_conservation_lineage.csv`

6. Use the same output contract as demand and upgraded supply:

   - totals are pass/fail;
   - `produced_total - reference_total` difference;
   - tolerance, status, reason, and mismatch boolean;
   - deterministic IDs and schema version;
   - year type where compressed projections are used;
   - scope audit and exclusion reasons;
   - count-once guard;
   - breakdown self-proves the headline difference;
   - no invented row-level allocations.

7. Treat special transformation behavior explicitly:

   - positive values are outputs and negative values are feedstock/auxiliary inputs;
   - v1 must not accidentally sum negative inputs into output totals;
   - zero-output skeletons may be needed for scenario/export coverage but must not masquerade as observed source energy;
   - one source module may feed multiple LEAP process branches; retain honest fan-out status if shares are unavailable;
   - hydrogen, LNG liquefaction/regasification, refineries, coke ovens, blast furnaces, and other special modules may use different source structures—test at least one direct case and one nontrivial mapped case;
   - do not include own-use/loss proxy values as transformation outputs.

### Transformation acceptance criteria

Add `tests/test_transformation_conservation.py` with controlled fixtures proving:

- equal raw and produced output totals pass;
- a dropped output fuel is reported as missing produced energy;
- a duplicated output is reported as excess produced energy;
- negative feedstock inputs do not enter the output total;
- subtotal parents and leaf children are not double-counted;
- module fan-out is counted once and honestly classified;
- breakdown sums reproduce the headline difference;
- empty comparisons fail;
- the check never reads a LEAP balance export.

Run a compressed or narrowly scoped 20_USA integration proof that exercises transformation construction without running the full multi-hour workflow. Confirm all three transformation CSVs are written and inspect every mismatch; do not weaken the tolerance or add exclusions merely to obtain green output.

---

## Shared implementation constraints

- Prefer small reusable diagnostic helpers where demand, supply, and transformation genuinely share semantics. Do not force domain-specific extraction into a generic abstraction.
- Preserve notebook-safe project conventions (`#%%`, functions, final `#%%`, repository-relative path resolution).
- Keep existing demand behavior and outputs unchanged unless a narrowly scoped shared-helper extraction is required and fully regression-tested.
- Do not alter supply or transformation source values, mappings, exports, caps, efficiencies, or reconciliation behavior to satisfy diagnostics.
- Do not use `leap_mappings` output files as runtime dependencies. They may be read-only verification oracles.
- Keep `build_results_update_closure_diagnostics` separate: it answers whether a resolved reconciliation table balances, not whether source energy was conserved during construction.
- Record genuine unresolved semantic boundaries in `docs/special_rules_and_design_decisions.md`; do not hide them in code.

## End-to-end deliverables

- Upgraded `codebase/functions/supply_conservation.py`.
- New transformation conservation module.
- Wiring in `codebase/functions/supply_results_saver.py` or the narrowest appropriate orchestrator.
- Updated/new focused tests.
- Supply and transformation totals, breakdown, and lineage CSVs.
- A concise documentation section explaining:
  - the independent reference and produced sides;
  - comparison grains and sign rules;
  - what each check proves;
  - what it deliberately does not prove;
  - transformation v2's deferred input-output-loss identity and proxy-loss boundary.

## Definition of done

The work is complete only when a reviewer can inspect one headline mismatch in either supply or transformation, follow it through the breakdown to the responsible flow/module/fuel, inspect the underlying source and produced rows in lineage, and verify mathematically that the drill-down reproduces the headline difference without double-counting.

