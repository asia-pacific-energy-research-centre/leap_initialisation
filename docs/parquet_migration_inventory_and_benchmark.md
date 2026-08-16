# Parquet migration inventory and benchmark

Status: implementation, measurement and reversible archive proposal complete
2026-08-16; explicit approval pending for the named archive batch.

This report coordinates work-queue item [44] across `leap_initialisation`,
`leap_mappings`, `leap_dashboard`, `leap_review_tools`, and the regenerated
`leap_review_web_app` runtime. It distinguishes code-only storage from human,
browser, external, LEAP, and published cross-repository contracts.

## Safety baseline

| Repository | Branch | Starting commit | Starting state kept separate |
|---|---|---|---|
| `leap_initialisation` | `master` | `be92d350fd76709352bcefd9b2459643249a4578` | Six pre-existing source/test edits were active at discovery and were not touched; their owning pytest process was allowed to finish. They were committed independently before this migration checkpoint. |
| `leap_mappings` | `master` | `309234dbb4d61db9a9b497fe0b65c7b2d59a6e37` | Untracked `.codex_tmp_rollup_fix/` preserved. |
| `leap_dashboard` | `master` | `f5f79d29a823a45b110f5d5760f5d2c0b9294b91` | Clean. |
| `leap_review_tools` | `master` | `46c72b926254507a3c856378da6428023d17d6af` | Untracked `.codex_tmp_balancing_flow/` preserved. |
| `leap_review_web_app` | `space-deploy` | `05c492d4249ea6915d1b25f9de7d5231118751d5` | Modified `web_app/runtime_stats_remote.json` and untracked `.claude/` preserved. |

Baseline free space on `C:` was 75,210,002,432 bytes. The pinned Windows
environment is `C:\Users\Work\miniconda3\python.exe`, Python 3.13.9, pandas
2.3.3, and pyarrow 24.0.0. `fastparquet` is not installed. The generated scan
does not follow reparse points and excludes separate `.claude` worktrees,
Git metadata, Node dependencies, virtual environments, and frozen
third-party `_internal` libraries.

## Generated inventory

The reproducible generator is
`scripts/parquet_migration_inventory_exploration.py`. Its maintained outputs
are under `docs/diagnostics/parquet_migration/`:

- `format_family_inventory.csv` — repository/path-pattern families with
  format, compression, counts, sizes, header previews, classification, and
  rationale;
- `tabular_read_write_sites.csv` — every detected Python/notebook/JS/TS/config
  read or write site with file, line, operation, and evidence; and
- `inventory_summary.csv` — compact totals by repository, format, and policy
  classification.

The exact per-file trace is regenerated locally at
`outputs/parquet_migration/diagnostics/artifact_file_inventory.csv`; it is
intentionally kept with heavyweight diagnostics rather than committed as a
14 MB documentation file.

The refreshed scan found 19,081 tabular artifact files, 6,663 normalized
artifact families, and 3,445 tabular read/write sites. The largest clear
machine-only holdings were:

- 23.7 GB of 118 pickle cache files under supply reconciliation runtime trees;
- roughly 117.9 GB of repeated CSV reference caches under `data/.cache/`; and
- large detailed conservation/validation CSV families whose human-use outcome
  remains pending in the separate decision register.

The inventory is conservative. Ambiguous CSV/XLSX families remain retained;
absence of a code reference is not treated as proof that a person does not use
the file.

## Benchmarks

The benchmark generator is
`scripts/parquet_migration_benchmark_exploration.py`; exact results are in
`docs/diagnostics/parquet_migration/benchmark_results.csv`. Times are local
wall-clock samples, and memory is the sampled increase in resident set size
during the operation. Each candidate passed exact nested-value and DataFrame
value/order/dtype checks.

| Representative artifact | Current → candidate size | Current → candidate full read | Current → candidate peak RSS increase | Decision |
|---|---:|---:|---:|---|
| Small balance-demand bundle | 240,022 → 85,775 B | 0.003 → 0.134 s | 0.8 → 9.3 MB | Migrate; absolute overhead is immaterial and cache families are normally larger. |
| Medium balance-demand bundle | 16.5 → 2.0 MB | 0.134 → 0.280 s | 55.5 → 111.4 MB | Migrate; 88% storage reduction with sub-second read. |
| Large transform/supply bundle | 295.6 → 27.6 MB | 0.429 → 1.481 s | 367.4 → 895.0 MB | Migrate with recorded tradeoff: exact and 91% smaller; still materially below rebuilding from the CSV source path, but higher than pickle peak memory. Monitor the first workflow run. |
| 9th reference CSV cache | 288.9 → 14.7 MB | 8.982 → 0.430 s | 1,595 → 838 MB | Migrate. Selected read: 4.98 → 0.31 s; economy filter: 7.87 → 0.15 s. |

The transform/supply decision compares the approved options, not only the
unsafe incumbent: pickle writes must cease, while reconstructing from the
representative CSV took about 8–10 seconds and roughly 1.6 GB incremental peak
RSS. The typed bundle is the lower-memory approved path even though it does not
match pickle's object-sharing efficiency.

## Implemented initialisation families

### Augmented reference caches

`load_augmented_reference_tables()` now writes one authoritative
Parquet/Zstandard file per ESTO and 9th table. A JSON metadata file is written
last and records schema version, source signatures, row and column counts,
dtypes, byte size, and SHA-256. Reads verify version, compression, hash, and
row count. Writes use same-directory temporary files and atomic replacement.
Existing CSV caches are ignored, not deleted.

### Supply-reconciliation runtime caches

Balance-demand and transform/supply caches now use a versioned
`*.parquet_cache/` bundle. Every DataFrame is stored as checksummed
Parquet/Zstandard; nested dictionaries, lists, tuples, sets, NumPy scalars,
timestamps, non-finite floats, and column-label metadata are represented in
the JSON manifest. Mixed integer/string columns and original pandas dtypes are
restored explicitly. The complete directory is staged beside the destination
and renamed atomically. New runtime writes no longer create pickle files.

### Approved human-format families (HF-001 through HF-004)

The user approved the recommended `parquet_plus_human_summary` disposition on
2026-08-16. Complete conservation lineage and baseline-seed finding tables in
`leap_initialisation`, plus broad-row affected output and complete anchor detail
in `leap_mappings`, now use manifested Parquet/Zstandard. Compact breakdown,
grouped review, sample, findings, summary, and example CSVs remain available for
direct inspection. `leap_dashboard` reads the anchor details server-side and
temporarily falls back to legacy CSV result folders when Parquet is absent.

Representative existing outputs passed exact value/order/dtype round trips
through the production manifest writers and integrity readers:

| Artifact | Rows | Current bytes | Parquet bytes | Reduction |
|---|---:|---:|---:|---:|
| Balance-demand lineage | 39,582 | 8,403,478 | 467,650 | 94.435% |
| Transformation lineage | 12,681 | 2,961,832 | 341,414 | 88.473% |
| Baseline-seed findings | 1,436,464 | 689,911,996 | 1,625,991 | 99.764% |
| Broad-common-row affected output | 145,716 | 735,953,139 | 677,139 | 99.908% |
| Full anchor validation | 166,916 | 2,583,887 (CSV.gz) | 808,655 | 68.704% |
| Economy mapped-component context | 94,800 | 33,179,982 | 167,531 | 99.495% |

Exact measurements are in
`docs/diagnostics/parquet_migration/approved_human_format_validation.csv`.

## Validation completed at this checkpoint

- Pre-change cache tests failed as expected because only CSV caches existed.
- Typed storage and augmented-reference regression tests: 4 passed.
- Broader augmented-reference consumers: 9 passed with 4 existing warnings.
- Supply cache/config/preflight contract slice: 93 passed, 5 skipped.
- First full initialisation suite: 1,446 passed, 11 skipped, 35 deselected, 12
  subtests passed; 99 existing warnings. The final committed state, including
  the aggregate-preflight fix, passes 1,447 with the same skip/deselection and
  warning profile.
- Real small, medium, and large historical cache bundles passed exact nested
  round-trip comparison.
- The approved HF implementation passes 1,450 initialisation tests (11 skipped,
  35 deselected, 12 subtests), 540 available mapping tests (1 skipped; two
  modules unavailable because the required 20_USA REF balance export is
  absent), and 259 dashboard tests.

No existing cache or generated output has been removed. Full-system evidence is
recorded in
[`parquet_migration_full_system_validation.md`](parquet_migration_full_system_validation.md).
Nine template-backed economies produced 18 versioned cache bundles / 162
Parquet files and zero pickles; production-helper reads restored all expected
AUS objects. Existing template and baseline-seed findings prevent a completely
green archive gate, so no archive manifest has been generated.

## Deliberate retains and transition boundaries

- LEAP import/export workbooks and baseline seeds remain XLSX.
- Human summaries, compact review tables, editable configuration, readiness
  reports, and manifests remain CSV/XLSX.
- External ESTO/9th inputs remain unchanged; only regenerable caches beside
  them migrate.
- Browser assets remain HTML/JSON/JavaScript.
- Common ESTO and other cross-repository CSV/CSV.gz contracts remain
  authoritative until producer, all consumers, portable packaging, and the
  deployed runtime move together.
- Existing pickle and CSV cache files are obsolete candidates, not deletion
  targets. They require the separate checksummed archive approval gate.

## Remaining execution gates

1. Optionally investigate the four compressed-preflight SEED-008 findings;
   they are tracked separately and are not a Parquet prerequisite.
2. Wait for the seven economy templates and 51 missing-branch groups to become
   available through the corresponding LEAP-model work; do not synthesize them.
3. Keep HF-005 and all historical-run retention decisions separate.
4. Create no archive and move no original until the user explicitly approves
   the named checksummed archive batch.
