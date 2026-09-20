"""Source registration: content-addressed, immutable, version-aware.

``ref.source_document`` is the version registry. Under append-only,
``doc_id`` *is* the version identity and the SHA-256 proves the content — which
is why there is no ``source_version`` column anywhere. These tests hold that
line.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import pytest

from warehouse import registry


def _write(tmp_path, name: str, content: bytes):
    path = tmp_path / name
    path.write_bytes(content)
    return path


def _manifest(tmp_path, records: list[dict]):
    path = tmp_path / "_documents.json"
    path.write_text(json.dumps(records), encoding="utf-8")
    return path


def _record(doc_id: str, path, sha: str, note: str = "") -> dict:
    return {"doc_id": doc_id, "title": f"Title for {doc_id}", "publisher": "Test",
            "url": "http://example.test", "format": "pdf",
            "local_path": str(path), "sha256": sha, "bytes": path.stat().st_size,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "provenance_note": note}


# --- Digests ----------------------------------------------------------------

def test_sha256_matches_hashlib(tmp_path):
    path = _write(tmp_path, "a.bin", b"the quick brown fox")
    digest, size = registry.sha256_of(path)
    assert digest == hashlib.sha256(b"the quick brown fox").hexdigest()
    assert size == 19


def test_sha256_differs_after_a_one_byte_change(tmp_path):
    a = _write(tmp_path, "a.bin", b"payload-v1")
    b = _write(tmp_path, "b.bin", b"payload-v2")
    assert registry.sha256_of(a)[0] != registry.sha256_of(b)[0]


# --- Registration -----------------------------------------------------------

def test_document_is_registered_with_its_digest(cur, tmp_path):
    path = _write(tmp_path, "doc.pdf", b"contents")
    sha = hashlib.sha256(b"contents").hexdigest()
    mapping = registry.register_documents(cur, _manifest(tmp_path, [_record("d1", path, sha)]))

    assert mapping == {"d1": "d1"}
    stored = cur.execute(
        "SELECT sha256, bytes FROM ref.source_document WHERE doc_id = 'd1'").fetchone()
    assert stored[0] == sha
    assert stored[1] == 8


def test_registering_identical_bytes_twice_is_a_noop(cur, tmp_path):
    path = _write(tmp_path, "doc.pdf", b"contents")
    sha = hashlib.sha256(b"contents").hexdigest()
    manifest = _manifest(tmp_path, [_record("d1", path, sha)])

    registry.register_documents(cur, manifest)
    registry.register_documents(cur, manifest)

    assert cur.execute("SELECT COUNT(*) FROM ref.source_document").fetchone()[0] == 1


def test_revised_bytes_create_a_new_version_rather_than_overwriting(cur, tmp_path):
    """The requirement the architecture review turned on."""
    path = _write(tmp_path, "doc.pdf", b"original")
    sha_v1 = hashlib.sha256(b"original").hexdigest()
    registry.register_documents(cur, _manifest(tmp_path, [_record("d1", path, sha_v1)]))

    path.write_bytes(b"revised")
    sha_v2 = hashlib.sha256(b"revised").hexdigest()
    mapping = registry.register_documents(cur, _manifest(tmp_path, [_record("d1", path, sha_v2)]))

    assert mapping["d1"] != "d1", "a revision must get its own version id"
    rows = cur.execute(
        "SELECT doc_id, sha256 FROM ref.source_document ORDER BY doc_id").fetchall()
    assert len(rows) == 2
    assert {r[1] for r in rows} == {sha_v1, sha_v2}
    assert any(r[0] == "d1" for r in rows), "the original version must remain resolvable"


def test_same_content_under_a_different_id_is_not_duplicated(cur, tmp_path):
    """Content addressing means identical bytes are one artefact."""
    path = _write(tmp_path, "doc.pdf", b"shared")
    sha = hashlib.sha256(b"shared").hexdigest()
    registry.register_documents(cur, _manifest(tmp_path, [_record("first", path, sha)]))
    mapping = registry.register_documents(cur, _manifest(tmp_path, [_record("second", path, sha)]))

    assert mapping["second"] == "first", "the digest, not the name, identifies the artefact"
    assert cur.execute("SELECT COUNT(*) FROM ref.source_document").fetchone()[0] == 1


def test_mirror_note_sets_the_mirror_flag(cur, tmp_path):
    path = _write(tmp_path, "doc.xlsx", b"mirrored")
    sha = hashlib.sha256(b"mirrored").hexdigest()
    registry.register_documents(
        cur, _manifest(tmp_path, [_record("m1", path, sha,
                                          note="MIRROR, not the publisher's own copy.")]))
    flag = cur.execute(
        "SELECT is_mirror FROM ref.source_document WHERE doc_id = 'm1'").fetchone()[0]
    assert flag is True or flag == 1


def test_non_mirror_document_is_not_flagged(cur, tmp_path):
    path = _write(tmp_path, "doc.pdf", b"direct")
    sha = hashlib.sha256(b"direct").hexdigest()
    registry.register_documents(cur, _manifest(tmp_path, [_record("p1", path, sha)]))
    flag = cur.execute(
        "SELECT is_mirror FROM ref.source_document WHERE doc_id = 'p1'").fetchone()[0]
    assert flag is False or flag == 0


def test_missing_manifest_raises_rather_than_loading_nothing(cur, tmp_path):
    from warehouse.session import WarehouseError
    with pytest.raises(WarehouseError):
        registry.register_documents(cur, tmp_path / "absent.json")


def test_digest_drift_is_detected_and_disk_wins(cur, tmp_path, caplog):
    """If the manifest and the file disagree, trust the bytes and say so."""
    path = _write(tmp_path, "doc.pdf", b"actual contents")
    stale = hashlib.sha256(b"what the manifest claims").hexdigest()
    registry.register_documents(cur, _manifest(tmp_path, [_record("d1", path, stale)]))

    stored = cur.execute(
        "SELECT sha256 FROM ref.source_document WHERE doc_id = 'd1'").fetchone()[0]
    assert stored == hashlib.sha256(b"actual contents").hexdigest()
    assert any("digest_drift" in r.message for r in caplog.records)


# --- API datasets -----------------------------------------------------------

def test_api_csvs_are_registered_with_their_provider(cur, tmp_path):
    (tmp_path / "fred_observations.csv").write_text("series_id,date,value\nX,2026-01-01,1\n")
    (tmp_path / "bea_value_added.csv").write_text("Industry,Year,DataValue\n52,2026,1\n")
    mapping = registry.register_api_datasets(cur, tmp_path)

    assert set(mapping) == {"fred_observations", "bea_value_added"}
    providers = dict(cur.execute(
        "SELECT doc_id, publisher FROM ref.source_document").fetchall())
    assert "FRED" in providers["fred_observations"]
    assert "BEA" in providers["bea_value_added"]


def test_manifest_underscore_files_are_not_registered_as_sources(cur, tmp_path):
    (tmp_path / "_manifest.csv").write_text("dataset,purpose\nx,y\n")
    (tmp_path / "fred_observations.csv").write_text("series_id,date,value\nX,2026-01-01,1\n")
    mapping = registry.register_api_datasets(cur, tmp_path)
    assert "_manifest" not in mapping
