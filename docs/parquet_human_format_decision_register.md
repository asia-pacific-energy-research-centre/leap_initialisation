# Parquet human-format decision register

Status: active 2026-08-16. Pending entries default to `retain_temporarily` and
are excluded from every archive batch.

This register covers CSV/XLSX families where direct human use is plausible but
uncertain. Confirmed source inputs, LEAP workbooks, editable configuration,
browser assets, and published contracts are retained by policy and do not need
individual approval here. The machine-readable companion is
`docs/diagnostics/parquet_migration/human_format_decision_register.csv`.

## Prioritised decisions

### HF-001 — Supply conservation lineage detail

- Owner/family: `leap_initialisation`; patterns
  `outputs/leap_exports/supply_reconciliation/**/checks/supply_reconciliation_*_conservation_lineage.parquet`.
- Producer/consumers/frequency: conservation writers in the supply workflow;
  produced by retained baseline and results-update runs. Compact conservation
  summaries and breakdowns are sibling outputs.
- Size: individual files reach about 3.37 GB; repeated runs account for tens
  of gigabytes.
- Workbook semantics: CSV only; no formulas, formatting, comments, sheets, or
  charts.
- Human evidence: the lineage is drill-down evidence, but its size makes direct
  spreadsheet inspection impractical. Compact summaries are the normal review
  surface.
- Sample: the latest applicable run's `supporting_files/checks/` lineage file;
  header preview is in the generated family inventory.
- Recommendation: `parquet_plus_human_summary`.
- Effect/benefit: detailed rows become typed Parquet/Zstandard; existing compact
  CSV summary/breakdown remains. Expected storage and read savings are large.
- Status: `parquet_plus_human_summary`; approved by the user on 2026-08-16.
- Exceptions: compact summary and reviewer-sized breakdown CSVs remain human
  outputs.

### HF-002 — Baseline-seed artifact validation detail

- Owner/family: `leap_initialisation`;
  `outputs/leap_exports/supply_reconciliation/**/baseline_seed_artifact_validation/baseline_seed_artifact_findings.parquet`.
- Producer/consumers/frequency: baseline-seed validation; produced for full
  retained runs, with summary/count surfaces consumed by workflow reporting.
- Size: representative files are 600–690 MB.
- Workbook semantics: CSV only.
- Human evidence: findings are review evidence, but the full table is too large
  for ordinary Excel use; filtered summaries are more plausible human surfaces.
- Recommendation: `parquet_plus_human_summary`.
- Effect/benefit: full findings become Parquet, with a narrow CSV containing
  issue groups/counts/sample rows.
- Status: `parquet_plus_human_summary`; approved by the user on 2026-08-16.
- Exceptions: warning reports and compact issue-group CSVs remain human-facing.

### HF-003 — Mapping broad-row affected-output detail

- Owner/family: `leap_mappings`;
  `results/common_esto/diagnostics/broad_common_row_affected_output.parquet`.
- Producer/consumers/frequency: Common ESTO diagnostic generation; regenerated
  by full mapping runs and used to derive compact diagnostic evidence.
- Size: one current file is among the repository's largest CSVs (hundreds of MB).
- Workbook semantics: CSV only.
- Human evidence: diagnostic purpose suggests review, but direct full-file use
  is uncertain and impractical at this size.
- Recommendation: `parquet_plus_human_summary`.
- Effect/benefit: retain a reviewer-sized CSV summary and samples; use Parquet
  for the complete evidence table.
- Status: `parquet_plus_human_summary`; approved by the user on 2026-08-16.
- Exceptions: mapping health summaries and compact QA tables remain CSV.

### HF-004 — Full anchor-validation matrix/detail

- Owner/family: `leap_mappings`; full
  `source_parent_anchor_*` economy-matrix/detail outputs under mapping results
  and diagnostics.
- Producer/consumers/frequency: full four-source pipeline; dashboard diagnostics
  consume compact/status views.
- Size: representative detailed files are hundreds of MB.
- Workbook semantics: CSV only.
- Human evidence: reviewers use failures and compact evidence, while the full
  matrix supports programmatic derivation and audit reproducibility.
- Recommendation: `parquet_plus_human_summary`.
- Effect/benefit: full matrix/details migrate; failed/skipped summaries and
  representative evidence stay CSV.
- Status: `parquet_plus_human_summary`; approved by the user on 2026-08-16.
- Exceptions: files named as summary, failed-only, readiness, or health report
  remain human-readable.

### HF-005 — Historical run diagnostics and archived output tables

- Owner/family: `leap_initialisation`, `leap_mappings`, and `leap_dashboard`;
  dated run folders under `outputs/` and `results/` that are no longer active.
- Producer/consumers/frequency: prior workflow runs; normally not produced again
  under the same label.
- Size: collectively dominant, with many duplicated hundreds-of-MB files.
- Workbook semantics: mixed CSV/XLSX; XLSX may contain LEAP structure,
  formatting, and multiple sheets.
- Human evidence: some runs are cited evidence; others appear superseded, but
  modification time and absent code references are insufficient proof.
- Recommendation: `retire_after_archive` only for exact batches whose producing
  run, replacement, exclusions, and restoration path are proven.
- Effect/benefit: no format conversion is needed for already-superseded runs;
  approved originals would move intact into checksummed ZIP members.
- Status: `retain_temporarily`; batch-specific approval required.
- Exceptions: unique inputs, active outputs, review evidence, Git/worktrees,
  and junction targets are never included.

## Approved family decisions that do not require user review

- `parquet_only`: regenerable augmented reference caches and new
  supply-reconciliation runtime cache bundles.
- `retain_csv_or_xlsx`: LEAP import/export workbooks, baseline seeds, editable
  mapping/config workbooks, compact human summaries, readiness reports, and
  review/download deliverables.
- `retain_temporarily`: Common ESTO and other published cross-repository
  CSV/CSV.gz contracts until every producer/consumer/runtime migrates atomically.
- Browser JSON/HTML remains browser-readable and is outside Parquet conversion.

### Common ESTO mapping CSV exception — confirmed 2026-08-16

The public `leap_mappings/results/common_esto/source_to_common_esto_map.csv`
remains CSV. It is the deliberately simple seven-column mapping from every
dataset participating in a comparison scope to `common_row_id` and its two
labels. The former 27-column derivation is not the public mapping contract and
now writes as manifested
`structural_artifacts/source_pair_to_common_row.parquet`; its coverage report is
also Parquet. The primary Common ESTO values dataset is manifested
`common_esto_comparison_data.parquet`; the separately published compressed fact
contract remains CSV.gz. Existing legacy CSV copies remain untouched pending
the archive gate.
