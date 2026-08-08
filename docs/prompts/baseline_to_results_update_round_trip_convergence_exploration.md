# Explore baseline-seed to results-update round-trip convergence

Type: exploration-first implementation prompt. Status: active. Created
2026-07-30.

## Purpose

Build a reliable way to answer:

> After importing one `results_update` workbook into LEAP and recalculating,
> did the LEAP Energy Balance become closer to the independent ESTO/9th source
> than it was after the baseline seed?

The first deliverable is a measured design and a read-only comparison
prototype. Do not begin by automating LEAP imports or changing the allocation
rules.

## Define an iteration correctly

Keep these events separate:

1. **Iteration 0 / baseline observation**
   - generate and import the baseline seed;
   - recalculate LEAP;
   - export the selected LEAP Energy Balance;
   - run the balance diagnostics/review.
2. **Update intervention 1**
   - run `results_update` using the iteration-0 balance export;
   - produce the updated LEAP import workbook.
3. **Iteration 1 / post-update observation**
   - import update intervention 1 into LEAP;
   - recalculate LEAP;
   - export a new balance workbook;
   - run the same diagnostics/review again.

The update workbook is an intervention, not evidence of improvement by itself.
Improvement is observable only when iteration 0 and iteration 1 balance
snapshots are compared. The same sequence applies to later updates.

## Current repository capabilities

Read these before designing anything:

- `codebase/balance_update_workflow.py`
  - already supports review-only, update-only, and review-and-update presets;
  - review years and the full update horizon are independently selectable;
  - it does not currently link one review snapshot to the later post-import
    review snapshot.
- `codebase/functions/baseline_seed_balance_diagnostics.py`
  - writes `leap_balance_source_review.csv`;
  - compares LEAP and ESTO/9th on a common ESTO flow/product axis;
  - includes `difference_pj`, `absolute_difference_pj`, status, mapping
    cardinality, source-allocation provenance, balance-variable role,
    `requires_issue_review`, and `update_signal_eligible`;
  - uses the maintained imports-only balance-error-signal contract unless a
    more specific rule applies.
- `codebase/functions/balance_review_workbooks.py`
  - creates the human-facing selected-year comparison workbooks;
  - is a presentation layer, not an iteration-history store.
- `codebase/supply_reconciliation_allocation.py`
  - writes capacity-unmet pass state and
    `capacity_unmet_convergence.csv`;
  - records aggregate positive import gap, allocations, clipping, unresolved
    rows, and a simple trend.
- `codebase/functions/capacity_unmet_convergence_diagnostics.py`
  - summarizes allocator gap movement by fuel and compares named run ids.
- `codebase/supply_reconciliation_history.py`
  - owns additive convergence manifests and input fingerprints.
- `codebase/baseline_seed_comparison_workflow.py`
  - can compare two LEAP import workbooks by logical row key and parsed
    expression-year values;
  - may be reusable for describing which LEAP levers changed between the
    baseline seed and an update workbook.
- `config/runtime_tables/balance_error_signal_rules.csv`
  - defines which balance rows are allowed error signals and which are
    protected or derived checks.

Relevant documentation:

- `docs/baseline_seed_balance_diagnostics.md`
- `docs/supply_reconciliation_workflow_guide.md`
- `docs/results_update_dry_run_preview.md`
- `docs/baseline_seed_rule_inventory.md`
- `docs/check_registry.md`
- `docs/archive/capacity_unmet_convergence_diagnostics_prompt.md`

## What the existing convergence data proves—and does not prove

The capacity-unmet state is useful for explaining what the Python allocator
*intended* to do:

- starting import gap;
- production/capacity allocation;
- imports fallback;
- clipping;
- unresolved fuels.

It does not prove that the next LEAP recalculation produced the expected
balance. In particular:

- `supply_reconciliation_results_update_closure.csv` proves the generated
  reconciliation table closes algebraically; it is not a before/after LEAP
  result comparison;
- `capacity_unmet_convergence.csv` is centered on the eligible import-gap
  signal, not all protected transformation, transfers, losses, demand, and
  derived balance rows;
- a `results_update` run normally consumes one already-exported LEAP state and
  writes the next import workbook. The post-update LEAP result arrives later;
- run ids/manifests identify allocator runs but do not currently form an
  explicit chain of:
  `balance before -> update workbook -> balance after`;
- aggregate gap closure can hide a fuel or protected-flow regression elsewhere.

Real-output inspection on 2026-07-30 confirmed that the current review CSV is a
strong comparison surface. The USA review contained 1,007 rows and the key
`(economy, scenario, year, esto_flow, esto_product)` was unique for that
artifact. Do not assume this remains true: validate uniqueness and fail with a
diagnostic if a future artifact requires another controlled aggregation level.

## Primary design goal

Create an additive, read-only **round-trip iteration comparison** that joins:

```text
before balance diagnostic
        +
the LEAP import workbook generated from that balance
        +
after balance diagnostic
        +
provenance/fingerprints
```

It must answer four different questions separately:

1. Did the allowed updater error signal improve?
2. Did protected or derived balance rows regress?
3. Which LEAP input levers changed between observations?
4. Were the observations genuinely comparable, or did mappings, source data,
   code, workbook selection, scenario/year scope, or LEAP structure change?

## Required metric scopes

Never collapse all diagnostic rows into one unqualified “convergence” number.
Report at least these independent scopes:

### A. Updater objective

Rows with `update_signal_eligible=True`.

Report by economy, scenario, year, and ESTO product, plus overall:

- sum of absolute error in PJ;
- signed error in PJ;
- maximum absolute cell error;
- material mismatch count;
- resolved/new/worsened cell counts;
- closure percentage from before to after.

This is the primary measure of whether `results_update` did its intended job.

### B. Protected-flow health

Rows with `balance_variable_role == "protected"`.

Report the same movement statistics, but never treat these differences as
additional update signals. A worsening protected row is a regression or an
issue to classify.

### C. Derived checks

Rows with `balance_variable_role == "derived_check"`.

Keep these separate because adding parent totals and their components would
double-count energy.

### D. Comparison availability and structural health

Track counts and transitions for:

- `missing_in_leap`;
- `missing_in_reference`;
- `reference_unavailable`;
- mapping issues;
- `update_allocation_required`;
- incomplete projection allocation;
- multiple-LEAP-component comparisons;
- total-balance failures;
- replacement-boundary/placeholder findings when that check exists.

A numeric improvement is not certified if the comparable cell set shrank
because rows became unavailable.

## Cell-level movement classifications

Using a configurable PJ materiality tolerance, classify every joined cell as:

- `resolved`: material before, within tolerance after;
- `improved`: absolute error decreased materially but remains outside tolerance;
- `unchanged`;
- `worsened`;
- `new_mismatch`: within tolerance before, material after;
- `overshot_improved`: error changed sign but absolute error decreased;
- `overshot_worsened`: error changed sign and absolute error increased;
- `not_comparable`: missing from either observation or its comparison contract
  changed.

Retain before/after LEAP values, source values, signed/absolute differences,
status, role, eligibility, classification, owner, comparison grain, and
allocation provenance. Do not use raw percentage difference as the primary
ranking when the source value is zero or very small.

## Intervention attribution

Reuse or extract the stable parts of
`codebase/baseline_seed_comparison_workflow.py` to compare the import workbook
active before the update with the generated update workbook.

At minimum, record changes to:

- `Maximum Production`;
- reserve expressions when production changes require them;
- transformation `Exogenous Capacity`;
- process efficiency and output/feedstock shares, even when they were expected
  to remain unchanged;
- import and export targets;
- transfer assumptions;
- other rows changed by post-processing rules.

Join these lever changes to observed balance movement where a defensible
economy/scenario/year/fuel lineage exists. Where it does not, report the lever
change and balance movement side by side without claiming causality.

## Iteration identity and provenance

Design an additive iteration manifest. Do not widen or repurpose the legacy
capacity-unmet CSV merely because it already exists.

Recommended fields:

- `iteration_series_id`: stable id for one economy/model experiment;
- `observation_id`;
- `observation_index`: 0 for baseline, 1 after update 1, and so on;
- `parent_observation_id`;
- economy, scenarios, review years, update horizon;
- before balance workbook path and fingerprint;
- diagnostic directory and review CSV fingerprint;
- intervention workbook/run label/path and fingerprint;
- baseline or prior seed workbook path and fingerprint;
- git commit and active preset;
- ESTO, 9th, mapping workbook, LEAP template, and relevant runtime-config
  fingerprints;
- LEAP area/model name if available without fragile automation;
- timestamps for generation, manual import/recalculation, balance export, and
  diagnostic run;
- `certified_comparable` plus explicit reasons when false.

The workflow must allow the user to register the manual LEAP import,
recalculation, and export steps without pretending they happened
automatically.

## Proposed outputs

Prefer a small set of human-facing outputs:

1. `iteration_summary.csv`
   - one row per observation transition and metric scope;
   - before/after errors, closure, regression counts, comparability status.
2. `iteration_cell_movements.csv`
   - detailed joined diagnostic cells ranked by material movement.
3. `iteration_lever_changes.csv`
   - parsed import-workbook expression changes.
4. `iteration_manifest_<observation_id>.json`
   - lineage and fingerprints.
5. Optional `iteration_comparison.xlsx`
   - compact summary and largest improvements/regressions;
   - do not copy every full Energy Balance sheet into it;
   - verify programmatically without rendering images.

Debug-heavy join/provenance tables belong under `extra_detail` or
`diagnostics`.

## Exploration tasks

### Task 1: Audit current lineage

Trace one real economy through:

- baseline seed workbook;
- baseline LEAP balance export;
- baseline review output;
- first results-update output workbook;
- post-update LEAP balance export, if one exists;
- post-update review output.

State exactly which links can be inferred safely today and which need explicit
manifest fields. Do not infer iteration order solely from modification times or
four-digit filename dates.

### Task 2: Establish pairing and aggregation contracts

Determine and test:

- the exact diagnostic join key;
- whether every review artifact is unique on that key;
- how aggregate/shared comparison grains are paired;
- how missing/unavailable rows affect the common comparison set;
- which rows are excluded from each metric scope to prevent parent/child or
  derived/component double counting;
- how Current Accounts rows are handled when the experiment concerns Reference
  and Target.

Document decisions before coding the comparator.

### Task 3: Prototype a read-only two-observation comparison

Create notebook-safe functions that accept two existing
`leap_balance_source_review.csv` files and return:

- comparability findings;
- scope summaries;
- cell movements;
- largest improvements;
- largest regressions;
- newly unavailable and newly mapped cells.

Use synthetic fixtures first, then run read-only against available real
artifacts. Do not modify LEAP or rerun the full supply-reconciliation workflow
for initial tests.

### Task 4: Add intervention-workbook comparison

Given the seed/import workbook used before an observation and the update
workbook between observations, produce the lever-change table. Reuse existing
expression parsing and post-boundary logical-key rules; do not compare a raw
module workbook against a post-processed final seed.

### Task 5: Add manifests and notebook orchestration

Only after Tasks 1-4 are understood:

- add manifest helpers;
- add an explicit compare-iterations preset or notebook entry point;
- optionally connect it to `balance_update_workflow.py`;
- keep review generation, update generation, and iteration comparison
  independently runnable.

Do not automate LEAP COM import/recalculation/export as part of this feature.

## Tests and acceptance criteria

Add focused tests for:

- exact key uniqueness and a clear failure for uncontrolled duplicates;
- resolved, improved, unchanged, worsened, new mismatch, and both overshoot
  classifications;
- separate updater/protected/derived summaries;
- common-cell and availability accounting;
- no false improvement when a material row disappears;
- no double counting of derived totals and components;
- source/mapping/input fingerprint drift marking a comparison uncertified;
- legacy review CSVs with additive columns missing where graceful fallback is
  safe;
- seed/update expression parsing across `Data(...)`, constants, and expression
  kind changes;
- deterministic outputs independent of input row order.

Acceptance for a real two-observation pair:

1. A modeller can identify whether eligible import-gap error decreased after
   one LEAP round trip.
2. The report lists the largest protected-flow regressions separately.
3. Every claimed improvement links to the exact before/after balance cells.
4. The intervention workbook’s changed levers are visible.
5. Changed inputs or incomparable scopes prevent a certified convergence
   claim.
6. Existing comparison workbooks, convergence CSVs, and run manifests remain
   readable and unchanged.

## Interim manual workflow

Until this feature exists:

1. Use a stable experiment label and explicit observation number, for example:
   - `20USA_REF_TGT_OBS00_BASELINE_2022_2030`;
   - `20USA_REF_TGT_UPDATE01_FULL`;
   - `20USA_REF_TGT_OBS01_AFTER_UPDATE01_2022_2030`.
2. Export the same scenarios and review years after every LEAP recalculation.
3. Preserve each uniquely labelled diagnostic directory and its
   `leap_balance_source_review.csv`.
4. Compare the same cells in the comparison workbooks, prioritizing:
   - `update_signal_eligible` import rows;
   - protected transformation, transfers, losses, and demand rows;
   - mapping/unavailable issues.
5. Record any code, mapping, source-data, template, or LEAP-structure change
   between observations; treat such a pair as a new experiment unless the
   effect is deliberately being tested.
6. Do not conclude that an update worked merely because its generated closure
   CSV is closed or its allocator reported an allocation.

## Repository and execution rules

- Read all applicable `AGENTS.md` files, `docs/work_queue.md`, and
  `leap_mappings/docs/mappings_system.md`.
- Preserve unrelated working-tree changes.
- Use the pinned Windows interpreter:
  `C:\Users\Work\miniconda3\python.exe`.
- Keep scripts notebook-safe with `#%%` blocks and explicit function
  parameters.
- Do not visually inspect spreadsheet sheets; use programmatic checks.
- Do not change allocation behavior while building the read-only comparator.
- Commit small, independently verified changes with `codex:`-prefixed
  messages.
- When this prompt is fully implemented, move it from `docs/prompts/` to
  `docs/archive/` with the resulting design/findings notes.
