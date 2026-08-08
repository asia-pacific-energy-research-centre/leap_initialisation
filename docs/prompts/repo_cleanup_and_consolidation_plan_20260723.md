# Repo cleanup and diagnostics-consolidation plan (2026-07-23)

Type: consolidated findings + action plan. Written 2026-07-23 from five
read-only audit passes run the same day. **Nothing below has been acted on
yet** — this is the synthesis, not the execution. Cross-references
`docs/prompts/handoff_20260723_docs_audit_and_cleanup.md` (the earlier,
narrower docs/repo-hygiene handoff) rather than duplicating it; this doc
covers the broader `outputs/`, dead-code, and diagnostics-consolidation
scope the user asked to explore further.

## How to use this doc

Each section ends with a clear priority ordering and risk rating. Work
through the LOW-risk items first — they're mechanical and evidence-backed.
MEDIUM/HIGH-risk items need a design decision or a compatibility shim before
touching, and are flagged as such. Confirm before any deletion of a tracked
file or a large `outputs/` prune, per this project's standing destructive-
action rule.

---

## 1. `outputs/` cleanup — 54GB across 38+ run directories

Full per-directory table is in the audit agent's report (not reproduced here
in full — see the chat transcript from the "Audit outputs/ directory for
cleanup" agent, 2026-07-23). Summary:

| Bucket | Size | Action |
|---|---|---|
| Safe to delete | ~4.6GB | One-off scratch dirs, superseded intermediate `SEED_01_AUS_TWOYEAR_*` iteration steps, old debug logs. Confirmed evidence-based (superseded-by-later-iteration, or explicitly named "safe to delete" in the earlier handoff doc). |
| Archive-candidate (compress, don't delete) | ~10GB | `results_update/runs/*` (tied to the closed/archived `usa_target_results_update_failure_investigation` doc), old pre-run-label scratch under `supply_reconciliation/{checks,runtime,workbooks,supporting_files}` (lower confidence on this second part — needs a closer look before acting). |
| Protected — do not touch | ~25GB | Explicit reference baselines (`SEED_01_AUS_PRESETFLIP_*`, `SEED_4REAL_TEMPLATES_FULL_20260722`, `SEED_12_NZ_TGT_REF_CA`, `PARALLELISM_EQUIV_01_AUS`, `BASELINE_SEED_7ECON_PARALLEL3_20260723_*`, `O5_{BEFORE,AFTER}_01_AUS_20260723`, `SEED_01_AUS_TGT_REF_CA`, `SEED_01_AUS_TWOYEAR_AGGSOURCE_20260722`, `PARALLEL_SMOKE2_*`, `CONCURRENCY_SCALE_TEST_W3_*`) plus the known-buggy `SEED_21ECON_*` runs (kept as bug-evidence, not deleted, ~9.9GB of that total). |
| Uncertain — human call needed | ~14.4GB | Mostly `SEED_01_AUS_TWOYEAR_*`/`SEED_01_AUS_ZEROING_*` intermediate iterations the agent couldn't confidently place as superseded-vs-still-cited, plus ~7.8GB of pre-labeled-run legacy scratch. |

**Confirmed resolved during this session**: `BASELINE_SEED_7ECON_REAL_20260723`
is the *failed* run (crashed ~17 min in from lock contention with a stray
process, fixed same day) — `BASELINE_SEED_7ECON_PARALLEL3_20260723` is the
real, successful 7/7 production result. `REAL_20260723` is safe to delete
once you're satisfied `PARALLEL3` is the one to keep.

**Priority**: delete the ~4.6GB safe bucket first (mechanical, no risk).
Decide the ~14.4GB uncertain bucket next (needs you, not further automation
— the agent already tried and couldn't resolve it confidently). Archive
bucket can wait, it's not blocking anything.

---

## 2. Dead code — 16 solid findings across `codebase/`

Full list is in the "Full codebase dead-code audit" agent's report (2026-07-23,
chat transcript). Highlights, highest confidence first:

1. **5 whole dead modules** (only importers are in `archive/`/`old_workflows/`/
   `scrapbook/`, already-excluded holding areas): `buildings_technology_mapping.py`,
   `minor_demand_utils.py`, `detailed_balance_from_esto.py`,
   `leap_transformation_losses_own_use.py`, `ninth_to_esto_mapping_coverage.py`.

   **Resolved 2026-07-23 (81119c0)**: 4 of the 5 were genuinely dead and are
   now deleted — `buildings_technology_mapping.py`, `detailed_balance_from_esto.py`,
   `leap_transformation_losses_own_use.py`, `ninth_to_esto_mapping_coverage.py`.
   Backed up to `leap_cleanup_backups_20260723/dead_code_files.zip` first.
   `minor_demand_utils.py` was **NOT actually dead** — restored via
   `git checkout --`. The grep-based "no importer in codebase/tests/docs"
   check missed that `tests/test_minor_demand_workflow.py` directly imports
   `codebase.archive.minor_demand_workflow`, which in turn imports
   `minor_demand_utils`. A full pytest collection run (not just grep) is what
   caught this — it surfaced as a hard collection error (`ModuleNotFoundError`),
   not a silent behavior change. **Lesson: "archive/old_workflows importer only"
   is not sufficient evidence of dead code if any test file directly exercises
   the archived module — always run the full test suite after a dead-code
   deletion batch, before committing, not just a grep sweep.**
2. **A whole dead subpackage**: 10 of 12 files in
   `codebase/utilities/leap_results_dashboard_v2/` — only `config_loader.py`/
   `reference_loader.py` are genuinely live.

   **Resolved 2026-07-23**: this one was **also NOT actually dead** — all 10
   files were restored via `git checkout --` after deleting them broke real
   imports (59 pytest collection errors). The chain: `codebase/__init__.py`
   → `leap_series_comparison.py` → `codebase.scrapbook.utilities` →
   `esto_reference_loader.py` → triggers `leap_results_dashboard_v2/__init__.py`,
   which directly imports `from .models import DashboardV2Settings` and 3
   other of the "dead" files at package-load time. The grep-based "no external
   importer of the exported functions" check missed this because it looked for
   callers of the functions, not for the package's own `__init__.py`
   re-export/import chain. **Lesson: before deleting files inside any
   subpackage, check that subpackage's own `__init__.py` for direct imports of
   those files — a function having no external callers doesn't mean the
   module has no importers.** The originally-prepared
   `dead_code_dashboard_v2_subpackage.zip` backup was deleted since nothing
   was actually removed.
3. **~19 dead functions** in `leap_results_dashboard_balance.py` (module itself
   stays live for its path constants; the functions don't).
4. **Dead mini-subsystems in live files**: a whole unused "transport export
   logging" flow in `leap_core.py`; two unused functions in
   `energy_use_reconciliation.py`.
5. **Superseded-not-removed**: 3 specific transformation-analysis functions
   in `transformation_analysis_utils.py`, replaced by a generic dispatch
   function but never deleted.
6. **Dead config constants**: a handful in `supply_reconciliation/config.py`
   (verified against sibling constants that *are* read, ruling out "whole
   block is unused by convention") and one in `workflow_config.py`.
7. **Medium confidence**: a known/documented duplicate
   (`load_code_to_name_mapping`, already flagged in
   `docs/canonical_mapping_migration_notes.md` C6), leftover unused imports
   from an earlier migration, two items the agent explicitly wasn't
   confident enough to call dead (`leap_results_functions.py`'s interactive
   helpers, `transformation_entry.py` — the latter is explicitly documented
   as an intentional notebook entry point in `docs/workflow_inventory.md`,
   not orphaned).

**Priority**: items 1-4 above are safe to remove now (verified zero live
references). Item 5 needs a one-line decision (just delete the 3 superseded
functions + their config flags, or keep the flags as a documented no-op —
recommend delete, they're pure dead weight). Item 6 needs a quick confirm
that removing a never-read config constant doesn't break some future
intended use nobody's gotten to yet — low risk, but ask first since it's
config, not implementation detail. Item 7's two "not confident" items:
leave alone.

---

## 3. Diagnostics/output-file consolidation — the deepest finding

Two passes ran on this: a single-run sample (found the per-scenario-diagnostic
and validation-triplet patterns) and a systematic whole-pipeline survey
organized against `docs/check_registry.md`'s F1-F5 taxonomy. The second
pass's full report is authoritative; summary:

### The single highest-leverage finding: cross-economy merge is only built for F2

`codebase/supply_reconciliation/parallel_merge.py` merges baseline-seed
findings/issue-groups (F2) across a parallel run's per-economy workers — its
own docstring says this is deliberately scoped, not an oversight for other
checks. But **every other diagnostic already carries an `economy` column and
could be merged the exact same proven way**, and today isn't: a 7-economy
parallel run (like `BASELINE_SEED_7ECON_PARALLEL3_20260723`) produces 7
separate, unmerged copies of `source_diagnostics`, `template_matching_summary`,
and both F5 conservation-check triplets, one per economy directory, with no
combined view anywhere.

**Priority 1 (do this first): extend `supply_reconciliation/parallel_merge.py`** to also
merge `source_diagnostics`, `template_matching_summary`, and the F5
conservation summaries across economies. **Risk: low** — reuses an
already-proven pattern, doesn't touch any column semantics, purely additive.

### Priority 2: reconcile two independently-built "unified diagnostic" schemas

The repo built the F1-F3 "unresolved row" consolidation **twice**, in two
different modules, with two incompatible schemas that don't absorb each
other's inputs:
- `build_template_matching_summary` (`supply_reconciliation/results_saver.py:1267`) — feeds
  from `unmatched_id_rows`, `metadata_mismatch_rows`, `mapping_config_mismatch_rows`.
- `_build_source_diagnostics` (`supply_reconciliation/preflight.py:832`) — feeds from
  `balance_demand_issues`, `nonzero_missing_id_rows`; its schema is actually
  the more general one (has `economy`, `year`, `suggested_fix`, generic
  `issue_type`) and could subsume the other's inputs too.

**Proposal**: adopt `SOURCE_DIAGNOSTIC_COLUMNS` as the one F1-F3 schema, feed
all five source checks into it, retire the separate `template_matching_summary`
file. **Risk: medium** — `build_template_matching_summary` doesn't currently
take an economy argument (those checks run pre-economy-split), so threading
economy context through correctly needs actual code changes, not just a
glob-widen.

**Leave alone**: `supply_reconciliation_balance_matching_diagnostics.csv` and
`supply_reconciliation_dropped_unmatched_zero_supply_rows.csv` — these are
row-provenance / deliberate-exclusion audit trails, not "this is wrong" issue
lists. Folding them in would hide legitimate no-action rows among actionable
ones.

### Priority 3: F2 cross-stage merge (combiner vs verification vs patcher)

`prepare_seed_rows_for_write` has 3 call sites (full-run combiner, results
verification, the patcher), each emitting the identical 3-file schema
(`_rule_findings.csv`/`_duplicate_groups.csv`/`_issue_groups.csv`) under a
different stem. `supply_reconciliation/parallel_merge.py` already merges across economies
but not across these three call-site stages. **Proposal**: add a `run_stage`
column, widen the merge function's input glob to catch all stems present,
not just the economy dimension. **Risk: low** — small, additive extension of
an existing, already-production-exercised function.

### Priority 4 (highest payoff, but real consumer risk): F5 subject-unification

Two independently-built, near-identical 3-tier (summary→breakdown→lineage)
diagnostic families exist for demand-vs-transformation-output conservation
checks (`supply_reconciliation_balance_demand_conservation*.csv` and
`supply_reconciliation_transformation_output_conservation*.csv`) — 11 of 15
summary columns are literally identical between them, differing only in the
subject-dimension columns (`sector_context`/`esto_product` vs
`transformation_module`/`output_fuel`).

**Proposal**: a `check_subject` column plus generic dimension columns,
folding 6 files into 3 (one merged summary/breakdown/lineage triplet instead
of two separate ones). **Risk: medium-high** — these are the most
information-dense diagnostic files in a run, used for numeric debugging by
modellers who currently key on subject-specific column names, and at least
one downstream dashboard reads from `supporting_files/checks/` directly. **Do
this only with a compatibility shim**: keep the two per-subject files as
thin derived views over one merged internal frame, don't delete the
subject-specific files outright.

**Explicitly out of scope / do not merge**: F1 (silent data-mutation, not a
"what's wrong" report — nothing to merge), F4 preflight (genuinely different
input universe per stage per `check_registry.md`, correctly kept separate),
and the summary→breakdown→lineage **tier structure itself** within F5 (an
intentional drill-down, not the "same thing written 3x" duplication pattern
— collapsing tiers would destroy the drill-down, not simplify it).

**Also flagged, not a duplication issue but a gap in the opposite
direction**: `conservation_policy.py`'s downgrade-to-warning path has *no*
persisted diagnostic file at all, only a `print("[WARN]...")` — a modeller
can't grep a CSV for "which producer silently fell back to non-strict
conservation," it only shows up in run logs. Worth a follow-up if this
matters in practice.

### Overall consolidation estimate

Combining both passes' estimates: implementing priorities 1-3 (the low-risk
items) alone would meaningfully cut per-economy file duplication in a
multi-economy parallel run (today: 7x duplication of several diagnostic
families with zero cross-economy view) without any schema-semantics risk.
Priority 4 (F5) is the single biggest file-count win (6→3) but should wait
for a deliberate decision given the consumer risk.

---

## 4. Process maps — done

`docs/process_map_agent.md` and `docs/process_map_human.md` (committed
`fd64048`) — use these as the up-to-date reference for where in the code
each diagnostic file above actually gets written, instead of re-deriving the
pipeline shape from scratch for future work on this plan.

---

## Suggested order to actually execute this plan

1. Delete the ~4.6GB safe `outputs/` bucket (mechanical, zero risk).
2. Remove the dead-code items 1-4 from §2 (whole modules/subpackage/
   mini-subsystems, all verified zero references).
3. Extend `supply_reconciliation/parallel_merge.py` per §3 priority 1 (low risk, high
   value, reuses a proven pattern).
4. Decide the ~14.4GB uncertain `outputs/` bucket (needs you).
5. Everything else (dead-code item 5-6, diagnostics priorities 2-4, the
   ~10GB archive bucket) — pick up as time allows, none of it is blocking.
