"""BTOS adapter: wide biweekly Excel into tidy adoption observations.

BTOS publishes one column per two-week reference period, with suppressed cells
marked ``S`` and not-collected cells marked ``.``.  Both are dropped rather than
zero-filled -- a suppressed estimate is missing information, not a zero.
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from documents.schemas import AdoptionObservation

LOG = logging.getLogger("documents.btos")

SHEET = "Response Estimates"
QUESTION_CURRENT_AI = "7"    # used AI in the last two weeks
QUESTION_FUTURE_AI = "24"    # expects to use AI in the next six months
SUPPRESSED = {"S", ".", "", "nan", "None"}

PERIOD_RE = re.compile(r"^(20\d{2})(\d{2})$")


def _parse_period(label: str) -> date | None:
    """BTOS period labels are YYYYWW; return the Monday of that ISO week."""
    match = PERIOD_RE.match(str(label).strip())
    if not match:
        return None
    year, week = int(match.group(1)), int(match.group(2))
    if not 1 <= week <= 53:
        return None
    try:
        return date.fromisocalendar(year, week, 1)
    except ValueError:
        return date(year, 1, 1) + timedelta(weeks=week - 1)


def _clean_percent(value) -> float | None:
    text = str(value).strip()
    if text in SUPPRESSED:
        return None
    text = text.rstrip("%")
    try:
        return float(text)
    except ValueError:
        return None


def load_ai_adoption(path: str | Path, source_doc_id: str,
                     question_id: str = QUESTION_CURRENT_AI,
                     sector_filter: str | None = None) -> list[AdoptionObservation]:
    """Melt one BTOS question into tidy observations.

    ``sector_filter`` takes a 2-digit NAICS sector code such as ``'52'``.
    """
    df = pd.read_excel(path, sheet_name=SHEET, header=0, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]

    id_cols = [c for c in ("Sector", "Question ID", "Question", "Answer ID", "Answer")
               if c in df.columns]
    period_cols = [c for c in df.columns if PERIOD_RE.match(str(c).strip())]
    if not period_cols:
        raise ValueError(f"No YYYYWW period columns found in {path}")

    wanted = df["Question ID"].astype(str).str.split(".").str[0] == str(question_id)
    df = df[wanted].copy()
    if df.empty:
        raise ValueError(f"Question ID {question_id} not present in {path}")

    if sector_filter and "Sector" in df.columns:
        df = df[df["Sector"].astype(str).str.strip() == sector_filter]

    long = df.melt(id_vars=id_cols, value_vars=period_cols,
                   var_name="period", value_name="raw_value")
    long["value"] = long["raw_value"].map(_clean_percent)
    long = long.dropna(subset=["value"])

    question_text = str(df["Question"].iloc[0])[:180] if "Question" in df.columns else ""

    observations: list[AdoptionObservation] = []
    for _, row in long.iterrows():
        answer = str(row.get("Answer", "")).strip()
        observations.append(AdoptionObservation(
            period=str(row["period"]),
            period_start=_parse_period(row["period"]),
            sector_code=str(row.get("Sector", "")).strip() or None,
            sector_label=str(row.get("Sector", "")).strip(),
            measure=f"BTOS Q{question_id} [{answer}]: {question_text}",
            value=float(row["value"]),
            unit="percent",
            source_doc_id=source_doc_id,
        ))

    LOG.info("source=btos status=ok question=%s sector=%s observations=%s",
             question_id, sector_filter, len(observations))
    return observations


def yes_series(observations: list[AdoptionObservation]) -> pd.DataFrame:
    """Reduce to the 'Yes' answer only, sorted by period: the adoption curve."""
    rows = [
        {"period": o.period, "period_start": o.period_start, "value": o.value,
         "sector": o.sector_code}
        for o in observations if "[Yes]" in o.measure
    ]
    df = pd.DataFrame(rows)
    return df.sort_values("period_start").reset_index(drop=True) if not df.empty else df
