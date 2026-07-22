# Zip extraction plan: `config.zip` / `data.zip`

> **✅ Pulled 2026-07-22.** `git pull --ff-only origin master` brought in 155
> commits (`805d3bf` → `d846955`). This landed exactly the change flagged as
> pending below: `data/full model export.xlsx` is now **formally retired**
> (see `docs/full_model_export_retirement_scope.md`, commit `8d4043d`,
> 2026-07-21) and replaced by **`data/leap_export_templates/`**, resolved
> per-economy via the new `codebase/utilities/leap_export_template_resolver.py`.
> This flips that folder from "re-verify" to "confirmed required" — see the
> updated rows below. The rest of the plan (config/, the two ESTO/9th CSVs,
> `data/.cache/`, `intermediate_data/`) is unaffected. This repo moves fast —
> `docs/prompts/session_handoff_20260722.md` (pulled in this same update)
> describes active same-day engineering work, so re-check before any real
> extraction if time has passed since 2026-07-22.

## Instructions for whoever reviews this on the other PC (post-pull)

In addition to actioning the extraction plan below, do a **clutter audit** of
this PC's own copy of the repo (not just the zip contents) and add findings
as a new section at the bottom of this file, following the same
evidence-based style used throughout (cite `file:line`, don't guess). Two
passes:

1. **Single-use / one-off files and folders.** Look for anything that reads
   as a scratch output from one specific run or investigation rather than a
   reusable input or a regularly-regenerated artifact — dated one-off folder
   names (like `data/backup_tgt_ref_ca_20260625/` or the dated
   `full model export <DDMMYYYY>.xlsx` files this plan already flags as
   obsolete), notebook/script output dumped straight into `data/` or the repo
   root instead of `outputs/`, or files whose name references a specific
   ticket/date/person/investigation. For each candidate, note: what it looks
   like it was for, whether anything in `codebase/` still reads it (grep
   first — don't assume), and whether it's safe to move into an `archive/`
   folder (already gitignored via `**/archive` per `.gitignore`) rather than
   deleting outright, so nothing is lost if the guess is wrong.
2. **Near-duplicate diagnostic/report files.** Look for files that appear to
   be slightly different versions or snapshots of the same underlying report
   — same base name with a date/number/suffix variation, or content that's
   clearly the same shape written by the same code path at different times
   (the kind of thing `leap_dashboard/zip_extraction_plan.md`'s "confirmed
   dead weight" section and duplicate-CSV findings illustrate — e.g. that
   repo found an exact-duplicate `esto_axis_comparison_long.csv` written
   twice from the same in-memory object). For each cluster found, identify
   which copy (if any) is actually read back by later code vs. which are
   pure write-once diagnostics nothing consumes, and recommend keeping only
   the load-bearing one(s).

Don't delete or move anything as part of this audit pass — record findings
here first (candidate list + evidence), get them reviewed, then action
separately once agreed. The goal is the same as the rest of this doc: reduce
repo clutter (tracked and untracked) without breaking any live workflow.

Goal: shrink the repo (tracked + untracked) by extracting from the two root
zips (`config.zip`, `data.zip` — currently identical copies of the same
4,450-entry archive containing `config/`, `data/`, and `intermediate_data/`
trees) **only** what the live workflow scripts in `codebase/` actually read.
Everything else — cache, archive, superseded dated exports, and content with
zero references anywhere in the repo — should be left unextracted.

Zip totals: 4,450 entries. The dominant mass is `data/.cache/` (103GB
uncompressed pandas cache across 5 subfolders) and `data/population/`
(267MB), neither of which any live script requires pre-populated. Recommended
extraction is a small fraction of the archive — see summary below.

## Evidence base

- `docs/workflow_inventory.md` (this repo, last reviewed 2026-07-07) —
  existing cleanup-oriented inventory of active vs. legacy workflow scripts.
- `docs/supply_reconciliation_workflow_guide.md:76-104` — describes the
  baseline-seed producer scripts and confirms `supply_reconciliation_workflow.py`
  uses `supply_workflow.py` and `transformation_workflow.py` output as its
  baseline reference; the other producers (`aggregated_demand_workflow.py`,
  `electricity_heat_interim_workflow.py`, `other_loss_own_use_proxy_workflow.py`,
  `refining_workflow.py`, `transfers_workflow.py`, `hydrogen_transformation_workflow.py`)
  run once at initialisation.
- `AGENTS.md:14-17,47` — this repo owns supply/transformation/transfers/baseline-seed/
  LEAP import-export work; `leap_mappings` is canonical for mapping data and this
  repo "should not duplicate mapping logic".
- `codebase/utilities/output_paths.py:6-36` — all of `outputs/` is a pure write
  target (`mkdir(parents=True, exist_ok=True)`); nothing needs to pre-exist there.
- `codebase/refining_workflow.py:418` — `intermediate_data/refining_fuel_remap_report.csv`
  is a write-only report path (confirmed via `report_path=REMAP_REPORT_PATH` at
  line 453, never read back). `.gitignore:222,226` confirms `intermediate_data/`
  is gitignored except `.gitkeep`. **`intermediate_data/` needs nothing extracted.**
- `codebase/utilities/esto_reference_loader.py:95-144` — `load_augmented_reference_tables()`
  hashes source-file signatures into a cache key, checks whether cached CSVs exist,
  and only rebuilds if missing (`cache_dir.mkdir(parents=True, exist_ok=True)` at
  line 123, cache-hit return at line 144). Same lazy-rebuild pattern confirmed for
  all five `data/.cache/*_reference_tables` directories (see cache table below).
  **`data/.cache/` needs nothing extracted — first run just rebuilds it, slower but
  not broken.**
- Repo-wide grep for `WPP2024`, `population` across every `*.py`/`*.json`/`*.md`/`*.csv`
  in the repo: **zero matches anywhere** — these remain orphaned.
- **Updated 2026-07-22 post-pull:** `leap_export_templates` and `APEC_aggregates`
  are **no longer orphaned** — the pull added `codebase/utilities/leap_export_template_resolver.py`
  and `codebase/utilities/apec_aggregate_sources.py`, both of which read from
  those folders. See the dedicated sections below; this replaces the earlier
  "zero references" finding for both. **Implementation correction, verified on
  the runnable PC:** the ordinary compressed-projection preflight currently
  does *not* pass `economy_filter=["00_APEC"]` when it creates its sources
  (`functions/supply_preflight.py:1401`). The helper selects the aggregate
  source files only when that filter contains `00_APEC` (`:977-995`). Include
  the aggregate ninth file in a handoff anyway, but do not claim the normal
  preflight currently proves that file is being used; route it and add a
  focused test as a separate workflow-code change.
- `codebase/configuration/workflow_config.py:40-64` — `GLOBAL_ECONOMIES` lists
  all 21 APEC economies.
- `codebase/supply_reconciliation_workflow.py:769-775` (line numbers shifted
  after the 2026-07-22 pull added 351 lines to this file) — the actual
  `ECONOMIES_RUN_ORDER` used by the reconciliation loop is annotated inline:
  `"...10_MAS", "02_BD", #the rest dont contain actual leap araeas yet"` — i.e.
  10 of the 21 economies are called out as not yet having real LEAP areas:
  `03_CDA, 04_CHL, 06_HKC, 07_INA, 08_JPN, 09_ROK, 14_PE, 16_RUS, 17_SGP, 18_CT`.
  **Caution:** this comment is informal/hand-maintained and doesn't necessarily
  match the authoritative "real vs. `_COMP_GEN` template" status tracked in
  `docs/full_model_export_retirement_scope.md:213` (`01_AUS`, `12_NZ`, `20_USA`
  confirmed real as of 2026-07-22) — the two lists aren't identical (e.g.
  `01_AUS` appears in both the run order and the "not yet real" comment
  region depending on how the code is currently edited). Treat the retirement
  doc's real-template list as authoritative for template-readiness questions,
  and this run-order comment as authoritative only for "is this economy in
  the reconciliation loop at all".
- Several script-level notebook defaults narrow further to a single economy,
  e.g. `codebase/refining_workflow.py:59` (`ECONOMY = "20_USA"`) and
  `codebase/supply_workflow.py:178` (`NOTEBOOK_WORKFLOW_ECONOMIES = ['20_USA']`)
  — `20_USA` is the economy in active day-to-day use; the other 10 "real area"
  economies matter for a full baseline-seed run across `ECONOMIES_RUN_ORDER`.

## Live workflow scripts (confirmed via `docs/workflow_inventory.md` + import tracing)

Part of the active baseline-seed / reconciliation surface:
`supply_reconciliation_workflow.py`, `supply_workflow.py`, `transformation_workflow.py`,
`hydrogen_transformation_workflow.py`, `transfers_workflow.py`,
`aggregated_demand_workflow.py`, `electricity_heat_interim_workflow.py`,
`other_loss_own_use_proxy_workflow.py`, `refining_workflow.py`,
`baseline_seed_comparison_workflow.py` (standalone QA, opt-in),
`outlook_mapping_maintenance_workflow.py` (standalone maintenance tool),
`transformation_entry.py` (notebook convenience wrapper).

Confirmed **not** live for the purposes of this plan (per `docs/workflow_inventory.md`
and import tracing done here): everything under `codebase/old_workflows/`,
`codebase/archive/`, `codebase/scrapbook/`, `codebase/other/`, `codebase/examples/`,
`codebase/mapping_code/` (a diverged duplicate bundle, per its own
`README_dashboard_mapping_starter.md`), and most of `codebase/mapping_tools/`
(only `excel_sheet_utils.safe_excel_sheet_name` is imported by the one live
maintenance workflow; the rest duplicates the canonical `leap_mappings` pipeline
and isn't invoked from this repo — consistent with `AGENTS.md`'s instruction
not to duplicate mapping logic here).

## config/ — extract nothing

Every file the live scripts reference under `config/` is **already tracked in
git** and shows only as a pre-existing local `D` (deleted from working tree,
not from git) in `git status` — confirmed against `git ls-files config/`.
`config/runtime_tables/*.csv` (already tracked) hold the repo's own operational
tables; the canonical mapping workbook (`outlook_mappings_master.xlsx`) is
sourced from the sibling `leap_mappings` repo (`codebase/utilities/master_config.py:11-12`),
not from this repo's `config/` at all.

| Path in zip | Needed? | Why |
|---|---|---|
| `config/88B2F820`, `config/ED114820` | No | Already tracked in git |
| `config/leap settings workbook.xlsx` | No | Already tracked in git |
| `config/LEAP_API_helpers.py`, `LEAP_API_utilities.py` | No | Already tracked in git; imported via `sys.path` trick in `codebase/configuration/config.py:191-193` |
| `config/leap_export_workbook_mappings.xlsx` | No | Already tracked in git; read by `functions/analysis_input_write_dispatcher.py:326` |
| `config/leap_mappings.xlsx` | No | Already tracked in git; only read by scrapbook/old_workflows/mapping_code (out of scope) |
| `config/leap_results_expected_sheets.json` | No | Already tracked in git |
| `config/leap_transformation_losses_own_use_config.py` | No | Already tracked in git |
| `config/mapping_coverage_gaps.csv` | No | Already tracked in git |
| `config/master_config.xlsx` | No | Already tracked in git |
| `config/missing_zero_branch_mapping_candidates.xlsx` | No | Already tracked in git |
| `config/runtime_tables/*.csv` (6 files) | No | Already tracked in git |
| `config/supply_reconciliation_config.json` | No | Already tracked in git; also explicitly noted "now archived — no longer [read]" at `supply_reconciliation_config.py:403` |
| `config/TypeLib_LEAP_API_full.txt` | No | Already tracked in git |
| `config/.archive/**` (27 daily backup zips) | No | Regenerated automatically; matches `**/.archive` gitignore |
| `config/__pycache__/*.pyc` | No | Regenerated automatically; matches `__pycache__/` gitignore |

**Skip `config/` entirely — nothing to extract.**

## data/ — the real question

Only 3 files under `data/` are tracked in git (`data/README.md`,
`data/leap balances exports/README.md`,
`data/population/WPP2024_GEN_F01_DEMOGRAPHIC_INDICATORS_NOTES.txt`); everything
else is gitignored (`data/*` per `.gitignore:216`) and therefore is not supplied
by a clone. This runnable PC currently has the ignored inputs present locally;
the extraction decision is about what a receiving PC needs in addition to Git.

| Path in zip | Needed? | Why |
|---|---|---|
| `data/00APEC_2024_low_with_subtotals.csv` (26.2MB) | **Yes** | `workflow_config.py:147` `ENERGY_SOURCE_ESTO_BASE_TABLE_PATH`; also directly listed in `other_loss_own_use_proxy_workflow.py:134-135` as one of two validation ESTO paths |
| `data/00APEC_2025_low_with_subtotals.csv` (26.9MB) | **Yes** | Default ESTO path in `workflow_utils.py:25`, `leap_results_dashboard_balance.py:70`, `outlook_mapping_maintenance_workflow.py:94`; also in the same `other_loss_own_use_proxy_workflow.py:134` validation list. Both 2024 and 2025 variants are read, not a fallback chain — confirmed by the two-path validation list. |
| `data/9th_macro_data.csv` (183KB) | No | Only referenced by `codebase/scrapbook/gdp_intensity_comparison_workflow.py` and `codebase/archive/minor_demand_workflow.py` — both out of scope |
| `data/APEC_aggregates/APEC_aggregate_2024_low_with_subtotals.csv`, `APEC_aggregate_2025_low_with_subtotals.csv` | No | Pure cache — `apec_aggregate_sources.py:78-88` `ensure_apec_esto_aggregate()` builds these from `data/00APEC_<year>_low_with_subtotals.csv` (item already required) only when absent, same lazy-rebuild pattern as `data/.cache/` |
| `data/APEC_aggregates/merged_file_energy_00_APEC_20251106.csv` | **Yes — include for intended aggregate work** | `apec_aggregate_sources.py:91-104` `resolve_apec_ninth_aggregate()` has **no auto-build fallback**. However, the ordinary projection preflight currently calls `_create_preflight_compressed_source_files()` without `economy_filter=["00_APEC"]` (`functions/supply_preflight.py:1401`), so it does not currently select this file despite then running `00_APEC`. Include it for the intended/fixed aggregate path, and add a focused routing test when that code defect is corrected. |
| `data/archive/00APEC_2024_low.csv`, `00APEC_2025_low.csv` (old naming, no `_with_subtotals`) | No | Only the `_with_subtotals` variants are read on any live path; the bare `00APEC_2024_low.csv` default in `leap_series_comparison.py:106` belongs to `run_transport_results_table_comparison()`, which is dead code — it unconditionally `raise RuntimeError("...has been removed...")` at line 1511-1514 |
| `data/archive/full model export *.xlsx` (3 files) | See `full model export.xlsx` row below | Superseded/backup copies |
| `data/backup_tgt_ref_ca_20260625/**` (22 files) | **No** | User-confirmed 2026-07-22: no longer useful. Exact match for `REFERENCE_SEED_DIR` hardcoded in `baseline_seed_comparison_workflow.py:763` (only read when `RUN_COMPARISON = True`, default `False`), but the snapshot itself is stale — discard. If the opt-in comparison tool is needed again later, it'll need a fresh reference snapshot, not this one. |
| `data/Data for comparison  - APERC outlooks .xlsx` | No | Only referenced by `codebase/old_workflows/aperc_reference_aggregation_workflow.py` and `codebase/scrapbook/fill_apec_9th_fuels_template.py` — both out of scope |
| `data/detailed balance table output example.xlsx` | No | Only used by `codebase/utilities/detailed_balance_from_esto.py`, itself only imported by the legacy `codebase/old_workflows/detailed_balance_from_esto_workflow.py` |
| `data/full model export 13072026.xlsx`, `14072026.xlsx`, `15072026.xlsx` (dated, root), and `data/archive/full model export*.xlsx` | **No** | **Confirmed post-pull, 2026-07-22:** formally retired in commit `8d4043d` (`docs/full_model_export_retirement_scope.md`). The former `data/full model export.xlsx` was moved to `data/archive/full model export_retired_20260721.xlsx` after confirming a byte-identical SHA-256 match with `leap_export_template 20_USA.xlsx`; every live call site (`aggregated_demand_workflow.py`, `electricity_heat_interim_workflow.py`, `workflow_config.py`, `supply_reconciliation_config.py`, `transfers_workflow.py`, `transformation_workflow.py`, `patch_baseline_seeds.py`, `supply_branch_classification.py`, `fuel_catalog_preflight.py`) now reads `data/leap_export_templates/leap_export_template 20_USA.xlsx` instead. Discard all `full model export *.xlsx` variants — none are read by any live code any more. |
| `data/leap balances exports/<economy>/*.xlsx` | **Yes, per economy in scope** | `codebase/utilities/leap_balance_export_resolver.py:13,104-192` — `DEFAULT_BALANCE_EXPORTS_ROOT` resolves the newest `full model output all years <date> REF/TGT.xlsx` per economy subfolder (non-recursive `export_dir.glob("*.xlsx")`, so nested `archive/` subfolders per economy are already excluded automatically) |
| `data/leap_export_templates/leap_export_template <economy>.xlsx` (21 economies) | **Yes — required** | **Confirmed post-pull, 2026-07-22.** `codebase/utilities/leap_export_template_resolver.py` resolves one template per economy and is the confirmed replacement for the retired `full model export.xlsx` (see row above and `docs/full_model_export_retirement_scope.md`). Real (non-provisional) templates currently exist for only `01_AUS`, `12_NZ`, `20_USA`; the other 18 economies have `_COMP_GEN` (computer-generated, provisional) templates derived from USA — still usable, but baseline seeds built from them get a `_PRELIM` filename marker. Extract the whole folder (all 21 files) — cheap at ~45MB total, and avoids re-litigating per-economy as templates get replaced with real exports over time. |
| `data/leap_export_templates/archive/**` (2 old template versions) | No | Superseded; matches `**/archive` gitignore, not read by the resolver |
| `data/leap results tables/*.xlsx` (root level, 10 files per economy) | **Conditionally yes** | `supply_reconciliation_config.py:183` `LEAP_RESULTS_TABLES_DIR`; read directly and non-recursively (flat `LEAP_RESULTS_TABLES_DIR / filename` lookups in `supply_reconciliation_results.py:402,412` and `functions/supply_demand_mapping.py:1409`). Only needed for a `results_update` reconciliation pass reading LEAP's own exported results — a `baseline_seed` pass sources demand from the 9th projection CSV instead regardless of whether this folder exists (`supply_demand_mapping.py:1414-1418`) |
| `data/leap results tables/a/**` (nested duplicate) | No | Every code path reads `LEAP_RESULTS_TABLES_DIR` flatly (no `/a/` subfolder anywhere in any lookup) — this is dead duplication in the zip, not a real input path |
| `data/leap results tables/README.md`-adjacent processed tables at root, duplicated again | No (dedupe) | Confirm and keep only one copy of each `transformation_derived_metrics_20_USA.csv` / `transformation_auxiliary_own_use_20_USA.csv` — these are regenerable derived outputs, not source inputs (see cache/derived-output note) |
| `data/merged_file_energy_ALL_20251106.csv` (287.8MB) | **Yes** | `workflow_config.py:149` `ENERGY_SOURCE_NINTH_PROJECTION_TABLE_PATH`; also the default in `workflow_utils.py:24`, `leap_results_dashboard_balance.py:71`, `outlook_mapping_maintenance_workflow.py:95`, `functions/buildings_fuel_remap.py:70`, `functions/industry_fuel_remap.py:66`. Biggest single required file. |
| `data/population/**` (WPP2024 CSV/xlsx/notes, 267MB) | No (except the already-tracked `_NOTES.txt`) | Zero references anywhere in the repo. Demand/population initialisation is explicitly out of this repo's scope per `docs/supply_reconciliation_workflow_guide.md:65` ("Demand and Power are initialised by separate workflows/processes") |
| `data/README.md` | Yes (already tracked) | — |
| `data/transformation and supply settings - USA.xlsx` | No | Zero references found anywhere in the repo |

### The `data/full model export.xlsx` retirement — fully resolved 2026-07-22

User-confirmed on 2026-07-22 that none of the dated `full model export
*.xlsx` files are current; the same-day `git pull` (155 commits,
`805d3bf`→`d846955`) confirmed why: the file was **formally retired** in
commit `8d4043d`, per `docs/full_model_export_retirement_scope.md`.

What changed, per that doc's implementation record:
- **Task 0**: confirmed `data/full model export.xlsx` and
  `data/leap_export_templates/leap_export_template 20_USA.xlsx` were
  byte-identical (SHA-256 match, 9,182 Export rows) before retiring one in
  favour of the other.
- **Tasks 1-6** (commit `8d4043d`): the file was moved to
  `data/archive/full model export_retired_20260721.xlsx`; every call site that
  used to hardcode `data/full model export.xlsx` — including
  `fuel_catalog_preflight.py`'s `DEFAULT_FULL_MODEL_EXPORT_PATH`,
  `supply_reconciliation_config.py`'s `RESULTS_VERIFICATION_EXPORT_PATH`, and
  the fallback defaults in `aggregated_demand_workflow.py`,
  `electricity_heat_interim_workflow.py`, `baseline_seed_comparison_workflow.py`,
  `transformation_workflow.py`, `transfers_workflow.py` — was repointed at the
  canonical `data/leap_export_templates/leap_export_template 20_USA.xlsx`.
  Confirmed directly: `fuel_catalog_preflight.py:36` now reads
  `DEFAULT_FULL_MODEL_EXPORT_PATH = REPO_ROOT / "data" / "leap_export_templates" / "leap_export_template 20_USA.xlsx"`.
- **Per-economy resolution**: `codebase/utilities/leap_export_template_resolver.py`
  (new) resolves each economy's own template for supply-root classification and
  ID lookups, rather than every economy borrowing USA's IDs. Real (non-`_COMP_GEN`)
  templates currently exist for `01_AUS`, `12_NZ`, `20_USA` only; the rest are
  provisional `_COMP_GEN` templates derived from USA, which is why baseline
  seeds built from them carry a `_PRELIM` filename marker
  (`patch_baseline_seeds.SEED_FILENAME_PATTERN`).
- **Verified on real data**: a full `01_AUS` run at commit `b45ccc6` produced a
  baseline seed with AUS's own IDs on 504/504 discriminating rows (zero
  borrowed from USA), confirming the repoint works end-to-end for a
  real-template economy.

**Net effect on this plan:** discard all `full model export *.xlsx` variants
(confirmed dead); extract all of `data/leap_export_templates/` instead (see
row above) — this is now the load-bearing input, not an orphaned folder.

## `data/.cache/` — confirmed regenerable, skip entirely

| Cache dir (zip) | Constant in code | Confirmed lazy-rebuild? |
|---|---|---|
| `data/.cache/buildings_reference_tables` | `functions/buildings_fuel_remap.py:72` | Yes — same `load_augmented_reference_tables()` pattern as `esto_reference_loader.py:95-144` |
| `data/.cache/industry_reference_tables` | `functions/industry_fuel_remap.py:68` | Yes |
| `data/.cache/leap_series_comparison_reference_tables` | `functions/leap_series_comparison.py:319,337` | Yes |
| `data/.cache/transformation_reference_tables` | `functions/transformation_analysis_utils.py:121,1779` | Yes |
| `data/.cache/supply_reference_tables` | `functions/supply_assets.py:57,100`, `functions/supply_data_pipeline.py:148` | Yes |

All five call the same cache-key/mkdir/rebuild-on-miss pattern confirmed in
`esto_reference_loader.py`. First run after a fresh clone will just be slower
(rebuilding ~100GB of reference tables from the two source CSVs above) rather
than broken. **Do not extract any of `data/.cache/`.**

## `intermediate_data/` — pure write target

Only one reference found (`codebase/refining_workflow.py:418`), and it's a
report output path, never read back. `.gitignore:222,226` already ignores it
except `.gitkeep`. **Nothing needs to pre-exist here.**

## Summary — what to actually extract

1. **`data/00APEC_2024_low_with_subtotals.csv`** (26.2MB) and
   **`data/00APEC_2025_low_with_subtotals.csv`** (26.9MB) — both required directly.
2. **`data/merged_file_energy_ALL_20251106.csv`** (287.8MB) — required directly;
   the single biggest necessary file.
3. **`data/full model export.xlsx`** and all dated variants — **discard**.
   Confirmed formally retired in commit `8d4043d` (2026-07-22 pull); replaced
   by `data/leap_export_templates/` (item 10 below), which is now required.
4. **`data/leap balances exports/<economy>/`** — extract only the newest
   `full model output all years <date> REF/TGT.xlsx` per economy currently
   available. User-confirmed 2026-07-22: economies are populated over time,
   so there's no fixed target list to hit right now — extract whatever
   exists opportunistically as it comes in, rather than requiring all 11
   `ECONOMIES_RUN_ORDER` economies up front. Drop every economy's own
   `archive/` subfolder (older dated copies) — the resolver already ignores
   them via non-recursive glob, so they're just dead weight in the zip.
5. **`data/leap results tables/*.xlsx`** (root level only, not the nested
   `a/` duplicate) — only needed if you plan to run a `results_update`
   reconciliation pass against already-exported LEAP results; a fresh
   `baseline_seed` pass does not need this folder at all. Same
   populated-over-time scope as #4 applies.
6. **`data/backup_tgt_ref_ca_20260625/`** — **discard**. User-confirmed
   2026-07-22: no longer useful. Was the reference/golden snapshot for
   `baseline_seed_comparison_workflow.py`'s opt-in comparison tool, but the
   snapshot itself is stale now — don't extract it.
7. **`config/`** — nothing. Already fully covered by tracked git files.
8. **`data/.cache/`** — nothing. Regenerates automatically, ~100GB saved.
9. **`intermediate_data/`** — nothing. Pure write target.
10. **`data/leap_export_templates/leap_export_template <economy>.xlsx`**
    (21 economies, ~45MB total, skip its own `archive/` subfolder) —
    **confirmed required** as of the 2026-07-22 pull. This is the retired
    `full model export.xlsx`'s replacement — see item 3 and the dedicated
    section above.
11. **`data/APEC_aggregates/merged_file_energy_00_APEC_20251106.csv`**
    (12.8MB) — **include for intended aggregate/preflight work**. There is no
    auto-build fallback for this one file. The normal compressed-projection
    preflight does not yet select it because it fails to pass the `00_APEC`
    economy filter to its source builder; fix and test that routing separately.
    The other two files in that folder (`APEC_aggregate_2024/2025_low_with_subtotals.csv`)
    remain pure cache — skip them, they rebuild automatically from item 1's
    files.
12. Everything else (`data/population/` 267MB, `data/9th_macro_data.csv`,
    `data/transformation and supply settings - USA.xlsx`,
    `data/Data for comparison  - APERC outlooks .xlsx`,
    `data/detailed balance table output example.xlsx`, all of `data/archive/`,
    `data/leap_export_templates/archive/`, the nested `data/leap results
    tables/a/` duplicate) — discard. Zero live references, or
    superseded/archived/duplicated/regenerable.

## Packaging a `data.zip` to send to a new PC

Since `.gitignore` deliberately keeps `config/*` (mostly) and all of `data/`
out of git — large model workbooks/CSVs shouldn't go through GitHub — a new
PC needs two things to start running: a `git clone`/`pull` (covers all of
`config/`, since that's fully tracked — see "`config/` — extract nothing"
above) plus **a hand-carried `data.zip`**. No `config.zip` is needed at all.

**Recommended method: exclude the known-bad categories, keep everything
else.** Rather than hand-picking individual files (which breaks every time a
new economy folder shows up), start from the whole `data/` folder and drop
four categories — cache, archive, superseded, and orphaned — each backed by
the evidence already in this doc:

| Category | What it matches | Why drop |
|---|---|---|
| **cache** | `data/.cache/` | ~100GB uncompressed, regenerates automatically on first run (see "`data/.cache/`" section above) |
| **archive** | any folder literally named `archive` anywhere in the tree — `data/archive/`, each economy's `leap balances exports/<economy>/archive/`, `leap_export_templates/archive/` | superseded dated copies; live code only ever reads the non-archive path (non-recursive glob) |
| **superseded** | root-level `data/full model export *.xlsx` (dated) | user-confirmed 2026-07-22: obsolete, replaced by economy-specific templates |
| **orphaned** (zero references anywhere in the repo) | `data/population/` (267MB), `data/9th_macro_data.csv`, `data/transformation and supply settings - USA.xlsx`, `data/Data for comparison  - APERC outlooks .xlsx`, `data/detailed balance table output example.xlsx`, and the nested duplicate `data/leap results tables/a/` | confirmed unread by any live or legacy script |
| **stale reference snapshot** | `data/backup_tgt_ref_ca_20260625/` (22 files) | User-confirmed 2026-07-22: no longer useful, even though it's still technically read by the opt-in comparison tool — the snapshot itself is outdated |

Everything else — `data/00APEC_2024/2025_low_with_subtotals.csv`,
`data/merged_file_energy_ALL_20251106.csv`, the current (non-archive)
contents of `data/leap balances exports/`, root-level `data/leap results
tables/*.xlsx`, and
**`data/leap_export_templates/`** (confirmed required post-pull, see above) —
just rides along as-is. `data/APEC_aggregates/` is a partial case: its two
`APEC_aggregate_*.csv` files are pure cache (safe to drop, they auto-rebuild),
but `merged_file_energy_00_APEC_20251106.csv` in that same folder has no
auto-build fallback — user-confirmed 2026-07-22 that an `00_APEC` aggregate
preflight may get run on the receiving PC, so include the whole folder.
It's cheap to carry the
small ambiguous items rather than adjudicate each one, and this list lands at
roughly the same size as a hand-picked whitelist would (~350-450MB) since the
mass is concentrated in the categories above, not spread across many small
files.

**`robocopy` command (Windows, run from the repo root):**

```powershell
robocopy "data" "..\leap_init_handoff\data" /E `
  /XD ".cache" "archive" "backup_tgt_ref_ca_20260625" `
  /XF "full model export*.xlsx"
```

This mirrors `data/` into a staging folder next to the repo, skipping any
directory named `.cache` or `archive` at any depth (this also correctly keeps
`data/leap_export_templates/` itself, only dropping its `archive/`
subfolder), the now-confirmed-stale `backup_tgt_ref_ca_20260625/`, and any
file matching `full model export*.xlsx`. It does **not** drop the small
orphaned files listed above (population, etc.), the two `APEC_aggregate_*.csv`
cache files, or the nested `leap results tables/a/` duplicate — those are
cheap to carry, but if disk space on the receiving end is tight, add them
explicitly (note `APEC_aggregates` itself is **not** excluded as a whole
directory, since `merged_file_energy_00_APEC_20251106.csv` inside it has no
auto-build fallback — only its two cache files are dropped by name):

```powershell
robocopy "data" "..\leap_init_handoff\data" /E `
  /XD ".cache" "archive" "population" "backup_tgt_ref_ca_20260625" `
  /XF "full model export*.xlsx" "9th_macro_data.csv" `
       "transformation and supply settings - USA.xlsx" `
       "Data for comparison*.xlsx" "detailed balance table output example.xlsx" `
       "APEC_aggregate_2024_low_with_subtotals.csv" `
       "APEC_aggregate_2025_low_with_subtotals.csv"
Remove-Item -Recurse -Force "..\leap_init_handoff\data\leap results tables\a"
```

**Then zip and hand off:**

```powershell
Compress-Archive -Path "..\leap_init_handoff\data" -DestinationPath "..\leap_init_handoff\data.zip"
```

Create `..\leap_init_handoff\data` empty for each package build. The `robocopy`
commands above copy/update files but do not remove stale files already in the
destination. Do not substitute `/MIR` casually: it would make a typo in the
staging destination destructive.

**On the new PC:** `git clone` (or `pull`), then extract `data.zip` so its
`data/` folder lands at the repo root. Re-run the `robocopy` step fresh each
time you package a handoff — don't reuse an old `data.zip`, since the
`leap balances exports/` contents grow as more economies get populated.

**Size estimate:** roughly 350-450MB today, growing slowly as more economies'
REF/TGT workbook pairs (~0.4-2MB each) get added — several orders of
magnitude smaller than the ~7.3GB `config.zip`/`data.zip` pair currently
sitting in the repo root, since those still carry the full 100GB-uncompressed
cache and every superseded/archived/orphaned variant.

## Fresh-PC acceptance checklist

Run this before starting a long workflow on a receiving PC. It is deliberately
read-only: it proves that the hand-carried inputs resolve without building a
cache, writing outputs, or importing anything into LEAP.

1. Clone/pull the repository first, then extract `data.zip` at the repository
   root. Confirm the expected source files exist:

   ```powershell
   $required = @(
     "data/00APEC_2024_low_with_subtotals.csv",
     "data/00APEC_2025_low_with_subtotals.csv",
     "data/merged_file_energy_ALL_20251106.csv",
     "data/APEC_aggregates/merged_file_energy_00_APEC_20251106.csv"
   )
   $missing = $required | Where-Object { -not (Test-Path $_) }
   if ($missing) { throw "Missing handoff inputs: $($missing -join ', ')" }
   ```

2. Use the pinned interpreter to resolve every economy template and the
   aggregate ninth source. This reads filenames only; it does not launch the
   reconciliation workflow:

   ```powershell
   @'
   from codebase.configuration.workflow_config import GLOBAL_ECONOMIES
   from codebase.utilities.apec_aggregate_sources import resolve_apec_ninth_aggregate
   from codebase.utilities.leap_export_template_resolver import resolve_leap_export_template

   resolved = [resolve_leap_export_template(economy) for economy in GLOBAL_ECONOMIES]
   aggregate = resolve_apec_ninth_aggregate("data/merged_file_energy_ALL_20251106.csv")
   print(f"Resolved {len(resolved)} economy templates")
   print(f"Resolved aggregate ninth source: {aggregate}")
   '@ | & "C:\Users\Work\miniconda3\python.exe" -
   ```

3. Run the fast resolver/unit-test subset after dependencies are installed:

   ```powershell
   & "C:\Users\Work\miniconda3\python.exe" -m pytest `
     tests/test_leap_export_template_resolver.py `
     tests/test_leap_balance_export_resolver.py `
     tests/test_workflow_utils.py
   ```

4. Only when a `results_update` run is intended, check that its flat
   `data/leap results tables/` files and the relevant economy's REF/TGT balance
   exports are present. A baseline-seed run does not require those optional
   results-update inputs.

5. The first real baseline-seed run may spend substantial time rebuilding the
   omitted caches. Start with the standard two-year iteration horizon. Do not
   treat it as proof of aggregate-source routing: until the separate
   `economy_filter=["00_APEC"]` fix lands, the normal compressed projection
   preflight does not select the packaged APEC aggregate ninth CSV. After that
   fix, use one two-year run with compressed projection preflight enabled as
   the end-to-end aggregate acceptance check.

## Open questions for the user

1. ~~Which dated `full model export *.xlsx` is current?~~ **Resolved
   2026-07-22:** none — all obsolete, discard. Further confirmed by the
   2026-07-22 pull: formally retired in commit `8d4043d`.
2. ~~Which economies' `leap balances exports/` and `leap results tables/`
   need populating right now?~~ **Resolved 2026-07-22:** populated over
   time, no fixed list — extract whatever currently exists.
3. ~~Is `data/backup_tgt_ref_ca_20260625/` still the intended comparison
   reference?~~ **Resolved 2026-07-22:** no — user-confirmed no longer
   useful. Discard.
4. ~~Re-grep for `leap_export_template` once pulled~~ **Resolved 2026-07-22:**
   done — confirmed required, see `data/leap_export_templates/` rows above.
5. ~~Do you plan to ever run an `"00_APEC"` aggregate/preflight pass on the
   receiving PC?~~ **Resolved 2026-07-22:** yes, this may get run. Include
   `data/APEC_aggregates/merged_file_energy_00_APEC_20251106.csv` (no
   auto-build fallback exists for it) — matches the packaging section's
   existing default of carrying the whole folder.
6. **New, given how fast this repo moves** (155 commits landed between the
   plan's first draft and this pull, all in roughly one day): re-run
   `git fetch origin && git log --oneline HEAD..origin/master` immediately
   before actually building a handoff zip, and re-grep the specific
   file:line citations above if meaningful time has passed — don't rely on
   this document's citations remaining accurate indefinitely.

## Post-pull clutter audit — output-writing code (2026-07-22)

Static code audit of every live workflow script's output-writing paths,
performed per the "Instructions for whoever reviews this on the other PC"
section above. `outputs/` and `results/` are empty on this machine (no runs
have happened here yet), so this is entirely a *code-tracing* exercise —
nothing here was confirmed against files actually on disk. Scope: the live
surface listed in `docs/workflow_inventory.md` and reiterated in the task
brief (`supply_reconciliation_workflow.py`, `supply_workflow.py`,
`transformation_workflow.py`, `hydrogen_transformation_workflow.py`,
`transfers_workflow.py`, `aggregated_demand_workflow.py`,
`electricity_heat_interim_workflow.py`,
`other_loss_own_use_proxy_workflow.py`, `refining_workflow.py`,
`baseline_seed_comparison_workflow.py`, `outlook_mapping_maintenance_workflow.py`,
`transformation_entry.py`, plus `codebase/functions/` and
`codebase/utilities/` writer modules). `old_workflows/`, `archive/`,
`scrapbook/`, `other/`, `examples/`, `mapping_code/` excluded as already
established out of scope.

### Pass 1 — single-use / one-off files and folders

| # | Finding | Evidence | Verdict |
|---|---|---|---|
| 1 | `outputs/leap_exports/supply_reconciliation/<pass_mode>/runs/<RUN_OUTPUT_LABEL>/` trees accumulate forever; nothing in live code deletes an old run tree. | `codebase/supply_reconciliation_config.py:396-410` (`refresh_output_paths_for_pass_mode` builds `OUTPUT_DIR = INTEGRATED_LEAP_EXPORTS_ROOT / <subdir> / "runs" / safe_label` whenever a label is set); `codebase/supply_reconciliation_workflow.py:690-711` (`_automatic_run_output_label`/`_resolve_run_output_label` — `"auto"` still generates a new label per distinct economy/scenario scope, so repeated experimentation naturally mints new folders). No `shutil.rmtree`/eviction call exists anywhere in live code for this tree (repo-wide grep for `rmtree`/`cleanup`/`purge`/`evict` in `codebase/` only matches `codebase/old_workflows/leap_favorites_transplant_workflow.py:95,130`, out of scope). Real, already-observed instance: `docs/prompts/session_handoff_20260722.md:45-46` — `outputs/.../runs/SEED_21ECON_POSTFIX_20260722/` holds 5 orphan preflight files from a 90-second aborted launch, explicitly called "safe to delete" by the session that created it, but nothing in the codebase does so automatically. | **Genuine clutter risk.** Every aborted/experimental/re-labelled run leaves a permanent directory tree (workbooks, balance tables, diagnostics, timing history, caches) with no automatic cleanup. Not flagged elsewhere in `work_queue.md` (grepped for `runs/<LABEL>`, `RUN_OUTPUT_LABEL` cleanup — no hits). |
| 2 | `promote_baseline_seed_to_primary_dir` only rescues the final seed workbook from a labelled run tree — it does not touch the rest of that run's outputs (balance tables, diagnostics, timing history under `runs/<LABEL>/`), so finding #1's accumulation isn't mitigated by promotion. | `codebase/functions/supply_leap_io.py:1450-1490` — docstring and body only move/copy the single `seed_path` up to the primary `baseline_seed/` dir; `docs/full_model_export_retirement_scope.md:41-56` confirms this is deliberately scoped to the seed file only ("the run-scoped copy is always kept as the record of the run"). | **Working as designed, but worth noting** — it's a targeted fix for one specific invisibility problem (seeds), not a general run-tree cleanup mechanism, so it shouldn't be mistaken for one. |
| 3 | `RESULTS_SINGLE_FILE_ARCHIVE_DIR` (the single-file combined workbook's archive folder) receives a new timestamped copy on effectively every run, with no cap or eviction. | `codebase/supply_reconciliation_config.py:274-276,422` (`RESULTS_SINGLE_FILE_ARCHIVE_DIR = OUTPUT_DIR / "supporting_files" / "archive"`, `RESULTS_SINGLE_FILE_ARCHIVE_EVERY_RUN = True` default, `RESULTS_SINGLE_FILE_ARCHIVE_MIN_HOURS = 24`); `codebase/functions/supply_results_saver.py:1147-1166` (`_archive_existing_results_file_if_needed` — copies the pre-existing workbook before overwrite, throttled to once per `min_hours`) and `:1170-1185` (`_archive_results_file_snapshot` — copies the newly-written workbook, gated only by `archive_every_run`, i.e. every run by default); both called from `:2423-2426` and `:2498-2501`. Neither function nor any caller ever prunes old entries in that directory. | **Genuine clutter risk** — with the default `archive_every_run=True`, every run of the combined single-file export leaves a full workbook copy behind forever; over months of daily runs this is an unbounded disk sink. Distinct from #4 below, which *does* have a cap. Not found in `work_queue.md` under any archive/cleanup heading. |
| 4 | Per-economy baseline-seed `archive/` subfolders (created both by promotion-time replacement and by the writer moving any pre-existing same-named seed aside) also grow without eviction. | `codebase/supply_reconciliation_workflow.py:2150-2153` (`write_per_economy_combined_workbooks` — `for existing in out_dir.glob(...): shutil.move(str(existing), str(archive_dir / existing.name))` before writing a new seed, no pruning); `codebase/functions/supply_leap_io.py:1450-1490` (promotion moves a same-named primary file to `archive/` with a timestamp before replacing it — quoting `docs/full_model_export_retirement_scope.md:51-52`, "an existing primary file of the same name is moved to `archive/` with a timestamp before being replaced, so promotion never destroys a seed"). | **Working as designed but worth noting** — this is deliberate, documented "never destroy a seed" behaviour (per the retirement-scope doc itself), not an oversight. Still a slow, permanent accumulation source with no eviction policy defined anywhere. Same shape as #3; together they're two independent unbounded archive sinks plus the `runs/` tree in #1. |
| 5 | `config/.archive/` daily backup zips (one `config_<YYYYMMDD>.zip` per calendar day, deduplicated within a day) also have no eviction. | `codebase/utilities/workflow_common.py:453-488` (`archive_config_dir_once_per_day` — `existing = sorted(daily_dir.glob("config_*.zip")); if existing: return existing[0]` skips re-archiving the same day, but nothing ever deletes an old day's zip); called from `codebase/functions/supply_results_saver.py:2872`. This is the same folder the top-of-document `config/` table already lists as "27 daily backup zips ... Regenerated automatically" (line ~168 in the extraction-plan table above) — that entry correctly notes it's regenerable/gitignored, but didn't note it also has no upper bound on retained days. | **Working as designed but worth noting** — already partially covered above as a "regenerates automatically" cache-like item; this audit adds that it also has no cap, same pattern as #3/#4. |
| 6 | `codebase/utilities/economy_run_lock.py` cross-process locks — checked for guaranteed release / stale-lock risk. | `economy_run_lock.py:83-115` — `economy_run_locks` is a `@contextmanager` with `try/...finally: for lock_path in reversed(acquired): lock_path.unlink(missing_ok=True)`, so a normal exit (including an exception propagating out of the `with` block) always releases locks. A crash that kills the *process* (not just the Python exception path) on the **same host** is also handled: `_process_is_running` (`:22-45`, Windows-specific `OpenProcess` check at `:28-38`) detects the dead PID and a subsequent run auto-clears the stale lock (`:89-95`) before re-acquiring. A lock left by a **different host** is deliberately never auto-cleared (docstring `:62-67`: "Locks from another machine are deliberately retained so shared-drive writes remain safe"), which is a real permanent-block risk only if that other host's process died without ever running this code again to release it (e.g. shared-drive network partition, host decommissioned mid-run). | **Working as designed** for the same-host crash case (this is a genuine crash-safety win, not a gap); the cross-host case is a deliberate safety tradeoff documented in the code, not an oversight — flagging only as an edge case worth knowing about, not a defect. |
| 7 | `AGENTS.md`'s "Workflow Timing History" section undersells the code — it describes only a manual reset procedure (delete files from `history/`) and doesn't mention that the code already caps the folder automatically. | `AGENTS.md:134-157` documents `WorkflowTimer.write_csv()` writing a timestamped copy into `history/` and says resetting "requires" manually deleting files there — no mention of any automatic limit. Actual code: `codebase/utilities/workflow_common.py:31` (`_TIMING_HISTORY_KEEP = 20`) and `:264-269` (`old_files = sorted(history_dir.glob(...)); for old_file in old_files[:-_TIMING_HISTORY_KEEP]: ... old_file.unlink()`) — the 20 most recent history files per timing-CSV-stem are kept automatically and older ones are deleted on every `write_csv()` call. | **Doc-vs-code mismatch, not a code defect** — per the task brief's explicit instruction, this is *not* flagged as a clutter defect (the mechanism is deliberate and by design, and the code turns out to be *better* than the doc implies: it already self-caps at 20 files, unlike the unbounded archives in #3-#5). Worth a small doc fix to `AGENTS.md` noting the automatic 20-file cap exists, so nobody assumes manual deletion is the only lever or worries this folder grows forever — it doesn't, in contrast to the truly-unbounded sinks above. |

### Pass 2 — near-duplicate diagnostic/report files

| # | Finding | Evidence | Verdict |
|---|---|---|---|
| 8 | The shared LEAP fuel-branch catalog is written to two different filenames on every build: the canonical path and a "legacy" compatibility path. | `codebase/functions/supply_results_saver.py:1085-1111` (`_build_transformation_supply_fuel_catalog` — `catalog_df.to_csv(catalog_path, index=False)` then, if the paths differ, `catalog_df.to_csv(legacy_catalog_path, index=False)`, same in-memory `catalog_df` written twice, matching the sibling `leap_dashboard` repo's exact-duplicate-CSV failure mode). | **Not the same defect as the sibling repo's dead duplicate** — confirmed the legacy copy *is* read back: `codebase/utilities/fuel_catalog_preflight.py:1070-1082` (`load_fuel_catalog`) falls back to `LEGACY_FUEL_CATALOG_PATH` if the canonical path is missing. The function's own docstring (`supply_results_saver.py:1093-1094`) states this is intentional: "The legacy filename is written beside the canonical file until all external readers have migrated." **Working as designed, but flag for follow-up** — no migration completion date/check exists in code, so this could quietly persist indefinitely; worth a one-line work-queue item to eventually confirm all legacy readers have migrated and drop the second write. |
| 9 | No other near-duplicate write-the-same-object-twice pattern found in the results-writing surface. | Grepped every `.to_csv(`/`.to_excel(` call in `codebase/functions/supply_results_saver.py` (17 call sites) and checked each write target: probe/report/reconciliation/diagnostics paths are each written once to a single path; the combined-workbook writer (`:2444-2512`) writes distinct sheets (`Export`, header, manifest) of one workbook, not duplicate files. No second instance of the `esto_axis_comparison_long.csv`-style exact-duplicate pattern found in the live writers. | **Not a problem** — the audit target from the sibling repo's findings doesn't recur elsewhere in this repo's writer surface as far as static tracing can show. |

### Already tracked elsewhere (not re-reported as new)

- `supply_reconciliation_config.py:312` `AGGREGATED_DEMAND_ID_LOOKUP_PATH` is flagged dead ("DEAD — zero references anywhere including tests... Delete it") in `docs/work_queue.md:412`. Not an output-writing path (it's an ID-lookup input constant), so out of this audit's direct scope, but noted here so it isn't mistaken for a fresh finding.
- The `data/backup_tgt_ref_ca_20260625/` dated one-off folder and the retired `full model export *.xlsx` variants are already covered in the "Open questions" and `data/` sections above in this same document — not re-derived here.
- `docs/full_model_export_retirement_scope.md`'s seed-promotion archive behaviour (finding #4 above) is itself documented in that file as deliberate; it is not tracked in `work_queue.md` as an open cleanup item, so it is reported here as "worth noting" rather than "already tracked."

### Biggest wins, ranked

1. **`runs/<LABEL>/` accumulation (#1)** — largest and most concrete: real orphaned output (5 files from one aborted launch) already exists per the session-handoff doc, and every future experimental/aborted/re-labelled run adds another full tree with no automatic cleanup. Cheapest fix: a simple retention policy or a documented manual-cleanup habit (mirroring the timing-history's already-working 20-file cap in #7) would close this immediately.
2. **Unbounded archive sinks (#3, #4, #5)** — three independent "copy-before-overwrite, never prune" mechanisms (single-file results archive, per-economy baseline-seed archive, daily config zip). None is wrong on its own, but together they're the largest slow-growing disk cost in the output-writing surface, and none has the cap that the timing-history mechanism (#7) already demonstrates is easy to add.
3. **Legacy fuel-catalog dual-write (#8)** — smallest and lowest risk (one small CSV, genuinely read-back, explicitly temporary by its own docstring) but worth a work-queue entry to track when the migration is actually complete so the second write can be dropped.
4. Everything else in this section (#2, #6, #7's doc gap, #9) is either working as designed or a documentation nit, not an action item.
