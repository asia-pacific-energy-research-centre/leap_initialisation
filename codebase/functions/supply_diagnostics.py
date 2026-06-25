#%%
# Summary: Diagnostic print helpers for the supply workflow.

from codebase.functions.esto_data_utils import sum_years, try_debug_breakpoint
from codebase.functions.supply_value_series import (
    get_years_from,
    select_flow_rows,
    select_fuel_rows,
)


#%%
######### FUNCTIONS #########
def print_flow_rows(
    df,
    label,
    year_cols,
    print_fuel_rows: bool = True,
    print_only_nonzero_rows: bool = True,
    print_top_rows: int = 10,
):
    """Print flow rows for debugging."""
    try:
        if not print_fuel_rows:
            return
        if df.empty:
            print(f"{label}: no rows found")
            return
        summary = df.copy()
        summary["total_base_year"] = summary[year_cols].sum(axis=1)
        if print_only_nonzero_rows:
            summary = summary[summary["total_base_year"] != 0]
        if summary.empty:
            print(f"{label}: no nonzero rows after filtering")
            return
        columns_to_show = [
            "scenarios",
            "economy",
            "sectors",
            "flows",
            "fuels",
            "subfuels",
            "products",
            "total_base_year",
        ]
        columns_to_show = [col for col in columns_to_show if col in summary.columns]
        print(f"{label}: rows {summary.shape[0]}")
        print(summary[columns_to_show].head(print_top_rows).to_string(index=False))
    except Exception as exc:
        print(f"Failed to print flow rows: {exc}")
        try_debug_breakpoint()
        raise


def summarize_supply_for_fuel(
    data,
    year_cols,
    economy,
    fuel_config,
    flow_codes,
    base_year,
    code_to_name_mapping=None,
    print_fuel_rows: bool = True,
    print_only_nonzero_rows: bool = True,
    print_top_rows: int = 10,
):
    """Print import/export totals for a fuel and economy."""
    try:
        year_cols_from_base = get_years_from(year_cols, base_year)
        display_name = fuel_config.get("fuel_name", fuel_config["fuel_label_esto"])
        fuel_rows = select_fuel_rows(
            data,
            fuel_config["fuel_code_ninth"],
            fuel_config["fuel_label_esto"],
            fuel_name=fuel_config.get("fuel_name"),
            code_to_name_mapping=code_to_name_mapping,
        )
        if fuel_rows.empty:
            print(f"{display_name}: no fuel rows found")
            return

        imports_rows = select_flow_rows(fuel_rows, economy, flow_codes["imports"])
        exports_rows = select_flow_rows(fuel_rows, economy, flow_codes["exports"])

        print_flow_rows(
            imports_rows,
            f"{economy} imports",
            year_cols_from_base,
            print_fuel_rows=print_fuel_rows,
            print_only_nonzero_rows=print_only_nonzero_rows,
            print_top_rows=print_top_rows,
        )
        print_flow_rows(
            exports_rows,
            f"{economy} exports",
            year_cols_from_base,
            print_fuel_rows=print_fuel_rows,
            print_only_nonzero_rows=print_only_nonzero_rows,
            print_top_rows=print_top_rows,
        )

        imports_total = sum_years(imports_rows, year_cols_from_base)
        exports_total = sum_years(exports_rows, year_cols_from_base)

        print(
            f"{economy} {display_name} (base {base_year}): "
            f"imports {imports_total:.3f}, exports {exports_total:.3f}"
        )
    except Exception as exc:
        print(f"Failed to summarize supply for {fuel_config}: {exc}")
        try_debug_breakpoint()
        raise


def list_unique_fuels_and_products(ninth_data, esto_data):
    """Print unique fuel/subfuel combos (9th) and products (ESTO)."""
    try:
        if "fuels" in ninth_data.columns and "subfuels" in ninth_data.columns:
            fuels = (
                ninth_data[["fuels", "subfuels"]]
                .dropna()
                .drop_duplicates()
                .sort_values(["fuels", "subfuels"])
            )
            fuel_pairs = list(fuels.itertuples(index=False, name=None))
            print(f"9th fuel/subfuel combos: {len(fuel_pairs)}")
            for fuel, subfuel in fuel_pairs:
                print(f"- {fuel} / {subfuel}")
        else:
            print("9th data missing fuels/subfuels columns")

        if "products" in esto_data.columns:
            products = (
                esto_data[["products"]]
                .dropna()
                .drop_duplicates()
                .sort_values(["products"])
            )
            product_list = products["products"].astype(str).tolist()
            print(f"ESTO products: {len(product_list)}")
            for product in product_list:
                print(f"- {product}")
        else:
            print("ESTO data missing products column")
    except Exception as exc:
        print(f"Failed to list unique fuels/products: {exc}")
        try_debug_breakpoint()
        raise


#%%
