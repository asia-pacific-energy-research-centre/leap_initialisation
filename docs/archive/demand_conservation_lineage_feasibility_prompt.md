# Prompt: verify conservation-lineage feasibility across both repositories

Work primarily in:

- `C:\Users\Work\github\leap_initialisation`
- Read `C:\Users\Work\github\leap_mappings` where required for the cross-repository comparison.

This is a **read-only feasibility audit**. Do not implement the diagnostic, edit
production code, regenerate mapping outputs, or modify either mapping workbook.
Both repositories may have unrelated active changes from other sessions; preserve
them. Report findings in chat unless the user explicitly asks for a file.

Read and follow the applicable `AGENTS.md` files first, including:

- `C:\Users\Work\github\leap_initialisation\AGENTS.md`
- `C:\Users\Work\github\leap_mappings\AGENTS.md`
- `C:\Users\Work\.codex\AGENTS_BALANCE_TABLES.md`
- `C:\Users\Work\.codex\AGENTS_LEAP_EXPORT.md`

Also read these design references:

- `leap_initialisation/docs/balance_demand_conservation_check.md`
- `leap_initialisation/codebase/functions/balance_demand_conservation.py`
- The caller in `leap_initialisation/codebase/functions/supply_results_saver.py`
- `leap_mappings/docs/prompts/common_esto_lineage_validation/03_partitioned_value_application_and_lineage.md`
- `leap_mappings/docs/prompts/common_esto_lineage_validation/06_reconcile_anchor_validation_against_conversion_outputs.md`
- The current lineage, conversion, and anchor-validation implementations named by those prompts

## Goal

Determine, with concrete data and call-chain evidence, whether we can build a
useful three-stage conservation diagnostic in `leap_initialisation` and a
structurally similar diagnostic in `leap_mappings`:

1. `original_source_value` — value in the raw ESTO or Ninth source row.
2. `expected_mapped_value` — value after the applicable mapping, fan-out,
   allocation, exclusion, and rollup rules.
3. `actual_resolved_value` — value ultimately consumed by supply reconciliation.

The diagnostic should explain totals using their component rows and categories,
not merely report that two totals differ.

## Questions that must be answered

### A. `leap_initialisation` traceability

Trace the real results-update demand call chain from raw source data through:

- raw ESTO/Ninth demand extraction;
- subtotal and sector exclusions;
- fuel/product mapping and contextual allocation;
- rollup or fallback mapping;
- construction of `demand_table` / `resolved_demand_totals`;
- the final conservation aggregation.

For every stage, identify:

- the function and file;
- available identifying columns;
- value column and units;
- whether source rows are aggregated or discarded;
- whether one-to-many or many-to-one mapping occurs;
- whether allocation weights are retained;
- whether exclusions and their reasons remain observable;
- the earliest point at which exact source-row lineage is irreversibly lost.

Prove whether a stable `source_row_id`, `mapping_row_id`, and `resolved_row_id`
can be constructed without changing source files. State which IDs would be
natural keys and which would need deterministic synthetic hashes.

### B. Exact values versus estimates

Classify each proposed value as one of:

- exact and directly observed;
- exact but aggregated;
- allocated according to an explicit share;
- estimated because the required split is unavailable;
- untraceable with current artifacts.

Do not call an allocated or inferred value “actual.” In particular, determine
whether `expected_mapped_value` can always be calculated, or whether some rows
must be reported as `unallocatable` / `unanchorable` instead.

Check whether source fan-out would repeat `original_source_value`. Specify how a
summary can count each source row exactly once while a detail table still shows
every target mapping.

### C. Demonstrate on the current mismatch

Use the existing `20_USA`, `Reference` compressed-results-update artifacts if
available. The current total diagnostic reports approximately:

- 2022: `+12,248.45 PJ`
- compressed 2023: `+323,149.29 PJ`

Without modifying the workflow, attempt to produce a small manual trace for at
least one year that shows:

- raw source components by source sector/flow and fuel/product;
- expected mapped components by ESTO product and mapping rule;
- actual resolved components by ESTO product and, where available, LEAP branch;
- included and excluded components;
- component differences that add back to the reported total difference.

If the available artifacts cannot add back exactly, quantify the unexplained
remainder and identify the precise lineage information that is missing.

Remember that compressed 2023 is a synthetic signed sum of post-base-year
sheets, not the real 2023 energy balance.

### D. `leap_mappings` compatibility

Inspect whether the lineage and anchor-validation artifacts in `leap_mappings`
can support a parallel structure:

| `leap_initialisation` concept | `leap_mappings` analogue |
|---|---|
| `original_source_value` | raw source row / raw parent contribution |
| `expected_mapped_value` | partitioned lineage or converted ESTO contribution |
| `actual_resolved_value` | converted common-boundary value, where semantically applicable |
| mapping status | exact boundary / rollup boundary / unresolved |

Do not force a third stage where the mappings pipeline genuinely has only two
independent stages. Determine which columns and statuses can be common across
the repositories and which must remain repository-specific.

Check specifically whether the existing lineage output can identify all
contributors to each failed anchor, including source categories and allocation
or membership weights. Confirm whether the two ESTO oil-family failures
(`06 Crude oil & NGL` and `07 Petroleum products`) can be decomposed from current
artifacts without rerunning or altering the pipeline.

### E. Proposed output contract

Assess whether these three outputs are feasible while leaving the existing
totals CSV unchanged:

1. Existing total comparison:
   `supply_reconciliation_balance_demand_conservation.csv`
2. Grouped breakdown:
   `supply_reconciliation_balance_demand_conservation_breakdown.csv`
3. Row lineage:
   `supply_reconciliation_balance_demand_conservation_lineage.csv`

Evaluate this candidate shared vocabulary:

- `check_id`
- `source_system`, `source_file`, `source_row_id`
- `economy`, `scenario`, `year`
- source sector/flow hierarchy fields
- source fuel/product hierarchy fields
- `original_source_value`
- `mapping_row_id`, `mapping_rule`, `mapping_status`
- `allocation_share`, `expected_mapped_value`
- target ESTO flow/product and LEAP branch
- `resolved_row_id`, `actual_resolved_value`
- `included`, `exclusion_reason`
- `difference`, `absolute_difference`, `tolerance_pj`, `status`

Identify columns that cannot be populated reliably and any additional columns
needed to prevent ambiguous or double-counted interpretation.

## Required deliverable

Return a concise but evidence-backed feasibility report containing:

1. A stage-by-stage lineage matrix for `leap_initialisation`.
2. A stage-by-stage lineage matrix for `leap_mappings`.
3. A `yes`, `partial`, or `no` verdict for each proposed output and key field.
4. The manual `20_USA` trace or a quantified explanation of why it cannot yet be produced.
5. A list of the minimum localized code changes required in each repository.
6. Explicit risks: fan-out double counting, lost dimensions, unstable IDs,
   ambiguous mappings, rollup contamination, exclusions, and synthetic-year interpretation.
7. A recommended common schema and naming convention, distinguishing exact,
   allocated, estimated, and unanchorable values.
8. A final go/no-go recommendation for implementing in `leap_initialisation`
   first and adapting `leap_mappings` afterward.

Do not infer feasibility merely from function names or documentation. Inspect
real dataframe schemas and, where safe, existing output rows. Do not silently
paper over gaps: an honest `partial` result is preferable to a lineage table
that appears exact but is reconstructed from insufficient information.

