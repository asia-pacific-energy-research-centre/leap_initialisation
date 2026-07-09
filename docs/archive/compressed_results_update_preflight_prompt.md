# Compressed results-update preflight — implementation prompt

Work in:

`C:\Users\Work\github\leap_initialisation`

Read and follow:

- `AGENTS.md`
- `C:\Users\Work\.codex\AGENTS_BALANCE_TABLES.md`
- `C:\Users\Work\.codex\AGENTS_LEAP_EXPORT.md`
- `docs/supply_reconciliation_workflow_guide.md`
- `docs/special_rules_and_design_decisions.md`

Before editing, run `git status --short`. The worktree may contain unrelated
uncommitted changes from other tasks. Preserve them, inspect overlapping diffs,
and do not stage or commit changes you did not author.

## Task

Add a compressed `20_USA` results-update preflight.

The supply reconciliation workflow currently has
`PREFLIGHT_COMPRESSED_PROJECTION`, implemented mainly in:

- `codebase/functions/supply_preflight.py`
- `codebase/supply_reconciliation_workflow.py`

That preflight is primarily a fast integration test of the `baseline_seed`
path. It uses:

- economy `00_APEC`;
- the configured ESTO base year;
- one synthetic projection year (`BASE_YEAR + 1`);
- all future 9th Outlook activity compressed into that projection year;
- isolated outputs;
- no LEAP imports or LEAP-results scraping.

We need a second, complementary preflight that tests the majority of the
`results_update` path using real `20_USA` LEAP balance-export structure but
only two effective years.

The two preflights should be documented and presented together as the fast
checks to run before the long full baseline-seed and results-update runs.

## Existing LEAP balance inputs

Source directory:

`data/leap balances exports/20_USA`

Current workbooks include:

- `full model output all years 24042026 REF.xlsx`
- `full model output all years 27052026 TGT.xlsx`

The Reference workbook currently contains `EBal|2022` through `EBal|2060`.
The Target workbook contains `EBal|2022` and future sheets through 2060 but
does not necessarily contain `EBal|2023`.

Never modify these source workbooks in place.

## Required new preflight

Add a new preflight with a clear name such as:

`preflight_compressed_results_update`

Add notebook-facing toggles consistent with the existing style, for example:

```python
RUN_PREFLIGHT_COMPRESSED_RESULTS_UPDATE = True
PREFLIGHT_COMPRESSED_RESULTS_UPDATE_ONLY = False
PREFLIGHT_COMPRESSED_RESULTS_UPDATE_FAIL_FAST = False
```

Use judgement on exact names, but keep the baseline compressed preflight and
results-update compressed preflight clearly distinct.

## Effective test dataset

Run the new preflight for:

```python
ECONOMIES = ["20_USA"]
CAPACITY_UNMET_PASS_MODE = "results_update"
```

Use two effective years:

- Base year: the configured ESTO base year, currently 2022.
- Synthetic future year: `BASE_YEAR + 1`, currently 2023.

### Reduced LEAP balance workbooks

Create temporary preflight copies of both the REF and TGT LEAP balance
workbooks under the isolated preflight runtime/output directory.

Each reduced workbook should contain exactly:

- `EBal|2022`: copied unchanged from the source workbook.
- `EBal|2023`: a synthetic future balance sheet created from all source
  `EBal|YYYY` sheets where `YYYY > BASE_YEAR`.

For the synthetic sheet:

1. Preserve the LEAP balance sheet's labels, headers and structural columns.
2. Sum corresponding numeric balance values across all future sheets.
3. Preserve signs.
4. Do not use absolute values for the actual synthetic balance values.
5. Validate that future sheets have compatible structure before summing.
6. Do not blindly sum by row position unless row identities and structural
   columns have first been proven identical.
7. If structures differ, align using the stable identifying columns used by
   the balance converter, and fail with a clear diagnostic if rows cannot be
   aligned safely.
8. Do not invent or discard unmatched rows silently.
9. Write an optional absolute-sum diagnostic if useful for detecting signed
   cancellation, but keep it separate from the actual signed synthetic sheet.
10. Preserve the workbook format sufficiently for the existing balance reader;
    do not attempt to produce a LEAP-import workbook.

The REF synthetic sheet must be built only from the REF workbook. The TGT
synthetic sheet must be built only from the TGT workbook.

The absence of a literal `EBal|2023` sheet in the Target source workbook must
not matter because the synthetic future sheet is constructed from all
post-base-year sheets and named `EBal|2023` in the temporary workbook.

### Compressed ESTO and 9th inputs

Reuse or minimally extend the existing compressed-source machinery.

- Keep the ESTO base-year input.
- Compress all future 9th Outlook years into synthetic `BASE_YEAR + 1`.
- For this results-update preflight, preserve scenario separation:
  - Reference source rows should be compressed into Reference.
  - Target source rows should be compressed into Target.
- Do not sum Reference and Target together and then replicate the combined
  value into both scenarios for this test.
- Retain signed sums.
- Produce an absolute-sum diagnostic separately to expose categories hidden by
  signed cancellation.
- Filter/use `20_USA`, not `00_APEC`.

If sharing code with the existing baseline compressed preflight is clean and
low-risk, extract a small helper. Do not rewrite the existing preflight.

## Isolated state and outputs

The new preflight must not mutate production run state.

Use a dedicated root such as:

`outputs/leap_exports/supply_reconciliation/preflight_compressed_results_update/`

Redirect at least:

- output directories;
- checks directories;
- runtime directories;
- yearly/conventional balance directories;
- iterative state paths;
- timing outputs;
- temporary compressed source files;
- temporary reduced REF/TGT balance workbooks.

Disable:

- LEAP imports;
- LEAP branch creation/filling;
- LEAP results scraping;
- production cache reuse;
- reuse of existing economy exports.

Force:

```python
TRANSFORMATION_SUPPLY_CACHE_ENABLED = False
CAPACITY_UNMET_PASS_MODE = "results_update"
```

Snapshot and restore every changed global/config value in `finally`, following
the existing `_snapshot_preflight_state`, `_apply_preflight_compressed_state`,
and `_restore_preflight_state` pattern.

A failed preflight must also restore normal state.

## Balance-workbook resolution

Ensure:

```python
load_balance_demand_inputs(
    ...,
    allow_projection_only_without_balance_exports=False,
)
```

reads the temporary two-sheet `20_USA` REF/TGT workbooks during this preflight.

Do not overwrite or rename the production source workbooks. Prefer explicit
temporary path overrides over relying on filename discovery if that is safer
and clearer.

## Issue-report behaviour

The preflight must regenerate the balance-demand mapping diagnostics through
the real LEAP-export/results-update path.

Write its report under the preflight checks directory, not over the production
CSV.

The report should use the current schema, including:

- `issue_fuel_is_non_actionable`
- `demand_relevant`
- `demand_relevance_basis`

Do not preserve the obsolete `issue_fuel_is_do_not_use` naming.

Always produce a deterministic report artifact:

- If issues exist, write all issue rows.
- If no issues exist, write a header-only CSV or a clearly named summary
  showing zero issues.
- Never leave a stale report from an earlier preflight and present it as the
  current result.

Print a compact summary containing:

- total issue rows;
- actionable demand issue rows;
- ignored/non-demand rows;
- counts by `reason`;
- unique sector/fuel issue keys;
- `Total` fuel rows;
- known-label-exception rescues;
- rollup-resolved rows;
- unresolved rows.

Unresolved demand-relevant leaf rows must remain visible and should fail the
preflight when the normal fail-on-mapping-issues setting requires that.

## Workflow integration

Integrate the new preflight alongside the existing compressed projection
preflight in `run_with_config()`.

Required behaviour:

- Either preflight can be enabled independently.
- Each can run in preflight-only mode.
- Each can be configured fail-fast or warning-and-continue.
- Running the new preflight before a full results update must not affect the
  subsequent production run.
- Do not make the existing baseline preflight depend on real LEAP exports.
- Preserve existing defaults unless there is a strong documented reason to
  change them.

Keep this notebook-friendly. Do not add an argparse-based CLI.

## Meaning of the two preflights

Document the distinction accurately.

### Compressed projection preflight

A fast approximation of the baseline-seed integration path:

- uses `00_APEC`;
- uses the ESTO base year plus one compressed future year;
- exercises source mappings, transformations, transfers, supply workflows,
  workbook construction and future-only category coverage;
- uses projection-only demand;
- does not validate real LEAP results;
- does not verify per-economy or year-by-year behaviour;
- disables LEAP imports.

### Compressed results-update preflight

A fast approximation of the results-update integration path:

- uses `20_USA`;
- uses the base year plus one compressed future year;
- reads temporary reduced LEAP REF/TGT balance workbooks;
- exercises real LEAP balance conversion, balance-demand mapping,
  results-update demand sourcing, issue classification and downstream
  reconciliation wiring;
- does not verify individual-year trajectories;
- does not replace a complete results-update run;
- disables LEAP imports and uses isolated iterative state.

Together, these are the recommended fast integration checks before the
long-running full baseline-seed and results-update runs. They verify most major
code paths, but they do not prove every economy, year, economy-specific rule,
LEAP import, or iterative convergence behaviour.

## Documentation

Update:

- `docs/supply_reconciliation_workflow_guide.md`
- `docs/special_rules_and_design_decisions.md`

In the workflow guide, add a clear **Fast preflight checks** section covering:

1. Why the full runs are slow.
2. The two complementary preflights.
3. What each one covers.
4. What each one does not cover.
5. Recommended order before full runs.
6. Notebook toggles.
7. Output locations.
8. How failures affect continuation.
9. That neither preflight performs LEAP imports.

Recommended order:

```text
Compressed projection preflight
→ compressed results-update preflight
→ full baseline_seed when needed
→ import/recalculate/export in LEAP
→ full results_update
```

Clarify that the compressed results-update preflight uses existing real
`20_USA` balance-export structure, not a newly recalculated LEAP model
corresponding to the compressed inputs. It is therefore a strong structural
and integration test, not a numerical reproduction of a genuine two-year LEAP
run.

In `special_rules_and_design_decisions.md`, add or update an entry using the
next available INIT ID. Record:

- the decision to maintain two complementary compressed preflights;
- why one cannot replace the other;
- why synthetic future values use signed sums;
- why absolute sums are diagnostics only;
- why all state and outputs are isolated;
- limitations and removal/change conditions;
- a dated History entry for the implementation date.

## Tests

Add focused tests for at least:

1. REF workbook reduction produces base and synthetic future sheets.
2. TGT reduction works when literal `EBal|2023` is absent.
3. Signed values are preserved when future sheets are summed.
4. Absolute-sum diagnostics expose cancellation.
5. Structural mismatch produces a clear failure rather than positional
   corruption.
6. Scenario-specific 9th compression keeps Reference and Target separate.
7. Temporary workbook resolution is used by
   `load_balance_demand_inputs(...,
   allow_projection_only_without_balance_exports=False)`.
8. The results-update preflight forces `20_USA`.
9. Cache and LEAP imports are disabled.
10. State is restored after success.
11. State is restored after failure.
12. Output is isolated from production.
13. Zero issues produce a current empty/header-only report rather than leaving
    stale output.
14. Existing compressed projection preflight behaviour remains intact.

Run:

```powershell
& 'C:\Users\Work\miniconda3\python.exe' -m pytest tests/ -k "preflight or balance_demand or supply_reconciliation" -q
```

Then run:

```powershell
& 'C:\Users\Work\miniconda3\python.exe' -m pytest -q --ignore=tmp
```

If the complete suite hangs or exceeds a reasonable timeout, report the last
confirmed test scope and do not claim it passed.

## Manual verification

Run the new preflight in preflight-only mode for `20_USA`.

Report:

- runtime;
- generated temporary REF/TGT paths;
- sheet names in each temporary workbook;
- compressed years;
- scenarios;
- issue counts;
- actionable issue counts;
- unresolved unique sector/fuel keys;
- whether the old 1,384 actionable rows are now resolved or classified
  non-actionable;
- confirmation that production source workbooks and production iterative state
  were not modified.

Provide clickable and plain Windows paths for generated CSV/XLSX outputs.

## Boundaries

- Never edit the source REF/TGT workbooks.
- Never edit `leap_mappings/config/outlook_mappings_master.xlsx`.
- Do not perform LEAP imports.
- Do not enable live LEAP scraping.
- Do not silently discard unresolved leaf mappings.
- Do not treat aggregate parent rows as replacement demand facts.
- Do not rewrite the existing compressed projection preflight.
- Keep changes surgical and notebook-friendly.
- Preserve unrelated uncommitted work.
