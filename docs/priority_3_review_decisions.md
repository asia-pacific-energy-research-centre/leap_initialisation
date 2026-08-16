# Priority 3 review decisions

**Prepared:** 2026-08-13  
**Purpose:** a human-review packet for the decisions deliberately excluded from
the autonomous Priority 1–2 work.  
**Status:** review only; this file does not replace the owning repositories'
work queues.

## How to use this document

Sections are independent unless explicitly folded together. P3-03 is now part
of P3-02 because rebuild and patch severity should use the same finding
classification. Record a choice in each remaining **Decision** line and, where
useful, add a short reason. After review, implementation should update the named
owning queue rather than creating another backlog here.

## Decision summary

| ID | Decision | Owner / authoritative queue | Suggested choice | Your oversight |
|---|---|---|---|---|
| P3-01 | Keep standalone coke/blast detail beside inclusive own-use rows, or introduce replacement semantics | `leap_mappings` MAPQ-046 | **Approved: keep mapping detail; dashboard uses inclusive frontier** | Completed 2026-08-16 |
| P3-02 | Classify baseline-seed findings consistently for full rebuilds, patches, and promotion | `leap_initialisation` queue [29] / INIT-005 | LEAP-structure migration lag remains non-blocking; genuine integrity defects retain their own severity | Policy confirmed 2026-08-16; better classifier still needed |
| P3-03 | Surgical-patch severity | Folded into P3-02 | Use the same finding classification as full rebuilds, not a blanket stricter mode | No separate decision |
| P3-04 | Cross-economy combined workbooks | `leap_initialisation` queue [26] | **Retired in sequential and parallel runs** | Decision confirmed 2026-08-16; implementation complete |
| P3-05 | How initialisation receives the generated mapping master (D3.4) | `leap_initialisation` INITQ-020; mapping semantics owned by `leap_mappings` | **Approved: prefer live `leap_mappings`; committed read-only fallback** | Decision confirmed 2026-08-16; implementation pending |
| P3-06 | Generalize missing-9th-sector filling beyond gas processing | `leap_initialisation` queue [20] | Inventory first; approve family-specific rules individually | Required per model family |
| P3-07 | Quarantine/delete old outputs, temporary directories, branches and worktrees | Mapping MAPQ-013/MAPQ-023; dashboard DASHQ-014 | Quarantine outputs; remove only proven-superseded Git objects | Required before destructive work |
| P3-08 | Remaining mapping authority/frontier/input-contract choices | Mapping MAPQ-019/MAPQ-020/MAPQ-021 | Use published extracts and named frontiers; review ESTO definitions row by row | Required: domain semantics |

---

## P3-01 — Coke-oven and blast-furnace detail-retention policy

**Decision:** ☒ Keep both mapping views; ordinary dashboards use only the inclusive frontier ☐ Replace detail with inclusive rows ☐ Defer

**Status:** Complete. No further implementation or mapping-pipeline rerun is
required for this decision.

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
- The complete dashboard test module passes: 119 tests.
- Mapping data and rollup semantics were not changed while closing this
  decision, so the completed 2026-08-13 full-pipeline evidence remains valid.
  Do not schedule another full mapping-pipeline run solely for P3-01.
- At the next normally scheduled all-economy dashboard render, confirm that
  `10.01.05` and `10.01.07` remain absent from ordinary chart manifests. This
  is a non-blocking confirmation, not unfinished P3-01 work.
- The implementation and decision records are committed locally in
  `leap_dashboard` (`00210a0`), `leap_mappings` (`33042b1`), and
  `leap_initialisation` (`4ef91ce`). Pushing those commits is the only remaining
  administrative follow-up.

Reopen P3-01 only if a future downstream export must physically exclude the
standalone identities. That would require an exact rule-level replacement
selector plus a complete four-source pipeline and all-economy dashboard rerun.

---

## P3-02 — Baseline-seed finding classification and LEAP migration lag

**Decision:** **Confirmed 2026-08-16.** Missing rows caused by pending LEAP-area
structure updates remain warnings. LEAP updates are deliberately batched and
performed periodically rather than every time a missing branch is detected.

### Current behavior

The central BSA-001–BSA-010 package runs after physical workbook write/readback.
The production setting
`BASELINE_SEED_VALIDATION_BLOCKING_FINDINGS_ARE_WARNINGS = True` exists because
many current missing rows are expected differences between the desired model
structure and LEAP areas that have not yet received the next periodic structure
update. Routine seed work must continue while that migration backlog exists.

The problem is not that warning mode is temporary. It may remain the normal
operating mode indefinitely. The problem is that one global switch cannot
distinguish expected LEAP-structure lag from unrelated defects such as broken
share groups, duplicate keys, serialization loss, wrong-economy IDs, or missing
producer evidence.

### Confirmed policy

1. A missing LEAP branch attributable to a pending periodic area update is a
   visible, non-blocking migration finding.
2. Discovering another missing branch does not trigger an immediate LEAP area
   edit. It is added to the structure-migration backlog for the next coordinated
   LEAP update batch.
3. Full rebuilds and surgical patches use the same classification. A patch is
   not stricter merely because it is a patch.
4. Findings unrelated to LEAP structure retain their actual severity. Warning
   treatment for migration lag must not downgrade a duplicate, invalid share
   group, serialization loss, wrong template/IDs, or missing required evidence.
5. Promotion may proceed with declared migration warnings. Promotion policy
   should consider unresolved non-migration integrity findings separately.

### Recommendation

Replace the global all-findings downgrade with one shared classifier used by
the full writer, patcher, final-artifact gate, and promotion check. At minimum,
every missing-structure finding should carry:

- a stable finding or backlog ID;
- economy and normalized branch path;
- classification: `known_migration_backlog`, `new_migration_candidate`, or
  `not_structure_migration`;
- first-seen and last-seen dates/run IDs;
- affected workflow and current value/materiality;
- review status and notes for the next LEAP update batch;
- the template/version where the branch becomes available, once migrated.

Both known and newly detected structural gaps should remain non-blocking, but a
new candidate should be prominent in the migration report until reviewed. Once
LEAP templates are refreshed, the next validation should automatically close
backlog entries that are now present and flag stale exceptions rather than
silently retaining them forever.

Do not require `SHADOW_PASS` for promotion while that status treats declared
LEAP-structure lag as failure. Define acceptance as: required checks completed;
no unresolved non-migration integrity failure; migration warnings fully
reported. The twelve aggregate-demand placeholders are examples of this class,
not the only permanent exceptions.

### Evidence and completion

- Authority: `docs/work_queue.md` [29].
- Contract: `docs/baseline_seed_final_artifact_contract.md`.
- Review: `docs/baseline_seed_gate_consolidation_review.md`.
- Improvement complete when one classifier drives rebuild, patch, artifact,
  and promotion reporting; known/new migration findings are separated; genuine
  integrity failures are no longer downgraded by the migration policy; and
  periodic template refreshes reconcile the backlog automatically.

---

## P3-03 — Surgical patching severity (folded into P3-02)

**Decision:** **No separate policy.** Use P3-02's shared finding classifier.

### Current behavior

The normal seed writer currently honors
`BASELINE_SEED_VALIDATION_BLOCKING_FINDINGS_ARE_WARNINGS`; the baseline patcher
does not pass that setting and therefore behaves more strictly. That is an
implementation inconsistency, not the desired policy.

### Trade-off

- A missing branch caused by scheduled LEAP migration remains the same missing
  branch whether encountered during a rebuild or a patch. It should not block
  either path.
- A patch can lack some fresh producer evidence, but that should be represented
  explicitly as absent/incomplete evidence—not by treating every validation
  family as stricter.
- Genuine invalidity must retain its severity in both paths.

### Recommendation

Route patch findings through the same classifier as rebuild findings. Allow
declared or newly identified LEAP-structure migration gaps to remain warnings.
Continue to refuse a patch for non-migration integrity failures or when the
patch cannot provide evidence required to prove that its changed scope is safe.

### Evidence and completion

- Authority/evidence: `docs/work_queue.md`, patcher verification under the
  economy-template routing work.
- Complete together with P3-02, with paired rebuild/patch tests proving the same
  finding receives the same classification and effective severity.

---

## P3-04 — Cross-economy combined workbooks

**Decision:** **Retired 2026-08-16.** No sequential or parallel run needs a
workbook containing multiple economies.

The sequential `supply_recon_run_*.xlsx` writer, its archive/configuration
controls, and the unused `merge_parallel_results_workbooks()` helper were
removed. Their workbook-specific tests were removed with them. This does not
remove `write_per_economy_combined_workbooks`: that function assembles the
producer workbooks into each economy's final LEAP-import seed and remains part
of the required output path.

Parallel parent aggregation now remains deliberately CSV-only: validation
findings, issue groups, source/template diagnostics, and conservation families.
The authoritative workbook artifacts are the independent
`leap_import_baseline_seed_<economy>_*.xlsx` files.

---

## P3-05 — Prefer the live mapping master, with a standalone fallback

**Decision:** **Confirmed 2026-08-16.** A user must be able to run
`leap_initialisation` without a sibling `leap_mappings` checkout, while a normal
developer checkout must use the live generated master from `leap_mappings` when
that repository is available. A fallback copy is committed under
`leap_initialisation/config/` and clearly named as a read-only generated
dependency.

### Confirmed ownership boundary

- `leap_mappings/config/outlook_mappings_single_axis.xlsx` remains the only
  human-edited mapping authority.
- `leap_mappings/config/outlook_mappings_master.xlsx` remains the generated
  production master.
- `leap_initialisation` receives an exact committed snapshot named
  `config/outlook_mappings_master_DO_NOT_EDIT.xlsx`.
- Initialisation first resolves
  `../leap_mappings/config/outlook_mappings_master.xlsx`. If that workbook
  exists and is readable and schema-valid, it is always selected.
- Only when the sibling workbook is unavailable does initialisation use
  `config/outlook_mappings_master_DO_NOT_EDIT.xlsx`.
- Users do not edit the snapshot. Mapping changes are made in `leap_mappings`,
  regenerated there, then synchronized into initialisation.

The local file is a **vendored fallback snapshot**, not a placeholder: its exact
contents affect standalone initialisation results. Runtime manifests must record
whether the sibling or fallback workbook was selected, its resolved path, its
SHA-256, and—when available—the source mapping commit.

### Refresh and commit policy

Do not create an automatic commit on every ordinary repository commit. Instead,
run a required synchronization check before committing or releasing mapping-
dependent initialisation changes:

1. regenerate and commit the master in `leap_mappings`;
2. copy it byte-for-byte to
   `leap_initialisation/config/outlook_mappings_master_DO_NOT_EDIT.xlsx`;
3. update a small fallback-provenance sidecar with the source repository commit, source
   path, workbook SHA-256, copy time, and schema/contract version where
   available;
4. validate the workbook schema and prove the copied SHA-256 equals the source;
5. commit the snapshot, sidecar, and any required initialisation compatibility
   changes together.

If the source workbook has not changed, the sync check should produce no Git
diff. A commit hook may run the check, but it must not silently rewrite or
commit files.

### Filename rationale

Use `outlook_mappings_master_DO_NOT_EDIT.xlsx`, not
`master_config-DO NOT EDIT.xlsx`. `master_config.xlsx` is already the name of a
retired legacy workbook under `config/legacy/`; reusing it would make the new
canonical snapshot look like the old format. Underscores also avoid unnecessary
path quoting while keeping the warning prominent.

### Failure behavior

- If the sibling workbook exists but is unreadable or schema-incompatible, fail
  clearly; do not silently hide a broken live mapping checkout by using the
  fallback.
- If no sibling workbook exists, a missing, unreadable, hash-mismatched, or
  schema-incompatible fallback fails clearly before workflow processing.
- There is no silent fallback to `config/legacy/master_config.xlsx`,
  or `config/legacy/leap_mappings.xlsx`.
- When both copies exist, the sibling is selected even if its hash differs from
  the committed fallback. Report the difference as a refresh reminder, not a
  reason to substitute the older fallback.

### Evidence and completion

- Authority: INITQ-020 and
  `docs/prompts/phase_3_canonical_mapping_migration_execution.md`, D3.4.
- Mapping semantics and generation remain owned by `leap_mappings`; only the
  immutable fallback snapshot is owned here.
- Complete when the snapshot and provenance file are committed, all canonical
  loaders implement and report sibling-first/fallback-second resolution, the
  sync/validation helper is notebook-safe, standalone tests run with no sibling
  repository present, and the portable release consumes an explicitly staged
  workbook under the same validation contract.

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
2. **P3-02/P3-03** — implement the confirmed shared migration classifier for
   rebuilds, patches, and promotion.
3. **P3-05** — closes the remaining cross-repository ownership ambiguity.
4. **P3-04** — complete; no further review required.
5. **P3-06** — approve the inventory before reviewing model-family rules.
6. **P3-08** — domain and mapping-governance decisions.
7. **P3-07** — cleanup last, after the decisions above identify which evidence
   must be retained.
