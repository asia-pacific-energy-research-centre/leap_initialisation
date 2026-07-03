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

## Open questions / issues for review

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
