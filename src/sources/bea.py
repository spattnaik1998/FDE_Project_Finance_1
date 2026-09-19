"""BEA adapter: GDP by Industry and Fixed Assets.

BEA returns a deeply nested envelope and encodes every value as a string with
thousands separators; normalisation happens here so callers see a tidy frame.
"""

from __future__ import annotations

import pandas as pd

from http_client import get_json, FetchError

BASE = "https://apps.bea.gov/api/data"


def _results(payload: dict, source: str) -> dict:
    """Normalise BEA's envelope.

    ``Results`` is a dict for most datasets but a single-element *list* for
    GDPbyIndustry, so both shapes are unwrapped here rather than at each call
    site.
    """
    api = payload.get("BEAAPI", {})
    if api.get("Error"):
        raise FetchError(f"{source}: BEA error :: {api['Error']}")

    results = api.get("Results", {})
    if isinstance(results, list):
        results = results[0] if results else {}
    if isinstance(results, dict) and results.get("Error"):
        raise FetchError(f"{source}: BEA error :: {results['Error']}")
    return results


def list_datasets(api_key: str) -> pd.DataFrame:
    """Return BEA's dataset catalog."""
    data = get_json(BASE, source="bea.datasets", params={
        "UserID": api_key, "method": "GETDATASETLIST", "ResultFormat": "JSON"})
    return pd.DataFrame(_results(data, "bea.datasets").get("Dataset", []))


def parameter_values(api_key: str, dataset: str, parameter: str) -> pd.DataFrame:
    """Return allowed values for a dataset parameter (tables, years, industries)."""
    data = get_json(BASE, source="bea.params", params={
        "UserID": api_key, "method": "GetParameterValues", "datasetname": dataset,
        "ParameterName": parameter, "ResultFormat": "JSON"})
    return pd.DataFrame(_results(data, "bea.params").get("ParamValue", []))


def gdp_by_industry(api_key: str, table_id: int, frequency: str = "A",
                    year: str = "ALL", industry: str = "ALL") -> pd.DataFrame:
    """Fetch a GDP-by-Industry table as a tidy frame."""
    data = get_json(BASE, source=f"bea.gdpindustry.t{table_id}", params={
        "UserID": api_key, "method": "GetData", "datasetname": "GDPbyIndustry",
        "TableID": table_id, "Frequency": frequency, "Year": year,
        "Industry": industry, "ResultFormat": "JSON"})
    rows = _results(data, "bea.gdpindustry").get("Data", [])
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["DataValue"] = pd.to_numeric(
        df["DataValue"].astype(str).str.replace(",", "", regex=False), errors="coerce")
    df["TableID"] = table_id
    return df


def nipa_table(api_key: str, table_name: str, frequency: str = "A",
               year: str = "ALL") -> pd.DataFrame:
    """Fetch a NIPA / FixedAssets style table by name."""
    dataset = "FixedAssets" if table_name.startswith("FAAt") else "NIPA"
    params = {"UserID": api_key, "method": "GetData", "datasetname": dataset,
              "Year": year, "ResultFormat": "JSON"}
    if dataset == "FixedAssets":
        params["TableName"] = table_name
    else:
        params["TableName"] = table_name
        params["Frequency"] = frequency

    data = get_json(BASE, source=f"bea.{dataset}.{table_name}", params=params)
    rows = _results(data, f"bea.{dataset}").get("Data", [])
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["DataValue"] = pd.to_numeric(
        df["DataValue"].astype(str).str.replace(",", "", regex=False), errors="coerce")
    df["TableName"] = table_name
    return df
