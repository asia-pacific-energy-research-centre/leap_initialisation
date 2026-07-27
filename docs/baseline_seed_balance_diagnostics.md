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

### Difference convention

```text
difference_pj = leap_value_pj - source_value_pj
correction_to_match_source_pj = source_value_pj - leap_value_pj
```

A positive difference means LEAP shows more energy than the source at the
reported comparison grain.

### Comparison grain and many-to-one mappings

The common comparison grain is the ESTO flow/product pair. Several LEAP rows can
map to one ESTO pair, and one ESTO pair can represent several 9th pairs. Their
sums are valid for diagnosing an aggregate difference, but the aggregate
difference cannot be pushed back to individual LEAP rows without an explicit
allocation rule.

Rows therefore include:

- `comparison_grain`;
- `leap_component_count`;
- `ninth_pair_count`;
- `ninth_pair_max_esto_claimants` (the inverse cardinality: how many ESTO
  pairs share a 9th pair);
- `update_allocation_required`; and
- `update_allocation_reason`.

These fields are warnings for later update design. Step 1 never changes LEAP or
generates an update workbook.

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

The normal filename and Level 2 detail rules in
`data/leap balances exports/README.md` still apply.

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

1. Add a dry-run update preview showing the exact supply-side settings the
   current `results_update` allocator would change, before writing a workbook.
2. Reconcile the update path with current baseline-seed rules and require both
   paths to cross the same post-boundary seed validation/completion logic.
3. Define explicit allocation policies for aggregate comparisons, especially
   LEAP-to-9th many-to-one and one-to-many cases. Aggregate differences must not
   be divided silently.
4. Add issue classification by likely owner: demand, supply, transformation,
   transfers, own use/losses, mapping, or LEAP structure.
5. Add convergence history across repeated limited-year LEAP export/update
   cycles, then graduate a clean economy to a full-horizon verification run.
