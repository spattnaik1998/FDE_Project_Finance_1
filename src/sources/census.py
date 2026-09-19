"""Census Bureau adapter: ABS technology modules, BDS, and CBP.

The Census API returns a header row followed by data rows, all as strings.
:func:`_to_frame` applies the header and coerces the numeric columns each
dataset actually uses.
"""

from __future__ import annotations

import pandas as pd

from http_client import get_json

BASE = "https://api.census.gov/data"

NUMERIC_HINTS = (
    "FIRMPDEMP", "EMP", "PAYANN", "RCPPDEMP", "ESTAB", "FIRM", "JOB_",
    "NET_JOB", "REALLOCATION", "FIRMDEATH", "ESTABS_", "_PCT", "_S",
)


def _to_frame(rows: list[list[str]]) -> pd.DataFrame:
    if not rows or len(rows) < 2:
        return pd.DataFrame()
    df = pd.DataFrame(rows[1:], columns=rows[0])
    for col in df.columns:
        if any(h in col for h in NUMERIC_HINTS):
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def fetch(dataset: str, get_vars: list[str], api_key: str,
          geo: str = "us:*", **filters: str) -> pd.DataFrame:
    """Fetch any Census dataset path with the given variables and filters."""
    params = {"get": ",".join(get_vars), "for": geo, "key": api_key}
    params.update(filters)
    rows = get_json(f"{BASE}/{dataset}", source=f"census.{dataset}", params=params)
    return _to_frame(rows)


def variables(dataset: str) -> pd.DataFrame:
    """Return the variable dictionary for a dataset (no key required)."""
    data = get_json(f"{BASE}/{dataset}/variables.json", source=f"census.{dataset}.vars")
    rows = [{"name": k, "label": v.get("label"), "concept": v.get("concept"),
             "predicate_type": v.get("predicateType")}
            for k, v in data.get("variables", {}).items()]
    return pd.DataFrame(rows).sort_values("name").reset_index(drop=True)
