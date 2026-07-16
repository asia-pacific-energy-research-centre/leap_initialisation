# Check registry

A single directory of every "getting things ready before sending out" check in
the initialisation codebase: readiness checks, structural invariants, and the
default-imposing fill/reset mechanisms.

**Why this exists.** These checks grew independently inside each sub-workflow.
The existing [baseline_seed_rule_inventory.md](baseline_seed_rule_inventory.md)
catalogs one family well (the seed-write validator rules) but answers only
*"what must be true?"* — not *"where is it enforced, and which execution paths
cross it?"*. That second axis is what lets checks silently diverge between the
same workflow run **standalone** vs **within**
`codebase/supply_reconciliation_workflow.py`. A concrete instance is recorded in
[§ Known hotspots](#known-hotspots--gaps) (the transformation-patch hydrogen
episode).

> Line references are navigation aids verified 2026-07-16; some are carried from
> a related session and marked *(reported)*. Re-verify with `rg <name>` before
> editing. 12 core `codebase/*.py` files carry a UTF-8 BOM — read as
> `utf-8-sig` when scripting over sources.

## How to use / maintain

- When you add or move any check, add or update its row here.
- Each row records **where** it runs and **which paths cross it**, so you can
  see at a glance whether standalone and orchestrated runs get the same
  treatment.
- The registry does not duplicate the SEED rule detail — for family F2 it points
  at `baseline_seed_rule_inventory.md`.

## The two decision rules this registry encodes

**A. Boundary vs workflow-local** — where should a check live? Ask five
questions; the more that lean "boundary," the stronger the case:

1. Checkable from `(final rows + template)` alone, or does it need in-flight
   state that's gone by assembly? (former → boundary)
2. Can more than one workflow produce the bad shape? (yes → boundary, else it
   gets copied N times and drifts)
3. Is detection generic but the *fix* domain-specific? (→ boundary detects and
   orchestrates; workflow supplies the fill/fix policy via config/callback)
4. Does it need cross-scenario / cross-module / assembled state? (yes → must sit
   at the post-assembly, per-economy-all-scenarios granularity, never
   per-export-file)
5. Readiness-to-**compute** or readiness-to-**emit**? (never merge preflight
   into the emit boundary)

One-line test: *if someone handed you the workbook with no idea which workflow
made it, could they still check this property? If yes → boundary invariant; if
they'd need to know how it was computed → local.*

**B. Gateability** — may a default-imposing fill be switched off?

> A fill is safe to gate off **only if a boundary invariant catches the bad case
> it would have prevented.** Otherwise the fill *is* the safety net, and gating
> it silently delegates correctness to LEAP's inheritance.

This is why the `BACKING-CHECK` column exists below: gateable ⇔ backing-check is
non-empty.

## The five families

| Family | What it does | Timing |
|---|---|---|
| **F1** Enumeration: gap-fill / reset | invent missing rows (gap-fill) or overwrite existing rows (reset) | pre-emit |
| **F2** Artifact invariants | the emitted rows must satisfy structural rules (shares, IDs, coverage, capacity gate) | at emit boundary |
| **F3** LEAP-import readiness | the workbook will import into LEAP cleanly (region, scenarios, sheets) | post-write |
| **F4** Preflight | inputs are present and current enough to compute | pre-compute |
| **F5** Conservation / numeric | energy balances and activity/target consistency hold | post-compute |

---

## F1 — Enumeration: gap-fill and reset mechanisms

Two behaviourally different kinds. **gap-fill** only touches unset branches;
**reset** overwrites existing values. Note the asymmetry in the `gated-by`
column: the resets already have preserve-originals switches; the gap-fills do
not. Some fills are **structural** (LEAP rejects the import without them → always
on); others are **optional** placeholders a researcher may prefer LEAP to inherit
(→ gateable, once backed by a check).

| Mechanism | Location | Kind | Measures | structural / optional | gated-by | BACKING-CHECK |
|---|---|---|---|---|---|---|
| `build_aux_fuel_zero_rows` | `transformation_record_builder.py:2180` | gap-fill | Output/Feedstock/Process Share | **structural** | always-on | F2 capacity-guard (SEED-C009/C011/C013) |
| ″ | ″ | gap-fill | Aux Fuel Use, Import/Export Target, Historical Production, Exogenous Capacity, **Process Efficiency** | optional | ❌ none | **⚠ NONE for Process Efficiency** (see hotspots); others unverified |
| `add_zero_rows_for_unset_values` | `other_loss_own_use_proxy_utils.py:2225` | gap-fill | Activity Level, Final Energy Intensity | optional | ❌ none | none |
| `build_demand_zeroing_rows` / `save_demand_zeroing_workbook` | `aggregated_demand_workflow.py:1463` / `:1553` | **reset** | blanket-zero non-share `Demand\` | optional | ✅ `ZERO_OTHER_DEMAND_BRANCHES_FROM_EXPORT` + `..._INCLUDE_IN_LEAP_IMPORT` | excludes agg-demand + own-use prefixes (SEED-C023) |
| `reset_supply_and_transformation_import_export_to_zero` | `supply_reconciliation_tables.py:1741` | **reset** | supply/transformation Import/Export Target | optional | ✅ `RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT` | — |
| `_zero_years_outside_range` | `electricity_heat_interim_workflow.py:230` | gap-fill (zero) | zero values outside scenario window | structural | always-on | SEED-C017 (year-window) |
| `_zero_small_numeric_values` | `supply_reconciliation_balance_tables.py:481` | normalize | clamp near-zero to 0 | structural | always-on | — |
| `_backfill_base_year_activity_from_projection` | `other_loss_own_use_proxy_utils.py:1187` | gap-fill | base-year Activity from projection | optional | ❌ none | pre-base-year consistency notice (diagnostic) |
| `_zero_data_expression_for_scenario` | `other_loss_own_use_proxy_utils.py:2210` | helper | build zero `Data()` series | n/a | n/a | — |

**Header-parsing drift** (same full-model export, three readers — consolidate
into one loader): `load_export_key_table`
(`other_loss_own_use_proxy_utils.py:2100`, hardcodes `header=2`),
`build_demand_zeroing_rows` (header scan), `_read_leap_data` in
`supply_leap_io.py` (`write_per_economy_combined_workbooks`). Tracked by
[export_zero_fill_consolidation_execution_prompt.md](prompts/export_zero_fill_consolidation_execution_prompt.md).

**Proposed fill-policy surface** (design, not yet built): a per-measure
`FILL_MISSING_DEFAULTS` dict threaded as a function parameter into the gap-fill
functions, so optional fills can be switched to "let LEAP inherit" without
touching structural anchors. Long-term home is the shared `export_zero_fill.py`
module. Do not add a gate for a measure until its `BACKING-CHECK` is non-empty
(rule B).

---

## F2 — Artifact invariants (the emit boundary)

The boundary is `prepare_seed_rows_for_write`
(`baseline_seed_validation.py:1683`), which runs ID enrichment → duplicate
resolution → `complete_canonical_share_groups` → validation. Full detail of the
rules lives in [baseline_seed_rule_inventory.md](baseline_seed_rule_inventory.md)
(SEED-C001–C029). Summary of the enforcing functions and, crucially, **which
paths cross the boundary**:

| Check / function | Location | Rule(s) | Crossed by |
|---|---|---|---|
| `prepare_seed_rows_for_write` | `baseline_seed_validation.py:1683` | orchestrates below | full-run seed assembly; **patcher** (`patch_baseline_seeds.py:940`) |
| `resolve_logical_duplicates` | `baseline_seed_validation.py` | SEED-C001–C004 | ″ |
| `enrich_seed_ids_from_template` | `baseline_seed_validation.py` | SEED-C005–C006, C020 | ″ |
| `complete_canonical_share_groups` | `baseline_seed_validation.py:817` | SEED-C008–C014 | ″ |
| `_zero_capacity_is_explicit` (capacity-guard) | `baseline_seed_validation.py:745` | SEED-C009/C011/C013 | ″ |
| `_validate_shares` | `baseline_seed_validation.py:1112` | SEED-C008/C010/C012 | ″ |
| `_validate_canonical_share_completeness` | `baseline_seed_validation.py:1173` | SEED-C014 | ″ |
| `check_producer_coverage` | `baseline_seed_validation.py:383` | SEED-C018 (SEED-012) | ″ |
| `validate_exception_records` | `baseline_seed_validation.py:1473` | SEED-C007/C022 | ″ |
| `validate_seed_files` | `patch_baseline_seeds.py:453` | post-write file check | patcher |

**Duplicated / divergent implementations of F2 (drift risk):**

- `_assert_atomic_canonical_share_groups` (`patch_baseline_seeds.py:112`) —
  re-implements a share-group atomicity check outside the boundary.
- `_fill_ids_from_template` (`patch_baseline_seeds.py:427`) — a second ID fill
  distinct from `enrich_seed_ids_from_template`.
- **`_normalize_share_columns_wide` (`leap_core.py:2304`) + `_fill_from_df`
  (`leap_core.py:2444`)** — share/ID normalization that runs at **LEAP-import
  time**, i.e. a *second, different* implementation of the same invariants one
  stage downstream of the seed writer. **Untracked divergence — same class of
  bug as the hydrogen episode, one stage further down.**
- `check_scenario_and_region_ids` (`leap_excel_io.py:681`).

---

## F3 — LEAP-import readiness

Mostly already centralized (good) — thin per-workflow wrappers delegate to a
shared implementation.

| Check | Central impl | Wrappers / notes |
|---|---|---|
| region present in export | `leap_exports.validate_region` (`leap_exports.py:106`) | `validate_export_region` in transformation:562, transfers:999, hydrogen:555, workflow_common:733, supply_export_io:116 — **thin delegates, not duplication** |
| region injected if missing | `ensure_region_in_export` | transformation:678, transfers:1195, hydrogen:661 |
| all target scenarios present (copy fallback) | `_ensure_export_contains_scenarios` (`refining_workflow.py:122`) | copies from a source scenario when one is missing |
| Current Accounts scenario present | `_ensure_current_accounts_scenario` (`supply_reconciliation_balance_tables.py:516`) | |
| manual-import workbook shape | `validate_workbook_for_manual_import` (`analysis_input_write_dispatcher.py:464`), `_validate_workbook_structure_against_canonical` (`:298`) | |
| power-interim fuel/sector coverage | `validate_power_interim_fuel_coverage` (`electricity_heat_interim_workflow.py:582`), `validate_power_interim_sub1sectors` (`:133`) | |

---

## F4 — Preflight (pre-compute readiness)

Different timing from the emit boundary — these guard **inputs**, not outputs.
Do not fold into F1/F2.

| Check | Location | Guards |
|---|---|---|
| compressed-projection preflight | `supply_preflight.py:1278` (`run_preflight_compressed_projection`) | reduced/compressed source files build cleanly before a full run |
| compressed results-update preflight | `supply_preflight.py:1852` (`run_preflight_compressed_results_update`) | results-update inputs before the update pass |
| balance/demand issue report | `supply_preflight.py:1735` (`_finalize_balance_demand_issue_report`) | bridges preflight into F5 conservation reporting |
| reset-scope resolution | `supply_preflight.py:570` (`_load_reset_scope_from_full_model_export`), `:657`, `:682`, `:713` | reset module/fuel scope is resolvable from the export |
| capacity-priority coverage | `supply_reconciliation_allocation.py:581` (`_validate_capacity_priority_coverage`) | every capacitied process has a priority |
| fuel-catalog currency | `fuel_catalog_preflight.py` (`ensure_fuel_catalog_current:486`, `_validate_probe_vs_full_model:300`) | LEAP probe vs full-model export |
| projected base-year coverage | `industry_fuel_remap.py:371` (`_validate_projected_base_year_coverage`) | base-year data present after projection |
| results-update readiness | `supply_reconciliation_workflow.py` (~1021–1029) | fresh LEAP balance workbooks exported before update pass |
| level-2 export readiness | see `project_level2_export_requirement` memory | level-2 branches exported before dependent step |

---

## F5 — Conservation / numeric consistency

Numerical (not structural) checks. Documented separately in
[supply_conservation_checks.md](supply_conservation_checks.md) and
[balance_demand_conservation_check.md](balance_demand_conservation_check.md).

| Check | Location | Verifies | gated-by |
|---|---|---|---|
| proxy activity/target consistency | `other_loss_own_use_proxy_workflow.py:935` (`validate_proxy_activity_target_consistency`) | proxy activity matches target energy | — |
| balance/demand conservation | `functions/balance_demand_conservation.py` (`build_raw_demand_conservation_reference:86`, `build_balance_demand_conservation_breakdown:242`, `..._lineage:358`, `..._diagnostics:516`) | raw vs resolved demand totals reconcile per sector/product/year | reporting/diagnostic |
| projection strict conservation | `core.build_esto_projection_table(strict_conservation=...)` | ESTO projection conserves against the 9th base | ✅ `PROJECTION_STRICT_CONSERVATION` (transformation), `strict_conservation=True` (aggregated_demand:878), `False` (transfers:605) |
| supply conservation | see `supply_conservation_checks.md` | supply == demand + transformation | — |

**⚠ The projection strict-conservation check is self-bypassing.**
`transformation_workflow.py:198-223` calls `build_esto_projection_table` with
`strict_conservation=core.PROJECTION_STRICT_CONSERVATION`, and on `ValueError`
prints `[WARN] Projection strict-conservation check failed … retrying non-strict`
then **re-runs with `strict_conservation=False` and merges that result**. So
setting `PROJECTION_STRICT_CONSERVATION=True` guarantees only a *warning* on
failure — the unchecked projection still reaches the output. Note this
contradicts the seed-writer philosophy documented in
`baseline_seed_rule_inventory.md` ("Deferring an exception never permits invalid
rows to reach a final LEAP import workbook"). Decide which philosophy applies and
make it explicit.

The `strict_conservation` setting is also inconsistent across producers:
aggregated_demand hardcodes `True`, transfers hardcodes `False`, transformation
reads config then falls back to `False`. That asymmetry looks unintentional —
confirm before consolidating.

---

## Known hotspots / gaps

1. **F1 gap-fills are ungated; resets are gated.** The three gap-fills
   (transformation aux/measures, own-use activity/intensity, own-use backfill)
   have no preserve-originals switch, unlike the two resets. Proposed fix:
   per-measure `FILL_MISSING_DEFAULTS` (see F1).

2. **⚠ Process Efficiency fill has no backing invariant.**
   `baseline_seed_validation.py` contains **zero** references to "Efficiency".
   The share fills are backed by the capacity-guard, but nothing catches
   "nonzero Exogenous Capacity, no Process Efficiency". Per rule B this fill is
   **not safe to gate** as-is — if it is ever made optional, pair it with a new
   capacitied-process-must-have-efficiency invariant (mirroring the share
   capacity-guard). Arguably worth adding regardless, since the fill is currently
   the only safety net.

3. **F2 has a second, divergent implementation in `leap_core`** (checked
   2026-07-16). `_normalize_share_columns_wide` (`leap_core.py:2304`) runs at
   LEAP-import time and **differs** from the seed writer's
   `complete_canonical_share_groups`: for an all-zero share group it splits
   **equally** across existing siblings (`target/valid_count`) rather than
   borrowing a donor scenario's profile; it does **not** add missing canonical
   siblings from the template; and it has no capacity-conflict guard. Impact is
   bounded — it only acts when a group's total ≠ target (tol 1e-3), so it is a
   no-op for anything already through the seed writer (which sums to 100). The
   divergence bites only on **direct standalone→LEAP imports** (the per-workflow
   `import_*_workbook_to_leap` paths) that bypass the seed writer: there shares
   get equal-split instead of the canonical borrow/anchor, and missing siblings
   are not completed. Converge or document; add a test if that import path feeds
   production.
   - **Bonus bug:** `_fill_from_df` has two live `breakpoint()` calls
     (`leap_core.py:2452`, `:2457`) in the empty-scenario/region error path — pdb
     left in production; a non-interactive import with an empty filter would drop
     into pdb (hang/fail) instead of raising cleanly.

4. **Emit-boundary path divergence.** `complete_canonical_share_groups` runs only
   when a path crosses `prepare_seed_rows_for_write` (full run, patcher) — **not**
   for raw standalone workflow exports. This is why a standalone transformation
   export shows USA Target hydrogen output shares as all-zero while the seed
   (post-writer) carries the correct Reference→Target fallback profile. Comparisons
   and gates must always use **post-boundary** output; comparing raw export against
   a finished seed manufactures false differences. (This directly explains the
   transformation-patch gate's premise — see the patch-baseline-seeds work.)

5. **Self-bypassing conservation check (F5).** The projection strict-conservation
   check downgrades its own failure to a warning and re-runs non-strict
   (`transformation_workflow.py:198-223`), so the unchecked projection reaches the
   output. Its `strict_conservation` setting is also inconsistent across producers
   (aggregated_demand `True`, transfers `False`, transformation config-then-`False`).
   This contradicts the seed-writer's "never let invalid rows through" philosophy —
   pick one and make it explicit. See F5.

## Related documents

- [baseline_seed_rule_inventory.md](baseline_seed_rule_inventory.md) — full SEED-C rule detail (F2).
- [special_rules_and_design_decisions.md](special_rules_and_design_decisions.md).
- [supply_conservation_checks.md](supply_conservation_checks.md), [balance_demand_conservation_check.md](balance_demand_conservation_check.md) — F5.
- [prompts/export_zero_fill_consolidation_execution_prompt.md](prompts/export_zero_fill_consolidation_execution_prompt.md) — F1 consolidation plan.
