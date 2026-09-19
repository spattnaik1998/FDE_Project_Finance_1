"""Smoke-test each provider with one minimal live call.

Purpose is reconnaissance, not data collection: confirm the key works, learn the
response envelope, and surface the provider's own error text when it does not.
"""
from __future__ import annotations
import json, sys
sys.path.insert(0, "src")
import requests
from config import load_keys

KEYS = load_keys()
TIMEOUT = 45


def show(label: str, ok: bool, detail: str) -> None:
    print(f"\n{'='*70}\n{label}  ->  {'OK' if ok else 'PROBLEM'}\n{'='*70}")
    print(detail[:1800])


def probe_bls() -> None:
    r = requests.post(
        "https://api.bls.gov/publicAPI/v2/timeseries/data/",
        json={"seriesid": ["CES5552300001"], "startyear": "2022", "endyear": "2024",
              "registrationkey": KEYS["BLS_API_KEY"]},
        headers={"Content-Type": "application/json"}, timeout=TIMEOUT)
    d = r.json()
    series = d.get("Results", {}).get("series", [{}])[0]
    detail = (f"status={d.get('status')}  messages={d.get('message')}\n"
              f"series={series.get('seriesID')}  n_obs={len(series.get('data', []))}\n"
              f"latest={json.dumps(series.get('data', [{}])[0], indent=2)}")
    show("BLS v2 timeseries (CES5552300001 = securities/investment employment)",
         d.get("status") == "REQUEST_SUCCEEDED", detail)


def probe_bea() -> None:
    r = requests.get("https://apps.bea.gov/api/data", params={
        "UserID": KEYS["BEA_API_KEY"], "method": "GETDATASETLIST",
        "ResultFormat": "JSON"}, timeout=TIMEOUT)
    d = r.json()
    res = d.get("BEAAPI", {}).get("Results", {})
    sets = res.get("Dataset", [])
    detail = "\n".join(f"  {s['DatasetName']:24s} {s['DatasetDescription']}" for s in sets) \
        if sets else json.dumps(d)[:1500]
    show("BEA GETDATASETLIST", bool(sets), f"{len(sets)} datasets available\n{detail}")


def probe_fred() -> None:
    r = requests.get("https://api.stlouisfed.org/fred/series/observations", params={
        "series_id": "OPHNFB", "api_key": KEYS["FRED_API_KEY"], "file_type": "json",
        "observation_start": "2015-01-01"}, timeout=TIMEOUT)
    d = r.json()
    obs = d.get("observations", [])
    detail = (f"count={d.get('count')}  returned={len(obs)}\n"
              f"first={obs[0] if obs else None}\nlast={obs[-1] if obs else None}"
              if obs else json.dumps(d)[:1200])
    show("FRED observations (OPHNFB = nonfarm business output per hour)", bool(obs), detail)


def probe_census_btos() -> None:
    """Business Trends and Outlook Survey - the measured AI-adoption series."""
    r = requests.get("https://api.census.gov/data/timeseries/btos", params={
        "get": "cell_value,ref_date,answer_label", "for": "us:*",
        "time": "2024", "question_id": "B8", "key": KEYS["CENSUS_API_KEY"]},
        timeout=TIMEOUT)
    ok = r.status_code == 200
    detail = json.dumps(r.json()[:8], indent=1) if ok else f"HTTP {r.status_code}\n{r.text[:900]}"
    show("Census BTOS timeseries (question B8 = AI use in production)", ok, detail)


if __name__ == "__main__":
    for fn in (probe_bls, probe_bea, probe_fred, probe_census_btos):
        try:
            fn()
        except Exception as exc:  # reconnaissance: report and continue
            show(fn.__name__, False, f"{type(exc).__name__}: {exc}")
