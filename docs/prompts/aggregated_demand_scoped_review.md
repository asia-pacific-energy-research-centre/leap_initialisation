# Aggregated demand - scoped review and implementation brief

## Purpose

`codebase/aggregated_demand_workflow.py` creates the temporary
`Demand\\All demand aggregated` source used during initialisation. It also
zeros detailed demand branches so LEAP does not double-count demand while the
aggregate placeholder is active. Its constants define the demand model, not
merely notebook convenience.

This brief is linked from `docs/work_queue.md` [15]. Do not fold it into the
low-risk Phase 2 configuration work.

## Current contract to preserve

- It combines ESTO base-year values with 9th Outlook projections, using the
  configured bridge behaviour at the first projection year.
- It includes a curated set of ESTO and ninth demand/own-use/T&D sectors and
  deliberately excludes electricity from T&D losses.
- It can write flat or sector-level aggregate branches and may write a separate
  detailed-demand zeroing workbook.
- Own-use and T&D-loss branches must be excluded from the aggregate when the
  proxy workflow supplies them, otherwise energy is double-counted.
- Region and ID lookup resolve per economy; aggregate/no-template fallback is
  explicitly separate. Never replace it with a pinned USA ID source.
- The shared loader currently uses selective-column caching. It is intentionally
  not forced onto the full-data cache because a 200MB+ projection table can make
  memory usage worse.

## Review questions

1. Which sector/fuel include/exclude lists are modelling definitions that need a
   human-maintained source of truth, and which are technical parsing helpers?
2. Is the 2060 projection end year, first-projection bridge, and
   intensity/activity output form intended policy for every economy?
3. In which reconciliation pass modes should aggregated demand and detailed
   demand zeroing be emitted? Confirm the paired settings together.
4. What cache measurements are needed before changing selective-column cache
   behaviour: cold/warm runtime, peak RSS, selected-column sets, and invalidation
   after a source file refresh?
5. Which output comparisons constitute acceptance: aggregate total by
   economy/scenario/fuel, branch-row keys, or exact expressions?

Write the answers and a sample-economy evidence table here before implementation.

## Proposed implementation sequence

1. Add a read-only configuration inventory that groups every module setting as
   source path, demand-definition rule, output-shape rule, zeroing rule, or
   technical/cache setting. Do not relocate values yet.
2. Extract only a parameter object/function boundary for a caller-selected
   economy, scenarios, exclusions, branch mode, and zeroing pair. Preserve all
   existing defaults exactly.
3. Keep source filters and demand semantics local until a mapping-owned source
   and regression fixture have been agreed.
4. Retain the selective loader. If measurements demonstrate a need, add a
   distinct cache policy keyed by path, source signature, `usecols`, and dtype -
   never silently substitute a full-frame cache.
5. Only then consider a short notebook-default block, clearly separated from
   modelling choices.

## Tests and acceptance checks

- Tiny ESTO/ninth fixtures: expected source-sector inclusion, own-use/T&D
  exclusion, and base-to-projection transition.
- Output-shape tests for flat and sector-branch modes.
- A paired zeroing test confirming aggregate branches are retained and share
  variables are not zeroed.
- Per-economy template test: rows use the selected template's IDs and region.
- Cache tests: same projection reuses the correct selective projection; a
  changed source signature invalidates it; callers cannot mutate cached frames.
- Before/after comparison for one real economy, with totals and LEAP keys.

## Non-goals

Do not alter demand assumptions, sector mappings, zeroing semantics, template
fallback policy, or cache memory behaviour as incidental cleanup. Any such
change needs an explicit modelling decision and a separately recorded result.
