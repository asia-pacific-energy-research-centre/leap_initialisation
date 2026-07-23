# Other loss and own-use proxy - scoped review and implementation brief

## Purpose

`codebase/other_loss_own_use_proxy_workflow.py` creates values for
`Demand\\Other loss and own use` where losses/own-use cannot be represented by
a specific transformation module. It is a modelling proxy: activity source,
fuel intensity, validation strictness, and fallback handling all affect the
seed values.

This brief is linked from `docs/work_queue.md` [15]. It should be reviewed
before any large refactor or rewrite.

## Important current facts

- `PROXY_ACTIVITY_SOURCE_MODE = "esto_ninth"` and
  `PROXY_INTENSITY_MODE = "target_matching_initialisation"` are model choices.
- The reconciliation presets select the first (ESTO/ninth) or second
  (LEAP-balance) activity stage; this is a pass-mode decision, not a wrapper
  default.
- `PROXY_CONFIG` maps individual processes to activity and target data. Treat
  it as the model specification until a reviewed replacement exists.
- The workflow now resolves export keys from the requested economy's template.
  USA fallback remains only for aggregate/no-template cases. This prevents
  cross-economy BranchID borrowing.
- The known `Non specified own uses` issue is a template migration gap: do not
  create missing LEAP IDs in Python or copy them from another economy.

## Structural assessment 2026-07-21 — the file is healthy; coverage is the weakness

Measured while resolving Phase 4's D4.4 (see
`docs/prompts/phase_4_monolith_decomposition_execution.md`). Recording it here
because the follow-up work belongs to this review, not to Phase 4.

**No structural work is warranted.** `AGENTS.md`'s "2,900-line monolith …
so internally tangled that rewriting from scratch may be cleaner" no longer
describes this code:

| Metric | `other_loss_own_use_proxy_workflow.py` | `functions/other_loss_own_use_proxy_utils.py` |
|---|---|---|
| Lines | 1,770 (not 2,923) | 2,343 |
| Largest function | `assemble_proxy_workbook` 356 lines / 43 branches | `build_proxy_source_coverage_gaps` 183 / 42 |
| Next two | 140 / 21, 103 / 8 | 122 / 15, 106 / 6 |
| Everything else | under ~70 lines | under ~90 lines |
| `TODO`/`FIXME`/`HACK` | 1 | 0 |

`PROXY_CONFIG` is 19 declarative entries on one uniform 8-key schema
(`process_key`, `process_label`, `leap_process_label`, `activity_label`,
`activity_sources`, `target_sources`, `enabled`, `notes`). Adding a process is a
data edit. Only `assemble_proxy_workbook` is large enough that its size could
plausibly hide a defect; splitting it is optional cleanup, not a prerequisite.

### The actual gap: the tested set and the enabled set only partly overlap

60 tests exist (`test_other_loss_own_use_proxy_workflow.py` 59,
`test_other_loss_own_use_proxy_aggregate.py` 1), but they are aimed partly at
processes that are switched off:

- **Enabled (9):** `coal_mines`, `electricity_chp_and_heat_plants`,
  `liquefaction_regasification_plants`, `oil_and_gas_extraction`,
  `pump_storage_plants`, `nuclear_industry`,
  `gasification_plants_for_biogases`, `nonspecified_own_uses`,
  `transmission_and_distribution_losses`.
- **Disabled (10):** `gas_works_plants`, `gas_to_liquids_plants`, `coke_ovens`,
  `blast_furnaces`, `patent_fuel_plants`, `bkb_pb_plants`,
  `liquefaction_plants_coal_to_oil`, `oil_refineries`,
  `charcoal_production_plants`, `ccs`.
- Test mentions: `liquefaction` 18, `coal_mines` 15, `blast_furnaces` 13,
  `gas_works` 4, `coke_ovens` 4, `oil_refineries` 3, `nonspecified_own_uses` 2,
  `pumped` 1. **Three of the four most-tested processes are disabled.**

**Five enabled processes are not named anywhere in the tests:**
`electricity_chp_and_heat_plants`, `oil_and_gas_extraction`,
`nuclear_industry`, `gasification_plants_for_biogases`,
`transmission_and_distribution_losses`.

**Priority action for this review:** build fixtures for those five first (this
is deliverable 1 below, narrowed to a concrete starting set). Two of them are
material — `electricity_chp_and_heat_plants` and
`transmission_and_distribution_losses` carry large own-use/loss volumes — and
`pump_storage_plants` has already produced a real defect once (see the
pump-storage strict-check history).

Caveat: this assessment covers structure and coverage shape only. It does not
establish that the proxy's values are correct. A well-structured, well-covered
module can still encode the wrong methodology; that remains the separate
modelling question in "Design decisions required".

## Discovery deliverables

Create a compact inventory (in this prompt or a companion findings note) with:

1. Every enabled `PROXY_CONFIG` process, its activity numerator/denominator,
   ESTO/ninth source filters, LEAP balance rows, and intended branch target.
2. Every fallback path: no activity, zero throughput, no target fuel, missing
   template branch, missing region, and no LEAP balance export.
3. Output contract: workbooks, diagnostics, strictness switches, and which
   conditions are warnings versus seed-blocking errors.
4. A sample of real-template economies plus one aggregate/preflight case,
   reporting template provenance, region, BranchID coverage, and unresolved
   paths.

## Design decisions required

- Whether the 2,900-line module should be decomposed incrementally or rewritten
  behind an exact workbook-output contract.
- Who owns the proxy process list and fuel mappings: this repository or
  `leap_mappings`. Do not duplicate canonical mappings without an agreed reason.
- Whether target-matching intensity is retained for every process and pass.
- Whether strict consistency issues fail a production run, remain diagnostics,
  or differ by pass type.
- The migration path for template-only branches such as non-specified own use:
  update the real LEAP area/template, then rerun; code must report rather than
  fabricate IDs.

## Scoped review findings 2026-07-23

This is the review this brief itself asks for (activity source, intensity
mode, fallback policy, template-ID contract) — not T8's structure/coverage
work, which is settled and out of scope here (see
`docs/prompts/initialisation_refactor_continuation.md` T8). Every claim below
is cited `file:line` against the current tree (clean `master` checkout,
commit `048a927` at review start).

### 1. Activity source: confirmed pass-mode decision, and one gap in what gets forwarded

- `PROXY_ACTIVITY_SOURCE_MODE = "esto_ninth"` is only the *default parameter
  value* on `assemble_proxy_workbook`
  (`codebase/other_loss_own_use_proxy_workflow.py:201`,
  `:1369`). The production caller always overrides it:
  `build_other_loss_own_use_proxy_workbooks_for_results_supply` resolves
  `activity_source_mode` from `OTHER_LOSS_OWN_USE_PROXY_STAGE` /
  `CAPACITY_UNMET_PASS_MODE` via
  `_resolve_other_loss_own_use_proxy_activity_source_mode`
  (`codebase/functions/supply_leap_io.py:1071-1097`) before ever calling
  `assemble_proxy_workbook` (`:1166-1177`) — `"auto"` maps
  `baseline_seed -> esto_ninth` and `results_update -> leap_balance`
  (`:1088-1092`), and an unresolvable pass mode raises rather than silently
  defaulting (`:1093-1097`). The brief's "pass-mode decision, not a wrapper
  default" claim is correct.
- Only one production call site exists:
  `codebase/functions/supply_results_saver.py:3738-3749`, gated by
  `RUN_OTHER_LOSS_OWN_USE_PROXY` and forwarding `proxy_stage`,
  `iteration_run_mode`, `output_fuel_scope`, and the three
  `leap_balance_*` knobs — but **not** `strict_proxy_activity_target_consistency`
  or `intensity_mode`. Both therefore always take the module-level default
  regardless of which pass is running (see finding 3).
- `esto_ninth` mode has its own alternative-source fallback tiers
  (`ESTO_NINTH_ACTIVITY_FALLBACKS`,
  `codebase/functions/other_loss_own_use_proxy_utils.py:426-498`), used only
  when the *whole* configured series is zero
  (`build_proxy_activity_series_with_fallback`, `:1097-1186`, guard at
  `:1121-1122`). Coverage is asymmetric: of the 12 currently-enabled processes
  with an ESTO/9th activity leg, only 2 have a configured fallback chain
  (`liquefaction_regasification_plants`, `pump_storage_plants`,
  `:432-498`); the other 10 (`coal_mines`,
  `electricity_chp_and_heat_plants`, `oil_and_gas_extraction`,
  `nuclear_industry`, `gasification_plants_for_biogases`,
  `nonspecified_own_uses`, `transmission_and_distribution_losses`) have no
  alternative-source tier and simply stay at zero activity if their
  configured ESTO/9th flows are empty for an economy — which then either
  trips `STRICT_PROXY_ACTIVITY_TARGET_CONSISTENCY` (if target energy is
  positive) or silently produces a zero-intensity row (if target energy is
  also zero). `leap_balance` mode has a separate, smaller fallback table
  (`LEAP_BALANCE_ACTIVITY_FALLBACKS`, `:382-418`) covering 3 processes
  (`pump_storage_plants`, `electricity_chp_and_heat_plants`,
  `liquefaction_regasification_plants`) — not the same 3 as the esto/9th
  table, so a process's fallback safety net differs by activity_source_mode.
  **This asymmetry is a design gap worth a decision**, not just a coverage
  gap: `nonspecified_own_uses` and `transmission_and_distribution_losses` are
  called out in the doc's own coverage section as carrying "large
  own-use/loss volumes" yet have zero fallback tiers in either mode.
- A separate, mode-independent safety net exists only for `esto_ninth`:
  `_backfill_base_year_activity_from_projection`
  (`codebase/functions/other_loss_own_use_proxy_utils.py:1189-1213`, wired in
  at `build_activity_series_for_mode:1230-1248`) copies the first nonzero
  *projection*-year activity into a zero base year. This is the mechanism
  that resolved the pump-storage strict-check blocker (see
  `project_pump_storage_strict_check_blocker` in memory). It only ever
  touches the base year; earlier years are left zero and stay report-only
  (`:1199-1202`).

### 2. Intensity mode: one of two modes is defined, tested, and never invoked in production

- `PROXY_INTENSITY_MODE = "target_matching_initialisation"`
  (`codebase/other_loss_own_use_proxy_workflow.py:210`) is the only value any
  production caller ever supplies. `build_other_loss_own_use_proxy_workbooks_for_results_supply`
  (`codebase/functions/supply_leap_io.py:1132-1179`) never passes
  `intensity_mode` to `assemble_proxy_workbook`, so both baseline-seed and
  results-update passes always run target-matching intensity — this is the
  literal answer to "whether target-matching intensity is retained for every
  process and pass": **yes, currently for every enabled process and both
  passes, because nothing in the call chain can select the alternative.**
- `"post_initialisation_anchored_intensity"` is fully implemented
  (`_add_anchored_intensity_columns`,
  `codebase/functions/other_loss_own_use_proxy_utils.py:932-964`; dispatched
  from `build_proxy_detail_table`,
  `codebase/other_loss_own_use_proxy_workflow.py:1103-1109`) and has direct
  unit coverage (`test_post_initialisation_intensity_uses_first_valid_nonzero_anchor`,
  `tests/test_other_loss_own_use_proxy_workflow.py:1320`), but
  `grep -rn "post_initialisation_anchored_intensity\|intensity_mode=" codebase`
  outside the workflow/utils pair itself returns nothing — no caller anywhere
  in the codebase ever requests it. It is reachable only by calling
  `assemble_proxy_workbook`/`build_proxy_detail_table` directly with an
  explicit `intensity_mode=` override (e.g. from a notebook or a test), never
  through the production entry point. The module docstring
  (`codebase/other_loss_own_use_proxy_workflow.py:12-19`) frames
  post-initialisation as a real future mode ("used only once the model is no
  longer trying to match external projection-year target energy"), so this
  reads as deliberately-staged-but-not-yet-switched-on, not dead code to
  delete — but the design-decision question ("whether target-matching
  intensity is retained for every process and pass") currently has a crisp,
  citable answer rather than an open one.

### 3. Fallback / strictness policy: does not currently differ by pass type

- `STRICT_PROXY_ACTIVITY_TARGET_CONSISTENCY = True` and
  `WRITE_PROXY_ACTIVITY_TARGET_CONSISTENCY_ISSUES = True`
  (`codebase/other_loss_own_use_proxy_workflow.py:212-213`) are both module
  constants with no per-pass override anywhere in the call chain: neither
  `build_other_loss_own_use_proxy_workbooks_for_results_supply`
  (`codebase/functions/supply_leap_io.py:1132-1179`) nor its one caller
  (`codebase/functions/supply_results_saver.py:3738-3749`) forwards a
  `strict_proxy_activity_target_consistency` argument, so `assemble_proxy_workbook`
  always uses its default (`:1371`) — identically strict for baseline-seed
  and results-update passes. This directly answers the brief's open question
  "Whether strict consistency issues fail a production run, remain
  diagnostics, or differ by pass type": **today it does not differ by pass
  type; it is always blocking**, gated only by `blocking_min_year=EXPORT_BASE_YEAR`
  (`:1468`) so pre-base-year rows stay report-only regardless of pass
  (`validate_proxy_activity_target_consistency`,
  `codebase/other_loss_own_use_proxy_workflow.py:998-1059`, the
  `blocking_min_year` filter at `:1018-1023`).
- Inside `build_proxy_detail_table`, the internal consistency check runs once
  non-blocking (`strict_proxy_activity_target_consistency=False` is
  hardcoded at the call site in `assemble_proxy_workbook:1443`, and
  `validate_proxy_activity_target_consistency` is called again with
  `print_warning=False` at `build_proxy_detail_table:1158-1164`) purely to
  populate `LAST_FUEL_MAPPING_AMBIGUITY`-style bookkeeping; the real
  strict/blocking evaluation happens exactly once, later, at
  `assemble_proxy_workbook:1463-1469`, with the caller-supplied
  `strict_proxy_activity_target_consistency` value. There is no double
  jeopardy and no silent swallow — one clear gate.
- Two independent non-fatal diagnostics exist alongside the fatal gate:
  `build_activity_source_gap_warnings` (ESTO nonzero, 9th projection all
  zero — printed, never raises,
  `codebase/other_loss_own_use_proxy_workflow.py:1525-1573`) and
  `build_proxy_source_coverage_gaps` (nonzero 10.x rows not covered by any
  `PROXY_CONFIG` entry — printed, never raises, `:1581-1608`). Only the
  output-fuel-validation check is unconditionally fatal regardless of pass
  or strict flag: `assemble_proxy_workbook:1503-1513` raises `ValueError` if
  any output branch fails the ESTO-snapshot non-zero check, with no
  parameter to downgrade it to a warning. So today there are three tiers in
  practice — always-warn, warn-unless-strict (the consistency gate,
  currently always strict in production), and always-raise (output-fuel
  validation) — not the binary "warning vs seed-blocking error" the brief's
  deliverable 3 framed it as.

### 4. Template-ID contract: matches the brief, with one precision correction

- `_resolve_export_key_workbook_path`
  (`codebase/other_loss_own_use_proxy_workflow.py:1342-1357`) calls
  `leap_export_template_resolver.resolve_leap_export_template_or_fallback`
  with `fallback=EXPORT_KEY_WORKBOOK_PATH` (the legacy USA template,
  `:187-189`), confirming the brief's "resolves export keys from the
  requested economy's template" claim.
- **Precision correction**: the fallback is not aggregate-only. Per
  `resolve_leap_export_template_or_fallback`'s own docstring and code
  (`codebase/utilities/leap_export_template_resolver.py:200-233`), it falls
  back to the USA template in two cases: (a) aggregate sentinels
  (`is_aggregate_economy`, `:223-224`), and (b) **any single economy** whose
  `resolve_leap_export_template` call raises `FileNotFoundError` or
  `ValueError` — i.e. a real, named economy with no template yet
  (`:225-233`, docstring at `:209-213`: "an economy with no template yet").
  The workflow's own comment ("USA template is retained only as the explicit
  fallback for aggregate runs that do not have one economy's area to
  resolve", `codebase/other_loss_own_use_proxy_workflow.py:184-186`)
  undersells this: it also covers a real economy that simply has no template
  exported yet, and a `[WARN]` is printed either way
  (`leap_export_template_resolver.py:232`). This is not a defect — the
  behaviour is deliberate and warned — but the in-file comment should say
  "aggregate or no-template-yet" rather than "aggregate runs" alone if it is
  ever touched, to avoid a future reader assuming individual economies are
  unconditionally exempt from ever needing the fallback.
- ID attachment never fabricates: `merge_export_ids`
  (`codebase/functions/other_loss_own_use_proxy_utils.py:2152-2209`) left-joins
  generated rows to the export key table on `Branch Path`/`Variable`/`Scenario`
  and **drops** (not invents) unmatched rows with a `[WARN]` naming them
  (`:2188-2198`); if a row matches the join but still has a missing ID value
  it raises rather than defaulting (`:2200-2207`). `load_export_key_table`
  (`:2102-2149`) also raises on duplicate `Branch Path`+`Variable`+`Scenario`+`Region`
  keys (`:2142-2148`) rather than picking one arbitrarily. This matches the
  brief's "do not create missing LEAP IDs in Python or copy them from another
  economy" policy for the `Non specified own uses` template gap — the
  mechanism that would prevent fabrication either way is the same
  `merge_export_ids` drop-and-warn path used for every process, not a
  special case.
- `add_zero_rows_for_unset_values`
  (`codebase/functions/other_loss_own_use_proxy_utils.py:2221-2270`) only
  fills zero expressions for keys **already present** in the export key
  table (it reads `export_key_table`, never writes to it), so it cannot be
  the source of a fabricated ID either — it is scoped to
  `Demand\Other loss and own use` rows via `include_prefixes=(root_path,)`
  (`:2247`) and the two managed variables.
- Existing test coverage for this contract:
  `test_export_key_workbook_resolves_for_economy_when_not_overridden` and
  `test_export_key_workbook_explicit_override_skips_economy_resolution`
  (`tests/test_other_loss_own_use_proxy_workflow.py:63`, `:81`) exercise the
  per-economy resolution path directly.

### 5. Config ownership (leap_mappings vs this repo)

- `PROXY_CONFIG`'s process definitions — which ESTO 10.0x/09.xx flow codes
  and 9th `sector_codes`/`fuels`/`subfuels` constitute each of the 19
  processes — are defined entirely in this repo
  (`codebase/other_loss_own_use_proxy_workflow.py:333-736`) with no import
  from `leap_mappings`. Only the **fuel-name canonicalization** used to label
  output branches is externally owned: `load_fuel_mapping_lookup`
  (`codebase/other_loss_own_use_proxy_workflow.py:848-873`) reads
  `leap_combined_esto`/`leap_combined_ninth` from
  `OUTLOOK_MAPPINGS_MASTER_PATH` (`outlook_mappings_master.xlsx`, owned by
  `leap_mappings`) via `codebase.mappings.canonical_loaders`
  (`:39-42`). So the brief's ownership question splits cleanly along an
  existing seam: **process-to-flow-code assignment stays here; fuel-label
  canonicalization is already the `leap_mappings`-owned lookup** — there is
  no duplication to resolve on the fuel-label side, and no natural home in
  `leap_mappings` for the process list itself (10.01.x own-use/loss process
  splits are not part of any canonical mapping sheet found in this repo's
  view of `leap_mappings`).

## Safe implementation phases

1. Add characterization tests around existing output workbooks before moving
   logic. Include first-stage and second-stage activity modes.
2. Extract pure, data-frame-level helpers one at a time (activity selection,
   intensity calculation, template-ID attachment, diagnostics). Preserve input
   and output schemas.
3. Keep orchestration and all `PROXY_CONFIG` values unchanged until their
   inventory is reviewed.
4. Consider a clean rewrite only after fixtures cover each enabled process and
   a before/after real-economy comparison is exact within stated tolerance.

## Acceptance

For each migrated portion, compare keyed rows and expressions to the existing
workflow for a baseline seed and a results-update seed. Verify no output row
uses another economy's template IDs, and separately report genuine missing
template branches. Do not combine this work with a full fleet run.
