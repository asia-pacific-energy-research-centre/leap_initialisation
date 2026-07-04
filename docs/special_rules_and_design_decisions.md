# Special rules and design decisions

This is the decision log for `leap_initialisation`. Record rules whose correct behaviour cannot be derived from source data, canonical configuration, or the established model structure. Keep implementation details in code documentation. Update an existing entry and its history rather than creating a duplicate.

Cross-repository decisions use a `CROSS-###` ID and have one authoritative entry in the repository that owns the implementation. Other affected repositories should link to that entry instead of copying it.

## INIT-001: Aggregate fuel labels are not LEAP template branches

**Status:** Confirmed
**Owner:** leap_initialisation
**Type:** Exception
**Affected areas:** `codebase/functions/patch_baseline_seeds.py`; `VALIDATION_IGNORE_FUEL_NAMES`; baseline seed validation output

### Situation

Some 9th Outlook aggregate fuel labels can reach baseline seed generation even though they are not real LEAP branches. Treating them as ordinary unknown paths creates false validation failures; ignoring every unknown path would hide genuine model/template gaps.

### Options

- Fail validation for every unknown fuel path.
- Ignore all unknown paths.
- Ignore only explicitly reviewed aggregate labels that are not branches in any sector.

### Current rule

Use an explicit allowlist. The current labels are `Biomass`, `Coal`, `Gas`, `Others`, and `Municipal solid waste non and renewable`. `Solar` is not ignored: unallocated solar codes must be remapped to `Solar nonspecified` before validation.

### Validation

Confirm ignored rows end only with an allowlisted label. Review every other unknown path as a possible workflow or template defect. When the allowlist changes, run seed validation against the full model export and compare ignored-row counts and fuel totals before and after.

### History

- 2026-06-27: Recorded the existing baseline seed validation exception.

## INIT-002: LEAP transformation balancing defaults and exceptions

**Status:** Confirmed
**Owner:** leap_initialisation
**Type:** Modelling
**Affected areas:** LEAP transformation shortfall/surplus rules; Resources `Unmet Requirements`; module ordering; `docs/supply_reconciliation_workflow_guide.md` section 12b; reconciliation imports and exports

### Situation

LEAP can produce technically valid balances through different combinations of transformation imports, domestic Resources supply, exports, unmet requirements, and module ordering. Source balances do not determine which route represents the intended model behaviour.

### Options

- Resolve shortfalls inside transformation modules with `ImportToMeetShortfall`, which can bypass intended domestic supply routes.
- Pass shortfalls upstream with `RequirementsRemainUnmet` and close tradeable-fuel gaps at Resources.
- Keep surpluses in the domestic pool, export them, or explicitly waste them; each choice changes reported supply and trade.

### Current rule

Default transformation shortfalls to `RequirementsRemainUnmet`, with tradeable-fuel Resources set to `MeetWithImports`. Use `ImportToMeetShortfall` only for an explicitly intended import-backed route and normally on at most one module per fuel. Default surpluses to `SurplusAvailable`; use `SurplusExported` only for realistic export routes such as reviewed refinery co-products, and `SurplusWasted` only for explicit curtailment, flaring, or dumping. Review module order together with these settings.

### Validation

After each LEAP recalculation, compare production, transformation inputs/outputs, imports, exports, and unmet requirements by fuel. Check that no fuel has competing import-backed modules and that module exports plus planned Resources exports do not inflate total exports. Record economy- or module-specific exceptions as new entries or configuration.

### History

- 2026-06-27: Recorded the balancing rules documented in the workflow guide.

## CROSS-001: Full-model export and LEAP import ID integrity

**Status:** Confirmed
**Owner:** leap_initialisation
**Type:** Operational invariant
**Affected areas:** `data/full model export.xlsx`; baseline-seed generation and validation; transformation reset scope; supply root classification; `leap_mappings` LEAP hierarchy maintenance

### Situation

Generated workbooks address LEAP through readable keys and model-specific IDs. A stale full-model export can leave a real branch unmatched, attach stale IDs, omit new fuel leaves from reset scope, or misrepresent the LEAP hierarchy used by mapping maintenance. Duplicate logical keys can also conceal conflicting expressions, especially when one copy has valid IDs and another has `-1` sentinels.

### Options

- Treat branch names alone as sufficient and tolerate unresolved IDs.
- Reject only nonzero rows with `BranchID=-1`.
- Require a current structural export, unique logical keys, and valid required IDs for final import rows, with explicit review of any proven no-op exception.

### Current rule

Use `data/full model export.xlsx` as the canonical LEAP structure and ID reference. Refresh it after any branch, variable, scenario, Resources-root, process, or fuel-leaf structural change, including deletion and recreation of a branch with the same name. Numerical changes alone do not require refresh.

The logical key `Branch Path + Variable + Scenario + Region` must be unique in a final import workbook. Exact duplicates can be removed deterministically. For conflicting duplicates, a sole row with all four valid IDs is selected only to support diagnostics; the physical duplicate group still blocks final import until corrected. Multiple valid-ID conflicts and possible insufficient-key cases are never resolved from workbook row order. Duplicate resolution must precede share validation.

A `-1` sentinel is acceptable only in an intermediate row or an explicitly reviewed no-op that will not be relied on for import. Nonzero missing-ID rows are errors; zero-valued missing-ID rows must also be reviewed when they are intended to reset existing values. Validate all required ID columns, not only `BranchID`.

### Validation

After refreshing the export, compare its branch paths and IDs with the archived version; rebuild catalog/reset scope; run unknown-path, metadata, duplicate-key, and missing-ID checks; validate share totals after duplicate resolution; and compare new baseline seeds with the last accepted set. Rules `SEED-001` through `SEED-005` and `SEED-011` automate the import-integrity checks. The detailed lifecycle and required export contents are documented in `data/README.md`.

Missing-ID rows remain blocking by default, including zero resets. The final
writer accepts an optional exact-match exception list for a specifically
reviewed rule and measure/logical key. Broad rule-only exceptions are invalid,
and no production missing-ID exception is currently configured. An exception
does not make a `-1` row effective in LEAP.

### History

- 2026-06-27: Defined order-independent duplicate classification and required duplicate resolution before share validation.
- 2026-06-27: Recorded the full-model export lifecycle, ID sentinel rules, duplicate-key requirement, and cross-repository mapping dependency after reviewing the June 2026 USA baseline backup.
- 2026-06-28: Added a narrow rule-and-key exception mechanism for explicitly reviewed findings; missing-ID zero resets continue to block by default.

## INIT-003: Share group invariants

**Status:** Confirmed
**Owner:** leap_initialisation
**Type:** Baseline seed validation
**Affected areas:** transformation workbook generation; `codebase/functions/baseline_seed_validation.py`; `codebase/baseline_seed_comparison_workflow.py`

### Situation

LEAP Output Share, Process Share, and Feedstock Fuel Share rows allocate one parent quantity across sibling branches. Duplicate physical rows, missing expressions, or a fallback applied at the wrong hierarchy can make the apparent sum invalid or can double-count an otherwise valid allocation.

### Options

- Sum every physical workbook row, which double-counts duplicate logical keys.
- Select the last workbook row, which makes results depend on row order and may select a `-1` sentinel row.
- Resolve duplicate logical keys deterministically, then validate each parent, variable, economy/region, scenario, and year group.

### Current rule

Use the third option. Every Output Share, Process Share, and Feedstock Fuel
Share group owned and written by a producer must contain the complete set of
canonical sibling rows from `data/full model export.xlsx`. Write an explicit
zero for every unused canonical sibling for every applicable scenario and
year; this applies to each of the three share measures, not only Output Share.
The template supplies the sibling structure and canonical IDs, while ESTO or
9th Outlook data supplies the genuine values.

After duplicate resolution, normalize genuine non-negative sibling values to
exactly 100% whether their source total is below or above 100%. An isolated
all-zero year copies the nearest genuine profile from the same group. Only when
the group has no genuine sibling values in any configured year may a synthetic
100% anchor be considered, and it should normally be used only when the
relevant Exogenous Capacity is explicitly zero. Any exception to the
zero-capacity condition must be documented in producer configuration.
Before falling back to a synthetic anchor, a group with no genuine values in a
scenario borrows the normalized profile from the same group in another scenario
(donor priority Reference, Current Accounts, Target; nearest-year mapping),
still gated on explicit zero capacity. Zero-skeleton process records likewise
borrow inert technology measures (efficiency, auxiliary/own-use ratios) from a
donor scenario via `borrow_zero_skeleton_measures`.
When no donor exists and no producer-specific fallback is configured, select
the alphabetically first canonical branch path. This is deterministic and must
not depend on workbook row order. No capacity exception is currently approved.

Missing or unparseable share expressions and conflicting duplicate groups block import. A one-leaf active group must therefore be 100%. The validator does not infer required scenarios or years from a reference workbook; callers provide those windows explicitly.

### Validation

Run rules `SEED-006`, `SEED-007`, and `SEED-008`. Review duplicate findings
first, then compare the resolved group with the canonical sibling set before
checking its annual totals. Validation must reject an omitted canonical
sibling, a missing explicit zero, a partial-group patch, or a fallback applied
without the required capacity evidence.

### History

- 2026-06-27: Confirmed the three share-group invariants and separated them from unresolved zero-activity and fallback-fuel choices.
- 2026-06-28: Required complete canonical sibling groups with explicit zero rows for unused siblings across every generated share measure; confirmed normalization above or below 100%, nearest-profile reuse for isolated zero years, and the zero-capacity constraint on wholly synthetic groups.
- 2026-06-28: Implemented template-driven completion for Output, Process, and Feedstock shares; deterministic alphabetical fallback is permitted only with explicit zero capacity, and partial share-group patches block.
- 2026-07-03: Zero-skeleton records now carry the full branch/variable key set (scenario-coverage symmetry, SEED-010). All-zero share groups borrow the donor scenario's genuine profile before the synthetic anchor, and zero-skeleton records borrow inert efficiency/auxiliary measures from a donor scenario (user decision, Finn: prefer real profiles over defaults when a scenario legitimately has zero activity, e.g. USA Target hydrogen).

## INIT-004: Do not use 9th Outlook power-output sectors in interim power calculations

**Status:** Confirmed
**Owner:** leap_initialisation
**Type:** Source-data role boundary
**Affected areas:** `codebase/electricity_heat_interim_workflow.py`; electricity, CHP, and heat interim input selection; interim Output Share and efficiency generation

### Situation

The interim electricity, CHP, and heat calculations use signed energy-balance
values from their corresponding `09_*` transformation sectors. Within those
rows, positive values are outputs and negative values are inputs. The separate
`18_*` electricity-output and `19_*` heat-output accounting sectors are not
inputs to this workflow and must not be introduced as alternative output
evidence.

### Current rule

Never use any `18_*` electricity-output or `19_*` heat-output sector in
electricity interim, CHP interim, or heat plant interim calculations. This is
an absolute source-selection prohibition, not merely a warning about units.

Use only these 9th Outlook sectors for their corresponding modules:

- Electricity interim: `09_01_electricity_plants`;
- CHP interim: `09_02_chp_plants`;
- Heat plant interim: `09_x_heat_plants`.

For each selected `09_*` row, positive signed values produce output values and
Output Shares; negative signed values produce feedstock inputs and Feedstock
Fuel Shares. Efficiency and capacity calculations must use the same permitted
`09_*` source rows according to their established formulas.

If an interim Output Share group is missing, do not fill it from the `18_*` or
`19_*` rows. Apply the canonical share-group rules in INIT-003 to the signed
`09_*` values and the full-model template.

### Validation

Maintain a reusable deny-list for
`18_01_electricity_plants`, `18_02_chp_plants`, `19_01_chp_plants`, and
`19_02_heat_plants`. Test that every configured interim source-sector filter is
disjoint from it. Also test that positive and negative values from each allowed
`09_*` sector are routed to outputs and inputs respectively. A missing Output
Share group is not evidence that an `18_*` or `19_*` row should be introduced.

### History

- 2026-06-28: Confirmed that all `18_*` and `19_*` values are prohibited in interim power calculations and that signed `09_*` rows supply both outputs and inputs.
- 2026-06-28: Added an enforced source-sector allow/deny boundary and signed-row regression coverage.

## INIT-005: Defer baseline-seed validation failure until the full viable run completes

**Status:** Confirmed
**Owner:** leap_initialisation
**Type:** Operational invariant
**Affected areas:** baseline-seed producer orchestration; final workbook writers; validation diagnostics; end-to-end run reporting

### Situation

Baseline-seed production takes long enough that failing on the first ordinary
validation violation wastes the remaining run and hides failures in later
producers or economies. Validation still has to prevent an invalid candidate
from replacing or becoming a final LEAP import workbook.

### Current rule

Do not fail fast on ordinary validation violations. Run every independently
runnable producer and validation stage, accumulate findings, write consolidated
diagnostics after the complete viable run, and then raise one summary exception
if blocking findings remain. Do not create or replace a final import workbook
when blocking findings exist.

If an unexpected fatal error makes safe continuation impossible, write all
findings collected so far before re-raising it. Deferring failure does not turn
a blocking finding into a warning and does not permit invalid rows to reach a
final workbook.

### Validation

Diagnostics identify the source workflow, logical key, scenario and year where
applicable, rule ID, severity, blocking status, and reason. Tests must prove
that failures from multiple independently runnable stages are retained, reports
exist before the summary exception is raised, fatal errors preserve partial
diagnostics, and no invalid final workbook is written or substituted.

### History

- 2026-06-28: Confirmed deferred, consolidated reporting for long-running baseline-seed production.
- 2026-06-28: Final baseline-seed writing now validates every requested economy first, writes consolidated findings, and performs no archive or final-write action when any economy remains blocking.

## INIT-006: Baseline-seed scenario windows and refining capacity policy

**Status:** Confirmed
**Owner:** leap_initialisation
**Type:** Production configuration
**Affected areas:** final baseline-seed coverage validation; refining initialisation

### Current rule

Use configurable base year 2022 and final year 2060. Current Accounts is the
base-year snapshot and must cover 2022. Reference and Target are projection
scenarios and must cover 2023 through 2060. Configuration is centralized in
`workflow_config.py`.

Retain the refining capacity heuristic: copy each refining process/scenario's
Historical Production values to Exogenous Capacity and use `Gigajoules/Year`
with `Million` scale. This policy can be disabled explicitly for testing or a
future modelling decision, but is enabled for production.

### History

- 2026-06-28: Confirmed 2022 base year, 2060 final year, and retention of the refining Historical Production capacity heuristic.

## INIT-007: Fixed-technology transformation modules are locked at base-year output

**Status:** Confirmed (lock policy); Planned (all-economy application)
**Owner:** leap_initialisation
**Type:** Modelling
**Affected areas:** `CAPACITY_UNMET_MODULE_CAPACITY_UPPER_LIMITS` and `CAPACITY_UNMET_PRODUCTION_UPPER_LIMITS` in `codebase/supply_reconciliation_config.py`; capacity-unmet gap allocation in `codebase/supply_reconciliation_allocation.py`; `docs/supply_reconciliation_workflow_guide.md` section 4b

### Situation

When the capacity-unmet allocator closes a positive import gap, it may add
transformation `Exogenous Capacity` to eligible modules. Some legacy /
fixed-technology modules (coke ovens, blast furnaces, gas works, etc.) should
not expand to absorb gaps: growing them is not a realistic supply pathway and
distorts trade. The cap lookups return "no cap" for any economy or module not
explicitly listed, so an unlisted economy runs those modules fully unconstrained.

### Options

- Leave every module uncapped and let the allocator grow whatever closes the gap.
- Lock the fixed-technology modules at base-year output for one representative
  economy only.
- Lock the fixed-technology modules at base-year output for every economy, with
  per-economy overrides added as future runs reveal genuine ceilings.

### Current rule

Lock the following fixed-technology modules at base-year (ESTO baseline) output
via `KEEP_EXOGENOUS_CAP_SAME_AS_BASE_YEAR_ENERGY_OUTPUT`, so the gap-filler
cannot expand them; residual gaps spill to the next lever (imports fallback):
Blast furnaces, BKB and PB plants, Charcoal processing, Coke ovens, Gas works
plants, Liquefaction coal to oil, Natural gas blending plants, Non-specified
transformation, Patent fuel plants, Petrochemical industry, Refinery and
blending transfers, Transfers unallocated, Upstream liquids transfers. All other
modules are `UNLIMITED`.

This lock currently exists only under the `20_USA` key. The agreed direction is
to apply it to **all** economies through a shared `__default__` economy entry
that the cap lookups fall back to, with specific economies overriding it as
future runs supply real ceilings. The `reference` and `target` scenario ceilings
are kept as independent dicts (one shared template copied per scenario) so they
can diverge by scenario without editing one silently changing the other.

`CAPACITY_UNMET_PRODUCTION_UPPER_LIMITS` is presently an all-`UNLIMITED_PRODUCTION`
scaffold (a no-op that documents which products could be capped later); it
applies no production constraint today.

### Validation

Extending the lock to all economies is a modelling change: gaps that legacy
modules previously absorbed by unbounded growth will move to the next lever. On
the first run with the change, compare per-fuel production, transformation
output, imports/exports, and unresolved-residual counts against the prior run,
and confirm no locked module reports added capacity in any economy/scenario.

### History

- 2026-07-01: Recorded the fixed-technology base-year lock, the plan to apply it
  to all economies via a `__default__` fallback, the per-scenario independence of
  reference/target ceilings, and the no-op status of the production cap dict.

## INIT-008: Balance-demand mapping gaps — baseline_seed demand source, non-actionable fuel, known LEAP label exceptions, and the general rollup fallback

**Status:** Confirmed
**Owner:** leap_initialisation
**Type:** Data mapping / comparison boundary
**Affected areas:**
`codebase/functions/supply_demand_mapping.py`
(`load_balance_demand_inputs`, `_build_augmented_balance_demand_mapping_workbook`,
`_build_direct_demand_mapping_status`, `_resolve_demand_esto_pairs_via_rollups`,
`_build_inferred_esto_rows`, `_annotate_balance_demand_issue_scope`);
`codebase/functions/supply_results_saver.py`
(`_is_capacity_unmet_baseline_seed_pass`, balance-demand issue gating);
`codebase/functions/baseline_seed_validation.py`
(`enrich_seed_ids_from_template`, `_rescue_ids_via_known_leap_label_exceptions`);
`codebase/configuration/known_leap_label_exceptions.py`
(`KNOWN_LEAP_LABEL_EXCEPTIONS`);
`codebase/supply_reconciliation_config.py`
(`DEMAND_NON_ACTIONABLE_FUEL_EXACT_MATCHES`);
`codebase/mapping_tools/mapping_rollups.py` (reused rollup machinery);
`leap_mappings/config/outlook_mappings_master.xlsx` sheets `leap_combined_ninth`,
`leap_combined_esto`, `leap_rollup_rules`, `esto_rollup_rules`,
`ninth_rollup_rules`, `ninth_pairs_to_esto_pairs` (read only — never edited here).

### Situation

A `20_USA` baseline_seed run produced 1384 `missing_esto_pair` rows in
`supply_reconciliation_balance_demand_issues.csv` that were also flagged
demand-relevant, hard-stopping the run under
`BALANCE_DEMAND_FAIL_ON_MAPPING_ISSUES = True`. Root causes were four distinct
issues, not one:

1. **baseline_seed was comparing against real LEAP balance exports.** During the
   baseline_seed pass there is no meaningful LEAP export to compare against; the
   pass should size supply purely from the 9th projection-only demand. Comparing
   against LEAP exports is the `results_update` pass's job.
2. **`Total` fuel rows were treated as demand-actionable.** A fuel label of
   exactly `Total` is a sector rollup, not a real fuel, so a missing ESTO pair
   for it should never block demand sizing.
3. **One correctly-spelled mapping row broke an exact-string join.** The live
   LEAP model, its raw full-model export, and `ESTO_PRODUCT_LIST`
   (`15.04 Black liqour`) all use the typo `Black liqour`, but
   `leap_combined_ninth`/`leap_combined_esto` spell it correctly as
   `Black liquor`. The exact-string join in the demand-comparison path and the
   template ID-canonicalization path therefore failed for that fuel.
4. **`Freight road`/`Passenger road` had no ESTO rows at any level.**
   `leap_combined_ninth` has full leaf-level mappings for both sectors but
   `leap_combined_esto` has zero rows for either — 1270 of the 1384 actionable
   rows. Both combined sheets already contain a complete pre-built synthetic
   `Road` sector (12 fuel rows), and `leap_rollup_rules` already declares
   `Freight road`/`Passenger road` → sector `Road`.

### Options

- Edit `outlook_mappings_master.xlsx` to fix the `Black liquor` spelling and to
  author `Freight road`/`Passenger road` ESTO rows. **Rejected by Finn:** the
  spelling is a LEAP-model-side issue to be corrected upstream, and the Road
  target already exists — nothing needs authoring in the workbook.
- Special-case `Black liqour` and `Road` in code. **Rejected:** brittle and
  hides the general shape of both problems.
- Handle the spelling gap as a reviewable config-keyed alias and the missing
  ESTO pairs as a general resolver over the maintained rollup sheets. **Chosen.**

### Current rule

1. **baseline_seed uses projection-only demand unconditionally.**
   `load_balance_demand_inputs(..., allow_projection_only_without_balance_exports=True)`
   (set only for the baseline_seed pass via `_is_capacity_unmet_baseline_seed_pass()`)
   sources every economy's demand from the 9th projection-only table and ignores
   any LEAP balance export for that economy. Real LEAP exports are compared only
   during `results_update`.
2. **`Total` fuel rows are not demand-actionable.**
   `DEMAND_NON_ACTIONABLE_FUEL_EXACT_MATCHES = ("total",)` drives
   `_is_non_actionable_demand_fuel`; matching rows get `demand_relevant = False`,
   basis `excluded_non_actionable_fuel` (flag `issue_fuel_is_non_actionable`).
3. **Known LEAP label exceptions (temporary).**
   `KNOWN_LEAP_LABEL_EXCEPTIONS = {"Black liqour": "Black liquor"}` in
   `codebase/configuration/known_leap_label_exceptions.py` maps a LEAP-model
   spelling to the mapping-sheet spelling. It is applied in two places:
   - In `_build_direct_demand_mapping_status`, the LEAP fuel-label column is
     rewritten through the dict before the `leap_combined_ninth`/`leap_combined_esto`
     join (safe to apply eagerly — an entry only rewrites a label that would not
     otherwise match).
   - In `enrich_seed_ids_from_template`, a narrow rescue pass runs *after* the
     normal template lookup: only rows still at `BranchID`/`VariableID == -1` get
     the alias applied (both directions) to their branch key and re-looked-up
     against the same `branch_ids`/`variable_ids` dicts. Only rows that flip from
     `-1` to a real match are overwritten; genuinely unmatched rows stay `-1` and
     stay blocking. Rescues are logged
     (`[INFO] rescued … via KNOWN_LEAP_LABEL_EXCEPTIONS`).
   This mechanism is **temporary**. Remove the entry once the LEAP model spelling
   is corrected upstream and the rescue log goes quiet. Do not expand the dict
   beyond reviewed entries without checking with Finn — it is not a general
   fuzzy-matching layer.
4. **General rollup-resolution fallback.**
   `_resolve_demand_esto_pairs_via_rollups`, wired into
   `_build_augmented_balance_demand_mapping_workbook`, resolves any demand
   `(leap_sector, fuel)` that has no direct leaf-level ESTO pair and no canonical
   `ninth_pairs_to_esto_pairs` bridge. It rolls the LEAP identity to a maintained
   rollup target via `leap_rollup_rules` (exact-or-descendant sector match; blank
   `rolled_*` keeps the original per the sheet's own convention) and looks up that
   target's pre-built combined-sheet ESTO pair; failing that, it rolls the 9th
   identity via `ninth_rollup_rules` and bridges through `ninth_pairs_to_esto_pairs`.
   It reuses `codebase/mapping_tools/mapping_rollups.py` (`active_rollup_rules`,
   `value_matches`, `parse_priority`, `normalise_key`, `rollup_columns_for_sheet`)
   rather than a parallel implementation. It is **general over all active rows in
   `leap_rollup_rules`, `esto_rollup_rules`, and `ninth_rollup_rules`**, gated only
   by each row's own `include`/`rollup_context` fields — no separate allowlist, per
   Finn's explicit call, since those sheets are already maintained and reviewed. It
   is proven via the Road transport case but not scoped to it (e.g. it equally
   resolves `Coal transformation` and other maintained rollups). Rows that no rule
   plus pre-built target can resolve are reported (`[WARN] … no active rollup rule
   with a pre-built rolled target`), never silently invented.

### Validation

- `python -m pytest tests/ -k "demand or balance_demand or supply_reconciliation or baseline_seed" -q`.
- `tests/test_balance_demand_mapping_fixes.py` (alias parity; Road leap-rollup;
  a second non-Road leap-rollup pattern; a ninth_rollup fallback; an unresolvable
  row omitted) and the `enrich_seed_ids_from_template` rescue / stays-`-1` tests
  in `tests/test_baseline_seed_comparison_workflow.py`.
- Rebuilding the augmented balance-demand mapping leaves **0** demand
  `(leap_sector, fuel)` keys without an ESTO pair (57 candidates, all resolved),
  and `_build_projection_only_mapping_status` — the inner-join path baseline_seed
  uses — now contains the `Freight road`/`Passenger road` descendant 9th sectors
  (`15_02_01_*` / `15_02_02_*`) carrying the pre-built `15.02 Road` ESTO pair,
  rather than silently dropping them.
- Provenance note (verified against the current workbook): the pre-existing
  canonical `ninth_pairs_to_esto_pairs` bridge already maps every **non-subtotal
  leaf** Freight/Passenger road 9th code (the deep vehicle/technology codes such
  as `15_02_01_01_02_gasoline_engine`, 143 of 157 rows) to `15.02 Road`, so those
  leaves — which carry the actual demand — resolve via the canonical bridge and
  the rollup fallback adds 0 rows today. The only Freight/Passenger road 9th codes
  the canonical bridge does *not* cover are the parent codes `15_02_02_freight` /
  `15_02_01_passenger`, but every such row is `leap_is_subtotal = True` /
  `ninth_pair_is_subtotal = True` and is excluded from the augment candidates (and
  from the projection-only inner join — 0 rows) to avoid double-counting the
  children, so no demand is lost. The rollup resolver is therefore the general
  safety net for any *non-subtotal* sector/fuel a rollup rule + pre-built target
  covers but the canonical bridge does not (present or future); its own resolution
  is exercised directly in `tests/test_balance_demand_mapping_fixes.py` with an
  empty canonical bridge. Any residual gap is reported, never invented.

### History

- 2026-07-03: Recorded all four balance-demand mapping fixes — baseline_seed
  projection-only demand source, the `Total` non-actionable-fuel exclusion, the
  temporary `KNOWN_LEAP_LABEL_EXCEPTIONS` alias/rescue mechanism, and the general
  rollup-resolution fallback (proven via the Road transport case). No mapping
  workbook rows were edited.

## INIT-009: Two complementary compressed preflights before the long baseline-seed and results-update runs

**Status:** Confirmed
**Owner:** leap_initialisation
**Type:** Integration test / run-workflow boundary
**Affected areas:**
`codebase/functions/supply_preflight.py`
(`run_preflight_compressed_projection`, `run_preflight_compressed_results_update`,
`_create_preflight_compressed_source_files`, `_build_reduced_preflight_balance_workbook`,
`_sum_future_balance_grids`, `_broadcast_config_overrides`,
`_finalize_balance_demand_issue_report`);
`codebase/supply_reconciliation_workflow.py` (`run_with_config` preflight toggles);
real `20_USA` LEAP balance-export workbooks under
`data/leap balances exports/20_USA/` (read only — never edited here);
isolated outputs under
`outputs/leap_exports/supply_reconciliation/preflight_compressed_results_update/`.

### Situation

Full `baseline_seed` and `results_update` runs are slow (whole pipeline per
economy across all years; a full LEAP energy-balance export alone takes 3–4
hours). A regression that only surfaces late in a full run is expensive to find.
The pre-existing `run_preflight_compressed_projection` is a fast 00_APEC
baseline-seed integration check, but it uses projection-only demand and never
reads real LEAP balance exports, so the entire results-update balance path
(balance conversion, balance-demand mapping, issue classification,
results-update demand sourcing) was unexercised by any fast check.

### Decision

Maintain **two complementary** compressed preflights and present them together as
the fast checks before the long runs:

1. **Compressed projection preflight** — 00_APEC, ESTO base year + one compressed
   future year of signed-summed 9th projection activity; exercises the
   baseline-seed path; no real LEAP exports.
2. **Compressed results-update preflight** — 20_USA, base year + one compressed
   future year, reading temporary **reduced** REF/TGT balance workbooks
   (`EBal|<base>` verbatim + synthetic `EBal|<base+1>` = signed sum of every
   post-base-year source sheet); exercises the results-update path in
   `CAPACITY_UNMET_PASS_MODE = "results_update"`.

**Why one cannot replace the other:** the projection preflight deliberately has no
dependency on real LEAP exports (so it stays fast and always runnable) and only
proves the baseline-seed sizing path; the results-update preflight only proves the
LEAP-export/results-update path and depends on the real 20_USA balance structure.
Each covers code the other does not.

**Why synthetic future values use signed sums:** the balance rows carry signed
conventions (exports, bunkers, stock changes, transformation inputs are negative),
so the synthetic future sheet must preserve signs to remain a valid balance the
existing reader can convert. Absolute values would corrupt the balance.

**Why absolute sums are diagnostics only:** signed summation can hide a category
whose positive and negative future contributions cancel to zero. A separate
abs-sum diagnostic (a sidecar CSV, never the balance sheet itself) exposes those
categories without polluting the signed synthetic values.

**Why all state and outputs are isolated:** the preflight forces a two-year,
single-economy, results_update, cache-off, LEAP-import-off configuration across
many modules. Config values are broadcast to every consuming module and restored
in `finally` (even on failure), and every output/runtime/checks directory plus the
temporary reduced workbooks live under a dedicated preflight root, so a subsequent
production run is unaffected and the production source workbooks and iterative
state are never modified.

### Limitations

The results-update preflight uses the *existing* real 20_USA balance-export
structure, not a newly recalculated LEAP model matching the compressed inputs. It
is a strong structural and integration test, not a numerical reproduction of a
genuine two-year LEAP run. Neither preflight proves every economy, year,
economy-specific rule, LEAP import, or iterative convergence behaviour, and neither
performs any LEAP import or live results scraping.

### Removal / change conditions

Retire or fold together the two preflights only if the full runs become cheap
enough that a fast approximation is no longer worthwhile, or if a genuine
two-year recalculated 20_USA LEAP export becomes available (which would let the
results-update preflight become a numerical check rather than a structural one).
If the balance reader's expected sheet structure changes,
`_sum_future_balance_grids` / `_build_reduced_preflight_balance_workbook` must be
revalidated against it.

### History

- 2026-07-03: Added the compressed results-update preflight
  (`run_preflight_compressed_results_update`) alongside the existing compressed
  projection preflight, with reduced REF/TGT balance workbooks (signed synthetic
  future sheet + abs-sum diagnostic), scenario-separated 9th compression,
  isolated broadcast state management, a deterministic balance-demand issue report
  using the current schema (`issue_fuel_is_non_actionable`, `demand_relevant`,
  `demand_relevance_basis`), and `run_with_config` toggles. No source workbooks or
  mapping workbook rows were edited.

## End-to-end run report

Append a dated subsection after each end-to-end run. Report:

- newly discovered decisions;
- unresolved decisions blocking correct output;
- provisional assumptions used to continue;
- rules that should move into configuration;
- rules that should become automated validation;
- the next decisions requiring human guidance.

Also report coverage, dropped rows, source-versus-output totals, hierarchy consistency, mapping cardinality where mappings are consumed, and semantic review of reconciliation behaviour. A successful process exit is not evidence that the model output is correct.
# Internal supply and transformation conservation diagnostics

Baseline-seed verification compares independent raw ESTO/9th reference energy
with the values built by this repository before LEAP export. It never uses a
LEAP balance readback and never changes an export value to obtain a match.

Supply is compared by `economy / flow / year`. Production and imports must be
positive. Raw balance exports must be non-positive and are converted to positive
export magnitude exactly once. Structurally aggregate products and flagged
subtotals are excluded and retained in lineage with their scope reason. The
headline CSV is pass/fail; its breakdown and lineage CSVs localise product rows
and prove that their signed contributions reproduce each headline difference.

Transformation v1 compares positive transformation output energy at the
reliable shared grain `economy / scenario / all transformation outputs / all
fuels / year`. Raw ESTO base-year and 9th projection rows are independent of the
produced side, which is read from final pre-export transformation process
records. Negative feedstock and auxiliary inputs, zero skeletons, aggregate
parents, and own-use/loss proxy values are not outputs. Finer raw modules and
fuels remain in lineage because source and LEAP module definitions are not
consistently one-to-one; no allocation shares are invented.

The reference scope follows modules active in the run. Electricity, CHP, and
heat-plant source outputs remain visible in the scope-audit lineage but use
`module_not_built_in_active_workflow` when the electricity/heat interim workflow
is disabled. When it is enabled, its pre-export process records are included on
the produced side. Reference and Current Accounts use the reference projection;
Target uses the target projection, matching transformation export generation.

This proves that output energy was not dropped or duplicated during
construction. It does not prove LEAP round-trip fidelity, convergence,
efficiency, or the full transformation identity. Transformation v2 is deferred:
`feedstock input + applicable auxiliary/loss energy -> output through configured
efficiency`. Before v2, each module must specify whether losses are embedded in
its efficiency or supplied by `other_loss_own_use_proxy`, to prevent the same
loss energy being counted twice.
