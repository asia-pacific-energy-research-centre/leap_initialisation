# Task: Expand capacity-unmet convergence reporting into run diagnostics

Use this prompt when extending the convergence tracking in
`codebase/supply_reconciliation_allocation.py` into a modeller-facing
diagnostics layer: understanding what a single update run changed after it
finishes, and comparing between runs.

## Current Context

Iterative capacity-unmet passes already compute convergence metrics from the
saved pass history (`_compute_convergence_metrics` in
`codebase/supply_reconciliation_allocation.py`): pass count, first/current gap,
gap closure percentage, last-pass gap delta, cumulative allocated output,
clipped total, unresolved fuel count and names, and a
converging/diverging/stable trend. Each pass appends one row to
`outputs/leap_exports/supply_reconciliation/supporting_files/runtime/capacity_unmet_convergence.csv`
via `_write_convergence_csv`.

History maintenance already exists in `codebase/supply_reconciliation_history.py`:

- `trim_convergence_csv_to_pass(pass_number, csv_path)` — drops rows whose
  `pass_count` exceeds a given pass (used when reverting passes from state).
- `clear_convergence_csv(csv_path)` — truncates to the header row.

Related per-pass artifacts that diagnostics can draw on:

- The JSON state file (`CAPACITY_UNMET_STATE_PATH`) with the full `passes`
  history, including per-fuel allocation, clipping, and unresolved rows.
- Unresolved-residual and clipping CSV/JSON reports in the runtime folder.

Tests live in `tests/test_supply_reconciliation_capacity_unmet_iterative.py`.

Known limitations to address (not just nice-to-haves):

- The convergence CSV has no run identifier. Rows carry `timestamp_utc`,
  `mode`, `iteration_run_mode`, and `pass_count`, but nothing groups the
  passes of one logical run together, so between-run comparison currently
  requires guessing run boundaries from `pass_count` resets or timestamp gaps.
- Convergence metrics are aggregate-only (total gap across all fuels). A
  modeller cannot see from the CSV which fuel drove the change in a pass.
- There is no modeller-facing helper for removing selected convergence-history
  rows when a run is deliberately reverted (the guide's "remaining
  improvement"). `trim_convergence_csv_to_pass` exists but is pass-oriented
  and internal.

## Goals

Build post-run diagnostics with two audiences of use:

1. **Single-run understanding** — after an update run finishes, the modeller
   can answer: what did this run change, which fuels closed or opened gaps,
   what was allocated where (production vs transformation vs imports
   fallback), what got clipped, and what remains unresolved.
2. **Between-run comparison** — the modeller can compare two runs (e.g.
   before/after a config change to caps or priority order) on the same
   metrics: gap trajectories, closure rates, unresolved fuel sets, and
   allocation mix.

## Task 1: Run identity in the convergence history

Add a `run_id` (and keep `timestamp_utc` per pass) to every convergence CSV
row and to the pass summary. Requirements:

- Generate the run id once per workflow invocation (UTC timestamp-based, same
  convention as the leap_mappings run_id) and thread it through both call
  sites of `_write_convergence_csv` (there are two: the main iterative path
  and a second path near the end of the module — update both).
- Old CSVs without the column must still load; treat missing `run_id` as
  blank rather than erroring.
- Update `trim_convergence_csv_to_pass` so trimming is scoped to a run rather
  than global `pass_count` comparison, once run ids exist.

## Task 2: Single-run diagnostics report

Add a post-run report generator (new module or extend
`codebase/supply_reconciliation_allocation.py` — prefer a new
`codebase/functions/` module to keep the allocation module from regrowing)
that, given a run id (default: latest run), produces:

- **Run summary**: passes executed, first/final gap, closure %, trend across
  the run, cumulative allocation split by lever (primary production headroom,
  transformation capacity, imports fallback), total clipped.
- **Per-fuel breakdown**: for each fuel touched in the run — gap at run start,
  gap at run end, delta, allocation received by lever, clipped amount, and
  whether it is still in the unresolved set. Source this from the state file's
  pass history, not just the aggregate CSV.
- **Movers table**: fuels ranked by absolute gap change, so the biggest
  improvements and regressions lead.
- Output both a printed summary (notebook/console friendly) and a CSV in the
  runtime supporting-files folder, named with the run id.

## Task 3: Between-run comparison

Add a comparison helper taking two run ids (default: latest two) that reports:

- Gap trajectory side by side (pass-by-pass gap series for each run).
- Closure % and pass-count deltas.
- Unresolved fuel set differences (resolved-in-B, newly-unresolved-in-B,
  unresolved-in-both).
- Per-fuel end-gap deltas between the runs, ranked by magnitude.
- Note in the output when the two runs used different `mode` /
  `iteration_run_mode` values, since that makes comparison apples-to-oranges.

## Task 4: Modeller-facing history revert helper

Add a documented, modeller-callable helper in
`codebase/supply_reconciliation_history.py` to remove convergence-history rows
for a deliberately reverted run:

- Primary form: remove all rows for a given `run_id` (or the latest run).
- Keep the existing pass-scoped trim for internal state-revert use.
- Print what was removed (row count, run id, pass range) and never delete the
  file itself — truncate-to-header stays the job of `clear_convergence_csv`.

## Requirements

- Read `AGENTS.md` and referenced instruction files first; run
  `git status --short` and preserve unrelated existing changes.
- Do not run the full supply reconciliation workflow to test this; drive the
  new helpers with synthetic state/CSV fixtures in tests.
- Several core `codebase/*.py` files carry a UTF-8 BOM — read with
  `utf-8-sig` when tooling over them.
- Extend `tests/test_supply_reconciliation_capacity_unmet_iterative.py` (or a
  sibling test module) to cover: run-id threading through both CSV write
  sites, legacy-CSV loading without `run_id`, the single-run report numbers
  against a synthetic multi-pass state, the between-run comparison including
  the unresolved-set diff, and the run-scoped revert helper.
- Update `docs/supply_reconciliation_workflow_guide.md`: replace the
  "Remaining improvement" line in the "Convergence rate reporting and run
  history tracking" section with the new diagnostics/comparison/revert
  helpers, and add a short modeller how-to (how to print the latest run
  report, compare the last two runs, and revert a run's history rows).
  Mirror the status change in `AGENTS.md` if it lists this item.

## Verification

- Run the extended test module and report pass/fail output.
- Demonstrate the report and comparison helpers against the real
  `capacity_unmet_convergence.csv` if one exists locally (read-only); if the
  file predates `run_id`, show that the helpers degrade gracefully.
