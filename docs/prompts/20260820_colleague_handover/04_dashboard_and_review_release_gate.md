# DASHQ-007 / DASHQ-017 and review-app post-mapping release gate

## Objective

Perform a single, reproducible downstream rehearsal after a fresh mapping run
is proven safe. The purpose is to find undocumented colleague assumptions
before publication, not to make a dashboard feature change. This task covers
the dashboard’s clean-checkout handover rehearsal and the review web app’s
post-mapping integration checklist.

## Hard entry gate

Start the execution phase only when the MAPQ-052 owner reports
`MAPPING_OUTPUT_SAFE_TO_REFRESH` and supplies a completed, equivalent mapping
run ID and output path. If that is not available by the coordinator’s T+135
decision point, perform only static preparation and issue `RELEASE_HOLD`.
Never treat an OS-killed run, a skipped validator, or a manually altered output
directory as a green mapping result.

## Static preparation (safe before the gate)

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

## Execution after the gate

1. Use the fresh mapping output explicitly and verify its output contract,
   run manifest, source coverage, missing-map, unmapped-LEAP, and unresolved
   partial-coverage QA. Record warnings separately from mapping failures.
2. From the clean dashboard checkout, render one representative economy end to
   end (prefer the documented USA path unless the new run provides a clearer
   available economy). Verify dashboard HTML, `chart_manifest.csv`, and
   `page_assignment_summary.csv`; run focused dashboard tests,
   publication-readiness, page-noise, and routing/page-assignment checks.
3. Check the release-sensitive dashboard items: the fresh mapping run removes
   the stale-provenance condition required by DASHQ-007; Stock changes and
   Statistical discrepancy have their declared `esto_leap` behavior; no
   mixed-cutover Non-energy change from paused DASHQ-047 is introduced.
4. Update the review-app release metadata using the documented source workflow
   only: manifest hashes/assets first, then the refresh script, then the
   generated-runtime check. Respect the `2026_PRELIMINARY` tag and validate the
   selected ESTO Extended vintage/base-year behavior.
5. Generate the representative review-app dashboard and balance-review
   workbook. Inspect Industry vs Other demand non-energy ownership, green
   electricity/hydrogen/import data where expected, base-year continuity, and
   ESTO Extended comparison-basis selection. Then refresh the local app and
   check vintage control, completion time, cancellation, and refreshed-output
   behavior.

## Completion record

Write a dated rehearsal record with clean checkout revisions, mapping run ID,
all commands/tests, emitted output locations, warnings, and every undocumented
prerequisite found. Finish with one status only:

- `READY_FOR_COLLEAGUE_HANDOFF` — all required checks passed and runtime
  manifest hashes match the generated sources; or
- `RELEASE_HOLD` — name the first failed/missing gate, owner, and exact next
  action. Do not publish the hosted app in either case without the user’s
  explicit authority.
