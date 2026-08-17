# Documentation re-review — 2026-08-17

## Baseline and scope

The baseline was the preservation-first 28 July documentation cluster ending
at `0e10378`. This pass inventoried every tracked Markdown file, checked
relative links, compared the active front doors and workflow inventory with
the current code/configuration, and reviewed material Git changes since that
cluster. Dated findings remain evidence rather than live operating guidance.

## Material changes since the baseline

- Mapping maintenance now begins upstream with the mandatory single-axis
  `generate` gate; this repository consumes the generated compatibility master.
- Supply reconciliation gained final-artifact validation, post-process rules,
  balance diagnostics, update-workbook support, package decomposition, typed
  machine-only outputs and extensive check-registry coverage. These topics are
  already documented in their focused contracts and work-queue entries.
- The review-tools web/release application moved to the sibling
  `leap_review_tools` repository on 5 August. This repository retains packaging
  and handover history, not the current app implementation.
- The root README still contained the old `leap_utilities` setup, API-first and
  dashboard-discovery instructions as if they were current.
- The workflow inventory omitted four current review/validation entry points,
  and the prompt inventory still listed the completed parquet migration while
  omitting the active round-trip convergence exploration.

## Actions

- Replaced the root README with a concise current ownership, mapping boundary,
  inputs, run-safety and review-tools handover guide; obsolete setup/API text
  is no longer presented as current.
- Refreshed the workflow inventory and clarified the retained portable-release
  package boundary.
- Archived the completed documentation-restructure notes and reconciled the
  prompt inventory.
- Kept dated investigations, migration plans and detailed engineering history
  where they are explicitly labeled as historical evidence.

## Validation

- Relative Markdown links were checked after the move and front-door rewrite.
- No workflow code, model configuration, source data, generated result or
  workbook was changed by this review.
