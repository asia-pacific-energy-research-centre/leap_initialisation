# Prompt: Realign the balance-demand conservation check to an internal ESTO/9th target comparison

## Goal in one sentence

Make the balance-demand conservation check always answer **one** question — *"do the demand totals this repository produces match the ESTO + 9th Outlook totals we are trying to build them to match?"* — and make it answer that question the **same way in both `baseline_seed` and `results_update` modes**, never by comparing against the LEAP balance readback.

Keep everything already built (breakdown CSV, lineage CSV, totals diagnostic CSV, scope audits, value classifications). This is a **realignment of what the "actual" side is compared against**, not a rewrite.

## Why (read this so you don't reintroduce the problem)

There are two genuinely different questions, and the current check blurs them:

1. **Did our own code conserve energy?** raw ESTO/9th demand → the demand this repo builds and hands to LEAP. A mismatch here is *our* bug (dropped row, bad mapping, double count). It should be ~zero. **This is the conservation check.**
2. **Did LEAP produce the balance we expected?** our estimate vs the LEAP balance we read back. A mismatch here is *expected and normal* — rebalancing is the whole point of reconciliation. This is already covered by the convergence metrics and the dashboard. **This is NOT conservation and must not live in this check.**

In `results_update` mode the "resolved/actual" side of the current check is sourced from the LEAP readback (`load_balance_demand_inputs` → `sector_demand_table`), so the check is contaminated with question 2. The result is a mismatch number that can't tell you whether *you* made a mistake, because LEAP is *supposed* to change the numbers.

`baseline_seed` mode already does the right thing (compares our source against our own built demand). The task is to make `results_update` behave the same way.

## Current state (verified locations — confirm before editing)

- `codebase/functions/balance_demand_conservation.py` — all the builder functions:
  `build_raw_demand_conservation_reference` (reference = raw ESTO/9th ✅ keep as the target),
  `prepare_reconciliation_demand_totals` / `prepare_reconciliation_sector_demand_totals` (build the "resolved/actual" side),
  `build_balance_demand_conservation_diagnostics` (totals CSV),
  `build_balance_demand_conservation_breakdown`, `build_balance_demand_conservation_lineage`.
- `codebase/functions/supply_results_saver.py` ~lines 2748–2890 — where the check is wired and the three CSVs are written:
  - `supply_reconciliation_balance_demand_conservation.csv` (totals diagnostic)
  - `supply_reconciliation_balance_demand_conservation_breakdown.csv`
  - `supply_reconciliation_balance_demand_conservation_lineage.csv`
- The "actual" side today flows from `sector_demand_table` through `prepare_reconciliation_sector_demand_totals`. **Trace where `sector_demand_table` comes from in each mode** (`load_results_sector_demand_table` in `supply_reconciliation_tables.py`, and `load_balance_demand_inputs` in `supply_demand_mapping.py`). Confirm that in `results_update` it derives from the LEAP balance export, and in `baseline_seed` it does not. Base your change on what you actually find, not on this description.

## Required change

1. **Define the "actual" side as the reconciliation process's own produced demand**, consistently in both modes — the demand this repo builds and would write into the LEAP import workbook (the aggregated-demand placeholder plus any detailed sector rows the workflow itself generates). This is the same family of data `baseline_seed` already uses. **Do not** source the conservation "actual" side from `load_balance_demand_inputs` / the LEAP-derived `sector_demand_table`.

2. **Keep the reference/target side exactly as is**: `build_raw_demand_conservation_reference` (independent ESTO + 9th totals). This is the thing we are trying to match.

3. **Totals-first.** The headline check is the totals diagnostic (`build_balance_demand_conservation_diagnostics`): compare produced-demand totals vs ESTO/9th totals by `economy / scenario / year` (and by product where already supported), with the existing tolerance and `status` / `is_mismatch` fields. This is the pass/fail signal.

4. **Keep the row lineage** (`build_balance_demand_conservation_lineage`) and breakdown as the optional drill-down. Relabel any stage names / `mapping_status` / `value_classification` values that currently imply "LEAP balance" on the actual side, so the lineage honestly reflects that the actual side is now *our produced demand*, not a LEAP readback. Do not invent cross-stage links that were not retained (the existing code is already careful about this — preserve that honesty).

5. **Unify the two modes.** After the change, `baseline_seed` and `results_update` should build the conservation inputs the same way. If a mode difference remains (e.g. which detailed sectors are in scope), it must be a *scope* difference expressed through the existing `excluded_sectors` / scope-audit machinery, not a difference in *which dataset the actual side comes from*.

## Keep unchanged / out of scope

- Do **not** change `leap_mappings` in this task.
- Do **not** build a "did LEAP receive what we sent" round-trip check here. If that is wanted later it is a *separate* artifact with a different name; it must never be folded into this conservation check (its answer is not expected to be zero).
- Do not remove or rename the three existing output CSVs or their columns unless a rename is strictly required by point 4; if you must, keep backward-compatible columns where cheap.
- Preserve the existing scope-audit outputs and the `exact / allocated / estimated / excluded / untraceable` value classifications.

## Edge cases to handle

- **Compressed synthetic year.** The compressed results-update preflight fabricates a signed-sum synthetic `BASE_YEAR + 1`. Label such years `year_type = compressed_projection` (or equivalent) in the outputs so a synthetic total is never read as a real annual balance. Confirm whether this label already exists; add it if not.
- **Scenario/exclusion consistency.** The reference side and the actual side must apply the *same* scenario set and the *same* sector exclusions (`conservation_exclusions`), or the totals will diverge for reasons that are not conservation failures. This is already threaded through the current code — keep both sides aligned after the swap.
- **Preserve the "already modelled" exclusion (do not regress this).** The aggregated-demand branch deliberately excludes sectors that are already represented as active detailed demand branches, via `resolve_effective_aggregated_demand_exclusions` (→ `resolve_active_branch_excluded_sectors`, keyed off `DETAILED_DEMAND_BRANCHES_ACTIVE` / `AGGREGATED_DEMAND_EXCLUDED_SECTORS`). This exclusion must continue to apply, and it must apply to the **new** produced-demand "actual" side exactly as it does to the ESTO/9th reference side. When you swap the actual side away from the LEAP-derived `sector_demand_table`, re-apply the identical `conservation_exclusions` set to whatever now sources the actual side, or the check will report the excluded sectors as spurious mismatches. Add a test that turns an exclusion on and proves both sides drop the same sectors and the totals still reconcile.
- **Fan-out / allocation.** Where one source row maps to many products, do not let an original source value be counted more than once. Totals must reconcile; component/contribution values (not repeated original values) are what sum in the detail view.

## Verification / acceptance criteria

1. Full test suite passes (`pytest`). Update `tests/test_balance_demand_conservation.py` and add cases proving:
   - the actual side is built from produced demand, **not** from a LEAP balance input, in both modes;
   - totals reconcile to within tolerance on a controlled fixture where conservation genuinely holds;
   - an injected leak (dropped/duplicated row) is caught and localized by the breakdown.
2. Run the **compressed results-update preflight** and confirm all three CSVs are written and the totals diagnostic reports conservation of *our* produced demand against ESTO/9th (not a LEAP-vs-us gap). The synthetic 2023 must be labelled as a compressed projection year.
3. The totals check is the pass/fail; lineage remains an inspectable drill-down.
4. State plainly in the run output / a short doc note that this check no longer involves the LEAP balance readback.

## Deliverables

- Edited `balance_demand_conservation.py` and `supply_results_saver.py` (and any table-loader used to source produced demand).
- Updated tests.
- A short note in `docs/balance_demand_conservation_check.md` describing the realigned semantics (internal target comparison, both modes identical, LEAP readback explicitly excluded, lineage retained as drill-down).
- Do not run the full multi-hour workflow; the compressed preflight is the integration proof.

---

## Follow-up work (do AFTER the demand realignment lands — do not start these in the same change)

Once the demand check is realigned and green, extend the *same* internal-conservation pattern to the other two sides, **within `baseline_seed` mode** (never against the LEAP readback, for the same reason). Structure the demand realignment so these can reuse its breakdown / lineage / scope-audit / value-classification helpers rather than each reinventing them.

1. **Supply (easy — it's an upgrade, not a new build).** A baseline totals conservation check already exists: `codebase/functions/supply_conservation.py` → `build_baseline_supply_source_preservation` compares pre-mapping ESTO/9th flow totals (production / imports / exports) against the mapped baseline supply tables, per `economy / flow / year`, with the same `tolerance_pj` / `status` / `is_mismatch` framework. The task is to add the breakdown + row-lineage + value-classification layer on top of it so it matches the demand check's shape. **Do not** conflate it with `build_results_update_closure_diagnostics` in the same file — that recomputes the supply/demand balance residual in results_update and is a different check.

2. **Transformation (new build — needs one design decision first).** No equivalent module exists yet. Transformation is not a single flow total: it has feedstock **inputs**, **outputs**, and **own-use/losses** tied by efficiencies. Decide the conserved quantity before building:
   - *v1 (ship first):* conserve transformation **output** totals per module/fuel — our built output vs ESTO/9th transformation-sector output totals. Directly analogous to demand/supply.
   - *v2 (later):* conserve the full **input − output − loss** identity per module, which actually verifies the transformation logic. This overlaps with the `other_loss_own_use_proxy` split (documented in `supply_reconciliation_workflow.py`), so account for which losses are proxied vs embedded.

Recommended order: demand realignment → supply upgrade → transformation v1.

## Cross-repo consistency with `leap_mappings` (align conventions, don't diverge)

`leap_mappings` has already built the same *"compare two independently-derived totals and explain the gap without fabricating allocation"* pattern one layer upstream, and it is mature and well-tested. Mirror its proven conventions so the two repos read the same way. Reference implementation: `leap_mappings/codebase/mapping_tools/reconcile_anchor_validation.py` and its test `leap_mappings/tests/test_anchor_contribution_breakdown.py`.

Adopt these specific conventions in the leap_initialisation check (harmonize the existing vocabulary toward them where cheap; note deviations you keep and why):

- **Two independent sides, different sources.** leap_mappings is explicit that `raw_parent_total` (raw source) and `converted_boundary_total` (converted output) are read from *different files* so the check is not a tautology. Our realignment already matches this (ESTO/9th reference vs produced demand) — keep that framing and state it.
- **Status vocabulary.** leap_mappings uses `passed` / `failed` / `unanchorable` with a `reason`, and treats an *empty* validation as `failed`, never a silent pass. Harmonize our `status` toward this (today the demand diagnostic uses `match` / `missing_resolved` / `unexpected_resolved` / `value_mismatch`); at minimum add the "empty is not a pass" rule.
- **Deterministic content-derived IDs + schema version.** leap_mappings' `check_id()` hashes the semantic key plus a `BREAKDOWN_SCHEMA_VERSION` constant, explicitly *not* a cache-local row index. We already have `_deterministic_row_ids`; add a schema-version constant to our breakdown/lineage outputs the same way so schema changes are visible and IDs stay stable across runs.
- **Honest, no-allocation fan-out handling ("Option A").** For a source that fans out to many targets (or a target fed by many sources) where no allocation share was retained, do **not** fabricate a per-edge split. List it one-sided and flag it (`unsafe_unallocated_fanout` / `unsafe_many_to_one`), exactly as leap_mappings does. Our lineage already refuses to invent cross-stage links — extend that to explicit fan-out flags with matching names.
- **Count-once guard + self-proving remainder.** leap_mappings emits `counting_role` (`resolved_pair` / `raw_source` / `converted_component`) so every source and component appears exactly once and the column sums equal the two compared totals; its summary carries `breakdown_remainder` (must be ~0) and `fully_attributed` / `lineage_complete` flags proving the breakdown reproduces the headline difference and adds no new numeric observation. Add the equivalent self-proof to our breakdown: a per-group remainder column asserted (in tests) to reproduce the totals diagnostic's difference, and a flag for whether every contributor was attributed per row vs only in aggregate.
- **Value-quality vocabulary.** Harmonize toward a shared set — leap_mappings uses `exact_direct` / `unknown` (+ `resolved`); we use `exact_aggregated` / `allocated` / `estimated`. Converge on one glossary across both repos (a short shared table in each repo's docs is enough) so `exact` / `allocated` / `estimated` / `unanchorable` mean the same thing on both sides.

Do **not** try to unify the two codebases into shared code in this task — they map different vocabularies (source→ESTO in mappings; source→produced-demand in initialisation). The goal is *matching conventions and output semantics*, so a reviewer moving between the two repos reads one consistent method. Capture the agreed glossary/status/ID conventions in `docs/balance_demand_conservation_check.md` and cross-link `leap_mappings/docs/mappings_system.md`.
