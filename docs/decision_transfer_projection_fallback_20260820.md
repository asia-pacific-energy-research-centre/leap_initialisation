# Decision record — baseline-seed transfer projection fallback (queue item [50])

Date: 2026-08-20. Investigation only; no production behaviour changed, no
mappings/dashboard edits, no baseline-seed batch run.

> **Decision taken 2026-08-20 — policy C with carry-forward approved.** §8 below
> originally returned `HUMAN_SEMANTIC_DECISION_REQUIRED` and asked the 9th
> maintainers to settle what an all-zero projection means. The maintainer decided
> without needing that answer, on different grounds: zero is wrong regardless of
> what the 9th intended, this codebase is not the right place to estimate how
> transfers should evolve, and a flat base-year carry-forward is a reasonable
> placeholder that detailed modelling can replace later. Carry-forward is the
> policy. §5's criterion selects where it applies; §7's regression cases stand.
> The method is recorded in
> [`initialisation_flow_estimation_methods.md`](initialisation_flow_estimation_methods.md#projection-availability-and-the-base-year-carry-forward),
> which also records the intended long-term replacement (activity-driven
> proxies). See §9 for the revised verdict.

Sources measured: `data/merged_file_energy_ALL_20251106.csv` (9th),
`data/00APEC_2024_low_with_subtotals.csv` (ESTO base table, base year 2022),
and the transfer workbooks of the last full seed run
`outputs/leap_exports/supply_reconciliation/baseline_seed/runs/BASELINE_ALL_TEMPLATES_FULL_NOPREFLIGHT_20260805/workbooks/`.

## 1. Where scenario is lost, and where it is not

The queue's premise is half right and needs correcting before any code is written.

**The seed workbook path is already scenario-aware.** Seed transfer workbooks are
written by `results_saver.py:1977` → `save_transfer_exports_with_supply_overrides`
(`supply_reconciliation/leap_io.py:844`), which at line 880 calls
`transfers_workflow.build_transfer_rows(..., scenario=projection_scenario)` with
`"target"`/`"reference"` derived per scenario. That reaches
`build_transfer_data_for_scenario` (`transfers_workflow.py:643`), which merges ESTO
history with a scenario-filtered 9th projection. The 2026-08-05 workbooks confirm
this empirically: `01_AUS` 2060 Exogenous Capacity is 79.01 under Reference and
73.56 under Target; `20_USA` is 7047.57 vs 8759.19. Requirement 1 of the queue item
is **already satisfied for the workbook values**.

**Scenario is lost on the reconciliation input path**, at a single site —
`codebase/supply_reconciliation/tables.py:182-206`,
`_collect_transformation_and_transfer_rows`:

- line 188: `transformation_workflow.collect_transformation_rows(economies=...)` —
  that function accepts `projection_scenario` (`transformation_workflow.py:158`)
  and it is not passed.
- line 200: `transfers_workflow.build_transfer_process_records(economy=..., use_output_targets=False)` —
  the legacy wrapper at `transfers_workflow.py:1208` does not even expose
  `scenario`, so it cannot be passed; `build_transfer_rows` therefore falls to
  `data = core.esto_data`, i.e. history only, no projection years at all.

Both outputs (`build_transformation_balance_table`,
`build_transformation_sector_table`) have **no scenario column**, so the loss is
structural, not just an unpassed argument. They feed `transformation_table` →
`build_reconciliation_table` (`results_saver.py:1691`) → `reconciliation_table`,
which is passed back into `save_transfer_exports_with_supply_overrides` as the
Process Share override source. A single scenario-blind reconciliation view is
therefore applied to both scenario workbooks.

**Where future values become zero.** Two distinct sites, neither of which is a
deliberate "extend as zero" rule:

- `functions/ninth_projection_mapping.py:1957` —
  `merged[year] = merged[proj_col].fillna(0.0)` in `merge_projection_into_esto`.
  The ESTO frame is left-joined to the projection table on
  `(economy, flow, product)`; any row with no projection match becomes 0.0 for
  every projection year. The run log emits
  `[WARN] No mapped 9th projection match for 97290 ESTO rows across 21 economies;
  projection years will be zero-filled` and names all four `08.xx` transfer flows
  among the top affected. **This is where "explicitly zero" and "no projection
  supplied" become indistinguishable** — after the `fillna`, nothing downstream can
  tell them apart.
- `functions/transformation_record_builder.py:543` `clip_value_by_year_range` keeps
  only years present in a record's `{year: value}` map, and `:1523`
  `_sum_series_map_by_year` substitutes 0.0 for absent years. This is the path that
  bites when `scenario` is not passed at all and the record ends at 2022.

Passing the scenario does not fix the zeros: `12_NZ` Reference in the 2026-08-05
run already came from the scenario-aware path and is 0.0 for all 38 projection
years, because the 9th table itself stores exact `0.0` (not NaN) there.

Current Accounts is base-year only (a single 2022 point) in every workbook checked.
That policy is intact and untouched by anything proposed here.

## 2. Economy × scenario evidence (active seed economies)

`GLOBAL_ECONOMIES` = the 11 below. 9th values are leaf rows
(`subtotal_results == False`, sector `08_transfers`), absolute mass in PJ. Seed
values are from the 2026-08-05 run, Exogenous Capacity, summed absolute. Reference
and Target are identical on every measure below **except** for the two
`projection_supplied` economies, so one row per economy suffices; scenario
differences are given inline.

| Economy | ESTO 2022 (abs) | Seed CA 2022 | 9th 2022 | post-2022 non-zero years | first / last non-zero | 9th projection state | Seed Ref / Tgt 2023-2060 |
|---|---|---|---|---|---|---|---|
| 01_AUS | 418.61 | 265.68 | 418.61 | 38 / 38 | 2023 / 2060 | supplied, declining | 158.49 (2030) → 79.01 / 73.56 (2060) |
| 20_USA | 13676.49 | 7049.54 | 13672.55 | 38 / 38 | 2023 / 2060 | supplied (Ref = flat carry-forward of 2022; Tgt grows) | 7047.57 flat / 8759.19 (2060) |
| 02_BD | 47.46 | 24.09 | 188.91 | 0 / 38 | — | all exactly 0.0 | 0.0 all years |
| 11_MEX | 343.81 | 182.43 | 612.78 | 0 / 38 | — | all exactly 0.0 | 0.0 all years |
| 12_NZ | 35.34 | 18.14 | 41.49 | 0 / 38 | — | all exactly 0.0 | 0.0 all years |
| 21_VN | 32.86 | 16.43 | 131.43 | 0 / 38 | — | all exactly 0.0 | 0.0 all years |
| 05_PRC | 5228.42 | **0.00** | 20913.67 | 0 / 38 | — | all exactly 0.0 | 0.0 all years |
| 13_PNG | 1.32 | **0.00** | 5.28 | 0 / 38 | — | all exactly 0.0 | 0.0 all years |
| 19_THA | 0.00 | 0.00 | 0.00 | 0 / 38 | — | zero, and base year zero too | 0.0 all years |
| 10_MAS | 0.00 | 0.00 | no 9th rows | — | — | absent (no rows) | 0.0 all years |
| 15_PHL | 0.00 | 0.00 | no 9th rows | — | — | absent (no rows) | 0.0 all years |

Notes on the table:

- `02_BD` is **Brunei Darussalam** throughout.
- 9th 2022 exceeds ESTO 2022 for the zero-projection economies because the 9th
  carries extra transfer rows in the base year. The seed base year is built from
  ESTO, not the 9th, which is why `21_VN` has a non-zero seed base year despite a
  9th 2022 of 131.43 that never projects.
- APEC-wide, only four economies have any post-2022 transfer projection —
  `01_AUS`, `03_CDA`, `09_ROK`, `20_USA` — reproducing the queue's "4 active
  economies" note. Two of the four are in seed scope.
- **`05_PRC` and `13_PNG` are a separate defect, not a projection-fallback case.**
  Both have non-zero ESTO base-year transfers (5228.42 and 1.32 PJ) that are already
  zero in the *base year* of the seed. Confirmed directly:
  `build_transfer_rows("05_PRC")` returns **0 rows** — `05_PRC` has no
  `TRANSFER_PROCESS_CONFIG` entry, so it falls to `_build_template_processes`, which
  yields nothing; `build_transfer_rows("13_PNG")` returns 1 row that lands in
  `Transfers unallocated` carrying no mass. A carry-forward policy would carry zero
  for both and change nothing until this is fixed independently.

## 3. Is a zero projection ever intentional in a maintained source?

**No maintained source declares it either way.** Checked
`leap_mappings/config/mapping_issue_exception_sets.xlsx`, the repo's designated home
for "deliberately not modelled" scope
(`leap_mappings/docs/special_rules_and_design_decisions.md:545`). Its
`unmodelled_source_ignored` sheet lists sectors 18/19 and three aggregate fuel
columns. **`08_transfers` is not on it**, so transfers are not registered as an
unmodelled sector. The same workbook's `source_mismatch_allowed` sheet does carry
confirmed `08_transfers` entries — classed `source_non_additivity` and
`provisional_apec_anchor_review`, economy `all`, years 2030-2070 — i.e. the 9th
transfers block is already known to be internally inconsistent in its projection
years.

Circumstantial evidence that the zeros mean "not supplied":

- The zeros are exact `0.0` for all 38 projection years in **both** scenarios,
  identically, with no taper from a substantial 2022 value. `05_PRC` drops from
  20913.67 PJ to 0.0 in a single year.
- Where the 9th team had no view but wanted continuity they encoded it explicitly:
  `20_USA` Reference and `03_CDA` are exact flat carry-forwards of the 2022 value
  through 2060. Zeroing is not their idiom for "no view".
- `08_transfers` sits in the never-projected list alongside `06_stock_changes`,
  `11_statistical_discrepancy` and `22_demand_supply_discrepancy` for 13 of 15
  economies — but unlike those three, four economies *do* project it, so it is not a
  modelling convention, it is per-economy modeller behaviour.

Circumstantial is not proof. Nothing in any maintained artefact distinguishes "the
modeller forecast transfers ceasing after 2022" from "the transfers block was never
populated for this economy". That distinction is a statement about intent held by
the 9th team, and this repository does not record it.

## 4. Policy comparison

Tested against one projected case (`01_AUS`) and one zero case (`12_NZ`).

**A — current zero-fill.** `01_AUS` correct. `12_NZ` runs at 18.14 PJ in 2022 under
Current Accounts and 0.0 from 2023 under both scenarios: a hard cliff at the
base-year boundary in every LEAP area, for six of eleven seed economies. Semantic
risk: the seed asserts, with no evidence, that transfers cease; downstream balance
closure absorbs the discontinuity into whatever residual it can find.

**B — always carry forward 2022 where post-base values are all zero.** `01_AUS`
unaffected (it has a projection). `12_NZ` becomes 18.14 PJ flat to 2060; continuity
restored. `19_THA`, `10_MAS`, `15_PHL` are no-ops because their base year is zero.
Semantic risk: if a 9th modeller ever *does* mean "transfers cease", B silently
overrides a real forecast and leaves no marker, so it is undetectable after the
fact. B also must never be generalised beyond transfers — the same all-zero pattern
holds for `06_stock_changes` and `11_statistical_discrepancy`, where zeroing after
the base year is genuinely correct.

**C — scenario-aware projection, explicit 9th values kept including intentional
zeros, documented carry-forward only for a separately detected
`projection_unavailable` state.** Numerically identical to B on today's data — the
criterion in §5 flags exactly the same six economies — but the state is computed,
recorded and auditable, so a later correction to the 9th reclassifies automatically
and the seed stops carrying forward without a code change. C is B plus a receipt.

C is the recommended shape, **subject to the condition in §6**.

## 5. Proposed availability criterion

Computed per (economy, scenario) over 9th leaf rows in sector `08_transfers`, and
evaluated **before** the `fillna(0.0)` at `ninth_projection_mapping.py:1957`:

```
projection_unavailable :=
      ESTO base-year (2022) transfer mass for the economy  >  tolerance
  AND 9th rows exist for (economy, scenario)
  AND every 9th projection year 2023..2060 is exactly 0.0 (not NaN, not near-zero)
```

with the complementary states `projection_supplied` (any non-zero projection year),
`structural_zero` (ESTO base year is itself zero — nothing to carry), and
`no_ninth_rows` (no 9th transfer rows at all for that economy/scenario).

Measured classification, all 11 seed economies, both scenarios:

- `projection_supplied` — `01_AUS`, `20_USA`
- `projection_unavailable` — `02_BD`, `05_PRC`, `11_MEX`, `12_NZ`, `13_PNG`, `21_VN`
- `structural_zero` — `19_THA`
- `no_ninth_rows` — `10_MAS`, `15_PHL`

The criterion is **reliable as a detector of the data pattern**: it separates all
four states cleanly, is stable across Reference and Target, and correctly declines
to flag `19_THA` and the two economies with no 9th rows. Keying on the **ESTO** base
year rather than the 9th base year is what makes `19_THA` classify correctly —
keying on 9th history would misclassify it, because the 9th carries 24.68 PJ of
`19_THA` transfer history before 2022.

It is **not reliable as a detector of intent.** It detects "all-zero after the base
year", and §3 establishes that no maintained source says whether that means
"unavailable" or "forecast to cease". Encoding it is equivalent to deciding, on our
own authority, that all-zero means missing.

## 6. Recommendation and affected economies

1. **Do now, independently of the semantic question** — pass the run scenario
   through `_collect_transformation_and_transfer_rows`. This is a correctness fix
   with no semantic content: the reconciliation currently applies one scenario-blind
   transformation/transfer view to both scenario workbooks. It requires
   `build_transfer_process_records` to gain a `scenario` parameter (or be replaced at
   that call site by `build_transfer_rows`), `collect_transformation_rows` to receive
   `projection_scenario`, and a `scenario` column on both balance tables.

2. **Do now** — emit the §5 classification as a diagnostic CSV on every seed run,
   with no behavioural effect, capturing the state *upstream* of the `fillna(0.0)`
   so the explicit-zero/absent distinction is preserved at least in the record. This
   makes the state visible and dated, and gives the 9th maintainers something
   concrete to confirm or deny.

3. ~~**Do not encode the carry-forward yet.**~~ **Superseded 2026-08-20 — approved,
   see the note at the top.** Affected economies: `02_BD`, `11_MEX`, `12_NZ`,
   `21_VN` immediately, plus `05_PRC` and `13_PNG` once their separate base-year
   defect (§2) is fixed — at which point `05_PRC` alone moves ~5228 PJ of
   base-year transfer mass into every projection year of both scenarios. That
   magnitude is the reason the two defects must be fixed in order: the base-year
   defect first, then carry-forward, so PRC's mass is verified in the base year
   before it is propagated across 38 years.

## 7. Three focused regression cases

1. **Scenario reaches the reconciliation input.**
   `tests/test_transfer_projection_scenario_plumbing.py` (new). Monkeypatch
   `transfers_workflow.build_transfer_process_records` and
   `transformation_workflow.collect_transformation_rows`; call
   `_collect_transformation_and_transfer_rows(economies=["12_NZ"], scenario="target")`
   and assert both receive `"target"`. Guards the §6.1 fix and the
   `build_transfer_process_records` signature gap at `transfers_workflow.py:1208`.

2. **Availability classifier, four states.**
   `tests/test_transfer_projection_availability.py` (new). Synthetic ESTO + 9th
   frames covering one economy per state, asserting `projection_supplied`,
   `projection_unavailable`, `structural_zero`, `no_ninth_rows`. Must include a case
   with a non-zero base year and a projection of `1e-12` asserting
   `projection_supplied` — the criterion is "exactly 0.0", and a near-zero tolerance
   here would silently reclassify real forecasts as missing.

3. **Explicit zeros survive; scenario workbooks stay distinct.**
   Extend `tests/test_transfer_no_data_zero_skeleton.py`, which already threads
   `scenario` through its `_fake_build_transfer_rows` fake. Add a case where the 9th
   supplies a genuine declining-to-zero projection, asserting the exported expression
   retains those years rather than being replaced by a carry-forward; and a case
   asserting that Reference and Target workbooks for an economy with a
   scenario-varying projection do not produce identical expressions. Guards against a
   future carry-forward overwriting real forecasts, and against regression to a
   single scenario-blind transfer view.

## 8. Verdict

The mechanical half of item [50] is unblocked and specified (§6.1, §6.2). The
semantic half is not: the criterion in §5 detects the data pattern reliably and the
intent behind it not at all, and §3 shows the maintained sources are silent.

**Unresolved source meaning.** Whether an exact-zero 9th projection for
`08_transfers`, in an economy with a substantial non-zero 2022 value, means "not
supplied" or "forecast to cease".

**Smallest evidence needed to decide it.** A yes/no from the 9th-edition maintainers
on the six flagged economies — `02_BD`, `05_PRC`, `11_MEX`, `12_NZ`, `13_PNG`,
`21_VN` — asking specifically why `20_USA` Reference and `03_CDA` were encoded as
flat carry-forwards of the 2022 value while these six were encoded as zeros. One
answer settles all six. If confirmed as "not supplied", record it in
`leap_mappings/config/mapping_issue_exception_sets.xlsx` so the classifier reads a
maintained fact rather than inferring one, then implement policy C.

## 9. Revised verdict (2026-08-20)

§8 is retained as the record of what the evidence alone could settle. The
maintainer's decision resolves the blocker on separate grounds, set out in the
note at the top: the choice is not "what did the 9th mean" but "what is the least
wrong placeholder for a flow this repository is not meant to project". Zero is
wrong on its face; a flat base-year carry-forward is reasonable, visible as a
placeholder, and replaceable by real modelling.

The 9th maintainers' answer is still worth having — it would let the classifier
read a maintained fact instead of a data pattern — but nothing waits on it.

Implementation was completed in `5c304fd`: §6.1 (scenario plumbing), §6.2
(classification diagnostic, computed upstream of the `fillna(0.0)`), §5 (the
criterion selecting where carry-forward applies), §7 (three regression cases).
The `05_PRC`/`13_PNG` base-year defect in §2 is a prerequisite for those two
economies and must land first. The method and its intended long-term replacement
are recorded in
[`initialisation_flow_estimation_methods.md`](initialisation_flow_estimation_methods.md#projection-availability-and-the-base-year-carry-forward).

IMPLEMENTED_AND_FOCUSED_TESTED
