# Canonical mapping migration — working notes

Task: migrate all supply-reconciliation mapping usage in `leap_initialisation`
onto the canonical workbook
`leap_mappings/config/outlook_mappings_master.xlsx` (sheets
`leap_combined_esto`, `leap_combined_ninth`, `ninth_pairs_to_esto_pairs`,
`leap_display_names`), removing runtime dependence on legacy tables in
`config/master_config.xlsx`, `config/leap_mappings.xlsx`, missing standalone
files, and compatibility redirects.

This file records what changed, decisions taken, and open questions for review.

## Audit summary (before edits)

Canonical workbook sheets confirmed present:
`leap_combined_esto` (1863 rows), `leap_combined_ninth` (2027),
`ninth_pairs_to_esto_pairs` (2412), `leap_display_names` (475).
None of the three base pair sheets currently carry `remove_row` /
`duplicate_to_remove` columns, so active-row filtering must be applied only
where those columns exist (matches existing `supply_demand_mapping.py` logic).

Legacy mapping touch-points found in active supply-reconciliation paths:

| # | Location | Legacy source | Target |
|---|----------|---------------|--------|
| 1 | `supply_reconciliation_config.py` `BALANCE_DEMAND_NINTH_TO_ESTO_MAPPING` -> `leap_results_dashboard_balance.DEFAULT_MAPPING_PAIRS_PATH` = `(config/master_config.xlsx, ninth_pairs_to_esto_pairs)` | master_config.xlsx | canonical `ninth_pairs_to_esto_pairs` |
| 2 | `other_loss_own_use_proxy_workflow.load_fuel_mapping_lookup` reads `config/leap_mappings.xlsx` sheets `fuel_product_final_proposed` / `fuel_ninth_final_proposed` | leap_mappings.xlsx | canonical `leap_combined_esto` + `leap_combined_ninth` |
| 3 | `refining_workflow.py` `MAPPING_CSV_PATH="../config/refining_fuel_mapping.csv"`, `NINTH_TO_ESTO_PAIRS_PATH="../config/ninth_pairs_to_esto_pairs.xlsx"`, `REMAP_REPORT_PATH="../intermediate_data/..."` | CWD-relative / missing csv | REPO_ROOT + canonical sheets |
| 4 | `electricity_heat_interim_workflow.py` reads `independent_product_mapping` + `sector_fuel_code_to_name` (via read_config_table -> master_config.xlsx) | master_config.xlsx | canonical pairs + `leap_display_names` |
| 5 | Display names: `transformation_analysis_utils.load_code_to_name_mapping` has canonical `leap_display_names` branch but falls back to legacy `code_to_name`; other workflows vary | mixed | canonical `leap_display_names` |
| 6 | `read_config_table` in `utilities/master_config.py` silently redirects legacy filenames to `master_config.xlsx` sheets | redirect table | keep for now; audited per-caller |

Note: `supply_demand_mapping.py` (direct balance demand) ALREADY reads canonical
`leap_combined_esto` / `leap_combined_ninth` via `OUTLOOK_MAPPINGS_MASTER_PATH`;
only its ninth->esto pairs pointer (#1) is legacy.

## Changes made

### C1 — shared canonical loaders (commit `codex: add shared canonical mapping loaders + tests`)
- New `codebase/mappings/canonical_loaders.py`: validated loaders for the four
  canonical sheets, active-row filtering, conflict detection, context-aware
  fuel resolution; raises `CanonicalMappingError`.
- New `tests/test_canonical_loaders.py` (16 tests, all pass incl. real workbook).

### C2 — balance-demand / balance-conversion ninth->esto pairs repointed to canonical
- `leap_results_dashboard_balance.DEFAULT_MAPPING_PAIRS_PATH` changed from
  `(config/master_config.xlsx, ninth_pairs_to_esto_pairs)` to
  `(leap_mappings/.../outlook_mappings_master.xlsx, ninth_pairs_to_esto_pairs)`.
  This is the single source feeding both `convert_leap_balances_to_esto_long_table`
  and the balance-demand `BALANCE_DEMAND_NINTH_TO_ESTO_MAPPING` pointer.
- Verified it loads via `load_canonical_pairs`: 2251 clean pairs, 224 one-to-many
  (conflicting-target) keys surfaced. Regression tests
  `test_balance_demand_mapping_fixes.py` + `test_balance_demand_conservation.py`
  (16) still pass.

### C3 — other loss/own use fuel mapping fixed (was silently empty)
- `other_loss_own_use_proxy_workflow.load_fuel_mapping_lookup` pointed at the
  canonical workbook (`LEAP_MAPPINGS_PATH = OUTLOOK_MAPPINGS_MASTER_PATH`) but
  requested sheets `fuel_product_final_proposed` / `fuel_ninth_final_proposed`
  that exist only in legacy `leap_mappings.xlsx`. The reads were caught and
  swallowed, so the lookup returned **empty dicts** and every output fuel label
  fell back to mechanical cleanup of the ESTO/9th code.
- Rebuilt from canonical `leap_combined_esto` (esto_product -> LEAP fuel) and
  `leap_combined_ninth` (ninth_fuel -> LEAP fuel). Only unambiguous fuel-only
  mappings are kept (71 ESTO, 52 9th). Ambiguous codes (0 ESTO, 5 9th) are
  recorded in `LAST_FUEL_MAPPING_AMBIGUITY` and left to mechanical cleanup —
  never resolved by arbitrary first-row selection.
- `test_other_loss_own_use_proxy_workflow.py` (36) still passes.

### C4 — refining remap: REPO_ROOT paths + canonical-derived mapping
- `refining_workflow.py`: `MAPPING_CSV_PATH`, `NINTH_TO_ESTO_PAIRS_PATH`,
  `REMAP_REPORT_PATH` were CWD-relative (`../config/...`, `../intermediate_data/...`)
  and `refining_fuel_mapping.csv` was missing. Now all resolve from `REPO_ROOT`;
  `NINTH_TO_ESTO_PAIRS_PATH` points at the canonical
  `(outlook_mappings_master.xlsx, ninth_pairs_to_esto_pairs)`.
- `transformation_fuel_remap._load_mapping` now derives the refining
  source-fuel -> 9th-fuel mapping from canonical `leap_combined_ninth` (refining
  paths, 24 unambiguous fuels). `mapping_csv_path` is optional and overrides the
  derived base only when the file exists. `_load_pairs` accepts a
  `(path, sheet)` ref so the canonical sheet is read directly.
- `test_refining_capacity_policy.py` passes; derivation + pair resolution
  verified (e.g. Crude oil -> 06_01_crude_oil -> 06.01 Crude oil).

### C5 — electricity/heat interim: BLOCKED, documented (no behaviour change)
Investigated migrating `electricity_heat_interim_workflow.py` off master_config.
Two legacy reads; both cannot be safely migrated yet because the canonical
workbook is missing rows the current logic depends on. Left as-is with an
in-code NOTE pointing here. **Evidence:**

1. `_load_esto_product_to_ninth_fuel` (esto_product -> 9th_fuel relationship)
   still reads `master_config.xlsx/independent_product_mapping`. Removing it and
   relying on canonical would (a) change 8 detailed assignments and (b) drop 8
   aggregate esto->9th rows that feed the parent-code fallback and are ABSENT
   from canonical `ninth_pairs_to_esto_pairs`:
   `01 Coal->01_coal`, `06 Crude oil & NGL->06_crude_oil_and_ngl_unallocated`,
   `07 Petroleum products->07_petroleum_products`, `08 Gas->08_gas`,
   `12 Solar->12_solar`, `15.04 Black liqour->15_04_black_liquor`
   (`02 Coal products`, `05 Oil shale...` are present in canonical).

2. `_load_power_interim_display_name_map` (labels) still reads
   `master_config.xlsx/sector_fuel_code_to_name`. Swapping to canonical
   `leap_display_names` would LOSE 193 code->name entries present in the legacy
   table but absent from `leap_display_names`, many power-sector and
   output-affecting (e.g. `09_01_08_solar->Solar`, `09_02_01_coal->Coal CHP`,
   `09_x_heat_plants->Other heat plants 1`, `12_solar->Solar`). These labels
   drive interim branch names AND the NEVER_OUTPUT filter, so the swap would
   change LEAP output. Not safe as a drop-in.

### C6 — display-name resolution already canonical (verified, no change)
- `transformation_analysis_utils.load_code_to_name_mapping` and
  `supply_config_builder.load_code_to_name_mapping` both read the canonical
  `leap_display_names` sheet first (`CODE_TO_NAME_PATHS[0] =
  OUTLOOK_MAPPINGS_MASTER_PATH`) and only fall back to legacy `code_to_name`
  files if the canonical sheet is absent. Supply, transformation and transfers
  (shared foundation) therefore already label via `leap_display_names`.
- other loss/own use now labels via canonical `raw_leap_fuel_name` (C3);
  refining renames leaves to canonical ESTO product codes (C4). Only the
  electricity/heat interim map remains legacy (C5, blocked).
- Minor future cleanup: the two `load_code_to_name_mapping` copies duplicate the
  `build_code_to_display_name` logic now in `canonical_loaders`; could be
  de-duplicated later, but left as-is to avoid behaviour churn.

## Mapping lineage table (post-migration)

For each supply-reconciliation workflow: which canonical sheet it reads, whether
it goes through a shared loader, the matching keys, allocation/label method, and
any remaining legacy/exceptional logic.

| Workflow | Canonical sheet(s) | Shared loader | Matching keys | Allocation method | Display-name method | Remaining exceptional logic |
|---|---|---|---|---|---|---|
| Direct balance demand (`supply_demand_mapping`) | `leap_combined_esto`, `leap_combined_ninth`, `ninth_pairs_to_esto_pairs` | partial (`load_canonical_pairs`); raw reads for esto/ninth | (leap path, raw fuel); (9th sector, 9th fuel) | exact pair, descendant expansion disabled | via transformation `code_to_name` (canonical) | runtime-inferred esto for demand rows w/o authored LEAP->ESTO row (labelled, not written back) |
| Supply projection alloc (`supply_reconciliation_tables`) | `ninth_pairs_to_esto_pairs` (via `DEFAULT_MAPPING_PAIRS_PATH`, now canonical) | no (uses balance module) | (9th sector, 9th fuel)->(flow, product) | sign-stable allocation | `leap_display_names` (supply_config_builder) | — |
| Transformation projection alloc | `ninth_pairs_to_esto_pairs` (canonical) | no | (9th sector, 9th fuel) | sign-stable allocation | `leap_display_names` | shares foundation with transfers |
| Transfers | shares transformation mapping/allocation | via transformation | same as transformation | same as transformation | `leap_display_names` | — |
| LEAP balance->ESTO conversion (`leap_results_dashboard_balance`) | `ninth_pairs_to_esto_pairs` (canonical, C2) | `load_canonical_pairs` | (9th sector, 9th fuel) | — (label conversion) | codebook/leap fallback | broad module; only pairs pointer migrated |
| Other loss/own use (`other_loss_own_use_proxy_workflow`) | `leap_combined_esto`, `leap_combined_ninth` (C3) | `load_leap_combined_esto/ninth` | esto_product / ninth_fuel -> LEAP fuel | proxy activity (unchanged) | canonical `raw_leap_fuel_name`, unambiguous only | ambiguous fuels -> mechanical cleanup (recorded) |
| Refining (`refining_workflow` / `transformation_fuel_remap`) | `leap_combined_ninth`, `ninth_pairs_to_esto_pairs` (C4) | `load_leap_combined_ninth` | source LEAP fuel -> 9th fuel -> esto_product | branch relabel (unchanged) | ESTO product code as branch leaf | optional `refining_fuel_mapping.csv` override if present |
| Aggregated demand (`aggregated_demand_workflow`) | still reads `read_config_table` redirects | no | — | — | — | NOT migrated this pass — see below |
| Electricity/heat interim | canonical `ninth fuel to esto product` + legacy master_config (C5) | no | esto_product/ninth_fuel | — | legacy `sector_fuel_code_to_name` | BLOCKED: canonical missing ~193 labels + 6 aggregates |
| Preflight (`supply_preflight`) | inherits above (compressed) | inherits | inherits | inherits | inherits | exercises future-only mappings |

## C7 — follow-up files reviewed (aggregated demand / template extractor / name lookup)

Investigated the three "lower priority" files. All three are **already off legacy
mapping data on the active supply-reconciliation path**; only dead code / stale
comments remained:

- `aggregated_demand_workflow.py` — already reads canonical sheets
  (`FUEL_MAPPINGS_PATH = OUTLOOK_MAPPINGS_MASTER_PATH`, `FUEL_ESTO_SHEET =
  leap_combined_esto`, `FUEL_NINTH_SHEET = leap_combined_ninth`). Removed a dead
  `else` branch in `load_fuel_mapping` that read the legacy
  `fuel_ninth_final_proposed` sheet (unreachable — no caller passes that name)
  and fixed a stale docstring referencing `fuel_product_final_proposed`.
  `test_aggregated_demand_workflow.py` (48) passes.
- `energy_balance_template_extractor.py` — reads its `mapping_pairs_path`, which
  on the supply path is the canonical workbook (it loads `leap_combined_ninth`
  from it at runtime). Its `*_final_proposed` reads are wrapped in try/except and
  simply no-op because those sheets are absent from canonical. Left untouched
  because the file also carries unrelated **pre-existing uncommitted changes**;
  the stale "config/leap_mappings.xlsx" comment can be cleaned up in a dedicated
  commit later.
- `unified_name_lookup.py` — deliberately a multi-source name *consolidator*
  (legacy proposed sheets + canonical `leap_combined_*` + master_config), with
  conflict detection. Only consumer of its consolidation API is a scrapbook
  (`fill_apec_9th_fuels_template.py`); its `load_active_mapping_sheet` export is
  called by aggregated demand with canonical paths. Correct as-is; not on the
  reconciliation hot path. No change.

- `read_config_table` legacy filename->master_config redirects remain in place
  (used by non-mapping config tables too); not removed to avoid broad breakage.

## Review diagnostics for the remaining canonical additions (C2 / C5)

Three CSVs under `docs/canonical_migration_diagnostics/` (see its README) list,
for your review, the rows the local `master_config.xlsx` copies carry that the
canonical workbook lacks or maps differently, each annotated with canonical's
alternative mapping:

- `canonical_ninth_pairs_missing_from_canonical.csv` — C2 (1580 rows; 381 are
  malformed local junk).
- `canonical_leap_display_names_missing.csv` — C5 labels (229 rows; 78 whose
  name already exists in canonical under another code).
- `canonical_independent_product_mapping_diff.csv` — C5 relationships (35 rows;
  includes the 6 aggregate esto->9th rows the interim workflow needs).

## Verification done

- New unit tests: `tests/test_canonical_loaders.py` (16),
  `tests/test_canonical_migration_fixes.py` (6) — all pass.
- Regression subset (123 tests) incl. balance-demand conservation, other
  loss/own use, supply conservation/diagnostics/export, module attribute
  contracts — all pass.
- Full suite run: **353 passed, 10 skipped, 0 failed** (exit 0, ~16 min).
- Not run: a live end-to-end supply-reconciliation preflight for a real economy
  (needs LEAP balance exports + full data env). **C2 in particular changes which
  9th->ESTO pairs are used — a real preflight + conservation check is still
  required before LEAP import.**

## Open questions / issues for review

- **[BLOCKER C5] To finish the electricity/heat interim migration, the canonical
  `leap_mappings` workbook must be extended** (via the leap_mappings maintenance
  workflow, not from here):
  - add the 6 missing aggregate esto->9th rows above to a canonical relationship
    sheet (or confirm the parent-code fallback should use canonical aggregates);
  - add the ~193 missing fuel/sector `code -> leap_display_name` entries (power
    plant/CHP/heat-plant/own-use fuels) to `leap_display_names`.
  Once present, both `_load_esto_product_to_ninth_fuel` and
  `_load_power_interim_display_name_map` can switch to the shared canonical
  loaders (a `build_code_to_display_name`-based version is ready to drop in).
  Until then the workflow keeps its master_config reads to avoid changing LEAP
  branch labels / dropping fallback coverage. A per-code diff dump can be
  regenerated on request.


- **[REVIEW C3] Behaviour change in other-loss/own-use output fuel labels.**
  Because the lookup was previously empty, some output-fuel branch labels will
  now be the canonical LEAP fuel name (`raw_leap_fuel_name`) instead of a
  mechanical cleanup of the ESTO product / 9th fuel code. This is more correct
  but changes some branch labels. The 5 ambiguous 9th-fuel codes (a 9th fuel
  code mapping to multiple LEAP fuels in the canonical sheet) are listed in
  `LAST_FUEL_MAPPING_AMBIGUITY['ninth']` after a run — worth a glance to decide
  whether any deserve a context-aware (sector-scoped) rule in leap_mappings.


- **[RISK C2] ninth_pairs content differs between the two workbooks.** The old
  `master_config.xlsx` sheet had 3126 rows; canonical has 2412. Comparing the
  four key columns: 1580 pairs were only in master_config, 937 only in canonical.
  Repointing is the intended migration (canonical = source of truth), but it
  WILL change which 9th->ESTO pairs balance-demand and balance-conversion use.
  **Please run a full supply-reconciliation pass for a known economy/scenario and
  re-check energy conservation + mapped-row coverage before importing to LEAP.**
  If canonical is missing pairs that master_config had and that removes real
  mapped energy, those pairs need to be added to the canonical workbook (in
  leap_mappings), not restored from master_config.
- **[INFO C2] 224 one-to-many 9th->ESTO keys** exist in canonical (a 9th pair
  mapping to multiple ESTO pairs). `load_canonical_pairs` returns these as
  `conflicts` but keeps all rows. This matches the documented mapping-system
  design (many-to-one is fine; one-to-many needs review). Not resolved by
  arbitrary selection.
