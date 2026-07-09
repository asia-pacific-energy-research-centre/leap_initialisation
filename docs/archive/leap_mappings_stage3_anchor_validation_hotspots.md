# Prompt: Optimize Stage 3 anchor validation in `leap_mappings`

## Status

Deferred. Do not start this until the current `leap_mappings` work is complete.

## Goal in one sentence

Reduce the wall-clock time of `run_mapping_pipeline.py`, especially Stage 3
(`source_parent_anchor_validation.py`), without changing any numeric outputs.

## Why this is deferred

This is a follow-up task for `leap_mappings`, not something to act on now.
Record it here so it is ready to pick up after the active mapping work finishes.

## Confirmed hotspots from the 2026-07-04 full pipeline run

1. `codebase/mapping_tools/source_parent_anchor_validation.py:383-413`
   (`load_raw_source_anchor_inputs`) does three row-wise
   `ninth[...].apply(lambda row: ..., axis=1)` passes over the raw 9th Outlook
   dataframe (`data/merged_file_energy_ALL_20251106.csv`, about 522k rows).
   It builds `source_flow`, `source_product`, and lookup columns by joining
   hierarchy levels with `/` and selecting the most specific non-`x` value.
   This is slow and triggers pandas fragmentation warnings.
   - Replace the row-wise apply with vectorized string operations.
   - Reuse the vectorized "most specific non-x sector/fuel" logic already used
     in `codebase/mapping_tools/apply_ninth_to_esto_conversion.py:52-63`
     (`prepare_ninth_long_format`) instead of re-deriving it row by row.

2. The same 522k-row 9th CSV is read and reshaped independently in three
   places:
   - `prepare_ninth_long_format` in `apply_ninth_to_esto_conversion.py`
   - `load_raw_source_anchor_inputs` in `source_parent_anchor_validation.py`
   - `build_ninth_tree` during the tree-validation stage
   Each reshape produces a roughly 23.7M-row long-format frame from scratch.
   - Check whether `run_mapping_pipeline.py` can build the 9th long-format frame
     once and pass it forward to later stages instead of repeating the work.

3. Coverage is only checked after melting to full long format.
   In the observed run, the 9th-to-ESTO conversion melted 23,760,464 rows and
   then found that 20,310,381 rows, or 85%, had no included ESTO mapping.
   Stage 3 then carries 8,656,668 ESTO-shaped rows through reconciliation and
   anchor validation.
   - Consider filtering the wide 9th dataframe to only source_flow /
     source_product pairs with an included mapping before melting year columns.
   - That would avoid expanding unmapped sector/fuel combinations across all
     years.

## Goal

Measurably reduce Stage 3 and 9th-to-ESTO wall-clock time in
`run_mapping_pipeline.py` without changing results.

## Non-negotiable output check

Byte-for-byte numeric outputs must remain unchanged:

- `results/mapping_relationships`
- `results/common_esto`

## Suggested verification

Add a quick before/after timing comparison around
`load_raw_source_anchor_inputs` using `time.perf_counter`, then confirm the
timing improvement on a full pipeline run.

