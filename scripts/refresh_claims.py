"""Re-derive prose claims under a corrected extractor.

    python scripts/refresh_claims.py --dry-run
    python scripts/refresh_claims.py

Two of the 21 claims reaching the customer-facing provenance appendix were front
matter: a dedication line that matched `intangible_complement` because it
contains the word "intangibles", and a JEL code block running into an abstract
header. Both passed every filter the extractor had -- right length, topic term
present, reads as prose -- because none of them was about front matter.

This is a **re-derivation, not a new source version**. The PDFs are unchanged and
their digests still match; what changed is which sentences we consider claims. So
the old rows are demoted rather than deleted: a past run that cited one stays
resolvable, and `VW_CLAIM_EVIDENCE` shows only the current derivation.

Runs as `USR_FDE_LOAD`, which holds `UPDATE(is_current)` and nothing else. It can
mark a row superseded and cannot rewrite a quote -- which is the whole point of
the column-level grant, exercised here rather than only asserted in a test.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, "src")

from documents.adapters import pdf
from warehouse.session import Principal, connect

logging.basicConfig(level=logging.WARNING,
                    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
                    datefmt="%H:%M:%S")
LOG = logging.getLogger("refresh_claims")

SOURCES = {
    "brynjolfsson_productivity_j_curve": (
        "data/docs/brynjolfsson_productivity_j_curve.pdf", pdf.J_CURVE_TOPICS),
    "eloundou_gpts_are_gpts": (
        "data/docs/eloundou_gpts_are_gpts.pdf", pdf.ELOUNDOU_TOPICS),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--database", default=None)
    args = parser.parse_args()

    print(f"\n{'=' * 78}")
    print(f"CLAIM RE-DERIVATION  —  extractor {pdf.CLAIM_EXTRACTOR_VERSION}")
    print(f"{'=' * 78}")

    derived = {}
    for doc_id, (path, topics) in SOURCES.items():
        if not Path(path).exists():
            print(f"  MISSING {path}; skipping {doc_id}")
            continue
        claims = pdf.find_claims(path, topics, doc_id)
        derived[doc_id] = claims
        print(f"  {doc_id:36} {len(claims)} claims")

    if not derived:
        print("\n  No source documents found.")
        return 1

    with connect(Principal.LOAD, database=args.database) as conn:
        cursor = conn.cursor()

        for doc_id, claims in derived.items():
            current = cursor.execute("""
                SELECT COUNT(*) FROM core.extracted_claim
                WHERE source_doc_id = ? AND is_current = 1""", doc_id).fetchone()[0]
            print(f"\n  {doc_id}")
            print(f"    currently current : {current}")
            print(f"    newly derived     : {len(claims)}")

            if args.dry_run:
                continue

            # Demote first, so the view never shows two derivations at once.
            cursor.execute("""
                UPDATE core.extracted_claim SET is_current = 0
                WHERE source_doc_id = ? AND is_current = 1""", doc_id)
            demoted = cursor.rowcount

            inserted = skipped = 0
            for claim in claims:
                cursor.execute(
                    "SELECT COUNT(*) FROM core.extracted_claim WHERE claim_id = ?",
                    claim.claim_id)
                if cursor.fetchone()[0]:
                    # Same extractor version already loaded: leave it current.
                    cursor.execute("""
                        UPDATE core.extracted_claim SET is_current = 1
                        WHERE claim_id = ?""", claim.claim_id)
                    skipped += 1
                    continue
                cursor.execute("""
                    INSERT INTO core.extracted_claim
                        (claim_id, topic, quote, page, note, source_doc_id,
                         is_current)
                    VALUES (?, ?, ?, ?, ?, ?, 1)""",
                    claim.claim_id, claim.topic, claim.quote, claim.page,
                    claim.note, claim.source_doc_id)
                inserted += 1

            print(f"    demoted           : {demoted}")
            print(f"    inserted          : {inserted}")
            print(f"    already present   : {skipped}")

        if not args.dry_run:
            conn.commit()

    if args.dry_run:
        print("\n  dry run: nothing written")
        return 0

    with connect(Principal.LOAD, database=args.database) as conn:
        total = conn.cursor().execute("""
            SELECT COUNT(*) FROM core.extracted_claim WHERE is_current = 1
            """).fetchone()[0]
    print(f"\n  current claims now: {total}")
    print("  Superseded rows are demoted, not deleted: a run that cited one")
    print("  stays resolvable, and the view shows only this derivation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
