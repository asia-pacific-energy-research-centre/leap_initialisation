#%%
# Summary: split_documented_exclusions is the single shared implementation of the
# "known aggregate fuel name / zero-energy prefix" masking logic that used to be
# duplicated across supply_leap_io.py (x2) and patch_baseline_seeds.py.

import pandas as pd

from codebase.functions.patch_baseline_seeds import (
    VALIDATION_IGNORE_FUEL_NAMES,
    VALIDATION_IGNORE_PREFIXES,
    split_documented_exclusions,
)


def test_excludes_known_aggregate_fuel_names():
    fuel_name = next(iter(VALIDATION_IGNORE_FUEL_NAMES))
    df = pd.DataFrame({
        "Branch Path": [f"Transformation\\Coke ovens\\Output Fuels\\{fuel_name}",
                         "Transformation\\Coke ovens\\Output Fuels\\Coke oven coke"],
    })
    kept, excluded = split_documented_exclusions(df)
    assert list(excluded["Branch Path"]) == [df["Branch Path"].iloc[0]]
    assert list(kept["Branch Path"]) == [df["Branch Path"].iloc[1]]


def test_excludes_known_zero_energy_prefixes():
    prefix = next(iter(VALIDATION_IGNORE_PREFIXES))
    df = pd.DataFrame({
        "Branch Path": [f"{prefix}Output Fuels\\Ethanol",
                         "Transformation\\Coke ovens\\Output Fuels\\Coke oven coke"],
    })
    kept, excluded = split_documented_exclusions(df)
    assert list(excluded["Branch Path"]) == [df["Branch Path"].iloc[0]]
    assert list(kept["Branch Path"]) == [df["Branch Path"].iloc[1]]


def test_respects_custom_branch_path_column_name():
    fuel_name = next(iter(VALIDATION_IGNORE_FUEL_NAMES))
    df = pd.DataFrame({
        "BP": [f"Transformation\\Coke ovens\\Output Fuels\\{fuel_name}"],
    })
    kept, excluded = split_documented_exclusions(df, branch_path_col="BP")
    assert kept.empty
    assert len(excluded) == 1


def test_keeps_rows_with_no_matching_exclusion():
    df = pd.DataFrame({
        "Branch Path": ["Transformation\\Coke ovens\\Output Fuels\\Coke oven coke"],
    })
    kept, excluded = split_documented_exclusions(df)
    assert len(kept) == 1
    assert excluded.empty
#%%
