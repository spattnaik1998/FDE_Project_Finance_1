"""BLS Labor Statistics adapter.

The v2 endpoint needs a registered key (500 queries/day, 50 series, 20 years).
The supplied key is currently rejected, so this adapter probes v2 once and
falls back to the keyless v1 endpoint (25 queries/day, 25 series, 10 years)
rather than failing the run.  The fallback is logged loudly because it silently
narrows the available history.
"""

from __future__ import annotations

import logging

import pandas as pd

import config
from http_client import post_json

LOG = logging.getLogger("fetch.bls")

V2 = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
V1 = "https://api.bls.gov/publicAPI/v1/timeseries/data/"

MONTH_PERIODS = {f"M{i:02d}" for i in range(1, 13)}


def key_is_valid(api_key: str) -> bool:
    """Return True if the v2 endpoint accepts this registration key."""
    body = {"seriesid": ["LNS14000000"], "startyear": "2024",
            "endyear": "2024", "registrationkey": api_key}
    result = post_json(V2, source="bls.keycheck", payload=body)
    ok = result.get("status") == "REQUEST_SUCCEEDED"
    if not ok:
        # BLS echoes the submitted key back inside this message, so it is
        # redacted before it reaches a log. Without this, the first use of a
        # freshly rotated key prints it to the console.
        LOG.warning("source=bls status=key_rejected messages=%s",
                    config.redact(result.get("message")))
    return ok


def fetch_series(series_ids: list[str], start_year: int, end_year: int,
                 api_key: str | None = None) -> pd.DataFrame:
    """Fetch one or more BLS series as a tidy long DataFrame.

    Returns columns: series_id, year, period, period_name, date, value, footnotes.
    """
    use_v2 = bool(api_key) and key_is_valid(api_key)
    url = V2 if use_v2 else V1
    max_series, max_years = (50, 20) if use_v2 else (25, 10)

    if not use_v2:
        start_year = max(start_year, end_year - max_years + 1)
        LOG.warning("source=bls status=fallback_v1 window=%s-%s", start_year, end_year)

    rows: list[dict] = []
    for i in range(0, len(series_ids), max_series):
        chunk = series_ids[i:i + max_series]
        payload = {"seriesid": chunk, "startyear": str(start_year),
                   "endyear": str(end_year)}
        if use_v2:
            payload["registrationkey"] = api_key

        result = post_json(url, source="bls", payload=payload)
        if result.get("status") != "REQUEST_SUCCEEDED":
            # Redacted here too: an exception message ends up in a traceback,
            # which is if anything more likely to be pasted somewhere than a
            # log line is.
            raise RuntimeError(
                f"BLS rejected request: {config.redact(result.get('message'))}")

        for series in result.get("Results", {}).get("series", []):
            sid = series.get("seriesID")
            for obs in series.get("data", []):
                rows.append({
                    "series_id": sid,
                    "year": int(obs["year"]),
                    "period": obs["period"],
                    "period_name": obs.get("periodName"),
                    "value": pd.to_numeric(obs.get("value"), errors="coerce"),
                    "footnotes": ";".join(
                        f.get("text", "") for f in obs.get("footnotes", []) if f
                    ),
                })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    month = df["period"].isin(MONTH_PERIODS)
    df["date"] = pd.NaT
    df.loc[month, "date"] = pd.to_datetime(
        df.loc[month, "year"].astype(str) + "-" + df.loc[month, "period"].str[1:] + "-01"
    )
    return df.sort_values(["series_id", "year", "period"]).reset_index(drop=True)
