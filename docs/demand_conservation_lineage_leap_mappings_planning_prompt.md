# Prompt: plan the conservation-lineage equivalent in `leap_mappings`

Work primarily in:

- `C:\Users\Work\github\leap_mappings`
- Read `C:\Users\Work\github\leap_initialisation` to understand the working
  prototype described below.

This is a **planning and design task first**. Inspect real code and current
artifacts, then propose the smallest reliable implementation for
`leap_mappings`. Do not force the initialisation design onto the mappings
pipeline where the semantics differ. Do not modify either mapping workbook.

For LEAP-side semantics that are not already encoded in code or workbook
structure, use the local manual clone at `C:\Users\Work\github\LEAP_manual`
as the reference point before proposing new mapping behavior. The sections
most likely to matter are `08 - Transformation`, `10 - Resources`,
`18 - Expressions`, and `21.1 - API`.

Read and follow both repositories' `AGENTS.md` files and:

- `leap_initialisation/docs/balance_demand_conservation_check.md`
- `leap_initialisation/codebase/functions/balance_demand_conservation.py`
- the conservation caller in
  `leap_initialisation/codebase/functions/supply_results_saver.py`
- `leap_initialisation/codebase/aggregated_demand_workflow.py`
- `leap_initialisation/codebase/functions/ninth_projection_mapping.py`
- `leap_mappings/docs/mappings_system.md`
- `leap_mappings/codebase/mapping_tools/apply_partitioned_common_esto.py`
- `leap_mappings/codebase/mapping_tools/reconcile_anchor_validation.py`
- current structural, converted-value, lineage, and anchor-validation outputs
  under `leap_mappings/results/`

## What now exists in `leap_initialisation`

The implementation was added in commits:

- `1e8babe` — demand-conservation breakdown and lineage prototype
- `9d1c6f3` — source-system and allocation provenance

The existing total output remains unchanged:

```text
supply_reconciliation_balance_demand_conservation.csv
```

Two supporting outputs are now produced:

```text
supply_reconciliation_balance_demand_conservation_breakdown.csv
supply_reconciliation_balance_demand_conservation_lineage.csv
```

The breakdown explains the total difference in two additive stages:

1. `source_to_expected_mapping`
   - Raw authoritative demand versus demand surviving the mapping process.
   - The raw source is ESTO in the base year and Ninth Outlook afterward.
2. `expected_mapping_to_actual_resolved`
   - Expected mapped ESTO-product demand versus demand read from the LEAP
     balance and consumed by reconciliation.

For each economy/scenario/year, summing `difference` over both stages reproduces
the existing total diagnostic exactly, apart from floating-point rounding.

The product-level rows now report:

- `expected_source_system` and `actual_source_system`
- source fuel/product codes
- allocation method
- minimum and maximum allocation share
- value quality:
  - `exact_direct`
  - `allocated`
  - `estimated`
  - `unknown`

The Ninth allocator can optionally return its complete allocation provenance
without changing the default two-return-value API used by existing callers.
Allocation methods distinguish:

- `direct`
- `proportional_esto_base_year`
- `proportional_apec_fallback`
- `equal_split_fallback`

The LEAP balance side uses the existing matching diagnostics, including:

- `source_value_petajoule`
- `allocation_share`
- `allocated_value_petajoule`
- `allocation_method`
- `mapping_status`
- LEAP branch/fuel and target ESTO pair

## Real-data verification already completed

The isolated `20_USA`, `Reference`, compressed-results-update preflight produced
the outputs successfully before a later unrelated baseline-seed validation
failure.

The breakdown reproduced the existing differences:

| Year | Existing difference | Breakdown sum | Remainder |
| --- | ---: | ---: | ---: |
| 2022 | +12,248.449683 PJ | +12,248.449683 PJ | about `-3.6e-12` PJ |
| synthetic 2023 | +323,149.294911 PJ | +323,149.294911 PJ | about `-5.8e-11` PJ |

Focused verification passed 61 tests.

The provenance columns changed the interpretation of apparently suspicious
rows. Several identical `6.065170005` PJ resolved values looked like equal
splits, but the recorded mapping evidence classified them as independent direct
mappings. Do not infer allocation method from value patterns.

## Interpretation agreed for initialisation

- ESTO is authoritative for the historical/base year.
- Ninth Outlook is the projection reference after the base year.
- A direct ESTO comparison is treated as the correct target.
- `allocated` values use explicit proportional shares and are not called direct.
- `estimated` values use fallbacks such as equal splitting and must be visible.
- The LEAP value is read from its exported energy balance. It is not created by
  the diagnostic.
- The compressed 2023 value is a synthetic signed sum across future sheets, not
  a real 2023 balance.

## Important initialisation limitation discovered

The label `All demand after detailed-sector exclusions` was misleading in the
verified run. No detailed sectors were excluded: the raw 2022 reference total
with no detailed-sector exclusions was exactly `76,821.254219 PJ`, matching the
diagnostic reference.

The extraction did still remove:

- own use and T&D losses, because another workflow handles them;
- subtotal rows, to prevent double counting;
- flows outside the configured demand families.

More importantly, if detailed-sector exclusions become active, the current code
applies them explicitly to the ESTO/Ninth reference but aggregates the LEAP
`demand_table` after sector identity has been removed. A reliable comparison
must remove the corresponding sectors from **both** sides and preserve evidence
of exactly what was included and excluded.

Any future implementation should therefore retain:

- included and excluded source flows/sectors;
- included and excluded LEAP branches;
- exclusion reason;
- each component's contribution to the compared product total.

## Goal for `leap_mappings`

Plan a structurally similar diagnostic that explains failed mapping anchors and
converted-value differences through their contributors, without pretending the
mappings pipeline has three independent numeric observations when it has only
two.

The likely mappings concepts are:

| Initialisation concept | Mappings analogue |
| --- | --- |
| authoritative raw demand | raw ESTO, Ninth, or LEAP source contribution |
| expected mapped value | contribution after relationship, allocation, exclusion, and rollup rules |
| actual resolved value | converted ESTO/common-boundary value, where independently meaningful |
| direct/allocated/estimated | direct membership, weighted allocation, fallback allocation |
| comparison exclusion | unmatched, deliberately excluded, subtotal/frontier removal, or unanchorable boundary |

Do not create a fake third stage. Where converted output is simply the sum of
mapped contributions, describe it as an aggregation stage rather than an
independent observation.

## Questions the plan must answer

1. Which current `leap_mappings` artifacts contain raw values, mapping
   membership, allocation weights, converted values, and anchor totals?
2. Does `contribution_lineage.csv` currently exist for all three source systems?
   If not, where should it be produced?
3. Can every failed anchor be decomposed into contributor rows without rerunning
   the conversion pipeline?
4. Which identifiers are stable across runs? Replace cache-local integer row IDs
   with deterministic IDs where necessary.
5. How will detailed and rolled views be prevented from being added together?
6. How will rollup-contaminated boundaries be labelled `unanchorable` rather
   than failed or estimated?
7. How will raw source values be counted once when one source row fans out to
   multiple targets?
8. Which exclusions occur on each side, and how will inclusion/exclusion reasons
   be retained?
9. Which allocation methods are direct, proportional, fallback, or genuinely
   unavailable?
10. Can the two current ESTO oil-family failures be explained by component rows
    after the proposed change?

## Candidate shared vocabulary

Reuse names where the meaning is genuinely common:

- `check_id`
- `source_system`, `source_file`, `source_row_id`
- `economy`, `scenario`, `year`, `year_type`
- source flow/sector and fuel/product fields
- `original_source_value`
- `mapping_row_id`, `relationship_id`, `rollup_context`
- `allocation_method`, `allocation_share`, `value_quality`
- target ESTO flow/product and common row
- `contribution_value`, `converted_value`
- `included`, `exclusion_reason`
- `boundary_kind`, `mapping_status`, `unanchorable_reason`
- `difference`, `absolute_difference`, `tolerance_pj`, `status`
- `source_value_counting_role` and `fanout_count`

Repository-specific fields are acceptable. Do not use the same name for values
with different semantics merely to make the schemas appear uniform.

## Required deliverable

Return a concrete implementation plan for `leap_mappings` containing:

1. A current-state data-flow diagram or compact stage table.
2. Exact files and functions to change.
3. Proposed output files and their columns.
4. Which values will be exact, allocated, estimated, or unanchorable.
5. Stable ID definitions and fan-out counting rules.
6. Treatment of exclusions, subtotals, rollups, and non-additive views.
7. A test plan using a small `20_USA` slice and the two ESTO oil-family failures.
8. Backward-compatibility requirements for existing converted and validation
   outputs.
9. A phased implementation order, starting with the smallest output that can
   explain one real failed anchor exactly.
10. Any design decision that must be made by the user before implementation.

Be explicit about gaps. A smaller honest diagnostic is preferred to a complete-
looking lineage table reconstructed from insufficient data.
