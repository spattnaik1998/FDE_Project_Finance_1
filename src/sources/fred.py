"""FRED (St. Louis Fed) adapter: series discovery plus observations."""

from __future__ import annotations

import pandas as pd

from http_client import get_json

BASE = "https://api.stlouisfed.org/fred"


def search_series(text: str, api_key: str, limit: int = 25) -> pd.DataFrame:
    """Search FRED's catalog so series choices are discovered, not guessed."""
    data = get_json(f"{BASE}/series/search", source="fred.search", params={
        "search_text": text, "api_key": api_key, "file_type": "json",
        "limit": limit, "order_by": "popularity", "sort_order": "desc"})
    rows = [{
        "id": s["id"], "title": s["title"], "frequency": s.get("frequency_short"),
        "units": s.get("units_short"), "seasonal": s.get("seasonal_adjustment_short"),
        "start": s.get("observation_start"), "end": s.get("observation_end"),
        "popularity": s.get("popularity"),
    } for s in data.get("seriess", [])]
    return pd.DataFrame(rows)


def fetch_observations(series_ids: list[str], api_key: str,
                       start: str = "1960-01-01") -> pd.DataFrame:
    """Fetch observations for several series into one tidy long DataFrame."""
    frames: list[pd.DataFrame] = []
    for sid in series_ids:
        data = get_json(f"{BASE}/series/observations", source="fred", params={
            "series_id": sid, "api_key": api_key, "file_type": "json",
            "observation_start": start})
        obs = data.get("observations", [])
        if not obs:
            continue
        df = pd.DataFrame(obs)[["date", "value"]]
        df["series_id"] = sid
        df["value"] = pd.to_numeric(df["value"], errors="coerce")  # FRED uses "." for NA
        frames.append(df)

    if not frames:
        return pd.DataFrame(columns=["series_id", "date", "value"])
    out = pd.concat(frames, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"])
    return out[["series_id", "date", "value"]].sort_values(["series_id", "date"]).reset_index(drop=True)


def fetch_metadata(series_ids: list[str], api_key: str) -> pd.DataFrame:
    """Fetch title/units/frequency for series so CSVs are self-documenting."""
    rows = []
    for sid in series_ids:
        data = get_json(f"{BASE}/series", source="fred.meta", params={
            "series_id": sid, "api_key": api_key, "file_type": "json"})
        for s in data.get("seriess", []):
            rows.append({"id": s["id"], "title": s["title"],
                         "units": s.get("units"), "frequency": s.get("frequency"),
                         "seasonal_adjustment": s.get("seasonal_adjustment"),
                         "start": s.get("observation_start"),
                         "end": s.get("observation_end"),
                         "notes": (s.get("notes") or "")[:500]})
    return pd.DataFrame(rows)
