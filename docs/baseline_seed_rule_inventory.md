# Baseline seed rule inventory

This inventory records evidence recovered from the legacy `leap_utilities`
initialisation workflows. Legacy behaviour is evidence, not authority. Only
items classified as `confirmed_rule` or `confirmed_exception` are enforced by
the baseline-seed validators.

## Comparator gap assessment

Before this work, `baseline_seed_comparison_workflow.py` checked file inventory,
row and metadata differences, expression form and year differences, duplicate
logical keys, and basic Output/Process/Feedstock share sums. It could not
validate a candidate without a reference, checked no complete-ID or template
branch rules, selected duplicate share rows using workbook order, had no stable
rule IDs/severity/blocking fields, and emitted no compact rule summary or fixture
provenance.

Rule-driven validation required deterministic duplicate resolution before share
calculation, explicit rule metadata, all-ID and branch checks, configurable
year/scenario coverage, explicit exceptions, and optional reference validation.
Those capabilities now live in
`codebase/functions/baseline_seed_validation.py`; the comparator writes candidate
rule findings regardless of whether a reference directory is supplied.

The detailed rule output includes stable rule ID, status, severity, blocking
flag, evidence, documentation reference, and conservative source-workflow
attribution. `rule_summary.csv` is the compact release view. Difference rows use
the supported taxonomy `intentional_improvement`,
`expected_formatting_or_structure`, `regression`,
`inherited_reference_defect`, `unresolved_modelling_decision`,
`equivalent_semantics`, and `not_comparable`. Automatic comparison assigns only
`unresolved_modelling_decision` or `not_comparable`; stronger labels require
review evidence.

Notebook use without a reference:

```python
#%%
outputs = run_baseline_seed_comparison(
    reference_dir=None,
    candidate_dir=CANDIDATE_SEED_DIR,
    output_dir=COMPARISON_OUTPUT_DIR,
    economies=["20_USA"],
    required_years=range(2022, 2061),
    required_scenarios=["Current Accounts", "Reference", "Target"],
)
#%%
```

Set `reference_dir` to any snapshot to add row comparison. Reference rule
validation remains off unless `validate_reference=True`.

## Candidate inventory

The line references below identify the evidence reviewed in the legacy repo and
the corresponding implementation in this repository. They are navigation aids,
not permanent API references.

| Candidate | Scope and calculation | Scenario/year/fallback evidence | Legacy evidence | Refactored implementation / tests | Classification |
|---|---|---|---|---|---|
| SEED-C001 | A final import row is keyed by Branch Path + Variable + Scenario + Region. | All scenarios and years; duplicates must be resolved before calculations. | `functions/patch_baseline_seeds.py:438,669-680` used order-sensitive `keep="last"`; `aggregated_demand_workflow.py:996` used a shorter three-column key. | `baseline_seed_validation.resolve_logical_duplicates`; `tests/test_baseline_seed_comparison_workflow.py` | `confirmed_rule` (CROSS-001); legacy resolution is a `probable_bug` |
| SEED-C002 | Exact physical duplicates with the same IDs and expression may be removed deterministically. | Independent of workbook row order. | Legacy patching removed duplicates by row position. | `resolve_logical_duplicates`; exact-duplicate test | `confirmed_rule` |
| SEED-C003 | Conflicting duplicates with one valid-ID row use that row for diagnostics, but the physical duplicate group blocks final import. | All scenarios/years. | June USA Heat plant interim contains valid-ID and `-1` expressions for the same logical key. | Heat plant unit and fixture tests | `confirmed_rule` |
| SEED-C004 | Conflicting duplicate groups with multiple valid-ID rows block import. | All scenarios/years; no automatic choice. | No safe legacy resolver was found. | Multiple-valid-row test | `confirmed_rule` |
| SEED-C005 | All four IDs are required on final import rows. | A `-1`, blank, or non-numeric ID is missing. | `supply_reconciliation_workflow.py:13261-13288` blocked only nonzero `BranchID=-1`; `functions/patch_baseline_seeds.py:726-727` defaulted IDs. | Rules SEED-003 to SEED-005; all-ID test | `confirmed_rule` (CROSS-001) |
| SEED-C006 | A nonzero or unparseable expression with any missing ID blocks import. | Constants and all `Data`/`Interp` values are inspected. | `supply_reconciliation_workflow.py:12381-12410,13261-13288` | SEED-004 | `confirmed_rule` |
| SEED-C007 | A zero missing-ID row can be intended as a reset, but cannot be assumed harmless because it will not address the LEAP object. | Applies to constant zero, empty, and all-zero series. | Legacy code assumed LEAP skipped `-1` rows. | SEED-003 blocks required-ID failure; SEED-005 labels reset intent for review. | `confirmed_rule`; exact exception policy remains unresolved |
| SEED-C008 | Active Output Share siblings under one Output Fuels parent sum to exactly 100%. | Per economy/region/scenario/year. Positive output is normalized; zero years use a fallback. | `transformation_analysis_utils.py:3034-3170`, especially `_build_output_share_lookup` and `_normalize_output_shares_for_export`. | SEED-006 and share tests | `confirmed_rule` |
| SEED-C009 | Output Share values are non-negative and rounded residual is assigned deterministically. | Legacy zero-data order: carry the prior nonzero profile, else first sorted fuel gets 100%. | `transformation_analysis_utils.py:2998-3031,3084-3170` | Current `transformation_record_builder.py:1169-1350` retains the pattern. | Normalization is `confirmed_rule`; fallback identity is `unresolved_modelling_decision` |
| SEED-C010 | Active Process Share siblings under one Processes parent sum to 100%. | Per economy/region/scenario/year; activity is output first, then feedstock plus losses. | `transformation_analysis_utils.py:2922-2997` | SEED-007; current builder uses the same activity basis. | `confirmed_rule` |
| SEED-C011 | Zero-activity Process Share behaviour. | Legacy equal-split all processes; current generic builder leaves all zero; supply-specific code makes a single process 100%. | Legacy `transformation_analysis_utils.py:2984-2997`; current `transformation_record_builder.py:1175-1188`; `supply_leap_io.py:380-430`. | Validator treats an all-zero Output/Process group as inactive information. | `unresolved_modelling_decision` |
| SEED-C012 | Feedstock Fuel Share siblings under each process sum to 100%. | Per economy/region/scenario/year; input 0–1 is converted to percent and negatives clipped. | `transformation_analysis_utils.py:2284-2401,2404-2472` | SEED-008; current `transformation_record_builder.py:419-660` | `confirmed_rule` |
| SEED-C013 | Missing feedstock years copy the nearest nonzero profile, preferring a future year on equal distance. If no profile exists, one label is anchored at 100%. | Full configured scenario year window. | `transformation_analysis_utils.py:2284-2401` | Current `transformation_record_builder.py:475-567` | `unresolved_modelling_decision` (the 100% invariant is confirmed; which fuel receives fallback is not) |
| SEED-C014 | Feedstock catalog reset rows are measure- and process-scoped so one workflow does not erase another workflow's values. | All exported scenarios and configured years; unwritten branches are zero, with one feedstock anchor where LEAP requires it. | `transformation_analysis_utils.py:3721-4056`; comments explicitly preserve other researchers' data. | Current `transformation_record_builder.py:1914-2180` | `confirmed_rule` |
| SEED-C015 | Auxiliary Fuel Use is derived from absolute losses/own-use relative to output, with zero-safe handling. | Scenario profiles inherit their source data window. | `transformation_analysis_utils.py:1157-1215,2070-2100`; balance sign convention in global instructions. | `transformation_series_utils.py:99-143` | `confirmed_rule` for sign/ratio; source-boundary choices are existing design decisions under INIT-002 |
| SEED-C016 | Process Efficiency is exported as percent, converting ratio-scale inputs. | Configured scenario window. | `transformation_analysis_utils.py:2475-2515,3458-3477` | Current transformation record builder. | `confirmed_rule` |
| SEED-C017 | A series expression must cover its configured scenario year window; constants apply across years. | Required years are caller configuration, not inferred from a backup. | `resolve_scenario_year_range` at legacy lines 2245-2265 and expression builders at 3564-3615. | SEED-009 | `confirmed_rule`; exact windows are configuration |
| SEED-C018 | Required scenario coverage is checked per Branch Path + Variable + Region. | Required scenarios are caller configuration. June USA happens to contain Current Accounts, Reference, and Target, but is not authoritative. | Legacy global scenario lists and workflow-specific filters vary. | SEED-010 | `confirmed_rule`; scenario set is configuration |
| SEED-C019 | `Data(...)` and `Interp(...)` with identical points are not automatically equivalent. | Interpolation between points differs. | Legacy exporters use both forms and LEAP import method settings. | Existing comparator expression-kind test. | `confirmed_rule` for comparison; classification of a deliberate form change is human review |
| SEED-C020 | Branches must exist in the canonical full-model export before final import. | Case-insensitive name matching is diagnostic only; IDs remain canonical. | Legacy `functions/patch_baseline_seeds.py:292-472`. | SEED-011 | `confirmed_rule` (CROSS-001) |
| SEED-C021 | Aggregate 9th fuel labels are not real LEAP branches and must not be emitted as ordinary leaves. | Current explicit set: Biomass, Coal, Gas, Others, Municipal solid waste non and renewable. | `aggregated_demand_workflow.py:57-67,307-318`; `patch_baseline_seeds.py:282-290`. | Existing `VALIDATION_IGNORE_FUEL_NAMES`; INIT-001. | `confirmed_exception` |
| SEED-C022 | Unknown non-excepted branch paths remain errors; allowlists are explicit. | No automatic expansion from observed backup rows. | Legacy validator had prefix and fuel allowlists. | SEED-011 exception records match explicit fields. | `confirmed_rule` |
| SEED-C023 | Demand zeroing excludes the aggregated-demand branch and Other loss and own use branches, preserving values owned by their workflows. | Scenario coverage follows the zeroing workbook. | `aggregated_demand_workflow.py:182-197,918-1008`; `supply_reconciliation_workflow.py:1065-1075`. | Current aggregated demand workflow. | `confirmed_exception` |
| SEED-C024 | Resources paths are classified against the full-model export; unmatched all-zero rows may be dropped, while unmatched nonzero rows are diagnostic failures. | All scenarios/years. | `supply_reconciliation_workflow.py:11400-11455,12275-12340`. | Current supply reconciliation functions. | `confirmed_rule` |
| SEED-C025 | Refining removes subtotal/aggregate fuel branches before import and applies capacity logic from historical production. | Workflow-specific year range. | `refining_workflow.py:257-399`. | Current refining workflow. | Subtotal exclusion is `confirmed_rule`; exact capacity heuristic is an `implementation_detail` pending modelling review |
| SEED-C026 | Transfers use configured process relationships and transformation share/zero-fill builders. | Current Accounts handling is explicitly configurable. | `transfers_workflow.py:1754+`; `configuration/workflow_config.py:240-252`. | Current transfers workflow and shared transformation functions. | `implementation_detail`; mapping semantics remain owned by `leap_mappings` |
| SEED-C027 | `Minimum Share of Production` exists in the model but is not a sibling allocation that must sum to 100%. | Constraint semantics, not an allocation group. | Present in `data/full model export.xlsx`; absent from the June USA seed. | Deliberately excluded from `SHARE_VARIABLE_RULE_IDS`. | `implementation_detail` |
| SEED-C028 | Workbook metadata (`Units`, `Scale`, `Per...`) and LEAP preamble are preserved from templates. | All rows/scenarios. | Legacy Excel writers and `AGENTS_LEAP_EXPORT.md`. | Comparator metadata differences and existing workbook writers. | `confirmed_rule` |

## Duplicate handling

The resolved diagnostic row is selected without using workbook order:

1. If exactly one physical row has all four valid IDs, select it.
2. Otherwise sort by ID validity, normalized ID tuple, expression signature, and
   metadata signature.
3. Exact duplicates are removable, but still violate physical logical-key
   uniqueness until removed.
4. Any conflicting duplicate blocks final import. Multiple valid-ID rows and
   possible insufficient-key cases are never chosen as authoritative.
5. Share and coverage validation runs on the resolved rows while retaining the
   duplicate finding as evidence.

## Coverage validation

Year and scenario checks are opt-in configuration. A caller supplies required
years and scenarios appropriate to the workflow. This avoids using the June
backup's Current Accounts/Reference/Target layout as an implicit standard.

## Deferred validation and reporting

Baseline-seed production is expensive, so ordinary validation violations must
not stop the run at the first failing producer, economy, or rule. Independently
runnable producer and validation stages continue while accumulating findings.
After all viable stages have run, the system writes consolidated diagnostics
and only then raises a summary exception and blocks final import-workbook
creation or replacement.

An unexpected fatal error may stop processing when safe continuation is not
possible, but all findings accumulated up to that point must be written before
the error is re-raised. Deferring an exception never permits invalid rows to
reach a final LEAP import workbook. Diagnostics must identify the source
workflow, logical key, scenario and year where applicable, rule ID, severity,
blocking status, and reason.

## Unresolved modelling decisions

1. **Zero-activity Process Share.** Choose equal allocation (legacy generic
   builder), all-zero inactive allocation (current generic builder), or a
   single deterministic 100% anchor. Equal shares keep totals valid but create
   arbitrary activity allocation; all-zero may be acceptable only when LEAP
   truly treats the module as inactive. Modeller question: what must LEAP
   receive for a multi-process module with no activity in a year?
2. **Output Share fallback fuel.** The first sorted fuel gets 100% before any
   nonzero observation; later gaps carry the last nonzero profile. This is
   deterministic but not necessarily meaningful. Modeller question: should the
   fallback be configured by module, use nearest activity, or leave the module
   inactive?
3. **Feedstock fallback fuel/profile.** Legacy/current logic uses the nearest
   valid profile, then a deterministic first-label anchor. The June USA Heat
   plant interim valid-ID rows allocate the Current Accounts feedstock anchor
   to lignite while a conflicting `-1` row allocates Other bituminous coal.
   Modeller question: is the anchor a LEAP import workaround or an intended
   physical allocation, and which fuel should receive it?
4. **Zero missing-ID reset exceptions.** CROSS-001 requires review, but no
   approved no-op exception register exists. Modeller question: should any
   final workbook retain such rows, or must every reset row resolve to a real
   LEAP ID?
5. **Canonical scenario windows.** Workflows differ in Current Accounts and
   projection coverage. Modeller question: define required years for Current
   Accounts, Reference, and Target for each baseline-seed producer.
6. **Refining capacity heuristic.** Legacy code derives Exogenous Capacity from
   Historical Production. Modeller question: retain this as policy or replace
   it with a capacity-data source?

## June fixture provenance and deferred work

The focused fixture used during development is
`data/backup_tgt_ref_ca_20260625/leap_import_baseline_seed_20_USA_20260620.xlsx`,
economy `20_USA`, modified 2026-06-26 23:11 local time, size 511,767 bytes. It
contains Current Accounts, Reference, and Target. Tests read only the known Heat
plant interim logical key; the backup remains provisional.

Deferred until a producer-stable snapshot is explicitly frozen:

- all-economy reference qualification;
- classification of every candidate/reference difference;
- treating any backup defect as an accepted exception;
- fresh production baseline generation or deep USA output review;
- producer changes to remove duplicate rows at source.
