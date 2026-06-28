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
| SEED-C007 | A zero missing-ID row can be intended as a reset, but cannot be assumed harmless because it will not address the LEAP object. It blocks by default. | Applies to constant zero, empty, and all-zero series. A deliberate exception must identify `rule_id` and at least one exact measure/logical-key/provenance field. | Legacy code assumed LEAP skipped `-1` rows. | `validate_exception_records`; final-writer `validation_exceptions`; scoped-exception tests | `confirmed_rule`; no production exception is currently configured |
| SEED-C008 | Output Share groups contain every canonical Output Fuels sibling and sum to exactly 100%. Unused siblings are explicit zero rows. | Per economy/region/scenario/year. Positive output is normalized whether its source total is below or above 100%; an isolated zero year uses the nearest genuine profile. | `transformation_analysis_utils.py:3034-3170`, especially `_build_output_share_lookup` and `_normalize_output_shares_for_export`. | SEED-006 and share tests; INIT-003 | `confirmed_rule` |
| SEED-C009 | Output Share values are non-negative and rounded residual is assigned deterministically. A synthetic 100% anchor is considered only when no configured year has genuine sibling values and relevant Exogenous Capacity is explicitly zero. | Full configured scenario window; no producer fallback is currently configured, so the final writer uses the alphabetically first canonical path. | `transformation_analysis_utils.py:2998-3031,3084-3170` | `baseline_seed_validation.complete_canonical_share_groups`; canonical-group tests | `confirmed_rule`; alphabetical fallback is a documented `implementation_detail` |
| SEED-C010 | Process Share groups contain every canonical Processes sibling and sum to 100%. Unused siblings are explicit zero rows. | Per economy/region/scenario/year; activity is output first, then feedstock plus losses. | `transformation_analysis_utils.py:2922-2997` | SEED-007; INIT-003 | `confirmed_rule` |
| SEED-C011 | A wholly synthetic Process Share profile is permitted only when no configured year has genuine sibling activity and relevant Exogenous Capacity is explicitly zero. | Legacy equal-split, all-zero, and supply-specific single-anchor behaviours are replaced by the common final-write rule. | Legacy `transformation_analysis_utils.py:2984-2997`; `supply_leap_io.py:380-430`. | `complete_canonical_share_groups`; zero-capacity and positive-capacity tests | `confirmed_rule` |
| SEED-C012 | Feedstock Fuel Share groups contain every canonical Feedstock Fuels sibling and sum to 100%. Unused siblings are explicit zero rows. | Per economy/region/scenario/year; input 0–1 is converted to percent and negatives clipped. | `transformation_analysis_utils.py:2284-2401,2404-2472` | SEED-008; INIT-003 | `confirmed_rule` |
| SEED-C013 | Missing feedstock years copy the nearest nonzero profile. A synthetic anchor is considered only when no configured year has a genuine profile and the owning process's Exogenous Capacity is explicitly zero. | Full configured scenario year window. | `transformation_analysis_utils.py:2284-2401` | Producer preserves zero profiles; `complete_canonical_share_groups` applies the capacity gate and fallback. | `confirmed_rule` |
| SEED-C014 | Canonical sibling reset rows are measure- and ownership-scoped so one workflow does not erase another workflow's values. Every unused canonical sibling in an owned Output Share, Process Share, or Feedstock Fuel Share group is written as zero. | All exported scenarios and configured years. | `transformation_analysis_utils.py:3721-4056`; comments explicitly preserve other researchers' data. | Template-driven completion in `baseline_seed_validation`; partial-patch rejection in `patch_baseline_seeds`; canonical-group tests | `confirmed_rule` |
| SEED-C015 | Auxiliary Fuel Use is derived from absolute losses/own-use relative to output, with zero-safe handling. | Scenario profiles inherit their source data window. | `transformation_analysis_utils.py:1157-1215,2070-2100`; balance sign convention in global instructions. | `transformation_series_utils.py:99-143` | `confirmed_rule` for sign/ratio; source-boundary choices are existing design decisions under INIT-002 |
| SEED-C016 | Process Efficiency is exported as percent, converting ratio-scale inputs. | Configured scenario window. | `transformation_analysis_utils.py:2475-2515,3458-3477` | Current transformation record builder. | `confirmed_rule` |
| SEED-C017 | A series expression must cover its configured scenario year window; constants apply across years. | Default: Current Accounts = 2022; Reference/Target = 2023–2060. Base and final years are configurable. | `resolve_scenario_year_range` at legacy lines 2245-2265 and expression builders at 3564-3615. | `workflow_config.get_baseline_seed_validation_years`; SEED-009; writer-window tests | `confirmed_rule` |
| SEED-C018 | Required scenario coverage is checked per Branch Path + Variable + Region. | Required scenarios are caller configuration. June USA happens to contain Current Accounts, Reference, and Target, but is not authoritative. | Legacy global scenario lists and workflow-specific filters vary. | SEED-010 | `confirmed_rule`; scenario set is configuration |
| SEED-C019 | `Data(...)` and `Interp(...)` with identical points are not automatically equivalent. | Interpolation between points differs. | Legacy exporters use both forms and LEAP import method settings. | Existing comparator expression-kind test. | `confirmed_rule` for comparison; classification of a deliberate form change is human review |
| SEED-C020 | Branches must exist in the canonical full-model export before final import. | Case-insensitive name matching is diagnostic only; IDs remain canonical. | Legacy `functions/patch_baseline_seeds.py:292-472`. | SEED-011 | `confirmed_rule` (CROSS-001) |
| SEED-C021 | Aggregate 9th fuel labels are not real LEAP branches and must not be emitted as ordinary leaves. | Current explicit set: Biomass, Coal, Gas, Others, Municipal solid waste non and renewable. | `aggregated_demand_workflow.py:57-67,307-318`; `patch_baseline_seeds.py:282-290`. | Existing `VALIDATION_IGNORE_FUEL_NAMES`; INIT-001. | `confirmed_exception` |
| SEED-C022 | Unknown non-excepted branch paths remain errors; allowlists are explicit. | No automatic expansion from observed backup rows. | Legacy validator had prefix and fuel allowlists. | SEED-011 exception records match explicit fields. | `confirmed_rule` |
| SEED-C023 | Demand zeroing excludes the aggregated-demand branch and Other loss and own use branches, preserving values owned by their workflows. | Scenario coverage follows the zeroing workbook. | `aggregated_demand_workflow.py:182-197,918-1008`; `supply_reconciliation_workflow.py:1065-1075`. | Current aggregated demand workflow. | `confirmed_exception` |
| SEED-C024 | Resources paths are classified against the full-model export; unmatched all-zero rows may be dropped, while unmatched nonzero rows are diagnostic failures. | All scenarios/years. | `supply_reconciliation_workflow.py:11400-11455,12275-12340`. | Current supply reconciliation functions. | `confirmed_rule` |
| SEED-C025 | Refining removes subtotal/aggregate fuel branches before import and sets Exogenous Capacity from Historical Production using Million Gigajoules/Year metadata. | Current Accounts base year and projection scenario window. | `refining_workflow.py:257-399`. | `REFINING_USE_HISTORICAL_PRODUCTION_CAPACITY_HEURISTIC`; refining capacity policy test | Retained `confirmed_rule` |
| SEED-C026 | Transfers use configured process relationships and transformation share/zero-fill builders. | Current Accounts handling is explicitly configurable. | `transfers_workflow.py:1754+`; `configuration/workflow_config.py:240-252`. | Current transfers workflow and shared transformation functions. | `implementation_detail`; mapping semantics remain owned by `leap_mappings` |
| SEED-C027 | `Minimum Share of Production` exists in the model but is not a sibling allocation that must sum to 100%. | Constraint semantics, not an allocation group. | Present in `data/full model export.xlsx`; absent from the June USA seed. | Deliberately excluded from `SHARE_VARIABLE_RULE_IDS`. | `implementation_detail` |
| SEED-C028 | Workbook metadata (`Units`, `Scale`, `Per...`) and LEAP preamble are preserved from templates. | All rows/scenarios. | Legacy Excel writers and `AGENTS_LEAP_EXPORT.md`. | Comparator metadata differences and existing workbook writers. | `confirmed_rule` |
| SEED-C029 | Interim electricity, CHP, and heat calculations use only their corresponding `09_*` transformation sectors. Positive signed values are outputs and negative signed values are inputs. All `18_*` and `19_*` values are prohibited. | Electricity: `09_01_electricity_plants`; CHP: `09_02_chp_plants`; heat: `09_x_heat_plants`. | Confirmed modeller decision; INIT-004. | Approved/forbidden constants and selection validation in `electricity_heat_interim_workflow.py`; `test_power_interim_output_sector_config.py` | `confirmed_rule` |

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

The production default is centralized in `workflow_config.py`: Current
Accounts covers the configurable base year (2022), while Reference and Target
cover base year + 1 through the configurable final year (2023–2060). Rule
`SEED-012` also requires every configured producer to supply a readable source
workbook for every requested economy; a producer cannot silently disappear
from one economy's final seed.

Validation exceptions are disabled by default. `validation_exceptions` entries
must include `rule_id` and at least one exact field among `Variable`, `Branch
Path`, `Scenario`, `Region`, `source_workflow`, `source_file`, or `year`. For
example, a deliberately reviewed zero reset could match `SEED-003`, `Variable`,
and `Branch Path`. Such an exception only changes blocking status; it does not
make a `-1` ID effective in LEAP, so it should remain exceptional.

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

## Resolved modelling decisions

1. Missing-ID zero resets block by default, with a narrow exact-match exception
   mechanism available when a modeller explicitly approves a particular
   measure/key. No production exception is configured.
2. Scenario coverage defaults to Current Accounts 2022 and Reference/Target
   2023–2060. The base and final years are centralized configuration values.
3. Refining retains the Historical Production → Exogenous Capacity heuristic.

## Production-readiness comparison (2026-06-28)

The seven active producer families correspond to those in `leap_utilities`,
but the active final writer adds canonical ID enrichment, deterministic
duplicate handling, complete share groups, producer/economy coverage, atomic
patch checks, and deferred consolidated failure. Demand-zeroing workbooks are
now included in the final baseline-seed source set rather than only being
generated/imported separately.

The June `20_USA` backup is useful for branch/variable coverage comparison but
is not an acceptance oracle. It contains 4,596 physical rows, including 3,558
rows participating in duplicate logical keys and more than 3,100 missing IDs.
Validation against the current template and configured windows reports 5,382
blocking findings, dominated by duplicates, missing IDs, and year coverage.
The active writer is intentionally required to reject those conditions rather
than reproduce them.

Code-path and unit-level readiness is complete. Final operational qualification
still requires one fresh, non-importing `20_USA` run after source data and LEAP
template availability are confirmed. That run must produce a candidate with no
blocking consolidated findings and then be compared structurally and
numerically with the June backup. A 21-economy qualification remains deferred.

One cross-repository dependency remains before the result can be called fully
canonical: aggregated demand and own-use/loss still read `leap_mappings.xlsx`,
and interim display-name resolution still reads `master_config.xlsx`. The new
canonical `leap_mappings/config/outlook_mappings_master.xlsx` must first be
connected and qualified by mapping task M2, then these initialisation producers
must be migrated under Phase 3. Until then this repository can reproduce the
legacy mapping basis with stronger workbook safety, but cannot claim that all
mapping semantics are newer or better than legacy.

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
