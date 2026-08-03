# Baseline-seed final-artifact contract

Contract version: `1.0.0-audit`
Qualification status: implemented in audit/shadow mode; operational blocking
and promotion coupling are not enabled.

This contract describes the saved output, not the method used to construct it.
For example, “share siblings sum to 100%” is a contract requirement. Borrowing a
Reference profile or constructing a zero-capacity anchor is an upstream assembly
method traced to that requirement, not part of the requirement itself.

All ten rules have contract severity `hard`. In the current production
configuration their enforcement mode is `audit`. A failed rule therefore records
`would_block=true` and `run_was_blocked=false`; it is never relabelled warning.

| ID | Exact output requirement and applicability | Severity | Required evidence / tolerance / exceptions | Existing rule cross-reference | Expected upstream mechanism | Central implementation | Automated tests | Status |
|---|---|---|---|---|---|---|---|---|
| BSA-001 | Exactly one readable candidate workbook is supplied for every expected economy; no unexpected economy is silently included. Applies to the complete run artifact set. | hard | Explicit expected economies and explicit economy→candidate paths. No directory-only inference. No tolerance. Exceptions are not allowed for a missing expected economy. | SEED-012 / SEED-C018 | Producer coverage tracking and `write_per_economy_combined_workbooks` | `check_required_artifact_set` | valid set; missing expected workbook | implemented; audit |
| BSA-002 | Every candidate is a valid Excel workbook with `LEAP` and `FOR_VIEWING`; each sheet has the two-row LEAP preamble, a detectable header at row 2, and required logical-key/ID/metadata columns. | hard | Saved workbook bytes. Header row must be index 2; row 0 contains `Area:` and `Ver:`, row 1 is blank. Required columns: four IDs, four logical keys, `Scale`, `Units`, `Per...`; `LEAP` additionally requires `Expression`, `FOR_VIEWING` requires `Method`. No exception for an unreadable workbook. | SEED-C028; AGENTS_LEAP_EXPORT | `add_leap_preamble`, final writer sheet assembly, `read_leap_sheet` | `check_workbook_structure` | unreadable; missing sheets; damaged preamble/missing column | implemented; audit |
| BSA-003 | Physical final rows are unique by Branch Path + Variable + Scenario + Region. | hard | Reopened `LEAP` rows. Exact equality after shared key normalization; no tolerance or exception. | SEED-001/002; SEED-C001–C004 | `resolve_logical_duplicates` before write | `check_shared_seed_rules` via `resolve_logical_duplicates`/`validate_seed_rows` | duplicate final keys; post-write corruption | implemented; audit |
| BSA-004 | Every final branch/variable/scenario/region label resolves against the target economy template and all four saved IDs equal the IDs produced by the canonical shared template lookup. | hard | Reopened rows and explicit economy→template paths/hashes. Exact integer comparison. Narrow label aliases already owned by the shared lookup are allowed; no cross-economy ID borrowing. | SEED-003/011; SEED-C005/C020/C024 | `build_template_id_lookup`, `apply_template_ids`, economy template resolver | `check_template_identity` | valid IDs; ID/label mismatch | implemented; audit |
| BSA-005 | Every row with a nonzero or unparseable payload resolves to valid LEAP objects; a transformation process with nonzero capacity has usable process efficiency. | hard | Reopened rows, target template, expression parser. Zero tolerance `1e-12`. Existing exact SEED exceptions may be supplied and are recorded. | SEED-003/004/005/011/013; SEED-C005–C007/C030 | ID enrichment, optional-zero omission, process-efficiency producer guard | `check_shared_seed_rules` | nonzero unresolved payload; process efficiency parity | implemented; audit |
| BSA-006 | Every represented canonical Output Share, Process Share, and Feedstock Fuel Share group contains the complete template sibling set and totals 100% for every required scenario/year. Values are nonnegative. | hard | Reopened rows, template, explicit scenario→years. Sum tolerance `1e-6`; zero tolerance `1e-12`. Only exact recorded SEED exceptions apply. | SEED-006/007/008; SEED-C008–C014 | `complete_canonical_share_groups` (borrow/normalize/anchor methods) | `check_shared_seed_rules` using `validate_seed_rows` | incomplete sibling set; total !=100; local/final parity | implemented; audit |
| BSA-007 | Every required scenario is present and every series contains each required year for that scenario. | hard | Explicit expected scenarios and scenario→years; reopened expressions. No inferred default inside the validator. `Unlimited` is valid where existing SEED rules allow it. | SEED-009/010; SEED-C017/C021; INIT-006 | centralized configured windows and writer expression construction | `check_shared_seed_rules` | missing scenario/year | implemented; audit |
| BSA-008 | Every reset or gap-fill row declared by the run is within an explicitly authorized scope, is present in the final workbook, and serializes as zero. | hard | Explicit per-economy zero-scope manifest with logical key, `authorized`, mechanism/source, and exception ID where applicable. Zero tolerance `1e-12`. Missing evidence is `INCOMPLETE`, not pass. | SEED-C007/C014/C023; F1 registry | producer zero-fill/reset builders and their ownership/exclusion config | `check_authorized_zero_scope` | unauthorized zero row; missing evidence | implemented; audit |
| BSA-009 | Values expected at the post-assembly boundary are numerically conserved in the reopened `LEAP` expressions and `FOR_VIEWING` year cells. | hard | Explicit expected post-assembly rows per economy plus both saved sheets. Key/year comparison, tolerance `1e-9`. Missing expected evidence is `INCOMPLETE`. Producer-level energy conservation remains a separate local calculation. | SEED-C019 plus supply/transformation/balance-demand conservation policies | assembled resolved rows, expression builder, viewing-sheet projection | `check_serialized_value_conservation` | injected serialization loss; post-write corruption | implemented; audit |
| BSA-010 | Every configured check runs or records why it could not; every expected producer has explicit evidence; every required diagnostic exists; the BSA findings, summary, and manifest are complete and self-consistent. | hard | Expected producers, producer artifact/manifest paths, required diagnostic paths, output files and hashes. Missing evidence is `INCOMPLETE`. No blanket exception. | SEED-012/SEED-C018 and check-registry F4/F5 evidence | producer path registry, baseline validation reports, readiness reports | `check_diagnostics_and_manifests` plus `write_acceptance_package` | missing diagnostic; check exception; deterministic complete manifest | implemented; audit |

## Standard finding contract

Every emitted row contains: `run_id`, `economy`, `workbook`, `check_id`,
`contract_severity`, `enforcement_mode`, `status`, `would_block`,
`run_was_blocked`, `branch_path`, `variable`, `scenario`, `year`, `expected`,
`actual`, `evidence`, `source_workflow`, `exception_id`, and `suggested_fix`.

Statuses are `PASS`, `FAIL`, `EXCEPTED`, `INCOMPLETE`, or `CHECK_ERROR`. An
`EXCEPTED` finding names the exact reviewed exception and is not a pass, but it
does not contribute to `would_block`. Enforcement modes
are `disabled`, `audit`, `warn`, and `block`. `disabled` records a non-pass
`INCOMPLETE` row so a configured check cannot disappear silently.

## Acceptance package and shadow result

`run_baseline_seed_artifact_validation` writes, deterministically:

- `baseline_seed_artifact_findings.csv`;
- `baseline_seed_artifact_summary.csv`;
- `baseline_seed_artifact_manifest.json`.

The manifest records expected/produced economies, candidate/template paths and
SHA-256 hashes, this contract version, all check configuration and run status,
finding counts, hard audit findings, `would_block` counts, exceptions, missing
diagnostics, and the final shadow status.

Shadow status precedence is:

1. `SHADOW_INCOMPLETE` when any required check is disabled, incomplete, or
   errors;
2. `SHADOW_WOULD_FAIL` when a completed hard rule fails in audit/warn mode;
3. `SHADOW_WARN` for non-hard findings;
4. `SHADOW_PASS` otherwise.

The result also exposes `accepted`. In unit-configured `block` mode a hard
failure makes `accepted=false` and `run_was_blocked=true`. Production wiring in
this phase uses audit mode only and does not consult `accepted` before promotion.

## Traceability and promotion qualification

Producer/assembly mechanisms remain documented in
`baseline_seed_rule_inventory.md`, `check_registry.md`, and
`baseline_seed_gate_consolidation_review.md`. Promotion may later depend on this
manifest by checking `shadow_status == SHADOW_PASS`, no `would_block` findings,
and manifest/check completeness. That dependency is deliberately not enabled in
contract version `1.0.0-audit`.
