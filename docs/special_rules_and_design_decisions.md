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

### History

- 2026-06-27: Defined order-independent duplicate classification and required duplicate resolution before share validation.
- 2026-06-27: Recorded the full-model export lifecycle, ID sentinel rules, duplicate-key requirement, and cross-repository mapping dependency after reviewing the June 2026 USA baseline backup.

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

## End-to-end run report

Append a dated subsection after each end-to-end run. Report:

- newly discovered decisions;
- unresolved decisions blocking correct output;
- provisional assumptions used to continue;
- rules that should move into configuration;
- rules that should become automated validation;
- the next decisions requiring human guidance.

Also report coverage, dropped rows, source-versus-output totals, hierarchy consistency, mapping cardinality where mappings are consumed, and semantic review of reconciliation behaviour. A successful process exit is not evidence that the model output is correct.
