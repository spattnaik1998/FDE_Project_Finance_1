"""Download the declared document sources into data/docs/."""
from __future__ import annotations
import json, logging, sys
sys.path.insert(0, "src")
from pathlib import Path
from documents.registry import SOURCES, download
from config import PROJECT_ROOT

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
                    datefmt="%H:%M:%S")
LOG = logging.getLogger("fetch_documents")
DOCS_DIR = PROJECT_ROOT / "data" / "docs"


def main() -> None:
    records, failures = [], []
    for source in SOURCES:
        try:
            doc = download(source, DOCS_DIR)
            records.append(doc)
        except Exception as exc:
            LOG.error("doc=%s status=failed error=%s", source.doc_id, str(exc)[:200])
            failures.append((source.doc_id, str(exc)[:200]))

    out = DOCS_DIR / "_documents.json"
    out.write_text(json.dumps([json.loads(r.model_dump_json()) for r in records],
                              indent=2), encoding="utf-8")

    print(f"\n{'='*82}\nDOCUMENTS: {len(records)}/{len(SOURCES)} retrieved\n{'='*82}")
    for r in records:
        print(f"  {r.doc_id:38s} {r.format.value:8s} {r.bytes:>10,} B  {r.sha256[:12]}")
    if failures:
        print(f"\nFailed ({len(failures)}):")
        for d, e in failures:
            print(f"  {d:38s} {e[:110]}")
    print(f"\nManifest: {out}")


if __name__ == "__main__":
    main()
