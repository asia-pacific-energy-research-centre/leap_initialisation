"""Shared, scope-configured zero-row generation for LEAP export workflows."""
from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence

import pandas as pd


def zero_data_expression(scenario: object, *, base_year: int, final_year: int) -> str:
    """Return the established own-use zero expression for a LEAP scenario."""
    if str(scenario or "").strip().lower() in {"current accounts", "current account"}:
        return f"Data({int(base_year)},0.0)"
    tokens: list[str] = []
    for year in range(int(base_year), int(final_year) + 1):
        tokens.extend([str(year), "0.0"])
    return f"Data({', '.join(tokens)})"


def zero_fill_unset_rows(
    written_df: pd.DataFrame | None,
    universe: pd.DataFrame,
    *,
    include_prefixes: Sequence[str],
    exclude_prefixes: Sequence[str] = (),
    variables: Iterable[str] | None = None,
    exclude_variables: Iterable[str] = (),
    scenarios: Iterable[str] | None = None,
    key_columns: Sequence[str] = ("Branch Path", "Variable", "Scenario"),
    only_unset: bool,
    region: str | None,
    expression: str | Callable[[object], str],
    metadata_columns: Sequence[str] = (),
) -> pd.DataFrame:
    """Return zero rows from a filtered export universe, optionally only unset keys.

    Callers retain their own scope and expression conventions; this function only
    centralises filter, de-duplicate, and anti-join mechanics.
    """
    required = {"Branch Path", "Variable", "Scenario", *key_columns}
    if not required.issubset(universe.columns):
        return pd.DataFrame(columns=[*key_columns, "Region", *metadata_columns, "Expression"])
    selected = universe.copy()
    for column in required | {"Region"}:
        if column in selected:
            selected[column] = selected[column].fillna("").astype(str).str.strip()
    path = selected["Branch Path"]
    mask = path.str.startswith(tuple(include_prefixes))
    if exclude_prefixes:
        mask &= ~path.str.startswith(tuple(exclude_prefixes))
    if variables is not None:
        mask &= selected["Variable"].isin(list(variables))
    if exclude_variables:
        mask &= ~selected["Variable"].isin(list(exclude_variables))
    if scenarios is not None:
        mask &= selected["Scenario"].isin(list(scenarios))
    selected = selected.loc[mask].drop_duplicates(subset=list(key_columns), keep="first")
    if only_unset and written_df is not None and not written_df.empty:
        present = written_df.reindex(columns=list(key_columns)).copy()
        for column in key_columns:
            present[column] = present[column].fillna("").astype(str).str.strip()
        selected = selected.merge(present.drop_duplicates(), on=list(key_columns), how="left", indicator=True)
        selected = selected[selected["_merge"].eq("left_only")].drop(columns=["_merge"])
    if selected.empty:
        return pd.DataFrame(columns=[*key_columns, "Region", *metadata_columns, "Expression"])
    result = selected.reindex(columns=list(key_columns)).copy()
    result["Region"] = region if region is not None else selected["Region"].values
    for column in metadata_columns:
        result[column] = selected[column].fillna("") if column in selected else ""
    result["Expression"] = selected["Scenario"].map(expression) if callable(expression) else expression
    return result.reset_index(drop=True)
