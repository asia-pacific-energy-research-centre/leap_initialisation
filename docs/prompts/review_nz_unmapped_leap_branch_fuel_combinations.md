# Prompt: review unmapped New Zealand LEAP branch/fuel combinations

You are working in the APERC repositories. Review the New Zealand LEAP export template:

`C:\Users\Work\github\leap_initialisation\data\leap_export_templates\leap_export_template 12_NZ.xlsx`

The purpose of this task is to quantify and explain LEAP branch/fuel combinations that do not currently have active mappings to ESTO and/or the 9th Outlook. Do not modify the mapping workbook during this review. The eventual goal is to produce safe, paste-ready mapping rows, but this task is first an evidence-based gap assessment.

## Reference mapping workbook

Use the canonical mapping workbook from the `leap_mappings` repository:

`C:\Users\Work\github\leap_mappings\config\outlook_mappings_master.xlsx`

Use these sheets:

- `leap_combined_esto`
- `leap_combined_ninth`
- `ninth_pairs_to_esto_pairs` when it helps trace an indirect LEAP → 9th → ESTO relationship

Use the mapping-system documentation in:

`C:\Users\Work\github\leap_mappings\docs\mappings_system.md`

Treat rows marked as removed/inactive according to the workbook’s existing conventions as unavailable mappings. In particular, distinguish a true missing mapping from a `removed_only` or intentionally excluded row. Do not reactivate removed rows automatically.

## LEAP export reading requirements

1. Read the LEAP export with the correct LEAP header offset (`header=2` unless inspection proves this file uses another valid layout).
2. Inspect the sheet names and columns before processing.
3. Identify the full branch path and the raw LEAP fuel name using the actual export structure and the existing mapping-sheet conventions. Do not silently assume that the fuel is always the final branch-path segment; document the extraction rule used.
4. Restrict the review to genuine branch/fuel source combinations. Exclude blank rows, metadata rows, non-energy/control variables, and duplicate export records that do not represent distinct source combinations.
5. Preserve the original spelling/casing in `raw_leap_fuel_name` and `leap_sector_name_full_path`; use a separately documented normalized key for matching.

## Matching logic

For every unique NZ `(leap_sector_name_full_path, raw_leap_fuel_name)` pair:

1. Check whether the pair has an active direct mapping in `leap_combined_esto`.
2. Check whether the pair has an active direct mapping in `leap_combined_ninth`.
3. Record whether the pair is:
   - mapped in both sheets;
   - mapped only to ESTO;
   - mapped only to the 9th Outlook;
   - unmapped in both;
   - present only in removed/inactive rows;
   - ambiguous because multiple active targets exist;
   - a likely parent/subtotal or aggregate row requiring hierarchy review.
4. Treat a mapping as a match only after applying the same normalization used by the mapping workflow. Show both the original values and the normalized comparison values.
5. Check for parent/child and subtotal mismatches. A missing leaf mapping must not be “fixed” by adding a parent mapping if that would create double counting. Likewise, do not count an aggregate fuel label as a missing real LEAP branch if it is not an actual LEAP branch.
6. Where useful, trace `leap_combined_ninth` through `ninth_pairs_to_esto_pairs` to identify an indirect ESTO counterpart. Label this as indirect evidence, not as an existing direct `leap_combined_esto` mapping.

## Required headline results

Report exact counts for:

- total unique NZ branch/fuel combinations reviewed;
- combinations mapped in both target systems;
- combinations mapped only to ESTO;
- combinations mapped only to the 9th Outlook;
- combinations unmapped in both;
- combinations present only in removed/inactive rows;
- combinations with multiple active ESTO targets;
- combinations with multiple active 9th targets;
- combinations requiring subtotal or parent/child review;
- distinct branch paths affected;
- distinct raw fuel names affected.

Also report counts after deduplicating equivalent normalized pairs, so duplicate spelling/casing does not inflate the concern.

## Required output files

Write compact, human-reviewable outputs under a clearly named folder such as:

`C:\Users\Work\github\leap_initialisation\outputs\mapping_gap_review\12_NZ\`

At minimum create:

1. `summary.csv` — the headline counts and definitions.
2. `all_nz_branch_fuel_pairs.csv` — every reviewed unique source pair with match status, normalized keys, source row counts, and any subtotal/parent-child flags.
3. `unmapped_or_partial_nz_branch_fuel_pairs.csv` — only pairs missing in at least one target system, with clear reason/status fields.
4. `mapping_review_candidates_esto.csv` — candidate rows for possible insertion into `leap_combined_esto`, only where an ESTO target can be supported by existing mapping evidence. Include confidence, evidence, and review status.
5. `mapping_review_candidates_ninth.csv` — candidate rows for possible insertion into `leap_combined_ninth`, using the same evidence standard.
6. `README.md` — describe the input files, sheet names, header handling, normalization, exclusions, status definitions, counts, and limitations.

The candidate files must use these exact columns and order:

For `mapping_review_candidates_esto.csv`:

```text
leap_sector_name_full_path,raw_leap_fuel_name,esto_flow,esto_product,leap_is_subtotal,esto_pair_is_subtotal,duplicate_to_remove
```

For `mapping_review_candidates_ninth.csv`:

```text
leap_sector_name_full_path,raw_leap_fuel_name,ninth_sector,ninth_fuel,leap_is_subtotal,ninth_pair_is_subtotal,duplicate_to_remove
```

If a candidate cannot be fully supported, leave its target fields blank and keep it in the diagnostic output rather than inventing a mapping. Candidate files should contain only complete, reviewable candidates unless the README explicitly labels a separate unresolved section. Set `duplicate_to_remove` blank unless there is direct evidence that the row duplicates an existing mapping and should be removed; never use this field as a guess.

## Evidence and quality rules

- Do not add or edit rows in `outlook_mappings_master.xlsx`.
- Do not infer mappings from name similarity alone.
- Do not split one LEAP aggregate across multiple ESTO or 9th targets without an explicit allocation method.
- Prefer an existing reviewed branch-to-flow and fuel-to-product pattern, an auditable indirect chain, or a clearly documented exact match.
- Flag aggregate targets such as `Total` rows and all subtotal-level mismatches for human review.
- Separate “missing direct mapping” from “no comparable category exists” and “mapping intentionally removed”.
- If the workbook columns differ from the requested names, show the actual columns and explain the translation rather than silently renaming semantics.
- Validate that candidate rows do not create one-to-many or many-to-many source coverage before presenting them as paste-ready.
- Check that no candidate duplicates an active existing row after normalization.

## Final response

Start with the headline number of unique NZ branch/fuel combinations and the number missing from each mapping sheet. Then summarize the main causes of the gaps and point to the output files. Clearly separate:

1. confirmed unmapped combinations;
2. removed or intentionally excluded combinations;
3. ambiguous/subtotal cases;
4. genuinely supportable mapping candidates.

Do not claim that a candidate is safe to insert until its target, subtotal level, cardinality impact, and evidence are shown.
