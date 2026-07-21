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
> delete.

## What this file is

`data/full model export.xlsx` is a LEAP **Export** of the `20_USA` area. Its
content is expected to be essentially the same as
`leap_export_templates/leap_export_template 20_USA.xlsx` (both are the USA area),
which is why it worked as a stand-in "canonical" reference while every economy
shared one area. **Confirming that equivalence is Task 0** — the whole plan rests
on repointing these uses at the `20_USA` template (or a purpose-named canonical
copy) instead.

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

## Acceptance criteria (the gate before archiving)

- Task 0 equivalence confirmed and recorded.
- Fuel catalog rebuild is identical to the committed catalog CSV.
- A grep for `full model export.xlsx` across `codebase/` (excluding tests /
  scrapbook / old_workflows / scripts / mapping_tools) returns **no runtime
  read** — only, at most, a documented archived-path reference.
- One end-to-end run (NZ or AUS, whichever is fresh) with the file **moved out of
  `data/`** completes without a `[WARN] … not found`, an empty catalog, or any
  new `BranchID=-1` row that was not already present.

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
