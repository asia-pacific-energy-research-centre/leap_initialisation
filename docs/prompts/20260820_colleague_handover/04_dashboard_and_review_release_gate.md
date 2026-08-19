# DASHQ-017 readiness rehearsal and review-app release preparation

## Objective

Perform a single, reproducible downstream rehearsal using the currently pinned
mapping baseline. The purpose is to find undocumented colleague assumptions
before publication, not to make a dashboard feature change or refresh mappings.
This task covers the dashboard’s clean-checkout handover rehearsal and the
review web app’s release preparation.

## Two separate gates

**Today’s readiness rehearsal:** start now with the mapping output currently
pinned by the dashboard/review runtime. It may close DASHQ-017-style local
handover gaps, but it does not claim DASHQ-007’s “fresh mapping baseline” is
complete.

**Future mapping-refresh release:** before switching the dashboard or review
runtime to newly generated mapping artifacts, MAPQ-052 must report
`MAPPING_OUTPUT_SAFE_TO_REFRESH` from a completed, equivalent mapping run.
Never treat an OS-killed run, a skipped validator, or a manually altered output
directory as a green mapping result.

## Today’s readiness rehearsal

1. Read `leap_dashboard/docs/handover/dashboard_pipeline_guide.md`, the
   dashboard consumer contract, and the review app’s
   `docs/post_mapping_integration_checklist.md`.
2. Create an isolated clean checkout/worktree for the rehearsal. Do not use
   dirty `master`: dashboard has a user-owned `code_colors.json` edit and the
   prepared web runtime is substantially dirty.
3. Make a checklist of required source data/bundle paths, mapping output
   contract/manifest, dashboard environment, review-tools refresh command, and
   expected output folders. Record every missing local prerequisite as an
   assumption before running anything.
4. Do not edit dashboard mapping logic, source mapping rows, or
   `leap_review_web_app/runtime/` manually. The web runtime must be regenerated
   from committed sources and then checked against `source_manifest.json`.
5. From the clean dashboard checkout, select the currently pinned mapping
   output explicitly and render one representative economy end to end. Verify
   dashboard HTML, `chart_manifest.csv`, and `page_assignment_summary.csv`; run
   focused dashboard tests plus publication-readiness, page-noise, and
   routing/page-assignment checks. This proves repeatability of the current
   setup; it does not replace a future fresh-data rerender.
6. Exercise the current review-app setup without refreshing its runtime: run
   the focused checks that are available in the clean source/runtime pair and
   generate the representative dashboard and balance-review workbook if the
   documented input is present. Record the vintage control, completion-time,
   cancellation, and output-retention observations. Treat an unavailable input
   or generated-runtime mismatch as a handover prerequisite, not something to
   repair by editing `runtime/`.

## Mapping-refresh steps — deferred until a future fresh mapping run

1. Use the fresh mapping output explicitly and verify its output contract,
   run manifest, source coverage, missing-map, unmapped-LEAP, and unresolved
   partial-coverage QA. Record warnings separately from mapping failures.
2. Repeat the clean dashboard render using the fresh mapping output. Check the
   release-sensitive items: the fresh mapping run removes
   the stale-provenance condition required by DASHQ-007; Stock changes and
   Statistical discrepancy have their declared `esto_leap` behavior; no
   mixed-cutover Non-energy change from paused DASHQ-047 is introduced.
3. Update the review-app release metadata using the documented source workflow
   only: manifest hashes/assets first, then the refresh script, then the
   generated-runtime check. Respect the `2026_PRELIMINARY` tag and validate the
   selected ESTO Extended vintage/base-year behavior.
4. Generate the representative review-app dashboard and balance-review
   workbook. Inspect Industry vs Other demand non-energy ownership, green
   electricity/hydrogen/import data where expected, base-year continuity, and
   ESTO Extended comparison-basis selection. Then refresh the local app and
   check vintage control, completion time, cancellation, and refreshed-output
   behavior.

## Completion record

Write a dated readiness record with clean checkout revisions, the currently
pinned mapping run/artifact identity, all commands/tests, emitted output
locations, warnings, and every undocumented prerequisite found. Finish with
one status only:

- `READY_FOR_COLLEAGUE_HANDOFF` — the current-baseline rehearsal passed and
  colleagues have every prerequisite needed to repeat it; or
- `RELEASE_HOLD` — name the first failed/missing gate, owner, and exact next
  action. A future mapping refresh/redeployment remains separately gated. Do
  not publish the hosted app in either case without the user’s explicit
  authority.
