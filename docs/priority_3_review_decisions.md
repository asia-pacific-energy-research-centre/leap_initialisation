# Priority 3 review decisions

**Prepared:** 2026-08-13  
**Purpose:** a human-review packet for the decisions deliberately excluded from
the autonomous Priority 1–2 work.  
**Status:** review only; this file does not replace the owning repositories'
work queues.

## How to use this document

Each section is an independent decision. You can approve one without deciding
the others. Record a choice in the **Decision** line and, where useful, add a
short reason. After review, implementation should update the named owning queue
rather than creating another backlog here.

## Decision summary

| ID | Decision | Owner / authoritative queue | Suggested choice | Your oversight |
|---|---|---|---|---|
| P3-01 | Keep standalone coke/blast detail beside inclusive own-use rows, or introduce replacement semantics | `leap_mappings` MAPQ-046 | **Approved: keep mapping detail; dashboard uses inclusive frontier** | Completed 2026-08-16 |
| P3-02 | When baseline-seed findings should block runs and promotion | `leap_initialisation` queue [29] / INIT-005 | Keep audit mode until the stated real-run evidence exists; then block promotion, not artifact generation | Required: release policy |
| P3-03 | Whether surgical seed patches should remain stricter than full rebuilds | `leap_initialisation` queue [12]/INIT-005 evidence | Keep patches strict | Required: operational policy |
| P3-04 | Activate the parallel parent combined workbook | `leap_initialisation` current execution roadmap item 2 | Do not activate by default yet; first prove real sequential equivalence | Approval after evidence |
| P3-05 | Ownership of rollup-rule reading (D3.4) | `leap_initialisation` INITQ-020; mapping contract owned by `leap_mappings` | Local reader against a frozen published schema contract | Required: cross-repo boundary |
| P3-06 | Generalize missing-9th-sector filling beyond gas processing | `leap_initialisation` queue [20] | Inventory first; approve family-specific rules individually | Required per model family |
| P3-07 | Quarantine/delete old outputs, temporary directories, branches and worktrees | Mapping MAPQ-013/MAPQ-023; dashboard DASHQ-014 | Quarantine outputs; remove only proven-superseded Git objects | Required before destructive work |
| P3-08 | Remaining mapping authority/frontier/input-contract choices | Mapping MAPQ-019/MAPQ-020/MAPQ-021 | Use published extracts and named frontiers; review ESTO definitions row by row | Required: domain semantics |

---

## P3-01 — Coke-oven and blast-furnace detail-retention policy

**Decision:** ☒ Keep both mapping views; ordinary dashboards use only the inclusive frontier ☐ Replace detail with inclusive rows ☐ Defer

### Current behavior

The four NINTH rollups now create these inclusive Common identities:

- `09.08.01 Coke ovens (including own use)` from transformation `09.08.01`
  plus own use `10.01.05`;
- `09.08.02 Blast furnaces (including own use)` from transformation `09.08.02`
  plus own use `10.01.07`.

The complete 2026-08-13 pipeline conserved every mapped source at 100%, but
the standalone `10.01.05` and `10.01.07` rows remain available as detailed
views. This is the documented generic `apply_source_rollups()` behavior, not a
failed rollup.

### Options

1. **Keep both views.** Inclusive rows are the authoritative non-overlapping
   comparison frontier; standalone rows remain drill-down evidence. Consumers
   must select a frontier and must not sum both layers.
2. **Add replacement semantics.** Introduce an explicit per-rule mode that
   removes the standalone identities after constructing the inclusive row.
   This needs new source-once, conservation, lineage, and consumer tests.
3. **Change all `NON_EXPANDING` rules to replacement behavior.** This has the
   broadest blast radius and is not recommended without a full contract review.

### Recommendation

Option 1 was approved on 2026-08-16. It preserves useful diagnostics and the
established generic contract. Following the existing Gas works plants and Oil
refineries precedent, ordinary dashboard charts select the inclusive Coke ovens
and Blast furnaces leaves and suppress the parallel plain transformation and
standalone own-use rows. Mapping and diagnostic outputs retain those components
as lineage evidence. Option 2 remains appropriate only if a future downstream
export must physically exclude the standalone identities; option 3 must not be
introduced as an incidental fix.

### Evidence and completion

- Authority: `leap_mappings/docs/work_queue.md`, MAPQ-046.
- Focused verification: 76 tests passed.
- Full-run maximum conservation drift: `1.1641532182693481e-10`.
- MAPQ-046 assertions 3 and 6 now state that coexistence is intentional and
  consumer frontiers prevent double counting.
- Dashboard regression coverage applies the existing metadata-driven Gas works
  behavior to Coke ovens and Blast furnaces without duplicating mapping logic.
- If option 2 is approved, require an exact rule-level selector and rerun the
  complete four-source pipeline plus all-economy dashboards.

---

## P3-02 — Baseline-seed gate: audit, blocking, and promotion

**Decision:** ☐ Follow staged recommendation ☐ Keep warnings indefinitely
☐ Block immediately ☐ Defer

### Current behavior

The central BSA-001–BSA-010 final-artifact package runs after physical workbook
write/readback. Hard findings expose `would_block`, but the production setting
`BASELINE_SEED_VALIDATION_BLOCKING_FINDINGS_ARE_WARNINGS = True` lets a full run
finish. Promotion does not yet consume the acceptance manifest.

The repaired historical NZ artifact reached `SHADOW_WARN`, but that reused
already-produced rows and therefore did not exercise every upstream producer
fix. Enabling blocking now would turn a shadow contract into release policy
without the specified fleet evidence.

### Options

1. **Staged enforcement:** retain audit mode while gathering the required real
   runs, then make promotion require an accepted manifest.
2. **Block artifact generation immediately:** any hard BSA finding stops the
   run before a reviewable candidate is available.
3. **Warnings only indefinitely:** retain diagnostics but never make them a
   release gate.

### Recommendation

Choose option 1. It separates producing evidence from approving an artifact:

1. run a fresh full `12_NZ` producer with a unique label;
2. review a fresh real-template `20_USA` package;
3. run the intended all-economy set;
4. integrate the gate with the parallel parent evidence merge;
5. in a separate reviewed commit, require an accepted manifest for promotion.

Keep the twelve known aggregate-demand placeholders visible as non-blocking
BSA-005 warnings unless their LEAP branches are deliberately added.

### Evidence and completion

- Authority: `docs/work_queue.md` [29].
- Contract: `docs/baseline_seed_final_artifact_contract.md`.
- Review: `docs/baseline_seed_gate_consolidation_review.md`.
- Complete only when real-run evidence has zero unexplained `would_block`
  findings and promotion behavior is changed in its own reviewable commit.

---

## P3-03 — Should surgical patching be stricter than full rebuilds?

**Decision:** ☐ Keep patcher strict ☐ Match full-run warning mode ☐ Defer

### Current behavior

The normal seed writer honors
`BASELINE_SEED_VALIDATION_BLOCKING_FINDINGS_ARE_WARNINGS`; the baseline patcher
does not pass that setting and therefore uses strict validation. The divergence
was discovered while verifying NZ template/ID routing and is not currently
documented as policy.

### Trade-off

- A patch changes an existing artifact without rebuilding all producer
  evidence. Strict refusal reduces the chance of preserving or compounding an
  invalid seed.
- Matching the full-run warning mode makes patches easier to apply, but could
  allow an invalid old workbook to be carried forward under a warning policy
  designed for newly generated, fully diagnosed output.

### Recommendation

Keep the patcher strict and document the difference. If a seed fails strict
validation, regenerate it rather than patching it. Add a deliberate escape
hatch only if it is explicit per invocation, records the accepted findings,
and never becomes the default.

### Evidence and completion

- Authority/evidence: `docs/work_queue.md`, patcher verification under the
  economy-template routing work.
- Complete when the policy is recorded beside both call sites and a regression
  test proves the patcher remains strict while full-run audit mode remains
  configurable.

---

## P3-04 — Parallel combined-workbook activation

**Decision:** ☐ Require combined workbook ☐ Make it opt-in ☐ Keep disabled
☐ Defer pending real equivalence

### Current behavior

Process-based per-economy workers are safe and their standalone seed workbooks
are correct. `merge_parallel_results_workbooks()` can preserve the raw Export
preamble/header layout and has synthetic tests, but the parallel runner does
not invoke it. Diagnostic CSV families already have deterministic parent
merges.

### Missing evidence

- A real, sequential multi-economy combined workbook built from the same inputs.
- A cell/key/layout comparison between that workbook and the proposed parent
  merge.
- Failure/retry evidence proving no partial combined workbook can look complete.
- Confirmation of the intended ownership of shared proxy rows when more than
  one worker supplies them.

### Recommendation

Do not activate it by default yet. First run a bounded two-economy real-data
comparison. If equivalent, introduce the merged workbook as opt-in for one
release cycle while per-economy workbooks remain authoritative. Make it the
default only after a broader economy run and manifest review.

### Evidence and completion

- Authority: `docs/current_execution_roadmap.md`, item 2.
- Tests: `tests/test_parallel_economy_merge.py`.
- Acceptance: identical logical rows and values to the sequential artifact;
  identical LEAP preamble/header semantics; deterministic economy ordering;
  failed/missing workers make the merge fail closed.

---

## P3-05 — D3.4 rollup-rule reading ownership

**Decision:** ☐ Frozen published schema + local reader ☐ Shared Python helper
☐ Duplicate independent reader ☐ Defer

### Question

Should `leap_initialisation` read the rollup-rule sheets itself, or import a
Python helper from `leap_mappings`?

The repositories currently share data contracts, not Python runtime imports.
`leap_mappings` owns mapping semantics; `leap_initialisation` must not silently
reinterpret them, but it also should not depend on a sibling checkout's module
layout to run.

### Recommendation

Approve a **frozen published column contract with a small local reader and
contract tests**:

- `leap_mappings` owns and publishes the workbook schema and meaning;
- `leap_initialisation` owns only parsing/validation of that published schema;
- unknown/missing required columns fail clearly;
- no label inference or fallback mapping semantics are allowed locally;
- schema changes require coordinated contract/version updates.

This is the recommendation already drafted in the Phase 3 execution prompt,
but it was parked so it would not be decided independently of the mapping-side
work.

### Evidence and completion

- Authority: INITQ-020 and
  `docs/prompts/phase_3_canonical_mapping_migration_execution.md`, D3.4.
- Cross-repo boundary:
  `../leap_mappings/docs/handover/cross_repository_data_contracts.md`.
- Complete when the choice is recorded in
  `docs/special_rules_and_design_decisions.md`, the local reader docstring names
  the owning mapping contract, and contract tests pin required columns/modes.

---

## P3-06 — General missing-9th-sector modeling

**Decision:** ☐ Approve inventory/design only ☐ Approve selected families
☐ Enable a general fill rule ☐ Defer

### Current behavior

The only implemented foundation is for missing `09.06` gas-processing children:
their economy-specific ESTO base-year value is carried forward, then the
existing gas-process builder retains production, efficiency, feedstocks, and
outputs. A nonzero aggregate with no economy-specific parent or child evidence
is left unallocated and written to diagnostics; it does not borrow APEC ratios
or use an equal split.

### Why one universal rule is unsafe

Different families may require fixed values, historical ratios, capacity
assumptions, external drivers, or an explicit decision to remain unprojected.
Supply, transformation, transfers, demand, and losses/own-use can also overlap
unless ownership is assigned before filling.

### Recommendation

Approve only the inventory and ownership-routing phase now. For every candidate
pair record:

- ESTO base-year activity and 9th presence;
- whether an initialisation producer already emits it;
- exactly one owning workflow;
- the proposed projection method and why it fits that family;
- conservation, continuity, and duplicate-output evidence.

Then approve families individually. Keep `FILL_IN_MISSING_9TH_SECTORS` opt-in
until each approved family has diagnostics and tests. Do not enable a generic
carry-forward rule across all sectors.

### Evidence and completion

- Authority: `docs/work_queue.md` [20].
- Initial supported family: `09.06` gas processing only.
- Completion is incremental: a family is complete when ownership is unique,
  the rule is documented, false-mode output is unchanged, and conservation,
  base-year continuity, and no-duplicate tests pass.

---

## P3-07 — Output, temporary-directory, branch, and worktree cleanup

**Decision:** ☐ Approve reversible quarantine ☐ Approve named Git cleanup
☐ Approve both ☐ Defer

### Items currently preserved

- Large/stale mapping results covered by mapping MAPQ-013, including old
  `_rebuilt` and tree-artifact candidates. Some are fallbacks or release
  evidence rather than disposable copies.
- Proven-superseded mapping branches/worktrees under MAPQ-023.
- Dashboard stale branch/worktree cleanup under DASHQ-014, which is gated by
  recovery of any unique uncommitted diff.
- `.codex_tmp_rollup_fix/`, `.codex_tmp_balancing_flow/`, web-app `.claude/`,
  and `runtime_stats_remote.json`, all deliberately preserved because they were
  not created or fully owned by this work session.

### Recommendation

Use two separate approvals:

1. **Generated outputs:** move only a named, verified set into a dated
   quarantine; record source path, reason, hashes where material, and recovery
   path in the owning archive log. Do not broadly delete `results/` or
   `outputs/`.
2. **Git worktrees/branches:** prove each branch is merged or patch-equivalent,
   verify the worktree is clean and list reparse points, then use
   `git worktree remove <exact-path>`. Never recursively delete a worktree
   parent or follow a junction.

Temporary directories belonging to another agent should be removed only after
that agent's contents are inspected and confirmed redundant.

### Evidence and completion

- Mapping outputs: `../leap_mappings/docs/results_folder_cleanup_candidates.md`
  and MAPQ-013.
- Mapping Git objects: MAPQ-023.
- Dashboard Git objects: `../leap_dashboard/docs/work_queue.md`, DASHQ-014.
- Completion requires a before/after inventory and recovery statement; cleanup
  should never be bundled with mapping-semantic changes.

---

## P3-08 — Remaining mapping authority and frontier choices

**Decision:** record choices separately below.

### P3-08A — LEAP no-data input contract (MAPQ-019)

**Decision:** ☐ Published extract ☐ Direct sibling-repository read ☐ Defer

Recommendation: publish a versioned extract from `leap_initialisation` rather
than making `leap_mappings` reach into a sibling's mutable export tree. This
keeps runs reproducible and lets incomplete economy coverage be stated in the
artifact contract. Available balance exports do not yet cover all 21 economies,
so missing coverage must remain `unavailable`, not false/no-data.

### P3-08B — ESTO external definition authority (MAPQ-020)

**Decision:** ☐ Review current working set ☐ Defer with named rows/reasons

Recommendation: re-derive the review queue against the latest completed mapping
run before reviewing it. Decide each remaining definition row individually,
with source citations and rejected interpretations preserved. Do not carry the
old quoted row counts forward or accept candidates in bulk.

### P3-08C — Additive frontier ownership (MAPQ-021 / CROSS-002)

**Decision:** ☐ One universal frontier ☐ Several named frontiers ☐ Defer

Recommendation: publish **several explicitly named frontiers** when different
views genuinely need different non-overlapping boundaries. `leap_mappings`
must define membership and additivity; `leap_dashboard` may select a published
frontier for a chart but must never infer hierarchy from labels. Each chart
type should name its required frontier, and the metadata should make summing
across frontier layers impossible or visibly invalid.

### Completion

Record each choice in the mapping decision log and update the published mapping
metadata or cross-repository contract. These are semantic decisions: a clean
pipeline run is evidence that processing completed, not evidence that a choice
is conceptually correct.

---

## Suggested review order

1. **P3-01** — small, concrete mapping decision with completed run evidence.
2. **P3-03 and P3-02** — establish patch/run/promotion safety policy together.
3. **P3-05** — closes the remaining cross-repository ownership ambiguity.
4. **P3-04** — approve evidence collection, then decide activation.
5. **P3-06** — approve the inventory before reviewing model-family rules.
6. **P3-08** — domain and mapping-governance decisions.
7. **P3-07** — cleanup last, after the decisions above identify which evidence
   must be retained.

