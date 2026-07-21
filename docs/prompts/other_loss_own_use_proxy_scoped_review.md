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
