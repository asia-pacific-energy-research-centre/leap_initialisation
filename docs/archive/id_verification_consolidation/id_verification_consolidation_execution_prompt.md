# ID/Branch-Match Consolidation + Preflight-State Dedup Execution Prompt

## Context

`leap_initialisation` runs two live presets in `codebase/supply_reconciliation_workflow.py`:
`_PRESET_BASELINE_SEED` and `_PRESET_RESULTS_UPDATE`. A prior review of every
verification/validation mechanism touching these presets found several
duplicated implementations. Two items from that review were already fixed
(see `docs/special_rules_and_design_decisions.md` INIT-005 history and the
`split_documented_exclusions`/`check_producer_coverage` consolidations already
in the codebase — read those two diffs first via `git log --oneline -- codebase/functions/patch_baseline_seeds.py codebase/functions/baseline_seed_validation.py codebase/functions/supply_leap_io.py` to see the pattern this repo already uses for this class of fix).

This prompt covers the two remaining, unstarted items:

1. **Four independent "does this row have a valid canonical LEAP ID"
   implementations** (the highest-risk, highest-value item — read the whole
   "Item 1" section before writing any code).
2. **Preflight state-override duplication + a diagnostic-CSV trio with a
   repeated write pattern** (lower risk, lower value — do this after Item 1
   is verified, or independently if you want a smaller warm-up task first).

**Do not treat this as "delete the duplicates and call the official one."**
Investigation already found that one of the four implementations bundles real,
non-duplicate business logic with genuinely wasted computation. Read the
"What must be preserved" subsection for Item 1 before changing
`supply_results_saver.py`.

## Before starting

1. Read `AGENTS.md` for repo routing and the supply-reconciliation workflow
   conventions.
2. Read `docs/special_rules_and_design_decisions.md`, specifically **INIT-005**
   (deferred validation) and **CROSS-001** (full-model-export and LEAP-import
   ID integrity) — these are the design decisions the "official" validator
   (`baseline_seed_validation.py`) already implements and that this
   consolidation must not violate.
3. Read `docs/baseline_seed_rule_inventory.md` for the SEED-001..012 rule
   catalogue.
4. Run `git status --short` and preserve all existing unrelated changes.
5. There is no existing automated test coverage for any of the four
   ID-matching implementations or the two preflight-state functions. You are
   building the safety net as part of this task, not relying on one that
   already exists — budget time for that.

---

## Item 1: Four independent ID/branch-match implementations

### The four mechanisms, in detail

**(A) `_merge_ids_from_reference_export`** — nested function inside
`save_results_linked_single_workbook`, `codebase/functions/supply_results_saver.py:1587-1765`.
Called once, at `supply_results_saver.py:2308-2312`. Matches every row's
`Branch Path`/`Variable`/`Scenario`/`Region` against `data/full model
export.xlsx` (loaded as `verification_data`/`source_data`, path constant
`RESULTS_VERIFICATION_EXPORT_PATH` in `codebase/supply_reconciliation_config.py:267`
— **this is the same file** `baseline_seed_validation.py`'s
`enrich_seed_ids_from_template` uses as its `template_path`). Two-pass merge:
exact match on all four keys, then a Branch+Variable-only fallback for rows
still unmatched. Produces `(export_df, unmatched_id_rows)`.

**(B) `enrich_seed_ids_from_template`** —
`codebase/functions/baseline_seed_validation.py:1266-1350`, called from
`validate_seed_rows` inside `prepare_seed_rows_for_write`
(`baseline_seed_validation.py:1563-1649`), which is called from
`save_combined_supply_transformation_export` and
`write_per_economy_combined_workbooks` in `supply_leap_io.py` — i.e. this is
the "official" framework everything ultimately funnels through before a
baseline-seed workbook is written. Matches **per-column** (BranchID keyed on
branch alone, VariableID keyed on branch+variable, ScenarioID keyed on
scenario alone, RegionID keyed on region alone, with a "sole template
RegionID" fallback) — a different, more permissive algorithm than (A)'s
combined-key-then-fallback approach. Also runs a "known LEAP-label exception"
alias-rescue pass (`_rescue_ids_via_known_leap_label_exceptions`) that (A)
does not have. Feeds SEED-003 (missing IDs), SEED-004 (nonzero rows with
missing IDs), SEED-011 (branch not in canonical export).

**(C) `_build_source_diagnostics`** —
`codebase/functions/supply_preflight.py:806-867`, called from
`supply_results_saver.py:3865-3869`. **Not itself a duplicate matching
algorithm.** It's a thin reformatter that repackages two independent inputs
into one CSV: `balance_demand_issues` (unrelated — sector/fuel mapping
completeness, not ID matching) and `nonzero_missing_id_rows` (derived from
(A)'s output — see "the wasted-computation chain" below). Can raise if
`SUPPLY_RECONCILIATION_FAIL_ON_SOURCE_DIAGNOSTICS`
(`supply_results_saver.py:3881-3888`).

**(D) `validate_seed_files`** —
`codebase/functions/patch_baseline_seeds.py:443-528`. Reads every
`leap_import_baseline_seed_*.xlsx` already on disk and re-checks each row's
IDs against the template with a **third** distinct algorithm (per-column
lookups built via `_build_id_lookup`, case-insensitive branch-path matching).
Runs automatically at the end of every `run_patch()` call
(`patch_baseline_seeds.py:1025`) but **its return value (`total_bad`) is
discarded by its only caller** — it is purely a printed report, never wired
into any pass/fail decision. It duplicates checking that `_patch_one` already
did moments earlier via `prepare_seed_rows_for_write` (which *does* raise on
blocking findings before the file is ever written).

### The wasted-computation chain (confirmed by tracing data flow — do not skip this)

`save_results_linked_single_workbook` (containing (A)) writes a standalone
per-producer workbook (e.g. `supply_leap_imports_<econ>_<scenario>.xlsx`).
That file is later passed as a `source_workbooks_by_workflow` entry into
`write_per_economy_combined_workbooks`, which re-reads it from disk and runs
(B) (`enrich_seed_ids_from_template`) on it. (B) **unconditionally overwrites
all four ID columns** (`baseline_seed_validation.py:1313-1333`,
specifically `result["BranchID"] = branch_keys.map(branch_ids).fillna(-1).astype(int)`
and the equivalent lines for VariableID/ScenarioID/RegionID — VariableID has
one exception, see below). This means **every ID value (A) computes is
discarded and recomputed from scratch by (B) before the row ever reaches a
final workbook.** The ID-matching portion of (A) is provably dead computation
for any row that flows through the normal baseline-seed/results-update
pipeline.

### What must be preserved exactly (do not delete this logic, only relocate/reuse the matching primitive it depends on)

(A) is not *only* dead ID computation. Inside the same function,
`supply_results_saver.py:1705-1753`, there is row-filtering business logic
with no equivalent anywhere else:

- A row under `Demand\All demand aggregated\...` with no canonical branch
  match (`BranchID` still NA after both merge passes) is **dropped** if every
  year value is zero (`drop_zero_placeholder_mask`), or **retained with
  BranchID=-1** if any year value is nonzero (`retain_missing_mask`) — the
  retained case is a deliberate signal that a real LEAP branch is missing and
  needs to be added/mapped; dropping it would hide the gap.
- This retain/drop decision depends on *which rows are unmatched*, which
  today comes from (A)'s own two-pass merge. Also note the alias-list
  interaction: `KNOWN_LEAP_LABEL_EXCEPTIONS` (imported at the top of
  `supply_results_saver.py`) is consulted here to avoid dropping rows whose
  branch label is a reviewed spelling alias — (B) has its own, separate
  alias-rescue pass (`_rescue_ids_via_known_leap_label_exceptions`) using the
  same `KNOWN_LEAP_LABEL_EXCEPTIONS` constant but different code.
- (B)'s VariableID matching (`baseline_seed_validation.py:1317-1328`) already
  has a special case to preserve a valid VariableID on a retained
  aggregate-demand placeholder row that has no BranchID — i.e. (B) was
  already written with awareness that upstream (A)-style retained rows exist.
  This is evidence the two were meant to interoperate, not stay fully
  independent.

**Constraint: any change to (A) must produce the same retain/drop decision
per row, driven by "is this branch matched in the canonical template,"
regardless of which matching algorithm answers that question.**

### `nonzero_missing_id_rows` contract (feeds (C) and a hard error gate — must not change shape)

`supply_results_saver.py:2555-2585`: after (A) produces `unmatched_id_rows`,
a second dataframe `nonzero_missing_id_rows` is derived — the subset of
`export_df` rows whose (Branch Path, Variable, Scenario, Region) key is in
the unmatched set **and** have at least one nonzero year value. This flows to:

- `supply_results_saver.py:3889-3895` — an unconditional hard `[ERROR]` print
  block when `RESULTS_SINGLE_FILE_OUTPUT and not _nonzero_missing_id_rows.empty`.
- `_build_source_diagnostics` (C), which expects columns `Branch Path`,
  `Scenario`, and at least one year column (it only reads the *first* year
  column it finds per row, `supply_preflight.py:841-847` — check this doesn't
  silently break if you change column ordering).

Preserve this contract (same trigger condition, same consuming columns) even
if you change how "unmatched" is computed.

### Proposed scoped consolidation (confirm this plan makes sense for the actual code you find before executing — the summary above was written from a prior read, re-verify line numbers first since they will have shifted)

1. **(A) → stop computing IDs it can prove are discarded.** Do not call it
   `_merge_ids_from_reference_export` if it no longer merges IDs — rename to
   reflect its real remaining purpose (row-filtering + "is this branch
   present in the canonical template" detection for the aggregate-demand
   retain/drop decision and the unmatched report). Have it determine
   "matched/unmatched" by calling (B)'s branch/variable resolution logic (you
   may need to extract a smaller pure function from `enrich_seed_ids_from_template`
   — e.g. "given a branch/variable key, is there a canonical match" — rather
   than importing the whole ID-overwriting function, since (A)'s call site
   runs *before* (B) runs downstream and should not itself finalize IDs it
   knows will be overwritten). Keep the retain/drop filtering and the
   `unmatched_id_rows` report output shape unchanged (same columns, same
   `reason` semantics) so `RESULTS_UNMATCHED_ID_REPORT_FILENAME` and
   `nonzero_missing_id_rows` downstream consumers don't need to change.
2. **(C) `_build_source_diagnostics`** — should need no logic change if (1)
   preserves `nonzero_missing_id_rows`'s shape. Verify with a test rather than
   assuming.
3. **(D) `validate_seed_files`** — replace its bespoke per-row matching with
   a call into (B)'s resolution logic (or a shared helper extracted from it),
   applied per seed file. Since its result is already discarded by its
   caller, this is the lowest-risk of the three changes — a regression here
   changes what gets printed, not what gets enforced. Still write a test
   proving it flags the same class of mismatch it used to.
4. **Do not** attempt to make the aggregate-demand retain/drop decision "official"
   inside `baseline_seed_validation.py`. That decision is specific to how
   `supply_results_saver.py` assembles aggregate-demand rows and mixing it into
   the generic validator would couple two things that should stay separably
   testable.

### Verification requirements (mandatory before trusting this on production data)

There is no existing test coverage for any of these four functions. Build it
as part of this task:

1. **Unit tests** for whatever new/changed shared matching primitive you
   extract from (B), and for (A)'s renamed function — cover: exact match,
   Branch+Variable-only fallback match (does the new approach still recover
   these, or did (A)'s two-pass fallback catch cases (B)'s per-column
   matching wouldn't? If per-column matching is strictly more permissive this
   should be a non-issue, but verify with a constructed counter-example
   before assuming), zero-value aggregate-demand row dropped, nonzero-value
   aggregate-demand row retained with BranchID=-1, alias-exception rescue
   still works from both directions.
2. **Equivalence test against real data, not just synthetic fixtures.** Before
   changing anything, run (or locate a recent run of)
   `codebase/supply_reconciliation_workflow.py` for a single economy (e.g.
   `01_AUS`, per `docs/prompts/supply_reconciliation_full_baselineseed_run_execution_prompt.md`
   conventions — launch detached, poll per `AGENTS.md`) and save the
   `outputs/leap_exports/supply_reconciliation/workbooks/supply_leap_imports_01_AUS_*.xlsx`
   file(s) and the `supporting_files/checks/supply_reconciliation_unmatched_id_rows.csv`
   as a "before" snapshot. After your change, rerun the same single-economy
   run and diff: the final `leap_import_baseline_seed_01_AUS_*.xlsx` output
   (should be byte-for-byte identical or explain every difference), the
   `combined_st_01_AUS_*_rule_findings.csv` (same blocking-finding count),
   and the unmatched-ID report (same rows, possibly different `reason` text
   if you changed the matching algorithm's internal labeling — flag any
   row-set difference, don't just diff text).
3. Run the full test suite (`python -m pytest tests/ -q`) — expect ~434+
   passed, 0 failed (matches the baseline at the time this prompt was
   written; if the count differs significantly, investigate before
   proceeding, don't just note the new number).

---

## Item 2: Preflight-state duplication + diagnostic-CSV trio

### Part A: `_apply_preflight_compressed_state` vs `_apply_preflight_results_update_state`

`codebase/functions/supply_preflight.py:1125-1187` (projection preflight) and
`codebase/functions/supply_preflight.py:1608-1699` (results-update preflight).
**Do not merge the two preflights themselves** — `docs/special_rules_and_design_decisions.md`
INIT-009 explicitly documents why they must stay separate (one exercises
synthetic 9th-projection data on `00_APEC`, the other exercises real LEAP
balance-export structure on `20_USA`; each covers code paths the other does
not). This item is only about the two **state-override helper functions**,
which are ~90% identical:

- Both set the same 8 `workflow_cfg.*` module globals (ESTO/ninth paths,
  base/compressed year, baseline-seed validation window).
- Both call the identical sequence of 7 `importlib.reload(...)` calls.
- Both build an `overrides` dict passed to `_broadcast_config_overrides`
  (`supply_preflight.py:1577-1600`) with a large common subset: `ECONOMIES`
  (hardcoded `["00_APEC"]` vs. an `economy` parameter), `SCENARIOS`,
  `FINAL_YEAR`, `BALANCE_EXPORT_YEARS`, `OUTPUT_DIR`, `EXPORT_OUTPUT_DIR`,
  `TRANSFORMATION_EXPORT_OUTPUT_DIR`, `YEARLY_BALANCE_DIR`,
  `CONVENTIONAL_BALANCE_DIR`, `RESULTS_CHECKS_DIR`, `RESULTS_RUNTIME_DIR`,
  `RESULTS_SINGLE_FILE_NAME` (different value per mode), the five
  `LEAP_IMPORT_*_TO_LEAP`/`LEAP_IMPORT_CREATE_BRANCHES`/`LEAP_IMPORT_FILL_BRANCHES`
  flags (all `False` in both), `AGGREGATED_DEMAND_INCLUDE_IN_LEAP_IMPORT`,
  `OTHER_LOSS_OWN_USE_INCLUDE_IN_LEAP_IMPORT`,
  `ZERO_OTHER_DEMAND_INCLUDE_IN_LEAP_IMPORT`,
  `RUN_LEAP_FUEL_BRANCH_PROBE_AT_START`, `SCRAPE_LEAP_RESULTS`,
  `TRANSFORMATION_SUPPLY_CACHE_ENABLED`, `SKIP_ECONOMIES_WITH_EXISTING_EXPORTS`,
  `DIRECT_DEMAND_BASE_TABLE_PATH`, `DIRECT_DEMAND_PROJECTION_TABLE_PATH`,
  `DIRECT_DEMAND_BASE_YEAR`, `DIRECT_DEMAND_PROJECTION_YEARS`,
  `BALANCE_DEMAND_BASE_TABLE_PATH`, `BALANCE_DEMAND_PROJECTION_TABLE_PATH`.
- The results-update variant additionally sets: `economy` (parameterized,
  not hardcoded), `CAPACITY_UNMET_PASS_MODE="results_update"`,
  `USE_AGGREGATED_DEMAND_AS_DUMMY=False`,
  `OTHER_LOSS_OWN_USE_PROXY_STAGE="second"`,
  `RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT=False`,
  `RUN_ELECTRICITY_HEAT_INTERIM=False`, `BALANCE_DEMAND_REF_WORKBOOK_PATH`,
  `BALANCE_DEMAND_TGT_WORKBOOK_PATH`, `BALANCE_DEMAND_EXPORTS_ROOT`,
  `DIRECT_DEMAND_PROJECTION_ECONOMY`, `DIRECT_DEMAND_BASE_ECONOMY`.

**Approach:** write one function, e.g.
`_apply_preflight_compressed_state(*, source_files, preflight_root, scenarios, mode: Literal["projection", "results_update"], economy="00_APEC", reduced_ref_path=None, reduced_tgt_path=None)`,
that builds the common override dict, then merges in the
`results_update`-only keys when `mode == "results_update"`. Keep the two
call sites (`run_preflight_compressed_projection`,
`run_preflight_compressed_results_update`) as separate functions calling this
one shared helper — do not merge the preflights themselves.

**Verification:** there's an existing test file,
`tests/test_preflight_compressed_results_update.py` — read it first, extend
it (and add a projection-preflight equivalent if one doesn't exist) to assert
the exact override dict produced by each mode, so a future edit to one mode
can't silently drop a key the other mode needs. Also check
`tests/test_preflight_smoke.py`.

### Part B: the metadata-mismatch / unit-review / config-mapping-mismatch trio

`codebase/functions/supply_results_saver.py:2600-2725`. Three nested
functions/blocks — `_collect_metadata_mismatches_against_reference` (defined
~1767, invoked ~2296), `_collect_gigajoule_template_rows` (defined ~1916,
invoked ~2300), `_collect_mapping_config_mismatches_against_reference`
(defined ~2001, invoked ~2315) — each independently: check non-empty, mkdir,
write a CSV via `_sort_output_frame_for_csv(...).to_csv(...)`, print a
`[WARN]` header + count + up-to-30-row preview + "...plus N more" tail. The
**collection** logic (what counts as a mismatch) is genuinely different per
report and should stay separate. The **reporting boilerplate** (the
non-empty check + mkdir + write + WARN-with-preview print pattern) is
identical three times and is a legitimate candidate for a shared helper, e.g.:

```python
def _write_diagnostic_report(
    rows: pd.DataFrame,
    path: Path,
    *,
    header: str,
    row_formatter: Callable[[pd.Series], str],
    preview_limit: int = 30,
) -> None:
    ...
```

This is lower-value than Item 1 and Part A — treat it as optional polish, not
a blocking requirement of this task. Only do it if Item 1 and Part A are
complete, verified, and committed first. Do not let this part delay or risk
the higher-value work above.

---

## Constraints that apply to all of the above

- This repo is notebook-first (`#%%` cell markers); do not restructure files
  wholesale, keep changes surgical.
- Never commit without running the full test suite first and reporting the
  pass/fail counts.
- Do not silently change behavior for a case you haven't explicitly tested —
  if you find a row-set difference in the equivalence test that you can't
  explain, stop and report it rather than guessing at a fix.
- Follow the commit-message convention already used in this repo's recent
  history (`git log --oneline -20`) — short, present-tense, prefixed
  consistently with how the last several commits are written.
- If you find the actual current code has drifted from what's described in
  this prompt (line numbers, function names, call sites), re-verify against
  the live file before proceeding — this prompt was written from a point-in-time
  read and the repo may have changed.
