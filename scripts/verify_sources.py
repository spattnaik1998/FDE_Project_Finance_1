"""Check mirrored sources against the publisher's own copy.

    python scripts/verify_sources.py --dry-run
    python scripts/verify_sources.py

Two of the 29 artefacts are mirrors: the Felten/Raj/Seamans AIOE files, taken
from a third-party reproducibility repository rather than the authors'. Their
provenance note says the values must be spot-checked before customer-facing
use, and `report.provenance` blocks `customer_deliverable` until they are.

This is what the content-addressed design was built for. A spot check of a few
values would show they *look* right; re-fetching the publisher's file and
comparing SHA-256 shows the bytes are **identical**, which is a strictly
stronger claim and needs no judgement about which values to sample.

The result is appended to ``audit.source_verification``, never written back
onto ``ref.source_document``. That row is immutable by design -- a snapshot
whose digest can be edited is not a snapshot -- and a verification is an event
with a time and an outcome that can be repeated, not a property of the
artefact. A publisher revision that breaks a previously passing check has to be
able to sit in the record next to the check it invalidates.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sys

import requests

sys.path.insert(0, "src")

from warehouse.session import Principal, connect

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
                    datefmt="%H:%M:%S")
LOG = logging.getLogger("verify_sources")

TIMEOUT = 60

# The publisher's own distribution for each mirrored artefact.
#
# github.com/AIOE-Data/AIOE is the authors' repository, not another
# third-party copy: its README carries the authors' own citation and their
# institutional contact addresses. That distinction is the whole point -- one
# GitHub URL is not automatically as good as another, and the reason to trust
# this one is authorship, not the hostname.
PUBLISHER_SOURCES = {
    "felten_aioe_language_modeling": (
        "https://raw.githubusercontent.com/AIOE-Data/AIOE/main/"
        "Language%20Modeling%20AIOE%20and%20AIIE.xlsx"),
    "felten_aioe_appendix": (
        "https://raw.githubusercontent.com/AIOE-Data/AIOE/main/"
        "AIOE_DataAppendix.xlsx"),
}

PUBLISHER_NOTE = (
    "Checked against the authors' own distribution at github.com/AIOE-Data/AIOE, "
    "whose README carries the Felten/Raj/Seamans citation and the authors' "
    "institutional contacts. SHA-256 of the publisher's file compared byte for "
    "byte against the stored digest."
)


def mirrors_needing_check(cursor) -> list[tuple[str, str, str]]:
    """Mirrors with no passing verification on record."""
    rows = cursor.execute("""
        SELECT d.doc_id, d.sha256, d.url
        FROM ref.source_document d
        WHERE d.is_mirror = 1
          AND d.verified_against_publisher = 0
          AND NOT EXISTS (SELECT 1 FROM audit.source_verification v
                          WHERE v.source_doc_id = d.doc_id AND v.matched = 1)
        ORDER BY d.doc_id""").fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--database", default=None)
    args = parser.parse_args()

    with connect(Principal.LOAD, database=args.database) as conn:
        cursor = conn.cursor()
        pending = mirrors_needing_check(cursor)

        print(f"\n{'=' * 78}")
        print("MIRROR VERIFICATION")
        print(f"{'=' * 78}")
        if not pending:
            print("  No mirror is awaiting verification.")
            return 0

        recorded = matched = 0
        for doc_id, stored_sha, mirror_url in pending:
            publisher_url = PUBLISHER_SOURCES.get(doc_id)
            if publisher_url is None:
                print(f"  {doc_id:34} SKIP  no publisher URL registered")
                continue

            try:
                response = requests.get(publisher_url, timeout=TIMEOUT)
                response.raise_for_status()
            except Exception as exc:                  # noqa: BLE001
                print(f"  {doc_id:34} FAIL  fetch: {type(exc).__name__}")
                continue

            publisher_sha = hashlib.sha256(response.content).hexdigest()
            is_match = publisher_sha == stored_sha

            print(f"  {doc_id}")
            print(f"    stored    {stored_sha}")
            print(f"    publisher {publisher_sha}")
            print(f"    {'MATCH — identical bytes' if is_match else 'MISMATCH — differs from the publisher'}")

            if args.dry_run:
                continue

            cursor.execute("""
                INSERT INTO audit.source_verification
                    (source_doc_id, method, publisher_url, publisher_sha256,
                     matched, note)
                VALUES (?, 'sha256_match', ?, ?, ?, ?)""",
                doc_id, publisher_url, publisher_sha,
                1 if is_match else 0,
                PUBLISHER_NOTE if is_match else
                "Publisher copy differs from the stored mirror. The stored "
                "digest is still what this warehouse holds and what past runs "
                "consumed; the difference must be explained before either is "
                "used for customer delivery.")
            recorded += 1
            matched += int(is_match)

        if not args.dry_run:
            conn.commit()
            print(f"\n  verifications recorded  {recorded}")
            print(f"  matched                 {matched}")
        else:
            print("\n  dry run: nothing written")

    print("\n  A mismatch is not corrected here. It is recorded, and the "
          "\n  difference has to be explained by a human before delivery.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
