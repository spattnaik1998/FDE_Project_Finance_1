"""The presentation tier. A dispatcher, and nothing else.

Run it with::

    streamlit run src/app/streamlit_app.py --server.address 127.0.0.1 \
        --server.port 8501

or simply ``python scripts/run_ui.py``, which sets the loopback flags for you.

This module deliberately contains **no** database access, no SQL, no scoring
and no model calls. It asks :mod:`app.gateway` for a
:class:`~app.view_model.ReportView`, asks :mod:`app.blocks` what to draw, and
turns each block into a Streamlit call. ``tests/test_app.py`` parses this file
and fails if a database library is imported or a SQL keyword appears, which is
what makes the tier boundary a fact rather than an intention.

The consequence worth stating: opening this page cannot change a number. There
is no code path here that recomputes an index, refits a lag or calls a model,
so a figure a customer saw yesterday is the figure they see today.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Streamlit executes this file as a script, so the package root has to be on
# the path before the app imports resolve.
_SRC = Path(__file__).resolve().parents[1]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import streamlit as st

from app import blocks as blocks_module
from app.gateway import NoRunAvailable, available_runs, load_view
from app.view_model import ReportView

PAGE_TITLE = "Task Exposure & Adoption Lag"
TONE_RENDERER = {"ok": "success", "warn": "warning", "stop": "error"}


def render_block(block: blocks_module.Block) -> None:
    """Turn one block into a Streamlit call.

    Raises on an unknown kind rather than skipping it. A silently dropped block
    is a figure the customer never saw, which is the failure mode this whole
    project is built to avoid.
    """
    kind, payload, meta = block.kind, block.payload, block.meta

    if kind == "title":
        st.title(payload)
    elif kind == "caption":
        st.caption(payload)
    elif kind == "heading":
        st.subheader(payload)
    elif kind == "markdown":
        st.markdown(payload)
    elif kind == "divider":
        st.divider()
    elif kind == "callout":
        getattr(st, TONE_RENDERER.get(meta.get("tone", "warn"), "warning"))(
            payload)
    elif kind == "metrics":
        columns = st.columns(len(payload))
        for column, metric in zip(columns, payload):
            with column:
                st.metric(label=metric["label"], value=metric["value"],
                          help=metric.get("help"))
    elif kind == "table":
        st.dataframe({column: [row[index] for row in payload["rows"]]
                      for index, column in enumerate(payload["columns"])},
                     width="stretch", hide_index=True)
    elif kind == "expander":
        with st.expander(meta.get("label", "Details")):
            for inner in payload:
                render_block(inner)
    elif kind == "download":
        st.download_button(meta.get("label", "Download"), payload,
                           file_name=meta.get("file_name", "report.md"),
                           mime="text/markdown")
    else:                                        # pragma: no cover - guarded
        raise ValueError(f"no renderer for block kind {kind!r}")


def render_page(view: ReportView) -> None:
    for block in blocks_module.page(view):
        render_block(block)


def sidebar_run_id() -> str | None:
    """Let the viewer pick a past run. Returns None for the latest."""
    st.sidebar.header("Run")
    st.sidebar.caption(
        "This page renders a run that already happened. It does not score "
        "anything, so opening it cannot change a figure.")
    try:
        runs = available_runs()
    except Exception as exc:                     # noqa: BLE001 - surfaced in UI
        st.sidebar.error(f"Could not list runs: {exc}")
        return None
    if not runs:
        return None

    labels = {f"{r['started_at']:%Y-%m-%d %H:%M} · {r['status']} · "
              f"{r['exposure_index']:.3f}": r["run_id"] for r in runs}
    choice = st.sidebar.selectbox("Scored runs", list(labels), index=0)
    return labels[choice]


def main() -> None:
    st.set_page_config(page_title=PAGE_TITLE, layout="wide")
    try:
        view = load_view(sidebar_run_id())
    except NoRunAvailable as exc:
        st.title(PAGE_TITLE)
        st.info(str(exc))
        return
    except Exception as exc:                     # noqa: BLE001 - surfaced in UI
        st.title(PAGE_TITLE)
        st.error(f"Could not load the run: {exc}")
        return
    render_page(view)


if __name__ == "__main__":
    main()
else:
    # Streamlit imports the script rather than running it under __main__.
    main()
