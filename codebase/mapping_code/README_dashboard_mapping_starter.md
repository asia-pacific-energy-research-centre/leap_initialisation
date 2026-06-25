# Dashboard mapping starter prototype

This folder contains a first-pass prototype for the ESTO-first dashboard mapping workflow.

## Files

- `codebase/mapping_tools/build_dashboard_graph_index.py`
  - reads the dashboard template JSON from repo `config/` if present, otherwise from this uploaded folder's `config/`
  - assigns `graph_id` and `use_case = "dashboard"` to every `aggregate_graphs` and `by_fuel_graphs` object in a copied JSON
  - writes graph index CSVs to repo `results/mapping_graph_index/`
  - writes product-aware flow/product graph matching rules

- `codebase/mapping_tools/convert_leap_combined_esto_to_esto_first.py`
  - reads repo `config/leap_mappings.xlsx`, sheet `leap_combined_esto`
  - normalises the mapping columns
  - converts to a flat ESTO-first dashboard mapping table
  - attaches graph IDs by `esto_flow` and product matching rules
  - writes a long graph-link table and QA tables

## Expected repo layout

The scripts are currently placed in:

```text
<repo root>/codebase/mapping_code/codebase/mapping_tools/
```

The default paths are:

```text
<repo root>/config/leap_mappings.xlsx
<repo root>/results/mapping_graph_index/
<repo root>/config/leap_comparison_dashboard_template_v3.json
<repo root>/codebase/mapping_code/config/leap_comparison_dashboard_template_v3.json
```

The graph-index script uses the repo template path if it exists. If it does not, it falls back to the uploaded template in `codebase/mapping_code/config/`.

## Run order

```powershell
& 'C:\Users\Work\miniconda3\python.exe' codebase\mapping_code\codebase\mapping_tools\build_dashboard_graph_index.py
& 'C:\Users\Work\miniconda3\python.exe' codebase\mapping_code\codebase\mapping_tools\convert_leap_combined_esto_to_esto_first.py
```

## Outputs

```text
results/mapping_graph_index/leap_comparison_dashboard_template_v3_with_graph_ids.json
results/mapping_graph_index/dashboard_graph_index.csv
results/mapping_graph_index/dashboard_graph_flow_index.csv
results/mapping_graph_index/dashboard_graph_product_index.csv
results/mapping_graph_index/dashboard_graph_flow_product_index.csv
results/mapping_graph_index/esto_first_mapping_candidates_dashboard.csv
results/mapping_graph_index/esto_first_mapping_candidates_dashboard.xlsx
results/mapping_graph_index/dashboard_mapping_graph_links.csv
results/mapping_graph_index/dashboard_active_mapping_rows_not_in_template.csv
results/mapping_graph_index/dashboard_all_source_rows_not_in_template.csv
results/mapping_graph_index/dashboard_template_flows_without_active_leap_mapping.csv
results/mapping_graph_index/dashboard_mapping_duplicate_active_source_rows.csv
results/mapping_graph_index/dashboard_mapping_duplicate_active_esto_rows.csv
results/mapping_graph_index/dashboard_mapping_parent_child_risks.csv
```

## Test results from repo config

- Graph configs found: 113
- Unique ESTO flows in dashboard template: 69
- Graph-flow-product rule rows: 7,153
- Mapping rows converted: 3,664
- Active mappings: 2,352
- Inactive mappings: 1,312
- Product-aware graph links: 8,344
- Active mapping rows not linked to a graph: 218
- All source rows not linked to a graph: 472
- Template flows without active LEAP mappings: 6
- Duplicate active source mapping groups: 378
- Duplicate active ESTO mapping groups: 350
- Parent/child risk rows: 271
