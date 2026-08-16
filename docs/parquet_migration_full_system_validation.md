# Parquet migration full-system validation

**Validation date:** 2026-08-16  
**Status:** implementation and broad validation complete; reversible archive
proposal is next. Expected LEAP-model coverage gaps are documented but are not
Parquet blockers.

## Cross-repository checks

| Repository / surface | Result |
|---|---|
| `leap_initialisation` default suite | 1,447 passed, 11 skipped, 35 deselected, 12 subtests passed; 99 warnings; 717.32 seconds |
| `leap_mappings` suite excluding unavailable 20_USA balance-export modules | 537 passed, 1 skipped; 91 warnings; 408.08 seconds |
| `leap_mappings` unavailable modules | Two modules could not collect because `leap_initialisation/data/leap balances exports/20_USA` contains no REF workbook; this external prerequisite was not masked |
| Mapping regeneration | MAPQ-048 Stage 3 run `common_esto_20260816T062433503628Z` retained 100% of mapped values in all ten scope/source combinations; maximum drift `1.1641532182693481e-10`; ESTO anchors passed 465/465 and 405/405 |
| `leap_dashboard` default suite | 258 passed in 375.25 seconds |
| Dashboard regeneration evidence | MAPQ-048 shared diagnostics contained zero ESTO flow issue cards; USA and Brunei smoke renders wrote 1,361 charts; readiness passed all 42 roots; page-noise reported zero flags |
| `leap_review_tools` | 50 passed, 1 deselected; one deprecation warning; 12.58 seconds |
| `leap_review_web_app` | 13 passed; one deprecation warning; 8.71 seconds |

The mapping contract remains CSV.gz intentionally. Its measured Parquet result
is substantially smaller and faster, but migrating the published boundary
requires an atomic producer, delta, dashboard, review, portable-runtime, test,
manifest and baseline transition. No review or deployed runtime was hand-edited
or given an unnecessary Parquet dependency.

## Labelled supply-reconciliation run

The supported process runner executed all 16 configured economies with the
explicit base label `PARQUET_MIGRATION_FULL_20260816`, the pinned
`C:\Users\Work\miniconda3\python.exe` interpreter, a two-year horizon, three
scenarios and at most two workers. It ran from 16:12:56 to approximately
18:39:30 JST and was never interrupted.

Resource evidence from
`outputs/parquet_migration/full_system_validation/PARQUET_MIGRATION_FULL_20260816/runner_logs/concurrency_resource_diagnostics.json`:

- 16 logical / 8 physical CPUs; 27.65 GiB RAM;
- 14.07 GiB available before the run;
- two workers observed at peak;
- 4.84 GiB peak aggregate worker RSS;
- 9.23 GiB calculated available headroom at peak; and
- 2.72 GiB maximum individual worker RSS.

### Cache-format result

Nine economies with available templates (`01_AUS`, `02_BD`, `05_PRC`,
`10_MAS`, `11_MEX`, `12_NZ`, `13_PNG`, `15_PHL`, `16_RUS`) each wrote one
versioned balance-demand bundle and one versioned transform/supply bundle: 18
bundles and 162 Parquet payload files in total, with zero pickle files.

A production-helper read of the completed AUS bundles restored all six expected
balance objects and all nine expected transform/supply objects. The seven
economies without templates wrote no cache bundle, as expected.

### Workflow disposition

`13_PNG` and `15_PHL` returned zero after about 35 minutes each. The other 14
workers returned nonzero for environment or pre-existing final-artifact gates,
not for Parquet serialization, schema, checksum or cache-read failures:

| Finding family | Economies / count |
|---|---|
| Missing economy-specific LEAP export template | `03_CDA`, `04_CHL`, `06_HKC`, `07_INA`, `08_JPN`, `09_ROK`, `14_PE` (7 economies) |
| Existing consolidated `missing_branch` groups after main workflow completion | `01_AUS` 5; `02_BD` 2; `05_PRC` 31; `10_MAS` 1; `11_MEX` 1; `12_NZ` 2; `16_RUS` 9 (51 groups total) |
| Compressed-preflight expression findings | `SEED-008=4` in later workers; the preflight retains these as blocking evidence |

Per the workflow owner's 2026-08-16 clarification, the seven unavailable
templates and 51 missing-branch groups are expected pending LEAP-area work,
just like model rows that have not yet been created. They become testable when
the corresponding LEAP work and fresh exports become available. They must stay
visible in workflow evidence, but they are not Parquet failures and do not
block the reversible archive proposal. The four `SEED-008` records remain a
separate, optional investigation tracked in work-queue item [45].

The first workers also exposed a code defect in template compatibility: the
synthetic `00_APEC` preflight aggregate was incorrectly sent to a one-area
template resolver. Commit `423cda1` routes it through the established APEC
template-path union without borrowing area IDs. Seven focused tests and the
full 1,447-test suite pass. Workers launched after the fix no longer reported
the sentinel error, providing real execution evidence in addition to tests.

## Archive gate

No archive proposal has yet been generated, no ZIP was created, and no original
was moved or deleted. Commit `368f999` adds a proposal-only generator that hashes
only explicit shared pickle-cache roots and old reference-cache CSVs with a
complete exact-key Parquet replacement. It excludes all historical run trees,
human outputs, contracts, source/configuration inputs, Git/worktrees and
reparse points.

The full-system evidence is sufficient for the storage-migration scope: cache
serialization, manifests, checksums, production reads and repository suites
passed, while the remaining model-coverage findings are separately owned. The
next step is therefore to generate the exact proposal, inspect every candidate
and exclusion, and present the manifest, sizes, free-space check and restoration
procedure for explicit approval. Generating the proposal does not authorize a
ZIP, move or deletion. Work-queue item [45] preserves the option to investigate
`SEED-008` independently without weakening its model-artifact gate.
