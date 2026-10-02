"""Cleaning: running headers/footers, cross-page site boilerplate, glyph artifacts, whitespace."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter

from .schema import RawDoc

_DIGITS = re.compile(r"\d+")
_PAGE_MARK = re.compile(r"(\|\s*)?page \d+( of \d+)?\s*$", re.I)


def _line_key(line: str) -> str:
    return _DIGITS.sub("#", line.strip().lower())


def strip_running_lines(pages: list[list[str]]) -> tuple[list[list[str]], int]:
    """Removes per-page headers/footers: lines recurring on >=60% of pages (digits normalised so
    'Page 1'/'Page 2' match), page-number lines, and top-of-page lines built from ' | ' segments."""
    removed = 0
    freq: Counter = Counter()
    if len(pages) >= 2:
        for lines in pages:
            freq.update({_line_key(ln) for ln in lines})
    cutoff = max(2, int(0.6 * len(pages) + 0.999))
    out = []
    for lines in pages:
        kept = []
        for i, ln in enumerate(lines):
            running = len(pages) >= 2 and freq[_line_key(ln)] >= cutoff
            page_mark = bool(_PAGE_MARK.search(ln))
            header_like = i < 2 and ln.count(" | ") >= 2
            if running or page_mark or header_like:
                removed += 1
            else:
                kept.append(ln)
        out.append(kept)
    return out, removed


def remove_site_boilerplate(docs: list[RawDoc], min_share: float = 0.5, min_pages: int = 3) -> int:
    """Drops short blocks repeated across most pages of one website source (nav remnants, promos)."""
    if len(docs) < min_pages:
        return 0
    counts: Counter = Counter()
    for d in docs:
        counts.update({b.text.strip().lower() for b in d.blocks if len(b.text) < 200})
    threshold = max(min_pages, int(min_share * len(docs) + 0.999))
    boiler = {t for t, c in counts.items() if c >= threshold}
    removed = 0
    for d in docs:
        before = len(d.blocks)
        d.blocks = [b for b in d.blocks if b.text.strip().lower() not in boiler]
        removed += before - len(d.blocks)
    return removed


def repair_glyphs(text: str, repairs: dict[str, str]) -> tuple[str, int]:
    n = 0
    for pattern, good in repairs.items():
        text, k = re.subn(pattern, good, text)
        n += k
    return text, n


def normalize_whitespace(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.replace(" ", " ").replace("​", "")
    return " ".join(text.split())


def clean_docs(docs: list[RawDoc], repairs: dict[str, str]) -> dict[str, int]:
    stats = Counter()
    for d in docs:
        for b in d.blocks:
            b.text, n = repair_glyphs(normalize_whitespace(b.text), repairs)
            stats["glyphs_repaired"] += n
            if b.cells:
                b.cells = {k: repair_glyphs(normalize_whitespace(v), repairs)[0] for k, v in b.cells.items()}
        d.blocks = [b for b in d.blocks if b.text]
    return dict(stats)
