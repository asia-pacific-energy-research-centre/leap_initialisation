# Scope: retiring / archiving `data/full model export.xlsx`

**Goal.** Make `data/full model export.xlsx` safe to archive (move out of `data/`)
without silently breaking any workflow. Today it *cannot* be archived — it is
still read at runtime by several live paths. This document scopes the work that
makes archiving safe, as a sequence of one-commit tasks with explicit acceptance
criteria.

> Status when written: **2026-07-21.** The per-economy **ID-routing** work
> ([work_queue.md](work_queue.md) [7]) is complete — real economies (`01_AUS`,
> `12_NZ`, `20_USA`) resolve to their own templates and no longer take IDs from
> this file. What remains are the **shared-union**, **aggregate/verification**,
> and **fallback** uses below. Archiving is a *repoint-and-verify* task, not a
> delete. After archiving, run the fleet-wide provisional baseline-seed check
> described below before treating the retirement as complete.

## Provisional seed naming policy

Baseline seeds produced with a computer-generated (`_COMP_GEN`) template are
now marked as provisional:

```text
leap_import_baseline_seed_02_BD_PRELIM_YYYYMMDD.xlsx
```

Seeds produced with a real economy template retain the normal filename:

```text
leap_import_baseline_seed_01_AUS_YYYYMMDD.xlsx
```

`PRELIM` is provenance, not a validation result. A provisional seed can be a
useful and internally consistent workflow output, but its IDs are still based
on the source area used to create the `_COMP_GEN` template (usually USA). When
a real template arrives, regenerate that economy and confirm the filename no
longer carries `PRELIM` before calling its seed import-ready.

The marker currently applies to final per-economy baseline-seed workbooks. It
does not imply that every intermediate source workbook has a `PRELIM` suffix.

## What this file is

`data/full model export.xlsx` is a LEAP **Export** of the `20_USA` area. Its
content is expected to be essentially the same as
`leap_export_templates/leap_export_template 20_USA.xlsx` (both are the USA area),
which is why it worked as a stand-in "canonical" reference while every economy
shared one area. **Confirming that equivalence is Task 0** — the whole plan rests
on repointing these uses at the `20_USA` template (or a purpose-named canonical
copy) instead.

## Implementation record (2026-07-21)

- **Task 0 passed.** The former `data/full model export.xlsx` and
  `data/leap_export_templates/leap_export_template 20_USA.xlsx` had identical
  SHA-256 hashes (`a686e9dc517aa56b36e4de55ba5839ac6c877d4a9561cad55e52177abca48c0d`),
  9,182 Export rows, key/ID columns, and parsed sheet contents.
- **Tasks 1-6 were implemented in commit `8d4043d`.** The former file was moved
  to `data/archive/full model export_retired_20260721.xlsx`; an older,
  non-identical archive copy was retained unchanged. The shared fuel catalog
  rebuilt byte-identically (6,191 rows; SHA-256
  `33a64998ad2cc0b7e7011911637c01b6d92d816f1acad3a4c064f58f06aee589`).
- The runtime sweep found additional fallback/reference users in
  `aggregated_demand_workflow.py`, `electricity_heat_interim_workflow.py`,
  `baseline_seed_comparison_workflow.py`, `transformation_workflow.py`, and
  `transfers_workflow.py`; these were also repointed to the canonical USA
  template.
- **Task 7 remains pending.** The post-retirement fleet run has not been used
  to certify provisional baseline seeds; it must be run under the execution
  handoff below before claiming fleet-wide import readiness.

## Inventory — every live dependency (grep the path string, not the constant)

Classified by *what the file is read for*. "Runtime read" = the file is actually
opened during a normal run; "fallback" = only opened when a primary path yields
`None`/misses.

| # | Site | Class | Reads at runtime? | Action to archive |
|---|---|---|---|---|
| A | `fuel_catalog_preflight.py:36` `DEFAULT_FULL_MODEL_EXPORT_PATH` | shared-union fuel-branch catalog source ([7]/[11]) | **YES — and currently the *sole* source**: the catalog is LEAP-probe **+** full-model-export, but the probe needs the decommissioned LEAP API (`LEAP_API_BLOCKED`), so the export alone feeds the catalog today | Repoint to the canonical `20_USA` template (or a named `canonical fuel branch union.xlsx`). Highest-risk item — do it first and verify the catalog is byte-stable. |
| B | `supply_results_saver.py:3796` | cross-economy single-file combined export `template_path` (`RESULTS_VERIFICATION_EXPORT_PATH`) | **YES** — read for IDs of the all-economy single-file artifact | Repoint to the `20_USA` template. Already documented as a deliberate pin; the artifact spans all economies so no one area is "correct" — USA is the intentional reference. |
| C | `supply_results_saver.py:1772` `_load_results_verification_data` | results-verification metadata-mismatch reference (`RESULTS_VERIFICATION_EXPORT_PATH`, `USE_RESULTS_VERIFICATION_EXPORT_SOURCE=True`) | **YES** — live by default | Repoint to the `20_USA` template. Diagnostic only (never raises), but it is read. |
| D | `workflow_common.py:760` `diagnose_missing_canonical_branches` | branch-existence diagnostic vs canonical export (defaults to `fuel_catalog_preflight.DEFAULT_FULL_MODEL_EXPORT_PATH`) | **YES** when called — informational, warns and skips if missing | Follows A automatically (shares A's default). No separate work if A is repointed. |
| E | `supply_reconciliation_config.py:310` `RESULTS_VERIFICATION_EXPORT_PATH` (+ `:321` `FULL_MODEL_EXPORT_CATALOG_PATH` alias) | the constant behind B, C, and the resolver fallback in `supply_leap_io:1426/1438` and `supply_preflight:576/757` | mixed | Point the constant itself at the canonical `20_USA` template once B/C are confirmed. Kills several fallbacks at once. |
| F | `supply_branch_classification.py:20` `SUPPLY_ROOT_CLASSIFICATION_SOURCE_PATH` | Resources branch-label/existence source | fallback — the seed path threads a per-economy template (`3756ccb`, [8]); the constant is the standalone/`source_path is None` default | Repoint the constant to the `20_USA` template; confirm no seed-path caller relies on the `None` default. |
| G | `workflow_config.py:184` `ANALYSIS_INPUT_CANONICAL_TEMPLATE_PATHS` | canonical **column layout** discovery for the analysis-input workbook format | conditional — the dispatcher skips entries that don't `exist()`; on the decommissioned API write path | Drop the `full model export.xlsx` entry (it is `[full model export, LEAP_EXPORTS_ROOT]`); the exports root already supplies the layout. Verify the dispatcher still finds a canonical workbook. |
| H | `patch_baseline_seeds.py:87` `FULL_MODEL_EXPORT_PATH` | deliberate aggregate/no-template fallback for the patcher | fallback | Repoint to the `20_USA` template; per-economy writing/validation already resolve `_template_for_economy`. |

### Out of scope / non-production references (leave alone)
Tests that build their own `tmp_path / "full model export.xlsx"` fixtures;
`scripts/`, `scrapbook/`, `old_workflows/`, `mapping_tools/`; and any
`leap_utilities` path. These do not gate archiving the `data/` copy.

## Task breakdown (one commit each)

0. **Confirm `full model export.xlsx` ≡ `leap_export_template 20_USA.xlsx`.**
   Compare Branch Path / Variable / Scenario / Region and all four ID columns.
   If identical (or a documented superset), the plan proceeds; if they diverge,
   the repoint target must be re-chosen (or a purpose-named canonical copy cut).
   *No repoint until this passes.*
1. **A + D — fuel catalog / branch diagnostic.** Repoint
   `DEFAULT_FULL_MODEL_EXPORT_PATH` to the canonical target. Rebuild the catalog
   and assert it is unchanged vs the committed `leap_fuel_branch_catalog.csv`.
   Highest risk because it is the sole live catalog source under `LEAP_API_BLOCKED`.
2. **B + C + E — results-verification / single-file artifact.** Repoint
   `RESULTS_VERIFICATION_EXPORT_PATH` (and the `FULL_MODEL_EXPORT_CATALOG_PATH`
   alias). Confirm the single-file combined workbook and the metadata-mismatch
   diagnostic are unchanged.
3. **F — supply-root classification.** Repoint the constant; confirm the seed
   path is unaffected (it already threads a per-economy template).
4. **G — analysis-input canonical layout.** Remove the `full model export.xlsx`
   entry; confirm the dispatcher resolves a canonical workbook from the exports
   root.
5. **H — patcher fallback.** Repoint; confirm per-economy patch writes are
   unaffected.
6. **Archive.** Move `data/full model export.xlsx` to `data/archive/` (or delete),
   run the full acceptance gate below, and update any manifest/docs. Keep the
   canonical `20_USA` template as the single source going forward.

7. **Run the provisional-fleet acceptance pass.** After Tasks 0-6 are
   complete, run the all-economy baseline-seed workflow using the execution
   procedure below. At minimum this covers every economy whose resolved
   template is still `_COMP_GEN`; preferably run all 21 configured economies so
   the same pass also exercises the three real-template routes (`01_AUS`,
   `12_NZ`, and `20_USA`). This is a strong integration test of retirement and
   workflow behavior, but it is not proof of economy-specific ID correctness
   for the provisional economies.

## Acceptance criteria (the gate before archiving)

- Task 0 equivalence confirmed and recorded.
- Fuel catalog rebuild is identical to the committed catalog CSV.
- A grep for `full model export.xlsx` across `codebase/` (excluding tests /
  scrapbook / old_workflows / scripts / mapping_tools) returns **no runtime
  read** — only, at most, a documented archived-path reference.
- One end-to-end run (NZ or AUS, whichever is fresh) with the file **moved out of
  `data/`** completes without a `[WARN] … not found`, an empty catalog, or any
  new `BranchID=-1` row that was not already present.

The post-archive fleet pass must additionally demonstrate:

- every `_COMP_GEN` economy receives a current seed whose filename contains
  `PRELIM`;
- every real-template economy receives a current seed without `PRELIM`;
- the resolved template path and provisional/real status are recorded per
  economy;
- no seed is called LEAP-import-ready solely because the workflow completed;
  unresolved IDs, unknown paths, and validation findings are reported by rule
  and economy;
- the shared fuel catalog is non-empty and its rebuild is identical to (or
  explicitly explained against) the committed catalog;
- per-economy readiness, region, duplicate-key, producer-coverage, canonical
  share, conservation, and deferred-error diagnostics are collected;
- outputs are classified using modification timestamps from this run, not
  merely by files already existing on disk.

## Post-retirement fleet run: execution handoff

Use the notebook-safe entry point in
`codebase/supply_reconciliation_workflow.py` with
`ACTIVE_PRESET = _PRESET_BASELINE_SEED`, all three scenarios, and
`THROW_ERROR_AFTER_RUN = True`. The standard full-run economy order and
scenario list are defined by
`docs/prompts/supply_reconciliation_full_baselineseed_run_execution_prompt.md`;
read the live values from the workflow before launching rather than copying an
old list into a new script.

The expected provisional set is currently:

```text
02_BD, 03_CDA, 04_CHL, 05_PRC, 06_HKC, 07_INA, 08_JPN, 09_ROK,
10_MAS, 11_MEX, 13_PNG, 14_PE, 15_PHL, 16_RUS, 17_SGP, 18_CT,
19_THA, 21_VN
```

The real-template set currently includes `01_AUS`, `12_NZ`, and `20_USA`.
Confirm this from the resolver at run time because the set changes as new
templates arrive.

Before launch:

1. Read `AGENTS.md`, this document, and the full baseline-seed execution
   prompt.
2. Run `git status --short`; preserve unrelated changes and do not stage them.
   Restore any temporary economy-scope override before a fleet run, unless the
   run metadata explicitly records a deliberate subset.
3. Record the starting commit, configuration, economy list, scenarios, start
   time, and exact launch command.
4. Confirm no other workflow Python process is running.
5. Confirm the retirement repoints are committed and
   `data/full model export.xlsx` is unavailable for the archive acceptance
   test.

Launch detached with `C:\Users\Work\miniconda3\python.exe`, using new,
uniquely timestamped stdout/stderr logs under `outputs/logs/`. Record the PID
and a metadata file containing the commit, start time, command, and log paths.
Do not overwrite a prior run log or launch inline behind a tool timeout.

While healthy, poll no more often than once every ten minutes. At each poll,
record process/CPU state, latest stage/economy/scenario, new warnings/errors,
and newly modified per-economy workbooks. Silence in a buffered log is not a
stall; a flat CPU time across polls is the relevant stall signal. Do not stop a
healthy run merely to inspect it.

After completion, produce an economy-by-economy table with one of:

- **Completed successfully** — fresh workbook from this run and no deferred
  error attached;
- **Completed with warnings** — fresh workbook but non-blocking findings;
- **Export failed** — no fresh workbook from this run;
- **Attempted but incomplete** — started but did not reach export completion;
- **Not attempted** — never reached before termination.

Review the consolidated rule findings across all rows, not only
`blocking=True`. The configured baseline-seed policy downgrades some blocking
findings to warnings so the run can expose the complete fleet picture. Do not
silently turn a finding into an exception or loosen validation to make the run
green. Classify each issue as infrastructure, diagnostic-only,
data/configuration, export validation, or calculation/domain logic, and leave
mapping/design decisions for explicit user review.

The final report must include the start/end commits and times, exact commands,
all log paths, per-economy statuses and output paths, `PRELIM`/template
provenance, grouped findings, conservation/deferred errors, catalog results,
comparison/timing outputs, any restarts, unresolved import-readiness issues,
and final `git status --short`. Confirm that no workflow process remains.

## What this fleet run proves — and what it does not

It is strong evidence that the retired-file replacement works across the
workflow: catalog loading, template routing, seed writing, readiness checks,
scenario coverage, and diagnostics all execute across many economies. It is
not evidence that a `_COMP_GEN` economy's IDs are its own. Those economies stay
provisional until a real template is available and that economy is regenerated
and revalidated. Do not bulk-regenerate merely to clear a `PRELIM` marker; the
marker is cleared by real-template provenance, not by another run.

## Traps (from `work_queue.md` "Traps that already cost time")

- **Grep the path string, not the constant name.** `aggregated_demand`'s
  `FULL_MODEL_EXPORT_PATH` was missed once because the sweep grepped
  `EXPORT_ID_LOOKUP_PATH`. Re-run the path-string grep after every repoint.
- **Check the callers, not just the function.** A repoint can be a production
  no-op if every caller passes the path explicitly (the `073c489` bypass). Verify
  at the call site.
- **Shared-union is intentional ([11]).** Do not make the fuel catalog
  economy-specific while retiring the file — repoint it to a *canonical union*
  source, not to per-economy templates.
- **Do not treat a passing run as proof on its own** — read the log for the
  catalog-source and `-1`-row warnings; a green run with an empty catalog would
  otherwise look fine.

## Related

- [work_queue.md](work_queue.md) [7] (ID-routing, complete) and [11] (shared-union
  catalog design).
- [check_registry.md](check_registry.md) hotspot 4 (post-boundary comparison).
