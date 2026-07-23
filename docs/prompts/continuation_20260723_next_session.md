# Continuation prompt — next session, 2026-07-23

Read `docs/current_execution_roadmap.md` and `docs/work_queue.md` first for
full context; this is a quick-start pointer, not the detail.

## What just landed (all committed to `master`)

- **Bounded process-based economy parallelism** — done and verified
  (`codebase/functions/parallel_economy_runner.py`, sequential-equivalence +
  two-economy concurrent smoke test both passed).
- **Deterministic parent merge, findings slice** —
  `codebase/functions/parallel_economy_merge.py` merges consolidated
  baseline-seed findings across workers. The single-file combined-workbook
  merge is explicitly NOT built — flagged as its own higher-risk follow-up,
  don't start it without discussing scope with the user first.
- **`[19]` template-matching diagnostics** — consolidated + filtered, verified
  row-for-row against the real four-real-template evidence CSV.
- **Phase 3 canonical mapping (T4)** — commits 1, 2, 3, 5 done. Commit 4
  (exclude rollup labels from display-name resolution, D3.2) is **blocked,
  not just deferred**: researched and found the join between a
  rollup-flagged code and its components is unreliable (10/21 codes have no
  matching rule row anywhere). Written up for the mapping owner under T10 in
  `docs/prompts/initialisation_refactor_continuation.md`. Do not implement
  commit 4 until that's answered.
- Several stale docs corrected (`AGENTS.md`, the open-thread register,
  `docs/canonical_mapping_migration_notes.md`,
  `docs/supply_reconciliation_workflow_guide.md`).

## Where to pick up

1. **If the mapping owner has answered T10**, implement Phase 3 commit 4 per
   `docs/prompts/phase_3_canonical_mapping_migration_execution.md` D3.2,
   using their answer to handle the unresolvable codes correctly. It's
   output-affecting — quiet tree, real single-economy A/B before landing.
2. **Otherwise**, next-highest-value open items (see
   `docs/prompts/initialisation_refactor_continuation.md`'s thread register
   for detail):
   - T4 remaining: D3.4 (rollup-rule reading ownership) and D3.5
     (equivalence tolerance) — both just need confirmation, not new work.
   - The single-file combined-workbook merge for parallel economy outputs —
     scope it with the user first (row/preamble reconstruction risk).
   - T6 5B.3/5B.4 (aggregated-demand branch contributions) — needs D5B.3/
     D5B.4 confirmation first.
3. Check `git log --oneline -20` before starting — this repo has had more
   than one concurrent session; don't assume nothing has moved since this
   was written.

## Standing rules (still apply)

- One issue per commit, `codex:` message convention.
- Never commit code while a long run is in flight (docs-only is safe).
- This worktree lacks the real `data/`/`config/` files needed to run
  anything — do development/testing work from the main checkout
  `C:\Users\Work\github\leap_initialisation` directly on `master` (confirmed
  acceptable by the user 2026-07-23); the dedicated worktree branch for this
  session is stale and can be ignored/removed.
- Ask before any output-affecting change goes live, and before any real
  production/verification run.
