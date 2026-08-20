# Baseline seed balance diagnostics

## Goal

Build a short feedback loop for LEAP initialisation:

1. generate a baseline seed;
2. import it into the economy's LEAP area;
3. recalculate LEAP;
4. export a small set of Energy Balance years;
5. compare the exported values with ESTO and the 9th Outlook;
6. investigate structural, mapping, ownership, or LEAP-configuration issues;
7. optionally preview the implemented results-update corrections only when an
   explicit run plan selects that under-review path.

The diagnostic comparison is useful independently of `results_update`.
Results update is optional, is under review, and may be deactivated; this
document does not make it a required feedback loop after baseline seed.

The limited-year path is intended to make structural and mapping mistakes cheap
to find before a full-horizon, data-heavy run.

The integrated supply-reconciliation baseline-seed run also records lightweight
process-memory telemetry. It samples RSS every 10 seconds and writes
`baseline_seed_resource_usage.json` beside the run's runtime log, including
average, minimum, and peak RSS plus the raw samples. The sampler performs one
small process-memory query per interval in a daemon thread; it does not alter
workflow scheduling or data processing. If `psutil` is unavailable, the output
records `psutil_unavailable` and the run continues normally.

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

`codebase/functions/balance_review_workbook_builder.py` places one diagnostic
result back into the source Energy Balance layout using Python and `openpyxl`
only; the review workflow has no Node.js or `@oai/artifact-tool` dependency.
When the source metadata reports `Thousand Petajoule`, it multiplies the
displayed LEAP values by 1,000 and relabels the copied review sheet as
`Petajoule`, keeping the LEAP, error, and full expected-source sheets on the
same PJ basis. Source files are never modified.

The normal review path now reads the maintained all-years files under
`data/leap balances exports/<economy>/`. Both filename forms are accepted:
`full model output all years <date> REF|TGT.xlsx` and the current
`REF|TGT <date> <economy>.xlsx`. A four-digit date such as `2907` is read as
`DDMM`, using the workbook modification year when ordering the latest export.
Sheet metadata is catalogued first, and only
the exact requested scenario/year sheets are passed to extraction. A selected
set of years produces one compact comparison workbook per
economy/scenario/year, rather than copying the unrelated all-years tabs into
every review file.

### Agent investigation pattern: use a difference to find a mapping gap

Use a LEAP-versus-source difference as a clue, not as proof that LEAP or a
mapping is wrong. Work from the reported difference back through the pipeline:

1. **Make the comparison like-for-like.** Fix one economy, scenario, year,
   flow, fuel, unit, and sign convention. Compare LEAP with ESTO in the base
   year and with the allocated 9th expectation in projection years. Do not
   compare a LEAP total with one detailed source row.
2. **Check whether the expected energy reached LEAP.** If the source/expected
   value is nonzero but the matching LEAP process or fuel is absent, trace the
   source code through the owner workflow and the canonical mapping. This is a
   likely missing mapping, omitted flow, or missing LEAP branch. If the LEAP row
   exists but has the wrong value, check allocation shares, signs, units, and
   process ownership before changing a mapping.
3. **Check the whole sibling set.** An apparent missing child can instead be a
   parent/child or subtotal issue. For transfers, inspect `08.01`, `08.02`,
   `08.03`, `08.04`, and `08.99` together with the `08 Transfers` parent. Do
   not add the parent and children together unless the source contract says
   they are additive.
4. **Locate the first boundary where the value changes.** Follow the value from
   source row → allocated expected row → producer/process record → LEAP export
   row → LEAP result. The first missing or changed boundary identifies the
   owner: mapping, source allocation, initialisation workflow, LEAP template,
   or LEAP model behaviour.
5. **Make the smallest correct repair.** Mapping relationships belong in
   `leap_mappings`; workflow inclusion or routing belongs in this repository.
   Check all sibling coverage and many-to-many effects before adding a
   relationship. Do not hide a difference by changing a total, disabling a
   check, or copying an ID.
6. **Prove the repair.** Add a focused regression test with the missing source
   case, rerun the narrow comparison, and record whether the LEAP-versus-source
   difference now closes. Keep any deliberate residual visible and explain it.

For example, a nonzero expected transfer child that never appears in a LEAP
transfer process points first to the transfer flow list or its mapping coverage,
not to a demand or import adjustment. The `08.04 Gas separation` review used
this pattern: check the full transfer sibling set, find the code omitted from
the active workflow list, add it, and lock the behavior with a regression test.

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

Both files already live in the canonical `leap_mappings/config` directory.
They should remain there and be read directly (preferably through the
`leap_mappings` loader functions), rather than copied into this repository and
allowed to drift.

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

### Comparison grain and observed 9th-to-ESTO fan-out

The common comparison grain is the ESTO flow/product pair. Several LEAP rows can
map to one ESTO pair, and one ESTO pair can represent several 9th pairs. Their
sums can be valid, but a 9th aggregate must not be repeated as the expected
value for every detailed ESTO pair that claims it.

The phrase "many-to-one cases are blocked" is therefore too broad. Mapping
direction matters:

- many source rows to one comparison row is a safe forward sum;
- one source aggregate fanning out to several comparison rows is not safe
  without the canonical projection allocation or a common rolled-up boundary.

The diagnostic already reads
`config/outlook_mappings_master.xlsx`, including
`ninth_pairs_to_esto_pairs`. The missing step was not another mapping table: it
was reuse of the same projection allocation already used to build the baseline
seed. The diagnostic now calls
`codebase/functions/ninth_projection_mapping.py`, which allocates a 9th source
pair across detailed ESTO pairs using economy base-year shares and records
allocation provenance. LEAP is compared against those allocated ESTO
expectations. Post-rollup Common ESTO structural artifacts remain useful for
aggregate checks where a detailed split is intentionally unavailable.

The real diagnostics distinguish the two cardinality directions:

- AUS 2022 has zero `update_allocation_required` rows.
- Before canonical projection allocation, the USA smoke blocked 32 rows. After
  allocation, only two remain blocked, both because the displayed discrepancy
  has multiple LEAP components.

The material issue was therefore comparison-side 9th fan-out, not a need to
invent another source allocation. The two genuine reverse LEAP target-selection
cases remain blocked for review.

Rows therefore include:

- `comparison_grain`;
- `leap_component_count`;
- `ninth_pair_count`;
- `ninth_pair_max_esto_claimants` (the inverse cardinality: how many ESTO
  pairs share a 9th pair);
- `update_allocation_required`; and
- `update_allocation_reason`.

The raw bridge fields remain visible, but shared 9th pairs no longer block an
update when the canonical allocation completely covers the displayed ESTO
comparison group. New columns record allocation completeness, target/matched
pair counts, methods, and share sources. Multiple LEAP components remain a
defensive block. Step 1 never changes LEAP or generates an update workbook.

The extraction stage deliberately validates and consumes only
`leap_combined_esto`. It does not mark unrelated `leap_combined_ninth`
validation findings as accepted: future-year comparison values are reached
through the separate `ninth_pairs_to_esto_pairs` ESTO bridge after extraction.

### Notebook use

For the complete review/update cycle, open
`codebase/balance_update_workflow.py`. Choose one of:

```python
ACTIVE_PRESET = _PRESET_REVIEW_ONLY
# ACTIVE_PRESET = _PRESET_UPDATE_ONLY
# ACTIVE_PRESET = _PRESET_REVIEW_AND_UPDATE
```

`REVIEW_YEARS` and `REVIEW_SCENARIOS` affect only the diagnostic and comparison
workbooks. `UPDATE_HORIZON` independently controls the existing results-update
workflow:

```python
REVIEW_YEARS = [2022, 2025]
UPDATE_HORIZON = "full"  # or "base_year_plus_one" for a smoke run
```

The full-horizon update gets a unique timestamped run label when
`UPDATE_RUN_OUTPUT_LABEL` is left as `None`. The review writer performs
programmatic formula/error checks and does not render preview images by
default.

For diagnostics without the comparison workbook or update stage, open
`codebase/baseline_seed_balance_diagnostics_workflow.py` and set:

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
    "01_AUS": r"C:\Users\Work\github\leap_initialisation\data\leap balances exports\01_AUS\REF 28072026 AUS.xlsx",
}
```

For an explicit workbook, scenario, year, and units are read from each sheet's
metadata, then narrowed to `YEARS` and `SCENARIOS` when those controls are set.
The diagnostic does not require or fabricate the other scenario.
Sheets may report `Petajoule` or `Thousand Petajoule`; recognized thousand-PJ
values are converted to PJ by the shared LEAP balance extractor before
comparison. The workbook must pass Level 2+ detail inspection before source
tables are loaded.

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

A `20_USA` smoke used the latest REF/TGT exports and years 2022-2023. The
pre-connection run wrote 996 comparison rows and blocked 32 rows. After
connecting the canonical projection allocator, the rerun wrote 1,056 comparison
rows, produced 465 canonical allocated projection rows, and reduced the blocked
set to two genuine multiple-LEAP-component rows. Canonical allocation provenance
included direct, proportional ESTO base-year, and equal-split fallback methods.

The inverse-cardinality audit still identifies shared 9th sector/fuel pairs,
but complete canonical allocation now makes those comparison rows usable rather
than treating the raw mapping fan-out as an update-allocation problem.

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
4. Use Common ESTO rollups for remaining aggregate checks where a detailed
   split is intentionally unavailable.
5. Add issue classification by likely owner: demand, supply, transformation,
   transfers, own use/losses, mapping, or LEAP structure.
6. Add convergence history across repeated limited-year LEAP export/update
   cycles, then graduate a clean economy to a full-horizon verification run.
