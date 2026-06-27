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

## End-to-end run report

Append a dated subsection after each end-to-end run. Report:

- newly discovered decisions;
- unresolved decisions blocking correct output;
- provisional assumptions used to continue;
- rules that should move into configuration;
- rules that should become automated validation;
- the next decisions requiring human guidance.

Also report coverage, dropped rows, source-versus-output totals, hierarchy consistency, mapping cardinality where mappings are consumed, and semantic review of reconciliation behaviour. A successful process exit is not evidence that the model output is correct.
