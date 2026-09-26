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
from app import document
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
    """Render one block that has to be a real widget.

    Only three kinds reach here. Everything that is part of the document is
    markup now (:mod:`app.document`), and the branches for headings, tables,
    figures and the rest were deleted rather than left unreachable --- a
    dispatcher listing renderers nothing calls invites the next person to edit
    the wrong one.

    Raises on anything else rather than skipping it: a silently dropped block is
    a figure the customer never saw, which is the failure mode this whole project
    is built to avoid.
    """
    kind, payload, meta = block.kind, block.payload, block.meta

    if kind == "request_form":
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
        # A widget because it needs a real HTTP response, which markup cannot
        # produce. The only other reason to keep one.
        st.download_button(meta.get("label", "Download"), payload,
                           file_name=meta.get("file_name", "report.md"),
                           mime="text/markdown")
    elif kind == "style":
        st.markdown(payload, unsafe_allow_html=True)
    else:                                        # pragma: no cover - guarded
        raise ValueError(
            f"block kind {kind!r} is not a widget; it belongs in the document")


def render_page(view: ReportView) -> None:
    """Emit the report as document runs with widgets in their proper places.

    One ``st.html`` per run rather than one widget per block. The block list is
    unchanged --- it is still the presentation model and still what the tests
    inspect --- but composing it into a document is what lets the page have one
    measure, one vertical rhythm and one type scale. Styling Streamlit's own
    widgets was the first attempt and it read as a tinted dashboard, because each
    widget brings its own container and its own idea of a heading.

    The download button stays a widget because it needs a real HTTP response,
    which markup cannot produce --- and it is emitted in position, inside the
    section that earns it, rather than appended after the document.
    """
    _emit(blocks_module.page(view))


def _emit(page_blocks) -> None:
    for kind, item in document.segments(page_blocks):
        if kind == "html":
            st.html(item)
        else:
            render_block(item)


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

    _emit(blocks_module.refusal_blocks(
        RefusalReason(**result.refusal.model_dump())))
    return None


def main() -> None:
    st.set_page_config(page_title=PAGE_TITLE, layout="wide",
                       initial_sidebar_state="collapsed")
    st.markdown(STYLESHEET, unsafe_allow_html=True)

    fresh_run_id = _run_pending_request()

    try:
        view = load_view(fresh_run_id or sidebar_run_id())
    except NoRunAvailable as exc:
        st.info(str(exc))
        _render_request_form()
        return
    except Exception as exc:                     # noqa: BLE001 - surfaced in UI
        st.error(f"Could not load the run: {exc}")
        return

    render_page(view)
    # The form follows the document, and that order was reversed deliberately.
    # It used to lead, on the reasoning that the customer's own question is the
    # entry point. But an input box above the letterhead makes the page read as a
    # tool rather than as a note, and the entry point for someone being shown
    # this is the finding. "Ask about another role" is the right next move once
    # they have read one, so it sits where that move belongs.
    _render_request_form()


def _render_request_form() -> None:
    """The request half of the TDD 1.1 contract, if any occupation is published."""
    try:
        occupations = in_scope_occupations()
    except Exception:                            # noqa: BLE001 - degrade quietly
        return
    if not occupations:
        return
    _emit(blocks_module.request_form_blocks(
        occupations, DEFAULT_QUESTION, RunCost()))


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
