"""Analyse the fetched datasets and write a findings report.

Each section answers one question the Brynjolfsson-McAfee frame poses, and
prints the evidence rather than a conclusion, so the numbers can be checked
against the source CSVs.  Output goes to notes/data_exploration.md and tidy
intermediate tables go to data/interim/.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, "src")

import pandas as pd

from config import DATA_INTERIM, DATA_RAW, PROJECT_ROOT, ensure_dirs

pd.set_option("display.width", 200)

REPORT_PATH = PROJECT_ROOT / "notes" / "data_exploration.md"
SECURITIES_BEA = "523"   # BEA industry code: securities, commodity contracts, investments
FINANCE_NAICS = "52"     # Census sector code: finance and insurance

_report: list[str] = []


def emit(text: str = "") -> None:
    """Write a line to both stdout and the report buffer."""
    print(text)
    _report.append(text)


def table(df: pd.DataFrame, **kwargs) -> None:
    """Emit a DataFrame as a fenced block so the report stays readable."""
    emit("```")
    emit(df.to_string(index=False, **kwargs))
    emit("```")
    emit()


def load(name: str) -> pd.DataFrame:
    return pd.read_csv(DATA_RAW / f"{name}.csv")


# ---------------------------------------------------------------------------
# 1. Where does AI adoption actually stand, and what sits underneath it?
# ---------------------------------------------------------------------------

def section_adoption_gradient() -> pd.DataFrame:
    emit("## 1. The adoption gradient (ABS 2018)")
    emit()
    emit("Share of employer firms reporting *any* use of each technology, by sector. "
         "The frame's claim is that the payoff lags the machine because the "
         "complementary reorganisation lags; the gap between substrate "
         "(cloud, software) and capability (AI) is where that lag lives.")
    emit()

    df = load("census_abs_tech_use_sectors_2018")
    total_use = df[df["TECHUSE"].astype(str).str.endswith("99")].copy()
    total_use["technology"] = total_use["TECHUSE_LABEL"].str.split(":").str[0].str.strip()

    wide = total_use.pivot_table(index=["NAICS2017", "NAICS2017_LABEL"],
                                 columns="technology", values="FIRMPDEMP_PCT",
                                 aggfunc="first").reset_index()
    wide.columns.name = None
    cols = ["Artificial Intelligence", "Cloud-Based", "Specialized Software",
            "Robotics", "Specialized Equipment"]
    keep = [c for c in cols if c in wide.columns]
    wide = wide[["NAICS2017", "NAICS2017_LABEL"] + keep]
    wide["substrate_minus_ai"] = wide["Cloud-Based"] - wide["Artificial Intelligence"]
    wide = wide.sort_values("Artificial Intelligence", ascending=False)

    wide.to_csv(DATA_INTERIM / "adoption_gradient_2018.csv", index=False)
    table(wide.rename(columns={"NAICS2017_LABEL": "sector"}), max_colwidth=38)

    fin = wide[wide["NAICS2017"] == FINANCE_NAICS]
    if not fin.empty:
        r = fin.iloc[0]
        rank = int((wide["Artificial Intelligence"] > r["Artificial Intelligence"]).sum()) + 1
        emit(f"**Finance and insurance (NAICS 52):** AI {r['Artificial Intelligence']:.1f}% of firms, "
             f"cloud {r['Cloud-Based']:.1f}%, specialised software {r['Specialized Software']:.1f}%. "
             f"Rank {rank} of {len(wide)} sectors on AI use.")
        emit()
        emit(f"The substrate-to-capability gap is {r['substrate_minus_ai']:.1f} points: "
             "the cloud was in place, the capability was not. That is the "
             "electrification pattern stated in current data.")
        emit()
    return wide


# ---------------------------------------------------------------------------
# 2. Which AI, specifically? (ABS 2020 decomposition)
# ---------------------------------------------------------------------------

def section_ai_decomposition() -> pd.DataFrame:
    emit("## 2. Which AI? The 2020 decomposition")
    emit()
    emit("ABS 2020 splits AI into components. Natural language processing is the "
         "one that bears on analyst work, so pooling it into a single 'AI' number "
         "would hide the relevant signal.")
    emit()

    df = load("census_abs_tech_use_2020")
    in_use = df[df["BUSCHAR"].astype(str).str.endswith("01")].copy()
    in_use["technology"] = in_use["BUSCHAR_LABEL"].str.split(":").str[0].str.strip()

    fin = in_use[in_use["NAICS2017"].astype(str) == FINANCE_NAICS]
    allsec = in_use[in_use["NAICS2017"].astype(str) == "00"]

    merged = (fin[["technology", "FIRMPDEMP_PCT", "FIRMPDEMP"]]
              .rename(columns={"FIRMPDEMP_PCT": "finance_pct", "FIRMPDEMP": "finance_firms"})
              .merge(allsec[["technology", "FIRMPDEMP_PCT"]]
                     .rename(columns={"FIRMPDEMP_PCT": "all_sectors_pct"}),
                     on="technology", how="left")
              .sort_values("finance_pct", ascending=False))
    merged["finance_vs_all"] = merged["finance_pct"] - merged["all_sectors_pct"]

    merged.to_csv(DATA_INTERIM / "ai_decomposition_2020.csv", index=False)
    table(merged, max_colwidth=40)

    nlp = merged[merged["technology"].str.contains("language", case=False, na=False)]
    if not nlp.empty:
        emit(f"**Natural language processing in finance, 2020: "
             f"{nlp.iloc[0]['finance_pct']:.1f}% of firms in use.** "
             "This is the pre-LLM baseline for the capability now aimed at "
             "drafting, summarisation and extraction work.")
        emit()
    return merged


# ---------------------------------------------------------------------------
# 3. Substitution or augmentation? (firms' own reports)
# ---------------------------------------------------------------------------

def section_workforce_impact() -> pd.DataFrame:
    emit("## 3. Substitution or augmentation, as firms reported it")
    emit()
    emit("The single most load-bearing number for the exposure score. Acemoglu's "
         "point is that direction is chosen, not given; here firms say which "
         "direction they chose.")
    emit()
    emit("The survey asks three separate questions about the effect of AI use, "
         "encoded in the item number: headcount (D01-D03), skill level "
         "(D04-D06) and STEM skills (D07-D09). They must not be pooled -- "
         "doing so mixes 'more workers' with 'more skilled workers', which are "
         "opposite answers to the exposure question.")
    emit()

    df = load("census_abs_workforce_impact_2018")
    df = df[df["IMPACTWF_U_LABEL"].notna()].copy()
    df["item"] = df["IMPACTWF_U"].astype(str).str[-3:]
    ai = df[df["IMPACTWF_U"].astype(str).str.startswith("T1E05D")].copy()

    headcount = {"D01": "headcount_increased", "D02": "headcount_decreased",
                 "D03": "headcount_unchanged"}
    skill = {"D04": "skill_increased", "D05": "skill_decreased",
             "D06": "skill_unchanged"}
    mapping = {**headcount, **skill}

    ai["measure"] = ai["item"].map(mapping)
    ai = ai[ai["measure"].notna()]

    pivot = ai.pivot_table(index=["NAICS2017", "NAICS2017_LABEL"], columns="measure",
                           values="FIRMPDEMP_PCT", aggfunc="first").reset_index()
    pivot.columns.name = None
    pivot["net_headcount"] = pivot["headcount_increased"] - pivot["headcount_decreased"]
    pivot = pivot.sort_values("net_headcount", ascending=False)

    cols = ["NAICS2017", "NAICS2017_LABEL", "headcount_increased",
            "headcount_decreased", "headcount_unchanged", "net_headcount",
            "skill_increased", "skill_decreased"]
    pivot = pivot[[c for c in cols if c in pivot.columns]]
    pivot.to_csv(DATA_INTERIM / "ai_workforce_impact_2018.csv", index=False)
    table(pivot.rename(columns={"NAICS2017_LABEL": "sector"}), max_colwidth=32)

    def row_for(code: str):
        hit = pivot[pivot["NAICS2017"].astype(str).str.zfill(2) == code]
        return hit.iloc[0] if not hit.empty else None

    allsec, fin = row_for("00"), row_for("52")
    if allsec is not None:
        emit(f"**All sectors:** {allsec['headcount_increased']:.1f}% of AI-using firms "
             f"reported *increasing* headcount against "
             f"{allsec['headcount_decreased']:.1f}% reporting a *decrease*; "
             f"{allsec['headcount_unchanged']:.1f}% reported no change.")
        emit()
    if fin is not None:
        emit(f"**Finance and insurance:** {fin['headcount_increased']:.1f}% increased "
             f"against {fin['headcount_decreased']:.1f}% decreased "
             f"(net {fin['net_headcount']:+.1f}), while "
             f"{fin['skill_increased']:.1f}% reported the *skill level* of their "
             f"workers rising and only {fin['skill_decreased']:.1f}% reported it falling.")
        emit()
        emit("That pairing is the finding worth carrying into the score. The "
             "dominant reported effect of AI use was not fewer workers but "
             "more skilled ones -- Snijders' aided expert, in survey form.")
        emit()

    emit("Caveats that must travel with these numbers: they cover firms that "
         "had already adopted, they count firms rather than jobs, they predate "
         "LLMs entirely, and 'AI' in 2018 meant the technologies in section 2, "
         "not generative models. They bound the prior; they do not settle it.")
    emit()
    return pivot


# ---------------------------------------------------------------------------
# 4. Does firm scale gate adoption?
# ---------------------------------------------------------------------------

def section_adoption_by_size() -> pd.DataFrame:
    emit("## 4. Does scale gate adoption? (2018)")
    emit()
    df = load("census_abs_tech_by_firm_size_2018")
    ai = df[df["TECHUSE"].astype(str) == "T1E03B99"].copy()
    out = ai[["NAICS2017", "NSFSZFI_LABEL", "FIRMPDEMP", "FIRMPDEMP_PCT"]].rename(
        columns={"NAICS2017": "naics", "NSFSZFI_LABEL": "firm_size",
                 "FIRMPDEMP": "firms_using_ai", "FIRMPDEMP_PCT": "pct_of_size_class"})
    out.to_csv(DATA_INTERIM / "ai_adoption_by_firm_size_2018.csv", index=False)
    table(out, max_colwidth=45)

    allsec = out[out["naics"].astype(str).str.zfill(2) == "00"]
    small = allsec[allsec["firm_size"].str.contains("1 to 9", na=False)]
    large = allsec[allsec["firm_size"].str.contains("10 employees or more", na=False)]
    if not small.empty and not large.empty:
        emit(f"Across all sectors the gradient is shallow: "
             f"{small.iloc[0]['pct_of_size_class']:.1f}% of firms with 1-9 employees "
             f"used AI against {large.iloc[0]['pct_of_size_class']:.1f}% of firms with "
             "10 or more. Scale mattered, but far less than the "
             "platform-advantage story would predict -- consistent with the "
             "notes' claim that machine learning arrived as a purchasable input "
             "through APIs and the cloud rather than as a capability only large "
             "firms could build.")
        emit()
    emit("**Limitation:** Census publishes no size breakdown for finance "
         "(NAICS 52) in this module -- only an all-firms figure. Any "
         "size-conditioned claim about finance is therefore unsupported by "
         "this source and must not be asserted.")
    emit()
    return out


# ---------------------------------------------------------------------------
# 5. Labour share in securities (BEA 523)
# ---------------------------------------------------------------------------

def section_labour_share() -> pd.DataFrame:
    emit("## 5. Labour share in securities (BEA industry 523)")
    emit()
    emit("Compensation of employees as a percent of value added. This is the "
         "cost line the exposure score is ultimately about, and the "
         "created-versus-captured question in one series.")
    emit()

    df = load("bea_value_added_shares")
    comp = df[df["IndustrYDescription"].str.strip() == "Compensation of employees"].copy()
    comp["Industry"] = comp["Industry"].astype(str)

    focus = comp[comp["Industry"].isin([SECURITIES_BEA, "52", "521CI", "524", "5415"])]
    wide = focus.pivot_table(index="Year", columns="Industry", values="DataValue",
                             aggfunc="first").reset_index()
    wide.columns.name = None
    wide.to_csv(DATA_INTERIM / "labour_share_by_industry.csv", index=False)

    show = wide[wide["Year"] % 3 == 0] if "Year" in wide else wide
    table(show)

    if SECURITIES_BEA in wide.columns:
        s = wide[["Year", SECURITIES_BEA]].dropna()
        first, last = s.iloc[0], s.iloc[-1]
        emit(f"**Securities (523):** compensation share of value added moved from "
             f"{first[SECURITIES_BEA]:.1f}% in {int(first['Year'])} to "
             f"{last[SECURITIES_BEA]:.1f}% in {int(last['Year'])} "
             f"({last[SECURITIES_BEA] - first[SECURITIES_BEA]:+.1f} points).")
        emit()
        emit("Note the level: compensation exceeds 90% of value added in "
             "securities, and tops 100% in some years. That is not an error -- "
             "value added is net of intermediate inputs and absorbs trading "
             "losses, so the ratio can exceed one when industry profits "
             "collapse (2007-08 is visible). It does mean this series is a "
             "poor single-year gauge and should be read as a trend.")
        emit()
    return wide


# ---------------------------------------------------------------------------
# 6. Churn: does concentration end in displacement?
# ---------------------------------------------------------------------------

def section_churn() -> pd.DataFrame:
    emit("## 6. Churn in finance, 1978 onward (BDS)")
    emit()
    emit("Livermore found 40% of the 1888-1905 industrial trusts dead by the "
         "early 1930s; Caves found the survivors' average share fell from 69% "
         "to 45%. Concentration under a general purpose technology may be a "
         "transitional phase. Entry and exit rates are how we would see that.")
    emit()

    df = load("census_bds_churn_finance").sort_values("YEAR")
    cols = ["YEAR", "FIRM", "ESTAB", "EMP", "ESTABS_ENTRY_RATE", "ESTABS_EXIT_RATE",
            "JOB_CREATION_RATE", "JOB_DESTRUCTION_RATE", "REALLOCATION_RATE"]
    out = df[[c for c in cols if c in df.columns]]
    out.to_csv(DATA_INTERIM / "finance_churn.csv", index=False)

    decade = out.assign(decade=(out["YEAR"] // 10) * 10).groupby("decade").agg(
        entry_rate=("ESTABS_ENTRY_RATE", "mean"),
        exit_rate=("ESTABS_EXIT_RATE", "mean"),
        reallocation=("REALLOCATION_RATE", "mean"),
        firms=("FIRM", "mean"),
    ).round(2).reset_index()
    table(decade)

    emit(f"Coverage: {int(out['YEAR'].min())}-{int(out['YEAR'].max())}, "
         f"{len(out)} annual observations for NAICS 52.")
    emit()
    return decade


# ---------------------------------------------------------------------------
# 7. Concentration in securities establishments
# ---------------------------------------------------------------------------

def section_concentration() -> pd.DataFrame:
    emit("## 7. Establishment size distribution, finance subsectors (CBP 2022)")
    emit()
    df = load("census_cbp_finance_2022")
    tot = df[df["EMPSZES"] == 1][["NAICS2017", "NAICS2017_LABEL", "ESTAB", "EMP", "PAYANN"]].copy()
    tot["avg_emp_per_estab"] = (tot["EMP"] / tot["ESTAB"]).round(1)
    tot["avg_pay_per_emp_usd"] = (tot["PAYANN"] * 1000 / tot["EMP"]).round(0)
    tot = tot.sort_values("EMP", ascending=False)
    tot.to_csv(DATA_INTERIM / "finance_establishment_profile.csv", index=False)
    table(tot, max_colwidth=45)

    sec = tot[tot["NAICS2017"].astype(str) == SECURITIES_BEA]
    if not sec.empty:
        r = sec.iloc[0]
        emit(f"**Securities (523):** {int(r['ESTAB']):,} establishments, "
             f"{int(r['EMP']):,} employees, average annual pay "
             f"${r['avg_pay_per_emp_usd']:,.0f}. That pay level is why a task-level "
             "exposure score in this occupation carries real money.")
        emit()
    return tot


# ---------------------------------------------------------------------------
# 8. Productivity and employment
# ---------------------------------------------------------------------------

def section_productivity() -> pd.DataFrame:
    emit("## 8. Productivity, labour share and finance employment (FRED)")
    emit()
    obs = load("fred_observations")
    obs["date"] = pd.to_datetime(obs["date"])
    meta = load("fred_metadata")

    emit("Series retrieved:")
    table(meta[["id", "title", "units", "frequency"]], max_colwidth=60)

    recent = obs[obs["date"] >= "2015-01-01"]
    summary = recent.groupby("series_id").agg(
        first_date=("date", "min"), last_date=("date", "max"),
        first_value=("value", "first"), last_value=("value", "last"),
        n_obs=("value", "size"),
    ).reset_index()
    summary["pct_change"] = ((summary["last_value"] / summary["first_value"] - 1) * 100).round(1)
    summary.to_csv(DATA_INTERIM / "fred_summary_since_2015.csv", index=False)
    table(summary)

    emit("Since 2015. Solow's remark was that you could see the computer age "
         "everywhere but in the productivity statistics; the question this "
         "project asks is whether the same is currently true of agents, and "
         "these are the series where it would show up first.")
    emit()
    return summary


# ---------------------------------------------------------------------------

def main() -> None:
    ensure_dirs()
    Path(REPORT_PATH.parent).mkdir(parents=True, exist_ok=True)

    emit("# Data exploration: what the four APIs actually give us")
    emit()
    manifest = pd.read_csv(DATA_RAW / "_manifest.csv")
    emit(f"{int((manifest['status'] == 'ok').sum())} datasets fetched from "
         "BEA, Census, FRED and BLS. Every number below is reproducible from "
         "`data/raw/` via `scripts/fetch_all.py`.")
    emit()

    sections = [
        section_adoption_gradient,
        section_ai_decomposition,
        section_workforce_impact,
        section_adoption_by_size,
        section_labour_share,
        section_churn,
        section_concentration,
        section_productivity,
    ]
    for fn in sections:
        try:
            fn()
        except Exception as exc:
            emit(f"> **Section `{fn.__name__}` failed:** `{type(exc).__name__}: {exc}`")
            emit()

    REPORT_PATH.write_text("\n".join(_report), encoding="utf-8")
    print(f"\nReport written to {REPORT_PATH}")


if __name__ == "__main__":
    main()
