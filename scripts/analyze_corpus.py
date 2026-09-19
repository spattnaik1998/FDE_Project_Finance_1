"""Join the document corpus with the API data and report what it adds.

The point of this script is to show that the three formats now answer one
question together: what does this occupation do, how exposed is it, and how
fast is the capability actually arriving.
"""

from __future__ import annotations

import json
import sys

sys.path.insert(0, "src")

import pandas as pd

from config import DATA_INTERIM, PROJECT_ROOT
from documents.adapters import exposure as exposure_adapter
from documents.schemas import Corpus

REPORT_PATH = PROJECT_ROOT / "notes" / "corpus_exploration.md"
TARGET_SOC = "13-2051"

_report: list[str] = []


def emit(text: str = "") -> None:
    print(text)
    _report.append(text)


def table(df: pd.DataFrame, **kwargs) -> None:
    emit("```")
    emit(df.to_string(index=False, **kwargs))
    emit("```")
    emit()


def main() -> None:
    corpus = Corpus.model_validate_json(
        (DATA_INTERIM / "corpus.json").read_text(encoding="utf-8"))

    emit("# Corpus exploration: what the unstructured sources add")
    emit()
    summary = corpus.summary()
    emit(", ".join(f"**{k}**: {v}" for k, v in summary.items()))
    emit()

    # -- 1. Tasks ---------------------------------------------------------
    emit("## 1. The task list (O*NET, tab-separated bulk file)")
    emit()
    tasks = pd.DataFrame([t.model_dump() for t in corpus.tasks])
    emit(f"{len(tasks)} tasks for SOC {TARGET_SOC} "
         f"({tasks['occupation'].dropna().iloc[0] if not tasks.empty else '?'}). "
         "This is the unit the exposure score operates on -- before this, the "
         "prototype had no input at all.")
    emit()
    top = tasks.sort_values("importance", ascending=False).head(10)
    table(top[["task_id", "task_type", "importance", "relevance_pct", "statement"]],
          max_colwidth=88)
    rated = int(tasks["importance"].notna().sum())
    emit(f"**Ratings coverage: {rated}/{len(tasks)} tasks.**")
    emit()
    if rated == 0:
        emit("O*NET publishes **no incumbent ratings for 13-2051**. Its task "
             "list comes from analyst review rather than a worker survey, so "
             "there is no importance score and no Core/Supplemental split. "
             "Most neighbouring finance occupations *do* have ratings "
             "(Financial Quantitative Analysts 13-2099.01, Credit Analysts "
             "13-2041, Financial Managers 11-3031), so this is specific to the "
             "occupation we picked, not to the source.")
        emit()
        emit("This is a real constraint on the rubric, and it has to be "
             "decided rather than absorbed: either weight all 26 tasks "
             "equally, borrow ratings from an adjacent occupation and say so, "
             "or move the target role. Quietly treating unweighted tasks as "
             "equally important would be a modelling choice disguised as a "
             "data property.")
        emit()

    # -- 2. Exposure benchmark -------------------------------------------
    emit("## 2. The exposure benchmark (Excel appendix)")
    emit()
    est = corpus.exposure_estimates
    ours = next((e for e in est if e.soc_code.startswith(TARGET_SOC)), None)
    if ours:
        pct = exposure_adapter.percentile_of(est, TARGET_SOC)
        emit(f"**{ours.occupation} ({ours.soc_code})**: "
             f"{ours.measure} = {ours.value:.3f}, which is the "
             f"**{pct:.0f}th percentile** of {len(est)} occupations.")
        emit()
        emit(f"> {ours.scale_note}")
        emit()

        frame = pd.DataFrame([e.model_dump() for e in est])
        frame = frame.sort_values("value", ascending=False)
        emit("Ten most exposed occupations, for context on what the index rewards:")
        table(frame.head(10)[["soc_code", "occupation", "value"]], max_colwidth=52)
        emit("Least exposed:")
        table(frame.tail(5)[["soc_code", "occupation", "value"]], max_colwidth=52)
        emit(f"This is the number our own rubric has to be checked against. If "
             f"we score financial analysts far from the {pct:.0f}th percentile, "
             "we need a reason better than 'our method differs'.")
        emit()

    # -- 3. Adoption curve ------------------------------------------------
    emit("## 3. The adoption curve (BTOS, wide Excel, biweekly)")
    emit()
    obs = pd.DataFrame([o.model_dump() for o in corpus.adoption_observations])
    yes = obs[obs["measure"].str.contains(r"\[Yes\]", regex=True)].copy()
    yes["period_start"] = pd.to_datetime(yes["period_start"])
    yes["question"] = yes["measure"].str.extract(r"BTOS Q(\d+)")

    for qid, label in [("7", "currently using AI"),
                       ("24", "expect to use AI within six months")]:
        sub = yes[yes["question"] == qid].sort_values("period_start")
        if sub.empty:
            continue
        emit(f"**Finance and insurance, firms {label} (BTOS Q{qid}):**")
        emit()
        show = sub[["period", "period_start", "value"]].copy()
        show["period_start"] = show["period_start"].dt.date
        table(pd.concat([show.head(4), show.tail(6)]))
        first, last = sub.iloc[0], sub.iloc[-1]
        emit(f"{first['value']:.1f}% at {first['period_start'].date()} -> "
             f"{last['value']:.1f}% at {last['period_start'].date()} "
             f"({last['value'] - first['value']:+.1f} points across "
             f"{len(sub)} biweekly observations).")
        emit()

    emit("Set against the ABS numbers from the API layer -- 4.5% of finance "
         "firms using any AI in 2018, and 1.1% using NLP in 2020 -- this is the "
         "diffusion curve the whole lag argument was missing. The API data "
         "gives the pre-LLM baseline; this gives what happened next.")
    emit()

    # -- 4. Claims --------------------------------------------------------
    emit("## 4. Claims with provenance (PDF)")
    emit()
    claims = pd.DataFrame([c.model_dump() for c in corpus.claims])
    emit(f"{len(claims)} verbatim quotes across "
         f"{claims['source_doc_id'].nunique()} papers, each carrying its page "
         "number. Nothing here is paraphrased.")
    emit()
    for topic in ["exposure_share", "not_prediction", "j_curve_definition"]:
        hit = claims[claims["topic"] == topic]
        if hit.empty:
            continue
        row = hit.iloc[0]
        emit(f"**{topic}** — {row['source_doc_id']}, p.{row['page']}:")
        emit(f"> {row['quote']}")
        emit()

    emit("The second of those is the one that matters most for us. Eloundou et "
         "al. explicitly decline to forecast adoption timing -- so their "
         "exposure number cannot be used as a timetable, which is exactly the "
         "distinction our score is built around.")
    emit()

    # -- 5. Provenance ----------------------------------------------------
    emit("## 5. Provenance ledger")
    emit()
    docs = pd.DataFrame(corpus.documents if isinstance(corpus.documents[0], dict)
                        else [d.model_dump() for d in corpus.documents])
    ledger = docs[["doc_id", "format", "bytes", "sha256"]].copy()
    ledger["sha256"] = ledger["sha256"].str[:12]
    ledger["format"] = ledger["format"].astype(str).str.replace("DocumentFormat.", "")
    table(ledger, max_colwidth=40)

    flagged = [d for d in (corpus.documents if isinstance(corpus.documents[0], dict)
                           else [d.model_dump() for d in corpus.documents])
               if "MIRROR" in (d.get("provenance_note") or "")]
    if flagged:
        emit(f"**{len(flagged)} source(s) carry a mirror warning** and must be "
             "spot-checked against the publisher's own copy before any "
             "customer-facing use:")
        for d in flagged:
            emit(f"- `{d['doc_id']}` — {d['provenance_note']}")
        emit()

    REPORT_PATH.write_text("\n".join(_report), encoding="utf-8")
    print(f"\nReport written to {REPORT_PATH}")


if __name__ == "__main__":
    main()
