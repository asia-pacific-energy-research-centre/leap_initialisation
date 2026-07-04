# Canonical migration diagnostics

Review CSVs generated during the supply-reconciliation canonical mapping
migration. They list rows the local `config/master_config.xlsx` copies carry
that the canonical `leap_mappings/config/outlook_mappings_master.xlsx` does not
(or maps differently), annotated with what canonical maps each side to instead.
Use them to decide which differences are real gaps to add to the canonical
workbook and which are the local copy being stale/junk.

## `canonical_ninth_pairs_missing_from_canonical.csv` (C2)

Every `(9th_sector, 9th_fuel, esto_flow, esto_product)` row in the local
`ninth_pairs_to_esto_pairs` that is absent from canonical (1580 deduped).

| Column | Meaning |
| --- | --- |
| `mc_9th_sector`, `mc_9th_fuel`, `mc_esto_flow`, `mc_esto_product` | the missing key-pair (4 key columns) |
| `ninth_source_in_canonical` | is the `(9th_sector, 9th_fuel)` source present anywhere in canonical? |
| `canonical_esto_for_this_9th_source` | what ESTO pair(s) canonical maps that 9th source to instead (the alternative) |
| `esto_target_in_canonical` | is the `(esto_flow, esto_product)` target present anywhere in canonical? |
| `canonical_9th_for_this_esto_target` | what 9th source(s) canonical maps to that ESTO target instead |
| `ninth_fuel_exists_anywhere`, `esto_product_exists_anywhere` | element-level: does the fuel / product appear at all in canonical? |
| `verdict` | derived interpretation (see below) |

Verdict counts: `esto_target_sourced_elsewhere_in_canonical` 501,
`9th_source_maps_elsewhere_in_canonical` 399, `malformed_blank_key` 381,
`pairing_absent_but_both_codes_exist` 202, `both_sides_retargeted` 88,
`esto_product_absent_from_canonical` 9. The 381 `malformed_blank_key` rows are
junk in the local copy (blank or mis-columned keys) and can be ignored.

### `canonical_ninth_pairs_missing_CLASSIFIED.csv` — the version to actually use

The row-level count above massively overstates real gaps: `ninth_pairs` is
heavily one-to-many, so a local row's full 4-tuple can be "missing" while the
underlying `(9th_fuel -> esto_product)` relationship is still present in
canonical under a different sector/flow. This file reclassifies every missing
row by whether the *relationship* survives in canonical:

| `classification` | Rows | Real gap? |
| --- | --- | --- |
| `fuelproduct_preserved_sectorflow_differs` | 1004 | No — same fuel->product, different sector/flow context (cardinality) |
| `malformed_blank` | 381 | No — local junk |
| `source_key_exists_diff_product` | 106 | No — canonical maps that 9th key to its own target |
| `review_fuelproduct_not_paired` | 51 | Maybe — worth a glance (mostly peat / aggregate labels) |
| `both_relationships_preserved` | 22 | No — pure cardinality artifact |
| `REAL_GAP_*` | **15** | Genuine absence — but see below |

The 15 `REAL_GAP` rows reduce to essentially nothing of substance:
- `03 Peat` / `04 Peat products` used as *9th fuels* (6 rows) — peat is negligible
  for APEC economies; canonical does not carry it.
- `06 Crude oil & NGL` as an *esto_product* (6 rows) — an aggregate label;
  canonical represents this via detailed `06.01`/`06.02` codes.
- `15.04 Black liqour` (3 rows) — a **spelling difference** only; canonical has
  `15.04 Black liquor`.

Conclusion: repointing `ninth_pairs` to canonical (C2) loses **no** material
mapped energy. A live preflight is still worth running, but the diff is not a
blocker. `canonical_products_for_this_fuel` column shows what canonical maps each
fuel to, for quick confirmation.

## `canonical_leap_display_names_missing.csv` (C5 labels)

Legacy `sector_fuel_code_to_name` code->name entries that are missing from or
disagree with canonical `leap_display_names` (229 rows: 193 missing codes, 36
different names).

| Column | Meaning |
| --- | --- |
| `legacy_code`, `code_column` | the code and whether it came from `esto_label` or `9th_label` |
| `legacy_name` | the display name the legacy table gave it |
| `status` | `missing_code` (not in canonical) or `different_name` (canonical disagrees) |
| `canonical_name_for_this_code` | the name canonical currently gives this code (blank if missing) |
| `legacy_name_already_in_canonical` | does `legacy_name` already appear as a display name for some other code? (78 yes / 151 no) |
| `canonical_codes_using_legacy_name` | which canonical codes already use that name |

`different_name` rows are worth a look first — some reveal questionable canonical
entries (e.g. `09.01.01 Electricity plants` currently resolves to `Gas`).

## `canonical_independent_product_mapping_diff.csv` (C5 relationships)

Legacy `independent_product_mapping` esto_product->9th_fuel rows that are missing
from or differ from canonical (35 rows).

| Column | Meaning |
| --- | --- |
| `indep_esto_label`, `indep_9th_label` | the legacy esto_product -> 9th_fuel row |
| `status` | `esto_product_absent_from_canonical_fuel_sheet` / `different_9th_fuel_in_canonical` / `present_plus_extra_canonical_targets` |
| `canonical_9th_for_esto` | what 9th fuel(s) canonical's `ninth fuel to esto product` sheet maps that esto product to |
| `esto_in_canonical_pairs`, `this_9th_in_canonical_pairs` | element presence in `ninth_pairs_to_esto_pairs` |

The 6 aggregate rows the interim workflow depends on show up as
`esto_product_absent_from_canonical_fuel_sheet` (`01 Coal`, `06 Crude oil & NGL`,
`07 Petroleum products`, `08 Gas`, `12 Solar`, `15.04 Black liqour`). The
`different_9th_fuel_in_canonical` rows are mostly canonical being *more specific*
than the legacy aggregate (e.g. `07.13 Lubricants`: legacy
`07_petroleum_products` vs canonical `07_x_other_petroleum_products`).
