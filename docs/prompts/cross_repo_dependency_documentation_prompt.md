# Prompt: Document cross-repository data dependencies

## Short version

Audit `leap_initialisation`, `leap_mappings`, and `leap_dashboard`, then create
one accurate, maintainable Markdown document explaining repository ownership,
data lineage, file dependencies, refresh order, and runtime boundaries. Include
Mermaid flow maps and file-level dependency tables. Discover additional
dependencies throughout the repositories rather than relying only on the
examples in this prompt.

This is a documentation and investigation task. Do not refactor production code,
move data, regenerate large datasets, or change mapping methodology unless a
small documentation-supporting correction is explicitly approved.

## Repositories

The expected sibling layout is:

```text
C:\Users\Work\github\leap_initialisation\
C:\Users\Work\github\leap_mappings\
C:\Users\Work\github\leap_dashboard\
```

Raw LEAP Energy Balance workbooks are canonically owned by:

```text
C:\Users\Work\github\leap_initialisation\data\leap balances exports\
```

Legacy copies may exist under `data/archive/leap balances exports/` in other
repositories. Treat archive folders as historical/reference data, not active
inputs.

## Required first steps

1. Read the applicable `AGENTS.md` files in all three repositories and the
   relevant global balance-table and LEAP-export instructions.
2. Run `git status --short` in all three repositories.
3. Preserve unrelated uncommitted changes. Do not edit or commit files already
   being changed by another agent without asking the user.
4. Inspect the existing centralisation audit:
   `leap_initialisation/docs/leap_balance_export_centralisation_audit.md`.
5. Verify current paths, function names, and configuration against the code;
   do not trust stale line numbers or this prompt blindly.

## Investigation scope

Search tracked source, configuration, tests, notebooks/scripts, and active
documentation in all three repositories for at least:

- `leap_initialisation`
- `leap_mappings`
- `leap_dashboard`
- `leap balances exports`
- `raw_leap_results.csv`
- `leap_results_converted_to_esto.csv`
- `common_esto_comparison_data.csv`
- `common_esto_rows.csv`
- `outputs/leap_exports`
- `capacity_unmet_convergence.csv`
- ESTO and 9th Outlook source files
- mapping workbooks and relationship outputs
- dashboard input/output paths
- environment variables and sibling-repository path resolution

Use `rg`/`rg --files` first. Exclude generated `results/`, `outputs/`, published
dashboard artifacts, caches, and archives from broad code searches where
appropriate, but inspect generated-file assumptions and representative output
locations separately.

Identify both direct and indirect dependencies. In particular, distinguish:

```text
raw LEAP workbook
  -> leap_mappings parser/converter
  -> Common ESTO comparison outputs
  -> leap_dashboard renderer
```

The dashboard does not directly read raw LEAP workbooks at runtime, but its
Common ESTO inputs may ultimately be derived from them. Explain that distinction
explicitly as runtime dependency versus upstream data-lineage dependency.

## Deliverable document

Create or update a single cross-repository guide at:

```text
leap_initialisation/docs/cross_repo_data_dependencies.md
```

Use the existing documentation style and keep the guide useful to both a new
modeller and a developer. It should include:

### 1. Executive summary

- What each repository owns.
- What each repository consumes.
- What each repository produces.
- The difference between raw, intermediate, derived, diagnostic, and published
  artifacts.

### 2. Repository ownership matrix

Include rows for at least:

- Raw LEAP balance workbooks.
- Full model export/template workbooks.
- ESTO historical data.
- 9th Outlook data.
- Mapping workbooks/configuration.
- Raw parsed LEAP results.
- Converted LEAP/ESTO relationship data.
- Common ESTO comparison rows and comparison data.
- Initialisation LEAP import/export products.
- Capacity-unmet convergence diagnostics.
- Dashboard HTML/chart outputs.

For each row document owner, active location, producers, consumers, whether it
is committed/generated/ignored, and whether it may be archived.

### 3. Mermaid data-flow maps

Create small readable diagrams rather than one giant diagram. Include:

- End-to-end data lineage from raw source files to dashboard output.
- `leap_mappings` pipeline stages.
- `leap_initialisation` workflow outputs and optional diagnostic feeds.
- Dashboard runtime inputs and publishing outputs.
- Refresh order across repositories.

Use Mermaid syntax compatible with the repository documentation tooling. Avoid
overly wide diagrams and use subgraphs for repository boundaries.

### 4. File dependency tables

List important files with columns such as:

| Repository | File/path | Type | Reads | Writes | Direct or indirect dependency | Refresh trigger |
|---|---|---|---|---|---|---|

Include actual module/workflow names and not only broad folder names. Record
environment-variable overrides and sibling-repository assumptions.

### 5. Operational runbooks

Document:

- How to add or refresh a raw LEAP export.
- How to run the mapping pipeline after a raw export changes.
- How to render the dashboard from existing Common ESTO outputs.
- Which steps can run without raw LEAP files.
- Which steps require raw LEAP files.
- How to identify stale derived outputs.
- How to handle missing economy/scenario workbooks.
- Which archive folders are historical and must not be used implicitly.

### 6. Dependency scenarios

Explain expected behavior for at least:

- Raw LEAP exports present; mapping outputs absent.
- Raw LEAP exports absent; existing Common ESTO outputs present.
- ESTO/9th data present but no LEAP export for an economy.
- Optional convergence diagnostic absent.
- Non-standard sibling checkout using an environment override.
- Archived legacy raw exports present but active folders absent.

State whether the system should fail, warn, skip, or continue in each case,
based on observed code behavior.

### 7. Risks and unresolved items

Record hardcoded paths, implicit dependencies, stale documentation, duplicated
inputs, generated outputs that are treated as source files, and any mismatch
between documented and observed behavior. Do not silently fix these during this
task; classify them and recommend a follow-up.

## Validation requirements

Before finalizing the document:

1. Verify every important path in the guide with `rg` or direct filesystem
   inspection.
2. Trace the actual call sites for raw LEAP parsing, Common ESTO generation,
   dashboard loading, and convergence loading.
3. Run focused existing tests relevant to path resolution and dashboard inputs.
4. If safe and reasonably quick, run read-only/import-level smoke checks; do not
   run the long-running supply reconciliation workflow.
5. Run `git diff --check` in every changed repository.
6. Check that no generated outputs or raw data files were accidentally added.

## Stop conditions

Ask the user before proceeding if:

- the canonical repository layout is different from the one above;
- a proposed documentation statement conflicts with observed runtime behavior
  and resolving it would require a code or data change;
- a file appears to be actively edited by another agent;
- the task would require moving, deleting, regenerating, or overwriting data;
- ownership of a shared file cannot be determined safely.

Otherwise, make reasonable assumptions, record them in the guide, and continue.

## Final report

Report:

- the document created/updated;
- the repositories and paths audited;
- key direct and indirect dependencies discovered;
- commands/tests run and results;
- unresolved risks or follow-up tasks;
- Git status and exactly which files were committed.

Once the work is complete, tested, and committed, move this prompt from
`docs/prompts/` to `docs/archive/` and add a short status note if the resulting
guide contains important decisions.
