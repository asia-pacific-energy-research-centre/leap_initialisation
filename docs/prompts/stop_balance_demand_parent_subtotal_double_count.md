# Prompt: Stop the balance-demand conservation reference from double-counting mis-flagged parent-product subtotals

## Goal in one sentence

Make the balance-demand conservation **reference** side exclude ESTO parent-product
subtotal rows that are mis-flagged `is_subtotal=False` in the source CSV, so the
check stops reporting a spurious ~58 PJ mismatch that is actually reference-side
double-counting — not lost demand.

Work only in `leap_initialisation`. Do **not** change `leap_mappings`. Do **not**
change the demand actually written to the LEAP import workbook.

## Background — the confirmed finding (don't re-derive from scratch)

The realigned conservation check (see `docs/balance_demand_conservation_check.md`)
compares the raw ESTO/9th **reference** against this repo's **produced demand**
(`build_aggregated_demand_as_dummy`). On the compressed 20_USA results-update
preflight, base year **2022** shows a `value_mismatch` of exactly **−58.09703 PJ**
for `__all_fuels__` (both Reference and Target scenarios); the synthetic 2023
(`compressed_projection`) reconciles to ~0.

Root cause (verified against `data/00APEC_2024_low_with_subtotals.csv`, economy
20_USA, demand flows, year 2022):

- The dropped items are ESTO **product** codes: `02 Coal products`,
  `15 Solid biomass`, `16 Others` — the bare aggregate parents.
- On flow `16.01.99 Commercial and public services unallocated`, the parent
  product row carries `is_subtotal=False` and a value that **exactly equals the
  sum of its leaf children on the same flow**:
  - `15 Solid biomass` = 30.1565  ==  Σ `15.0x` (30.1565)
  - `16 Others`        = 27.9405  ==  Σ `16.0x` (27.9405)
  - 30.1565 + 27.9405 = **58.0970** = the mismatch.
- So the parent row **is** a subtotal of its children, just mis-flagged
  `is_subtotal=False` in the source file.

Consequences:
- **Produced/LEAP side** maps by product code: it keeps the leaf children and
  drops the unmappable bare parent → each unit counted once → **correct**.
- **Conservation reference** (`_extract_base_year`, which trusts `is_subtotal`)
  keeps **both** the parent and its children → **double-counts by 58.10 PJ**.

Verification oracle in `leap_mappings` (read-only, do not modify):
- `results/tree_structure/esto_tree.csv` marks `15 Solid biomass` / `16 Others` /
  `02 Coal products` as `is_subtotal=True, is_leaf=False` (pure parents).
- `results/tree_structure/common_esto_validation_totals.csv` shows
  `parent_value == children_sum` (difference ≈ 0) for these codes.

Both confirm: these parents are pure subtotals; keeping them out of LEAP is correct
and lossless. The only defect is the reference side counting a mis-flagged parent.

## Current state (confirm before editing)

- `codebase/functions/balance_demand_conservation.py`
  - `build_raw_demand_conservation_reference` — builds the raw reference by
    concatenating `aggregated._extract_base_year` (ESTO base year) and
    `aggregated._extract_projection_years` (9th projection). Rows carry
    `fuel_code` (= ESTO product code / 9th fuel code) and `value`.
  - `_build_raw_source_scope_audit` — records every raw row with `included`
    and `exclusion_reason`; must stay consistent with whatever the reference drops.
- `codebase/aggregated_demand_workflow.py::_extract_base_year` (~line 506) —
  `not_subtotal = ~df["is_subtotal"]` is the exact filter that lets a mis-flagged
  parent leak through. Confirm this is the leak point.

## Required change

1. **Detect non-leaf ("parent") product codes from the data itself** — don't hard-code
   `15/16/02` and don't depend on the `leap_mappings` tree at runtime. Parse the
   leading numeric code token from each product label (e.g. `"15 Solid biomass"` →
   `"15"`, `"15.01 Fuelwood & woodwaste"` → `"15.01"`). A code `c` is a parent if
   any **other** product code present in scope starts with `c + "."`. (So `"15"` is
   a parent because `"15.01"` exists; `"17 Electricity"` stays a leaf if no `"17.xx"`
   product exists.)

2. **Exclude parent-product rows from the conservation reference**, treating them as
   subtotals even when `is_subtotal=False`. Apply this in
   `build_raw_demand_conservation_reference` (post-extraction is fine) so the reference
   keeps only leaf product codes.

3. **Record the exclusion honestly in the scope audit.** In
   `_build_raw_source_scope_audit`, mark these rows `included=False` with
   `exclusion_reason="mis_flagged_parent_subtotal"` (new reason string), so the
   lineage explains *why* the ~58 PJ is not on the reference side.

4. **Keep both sides symmetric.** The produced side already excludes these codes
   (they have no canonical fuel mapping, so they're dropped at mapping). Do **not**
   alter `build_aggregated_demand_as_dummy` output. Instead, add a test asserting the
   produced side contains none of the excluded parent codes, so if a parent code ever
   *does* gain a mapping it surfaces as an explicit failure rather than silently
   re-introducing the double count.

5. **Scope:** the confirmed case is the ESTO base year. Check whether the 9th
   projection side has the analogous pattern (a `subtotal_results=False` parent fuel
   whose value equals its children). The 2023 compressed year already reconciled to
   ~0, so if you find no 9th-side double count, note that and leave the projection
   path unchanged rather than inventing a fix.

## Edge cases

- **Genuine top-level leaves** (e.g. `17 Electricity`, `18 Heat` if they have no
  sub-products in the data) must NOT be excluded — the "has a `c.`-prefixed child"
  test handles this; verify against the real ESTO product set.
- **Deeper nesting** (`16.01` → `16.01.01`) — the rule generalizes: any code with a
  `c.`-prefixed descendant is a parent. Make sure you don't drop a mid-level code that
  is itself a leaf-for-demand with no children present.
- **Do not rely on `is_subtotal` alone** — that flag is exactly what's wrong here.
  The structural parent/child test is the source of truth; `is_subtotal=True` should
  still be excluded as before (union the two rules).

## Verification / acceptance criteria

1. Full `pytest` passes. Add a unit test in `tests/test_balance_demand_conservation.py`:
   a synthetic ESTO frame with a mis-flagged parent (`is_subtotal=False`) whose value
   equals its single child on the same flow → the reference excludes the parent, keeps
   the child, and the scope audit shows `exclusion_reason="mis_flagged_parent_subtotal"`;
   assert both the reference and the produced side drop the same parent and the totals
   reconcile to zero.
2. Re-run the **compressed results-update preflight**
   (`supply_preflight.run_preflight_compressed_results_update`). Confirm the 2022
   `__all_fuels__` rows for 20_USA (Reference and Target) change from
   `value_mismatch (−58.097)` to `match` (within tolerance), 2023 stays `match`, and
   the excluded parents appear in the lineage scope audit with the new reason. (The
   preflight fails later on an unrelated `supply_reconciliation_results.py`
   balance-table lookup for `20_USA/target`; that is pre-existing and out of scope —
   the three conservation CSVs are written before it.)
3. Cross-check the newly-excluded codes against
   `leap_mappings/results/tree_structure/esto_tree.csv` (should be `is_subtotal=True`
   / `is_leaf=False`) and `common_esto_validation_totals.csv` (`parent_value ==
   children_sum`) to prove the exclusion set matches the canonical subtotal set.

## Deliverables

- Edited `balance_demand_conservation.py` (reference builder + scope audit).
- New/updated tests.
- A short note in `docs/balance_demand_conservation_check.md` recording that
  parent-product rows mis-flagged `is_subtotal=False` are excluded from the reference
  to avoid double-counting, verifiable via the `leap_mappings` tree files.
- Do not run the full multi-hour workflow; the compressed preflight is the proof.


