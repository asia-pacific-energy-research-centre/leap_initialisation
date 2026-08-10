# Aggregated-demand template coverage audit

`codebase/aggregated_demand_template_coverage_workflow.py` preserves the
repeatable audit used to identify missing LEAP branches for aggregated demand.

The workflow:

1. loads ESTO once for the configured base year (currently 2022);
2. loads the Ninth Outlook once for the projection base year (currently 2023);
3. builds nonzero sector/fuel branch paths for every economy using Reference
   and Target projections, excluding own use and transmission/distribution
   losses because the separate proxy workflow owns those flows;
4. compares each economy with a template against its own exact paths;
5. compares the all-economy path union against the APEC union of all active
   economy templates; and
6. writes one `Economy, Branch Path` CSV containing both the real-economy gaps
   and synthetic `APEC` fallback gaps.

Run the file as a Jupyter notebook or in an interactive Python editor. The
bottom `RUN_AGGREGATED_DEMAND_TEMPLATE_COVERAGE_AUDIT` toggle controls the run.
The default output is:

`outputs/aggregated_demand_fuel_audit/all_economies_and_apec_missing_aggregated_demand_branches.csv`

The APEC union is a structural branch-existence catalog. It must never supply
BranchID, VariableID, ScenarioID, or RegionID values for another LEAP area.
Exact path case is preserved because active templates currently contain a few
case-only spelling variants.
