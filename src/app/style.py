"""The page's visual identity, as one stylesheet for one document.

This reads as a research note from a finance desk, because that is what its
audience reads. The reader is deciding a hiring plan against a figure they do not
yet trust, so the design's job is to make the finding legible and its standing
unmissable --- in that order.

**The palette is taken from the two sites you pointed at**, read from their
stylesheets rather than described from memory. Boston University:
BU Red ``#CC0000``, black ``#2D2926``, a deep navy ``#0C2537``, off-white
``#F5F6F8``. Red Key Solutions: reds ``#E82329`` / ``#C31420``, near-black
``#1C1B1A``, pale greys ``#F5F5F5`` / ``#DBDBDB``. What they agree on is more
useful than where they differ: both are overwhelmingly white, both carry a single
red, both set text in a warm near-black rather than pure black, and both keep
colour off the body of the page entirely.

So red appears in exactly four places --- the masthead rule, the section marks,
the primary button, and the "not fit to use" standing --- and nowhere else. In
particular **the data bars are ink, never red.** A bar in the brand's red reads as
an alarm, which would tell the reader something about the number that the number
does not say. The navy is the structural dark: headings, the meter fill, focus.

**Type inverts the usual pairing, on purpose.** Libre Franklin --- an American
institutional gothic, which is the register both reference sites are written in ---
sets the masthead and the headings, because a headline here is signage. Source
Serif carries the argument, because a case a reader has to weigh should read like
prose and not like an interface. IBM Plex Mono with tabular figures sets every
quantity, so columns align and a figure does not reflow as it changes.

**Exposure and lag get deliberately different grammar.** The architecture's
central claim is that they are separate quantities which must never be combined.
Exposure --- bounded 0 to 1 --- gets a meter with a track; the lag --- an unbounded
interval in years --- gets a span with no track at all. Matching gauges would
invite exactly the comparison the whole system refuses to make.

**The signature is the exposure spine.** Each row of the per-task table carries a
short ink rule scaled to that task's net exposure, so the shape of the
distribution is visible instead of being assembled from 26 decimals. That shape is
the claim the rubric exists to support --- it discriminates rather than saturates,
which is why this occupation was chosen --- and it is drawn from figures already on
the page rather than from anything new.

**Status is ink weight, never a fill.** "Independent check inconclusive" is a
finding. Rendered as a yellow hazard banner it reads as a defect and a client
discounts everything under it; rendered as dark ochre against a hairline rule it
reads as rigour.

**A document, not a dashboard.** The first version styled Streamlit's widgets and
lost: each one brings its own container, its own margin and its own idea of a
heading, so the result read as a tinted dashboard however good the colours were.
The page is composed markup on one measure with one vertical rhythm (see
:mod:`app.document`) and the framework's chrome is hidden. A dashboard is for
monitoring something you already understand; this reader is being persuaded.
"""

from __future__ import annotations

STYLESHEET = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Libre+Franklin:wght@400;500;600;700&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&family=IBM+Plex+Mono:wght@400;500&display=swap');

:root {
  /* Boston University and Red Key Solutions, read from their stylesheets. */
  --paper:     #FFFFFF;   /* both sites are overwhelmingly white */
  --panel:     #F5F6F8;   /* BU off-white; RKS #F3F4F8 agrees */
  --panel-warm:#F5F5F5;   /* RKS panel grey, for table hover */
  --ink:       #1C1B1A;   /* RKS near-black: warmer and more specific than #000 */
  --ink-body:  #33302E;
  --ink-soft:  #63605D;
  --ink-faint: #8E8B88;
  --rule:      #E4E4E6;
  --rule-firm: #DBDBDB;   /* RKS */
  --navy:      #0C2537;   /* BU secondary: the structural dark */
  --red:       #CC0000;   /* BU Red: the single accent */
  --red-deep:  #C31420;   /* RKS, for hover and the hardest status */
  --ok:        #1B6647;
  --review:    #8A6A11;

  --measure: 68ch;        /* one comfortable reading measure, used everywhere */
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
.masthead { border-top: 4px solid var(--red); padding-top: 1.15rem; margin-bottom: 2.1rem; }
.masthead .eyebrow {
  font-family: 'IBM Plex Mono', monospace;
  font-size: .68rem; font-weight: 500; text-transform: uppercase;
  letter-spacing: .2em; color: var(--red); margin: 0 0 .7rem;
}
.masthead h1 {
  font-family: 'Source Serif 4', Georgia, serif;
  font-size: 2.6rem; font-weight: 600; line-height: 1.06;
  letter-spacing: -.025em; color: var(--navy); margin: 0 0 .7rem;
  max-width: 26ch;
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
  font-family: 'Libre Franklin', system-ui, sans-serif;
  font-size: 1.28rem; font-weight: 600; line-height: 1.3;
  letter-spacing: -.012em; color: var(--navy);
  margin: 2.8rem 0 1.1rem; max-width: 40ch;
  display: flex; gap: .8rem; align-items: baseline;
}
h2.sec .sec-no {
  font-family: 'IBM Plex Mono', monospace; font-size: .8rem; font-weight: 500;
  color: var(--red); letter-spacing: .06em; flex: 0 0 auto;
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
  font-family: 'Libre Franklin', system-ui, sans-serif;
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
  font-family: 'Libre Franklin', system-ui, sans-serif;
  font-size: .78rem; line-height: 1.5; color: var(--ink-soft);
  margin: .6rem 0 0 !important; max-width: 34ch;
}

/* Bounded, so it gets a track. */
.meter { height: 3px; background: var(--rule); margin-top: .8rem; max-width: 34ch; }
.meter > i { display: block; height: 100%; background: var(--navy); }

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
.standing.stop { border-left-color: var(--red-deep); }
.standing.stop .tag { color: var(--red-deep); }

/* ---- the bottom-line panel ------------------------------------------- */
.panel {
  background: var(--panel); border-left: 3px solid var(--navy);
  padding: 1.3rem 1.5rem .65rem; margin: 0 0 1.6rem;
}
.panel-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: .68rem; font-weight: 500; text-transform: uppercase;
  letter-spacing: .17em; color: var(--navy); margin: 0 0 .7rem !important;
}
.panel p { font-size: 1.09rem; line-height: 1.62; }

/* ---- a neutral aside, and the two that are not neutral --------------- */
.note {
  font-family: 'Libre Franklin', system-ui, sans-serif;
  font-size: .86rem; line-height: 1.6; color: var(--ink-soft);
  border-left: 2px solid var(--rule-firm); padding: .1rem 0 .1rem .9rem;
  margin: 0 0 1.2rem; max-width: var(--measure);
}
.note.warn { border-left-color: var(--review); color: var(--ink-body); }
.note.stop { border-left-color: var(--red-deep); color: var(--ink-body); }

/* ---- metrics: a label row, not tiles --------------------------------- */
.metrics {
  display: flex; flex-wrap: wrap; gap: 2.6rem;
  margin: 0 0 1.5rem; padding: 1rem 0;
  border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule);
}
.metric-label {
  font-family: 'Libre Franklin', system-ui, sans-serif;
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
  font-family: 'Libre Franklin', system-ui, sans-serif;
  font-size: .67rem; font-weight: 600; text-transform: uppercase;
  letter-spacing: .09em; color: var(--ink-soft); text-align: left;
  padding: 0 .85rem .55rem 0; border-bottom: 1.5px solid var(--navy);
  white-space: nowrap;
}
.doc tbody td {
  font-size: .9rem; line-height: 1.5; color: var(--ink-body);
  padding: .6rem .85rem .6rem 0; border-bottom: 1px solid var(--rule);
  vertical-align: top;
}
.doc tbody tr:hover td { background: var(--panel-warm); }
.doc td.num, .doc th.num {
  font-family: 'IBM Plex Mono', monospace; font-variant-numeric: tabular-nums;
  text-align: right; white-space: nowrap; color: var(--ink);
}
.doc td.txt { max-width: 46ch; }
.doc thead th.txt { text-align: left; }
.doc thead th:first-child { min-width: 18ch; }

/* ---- the exposure spine: the signature element ----------------------- */
/* One short rule per task, scaled to its net exposure, sitting in the cell it
   describes. It makes the SHAPE of the distribution visible -- which is the claim
   the rubric exists to support, since the whole reason this occupation was chosen
   is that the score has to discriminate rather than saturate.

   Ink, not red. A bar in the brand's red would tell the reader something about
   the number that the number does not say. It sits to the left of the numeral in
   a fixed gutter so the numerals stay in one column and remain comparable. */
.spine {
  display: inline-block; width: 46px; height: 3px; margin-right: .6rem;
  background: var(--rule-firm); vertical-align: .22em;
}
.spine > i { display: block; height: 100%; background: var(--ink); }
.doc td.num:has(.spine) { white-space: nowrap; }

/* ---- disclosures: footnotes, not furniture --------------------------- */
details.disclose {
  border-top: 1px solid var(--rule); margin: 0 0 1.4rem; padding-top: .55rem;
}
details.disclose summary {
  font-family: 'Libre Franklin', system-ui, sans-serif;
  font-size: .78rem; font-weight: 500; color: var(--ink-soft);
  cursor: pointer; list-style: none; display: flex; gap: .5rem; align-items: center;
}
details.disclose summary::-webkit-details-marker { display: none; }
details.disclose summary::before {
  content: "+"; font-family: 'IBM Plex Mono', monospace; color: var(--red);
  font-size: .9rem; line-height: 1;
}
details.disclose[open] summary::before { content: "\\2013"; }
details.disclose summary:hover { color: var(--navy); }
.disclose-body { padding: .9rem 0 .2rem; }
.disclose-body p { font-size: .95rem; color: var(--ink-soft); }

p.caption {
  font-family: 'Libre Franklin', system-ui, sans-serif;
  font-size: .76rem; line-height: 1.55; color: var(--ink-faint);
  margin: 0 0 1rem; max-width: var(--measure);
}

/* ---- the request card ------------------------------------------------- */
/* This was a bare framework form sitting under the document: a label, a box, a
   tick and a button, each in its own container with its own margin. It read as
   an afterthought on a page that is otherwise composed, which is the worst place
   for it -- this is the one control on the page, and the moment a client decides
   whether the thing is theirs to use.

   It is now a card: panel ground, a red eyebrow tying it to the masthead, a
   serif input at the same measure as the prose, and the cost of a run stated
   beside the button rather than buried in a disclosure. A button that spends
   money should say so where the decision is made. */
[data-testid="stForm"] {
  border: 0 !important; border-top: 3px solid var(--navy) !important;
  border-radius: 0 !important; padding: 1.4rem 1.6rem 1.5rem !important;
  background: var(--panel); margin-top: .4rem;
}
.stTextArea textarea {
  font-family: 'Source Serif 4', Georgia, serif !important;
  font-size: 1.02rem !important; line-height: 1.55 !important;
  border-radius: 2px !important; border: 1px solid var(--rule-firm) !important;
  background: var(--paper) !important; color: var(--ink) !important;
  padding: .7rem .85rem !important;
}
.stTextArea textarea:focus {
  border-color: var(--navy) !important;
  box-shadow: 0 0 0 2px rgba(12, 37, 55, .12) !important;
}
.stTextArea label, .stCheckbox label, [data-testid="stWidgetLabel"] label,
[data-testid="stWidgetLabel"] p {
  font-family: 'Libre Franklin', system-ui, sans-serif !important;
  font-size: .78rem !important; font-weight: 500 !important;
  color: var(--ink-soft) !important;
}
[data-testid="stForm"] [data-testid="stCheckbox"] { margin-top: .3rem; }
button[kind="primary"], button[kind="primaryFormSubmit"] {
  border-radius: 2px !important; background: var(--red) !important;
  border-color: var(--red) !important; color: var(--paper) !important;
  font-family: 'Libre Franklin', system-ui, sans-serif !important;
  font-size: .85rem !important; font-weight: 600 !important;
  letter-spacing: .01em; padding: .5rem 1.5rem !important;
  box-shadow: none !important;
}
button[kind="primary"]:hover, button[kind="primaryFormSubmit"]:hover {
  background: var(--red-deep) !important; border-color: var(--red-deep) !important;
}
button[kind="secondary"], [data-testid="stDownloadButton"] button {
  border-radius: 2px !important; border-color: var(--rule-firm) !important;
  color: var(--navy) !important; background: var(--paper) !important;
  font-family: 'Libre Franklin', system-ui, sans-serif !important;
  font-size: .78rem !important; font-weight: 500 !important;
}
[data-testid="stDownloadButton"] button:hover {
  border-color: var(--navy) !important;
}
/* The run cost, set beside the button rather than under a disclosure. */
.run-cost {
  font-family: 'Libre Franklin', system-ui, sans-serif;
  font-size: .76rem; line-height: 1.5; color: var(--ink-soft);
  padding-top: .55rem;
}
[data-testid="stSidebar"] { background: var(--panel); border-right: 1px solid var(--rule); }
[data-testid="stSidebar"] * { font-family: 'Libre Franklin', system-ui, sans-serif !important; }
[data-testid="stAlert"] {
  border-radius: 0; border: 0; border-left: 2px solid var(--rule-firm);
  background: var(--panel); color: var(--ink-body);
  font-family: 'Libre Franklin', system-ui, sans-serif;
}

/* ---- quality floor --------------------------------------------------- */
*:focus-visible { outline: 2px solid var(--navy); outline-offset: 2px; }
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
