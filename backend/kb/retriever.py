"""Hybrid retrieval: metadata filter -> dense (e5 + Chroma) + BM25 -> RRF fusion -> optional rerank
-> no-match gate -> citations. Records flagged needs_review (lost a source conflict) are demoted."""

from __future__ import annotations

import json
import math
import os
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import embeddings
from .index import client, collection_name
from .normalize import Normalizer
from .schema import KBRecord

KB_DIR = Path(os.getenv("KB_DIR", Path(__file__).resolve().parents[2] / "data" / "kb"))
RRF_K = 60
CANDIDATES = 20
REVIEW_PENALTY = 0.5
# No-match gate on the top hit: dense cosine and IDF-weighted lexical coverage
# (calibrated on kb/eval_queries.yaml; see docs/q2_kb_design.md)
DENSE_STRONG = float(os.getenv("KB_DENSE_STRONG", "0.845"))
DENSE_MIN = float(os.getenv("KB_DENSE_MIN", "0.79"))
COVERAGE_MIN = float(os.getenv("KB_COVERAGE_MIN", "0.30"))

_TOKEN = re.compile(r"\w+", re.UNICODE)
STOPWORDS = set("""a an the is are was were be been of to in on at for and or but if then than with by from as it its this that these
those what which who whom how when where why can could do does did my your our their i you we they me us them about into over under
will would should may might must not no yes there here also just only very so too any some all much many more most per vs please
ang ng sa mga na po ko mo ba ito iyan yung kung kasi para may wala hindi oo ako ikaw siya kami tayo sila nga lang din rin pa
pwede puwede kong bang saan ilang bago naman talaga ano paano kailan ngayon dito diyan niya nila natin
yang dan di ke dari untuk dengan atau tidak ya itu ini saya anda kami kita mereka apa bagaimana berapa kapan kalau kok sih deh dong aja
nya adalah akan sudah belum bisa ada kena nggak gak lewat bolehkah boleh apakah gimana mau udah""".split())
DOC_TYPE_PRIOR = {"testimonial": 0.8, "marketing": 0.9, "reference": 0.85}


_ID_PREFIX = re.compile(r"^(meng|meny|mem|men|me|peng|peny|pem|pen|pe|ber|ter|di|ke|se)")
_ID_SUFFIX = re.compile(r"(nya|lah|kah|kan|an)$")


def _stem_id(tok: str) -> str:
    """Light Indonesian affix stripping (menagih/penagihan -> nagih) for lexical recall."""
    if len(tok) < 6:
        return tok
    t = _ID_SUFFIX.sub("", tok)
    t = _ID_PREFIX.sub("", t) if len(t) >= 6 else t
    return t if len(t) >= 3 else tok


def tokenize(text: str, market: str | None = None) -> list[str]:
    toks = [t for t in _TOKEN.findall(text.lower()) if t not in STOPWORDS and len(t) > 1]
    return [_stem_id(t) for t in toks] if market == "id_multifinance" else toks


_AGE = re.compile(r"\b(\d{2})\s*(?:-|\s)?(?:years?|yrs?|yo|year-old|tahun|taon|anyos)\b", re.I)
_BAND = re.compile(r"age band (\d{2})-(\d{2})")
PRODUCT_TERMS = {
    "Prithvi Silver": ("senior", "silver", "parents above"),
    "Prithvi FamilyShield": ("family", "floater", "spouse", "wife", "husband", "children", "kids"),
    "Prithvi Secure": ("individual", "myself", "single", "only me"),
}


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.docs = [Counter(d) for d in docs]
        self.lens = [len(d) for d in docs]
        self.avg = sum(self.lens) / max(1, len(self.lens))
        df = Counter(t for d in docs for t in set(d))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        # unseen query words are mostly colloquial/function words: median weight, not maximum
        self.unseen_idf = sorted(self.idf.values())[len(self.idf) // 2] if self.idf else 1.0

    def weighted_coverage(self, query: list[str], doc_tokens: set[str]) -> float:
        """Share of the query's information (IDF mass) present in the doc — informative terms dominate."""
        q = set(query)
        total = sum(self.idf.get(t, self.unseen_idf) for t in q)
        return sum(self.idf.get(t, self.unseen_idf) for t in q & doc_tokens) / total if total else 0.0

    def scores(self, query: list[str]) -> list[float]:
        out = []
        for tf, ln in zip(self.docs, self.lens):
            s = 0.0
            for t in query:
                if t in tf:
                    f = tf[t]
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * ln / self.avg))
            out.append(s)
        return out


@dataclass
class Hit:
    record: KBRecord
    score: float
    dense: float
    bm25: float
    coverage: float
    matched_terms: list[str]
    rerank: float | None = None

    def to_dict(self) -> dict:
        r = self.record
        return {"record_id": r.record_id, "title": r.title, "content": r.content, "category": r.category,
                "doc_type": r.doc_type, "product": r.product, "source": r.source.model_dump(), "citation": r.citation(),
                "version": r.version, "effective_date": r.effective_date, "needs_review": r.needs_review,
                "conflicts": r.conflicts, "score": round(self.score, 4), "dense": round(self.dense, 4),
                "bm25": round(self.bm25, 3), "coverage": round(self.coverage, 2), "matched_terms": self.matched_terms,
                "rerank": None if self.rerank is None else round(self.rerank, 3)}


@dataclass
class SearchResult:
    query: str
    market: str
    status: str
    hits: list[Hit] = field(default_factory=list)
    latency_ms: float = 0.0
    kb_version: str = ""

    def to_dict(self) -> dict:
        return {"query": self.query, "market": self.market, "status": self.status, "kb_version": self.kb_version,
                "latency_ms": round(self.latency_ms, 1), "hits": [h.to_dict() for h in self.hits]}

    def for_llm(self, max_hits: int = 3) -> str:
        """Compact grounding block for the voice agent; never invents content when nothing matched."""
        if self.status != "ok":
            return "NO_RELEVANT_INFO: the knowledge base has no information on this. Say so and offer a callback."
        parts = []
        for h in self.hits[:max_hits]:
            note = ""
            if h.record.needs_review and h.record.conflicts:
                c = h.record.conflicts[0]
                note = f" (OUTDATED on {c['fact']}: use {c['authoritative_record']})"
            parts.append(f"[{h.record.record_id}] {h.record.title}{note}\n{h.record.content}")
        return "\n\n".join(parts)


class Retriever:
    def __init__(self, kb_dir: Path = KB_DIR, rerank: bool | None = None) -> None:
        manifest = json.loads((kb_dir / "manifest.json").read_text(encoding="utf-8"))
        self.kb_version = manifest["kb_version"]
        records = [KBRecord(**json.loads(line)) for line in (kb_dir / "records.jsonl").read_text(encoding="utf-8").splitlines() if line]
        self.records = [r for r in records if r.status == "active"]
        self.by_id = {r.record_id: r for r in self.records}
        self._col = client(kb_dir / "index").get_collection(collection_name(self.kb_version))
        self._bm25: dict[str, tuple[BM25, list[KBRecord]]] = {}
        self._toks: dict[str, set[str]] = {}
        for market in {r.market for r in self.records}:
            recs = [r for r in self.records if r.market == market]
            docs = [tokenize(self._lexical(r), market) for r in recs]
            self._bm25[market] = (BM25(docs), recs)
            self._toks.update({r.record_id: set(d) for r, d in zip(recs, docs)})
        cfg_dir = Path(__file__).parent / "config"
        norm_cfg = yaml.safe_load((cfg_dir / "normalization.yaml").read_text(encoding="utf-8"))
        self._norm = Normalizer(norm_cfg, yaml.safe_load((cfg_dir / "taxonomy.yaml").read_text(encoding="utf-8")))
        self._synonyms: dict[str, list[str]] = norm_cfg.get("query_synonyms", {})
        self._rerank = rerank if rerank is not None else os.getenv("KB_RERANK", "false").lower() == "true"
        self._reranker = None
        embeddings.warmup()

    @staticmethod
    def _lexical(r: KBRecord) -> str:
        return f"{r.title} {r.content} {' '.join(r.tags)} {r.product or ''}"

    def normalize_query(self, query: str, market: str) -> str:
        """Same terminology normalization as the KB (cicilan -> angsuran, PED -> pre-existing condition)
        plus domain synonym expansion (mother -> parents)."""
        q, _ = self._norm.terminology(query, market)
        low = q.lower()
        extra = [canon for canon, variants in self._synonyms.items()
                 if any(re.search(rf"\b{re.escape(v)}\b", low) for v in variants) and canon not in low]
        return f"{q} {' '.join(extra)}".strip()

    def search(self, query: str, market: str, k: int = 4, doc_types: list[str] | None = None) -> SearchResult:
        t0 = time.perf_counter()
        raw_query, query = query, self.normalize_query(query, market)
        where: dict = {"market": market}
        if doc_types:
            where = {"$and": [{"market": market}, {"doc_type": {"$in": doc_types}}]}
        qv = embeddings.embed_query(query)
        res = self._col.query(query_embeddings=[qv.tolist()], n_results=CANDIDATES, where=where)
        dense = {rid: 1 - dist for rid, dist in zip(res["ids"][0], res["distances"][0])}

        bm, recs = self._bm25.get(market, (None, []))
        qtok = tokenize(query, market)
        bm_scores = {}
        if bm and qtok:
            for r, s in zip(recs, bm.scores(qtok)):
                if s > 0 and (not doc_types or r.doc_type in doc_types):
                    bm_scores[r.record_id] = s
        dense_rank = {rid: i for i, rid in enumerate(sorted(dense, key=dense.get, reverse=True))}
        bm_rank = {rid: i for i, rid in enumerate(sorted(bm_scores, key=bm_scores.get, reverse=True)[:CANDIDATES])}

        ql = query.lower()
        age = next((int(m) for m in _AGE.findall(query)), None)
        products = {p for p, terms in PRODUCT_TERMS.items() if any(t in ql for t in terms)}
        hits = []
        qset = set(qtok)
        for rid in set(dense_rank) | set(bm_rank):
            r = self.by_id.get(rid)
            if r is None:
                continue
            score = sum(1 / (RRF_K + rank[rid] + 1) for rank in (dense_rank, bm_rank) if rid in rank)
            toks = self._toks.get(rid, set())
            wcov = bm.weighted_coverage(qtok, toks) if bm else 0.0
            score *= (0.7 + 0.6 * wcov) * DOC_TYPE_PRIOR.get(r.doc_type, 1.0)
            if r.product and r.product in products:
                score *= 1.3
            band = _BAND.search(r.title)
            if age is not None and band and int(band[1]) <= age <= int(band[2]):
                score *= 1.3
            if r.needs_review:
                score *= REVIEW_PENALTY
            hits.append(Hit(record=r, score=score, dense=dense.get(rid, 0.0), bm25=bm_scores.get(rid, 0.0),
                            coverage=wcov, matched_terms=sorted(qset & toks)))
        hits.sort(key=lambda h: h.score, reverse=True)
        if self._rerank and hits:
            hits = self._apply_rerank(query, hits[:10])
        status = "ok" if hits and self._relevant(hits[0]) else "no_match"
        return SearchResult(query=raw_query, market=market, status=status, hits=hits[:k] if status == "ok" else hits[:1],
                            latency_ms=(time.perf_counter() - t0) * 1000, kb_version=self.kb_version)

    @staticmethod
    def _relevant(h: Hit) -> bool:
        if h.rerank is not None:
            return h.rerank > 0.0
        return h.dense >= DENSE_MIN and (h.dense >= DENSE_STRONG or h.coverage >= COVERAGE_MIN)

    def _apply_rerank(self, query: str, hits: list[Hit]) -> list[Hit]:
        if self._reranker is None:
            from fastembed.rerank.cross_encoder import TextCrossEncoder
            self._reranker = TextCrossEncoder("jinaai/jina-reranker-v2-base-multilingual",
                                              cache_dir=str(embeddings.CACHE_DIR))
        scores = list(self._reranker.rerank(query, [f"{h.record.title}\n{h.record.content}" for h in hits]))
        for h, s in zip(hits, scores):
            h.rerank = float(s) - (2.0 if h.record.needs_review else 0.0)
        return sorted(hits, key=lambda h: h.rerank, reverse=True)
