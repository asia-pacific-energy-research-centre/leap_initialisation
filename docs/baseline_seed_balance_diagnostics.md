# Baseline seed balance diagnostics

## Goal

Build a short feedback loop for LEAP initialisation:

1. generate a baseline seed;
2. import it into the economy's LEAP area;
3. recalculate LEAP;
4. export a small set of Energy Balance years;
5. compare the exported values with ESTO and the 9th Outlook;
6. preview and later apply corrections through the existing results-update path;
7. repeat until the remaining differences are understood or within tolerance.

The limited-year path is intended to make structural and mapping mistakes cheap
to find before a full-horizon, data-heavy run.

## Step 1: read-only source differences

`codebase/baseline_seed_balance_diagnostics_workflow.py` is the notebook entry
point. Its supporting functions live in
`codebase/functions/baseline_seed_balance_diagnostics.py`. Together they:

- resolves the latest REF and TGT workbooks from
  `data/leap balances exports/<economy>/`;
- inspects both workbooks before extraction and stops with a clear error when
  either is a Level 1 export without indented branch rows;
- accepts only the selected years, so a workbook may contain a small diagnostic
  horizon;
- reuses the same canonical LEAP-to-ESTO conversion and ESTO-to-9th comparison
  backbone used by `results_update`;
- compares the configured ESTO base year with ESTO and later years with the 9th
  Outlook;
- writes one combined CSV containing LEAP values, source values, `LEAP - source`,
  and the inverse correction required to equal the source; and
- reports mapping cardinality instead of inventing a row-level allocation.

The output is:

```text
outputs/leap_exports/supply_reconciliation/supporting_files/
baseline_seed_balance_diagnostics/leap_balance_source_differences.csv
```

If conversion finds unmapped LEAP rows, a second
`leap_balance_mapping_issues.csv` is written beside it.

`leap_balance_source_review.csv` is the human-facing review surface. It adds a
materiality flag, preliminary owner/classification, evidence note, and next
action while retaining the full numerical and cardinality columns. The run
summary separately counts value mismatches, missing sides, unmapped rows,
total-balance failures, direct comparisons, and aggregate/shared comparisons
unsafe for a direct update.

### Governing balance-variable contract

The diagnostic must not decide update eligibility by maintaining a list of
individual discrepancies. It first asks which balance variable LEAP is allowed
to move for each economy/scenario/fuel.

The maintained contract is
`config/runtime_tables/balance_error_signal_rules.csv`. Its initial rule is:

- `02 Imports` is the default allowed balancing variable for every fuel and is
  the `imports_gap` error signal;
- all unlisted direct flows are protected by default; and
- total primary supply and total final energy consumption are derived checks,
  not independently adjustable variables.

Rules may be narrowed by economy, scenario, or ESTO product. A more-specific
rule can therefore allow another variable for a reviewed exception, but the
default remains imports-only.

Every comparison row receives:

- `balance_variable_role`: `error_signal`, `protected`, or `derived_check`;
- `allowed_to_change`, `error_signal_name`, and the matched rule reason;
- `balance_contract_issue`;
- `requires_issue_review`; and
- `update_signal_eligible`.

A difference in an allowed error signal is updater input. A difference in a
protected or derived flow raises an issue whose initial hypotheses are:

1. the baseline seed recorded that flow incorrectly;
2. LEAP balancing/module rules moved something that was expected to remain
   fixed; or
3. the maintained balance-variable contract is wrong for that fuel.

Unavailable comparisons, unmapped rows, unexpected flow names, and mapping
cardinality problems remain issues rather than being silently treated as
updates.

### Placeholder and replacement sectors

Interim/placeholder sectors can legitimately be replaced by more detailed
sectors without preserving each sector-level row. The diagnostic marks known
placeholder scopes (`Electricity interim`, `CHP interim`, `Heat plant interim`,
and `All demand aggregated`) with `placeholder_scope=True`.

This does **not** automatically exclude their fuel/flow differences. A blanket
exclusion would have hidden the confirmed AUS thermal-coal seed defect inside
`Electricity interim`. A future exclusion must name a reviewed
placeholder-to-replacement group and pass a **replacement-boundary
reconciliation** before suppressing its internal redistribution.

This is narrower than a general transformation-efficiency or whole-balance
conservation rule. For each economy, scenario, year, signed flow, and fuel (or
an explicitly reviewed non-expanding rollup), it means:

```text
observed_group = retained_placeholder + sum(active_replacement_branches)
observed_group ~= source_expected_at_the_same_boundary
```

The placeholder and replacements may redistribute values internally, but their
combined value must still match the independent ESTO/9th expectation within the
configured tolerance. Transformation inputs and outputs must be checked
separately; a single net total could hide an input error with an offsetting
output error.

The canonical mapping repository already contains useful group declarations:

- `config/source_branch_fallback_rules.csv` pairs Electricity/CHP/Heat standard
  branches with their interim alternatives. Its current
  `warn_and_zero_interim` conversion policy prevents both alternatives from
  being added when both are active, but it does not prove that the selected
  branch matches the independent source expectation.
- `config/all_demand_aggregated_components.json` records which detailed demand
  sectors remain represented by `All demand aggregated`. It warns about
  overlap and deliberately does not zero either side because the aggregate may
  be a residual.

The update diagnostic should reuse these group declarations, then add the
independent group comparison above. Only a passing group can make internal
placeholder/replacement redistribution ignorable. A failing group remains a
baseline-seed, LEAP-rule, mapping, or balance-variable-contract issue.

### Difference convention

```text
difference_pj = leap_value_pj - source_value_pj
correction_to_match_source_pj = source_value_pj - leap_value_pj
```

A positive difference means LEAP shows more energy than the source at the
reported comparison grain.

### Comparison grain versus reverse-update allocation

The common comparison grain is the ESTO flow/product pair. Several LEAP rows can
map to one ESTO pair, and one ESTO pair can represent several 9th pairs. Their
sums are valid for diagnosing an aggregate difference, but the aggregate
difference cannot be pushed back to individual LEAP rows without an explicit
allocation rule.

The phrase "many-to-one cases are blocked" is therefore too broad. Mapping
direction matters:

- many source rows to one comparison row is a safe forward sum;
- one source aggregate fanning out to several comparison rows is not safe
  without an allocation or a common rolled-up boundary; and
- one safe aggregate difference mapping back to several possible LEAP update
  targets is a separate reverse-update target-selection problem.

The diagnostic already reads
`config/outlook_mappings_master.xlsx`, including
`ninth_pairs_to_esto_pairs`; merely referring to the master workbook again does
not resolve the ambiguity. The next comparison implementation should consume
the canonical post-rollup Common ESTO structural artifacts
(`source_pair_to_common_row.csv` and component lineage) so raw mapping
cardinality is not mistaken for comparison unsafety. Those artifacts define
safe aggregation membership but deliberately do not allocate a common-row
value back to its source children. Reverse update targeting must therefore
remain a separate decision.

Rows therefore include:

- `comparison_grain`;
- `leap_component_count`;
- `ninth_pair_count`;
- `ninth_pair_max_esto_claimants` (the inverse cardinality: how many ESTO
  pairs share a 9th pair);
- `update_allocation_required`; and
- `update_allocation_reason`.

These current fields conservatively combine comparison safety and reverse
targeting. A later schema should split them into, at minimum,
`comparison_boundary_safe` and `reverse_update_target_required`. Step 1 never
changes LEAP or generates an update workbook.

The extraction stage deliberately validates and consumes only
`leap_combined_esto`. It does not mark unrelated `leap_combined_ninth`
validation findings as accepted: future-year comparison values are reached
through the separate `ninth_pairs_to_esto_pairs` ESTO bridge after extraction.

### Notebook use

Open `codebase/baseline_seed_balance_diagnostics_workflow.py`, set:

```python
RUN_DIAGNOSTICS = True
ECONOMIES = ["20_USA"]
YEARS = [2022, 2023]
SCENARIOS = ["Reference", "Target"]
```

Then run all cells. To pin a specific pair of exports:

```python
DATE_IDS_BY_ECONOMY = {
    "20_USA": {"REF": "23072026", "TGT": "23072026"},
}
```

To run one explicit Reference-only workbook:

```python
WORKBOOK_PATHS_BY_ECONOMY = {
    "01_AUS": r"C:\Users\Work\github\leap_initialisation\data\leap balances exports - testing\01_AUS\2022.xlsx",
}
```

For an explicit workbook, scenario, year, and units are read from each sheet's
metadata. The diagnostic does not require or fabricate the other scenario.
Every sheet must report Petajoule and the workbook must pass Level 2+ detail
inspection before source tables are loaded.

The normal filename and Level 2 detail rules in
`data/leap balances exports/README.md` still apply.

### Minimum export detail

Level 2 is sufficient for the update backbone: it exposes the transformation
module/process rows used by the mappings without requiring the much larger
Level 4 demand-detail export. The diagnostic now applies the same minimum
detail check as `results_update` before loading ESTO or 9th data.

`data/leap balances exports - testing/01_AUS/2022.xlsx` is the representative
limited-year input checked on 2026-07-27. It contains indented child rows and
is detected as `Level 2+`, so it passes.

The workbook does not store a dependable setting that distinguishes Levels
2, 3, 4, and 5 after export. The check therefore reports either `Level 1` or
`Level 2+`; this is enough to enforce the update method's minimum without
claiming an exact higher detail level.

## Current boundary

Step 1 supports the configured ESTO base year and later 9th Outlook projection
years. Earlier historical years are rejected explicitly rather than silently
using the wrong reference. Supporting a multi-year ESTO historical comparison
is a follow-up.

### Real-data verification (2026-07-27)

A `20_USA` smoke used the latest REF/TGT exports and years 2022-2023. It wrote
996 comparison rows: 463 used ESTO, 325 used the 9th Outlook, and 208 had no
available source comparator. There were 738 mismatches.

The inverse-cardinality audit found 15 9th sector/fuel pairs shared by multiple
ESTO pairs. They affect 30 future-year rows, which the current schema flags as
`update_allocation_required=True`. This confirms that a row can have
`ninth_pair_count=1` and still be unsafe to update directly because the same
9th pair is also claimed elsewhere.

The run took about five minutes. Selecting two output years does not yet avoid
preparing the full 288 MB 9th table, so source-level economy/scenario/year
filtering is the next performance task.

## Later phases

1. Connect the dry-run update preview directly to `update_signal_eligible`
   imports-gap rows and keep protected-flow issues out of numeric updates.
2. Reuse the canonical placeholder/replacement group declarations and add the
   signed, fuel-specific replacement-boundary reconciliation before excluding
   internal sector redistribution.
3. Reconcile the update path with current baseline-seed rules and require both
   paths to cross the same post-boundary seed validation/completion logic.
4. Replace raw-cardinality blocking with post-rollup Common ESTO comparison
   safety, while keeping source fan-out and reverse LEAP update-target selection
   explicit. Aggregate differences must not be divided silently.
5. Add issue classification by likely owner: demand, supply, transformation,
   transfers, own use/losses, mapping, or LEAP structure.
6. Add convergence history across repeated limited-year LEAP export/update
   cycles, then graduate a clean economy to a full-horizon verification run.
