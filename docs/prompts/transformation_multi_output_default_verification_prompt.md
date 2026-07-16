# Task: Verify the multi_output=True default for transformation flow sectors

## Short version

On 2026-07-16 the `multi_output` default for `run_flow_sector_analysis` /
`summarize_transformation_flows` was changed from `False` to `True` (see "What
changed" below), fixing dropped co-product outputs (e.g. Australia coke ovens
Coal tar Output Share was 0 when source data shows a real nonzero value). This
was spot-verified only for `20_USA` against the current baseline. Once the next
full baseline-seed run (which bundles many other fixes) completes, re-verify
this specific change across all economies using that run's fresh seeds/exports,
since it was deliberately not verified broadly to avoid coupling with that run.

## Context

Root cause (see git history / commit for this change around 2026-07-16):
`MAJOR_SECTOR_CONFIG` in `codebase/functions/transformation_analysis_utils.py`
only set `"multi_output": True` explicitly for `oil_refineries`. Every other
`esto`-dataset flow-sector entry (`coal_coke_ovens`, `coal_blast_furnaces`,
`coal_patent_fuel_plants`, `coal_bkb_pb_plants`, `coal_liquefaction`,
`gas_blending`, `coal_mines`, `charcoal_processing`,
`nonspecified_transformation`) had no key and fell back to the `False` default
via `sector_config.get("multi_output", False)`. With `multi_output=False`, only
the single largest-value output fuel per flow was kept
(`transformation_sector_analysis.py::summarize_transformation_flows`,
`FEEDSTOCK_METHOD_MULTI` branch) — every other genuine co-product (e.g. coke
oven gas, coal tar, benzole for coke ovens) was silently dropped from the
process record, then back-filled with `Output Share = 0` by the zero-fill
"Tier-1 extension" in `transformation_record_builder.py`, producing rows that
look like legitimate zeros but are not.

The fix changed the default to `True` in two places:

- `codebase/functions/transformation_analysis_utils.py`: the
  `sector_config.get("multi_output", ...)` call inside `run_flow_sector_analysis`.
- `codebase/functions/transformation_sector_analysis.py`: the `multi_output=`
  parameter default on `summarize_transformation_flows`.

Verify both still say `True` before relying on this prompt — search for
`multi_output` in both files with `rg` rather than trusting line numbers here.

## What was already checked (do not redo)

For `20_USA`, `collect_transformation_rows(economies=["20_USA"])` was run twice
in the same interpreter: once against the unmodified config (monkeypatched
locally, not committed) and once with every esto flow-sector's `multi_output`
forced to `True`. Of 20 process records, exactly one changed
(`Coke ovens / 09.08.01 Coke ovens`): it gained `02.03 Coke oven gas` as a
second output alongside `02.01 Coke oven coke`, matching USA's raw ESTO data
(which already showed both fuels as real outputs). All other 19 records were
byte-identical. This was re-confirmed against the actual (non-monkeypatched)
code after the edit landed.

This is a single-economy, single-sector confirmation. It does not cover:

- Other economies, especially Australia (the original reported case: coal tar
  under coke ovens).
- Other sectors that now take the multi-output branch for the first time
  (`coal_blast_furnaces`, `coal_patent_fuel_plants`, `coal_bkb_pb_plants`,
  `coal_liquefaction`, `gas_blending`, `coal_mines`, `charcoal_processing`,
  `nonspecified_transformation`).
- Downstream effects on efficiency, auxiliary ratios, own-use ratios, and
  Output Share zero-fill rows once a full multi-economy export/import cycle
  runs.

## Prerequisites

- Confirm the pending full baseline-seed run referenced in
  `docs/prompts/supply_reconciliation_full_baselineseed_run_execution_prompt.md`
  (or whatever superseded it) has completed and its seeds/exports are current.
- Run `git status --short` first; preserve unrelated in-progress changes.
- Re-read `MAJOR_SECTOR_CONFIG` and confirm which sectors still lack an
  explicit `multi_output` key (i.e. rely on the default) versus which now have
  it set explicitly — the config may have been edited further since this
  prompt was written.

## Validation steps

1. Confirm the original reported case is fixed: for `01_AUS`, 2022, check
   `Transformation\Coke ovens\Output Fuels\Coal tar` / `Output Share` /
   `Current Accounts` is now nonzero in the fresh export/seed, and that the
   value is consistent with Australia's raw ESTO coal tar production for coke
   ovens (cross-check against
   `data/00APEC_2025_low_with_subtotals.csv` or the current APEC source file,
   `09.08.01 Coke ovens` / `02.07 Coal tar`).
2. For each of the newly-multi-output sectors, spot-check 2-3 economies with
   known multi-fuel activity (use the sector's raw ESTO rows, not just the
   process record, to know what to expect) and confirm all genuine positive
   output fuels now appear as separate output/Output Share rows, not just the
   single largest one.
3. Confirm process efficiency and auxiliary-ratio values shifted sensibly
   (denominator/numerator now include the additional output fuel) rather than
   becoming implausible (e.g. efficiency > 1, negative, or auxiliary ratios
   ballooning).
4. Confirm sectors with a single genuine output fuel (e.g. USA blast furnaces)
   are unaffected — the multi-output branch should be a strict superset
   behavior, not a value change, when there is truly only one output.
5. Run the existing transformation test suite and confirm no regressions:

```powershell
C:\Users\Work\miniconda3\python.exe -m pytest tests\test_transformation_conservation.py tests\test_transformation_sector_registration.py tests\test_transformation_analysis_utils_filtering.py tests\test_transformation_historical_only_zero_skeleton.py tests\test_transformation_lng_zero_skeleton.py tests\test_transformation_export_region_guard.py
```

6. Check whether `build_aux_fuel_zero_rows`'s zero-fill Tier-1 extension in
   `transformation_record_builder.py` now produces fewer zero-filled Output
   Share rows for these sectors (expected: fewer, since more fuels get real
   values instead of being back-filled with 0). Spot-check a couple of
   examples rather than diffing every row.

## Stop conditions / when to ask the user

- If any economy shows an output fuel share sum that no longer sums to
  approximately 1.0 (or 100%) across a sector's outputs, stop and report before
  changing code — this may indicate `_build_output_share_lookup` or a
  downstream consumer assumed single-output semantics.
- If efficiency or auxiliary-ratio values become implausible for any
  newly-affected sector, stop and report which sector/economy before deciding
  whether this is a genuine data pattern or a computation bug exposed by the
  fix.
- If the full baseline-seed run this prompt depends on has not completed, do
  not run a separate ad hoc full-economy transformation export just for this
  check — wait for the scheduled run's outputs, per the user's instruction to
  keep this verification separate from that run.
- Do not touch `MAJOR_SECTOR_CONFIG` sector definitions or re-introduce a
  per-sector `multi_output: False` override without discussing with the user
  first — the intent of this change was to make multi-output the universal
  default.

## Deliverables

1. Confirmation (with numbers) that the Australia coal tar case is fixed.
2. A short table of which sectors/economies were spot-checked and whether
   output-share sums and efficiency values look correct.
3. Test suite pass/fail result.
4. Any anomalies found, classified as genuine data patterns vs. computation
   bugs, with recommended next step for each.
