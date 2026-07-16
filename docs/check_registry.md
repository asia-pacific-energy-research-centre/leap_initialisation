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

> Line references are navigation aids verified 2026-07-16. Re-verify with
> `rg <name>` before editing. Some core `codebase/*.py` files carry a UTF-8 BOM —
> read as `utf-8-sig` when scripting over sources (`leap_core.py` does **not**).

## How to use / maintain

- When you add or move any check, add or update its row here.
- Each row records **where** it runs and **which paths cross it**, so you can
  see at a glance whether standalone and orchestrated runs get the same
  treatment.
- The registry does not duplicate the SEED rule detail — for family F2 it points
  at `baseline_seed_rule_inventory.md`.

## The decision rules this registry encodes

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

**C. Severity policy — every check declares one, but the *shape* differs by
family.** Do not impose a single blunt per-producer severity dict everywhere; most
families already have a (better-fitting) mechanism:

| Family | Policy shape | Mechanism | Status |
|---|---|---|---|
| F1 | *impose a default or not* (not block/warn — a fill doesn't "fail") | `FILL_MISSING_DEFAULTS` per measure | **proposed** |
| F2 | rule-level exceptions (narrow, must name `rule_id` + an exact field) + global warnings flag | `validation_exceptions`; `BASELINE_SEED_VALIDATION_BLOCKING_FINDINGS_ARE_WARNINGS` (`supply_leap_io.py:997`) | **exists** — don't add a per-producer waiver on top; LEAP-validity invariants must not be waivable wholesale |
| F3 | per-call tolerance | `raise_on_missing_branch=False` (`supply_leap_io.py:2282`) | **exists** |
| F4 | always block (warn-and-proceed defeats preflight) | — | **n/a by design** |
| F5 | warn by default, one switch to escalate to errors | `CONSERVATION_FAILURES_ARE_ERRORS` + `build_with_conservation_policy` (`functions/conservation_policy.py`) | **exists** (added 2026-07-16 — was the gap) |

**Config placement rule (2026-07-16):** these policies must live in a *centrally
accessible* surface — `supply_reconciliation_config.py` (with a
`# PRESET-CONTROLLED DEFAULT` comment) and overridable per-run from the presets in
`supply_reconciliation_workflow.py` — **not** as literals buried in the producer
module that happens to use them. The repo is not consistent about this yet; new
policy config should follow this rule, and buried literals (e.g. the hardcoded
`strict_conservation=True/False` at `aggregated_demand_workflow.py:878` and
`transfers_workflow.py:605`) should migrate as they are touched.

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
| `prepare_seed_rows_for_write` | `baseline_seed_validation.py:1694` | orchestrates below | **verified 2026-07-16 — three callers:** full-run seed combiner (`supply_leap_io.py:1784`), results verification (`supply_leap_io.py:1000`), patcher (`patch_baseline_seeds.py:940`) |
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
| projection strict conservation | `functions/conservation_policy.py` (`build_with_conservation_policy`), wrapping `build_esto_projection_table` / `allocate_ninth_projection_to_esto` | ESTO projection conserves against the 9th base | ✅ `CONSERVATION_FAILURES_ARE_ERRORS` (warn by default) |
| supply conservation | see `supply_conservation_checks.md` | supply == demand + transformation | — |

### Projection conservation severity — UNIFIED 2026-07-16

**Was:** five call sites disagreeing, with no single place to state the policy —
transformation asset-prep **blocked**; transformation's scenario projection
**warned** (it caught its own `ValueError` and silently re-ran non-strict — a
self-bypassing check); supply **blocked**; aggregated_demand **blocked**
(hardcoded `True`); transfers **never checked** (hardcoded `False`). And
`PROJECTION_STRICT_CONSERVATION = True` was defined **twice**
(`transformation_analysis_utils`, `supply_assets`), kept in manual sync by a
comment.

**Decision:** a conservation failure is a **WARNING by default** — long runs must
not halt on it — and every producer behaves identically. F5 may legitimately warn
where F2 must not (the seed writer's "never let invalid rows through"); the two
families deliberately differ.

**Now:** `functions/conservation_policy.py` owns it.

```python
# functions/conservation_policy.py   (PRESET-CONTROLLED DEFAULT)
CONSERVATION_FAILURES_ARE_ERRORS = False   # True -> raise instead of warn

build_with_conservation_policy(producer, build)   # build(strict_conservation=...)
```

The check is **always attempted with conservation on**; only failure handling
differs, so call sites can no longer choose their own severity. The module
imports stdlib only (no import cycles) and reads the flag at call time so presets
can override it. Guarded by `tests/test_conservation_policy.py`.

Migrated: `transformation_workflow` (its hand-rolled try/except removed),
`supply_assets` (duplicate flag deleted), `aggregated_demand_workflow`,
`transfers_workflow` (**now runs the check for the first time** — if transfers
cannot conserve by construction, exempt it rather than reverting the policy).

**Remaining:** the transformation asset-prep site
(`transformation_analysis_utils.py:1820`) and the last
`PROJECTION_STRICT_CONSERVATION` definition (`:137`) are not migrated — that file
had uncommitted work in progress. It still **blocks**, i.e. errs on the stricter
side. Finish the migration when the file is free.

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
   divergence bites on **direct API imports** (the per-workflow
   `import_*_workbook_to_leap` paths) that bypass the seed writer: there shares
   get equal-split instead of the canonical borrow/anchor, and missing siblings
   are not completed.
   - **DORMANT, not live** (corrected 2026-07-16 — an earlier note in this file
     wrongly escalated this to "live by default"). There are two routes into LEAP:
     **Route A (seed)** — producers → assembled → `prepare_seed_rows_for_write`
     (`supply_leap_io.py:1784`) → `leap_import_baseline_seed_*.xlsx`. Post-boundary.
     This is the **only working route**.
     **Route B (direct API)** — raw per-workflow workbooks →
     `import_*_workbook_to_leap` (`supply_leap_io.py:1265/2274/2314`) → `leap_core`.
     Pre-boundary. **The LEAP API is decommissioned**: `leap_api_guard.py`
     sets `LEAP_API_BLOCKED = True`, and `leap_core.py:202`
     (`ensure_leap_api_allowed` inside `connect_to_leap`) raises `RuntimeError` on
     any API use, while `:168` makes the availability check return `False`. So
     Route B **cannot execute** and the equal-split divergence never reaches LEAP.
   - **RESOLVED 2026-07-16 — Route B is now structurally dead.** Three fixes:
     (a) `LEAP_IMPORT_SUPPLY_TO_LEAP` / `..._TRANSFORMATION_TO_LEAP` /
     `..._TRANSFERS_TO_LEAP` now default **`False`**
     (`supply_reconciliation_config.py`), with the decommission rationale in-file;
     (b) **the real leak**: all five API-import guards in `supply_leap_io.py`
     (`run_other_loss_own_use_proxy_leap_import`,
     `RUN_ELECTRICITY_HEAT_INTERIM_leap_import`, `run_aggregated_demand_leap_import`,
     `run_other_demand_zeroing_leap_import`, `run_results_linked_leap_import`) read
     `get_analysis_input_write_mode() == "api" and not leap_api.is_available()` —
     which is **False in workbook mode**, so workbook runs *fell through and
     attempted every API import anyway*, hitting the guard and swallowing it as a
     WARN. All five now short-circuit on `not leap_api.is_available()` alone,
     decoupled from write mode; (c) `tests/test_leap_api_decommissioned.py` locks
     this in (guard blocked, `is_available()` False, `connect_to_leap()` raises,
     toggles default False, guards not write-mode-coupled, entry points return
     empty). The skeleton stays for a future LEAP fix — clearing
     `LEAP_API_BLOCKED` will fail that test module on purpose, which is the
     deliberate gate to revisit.
   - **If the API is ever re-enabled**, this divergence becomes live again and must
     be converged first. Recorded consequence to test at that point: the raw USA
     transformation export has an all-zero hydrogen Target share group (measured),
     which Route B would equal-split to ~33.3/33.3/33.3 across Ammonia/Efuel/
     Hydrogen instead of Route A's correct Reference-borrowed profile
     (Hydrogen 100→43/26/36, Efuel 0→57/74/64).
   - **Breakpoints: RESOLVED 2026-07-16.** `leap_core.py` had 26 raw `breakpoint()`
     calls (plus 6 commented notes) while the rest of the repo used the guarded
     `esto_data_utils.try_debug_breakpoint()` (`ENABLE_DEBUG_BREAKPOINTS = False`).
     All 26 now route through that shared helper; commented notes left as-is.

4. **Emit-boundary path divergence.** `complete_canonical_share_groups` runs only
   when a path crosses `prepare_seed_rows_for_write` (full run, patcher) — **not**
   for raw standalone workflow exports. This is why a standalone transformation
   export shows USA Target hydrogen output shares as all-zero while the seed
   (post-writer) carries the correct Reference→Target fallback profile. Comparisons
   and gates must always use **post-boundary** output; comparing raw export against
   a finished seed manufactures false differences. (This directly explains the
   transformation-patch gate's premise — see the patch-baseline-seeds work.)

5. **Self-bypassing conservation check (F5) — RESOLVED 2026-07-16.** The
   projection conservation check used to downgrade its own failure to a warning
   and silently re-run non-strict in one producer while three others blocked and a
   fifth never checked, with the strictness flag defined twice. Severity is now
   owned by `functions/conservation_policy.py` (warn by default;
   `CONSERVATION_FAILURES_ARE_ERRORS=True` to raise) and the behaviour is
   identical across producers. See F5 for what remains: the transformation
   asset-prep site (`transformation_analysis_utils.py:1820`) is not yet migrated
   and still blocks.

## Related documents

- [baseline_seed_rule_inventory.md](baseline_seed_rule_inventory.md) — full SEED-C rule detail (F2).
- [special_rules_and_design_decisions.md](special_rules_and_design_decisions.md).
- [supply_conservation_checks.md](supply_conservation_checks.md), [balance_demand_conservation_check.md](balance_demand_conservation_check.md) — F5.
- [prompts/export_zero_fill_consolidation_execution_prompt.md](prompts/export_zero_fill_consolidation_execution_prompt.md) — F1 consolidation plan.
