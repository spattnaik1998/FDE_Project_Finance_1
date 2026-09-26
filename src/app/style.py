"""The page's visual identity, as one stylesheet.

This reads as a research note for a finance desk, because that is what its
audience reads. The reader is deciding a hiring plan against a figure they do
not yet trust, so the design's job is to make the figure legible and its
standing unmissable — in that order.

Three decisions worth stating, because each one had an obvious alternative:

**The figures are the typography.** The hero of this page is not a headline, it
is a number: an exposure index and a lag interval. They are set in IBM Plex
Mono at display size with tabular figures, so the data carries the page's
personality rather than a display serif sitting above it. Plex was designed for
technical documents and reads as institutional rather than fashionable, which
is the register a skeptical analyst trusts.

**Exposure and lag get deliberately different grammar.** The architecture's
central claim is that they are separate quantities which must never be
combined. So exposure — bounded 0 to 1 — gets a meter, and lag — an unbounded
interval in years — gets a span with no track behind it. Giving them matching
gauges would invite exactly the comparison the whole system refuses to make.
Structure encoding truth, not decoration.

**Status is text-weight, never a fill.** "Analyst review required" is a
finding. Rendered as a yellow hazard banner it reads as a defect and a client
discounts everything under it; rendered as dark ochre against a hairline rule
it reads as rigour. The colours here are ink colours, chosen to pass contrast
on paper, not signal colours borrowed from an alerting system.

Cool paper against blue-cast ink, rather than the warm cream and terracotta that
has become the default palette of generated interfaces. This should look like it
came from an institution.
"""

from __future__ import annotations

STYLESHEET = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

:root {
  --paper:      #F7F8FA;
  --panel:      #EEF1F5;
  --ink:        #141922;
  --ink-soft:   #5A6472;
  --ink-faint:  #8A94A3;
  --rule:       #DDE2E8;
  --deep:       #16414E;
  --ok:         #1C6B4A;
  --review:     #7A5A12;
  --stop:       #8C2F24;
}

html, body, [class*="css"] { font-family: 'IBM Plex Sans', system-ui, sans-serif; }

/* Tighter measure: research notes are read, not scanned. */
.block-container { max-width: 1120px; padding-top: 2.2rem; }

h1 {
  font-size: 1.65rem !important; font-weight: 600 !important;
  letter-spacing: -0.015em; color: var(--ink) !important; margin-bottom: .15rem !important;
}
h2, h3 {
  font-size: .82rem !important; font-weight: 600 !important;
  text-transform: uppercase; letter-spacing: .10em;
  color: var(--ink-soft) !important;
  border-bottom: 1px solid var(--rule); padding-bottom: .45rem; margin-top: 2.1rem !important;
}

p, li { color: var(--ink); line-height: 1.62; }

/* ---- the figures are the typography ---------------------------------- */
.fig {
  font-family: 'IBM Plex Mono', monospace;
  font-variant-numeric: tabular-nums;
  font-size: 3.1rem; font-weight: 500; line-height: 1;
  letter-spacing: -0.03em; color: var(--ink);
}
.fig-label {
  font-size: .70rem; text-transform: uppercase; letter-spacing: .12em;
  color: var(--ink-faint); margin-bottom: .3rem;
}
.fig-note { font-size: .80rem; color: var(--ink-soft); margin-top: .35rem; }

/* Exposure is bounded, so it gets a track. */
.meter { height: 4px; background: var(--rule); margin-top: .7rem; position: relative; }
.meter > i { position: absolute; inset: 0 auto 0 0; background: var(--deep); display: block; }

/* Lag is unbounded, so it gets a span and deliberately NO track. */
.span-rule { display: flex; align-items: baseline; gap: .55rem; margin-top: .2rem; }
.span-rule .tick {
  font-family: 'IBM Plex Mono', monospace; font-variant-numeric: tabular-nums;
  font-size: 1.5rem; font-weight: 500; color: var(--ink);
}
.span-rule .mid { font-size: 1.05rem; color: var(--ink-soft); }
.span-rule .dash { flex: 0 0 26px; height: 1px; background: var(--ink-faint); }

/* ---- standing: a stamp, not a banner --------------------------------- */
.standing { border-left: 3px solid var(--rule); padding: .1rem 0 .1rem .85rem; margin: .2rem 0 1rem; }
.standing .tag {
  font-family: 'IBM Plex Mono', monospace;
  font-size: .70rem; font-weight: 600; text-transform: uppercase; letter-spacing: .13em;
}
.standing .body { font-size: .89rem; color: var(--ink-soft); margin-top: .3rem; line-height: 1.55; }
.standing.ok    { border-left-color: var(--ok); }
.standing.ok    .tag { color: var(--ok); }
.standing.warn  { border-left-color: var(--review); }
.standing.warn  .tag { color: var(--review); }
.standing.stop  { border-left-color: var(--stop); }
.standing.stop  .tag { color: var(--stop); }

/* ---- tables read as data, not as cards ------------------------------- */
[data-testid="stDataFrame"] { font-family: 'IBM Plex Mono', monospace; font-size: .80rem; }
[data-testid="stDataFrame"] div { border-radius: 0 !important; }

/* Streamlit's own metric, quietened and set in mono. */
[data-testid="stMetricValue"] {
  font-family: 'IBM Plex Mono', monospace; font-variant-numeric: tabular-nums;
  font-size: 1.45rem !important; font-weight: 500;
}
[data-testid="stMetricLabel"] {
  font-size: .70rem !important; text-transform: uppercase; letter-spacing: .10em;
  color: var(--ink-faint) !important;
}

/* Alerts: hairline-led, not filled slabs. */
[data-testid="stAlert"] {
  border-radius: 0; border-left: 3px solid var(--ink-faint);
  background: var(--panel); color: var(--ink);
}

button[kind="primary"] {
  border-radius: 2px !important; background: var(--deep) !important;
  border-color: var(--deep) !important; font-weight: 500;
}

/* Quality floor. */
*:focus-visible { outline: 2px solid var(--deep); outline-offset: 2px; }
@media (prefers-reduced-motion: reduce) { * { animation: none !important; transition: none !important; } }
@media (max-width: 640px) { .fig { font-size: 2.3rem; } .block-container { padding: 1.2rem 1rem; } }
</style>
"""
