"""The page's visual identity, as one stylesheet for one document.

This reads as a research note from a finance desk, because that is what its
audience reads. The reader is deciding a hiring plan against a figure they do not
yet trust, so the design's job is to make the finding legible and its standing
unmissable --- in that order.

Five decisions, each of which had an obvious alternative:

**A document, not a dashboard.** The first attempt styled Streamlit's widgets and
lost: every ``st.metric`` and ``st.dataframe`` carries its own container, its own
margin and its own idea of a heading, so the result read as a tinted dashboard
however good the colours were. The page is now composed markup on one measure
with one vertical rhythm (see :mod:`app.document`), and Streamlit's own chrome is
hidden. A dashboard is for monitoring something you already understand; this
reader is being persuaded.

**Serif for prose, sans for labels, mono for numbers.** Source Serif for the
argument, because a serif at a comfortable measure signals *published research*
rather than *software output*, and this analysis wants to be read as the former.
IBM Plex Sans for labels and navigation, IBM Plex Mono with tabular figures for
every quantity, so columns of numbers align and a figure never reflows as it
changes. Three faces doing three jobs, not three fonts for variety.

**Exposure and lag get deliberately different grammar.** The architecture's
central claim is that they are separate quantities which must never be combined.
So exposure --- bounded 0 to 1 --- gets a meter with a track, and the lag --- an
unbounded interval in years --- gets a span with no track at all. Matching gauges
would invite exactly the comparison the whole system refuses to make. Structure
encoding a claim, not decoration.

**Status is ink weight, never a fill.** "Independent check inconclusive" is a
finding. Rendered as a yellow hazard banner it reads as a defect and a client
discounts everything under it; rendered as dark ochre against a hairline rule it
reads as rigour. The colours here are ink colours chosen to pass contrast on
paper, not signal colours borrowed from an alerting system.

**Cool paper, blue-cast ink, one accent.** Rather than the warm cream and
terracotta that has become the house style of generated interfaces. A single deep
slate-teal carries every accent --- rules, section numbers, the meter fill --- so
nothing on the page is coloured for emphasis alone. It should look like it came
from an institution.
"""

from __future__ import annotations

STYLESHEET = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');

:root {
  --paper:     #FCFCFD;
  --panel:     #F1F3F6;
  --ink:       #0E1216;
  --ink-body:  #232A33;
  --ink-soft:  #5B6572;
  --ink-faint: #8D96A3;
  --rule:      #E2E6EB;
  --rule-firm: #C8CFD7;
  --deep:      #12414E;
  --ok:        #1B6647;
  --review:    #78570F;
  --stop:      #8A2E23;

  --measure: 68ch;        /* one comfortable reading measure, used everywhere */
  --gap:     1.5rem;
}

/* ---- host chrome: hidden, because this is a document ------------------- */
#MainMenu, header[data-testid="stHeader"], footer,
[data-testid="stToolbar"], [data-testid="stDecoration"],
[data-testid="stStatusWidget"] { display: none !important; visibility: hidden; }

html, body, [data-testid="stAppViewContainer"] { background: var(--paper); }

.block-container {
  max-width: 1040px !important;
  padding: 2.6rem 2rem 5rem !important;
}

/* Streamlit wraps every element in a spaced container. The document supplies
   its own rhythm, so the framework's is removed rather than fought. */
[data-testid="stVerticalBlock"] { gap: 0 !important; }
[data-testid="stMarkdownContainer"] > div { margin: 0 !important; }

/* ---- document frame --------------------------------------------------- */
.doc {
  font-family: 'Source Serif 4', Georgia, serif;
  font-size: 1.0625rem;
  line-height: 1.68;
  color: var(--ink-body);
}
.doc p { margin: 0 0 .85rem; max-width: var(--measure); }
.doc strong { font-weight: 600; color: var(--ink); }
.doc code {
  font-family: 'IBM Plex Mono', monospace; font-size: .86em;
  background: var(--panel); padding: .08em .3em; border-radius: 2px;
  color: var(--ink);
}
.doc .bullet { position: relative; padding-left: 1.05rem; }
.doc .bullet::before {
  content: ""; position: absolute; left: 0; top: .72em;
  width: 5px; height: 1px; background: var(--ink-faint);
}
hr.rule { border: 0; border-top: 1px solid var(--rule); margin: 2.4rem 0; }

/* ---- masthead: a letterhead ------------------------------------------- */
.masthead { border-top: 3px solid var(--ink); padding-top: 1.1rem; margin-bottom: 2rem; }
.masthead .eyebrow {
  font-family: 'IBM Plex Mono', monospace;
  font-size: .68rem; font-weight: 500; text-transform: uppercase;
  letter-spacing: .2em; color: var(--deep); margin: 0 0 .7rem;
}
.masthead h1 {
  font-family: 'Source Serif 4', Georgia, serif;
  font-size: 2.6rem; font-weight: 600; line-height: 1.06;
  letter-spacing: -.02em; color: var(--ink); margin: 0 0 .7rem;
  max-width: 24ch;
}
.masthead .lede {
  font-size: 1.1875rem; line-height: 1.5; color: var(--ink-soft);
  margin: 0 0 1.1rem; max-width: 52ch;
}
.masthead .meta {
  font-family: 'IBM Plex Mono', monospace; font-size: .72rem;
  color: var(--ink-faint); letter-spacing: .01em; margin: 0;
  padding-top: .8rem; border-top: 1px solid var(--rule);
  max-width: none;
}

/* ---- section headings: a number, then the reader's question ----------- */
h2.sec {
  font-family: 'IBM Plex Sans', system-ui, sans-serif;
  font-size: 1.28rem; font-weight: 600; line-height: 1.3;
  letter-spacing: -.012em; color: var(--ink);
  margin: 2.8rem 0 1.1rem; max-width: 40ch;
  display: flex; gap: .8rem; align-items: baseline;
}
h2.sec .sec-no {
  font-family: 'IBM Plex Mono', monospace; font-size: .8rem; font-weight: 500;
  color: var(--deep); letter-spacing: .06em; flex: 0 0 auto;
  padding-top: .18rem;
}

/* ---- the summary band ------------------------------------------------- */
.cards {
  display: grid; grid-template-columns: repeat(3, 1fr);
  gap: 0; border-top: 1px solid var(--rule-firm);
  border-bottom: 1px solid var(--rule-firm); margin: 0 0 1.8rem;
}
.card { padding: 1.35rem 1.4rem 1.5rem; border-left: 1px solid var(--rule); }
.card:first-child { border-left: 0; padding-left: 0; }

/* ---- figures: the numbers are the typography -------------------------- */
.fig { margin: 0; }
.fig-label {
  font-family: 'IBM Plex Sans', system-ui, sans-serif;
  font-size: .7rem; font-weight: 500; text-transform: uppercase;
  letter-spacing: .11em; color: var(--ink-faint);
  margin: 0 0 .55rem !important; max-width: 26ch;
}
.fig-value {
  font-family: 'IBM Plex Mono', monospace; font-variant-numeric: tabular-nums;
  font-size: 2.9rem; font-weight: 400; line-height: 1;
  letter-spacing: -.035em; color: var(--ink); margin: 0 !important;
}
.fig-note {
  font-family: 'IBM Plex Sans', system-ui, sans-serif;
  font-size: .78rem; line-height: 1.5; color: var(--ink-soft);
  margin: .6rem 0 0 !important; max-width: 34ch;
}

/* Bounded, so it gets a track. */
.meter { height: 3px; background: var(--rule); margin-top: .8rem; max-width: 34ch; }
.meter > i { display: block; height: 100%; background: var(--deep); }

/* Unbounded, so deliberately NO track. */
.span { display: flex; align-items: baseline; gap: .5rem; }
.span .tick, .span .mid {
  font-family: 'IBM Plex Mono', monospace; font-variant-numeric: tabular-nums;
  color: var(--ink); letter-spacing: -.02em;
}
.span .tick { font-size: 1.5rem; }
.span .mid  { font-size: 2.9rem; line-height: 1; letter-spacing: -.035em; }
.span .bar  { flex: 0 0 18px; height: 1px; background: var(--rule-firm); }

/* Inside a summary card the measure is a third of the page, so the figures step
   down. Measured rather than guessed: "5.0 - 10.1 - 30.0" set at the detail
   scale needs about 278px of a 280px card and wraps. */
.card .fig-value { font-size: 2.25rem; }
.card .span .mid { font-size: 2.25rem; }
.card .span .tick { font-size: 1.15rem; }
.card .span .bar { flex: 0 0 12px; }
.card .fig-note { font-size: .74rem; max-width: 26ch; }
.card .meter { max-width: none; }

/* ---- standing: a stamp, not a banner --------------------------------- */
.standing {
  border-left: 3px solid var(--rule-firm);
  padding: .15rem 0 .2rem 1rem; margin: 0 0 1.4rem;
}
.standing .tag {
  font-family: 'IBM Plex Mono', monospace;
  font-size: .72rem; font-weight: 500; text-transform: uppercase;
  letter-spacing: .14em; margin: 0 0 .4rem !important;
}
.standing .body {
  font-size: .98rem; line-height: 1.6; color: var(--ink-soft); margin: 0 !important;
}
.standing.ok   { border-left-color: var(--ok); }
.standing.ok   .tag { color: var(--ok); }
.standing.warn { border-left-color: var(--review); }
.standing.warn .tag { color: var(--review); }
.standing.stop { border-left-color: var(--stop); }
.standing.stop .tag { color: var(--stop); }

/* ---- the bottom-line panel ------------------------------------------- */
.panel {
  background: var(--panel); border-left: 3px solid var(--deep);
  padding: 1.3rem 1.5rem .65rem; margin: 0 0 1.6rem;
}
.panel-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: .68rem; font-weight: 500; text-transform: uppercase;
  letter-spacing: .17em; color: var(--deep); margin: 0 0 .7rem !important;
}
.panel p { font-size: 1.09rem; line-height: 1.62; }

/* ---- a neutral aside, and the two that are not neutral --------------- */
.note {
  font-family: 'IBM Plex Sans', system-ui, sans-serif;
  font-size: .86rem; line-height: 1.6; color: var(--ink-soft);
  border-left: 2px solid var(--rule-firm); padding: .1rem 0 .1rem .9rem;
  margin: 0 0 1.2rem; max-width: var(--measure);
}
.note.warn { border-left-color: var(--review); color: var(--ink-body); }
.note.stop { border-left-color: var(--stop);   color: var(--ink-body); }

/* ---- metrics: a label row, not tiles --------------------------------- */
.metrics {
  display: flex; flex-wrap: wrap; gap: 2.6rem;
  margin: 0 0 1.5rem; padding: 1rem 0;
  border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule);
}
.metric-label {
  font-family: 'IBM Plex Sans', system-ui, sans-serif;
  font-size: .68rem; font-weight: 500; text-transform: uppercase;
  letter-spacing: .1em; color: var(--ink-faint);
  margin: 0 0 .3rem !important; max-width: 22ch;
}
.metric-value {
  font-family: 'IBM Plex Mono', monospace; font-variant-numeric: tabular-nums;
  font-size: 1.45rem; color: var(--ink); margin: 0 !important; letter-spacing: -.02em;
}

/* ---- tables read as data --------------------------------------------- */
.table-wrap { margin: 0 0 1.6rem; overflow-x: auto; }
.doc table { width: 100%; border-collapse: collapse; }
.doc thead th {
  font-family: 'IBM Plex Sans', system-ui, sans-serif;
  font-size: .67rem; font-weight: 600; text-transform: uppercase;
  letter-spacing: .09em; color: var(--ink-soft); text-align: left;
  padding: 0 .85rem .55rem 0; border-bottom: 1px solid var(--ink);
  white-space: nowrap;
}
.doc tbody td {
  font-size: .9rem; line-height: 1.5; color: var(--ink-body);
  padding: .6rem .85rem .6rem 0; border-bottom: 1px solid var(--rule);
  vertical-align: top;
}
.doc tbody tr:hover td { background: var(--panel); }
.doc td.num, .doc th.num {
  font-family: 'IBM Plex Mono', monospace; font-variant-numeric: tabular-nums;
  text-align: right; white-space: nowrap; color: var(--ink);
}
.doc td.txt { max-width: 46ch; }
.doc thead th.txt { text-align: left; }
.doc thead th:first-child { min-width: 18ch; }

/* ---- disclosures: footnotes, not furniture --------------------------- */
details.disclose {
  border-top: 1px solid var(--rule); margin: 0 0 1.4rem; padding-top: .55rem;
}
details.disclose summary {
  font-family: 'IBM Plex Sans', system-ui, sans-serif;
  font-size: .78rem; font-weight: 500; color: var(--ink-soft);
  cursor: pointer; list-style: none; display: flex; gap: .5rem; align-items: center;
}
details.disclose summary::-webkit-details-marker { display: none; }
details.disclose summary::before {
  content: "+"; font-family: 'IBM Plex Mono', monospace; color: var(--deep);
  font-size: .9rem; line-height: 1;
}
details.disclose[open] summary::before { content: "\\2013"; }
details.disclose summary:hover { color: var(--deep); }
.disclose-body { padding: .9rem 0 .2rem; }
.disclose-body p { font-size: .95rem; color: var(--ink-soft); }

p.caption {
  font-family: 'IBM Plex Sans', system-ui, sans-serif;
  font-size: .76rem; line-height: 1.55; color: var(--ink-faint);
  margin: 0 0 1rem; max-width: var(--measure);
}

/* ---- the two surviving widgets, brought into the same language ------- */
[data-testid="stForm"] {
  border: 0; border-top: 1px solid var(--rule-firm); border-radius: 0;
  padding: 1.2rem 0 0; background: transparent;
}
.stTextArea textarea {
  font-family: 'Source Serif 4', Georgia, serif !important;
  font-size: 1rem !important; border-radius: 2px !important;
  border-color: var(--rule-firm) !important; background: #fff !important;
}
.stTextArea label, .stCheckbox label, [data-testid="stWidgetLabel"] label {
  font-family: 'IBM Plex Sans', system-ui, sans-serif !important;
  font-size: .8rem !important; color: var(--ink-soft) !important;
}
button[kind="primary"], button[kind="primaryFormSubmit"] {
  border-radius: 2px !important; background: var(--deep) !important;
  border-color: var(--deep) !important; color: #fff !important;
  font-family: 'IBM Plex Sans', system-ui, sans-serif !important;
  font-size: .85rem !important; font-weight: 500 !important;
  padding: .45rem 1.3rem !important;
}
button[kind="secondary"], [data-testid="stDownloadButton"] button {
  border-radius: 2px !important; border-color: var(--rule-firm) !important;
  color: var(--ink) !important; background: transparent !important;
  font-family: 'IBM Plex Sans', system-ui, sans-serif !important;
  font-size: .8rem !important;
}
[data-testid="stSidebar"] { background: var(--panel); border-right: 1px solid var(--rule); }
[data-testid="stSidebar"] * { font-family: 'IBM Plex Sans', system-ui, sans-serif !important; }
[data-testid="stAlert"] {
  border-radius: 0; border: 0; border-left: 2px solid var(--rule-firm);
  background: var(--panel); color: var(--ink-body);
  font-family: 'IBM Plex Sans', system-ui, sans-serif;
}

/* ---- quality floor --------------------------------------------------- */
*:focus-visible { outline: 2px solid var(--deep); outline-offset: 2px; }
@media (prefers-reduced-motion: reduce) { * { animation: none !important; transition: none !important; } }

@media (max-width: 820px) {
  .cards { grid-template-columns: 1fr; }
  .card { border-left: 0; border-top: 1px solid var(--rule); padding-left: 0; }
  .card:first-child { border-top: 0; }
  .masthead h1 { font-size: 2rem; }
  .fig-value, .span .mid { font-size: 2.2rem; }
  .block-container { padding: 1.5rem 1rem 3rem !important; }
  .metrics { gap: 1.6rem; }
}

/* It is a document, so it should print like one. */
@media print {
  .block-container { max-width: none !important; padding: 0 !important; }
  [data-testid="stSidebar"], [data-testid="stForm"],
  [data-testid="stDownloadButton"] { display: none !important; }
  details.disclose { open: true; }
  .doc { font-size: 10.5pt; }
  h2.sec { break-after: avoid; }
  .cards, .table-wrap, .panel { break-inside: avoid; }
}
</style>
"""
