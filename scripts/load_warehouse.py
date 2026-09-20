"""Load the landing zone and typed corpus into SQL Server.

Idempotent: re-running loads nothing new when the source bytes are unchanged.
Runs the blocking quality assertions afterwards and fails loudly if any trip.
"""
from __future__ import annotations
import logging, sys
sys.path.insert(0, "src")
from pathlib import Path

from config import DATA_INTERIM, DATA_RAW, PROJECT_ROOT
from warehouse import loaders, quality, registry
from warehouse.session import Principal, connect

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
                    datefmt="%H:%M:%S")
LOG = logging.getLogger("load_warehouse")

DOCS_DIR = PROJECT_ROOT / "data" / "docs"


def main() -> None:
    with connect(Principal.LOAD) as conn:
        cur = conn.cursor()

        doc_map = registry.register_documents(cur, DOCS_DIR / "_documents.json")
        doc_map |= registry.register_api_datasets(cur, DATA_RAW)

        results = loaders.load_corpus(cur, DATA_INTERIM / "corpus.json", doc_map)
        results.append(loaders.load_industry_metrics(cur, DATA_RAW, doc_map))

        checks = quality.run_assertions(cur)

    print(f"\n{'='*74}\nLOAD COMPLETE\n{'='*74}")
    print(f"  {'table':30s} {'inserted':>9} {'skipped':>9} {'demoted':>9}")
    for r in results:
        print(f"  {r.table:30s} {r.inserted:>9} {r.skipped_existing:>9} {r.demoted:>9}")

    print(f"\n  quality assertions: {sum(1 for _, ok, _ in checks if ok)}/{len(checks)} passed")
    for name, ok, count in checks:
        if not ok:
            print(f"    FAILED {name}: {count}")

    quality.enforce(checks)
    print("\n  All blocking assertions passed.")


if __name__ == "__main__":
    main()
