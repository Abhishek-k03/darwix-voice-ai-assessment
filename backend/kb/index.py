"""Stable record IDs, record versioning, KB semver, changelog, and the Chroma vector index."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import chromadb
from chromadb.config import Settings

from . import embeddings
from .schema import KBRecord

DOC_TYPE_SLUG = {"premium_table": "rates", "qualification_rule": "rule", "policy_rule": "policy",
                 "product_info": "product", "form_field": "form"}
MARKET_SLUG = {"in_health": "in", "ph_life": "ph", "id_multifinance": "id"}


def content_hash(r: KBRecord) -> str:
    return hashlib.sha256(f"{r.title}\n{r.content}".encode("utf-8")).hexdigest()[:16]


def _bump(version: str, part: str) -> str:
    major, minor, patch = (int(x) for x in version.split("."))
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def assign_ids(records: list[KBRecord], prev: dict | None) -> tuple[dict, dict]:
    """Reuses record_ids for known stable keys, bumps record version on content change,
    and derives the KB version (minor: records added/removed, patch: content updated)."""
    prev = prev or {}
    prev_recs: dict = prev.get("records", {})
    counters: dict = dict(prev.get("counters", {}))
    added, updated = [], []
    new_recs = {}
    for r in sorted(records, key=lambda x: x.stable_key):
        r.content_hash = content_hash(r)
        old = prev_recs.get(r.stable_key)
        if old:
            r.record_id = old["record_id"]
            if old["content_hash"] != r.content_hash:
                maj, mnr = old["version"].split(".")
                r.version = f"{maj}.{int(mnr) + 1}"
                updated.append(r.record_id)
            else:
                r.version = old["version"]
        else:
            prefix = f"kb_{MARKET_SLUG.get(r.market, r.market)}_{DOC_TYPE_SLUG.get(r.doc_type, r.doc_type)}"
            counters[prefix] = counters.get(prefix, 0) + 1
            r.record_id = f"{prefix}_{counters[prefix]:03d}"
            added.append(r.record_id)
        new_recs[r.stable_key] = {"record_id": r.record_id, "content_hash": r.content_hash, "version": r.version}
    removed = [v["record_id"] for k, v in prev_recs.items() if k not in new_recs]
    if not prev:
        kb_version = "1.0.0"
    elif added or removed:
        kb_version = _bump(prev["kb_version"], "minor")
    elif updated:
        kb_version = _bump(prev["kb_version"], "patch")
    else:
        kb_version = prev["kb_version"]
    for r in records:
        r.kb_version = kb_version
    manifest = {"kb_version": kb_version, "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "embedding_model": embeddings.MODEL, "records": new_recs, "counters": counters}
    change = {"kb_version": kb_version, "built_at": manifest["built_at"], "initial": not prev,
              "added": added, "updated": updated, "removed": removed}
    return manifest, change


def collection_name(kb_version: str) -> str:
    return f"kb-{kb_version}"


def client(index_dir: Path) -> chromadb.ClientAPI:
    return chromadb.PersistentClient(path=str(index_dir), settings=Settings(anonymized_telemetry=False))


def write_index(records: list[KBRecord], kb_version: str, index_dir: Path) -> str:
    active = [r for r in records if r.status == "active"]
    cl = client(index_dir)
    name = collection_name(kb_version)
    try:
        cl.delete_collection(name)
    except Exception:
        pass
    col = cl.create_collection(name=name, configuration={"hnsw": {"space": "cosine"}})
    vectors = embeddings.embed_passages([f"{r.title}\n{r.content}" for r in active])
    col.add(
        ids=[r.record_id for r in active],
        embeddings=vectors.tolist(),
        documents=[r.content for r in active],
        metadatas=[{"market": r.market, "doc_type": r.doc_type, "category": r.category, "title": r.title,
                    "authority": r.authority, "needs_review": r.needs_review, "product": r.product or "",
                    "kb_version": kb_version} for r in active],
    )
    return name


def write_jsonl(path: Path, records: list[KBRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in sorted(records, key=lambda x: x.record_id):
            f.write(json.dumps(r.model_dump(mode="json"), ensure_ascii=False) + "\n")
