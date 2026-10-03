# LinkedIn draft: stress-testing brand viability with the Taste Labs API

I had already picked a palette for my task-exposure prototype the slow way: curl
two sites I trusted, read their CSS, and take what they agreed on. Boston
University and an IT firm called Red Key both turned out to be overwhelmingly
white, one red, text in a warm near-black rather than pure black. So that is what
I built. White `#FFFFFF`, ink `#1C1B1A`, one red `#CC0000` in exactly four places.

Then I got access to the Taste Labs Design API and used it to check whether I had
chosen the right register or just a register I liked.

Their `/search` endpoint takes a plain-language description of an aesthetic and
returns ranked brands from a curated corpus, each with a classified palette and
typography strategy. I described my own page and got five strong matches, all
tagged `editorial-print` and `institutional`, all light, all muted, all
serif-sans pairings. The New York Times came back as the exemplar of the style:
`#FFFFFF`, `#121212`, red `#D0021B`. I had landed within a few hex points of it
from two unrelated sites.

That felt good for about a minute, and then I remembered that a check which cannot
fail is not a check.

So I ran two more searches. One described the opposite register: dark developer
SaaS, acid green, gradient mesh, geometric sans only. One described a near miss:
consumer fintech, pastels, rounded, playful. Three queries, three completely
disjoint result sets, zero brand overlap. The dark one came back
`high-contrast-street` with acid `#B9FF00`. The fintech one came back
`approachable` with warm high-saturation palettes and expressive multi-font
pairings.

The corpus discriminates. Which means the first result was evidence about my
palette rather than an API being agreeable.

The whole exercise cost three fast searches.

What it does not tell me is whether the page is any good. It tells me the page is
legible as institutional finance research instead of as a consumer app or a
developer tool, which is a narrower claim and the one I actually needed. The
reason I bothered running the control is the same reason the prototype itself
reports a calibration gate rather than a single confidence number: an external
check you cannot see the workings of is worth exactly as much as your evidence
that it discriminates.

Next: their `/judge/brand-adherence` endpoint scores a page against a reference
brand and returns fixes with exact target values. That one needs a public URL, and
mine runs on loopback, so it waits for a static export.

---

**Shorter variant, if the above runs long for the feed:**

I picked my prototype's palette by reading two trusted sites' CSS and taking what
they agreed on: white, warm near-black, one red.

Then I used the Taste Labs Design API to test whether that was the right register
or just one I liked. Their `/search` takes a description of an aesthetic and
returns ranked brands with classified palettes. Mine came back as five strong
matches, all `editorial-print` and `institutional`, with the NYT as the exemplar
at `#FFFFFF` / `#121212` / red `#D0021B`. I was within a few hex points.

Then I remembered that a check which cannot fail is not a check, so I ran two
controls: dark developer SaaS, and playful consumer fintech. Three queries, three
disjoint result sets, zero overlap. The corpus discriminates, so the first result
was evidence rather than an API being agreeable.

Three fast searches. It does not tell me the page is good. It tells me the page
reads as institutional finance research and not as a consumer app, which is the
narrower claim I needed.
