[WARN] Analysis-input config mapping mismatches detected against full model export metadata.
[WARN] Mapping mismatches: 18246 (details saved to C:\Users\Work\github\leap_utilities\outputs\leap_exports\supply_reconciliation\supporting_files\checks\supply_reconciliation_config_mapping_mismatches.csv)
  - scope='variable' | branch='nan' | variable='Share of Total Imports' | field='units' | config='Percent' | reference='' | issue='no_reference_match'
  - scope='variable' | branch='nan' | variable='Share of Total Imports' | field='scale' | config='nan' | reference='' | issue='no_reference_match'
  - scope='variable' | branch='nan' | variable='Share of Total Imports' | field='per' | config='nan' | reference='' | issue='no_reference_match'
  - scope='variable' | branch='nan' | variable='Average Mileage' | field='units' | config='Kilometer' | reference='' | issue='no_reference_match'
  - scope='variable' | branch='nan' | variable='Average Mileage' | field='scale' | config='nan' | reference='' | issue='no_reference_match'
  - scope='variable' | branch='nan' | variable='Average Mileage' | field='per' | config='nan' | reference='' | issue='no_reference_match'
  - scope='variable' | branch='nan' | variable='Delivered Cost' | field='units' | config='U.S. Dollar' | reference='' | issue='no_reference_match'
  - scope='variable' | branch='nan' | variable='Delivered Cost' | field='scale' | config='nan' | reference='' | issue='no_reference_match'
  - scope='variable' | branch='nan' | variable='Delivered Cost' | field='per' | config='Gigajoule' | reference='' | issue='no_reference_match'
  - scope='variable' | branch='nan' | variable='Device Share' | field='units' | config='Share' | reference='' | issue='no_reference_match'
  - scope='variable' | branch='nan' | variable='Device Share' | field='scale' | config='%' | reference='' | issue='no_reference_match'
  - scope='variable' | branch='nan' | variable='Device Share' | field='per' | config='nan' | reference='' | issue='no_reference_match'
  - scope='variable' | branch='nan' | variable='Final On-Road Fuel Economy' | field='units' | config='Percent' | reference='' | issue='no_reference_match'
  - scope='variable' | branch='nan' | variable='Final On-Road Fuel Economy' | field='scale' | config='nan' | reference='' | issue='no_reference_match'
  - scope='variable' | branch='nan' | variable='Final On-Road Fuel Economy' | field='per' | config='nan' | reference='' | issue='no_reference_match'
  - scope='variable' | branch='nan' | variable='Final On-Road Mileage' | field='units' | config='Kilometer' | reference='' | issue='no_reference_match'
  - scope='variable' | branch='nan' | variable='Final On-Road Mileage' | field='scale' | config='nan' | reference='' | issue='no_reference_match'
  - scope='variable' | branch='nan' | variable='Final On-Road Mileage' | field='per' | config='nan' | reference='' | issue='no_reference_match'
  - scope='variable' | branch='nan' | variable='First Sales Year' | field='units' | config='Years' | reference='' | issue='no_reference_match'
  - scope='variable' | branch='nan' | variable='First Sales Year' | field='scale' | config='nan' | reference='' | issue='no_reference_match'
  - scope='variable' | branch='nan' | variable='First Sales Year' | field='per' | config='nan' | reference='' | issue='no_reference_match'
  - scope='variable' | branch='nan' | variable='Fraction of Scrapped Replaced' | field='units' | config='Percent' | reference='' | issue='no_reference_match'
  - scope='variable' | branch='nan' | variable='Fraction of Scrapped Replaced' | field='scale' | config='%' | reference='' | issue='no_reference_match'
  - scope='variable' | branch='nan' | variable='Fraction of Scrapped Replaced' | field='per' | config='nan' | reference='' | issue='no_reference_match'
  - scope='variable' | branch='nan' | variable='Fuel Economy' | field='units' | config='MJ/100 km' | reference='' | issue='no_reference_match'
  - scope='variable' | branch='nan' | variable='Fuel Economy' | field='scale' | config='nan' | reference='' | issue='no_reference_match'
  - scope='variable' | branch='nan' | variable='Fuel Economy' | field='per' | config='nan' | reference='' | issue='no_reference_match'
  - scope='variable' | branch='nan' | variable='Fuel Economy Correction Factor' | field='units' | config='Percent' | reference='' | issue='no_reference_match'
  - scope='variable' | branch='nan' | variable='Fuel Economy Correction Factor' | field='scale' | config='nan' | reference='' | issue='no_reference_match'
  - scope='variable' | branch='nan' | variable='Fuel Economy Correction Factor' | field='per' | config='nan' | reference='' | issue='no_reference_match'
  ... plus 18216 more mapping mismatches
[INFO] Saved single-file results workbook in full-model Export structure to C:\Users\Work\github\leap_utilities\outputs\leap_exports\supply_reconciliation\supply_reconciliation_run_baseline_seed_01_AUS-02_BD-03_CDA-04_CHL-05_PRC-06_HKC-07_INA-08_JPN-09_ROK-10_MAS-11_MEX-12_NZ-13_PNG-14_PE-15_PHL-16_RUS-17_SGP-18_CT-19_THA-20_USA-21_VN_ref_ca.xlsx
[TIMING] supply_reconciliation | write consolidated run workbook | 0h 0m 54.3s
[TIMING] supply_reconciliation | write balance matching diagnostics | 0h 0m 1.2s
[TIMING] supply_reconciliation | write balance-demand issue report | 0h 0m 0.4s
[INFO] Ignoring non-demand balance mapping issues that do not affect supply_reconciliation demand inputs. See C:\Users\Work\github\leap_utilities\outputs\leap_exports\supply_reconciliation\supporting_files\checks\supply_reconciliation_balance_demand_issues.csv. Ignored rows: 22921
[WARN] Source diagnostics written to C:\Users\Work\github\leap_utilities\outputs\leap_exports\supply_reconciliation\supporting_files\checks\supply_reconciliation_source_diagnostics.csv. Counts: missing_esto_pair: 22921, missing_full_model_export_branch: 2
  - missing_esto_pair | source=balance_demand | scenario=Reference | branch=Production
  - missing_esto_pair | source=balance_demand | scenario=Reference | branch=Imports
  - missing_esto_pair | source=balance_demand | scenario=Reference | branch=Imports
  - missing_esto_pair | source=balance_demand | scenario=Reference | branch=Total Primary Supply
  - missing_esto_pair | source=balance_demand | scenario=Reference | branch=Total Primary Supply
[TIMING] supply_reconciliation | write source diagnostics | 0h 0m 3.7s

======================================================================
[ERROR] 2 rows have BranchID=-1 AND non-zero values.
        LEAP silently skips these on import — feedstock/process shares will
        sum to less than 100%. All outputs above have been saved.
        Fix: export a fresh 'full model export.xlsx' from LEAP that includes
        all active branches, then re-run.
======================================================================
  [ERROR] BranchID=-1 | non-zero | Branch Path='Transformation\Biofuels processing\Processes\Biofuels processing' | Variable='Process Share' | Scenario='Reference' | Region='United States'
  [ERROR] BranchID=-1 | non-zero | Branch Path='Transformation\Biofuels processing\Processes\Biofuels processing' | Variable='Process Share' | Scenario='Current Accounts' | Region='United States'

[TIMING] supply_reconciliation | total | 11h 13m 8.9s
[TIMING] supply_reconciliation timing written to C:\Users\Work\github\leap_utilities\outputs\leap_exports\supply_reconciliation\supporting_files\runtime\workflow_stage_timings.csv
[INFO] Windows sleep prevention released.
Traceback (most recent call last):
  File "C:\Users\Work\github\leap_utilities\codebase\supply_reconciliation_workflow.py", line 13629, in <module>
    run_with_config()
    ~~~~~~~~~~~~~~~^^
  File "C:\Users\Work\github\leap_utilities\codebase\supply_reconciliation_workflow.py", line 13518, in run_with_config
    return _run_with_config_inner()
  File "C:\Users\Work\github\leap_utilities\codebase\supply_reconciliation_workflow.py", line 13598, in _run_with_config_inner
    output = run_results_linked_transformation_supply_workflow(
        economies=ECONOMIES,
    ...<4 lines>...
        scrape_leap_results=SCRAPE_LEAP_RESULTS,
    )
  File "C:\Users\Work\github\leap_utilities\codebase\supply_reconciliation_workflow.py", line 13271, in run_results_linked_transformation_supply_workflow
    raise RuntimeError(
    ...<5 lines>...
    )
RuntimeError: 2 output row(s) have BranchID=-1 with non-zero values. All requested outputs were written, but these rows must be fixed before LEAP import because LEAP will skip unknown branch IDs. Results workbook: C:\Users\Work\github\leap_utilities\outputs\leap_exports\supply_reconciliation\supply_reconciliation_run_baseline_seed_01_AUS-02_BD-03_CDA-04_CHL-05_PRC-06_HKC-07_INA-08_JPN-09_ROK-10_MAS-11_MEX-12_NZ-13_PNG-14_PE-15_PHL-16_RUS-17_SGP-18_CT-19_THA-20_USA-21_VN_ref_ca.xlsx. Diagnostics: C:\Users\Work\github\leap_utilities\outputs\leap_exports\supply_reconciliation\supporting_files\checks\supply_reconciliation_source_diagnostics.csv.