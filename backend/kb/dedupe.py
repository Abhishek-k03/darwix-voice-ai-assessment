"""Duplicate handling with traceability: exact block-level dedupe (before chunking) and MinHash
near-duplicate merge (after chunking). The highest-authority copy is kept; the others go into also_found_in."""

from __future__ import annotations

import re

from datasketch import MinHash, MinHashLSH

from .schema import KBRecord, RawDoc, SourceRef

MIN_BLOCK_CHARS = 40
NEAR_DUP_JACCARD = 0.8


def _key(text: str) -> str:
    return re.sub(r"[^\w]+", " ", text.lower()).strip()


def _rank(doc: RawDoc) -> tuple:
    return (-doc.authority, "" if not doc.effective_date else "".join(chr(255 - ord(c)) for c in doc.effective_date))


def dedupe_blocks(docs: list[RawDoc]) -> int:
    """Removes paragraph-level exact duplicates across active docs of the same market."""
    seen: dict[tuple[str, str], tuple] = {}
    removed = 0
    for doc in sorted((d for d in docs if d.status == "active"), key=_rank):
        kept = []
        for b in doc.blocks:
            if b.kind == "heading" or len(b.text) < MIN_BLOCK_CHARS:
                kept.append(b)
                continue
            k = (doc.market, _key(b.text))
            if k in seen:
                first = seen[k][0]
                first.also_found_in.append(SourceRef(source_id=doc.source_id, type=doc.type, uri=doc.uri,
                                                     page=b.page, retrieved_at=doc.retrieved_at))
                removed += 1
                continue
            seen[k] = (b, doc)
            kept.append(b)
        doc.blocks = kept
    return removed


def _minhash(text: str, num_perm: int = 128) -> MinHash:
    words = _key(text).split()
    shingles = {" ".join(words[i:i + 3]) for i in range(max(1, len(words) - 2))}
    m = MinHash(num_perm=num_perm)
    for s in shingles:
        m.update(s.encode("utf-8"))
    return m


def near_dedupe(records: list[KBRecord], threshold: float = NEAR_DUP_JACCARD) -> tuple[list[KBRecord], list[tuple[KBRecord, KBRecord]]]:
    """Merges near-duplicate active records within a market. Returns (kept, [(dropped, kept_into)])."""
    kept: list[KBRecord] = []
    merged: list[tuple[KBRecord, KBRecord]] = []
    lsh: dict[str, MinHashLSH] = {}
    hashes: dict[str, MinHash] = {}
    by_key: dict[str, KBRecord] = {}
    ordered = sorted(records, key=lambda r: (r.status != "active", -r.authority, -len(r.content)))
    for r in ordered:
        if r.status != "active" or r.doc_type in ("premium_table", "qualification_rule"):
            kept.append(r)
            continue
        index = lsh.setdefault(r.market, MinHashLSH(threshold=threshold, num_perm=128))
        mh = _minhash(r.content)
        dup_of = None
        for cand in index.query(mh):
            if hashes[cand].jaccard(mh) >= threshold:
                dup_of = by_key[cand]
                break
        if dup_of:
            dup_of.also_found_in.append(r.source)
            dup_of.also_found_in.extend(r.also_found_in)
            merged.append((r, dup_of))
            continue
        key = f"{len(hashes)}"
        index.insert(key, mh)
        hashes[key] = mh
        by_key[key] = r
        kept.append(r)
    return kept, merged
