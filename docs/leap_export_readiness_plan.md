# LEAP Export Readiness Plan

## Purpose

Create one shared readiness framework for LEAP export workbooks while keeping
the individual checks responsible for different failure classes.

The framework should make it clear whether a workbook is ready to import into
LEAP, which producer generated each row, and exactly which check failed.

This plan follows the transfer-specific improvement:

1. Make transfer export generation run the shared fuel-branch preflight.
2. Add coverage tests for valid transfer-adjacent transformation paths and
   rejection of the legacy `Transformation\\Transfers\\...` root.
3. Then build the broader readiness framework described here.

## Design principles

- Keep check semantics separate. Do not replace all validation with one large
  validator.
- Share row reading, key normalisation, scope selection, reporting, and output
  manifests.
- Validate the combined workbook as well as producer-specific workbooks where
  the producer boundary matters.
- Treat `BranchID`, `VariableID`, `ScenarioID`, and `RegionID` as import identity
  checks, not fuel-catalog checks.
- Treat the fuel catalog as a shared union of exact LEAP branch structures.
- Preserve exact fuel labels. Report inconsistent labels across templates rather
  than merging them.
- Keep producer ownership explicit so transformation and transfer workbooks do
  not generate duplicate rows.
- Prefer diagnostics that survive the run over warnings visible only in logs.

## Target structure

```text
LEAP export readiness
├── shared workbook reader and key normalisation
├── source/provenance and producer ownership checks
├── fuel-branch catalog coverage
├── LEAP ID and Region validation
├── duplicate logical-key validation
├── transfer path and ownership validation
├── demand branch coverage validation
├── scenario/year/expression validation
├── conservation and balance checks
└── consolidated readiness report and manifest
```

## Common check result

Every check should be able to emit rows with a common shape:

```text
workbook
economy
scenario
branch_path
variable
producer
check_name
status
severity
reason
suggested_fix
```

Suggested statuses are `pass`, `warning`, `error`, and `skipped`. Suggested
severities are `info`, `warning`, and `blocking`.

Checks may also emit summary metadata:

```text
check_name
rows_checked
rows_failed
blocking_failures
diagnostic_path
```

## Implementation phases

### Phase 1 — Transfer preflight integration

- Run fuel-branch preflight explicitly for transfer exports.
- Confirm valid transfer-adjacent modules are covered by the shared catalog.
- Continue rejecting `Transformation\\Transfers\\...` legacy paths.
- Add focused tests for both cases.

Success criteria: a valid transfer export receives normal catalog coverage, and
legacy generic transfer paths fail before import.

### Phase 2 — Shared workbook and key utilities

Extract or standardise:

- LEAP sheet/header reading;
- branch-path normalisation;
- `(Branch Path, Variable, Scenario, Region)` logical keys;
- expression/year-column discovery;
- economy and producer inference;
- source-workbook provenance.

Success criteria: each producer uses the same row reader and key construction.

### Phase 3 — Common readiness runner

Create a small orchestration layer that accepts:

- workbook paths;
- producer name;
- economy/scenario scope;
- enabled checks;
- producer-owned branch scopes;
- output directory.

The runner should execute checks, write one consolidated findings CSV, write a
summary JSON, and return a structured result to the workflow.

It must support warning-only checks and blocking checks without duplicating
severity logic in every producer.

### Phase 4 — Migrate structural checks

Migrate these checks first:

- catalog branch coverage;
- missing or nonzero `BranchID=-1` rows;
- duplicate logical keys;
- Region/economy consistency;
- legacy transfer path detection;
- producer ownership and duplicate output detection.

These are the checks most directly related to silent import corruption.

### Phase 5 — Migrate content checks

Add or connect:

- scenario coverage;
- year-axis coverage;
- expression validity;
- required LEAP metadata;
- share-group completeness;
- conservation and total-balance checks.

Content checks should retain their existing domain-specific calculations. The
readiness runner should standardise their reporting, not rewrite their logic.

### Phase 6 — Combined-workbook gate

Run readiness checks after supply, transformation, transfers, demand, and
other-loss/own-use outputs have been combined.

The combined gate should verify:

- no duplicate logical keys;
- no producer ownership collisions;
- all nonzero rows resolve to the target economy template;
- branch paths exist in the shared catalog and target template;
- all blocking checks pass before LEAP import.

Producer-specific checks should still run earlier so failures can be traced to
the generating workflow.

## Branch-family coverage

| Branch family | Catalog coverage | Additional checks |
|---|---:|---|
| Transformation | Yes | process ownership, IDs, conservation |
| Transfer-adjacent transformation modules | Yes | transfer ownership and legacy-path rejection |
| Resources/Primary and Secondary | Yes | supply IDs and resource-path validation |
| Demand | Yes | demand scope, zero-fill, share/expression checks |
| Other loss/own use | By recognized LEAP path | producer provenance and import preflight |
| Transfers as a workflow | Via Transformation paths | transfer configuration and ownership |

## Rollout and safety

- Keep the existing individual checks active during migration.
- Compare consolidated findings with existing diagnostics for at least one NZ
  run and one combined export run.
- Do not delete old checks until their replacement has a registry entry, focused
  tests, and equivalent or better diagnostics.
- Keep the legacy fuel-catalog filename until all readers and external tooling
  have migrated; then remove it according to `docs/work_queue.md`.

## Completion criteria

The work is complete when:

- every export producer uses the shared workbook reader and readiness reporting;
- transfer exports run catalog preflight explicitly;
- the combined workbook has one documented readiness gate;
- every check appears in `docs/check_registry.md`;
- findings are written to durable CSV/JSON outputs;
- blocking failures prevent import;
- warning-only findings remain visible and attributable;
- focused producer tests and the NZ end-to-end validation run pass.

