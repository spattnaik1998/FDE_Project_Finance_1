"""Generate the customer-facing report for a persisted run.

    python scripts/generate_report.py                 # latest run with a verdict
    python scripts/generate_report.py --run-id <uuid>
    python scripts/generate_report.py --out report.md

The traceability walk runs on every generation and its result is printed. A
report whose walk is incomplete is still written -- refusing to write it would
hide the break -- but the exit code is non-zero and the failure is named, so a
pipeline cannot ship it by accident.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, "src")

from report import provenance, reader, render

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
                    datefmt="%H:%M:%S")
LOG = logging.getLogger("generate_report")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--soc", default=None,
                        help="Pick the latest run for this occupation")
    parser.add_argument("--out", default=None, help="Write the markdown here")
    parser.add_argument("--quiet", action="store_true",
                        help="Print the trace summary only, not the document")
    args = parser.parse_args()

    run_id = args.run_id or reader.latest_run_id(soc_code=args.soc)
    if run_id is None:
        print("No run with a persisted verdict was found.")
        return 1

    data = reader.load_run(run_id)
    markdown, figures = render.render(data)
    trace = provenance.walk(markdown, figures, data)

    if args.out:
        Path(args.out).write_text(markdown, encoding="utf-8")
        print(f"\nWrote {args.out} ({len(markdown):,} chars)")

    if not args.quiet:
        print("\n" + markdown)

    summary = trace.summary()
    print(f"\n{'=' * 78}")
    print("TRACEABILITY WALK")
    print(f"{'=' * 78}")
    print(f"  run                  {data.run_id}")
    print(f"  status               {data.status}")
    print(f"  figures traced       {summary['figures_traced']}")
    print(f"  chain complete       {summary['complete']}")
    print(f"  customer deliverable {summary['customer_deliverable']}")
    print(f"  unregistered         {summary['unregistered']}")
    print(f"  unbound              {summary['unbound']}")
    print(f"  unhashed             {summary['unhashed']}")
    print(f"  unverified mirrors   {summary['unverified_mirrors']}")

    if not trace.is_complete:
        print(f"\n  BROKEN: {trace.failure_detail()}")
        return 2
    if not trace.customer_deliverable:
        print("\n  Chain is complete, but an unverified mirror contributes. "
              "Spot-check before external use.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
