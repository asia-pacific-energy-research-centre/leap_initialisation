# Documentation audit — 2026-07-28

**Original scope:** the 93 project-owned tracked Markdown files present during
the first pass (`node_modules/` excluded). A preservation-first follow-up later
the same day reviewed all 102 tracked Markdown files then present, including
the archive and nine handover documents added after this census. Its complete
file-by-file decisions are in
[`documentation_disposition_20260728.md`](documentation_disposition_20260728.md).
Every claim was checked against `git` and current code, not only against the
documents' own self-reported status.

**Cross-repository correction after the file-by-file pass.** The final
contract check found that CROSS-001, INIT-003, the baseline rule inventory, and
the modeller runbook still called the retired
`data/full model export.xlsx` the live structure authority. Those active
instructions now point to the template resolved for each economy under
`data/leap_export_templates/`. The retired filenames remain visible only where
they are needed to explain history or identify code that still requires
migration.

**Editorial follow-up.** A second readability and accuracy pass corrected the
live ESTO and APEC-aggregate filenames, removed references to a nonexistent
workflow and subtotal workbook, linked the archived supply-side overview
explicitly, replaced an absent Word-guide reference with the maintained
handover guide, and aligned rejected-mapping guidance with `leap_mappings`.

**Method note.** This repository has a recorded history of documents that
describe themselves as done, blocked, or current and are none of those things.
Section A of `docs/prompts/handoff_20260723_docs_audit_and_cleanup.md` says so
explicitly. This audit therefore treats every status sentence as a claim to be
tested, and records the test.

## File census

| Location | Count |
|---|---|
| Repository root (`AGENTS.md`, `README.md`, `Untitled-2.md`) | 3 |
| `docs/` top level | 26 |
| `docs/prompts/` (33 prompts + `AGENTS.md` folder guide) | 34 |
| `docs/archive/` (any depth) | 25 |
| `docs/canonical_migration_diagnostics/README.md` | 1 |
| `codebase/` and `data/` READMEs | 4 |
| **Total** | **93** |

## Canonical documents

These are the documents a new owner should be pointed at. Everything else is
either reference detail, a work brief, or history.

| Document | Role | Verified state |
|---|---|---|
| `AGENTS.md` | Agent/contributor operating rules | Live, but carries stale sections — see D-01, D-02, D-03 |
| `docs/work_queue.md` | Technical backlog, item `[0]`–`[21]` | Live and the most detailed record; several items stale — see D-04, D-05, D-06 |
| `docs/current_execution_roadmap.md` | Operational roadmap and run policy | Live; contains one internal contradiction — see D-02 |
| `docs/check_registry.md` | Directory of all readiness checks (F1–F5) | Live and enforced by `tests/test_check_registry.py`; 2 broken links |
| `docs/supply_reconciliation_workflow_guide.md` | Modeller-facing guide to the main workflow | Live |
| `docs/special_rules_and_design_decisions.md` | Decision log (`INIT-*`, `SEED-*`, `CROSS-*`) | Live |
| `docs/process_map_human.md` / `docs/process_map_agent.md` | Orientation maps of the pipeline | Live, added `fd64048` |
| `docs/baseline_seed_balance_diagnostics.md` | Design + notebook usage for `[21]` | Live, current (2026-07-28) |
| `docs/results_update_dry_run_preview.md` | Update-strategy configuration and history | Live, current (2026-07-27) |
| `docs/prompts/initialisation_refactor_continuation.md` | Open-thread register T1–T11 | Live; the refactor worklist |
| `docs/prompts/AGENTS.md` | Prompt-folder policy + inventory | Policy live; inventory materially incomplete — see D-07 |

## Findings

### D-01 — `AGENTS.md` script LOC table is wrong in every row

`AGENTS.md` carries a self-applied staleness banner that corrects two rows.
Measured 2026-07-28, **all eight rows are wrong**, including the two the banner
claims to have fixed:

| Script | Table claim | Measured |
|---|---|---|
| `aggregated_demand_workflow.py` | 1,212 | 1,917 |
| `electricity_heat_interim_workflow.py` | 1,258 | 1,516 |
| `other_loss_own_use_proxy_workflow.py` | 2,923 (banner: 1,770) | 1,807 |
| `refining_workflow.py` | 535 | 554 |
| `supply_workflow.py` | 197 | 211 |
| `transformation_workflow.py` | 730 | 750 |
| `transfers_workflow.py` | 1,802 | 1,362 |
| `supply_reconciliation_workflow.py` | 13,628 (banner: 1,494) | 1,508 |

Related: `docs/prompts/phase_4_monolith_decomposition_execution.md` sizes
`codebase/supply_reconciliation/results_saver.py` at 4,024 LOC; it is now **4,508**.
The "re-decide `supply_results_saver`" task has grown, not shrunk, since it was
scoped.

**Action:** replace the table with a note that LOC is measured on demand, or
regenerate it. A table that has been wrong in every row twice is worse than no
table.

### D-02 — `AGENTS.md` and `current_execution_roadmap.md` both contradict the landed parallelism work

`AGENTS.md` § "Running two economies at once — supported by the workflow,
blocked by the config" states that a per-process override for `ECONOMIES` and
`RUN_OUTPUT_LABEL` does not exist, that launching a second run requires editing
the source file, and that the fix "belongs in the Phase 2 configuration work".

`docs/current_execution_roadmap.md` lines 19–22 repeat this: *"Do not run two
economies concurrently from this working tree… Safe parallelism waits for the
Phase 4 run-context work and per-process configuration overrides."*

**Both are contradicted by code in this repository**, and the same roadmap
document contradicts itself 70 lines later at its own item 2:

- `codebase/supply_reconciliation/parallel_runner.py` (13.6 KB) exists.
- `codebase/supply_reconciliation/parallel_merge.py` (14.8 KB) exists.
- `supply_reconciliation_workflow._apply_worker_snapshot_overrides()` is defined
  at `codebase/supply_reconciliation_workflow.py:715` and **called at line 1122**,
  reading a per-process `LEAP_WORKER_SNAPSHOT_JSON` snapshot before the preset
  broadcast.

That is exactly the per-process override both documents say does not exist. The
roadmap's item 2 records it as landed and verified 2026-07-23 (`9aab65b`) with a
two-economy concurrent smoke test.

**Action:** rewrite the `AGENTS.md` section and the roadmap's run-policy bullet
to state the real rule — parallelism goes through `supply_reconciliation/parallel_runner.py`,
and the prohibition applies only to launching a second *bare* invocation from the
same working tree. This is a live foot-gun: an operator reading either document
today would decline to use a facility that exists and works.

### D-03 — `AGENTS.md` carries a full mirror of the other two repositories' backlogs

Roughly 260 lines of `AGENTS.md` (from "Redevelopment readiness" to the end) are
a copy of the `leap_mappings` backlog (M1–M7), the `leap_dashboard` backlog
(DB1–DB5, D5–D6), and a build order across all three repositories.

This is a **stale parallel backlog in the wrong repository**:

- Its "critical blocker — pipeline is disconnected from the new workbook" claim
  is retracted by a banner higher in the same file (M2 is done) but the blocker
  text is still present verbatim below.
- `leap_mappings` now maintains its own dated queue at
  `leap_mappings/docs/work_queue.md` (MAPQ-001…MAPQ-022, snapshot 2026-07-28).
  Where the two disagree, the sibling repository owns the answer.
- `leap_dashboard` has no `docs/work_queue.md`; its live backlog is
  `docs/future_dashboard_backlog.md` and `docs/handover_mapping_diagnostics.md`,
  neither of which is what `AGENTS.md` describes.

**Action:** cut M1–M7 and DB1–DB5 from `AGENTS.md`, replacing them with links to
the owning repositories' queues. Keep only the initialisation-side phases.
Requires no semantic decision — it is a deduplication.

### D-04 — `work_queue.md [7]` / `[13]`: the `full model export.xlsx` retirement is materially further along than recorded

`[7]` states "Roughly 15 module-level constants still pin
`data/full model export.xlsx`" and lists them. `[13]` describes archiving it as
an open repoint-and-verify task gated on Task 0.

Measured 2026-07-28:

- **`data/full model export.xlsx` does not exist.** It has been removed from the
  working tree.
- **One** live code reference to the string remains outside
  `archive/`/`scrapbook/`/`old_workflows/`:
  `codebase/mapping_tools/update_mapping_cardinality.py`.
- `data/leap_export_templates/` holds 21 per-economy templates and is resolved by
  `codebase/utilities/leap_export_template_resolver.py`.

`docs/leap_initialisation zip_extraction_plan.md` already records this as
completed on 2026-07-22 (`8d4043d`). The work queue was never updated to match.

**Action:** re-verify the single remaining reference, then close `[13]` and strike
the constants list from `[7]`.

### D-05 — `work_queue.md [7]` / `[12]`: the real-vs-generated template split has inverted

Both items reason from "18 of 21 templates are `_COMP_GEN`, generated from the
USA area and carrying its BranchIDs verbatim; only `01_AUS`, `12_NZ`, `20_USA`
are real." Several safety arguments in `[7]` and `[12]` rest on that ratio.

Measured 2026-07-28 in `data/leap_export_templates/`:

| Category | Count | Files |
|---|---|---|
| `_COMP_GEN` (USA-derived) | 10 | CDA, CHL, HKC, INA, JPN, ROK, PE, RUS, SGP, CT |
| Real per-economy | 11 | AUS, BD, MAS, MEX, NZ, PHL, PNG, PRC, THA, USA, VN |

Eight real templates are dated **28/07** — i.e. they landed the day of this
audit. **The majority of templates are now real**, reversing the premise.

**Action (needs the modeller, not an agent):** `[12]`'s conclusion that
"regeneration is NOT the answer" was reached under the old ratio. Re-read it
against 11 real templates before relying on it. Do not assume the new templates
are safe merely because they are real — none has an end-to-end seed audit of the
kind `01_AUS` received on 2026-07-21.

### D-06 — `work_queue.md [14]`: Phase 2 status is understated but its tests are genuinely missing

`[14]` says "started, with one safe foundation landed" (`supply_workflow.py`,
`70613de`), with steps 2–4 pending.

Measured: **all seven** workflow wrappers already
`from codebase.configuration import workflow_config as workflow_cfg`, and
`transformation_workflow.py` (13 hits), `electricity_heat_interim_workflow.py`
(6) and `transfers_workflow.py` (7) all carry `NOTEBOOK_*` blocks. Those blocks
predate Phase 2 — they arrived in `0d953d1` (2026-06-25), not from this work.

However, `[14]`'s stated completion criterion is a per-script focused test.
Only `tests/test_supply_workflow_config.py` exists. **No test covers steps 2–4.**

**Action:** `[14]` is correctly *open*, but for the right reason — the wiring
largely exists and the verification does not. Restate it as "add the
forwarding/default tests and reconcile pre-existing `NOTEBOOK_*` blocks with the
central config", not "move the defaults".

### D-07 — `docs/prompts/AGENTS.md` inventory covers less than half the folder

The inventory is headed "Reviewed on 2026-07-27". Against the filesystem:

- **18 of 33 prompts are absent from the inventory**, including every
  2026-07-22/23 file: `advance_repo_20260722_execution_prompt.md`,
  `aggregated_demand_scoped_review.md`,
  `centralise_leap_balance_exports_across_repos.md`,
  `continuation_20260722_phase4_parallelism_and_release_readiness.md`,
  `continuation_20260723_next_session.md`,
  `fix_augmented_source_csv_dtype_warnings.md`,
  `handoff_20260723_docs_audit_and_cleanup.md`,
  `other_loss_own_use_proxy_scoped_review.md`,
  `phase_2_configuration_standardisation_execution.md`,
  `refining_workflow_scoped_review.md`,
  `repo_cleanup_and_consolidation_plan_20260723.md`,
  `review_nz_unmapped_leap_branch_fuel_combinations.md`,
  `session_handoff_20260722.md`,
  `supply_reconciliation_presets_scoped_review.md`,
  `supply_reconciliation_runtime_profiling_execution.md`,
  `transformation_final_handoff_and_verification_prompt.md`,
  `transformation_patch_rewire_exploration_prompt.md`,
  `transformation_patch_ungate_final_verification_prompt.md`.
- **One inventory row points at a file that is not there.**
  `id_verification_consolidation_execution_prompt.md` is listed as "Valid,
  active, high value" but lives at
  `docs/archive/id_verification_consolidation/`, archived alongside its own
  `STATUS.md`. The work is complete (`10e382a`, `535f09e`).
- The "Known Folder Issues" section states "There is a deleted prompt tracked in
  git status: `supply_reconciliation_full_run_execution_prompt.md`". **The
  working tree is clean**; there is no such pending deletion.

### D-08 — a completed prompt-archival plan from 2026-07-23 was never executed

`docs/prompts/handoff_20260723_docs_audit_and_cleanup.md` § A1 contains a
full 30-row classification of `docs/prompts/`, produced by a subagent pass that
cross-checked against real code and test state. It marks 14 prompts **DONE** or
**SUPERSEDED** with the recommendation "archive". The document states plainly:
*"None of the moves above are done yet — this table is the audit, not the
archival itself"*, and notes archival is safe to do immediately as a docs-only
change.

Five days later, **all 14 are still in `docs/prompts/`**. Only four unrelated
prompts have been archived since (listed under "Recently Archived" in
`docs/prompts/AGENTS.md`).

Prompts still awaiting the archival that plan authorised:

`advance_repo_20260722_execution_prompt.md`,
`centralise_leap_balance_exports_across_repos.md`,
`continuation_20260723_next_session.md`,
`nz_baseline_seed_hardening_readiness_prompt.md`,
`other_loss_own_use_proxy_scoped_review.md`,
`patch_baseline_seeds_module_verification_prompt.md`,
`preset_forwarding_fix_execution_prompt.md`,
`review_nz_unmapped_leap_branch_fuel_combinations.md`,
`session_handoff_20260722.md`,
`supply_reconciliation_runtime_profiling_execution.md`,
`transformation_final_handoff_and_verification_prompt.md`,
`transformation_patch_ungate_final_verification_prompt.md`,
`workflow_folder_migration_and_reconciliation_verification_prompt.md`,
and `continuation_20260722_phase4_parallelism_and_release_readiness.md`
(**decision first** — see D-09).

Two independent spot-checks confirm the classifications still hold:
`preset_forwarding_fix_execution_prompt.md` maps to `[17]`, marked SETTLED with
all five steps committed (`3928a7b`, `857b6e4`, `2017ef4`, `62678a2`,
`c5401a5`); `advance_repo_20260722_execution_prompt.md`'s main task was `[18]`,
which `current_execution_roadmap.md` records as a completed safety foundation.

**One conflict needs an owner.** The 2026-07-23 audit classifies
`patch_baseline_seeds_module_verification_prompt.md` as DONE/archive; the
2026-07-27 `docs/prompts/AGENTS.md` inventory calls it "Valid, active". Two
documents, two verdicts, four days apart. Do not archive it on this audit's
authority alone.

### D-09 — one open thread exists in only one place, and that place is slated for archival

The 2026-07-23 audit flags
`continuation_20260722_phase4_parallelism_and_release_readiness.md` as
"PARTIALLY DONE — needs a human decision": its *"[18] explicit-zero-in-seed
design correction"* section is a real open thread that **exists nowhere else in
the repository**. Archiving the file without first folding that section into the
work queue or the T-register would lose it.

This is the single highest-risk documentation item in the repo: an open design
question with exactly one copy, inside a file scheduled for archival.

### D-10 — three parallel classifications of the same prompt set

`docs/prompts/` is currently described by three documents that do not agree:

1. `docs/prompts/AGENTS.md` — inventory table, "Reviewed 2026-07-27", 15 of 33
   files, plus a recommended tackling order.
2. `docs/prompts/handoff_20260723_docs_audit_and_cleanup.md` § A1 — 30-row
   classification, 2026-07-23, unexecuted.
3. `docs/prompts/repo_cleanup_and_consolidation_plan_20260723.md` — a broader
   plan covering `outputs/`, dead code, and diagnostics consolidation, whose
   header states "Nothing below has been acted on yet" (partly untrue: its §2
   items 1–2 record same-day resolutions inline).

**Action:** collapse to one. `docs/prompts/AGENTS.md` should hold the inventory;
the other two should be archived once their still-open items are folded into the
work queue.

### D-11 — broken links and references

| Source | Target | Diagnosis |
|---|---|---|
| `docs/work_queue.md` | `prompts/export_zero_fill_consolidation_execution_prompt.md` | File was archived to `docs/archive/`; link not updated |
| `docs/check_registry.md` (×2) | `prompts/export_zero_fill_consolidation_execution_prompt.md` | Same |
| `README.md` | `docs/images/usa-transport-industry.png` | `docs/images/` does not exist |
| `README.md` | `docs/images/balance-table-example.png` | Same |
| `docs/colleague_intro_all_demand_aggregated.md` | `<C:\…\docs\leap_all_demand_aggregated_fuels_by_sector.csv>` | File exists; the link is malformed (angle brackets inside the target, absolute path) |
| `docs/leap_all_demand_aggregated_branch_guide.md` | same | Same |
| `AGENTS.md` § "When editing draw.io diagrams" | `AGENTS_DRAWIO.md` | **File does not exist anywhere in the repo.** Not a Markdown link, so link checkers miss it |

The three `export_zero_fill…` links are fixed in this audit's commit. The rest
need an owner decision (restore the images, or drop the references; find or drop
`AGENTS_DRAWIO.md`).

### D-12 — `Untitled-2.md` is a 990-line raw log tracked at the repository root

Not documentation. It is captured workflow stdout — repeated
`09.05 Chemical heat for electricity production: missing input/output balance
for 2022+ and all years; writing zero skeleton.` blocks per economy. It has an
unnamed filename, sits beside `README.md` and `AGENTS.md`, and has been tracked
since 2026-07-08.

**Action:** confirm nothing cites it, then archive or delete. Flagged, not acted
on — deleting a tracked file needs confirmation under this project's standing
rule.

### D-13 — missing handover material

| Gap | Why it matters |
|---|---|
| No `docs/README.md` index | `leap_mappings` has one and it is the fastest orientation path in that repo. Here, 26 top-level docs have no reading order. **Created by this audit.** |
| No cross-repository contract document | Three repositories exchange files by sibling-relative path with no single record of who owns what. **Created by this audit** as `docs/cross_repo_handover_index.md`; `leap_mappings` MAPQ-015 asks for the same thing from its side. |
| No clean-checkout runbook | Nothing states what a fresh clone needs before it can run. `data/` and `config/` are large and partly untracked; `docs/leap_initialisation zip_extraction_plan.md` is the closest thing and is framed as an inter-PC sync note, not a runbook. |
| No dated repository work queue | `docs/work_queue.md` is a technical backlog with no priorities, owners, target dates, or last-verified stamps. **Created by this audit** as `docs/handover_work_queue_20260728.md`. |
| `docs/system_overview_for_rewrite.md` (1,042 lines) unverified since 2026-07-17 | It predates the Phase 4 split evidence, the parallelism work, and the template rollout. Its § 11 "Current Pain Points" is likely to mislead a new owner. Not audited line-by-line here — flagged as a Week 2 task. |

## Documents verified as current — no action

`docs/baseline_seed_balance_diagnostics.md`, `docs/results_update_dry_run_preview.md`,
`docs/aus_2022_balance_export_investigation_findings.md`,
`docs/nz_target_results_update_20260728.md`, `docs/check_registry.md` (content;
links aside), `docs/process_map_agent.md`, `docs/process_map_human.md`,
`docs/leap_balance_export_centralisation_audit.md`,
`docs/aggregate_preflight_source_routing_contract.md`,
`docs/canonical_migration_diagnostics/README.md`, and the four `codebase/`/`data/`
READMEs.

The first pass did not re-audit the then-25 files under `docs/archive/`. The
follow-up did: each archive file was inspected as historical evidence, its
links were checked, and none was promoted back to live instruction. See the
disposition matrix for the individual results.

## Actions taken in this audit's commit

1. Created `docs/README.md` — reading order and index for `docs/`.
2. Created `docs/handover_work_queue_20260728.md` — the dated handover queue.
3. Created `docs/cross_repo_handover_index.md` — ownership and data contracts.
4. Fixed the three `export_zero_fill_consolidation_execution_prompt.md` links in
   `docs/work_queue.md` and `docs/check_registry.md` to point at `archive/`.
5. Added a pointer at the top of `docs/work_queue.md` naming the handover queue
   as the controlling schedule and `work_queue.md` as the technical detail.

Everything else in this audit is recorded, not acted on. No prompt was archived,
no branch or worktree was touched, no code was changed, and no semantic
modelling decision was made.

## Follow-up actions completed on 2026-07-28

The exhaustive preservation pass:

1. corrected live parallelism, template, mapping-ownership, and workflow
   inventory guidance;
2. archived the unnamed raw log and 15 completed/superseded prompts with status
   banners, preserving their useful evidence;
3. rescued the explicit-zero design into the still-active final-owned-seed
   prompt rather than discarding it;
4. rebuilt `docs/prompts/AGENTS.md` so every active prompt appears exactly once;
5. repaired links affected by the moves and removed references to two absent
   screenshots; and
6. created the 102-file disposition matrix linked above.

The original D-01–D-13 findings remain above as discovery history; the matrix
and current queues record their post-fix disposition.
