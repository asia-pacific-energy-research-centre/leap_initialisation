# Investigate the AUS 2022 LEAP balance export and improve baseline seeds

Type: investigation, targeted implementation, and verification.
Status: completed code-side 2026-07-27; fresh LEAP cycle remains a manual
verification follow-up.

## Short version

Use
`data/leap balances exports - testing/01_AUS/2022.xlsx` as the primary
real-world evidence for finding baseline-seed defects early.

First produce a read-only LEAP-versus-ESTO difference table for Reference 2022.
Then trace the important differences backwards through mappings, the
post-boundary baseline seed, its producer workflow, and its source data.
Classify every investigated difference before changing code. Fix only defects
whose ownership and expected result are demonstrated, add a focused regression
test for each fix, and rerun the narrowest relevant comparison.

Do not assume every LEAP/ESTO difference is a baseline-seed bug. Do not invent
allocations for aggregate mappings. Do not launch a full baseline-seed or
results-update run without explicit user approval.

## Update before use

Paths, branch state, filenames, source vintages, and function names are
point-in-time as of 2026-07-27. Verify them with `rg`, `git log`, and filesystem
inspection before acting.

The balance diagnostic was developed on
`codex/baseline-seed-export-diagnostics`. If it has not been merged, create the
investigation worktree from that branch or another branch containing commits:

- `1204ae3` - read-only LEAP/source balance differences;
- `ad9db88` - shared Level 2+ export-detail validation.

Follow the active repository `AGENTS.md`, `docs/prompts/AGENTS.md`,
`docs/work_queue.md` [21], and:

- `docs/baseline_seed_balance_diagnostics.md`;
- `docs/baseline_seed_rule_inventory.md`;
- `docs/special_rules_and_design_decisions.md`;
- `docs/prompts/baseline_seed_aus_things_to_check.md`.

If the investigation reaches mapping ownership or proposes a mapping change,
also read `C:\Users\Work\github\leap_mappings\docs\mappings_system.md` before
making the change.

## Primary evidence

Workbook:

```text
C:\Users\Work\github\leap_initialisation\data\leap balances exports - testing\01_AUS\2022.xlsx
```

Known facts to confirm rather than assume:

- economy: `01_AUS`;
- scenario: `Reference`;
- year: `2022`;
- units: `Petajoule`;
- one Energy Balance sheet;
- the workbook passes the shared detail check as `Level 2+`;
- Level 2 is sufficient for the results-update backbone.

This file is an input artifact. Do not edit it in place.

## Objective

Build evidence that answers:

1. Which material values in the AUS Reference 2022 LEAP balance disagree with
   the corresponding ESTO values?
2. Which differences are expected, inherited, mapping-related, aggregation
   related, LEAP-structure related, or genuine baseline-seed defects?
3. For each genuine seed defect, which producer or post-boundary completion
   rule created the bad value?
4. What is the smallest safe fix, and does a narrow rerun move the LEAP/source
   comparison in the expected direction without damaging adjacent rows?
5. What new checks should run on every future limited-year cycle so the same
   defect is caught before a full-horizon export?

The desired result is not blindly forcing LEAP to equal ESTO. It is a reviewed
set of discrepancies, proven fixes for real bugs, and durable early-warning
checks.

## Required working method

### 1. Start safely

1. Work in a dedicated git worktree and `codex/` branch.
2. Run `git status --short` before editing.
3. Confirm no long supply-reconciliation run is using the selected worktree.
4. Preserve unrelated changes and commit only files changed for this task.
5. Record a short plan with explicit verification criteria before coding.

### 2. Make the representative workbook a supported diagnostic input

The current notebook diagnostic normally resolves dated REF/TGT filenames
under `data/leap balances exports/<economy>/`. This representative file is a
single Reference/base-year workbook named `2022.xlsx` in the testing tree.

Inspect current behavior before changing it. If the file cannot be passed
directly, add the smallest notebook-friendly input override needed to support:

- one explicit workbook path;
- the scenario and year read from workbook metadata;
- Reference-only execution without requiring or fabricating a Target workbook;
- Level 2+ validation before extraction;
- no copy or rename into the production export directory.

Add synthetic tests for direct-workbook input and Reference-only behavior.
Do not generalize into an unrequested file-ingestion framework.

### 3. Produce the read-only AUS 2022 comparison

Run the limited diagnostic against the representative workbook.

For 2022, ESTO is the primary numeric comparator. Do not substitute 9th
projection values merely because the 9th table is available. Retain 9th
mapping/cardinality metadata only when it helps explain structure or future
update safety.

Write a small, human-facing review table with at least:

- LEAP balance row and fuel;
- mapped ESTO flow and product;
- LEAP value;
- ESTO value;
- `LEAP - ESTO`;
- absolute difference;
- percentage difference where meaningful;
- mapping/component cardinality;
- diagnostic status;
- preliminary owner/classification;
- evidence note;
- next action.

Keep trace-heavy joins in an `extra_detail` or `diagnostics` subfolder. Do not
put dozens of debug files beside the primary review table.

Before prioritizing, separately count:

- value mismatches;
- rows missing from LEAP;
- rows missing from ESTO/comparator;
- unmapped rows;
- total-balance check failures;
- direct one-to-one comparisons;
- aggregate or shared mappings unsafe for direct update.

Rank candidates by energy magnitude and structural importance, not percentage
alone. Near-zero denominators can create misleading percentages.

### 4. Classify before fixing

Every investigated discrepancy must receive exactly one primary
classification:

| Classification | Meaning |
|---|---|
| `baseline_seed_generation_bug` | The producer calculated or wrote a value contrary to its intended rule. |
| `post_boundary_completion_bug` | Seed assembly, zero-fill, canonical share completion, ID merge, or final validation changed/dropped a correct producer value. |
| `source_data_or_vintage_difference` | LEAP and ESTO legitimately reflect different source vintages or inherited source data. |
| `mapping_defect` | The active LEAP-to-ESTO relationship is wrong or incomplete. |
| `mapping_grain_or_allocation_required` | The aggregate comparison is valid, but a row-level correction is not identifiable without an explicit allocation rule. |
| `leap_structure_or_export_issue` | A missing branch, stale area, export setting, units, scenario, or workbook structure explains the result. |
| `leap_model_behavior` | The imported seed is correct, but recalculation/dispatch/constraints transform it into the observed balance. |
| `expected_method_difference` | The seed method intentionally differs from direct ESTO replication. |
| `diagnostic_bug` | Extraction, sign handling, grouping, or comparison logic creates a false discrepancy. |
| `unresolved` | Evidence is insufficient; state exactly what would resolve it. |

Do not label a row a seed bug solely because `difference_pj != 0`.

### 5. Trace genuine candidates end to end

For each high-priority candidate, preserve evidence for this lineage:

```text
ESTO source row
  -> canonical mapping relationship
  -> producer calculation/intermediate record
  -> producer workbook row
  -> assembled post-boundary baseline-seed row
  -> LEAP branch/variable/scenario/year
  -> exported LEAP balance row
```

Where a link is absent, record that as the finding. Compare post-boundary seed
rows with post-boundary seed rows; never compare a raw producer export directly
with a completed seed and call completion differences a regression.

Check signs explicitly for exports, stock changes, transformation inputs,
own-use/loss rows, and other categories where LEAP and ESTO presentation can
differ.

Use `docs/prompts/baseline_seed_aus_things_to_check.md` as prior evidence, not
as proof that an old issue still exists. Re-test its relevant items against
current code and current artifacts.

### 6. Fix only proven defects

Once the lineage demonstrates a code defect:

1. Write a focused failing regression test.
2. Apply the smallest fix in the owning producer or boundary function.
3. Do not refactor adjacent code.
4. Re-run the focused test and relevant existing tests.
5. Regenerate only the narrowest artifact needed to verify the fix.
6. Rebuild the AUS 2022 difference table and show the before/after rows.
7. Check adjacent rows, totals, shares, and conservation rules for regression.
8. Commit one coherent defect at a time with a `codex:` commit message.

If several defects are independent, use separate commits and evidence blocks.

### 7. Turn findings into early-warning checks

For each resolved defect, decide whether recurrence is best caught by:

- a producer unit test;
- post-boundary seed validation;
- LEAP export readiness;
- mapping validation;
- balance comparison diagnostics; or
- a conservation/total check.

Add only the narrowest useful check. If a check is added, moved, or renamed,
update `docs/check_registry.md` and its tests.

## Stop and ask the user before

- changing a modelling assumption or intentional seed methodology;
- changing canonical mappings where more than one relationship is plausible;
- changing ESTO or 9th source data;
- choosing an allocation rule for a many-to-one or one-to-many mapping;
- editing the LEAP area through COM/API;
- launching a full baseline-seed, results-update, or full-horizon workflow;
- overwriting or replacing the representative workbook; or
- accepting a large LEAP/ESTO difference as intentional without documentary or
  code evidence.

If blocked by a manual LEAP import/recalculate/export step, finish all
read-only and code-side work possible, provide the exact workbook/action the
user must run, and stop.

## Out of scope

- forcing every balance row to equal ESTO;
- automatic allocation of aggregate differences;
- broad mapping-system redesign;
- refactoring the supply-reconciliation architecture;
- a 21-economy fleet run;
- silently repairing source data;
- treating Target/future-year behavior as tested by this Reference 2022 file.

Future-year and Target findings require their own limited-year exports after
the base-year path is trustworthy.

## Verification

At minimum:

1. Shared detail inspection reports the real workbook as `Level 2+`.
2. A synthetic Level 1 workbook fails before source loading/conversion.
3. Direct single-workbook Reference-only input is covered if support had to be
   added.
4. The AUS 2022 comparison can be reproduced from notebook controls.
5. Each fixed bug has a failing-before/passing-after regression test.
6. Each fix has row-level before/after evidence and adjacent-total checks.
7. `git diff --check` passes.
8. Relevant focused tests and `tests/test_check_registry.py` pass.
9. The worktree is clean after commits.

Do not claim end-to-end correction unless a fresh LEAP recalculation and export
has actually been performed. A corrected seed or import workbook proves only
the pre-LEAP side of the cycle.

## Deliverables

1. A concise findings document under `docs/` containing:
   - input provenance;
   - comparison summary;
   - ranked discrepancy table;
   - lineage evidence;
   - classifications and ownership;
   - fixes made;
   - unresolved decisions;
   - exact verification performed.
2. The primary AUS 2022 review CSV, with the full Windows path reported to the
   user.
3. Focused tests for input handling and every defect fixed.
4. Small, coherent commits.
5. Updates to `docs/work_queue.md` [21] and `docs/check_registry.md` where
   applicable.
6. On completion, move this prompt from `docs/prompts/` to `docs/archive/` in
   the final commit, following `docs/prompts/AGENTS.md`.

## Final report format

Lead with:

- how many material discrepancies were reviewed;
- how many were proven baseline-seed/code defects;
- how many fixes landed;
- what remains a mapping/methodology/manual-LEAP decision; and
- whether a fresh LEAP cycle is still required.

For each fix, name the owning function, the regression test, and the
before/after AUS balance evidence. Clearly separate:

- confirmed;
- inferred but not yet LEAP-verified; and
- unresolved.
