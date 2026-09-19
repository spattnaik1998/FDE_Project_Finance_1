"""Fetch every dataset in the project's inventory into data/raw/*.csv.

Each task is declared with the analytical purpose it serves, so the manifest
records *why* a dataset is here and not only that it downloaded.  A task that
fails is recorded with its error and the run continues -- this is the
reconnaissance stage, and one dead endpoint should not cost the whole pull.
"""

from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass
from typing import Callable

sys.path.insert(0, "src")
sys.path.insert(0, "src/sources")

import pandas as pd

import bea
import bls
import census
import fred
from config import DATA_RAW, ensure_dirs, load_keys

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
                    datefmt="%H:%M:%S")
LOG = logging.getLogger("fetch_all")

KEYS = load_keys()
FINANCE_SUBSECTORS = ["521", "522", "523", "524", "525"]


@dataclass
class Task:
    """One dataset pull: a filename, the purpose it serves, and how to get it."""

    name: str
    purpose: str
    fn: Callable[[], pd.DataFrame]


# ---------------------------------------------------------------------------
# Census: technology adoption, firm churn, firm-size distribution
# ---------------------------------------------------------------------------

def abs_tech_use_all_sectors() -> pd.DataFrame:
    """2018 technology-use rates for every 2-digit NAICS sector."""
    return census.fetch(
        "2018/abstcb",
        ["NAME", "NAICS2017", "NAICS2017_LABEL", "TECHUSE", "TECHUSE_LABEL",
         "FIRMPDEMP", "FIRMPDEMP_PCT", "EMP", "EMP_PCT", "PAYANN", "PAYANN_PCT"],
        KEYS["CENSUS_API_KEY"], geo="us:*", INDLEVEL="2")


def abs_tech_use_2020() -> pd.DataFrame:
    """2020 technology use, all sectors.

    ABS 2020 splits "AI" into its components -- machine learning, natural
    language processing, machine vision, voice recognition -- which the 2018
    module reports only as a single "Artificial Intelligence" item.  NLP is the
    capability most relevant to analyst work, so the decomposition matters.

    Note both ABS technology modules publish at 2-digit NAICS only: there is no
    securities (523) breakout, and finance means NAICS 52 with banking and
    insurance pooled in.
    """
    return census.fetch(
        "2020/absmcb",
        ["NAME", "NAICS2017", "NAICS2017_LABEL", "QDESC", "BUSCHAR",
         "BUSCHAR_LABEL", "FIRMPDEMP", "FIRMPDEMP_PCT", "EMP", "EMP_PCT", "PAYANN"],
        KEYS["CENSUS_API_KEY"], geo="us:*", QDESC="B42")


def abs_cloud_use_2020() -> pd.DataFrame:
    """2020 cloud-service use: the complementary infrastructure AI rides on."""
    return census.fetch(
        "2020/absmcb",
        ["NAME", "NAICS2017", "NAICS2017_LABEL", "QDESC", "BUSCHAR",
         "BUSCHAR_LABEL", "FIRMPDEMP", "FIRMPDEMP_PCT"],
        KEYS["CENSUS_API_KEY"], geo="us:*", QDESC="B41")


def abs_tech_workforce_impact() -> pd.DataFrame:
    """Firm-reported workforce impact of technology USE: substitution vs augmentation."""
    return census.fetch(
        "2018/abstcb",
        ["NAME", "NAICS2017", "NAICS2017_LABEL", "IMPACTWF_U", "IMPACTWF_U_LABEL",
         "FIRMPDEMP", "FIRMPDEMP_PCT", "EMP", "EMP_PCT"],
        KEYS["CENSUS_API_KEY"], geo="us:*", INDLEVEL="2")


def abs_tech_worker_type_impact() -> pd.DataFrame:
    """Which *types* of worker the firms said technology use affected."""
    return census.fetch(
        "2018/abstcb",
        ["NAME", "NAICS2017", "NAICS2017_LABEL", "IMPACTWK_U", "IMPACTWK_U_LABEL",
         "FIRMPDEMP", "FIRMPDEMP_PCT"],
        KEYS["CENSUS_API_KEY"], geo="us:*", INDLEVEL="2")


def abs_tech_by_firm_size() -> pd.DataFrame:
    """Adoption by employment size class: does scale gate AI adoption?

    Pulled for all sectors (NAICS 00) and for finance (52); Census suppresses
    the size detail for some sector/technology cells, so both are kept and the
    analysis states which one it is reading.
    """
    frames = []
    for naics in ("00", "52"):
        frames.append(census.fetch(
            "2018/abstcb",
            ["NAME", "NAICS2017", "NAICS2017_LABEL", "NSFSZFI", "NSFSZFI_LABEL",
             "TECHUSE", "TECHUSE_LABEL", "FIRMPDEMP", "FIRMPDEMP_PCT"],
            KEYS["CENSUS_API_KEY"], geo="us:*", NAICS2017=naics))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def bds_churn_finance() -> pd.DataFrame:
    """Firm entry, exit and job reallocation: the Livermore/Caves churn test."""
    return census.fetch(
        "timeseries/bds",
        ["YEAR", "NAICS", "FIRM", "ESTAB", "EMP", "ESTABS_ENTRY_RATE",
         "ESTABS_EXIT_RATE", "JOB_CREATION_RATE", "JOB_DESTRUCTION_RATE",
         "NET_JOB_CREATION_RATE", "REALLOCATION_RATE", "FIRMDEATH_FIRMS",
         "FIRMDEATH_EMP"],
        KEYS["CENSUS_API_KEY"], geo="us:*", NAICS="52")


def bds_firm_size_finance() -> pd.DataFrame:
    """Firms by employment size class: raw material for a tail-index estimate."""
    return census.fetch(
        "timeseries/bds",
        ["YEAR", "NAICS", "EMPSZFI", "EMPSZFI_LABEL", "FIRM", "ESTAB", "EMP"],
        KEYS["CENSUS_API_KEY"], geo="us:*", NAICS="52")


def cbp_finance_2022() -> pd.DataFrame:
    """County Business Patterns: establishments and payroll for finance subsectors."""
    frames = []
    for naics in FINANCE_SUBSECTORS:
        frames.append(census.fetch(
            "2022/cbp",
            ["NAME", "NAICS2017", "NAICS2017_LABEL", "EMPSZES", "EMPSZES_LABEL",
             "ESTAB", "EMP", "PAYANN"],
            KEYS["CENSUS_API_KEY"], geo="us:*", NAICS2017=naics))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ---------------------------------------------------------------------------
# BEA: value added, labour share, intangible investment
# ---------------------------------------------------------------------------

def bea_dataset_catalog() -> pd.DataFrame:
    """BEA's own dataset list, kept so the inventory is reproducible."""
    return bea.list_datasets(KEYS["BEA_API_KEY"])


def bea_value_added_components() -> pd.DataFrame:
    """Compensation vs gross operating surplus by industry: labour share."""
    return bea.gdp_by_industry(KEYS["BEA_API_KEY"], table_id=6)


def bea_value_added_shares() -> pd.DataFrame:
    """Same components as a percentage of value added: comparable across industries."""
    return bea.gdp_by_industry(KEYS["BEA_API_KEY"], table_id=7)


def bea_value_added() -> pd.DataFrame:
    """Value added by industry, annual."""
    return bea.gdp_by_industry(KEYS["BEA_API_KEY"], table_id=1)


def bea_gross_output() -> pd.DataFrame:
    """Gross output by industry: the denominator for productivity work."""
    return bea.gdp_by_industry(KEYS["BEA_API_KEY"], table_id=15)


def bea_ip_investment() -> pd.DataFrame:
    """Investment in intellectual property products: the intangibles argument."""
    return bea.nipa_table(KEYS["BEA_API_KEY"], "T50302", frequency="A")


# ---------------------------------------------------------------------------
# FRED: productivity, labour share, finance employment
# ---------------------------------------------------------------------------

FRED_SERIES = [
    "OPHNFB",           # nonfarm business: real output per hour
    "PRS85006173",      # nonfarm business: labor share
    "USFIRE",           # all employees: financial activities
    "CES5552300001",    # all employees: securities, commodity contracts, investments
    "CES5552300008",    # average hourly earnings: same industry
    "MPU9900063",       # manufacturing sector labour productivity (see fred_metadata)
    "Y033RC1Q027SBEA",  # nonresidential fixed investment (see fred_metadata)
    "B985RC1Q027SBEA",  # nonresidential intellectual property products investment
    "GDPC1",            # real GDP, context
    "PAYEMS",           # total nonfarm payrolls, context
    "LNS14000000",      # unemployment rate, context
    "COMPRNFB",         # real hourly compensation, nonfarm business
]

FRED_SEARCHES = [
    "labor share nonfarm business",
    "information processing software investment",
    "securities commodity contracts employment",
    "multifactor productivity finance insurance",
    "intellectual property products investment",
]

_VALID_FRED: list[str] | None = None


def _valid_fred_ids() -> list[str]:
    """Keep only series FRED actually serves, so one bad id cannot kill the pull."""
    global _VALID_FRED
    if _VALID_FRED is not None:
        return _VALID_FRED

    good: list[str] = []
    for sid in FRED_SERIES:
        try:
            if not fred.fetch_metadata([sid], KEYS["FRED_API_KEY"]).empty:
                good.append(sid)
        except Exception as exc:
            LOG.warning("source=fred status=series_unavailable series=%s error=%s",
                        sid, str(exc)[:120])
    _VALID_FRED = good
    return good


def fred_metadata() -> pd.DataFrame:
    return fred.fetch_metadata(_valid_fred_ids(), KEYS["FRED_API_KEY"])


def fred_observations() -> pd.DataFrame:
    return fred.fetch_observations(_valid_fred_ids(), KEYS["FRED_API_KEY"],
                                   start="1947-01-01")


def fred_search_catalog() -> pd.DataFrame:
    """Discovery results, kept so series selection is auditable rather than guessed."""
    frames = []
    for term in FRED_SEARCHES:
        df = fred.search_series(term, KEYS["FRED_API_KEY"], limit=15)
        if not df.empty:
            df.insert(0, "search_term", term)
            frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ---------------------------------------------------------------------------
# BLS: industry employment and earnings
# ---------------------------------------------------------------------------

BLS_SERIES = [
    "CES5552300001",  # securities/commodity/investments: all employees
    "CES5552300006",  # ... average weekly hours
    "CES5552300008",  # ... average hourly earnings
    "CES5500000001",  # financial activities: all employees
    "CES0000000001",  # total nonfarm: all employees
    "LNS14000000",    # unemployment rate
    "PRS85006092",    # nonfarm business: output per hour index
    "PRS85006112",    # nonfarm business: unit labour costs
]


def bls_industry_series() -> pd.DataFrame:
    return bls.fetch_series(BLS_SERIES, start_year=2005, end_year=2025,
                            api_key=KEYS["BLS_API_KEY"])


TASKS: list[Task] = [
    Task("census_abs_tech_use_sectors_2018",
         "AI/cloud/robotics adoption by sector, 2018 baseline", abs_tech_use_all_sectors),
    Task("census_abs_tech_use_2020",
         "2020 tech use with AI split into ML / NLP / vision / voice", abs_tech_use_2020),
    Task("census_abs_cloud_use_2020",
         "2020 cloud-service use - the complementary infrastructure", abs_cloud_use_2020),
    Task("census_abs_workforce_impact_2018",
         "Firm-reported workforce impact: substitution vs augmentation", abs_tech_workforce_impact),
    Task("census_abs_worker_type_impact_2018",
         "Which worker types technology use affected", abs_tech_worker_type_impact),
    Task("census_abs_tech_by_firm_size_2018",
         "Does firm scale gate AI adoption in finance?", abs_tech_by_firm_size),
    Task("census_bds_churn_finance",
         "Firm entry/exit and job reallocation - churn under a GPT", bds_churn_finance),
    Task("census_bds_firm_size_finance",
         "Firms by employment size class - tail-index raw material", bds_firm_size_finance),
    Task("census_cbp_finance_2022",
         "Establishments, employment, payroll by size class", cbp_finance_2022),
    Task("bea_dataset_catalog",
         "BEA dataset catalog for reproducibility", bea_dataset_catalog),
    Task("bea_value_added_components",
         "Compensation vs operating surplus by industry", bea_value_added_components),
    Task("bea_value_added_shares",
         "Same components as % of value added", bea_value_added_shares),
    Task("bea_value_added",
         "Value added by industry, annual", bea_value_added),
    Task("bea_gross_output",
         "Gross output by industry", bea_gross_output),
    Task("bea_ip_investment",
         "Investment in intellectual property products - intangibles", bea_ip_investment),
    Task("fred_search_catalog",
         "Auditable series discovery", fred_search_catalog),
    Task("fred_metadata",
         "Titles/units/frequency for selected FRED series", fred_metadata),
    Task("fred_observations",
         "Productivity, labour share, finance employment history", fred_observations),
    Task("bls_industry_series",
         "Securities-industry employment, hours and earnings", bls_industry_series),
]


def main() -> None:
    ensure_dirs()
    manifest_rows = []

    for task in TASKS:
        started = time.perf_counter()
        path = DATA_RAW / f"{task.name}.csv"
        try:
            df = task.fn()
            duration_ms = int((time.perf_counter() - started) * 1000)

            if df is None or df.empty:
                LOG.warning("task=%s status=empty duration_ms=%s", task.name, duration_ms)
                manifest_rows.append({"dataset": task.name, "purpose": task.purpose,
                                      "status": "empty", "rows": 0, "cols": 0,
                                      "duration_ms": duration_ms, "file": "", "error": ""})
                continue

            df.to_csv(path, index=False)
            LOG.info("task=%s status=ok rows=%s cols=%s duration_ms=%s",
                     task.name, len(df), df.shape[1], duration_ms)
            manifest_rows.append({
                "dataset": task.name, "purpose": task.purpose, "status": "ok",
                "rows": len(df), "cols": df.shape[1], "duration_ms": duration_ms,
                "file": path.name, "error": "",
            })

        except Exception as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            LOG.error("task=%s status=failed duration_ms=%s error=%s",
                      task.name, duration_ms, str(exc)[:200])
            manifest_rows.append({"dataset": task.name, "purpose": task.purpose,
                                  "status": "failed", "rows": 0, "cols": 0,
                                  "duration_ms": duration_ms, "file": "",
                                  "error": str(exc)[:400]})

    manifest = pd.DataFrame(manifest_rows)
    manifest.to_csv(DATA_RAW / "_manifest.csv", index=False)

    ok = int((manifest["status"] == "ok").sum())
    print(f"\n{'=' * 78}\nFETCH COMPLETE: {ok}/{len(manifest)} datasets\n{'=' * 78}")
    print(manifest[["dataset", "status", "rows", "cols", "duration_ms"]].to_string(index=False))

    failed = manifest[manifest["status"] != "ok"]
    if not failed.empty:
        print(f"\nNeeding attention ({len(failed)}):")
        for _, row in failed.iterrows():
            print(f"  {row['dataset']:38s} {row['status']:7s} {row['error'][:110]}")


if __name__ == "__main__":
    main()
