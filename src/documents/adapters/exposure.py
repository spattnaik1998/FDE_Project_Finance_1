"""Felten/Raj/Seamans AIOE adapter: Excel appendix into exposure estimates."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from documents.schemas import ExposureEstimate

LOG = logging.getLogger("documents.exposure")

LM_SHEET = "LM AIOE"
LM_VALUE_COL = "Language Modeling AIOE"

SCALE_NOTE = (
    "Felten/Raj/Seamans AI Occupational Exposure, language-modelling variant. "
    "A standardised relative index, not a probability and not a percentage: "
    "higher means more exposed relative to other occupations. Values are only "
    "meaningful compared with other occupations in the same column."
)


def load_language_modeling_aioe(path: str | Path, source_doc_id: str,
                                soc_filter: str | None = None) -> list[ExposureEstimate]:
    """Load the language-modelling AIOE scores.

    ``soc_filter`` matches on the SOC code prefix when given, so a single
    occupation can be pulled without loading opinions about the other 773.
    """
    df = pd.read_excel(path, sheet_name=LM_SHEET)
    df.columns = [str(c).strip() for c in df.columns]

    if LM_VALUE_COL not in df.columns:
        raise ValueError(
            f"Expected column {LM_VALUE_COL!r} in {LM_SHEET!r}; got {list(df.columns)}")

    df = df.dropna(subset=["SOC Code", LM_VALUE_COL])
    if soc_filter:
        df = df[df["SOC Code"].astype(str).str.startswith(soc_filter)]

    estimates = [
        ExposureEstimate(
            soc_code=str(row["SOC Code"]).strip(),
            occupation=str(row.get("Occupation Title", "")).strip() or None,
            measure="AIOE_language_modeling",
            value=float(row[LM_VALUE_COL]),
            scale_note=SCALE_NOTE,
            source_doc_id=source_doc_id,
        )
        for _, row in df.iterrows()
    ]
    LOG.info("source=aioe status=ok estimates=%s filter=%s", len(estimates), soc_filter)
    return estimates


def percentile_of(estimates: list[ExposureEstimate], soc_code: str) -> float | None:
    """Where one occupation sits in the full distribution, as a percentile.

    The raw index is not interpretable on its own -- a rank is what a customer
    can actually act on.
    """
    values = sorted(e.value for e in estimates)
    hit = next((e for e in estimates if e.soc_code.startswith(soc_code)), None)
    if hit is None or not values:
        return None
    below = sum(1 for v in values if v < hit.value)
    return round(100.0 * below / len(values), 1)
