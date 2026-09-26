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
from app.contract import RefusalReason, RunCost, RunRequest
from app.style import STYLESHEET
from app.gateway import (NoRunAvailable, available_runs, in_scope_occupations,
                         load_view, submit)
from app.view_model import ReportView

PAGE_TITLE = "Task Exposure & Adoption Lag"
DEFAULT_QUESTION = ("Which of our equity research associate cost lines are "
                    "exposed to agent substitution, and on what timetable?")
# "info" is a neutral aside -- the sentence that stops a reader over-reading a
# figure is not a warning about the figure, and styling it as one would undercut
# the number it is protecting.
TONE_RENDERER = {"ok": "success", "warn": "warning", "stop": "error",
                 "info": "info"}


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
    elif kind == "style":
        st.markdown(payload, unsafe_allow_html=True)
    elif kind == "figure":
        meter = (f'<div class="meter"><i style="width:{payload["fill"]}"></i></div>'
                 if payload.get("fill") else "")
        note = (f'<div class="fig-note">{payload["note"]}</div>'
                if payload.get("note") else "")
        st.markdown(
            f'<div class="fig-label">{payload["label"]}</div>'
            f'<div class="fig">{payload["value"]}</div>{meter}{note}',
            unsafe_allow_html=True)
    elif kind == "span":
        note = (f'<div class="fig-note">{payload["note"]}</div>'
                if payload.get("note") else "")
        st.markdown(
            f'<div class="fig-label">{payload["label"]}</div>'
            f'<div class="span-rule">'
            f'<span class="tick">{payload["low"]}</span>'
            f'<span class="dash"></span>'
            f'<span class="mid">median {payload["mid"]}</span>'
            f'<span class="dash"></span>'
            f'<span class="tick">{payload["high"]}</span>'
            f'</div>{note}', unsafe_allow_html=True)
    elif kind == "masthead":
        st.markdown(
            f'<div class="masthead">'
            f'<div class="eyebrow">{payload["eyebrow"]}</div>'
            f'<h1>{payload["title"]}</h1>'
            f'<div class="question">{payload["question"]}</div>'
            f'<div class="meta">{payload["meta"]}</div>'
            f'</div>', unsafe_allow_html=True)
    elif kind == "panel":
        # A container, so the finding reads as one object rather than as loose
        # paragraphs. Streamlit cannot wrap arbitrary widgets in a div, so the
        # rule and the padding are drawn by a bordered container instead.
        with st.container(border=True):
            st.markdown(f'<div class="panel-label">{meta["label"]}</div>',
                        unsafe_allow_html=True)
            for inner in payload:
                render_block(inner)
    elif kind == "standing":
        st.markdown(
            f'<div class="standing {payload["tone"]}">'
            f'<div class="tag">{payload["tag"]}</div>'
            f'<div class="body">{payload["body"]}</div></div>',
            unsafe_allow_html=True)
    elif kind == "request_form":
        # The request half of the TDD 1.1 contract. Collects a question and
        # nothing else; scope resolution belongs to the Intent & Scope node.
        with st.form("run_request", clear_on_submit=False):
            question = st.text_area(payload["label"],
                                    value=payload["default_question"],
                                    height=90, max_chars=500)
            confirm = st.checkbox(payload["confirm_label"], value=False)
            submitted = st.form_submit_button(payload["submit_label"],
                                              type="primary")
        if submitted:
            if not confirm:
                st.warning("Please tick the box before running. A button that "
                           "quietly spends money is not one to trust.")
            else:
                st.session_state["pending_request"] = question
                st.rerun()
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


def _run_pending_request() -> str | None:
    """Submit a queued request through the gateway. Returns a run id, or None.

    The UI builds a typed RunRequest and calls the gateway; it does not touch
    the orchestration package, hold a credential, or interpret anything beyond
    the typed result it gets back. That is what keeps the tier boundary real
    while still satisfying the request arrow the architecture draws.
    """
    question = st.session_state.pop("pending_request", None)
    if not question:
        return None

    try:
        request = RunRequest(question=question)
    except Exception as exc:                     # noqa: BLE001 - surfaced
        st.error(f"That request was not accepted: {exc}")
        return None

    cost = RunCost()
    with st.spinner(f"Running the analysis — about {cost.calls} model calls, "
                    f"{cost.duration_text}. Do not close this tab."):
        result = submit(request)

    st.session_state["last_result"] = result.model_dump()
    if result.produced_a_verdict:
        st.success(f"Run complete: {result.status} · {result.calls} calls · "
                   f"{result.tokens:,} tokens")
        return result.run_id

    for block in blocks_module.refusal_blocks(
            RefusalReason(**result.refusal.model_dump())):
        render_block(block)
    return None


def main() -> None:
    st.set_page_config(page_title=PAGE_TITLE, layout="wide",
                       initial_sidebar_state="collapsed")
    st.markdown(STYLESHEET, unsafe_allow_html=True)

    fresh_run_id = _run_pending_request()

    # The request form sits above the report: the customer's own question is
    # the entry point, and the rendered run is the answer to it.
    try:
        occupations = in_scope_occupations()
    except Exception:                            # noqa: BLE001 - degrade
        occupations = []
    if occupations:
        for block in blocks_module.request_form_blocks(
                occupations, DEFAULT_QUESTION, RunCost()):
            render_block(block)

    try:
        view = load_view(fresh_run_id or sidebar_run_id())
    except NoRunAvailable as exc:
        st.title(PAGE_TITLE)
        st.info(str(exc))
        return
    except Exception as exc:                     # noqa: BLE001 - surfaced in UI
        st.title(PAGE_TITLE)
        st.error(f"Could not load the run: {exc}")
        return
    render_page(view)


# Streamlit executes the script with __name__ == "__main__" -- verified against
# the running version rather than assumed. An earlier `else: main()` branch
# claimed otherwise, which meant importing this module for a single constant
# executed the whole app. Harmless while main() only emitted no-ops outside a
# Streamlit context; the moment it created a form, the dangling form context
# broke the next AppTest with "Forms cannot be nested in other forms."
#
# Importing this module must have no side effects. A test that reads a constant
# from here should not run an application.
if __name__ == "__main__":
    main()
