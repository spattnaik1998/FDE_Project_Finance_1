"""Source-document registration.

Under the append-only model (TDD B.0) ``ref.source_document`` is the version
registry: every artefact is an immutable snapshot identified by its SHA-256,
and a revised artefact becomes a *new* row rather than an update to the old
one. ``doc_id`` therefore carries version identity, which is why there is no
separate ``source_version`` column anywhere in the schema.

Two kinds of artefact are registered here:

1. Documents fetched by ``scripts/fetch_documents.py``, whose digests are
   already recorded in ``data/docs/_documents.json``.
2. API datasets landed by ``scripts/fetch_all.py`` as CSV, whose digests are
   computed here from the file on disk.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pyodbc

from warehouse.session import WarehouseError

LOG = logging.getLogger("warehouse.registry")

CHUNK = 1 << 16
API_PROVIDER_PREFIXES = {
    "bea_": "BEA", "bls_": "BLS", "census_": "CENSUS", "fred_": "FRED",
}


def sha256_of(path: Path) -> tuple[str, int]:
    """Digest a file without holding it in memory twice."""
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
            total += len(chunk)
    return digest.hexdigest(), total


def _upsert_document(cursor: pyodbc.Cursor, *, doc_id: str, title: str,
                     publisher: str, url: str, fmt: str, sha256: str,
                     size: int, retrieved_at: datetime,
                     provenance_note: str, is_mirror: bool) -> str:
    """Register one artefact version.

    Idempotency is keyed on the SHA-256, not on ``doc_id``: re-registering
    identical bytes is a no-op, while changed bytes are a new version and get
    a suffixed id. Returns the ``doc_id`` actually in force.
    """
    cursor.execute("SELECT doc_id FROM ref.source_document WHERE sha256 = ?", sha256)
    existing = cursor.fetchone()
    if existing:
        return existing[0]

    cursor.execute("SELECT COUNT(*) FROM ref.source_document WHERE doc_id = ?", doc_id)
    if cursor.fetchone()[0]:
        # Same logical source, different bytes: a revision. Version the id so
        # the prior row -- and any run bound to it -- remains resolvable.
        cursor.execute(
            "SELECT COUNT(*) FROM ref.source_document WHERE doc_id LIKE ?", f"{doc_id}@%")
        doc_id = f"{doc_id}@v{cursor.fetchone()[0] + 2}"
        LOG.info("doc=%s status=revision_detected new_version=%s", doc_id, sha256[:12])

    cursor.execute("""
        INSERT INTO ref.source_document
            (doc_id, title, publisher, url, format, sha256, bytes,
             retrieved_at, provenance_note, is_mirror)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        doc_id, title[:500], publisher[:300], url[:1000], fmt, sha256, size,
        retrieved_at, provenance_note or None, 1 if is_mirror else 0)
    return doc_id


def register_documents(cursor: pyodbc.Cursor, manifest_path: Path) -> dict[str, str]:
    """Register the fetched documents. Returns {original doc_id: effective id}."""
    if not manifest_path.exists():
        raise WarehouseError(f"Document manifest not found: {manifest_path}")

    records = json.loads(manifest_path.read_text(encoding="utf-8"))
    mapping: dict[str, str] = {}

    for rec in records:
        local = Path(rec["local_path"])
        if local.exists():
            sha256, size = sha256_of(local)
            if sha256 != rec["sha256"]:
                LOG.warning("doc=%s status=digest_drift manifest=%s disk=%s",
                            rec["doc_id"], rec["sha256"][:12], sha256[:12])
        else:
            sha256, size = rec["sha256"], rec.get("bytes") or 0

        note = rec.get("provenance_note") or ""
        mapping[rec["doc_id"]] = _upsert_document(
            cursor, doc_id=rec["doc_id"], title=rec["title"],
            publisher=rec["publisher"], url=rec["url"],
            fmt=str(rec["format"]).replace("DocumentFormat.", "").lower(),
            sha256=sha256, size=size,
            retrieved_at=datetime.fromisoformat(rec["retrieved_at"]),
            provenance_note=note, is_mirror="MIRROR" in note)

    LOG.info("source=documents status=ok registered=%s", len(mapping))
    return mapping


def register_api_datasets(cursor: pyodbc.Cursor, raw_dir: Path) -> dict[str, str]:
    """Register landed API CSVs as source documents.

    The API layer predates the warehouse and has no manifest of digests, so
    they are computed from disk. Without this, industry metrics would have no
    provenance and the foreign key would refuse them -- which is the intended
    behaviour, not an obstacle to work around.
    """
    manifest = raw_dir / "_manifest.csv"
    purposes: dict[str, str] = {}
    if manifest.exists():
        import csv
        with manifest.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                purposes[row["dataset"]] = row.get("purpose", "")

    mapping: dict[str, str] = {}
    for path in sorted(raw_dir.glob("*.csv")):
        if path.name.startswith("_"):
            continue
        stem = path.stem
        provider = next((v for k, v in API_PROVIDER_PREFIXES.items()
                         if stem.startswith(k)), "CENSUS")
        sha256, size = sha256_of(path)
        mapping[stem] = _upsert_document(
            cursor, doc_id=stem,
            title=purposes.get(stem) or stem.replace("_", " "),
            publisher=f"{provider} (US federal statistical agency)",
            url=f"file://data/raw/{path.name}", fmt="csv",
            sha256=sha256, size=size,
            retrieved_at=datetime.fromtimestamp(path.stat().st_mtime, timezone.utc),
            provenance_note="Landed by scripts/fetch_all.py; digest computed from disk.",
            is_mirror=False)

    LOG.info("source=api_datasets status=ok registered=%s", len(mapping))
    return mapping
