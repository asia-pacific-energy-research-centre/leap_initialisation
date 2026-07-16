# AUS baseline seed — things to check on next run

Running list of issues found in the AUS baseline seed output that the next
full run should verify are fixed. For each item, check the regenerated
export against the "expected" note before considering it resolved.

## 1. Feedstock Fuel Share double-normalization (fixed 2026-07-16)

**Symptom:** Fuels with a genuinely small (<1%) feedstock share were getting
wildly inflated after export normalization, stealing share from the real
dominant fuels.

- Row: `Transformation\Electricity interim\Processes\Electricity interim\Feedstock Fuels\Biogas`
  → `Feedstock Fuel Share`, Australia, 2022 was **28.9114529929%** (expected ≈ 0.5%).
- Row: `Transformation\CHP interim\Processes\CHP interim\Feedstock Fuels\Bitumen`
  → `Feedstock Fuel Share`, Australia, 2022 was **31.1035071709%** (expected ≈ 0%, or
  whatever the true small share for `07_x_other_petroleum_products` works out to).

**Root cause:** `normalize_feedstock_share_to_percent()` was being applied twice —
once in `prepare_feedstock_shares_for_export()`
(`codebase/functions/transformation_record_builder.py:711`) and again inside
`normalize_feedstock_shares_for_export()`
(`codebase/functions/transformation_record_builder.py:575`, now removed). The second
pass misread already-percent values under 1% as raw 0–1 fractions and re-multiplied
them by 100, then the per-process renormalization to 100% let that inflated value
crowd out the real dominant fuels.

**Fix applied:** removed the redundant second call at
`codebase/functions/transformation_record_builder.py:575` (landed in `8c32504`
on 2026-07-16).

**Check on next run:** for every process's Feedstock Fuel Share export, confirm
shares sum to 100% per process/year as before, but that no single fuel with a
true share under 1% is now showing double-digit percentages. Specifically
re-check the Biogas (Electricity interim) and Bitumen (CHP interim) AUS 2022
rows above land near their expected small values.

## 2. Bitumen display-name mapping (flagged, not yet investigated)

**Symptom:** ESTO code `07_x_other_petroleum_products` displays as "Bitumen" via
the `leap_display_names` / `outlook_mappings_master.xlsx` mapping, which looks
like a possibly-incorrect label. Not the cause of item 1's inflation, but worth
sanity-checking the true (small) share value that ends up under this label once
item 1 is fixed — if it's not truly Bitumen, the label mapping should be reviewed
with whoever owns `leap_mappings`.

**Check on next run:** confirm whether the near-zero share left after the item 1
fix is plausible for whatever fuel `07_x_other_petroleum_products` actually is,
and decide whether the "Bitumen" label needs correcting in leap_mappings.

## 3. Coke ovens Coal tar Output Share was a false zero (fixed 2026-07-16)

**Symptom:**

```text
Transformation\Coke ovens\Output Fuels\Coal tar
Output Share, Current Accounts, Australia, 2022 -> 0
```

Australia's raw ESTO data shows a real nonzero 2022 coal tar production value
for coke ovens (`09.08.01 Coke ovens` / `02.07 Coal tar` ≈ 5.21 in
`data/00APEC_2025_low_with_subtotals.csv`), so the exported zero was not a
genuine physical zero.

**Root cause:** `MAJOR_SECTOR_CONFIG` flow-sector entries (every `esto`-dataset
sector except `oil_refineries` — `coal_coke_ovens`, `coal_blast_furnaces`,
`coal_patent_fuel_plants`, `coal_bkb_pb_plants`, `coal_liquefaction`,
`gas_blending`, `coal_mines`, `charcoal_processing`,
`nonspecified_transformation`) had no `multi_output` key and defaulted to
`False` in `summarize_transformation_flows`
(`codebase/functions/transformation_sector_analysis.py`). With
`multi_output=False`, only the single largest-value output fuel per flow
(Coke oven coke) was kept in the process record; genuine co-products (Coal
tar, Coke oven gas, benzole) were silently dropped. The dropped fuel was then
back-filled with `Output Share = 0` by the zero-fill Tier-1 extension in
`transformation_record_builder.py`, which looks like a legitimate zero but
isn't.

**Fix applied 2026-07-16:** `multi_output` now defaults to `True` in both
`run_flow_sector_analysis` (`codebase/functions/transformation_analysis_utils.py`)
and `summarize_transformation_flows`
(`codebase/functions/transformation_sector_analysis.py`). Only spot-verified
for `20_USA` so far: Coke ovens gained `Coke oven gas` as a second output
alongside Coke oven coke, and all 19 other USA process records were
byte-identical before/after. Not yet verified for AUS or for the other
newly-multi-output sectors — deliberately deferred to the next full run per
the user's request to keep this separate from the upcoming baseline-seed run.
See
`docs/prompts/transformation_multi_output_default_verification_prompt.md` for
the full verification recipe.

**Check on next run:**

- Confirm `Transformation\Coke ovens\Output Fuels\Coal tar` / `Output Share` /
  `Current Accounts` / Australia / 2022 is now nonzero and consistent with the
  raw ESTO value above.
- Confirm other coke oven co-products (Coke oven gas, benzole if present) also
  show nonzero Output Share for AUS where raw data supports it.
- Confirm Output Share values across all of a sector's output fuels still sum
  to ~100% per flow/year (the main way this change could break a downstream
  consumer that assumed single-output semantics).
- Confirm efficiency and auxiliary-fuel ratios for AUS Coke ovens (and the
  other newly-multi-output sectors listed above) are still plausible, not just
  changed.

## 3. Unused-fuel zero-fill in Demand\Other loss and own use (stale output, no code change)

**Symptom:** In the AUS baseline seed, fuel branches that carry no own-use/loss
energy for a process were *missing* from `Demand\Other loss and own use` rather
than present with Activity Level = 0 / Final Energy Intensity = 0. Reported
specifically for **Heat** under `Transmission and distribution loss` and
`Electricity CHP and heat plants`.

**Root cause:** not a code bug. `add_zero_rows_for_unset_values`
(`codebase/functions/other_loss_own_use_proxy_utils.py:2225`, called from
`assemble_proxy_workbook` at `codebase/other_loss_own_use_proxy_workflow.py:1559`)
already zero-fills every managed branch present in `data/full model export.xlsx`.
The on-disk AUS workbook was **stale** — generated 2026-07-15 16:49, before the
zero-fill fix ran against the full export. That file had only **29** demand
branches; a fresh run with current code produces **93**, with Heat present and
zero-filled on both the `LEAP` and `LEAP_WITH_IDS` sheets. Heat = 0 is the
*correct* value for AUS: source data has no `18 Heat` own-use under either
`10.01.01 Electricity, CHP and heat plants` or
`10.02 Transmission and distribution losses` (only electricity, crude oil,
natural gas, coke oven gas, and petroleum products appear there).

**Fix applied:** none needed — the mechanism works; the fix just has to be picked
up by regenerating. The AUS (and all pre-2026-07-15-fix) baseline-seed workbooks
must be **regenerated**.

**Check on next run:** confirm the regenerated AUS `other_loss_own_use_proxy_01_AUS_*`
workbook has ~93 `Demand\Other loss and own use` branches (not 29), and that
`…\Transmission and distribution loss\Heat` and
`…\Electricity CHP and heat plants\Heat` are each present with all-zero
`Data(…,0.0)` expressions for Activity Level and Final Energy Intensity across
every scenario. More generally, verify that every fuel branch in
`data/full model export.xlsx` under this root that has no real own-use/loss data
appears zero-filled rather than absent. Note the remaining data prerequisite:
enabled processes whose branches are NOT in the export key — **Nuclear industry**
and **Gasification plants for biogases** — cannot be zero-filled and would have
any real data silently dropped by `merge_export_ids`; those branches must be
created in LEAP and the export refreshed.

## 5. Default Process Efficiency rows

**Change to verify:** for every transformation process branch and each scenario,
the current run preserves an existing `Process Efficiency` value. If no value
was already set, it writes `Process Efficiency = 100` with units `Percent`.

**Check on next run:**

- Confirm every transformation process branch has a `Process Efficiency` row
  for `Target`, `Reference`, and `Current Accounts` where the branch is in the
  relevant export scope.
- Confirm `Target` and `Reference` rows cover the projected years, while
  `Current Accounts` covers only the base year, using the same `_years_for_scenario`
  logic as the share rows.
- Confirm newly added default rows contain `100` / `Percent` and do not have
  missing expressions or years.
- Confirm any process efficiency explicitly set by the run remains unchanged;
  the default must not overwrite an existing value.
