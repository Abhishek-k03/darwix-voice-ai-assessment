"""Normalization: terminology, dates (ISO 8601), headings, form fields, taxonomy and product tagging."""

from __future__ import annotations

import re
from datetime import date

from .schema import Issue, RawDoc

MONTHS = {
    # en
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    # id
    "januari": 1, "februari": 2, "maret": 3, "mei": 5, "juni": 6, "juli": 7, "agustus": 8,
    "oktober": 10, "desember": 12,
    # tl
    "enero": 1, "pebrero": 2, "marso": 3, "abril": 4, "mayo": 5, "hunyo": 6, "hulyo": 7, "agosto": 8,
    "setyembre": 9, "oktubre": 10, "nobyembre": 11, "disyembre": 12,
}
_MONTH_ALT = "|".join(sorted(MONTHS, key=len, reverse=True))
_D_MONTH_Y = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)? ({_MONTH_ALT}),? (\d{{4}})\b", re.I)
_MONTH_D_Y = re.compile(rf"\b({_MONTH_ALT}) (\d{{1,2}}),? (\d{{4}})\b", re.I)
_DMY_SLASH = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")


class Normalizer:
    def __init__(self, cfg: dict, taxonomy: dict) -> None:
        self.cfg = cfg
        self.taxonomy = taxonomy
        self._term_res: dict[str, list[tuple[re.Pattern, str, str]]] = {}
        for market, terms in cfg.get("terminology", {}).items():
            pairs = [(v, canon) for canon, variants in terms.items() for v in variants]
            pairs.sort(key=lambda p: len(p[0]), reverse=True)
            compiled = []
            for variant, canon in pairs:
                flags = 0 if variant.isupper() else re.I
                compiled.append((re.compile(rf"(?<![\w-]){re.escape(variant)}(?![\w-])", flags), canon, variant))
            self._term_res[market] = compiled
        self._form_res = [(name, re.compile(rf"^\s*(?:{'|'.join(pats)})\b", re.I))
                          for name, pats in cfg.get("form_fields", {}).items()]

    # ── terminology ──
    def terminology(self, text: str, market: str) -> tuple[str, set[str]]:
        hits: set[str] = set()
        for rx, canon, variant in self._term_res.get(market, []):
            def _sub(m: re.Match, _c=canon) -> str:
                return _c[0].upper() + _c[1:] if m.group(0)[0].isupper() and not m.group(0).isupper() else _c
            text, n = rx.subn(_sub, text)
            if n:
                hits.add(variant)
        text = re.sub(r"\b([\w\- ]{3,40}) \(\1\)", r"\1", text, flags=re.I)
        return text, hits

    # ── dates ──
    def dates(self, text: str) -> tuple[str, list[str]]:
        invalid: list[str] = []

        def _iso(y: int, m: int, d: int, raw: str) -> str:
            try:
                return date(y, m, d).isoformat()
            except ValueError:
                invalid.append(raw)
                return raw

        text = _D_MONTH_Y.sub(lambda m: _iso(int(m[3]), MONTHS[m[2].lower()], int(m[1]), m[0]), text)
        text = _MONTH_D_Y.sub(lambda m: _iso(int(m[3]), MONTHS[m[1].lower()], int(m[2]), m[0]), text)
        text = _DMY_SLASH.sub(lambda m: _iso(int(m[3]), int(m[2]), int(m[1]), m[0]), text)
        return text, invalid

    # ── headings ──
    def heading(self, text: str) -> str:
        t = re.sub(r"^\s*\d+(\.\d+)*\.?\s+", "", text).strip().rstrip(":")
        mapped = self.cfg.get("headings", {}).get(t.lower())
        if mapped:
            return mapped
        if t.isupper():
            t = t.title()
        return t[:1].upper() + t[1:]

    # ── form fields ──
    def form_field(self, label: str) -> str | None:
        for name, rx in self._form_res:
            if rx.search(label):
                return name
        return None

    # ── taxonomy / product ──
    def categorize(self, title: str, content: str, doc_type: str) -> str:
        if doc_type in self.taxonomy.get("fixed_doc_types", []):
            return self.taxonomy["doc_type_default_category"][doc_type]
        t, c = title.lower(), content.lower()
        best, best_score = None, 0
        for cat, kws in self.taxonomy["categories"].items():
            score = sum(3 * t.count(k) + c.count(k) for k in kws)
            if score > best_score:
                best, best_score = cat, score
        return best or self.taxonomy["doc_type_default_category"].get(doc_type, "product_overview")

    def product(self, title: str, content: str, market: str) -> str | None:
        t = f"{title} {content}".lower()
        for prod, kws in self.cfg.get("products", {}).get(market, {}).items():
            if any(k in t for k in kws):
                return prod
        return None

    def normalize_doc(self, doc: RawDoc) -> tuple[list[Issue], set[str]]:
        issues: list[Issue] = []
        aliases: set[str] = set()
        for b in doc.blocks:
            if b.kind == "heading":
                b.text = self.heading(b.text)
            b.text, hits = self.terminology(b.text, doc.market)
            aliases |= hits
            b.text, bad = self.dates(b.text)
            for raw in bad:
                issues.append(Issue(kind="source_error", source_id=doc.source_id, uri=doc.uri,
                                    detail=f"invalid date '{raw}' left unchanged"))
            if b.cells:
                b.cells = {k: self.dates(self.terminology(v, doc.market)[0])[0] for k, v in b.cells.items()}
        doc.title = self.dates(self.terminology(self.heading(doc.title), doc.market)[0])[0]
        return issues, aliases
