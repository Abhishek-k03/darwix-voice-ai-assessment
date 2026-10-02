"""Extraction: website crawl (HTTP + trafilatura), PDF (pdfplumber), CSV/XLSX (pandas), Markdown.

Every extractor returns structured Blocks (headings preserved) or raises ExtractionError with a reason
that the build report lists — failures never abort the build.
"""

from __future__ import annotations

import functools
import hashlib
import http.server
import logging
import re
import threading
import xml.etree.ElementTree as ET
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
import pandas as pd
import pdfplumber
import trafilatura
from bs4 import BeautifulSoup

from .clean import strip_running_lines
from .schema import Block, RawDoc

logger = logging.getLogger("kb.extract")

USER_AGENT = "DarwixKBBot/1.0 (+assessment; respects robots.txt)"
MIN_CONTENT_CHARS = 120
JS_HINTS = ("enable javascript", "please enable js", "requires javascript")


class ExtractionError(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()[:16]


# ── Local static server (so the synthetic website is crawled over real HTTP) ──

class LocalSite:
    def __init__(self, root: Path) -> None:
        handler = functools.partial(_QuietHandler, directory=str(root))
        self._httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.base_url = f"http://127.0.0.1:{self._httpd.server_address[1]}"
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def __enter__(self) -> "LocalSite":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass


# ── Web ──

def crawl(*, base_url: str, seeds: list[str], allow_prefix: str, max_pages: int,
          timeout: float = 10.0) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """BFS crawl restricted to allow_prefix. Returns ([(url, html)], [(url, failure_reason)])."""
    pages: list[tuple[str, str]] = []
    failures: list[tuple[str, str]] = []
    robots = _robots(base_url, seeds[0])
    queue = deque(urljoin(base_url, s) for s in seeds)
    seen: set[str] = set(queue)
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=timeout, follow_redirects=True) as client:
        while queue and len(pages) < max_pages:
            url = queue.popleft()
            if robots and not robots.can_fetch(USER_AGENT, url):
                failures.append((url, "disallowed by robots.txt"))
                continue
            try:
                resp = _get_with_retry(client, url)
            except httpx.HTTPError as exc:
                failures.append((url, f"network error: {exc}"))
                continue
            if resp.status_code >= 400:
                failures.append((url, f"HTTP {resp.status_code} (dead link)"))
                continue
            if "html" not in resp.headers.get("content-type", ""):
                failures.append((url, f"skipped non-HTML content-type {resp.headers.get('content-type')}"))
                continue
            pages.append((url, resp.text))
            for link in _links(resp.text, url):
                if urlparse(link).path.startswith(allow_prefix) and _same_host(link, url) and link not in seen:
                    seen.add(link)
                    queue.append(link)
    return pages, failures


def _get_with_retry(client: httpx.Client, url: str, attempts: int = 2) -> httpx.Response:
    last: Exception | None = None
    for _ in range(attempts):
        try:
            return client.get(url)
        except httpx.TransportError as exc:
            last = exc
    raise httpx.HTTPError(str(last))


def _robots(base_url: str, seed: str) -> RobotFileParser | None:
    root = urljoin(urljoin(base_url, seed), "/robots.txt")
    rp = RobotFileParser()
    try:
        resp = httpx.get(root, timeout=5, headers={"User-Agent": USER_AGENT})
    except httpx.HTTPError:
        return None
    if resp.status_code >= 400:
        return None
    rp.parse(resp.text.splitlines())
    return rp


def _same_host(a: str, b: str) -> bool:
    return urlparse(a).netloc == urlparse(b).netloc


def _links(html: str, page_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for a in soup.find_all("a", href=True):
        href = a["href"].split("#")[0].split("?")[0]
        if href and not href.startswith(("mailto:", "tel:", "javascript:")):
            out.append(urljoin(page_url, href))
    return out


def html_to_blocks(html: str) -> tuple[str, list[Block], str]:
    """Main-content extraction. trafilatura (boilerplate removal) first, BeautifulSoup fallback.
    Returns (title, blocks, extractor_used)."""
    xml = trafilatura.extract(html, output_format="xml", include_tables=True, include_comments=False,
                              favor_recall=True, with_metadata=True)
    title, blocks, used = "", [], "trafilatura"
    if xml:
        root = ET.fromstring(xml)
        title = root.attrib.get("title", "")
        main = root.find("main")
        if main is not None:
            blocks = _xml_blocks(main)
    if sum(len(b.text) for b in blocks) < MIN_CONTENT_CHARS:
        title2, blocks2 = _bs_blocks(html)
        if sum(len(b.text) for b in blocks2) > sum(len(b.text) for b in blocks):
            title, blocks, used = title2 or title, blocks2, "beautifulsoup"
    text = " ".join(b.text for b in blocks).lower()
    if sum(len(b.text) for b in blocks) < MIN_CONTENT_CHARS:
        if any(h in text for h in JS_HINTS) or "<script" in html.lower():
            raise ExtractionError("no server-rendered content (JavaScript-rendered page)")
        raise ExtractionError("too little main content after boilerplate removal")
    return title, blocks, used


def _xml_blocks(main: ET.Element) -> list[Block]:
    blocks: list[Block] = []
    for el in main:
        text = " ".join("".join(el.itertext()).split())
        if el.tag == "head":
            level = int(el.attrib.get("rend", "h2")[1:] or 2)
            if level > 1 and text:
                blocks.append(Block(kind="heading", text=text, level=level))
        elif el.tag == "p" and text:
            blocks.append(Block(kind="paragraph", text=text))
        elif el.tag == "quote" and text:
            blocks.append(Block(kind="quote", text=text))
        elif el.tag == "list":
            for item in el.iter("item"):
                t = " ".join("".join(item.itertext()).split())
                if t:
                    blocks.append(Block(kind="list_item", text=t))
        elif el.tag == "table":
            rows = [[" ".join("".join(c.itertext()).split()) for c in row.iter("cell")] for row in el.iter("row")]
            blocks += _table_blocks(rows)
    return blocks


def _bs_blocks(html: str) -> tuple[str, list[Block]]:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(strip=True).split("|")[0].strip() if soup.title else ""
    for sel in ["script", "style", "noscript", "nav", "header", "footer", "aside", "[class*=cookie]", "[class*=breadcrumb]"]:
        for el in soup.select(sel):
            el.decompose()
    root = soup.find("main") or soup.body or soup
    blocks: list[Block] = []
    for el in root.find_all(["h2", "h3", "h4", "p", "li", "blockquote", "tr"]):
        text = " ".join(el.get_text(" ", strip=True).split())
        if not text:
            continue
        if el.name in ("h2", "h3", "h4"):
            blocks.append(Block(kind="heading", text=text, level=int(el.name[1])))
        elif el.name == "li":
            blocks.append(Block(kind="list_item", text=text))
        elif el.name == "blockquote":
            blocks.append(Block(kind="quote", text=text))
        elif el.name == "p":
            blocks.append(Block(kind="paragraph", text=text))
    return title, blocks


def _table_blocks(rows: list[list[str]]) -> list[Block]:
    rows = [r for r in rows if any(c.strip() for c in r)]
    if len(rows) < 2:
        return [Block(kind="paragraph", text=" | ".join(r)) for r in rows]
    header = rows[0]
    out = []
    for r in rows[1:]:
        cells = {h or f"col{i}": (r[i] if i < len(r) else "") for i, h in enumerate(header)}
        out.append(Block(kind="table_row", text=" | ".join(f"{k}: {v}" for k, v in cells.items()), cells=cells))
    return out


def web_docs(src: dict, market: str, language: str, base_url: str) -> tuple[list[RawDoc], list[tuple[str, str]]]:
    pages, failures = crawl(base_url=base_url, seeds=src["seeds"], allow_prefix=src["allow_prefix"],
                            max_pages=src.get("max_pages", 30))
    docs: list[RawDoc] = []
    for url, html in pages:
        path = urlparse(url).path
        try:
            title, blocks, used = html_to_blocks(html)
        except ExtractionError as exc:
            failures.append((url, str(exc)))
            continue
        page_chars = len(" ".join(BeautifulSoup(html, "html.parser").get_text(" ").split()))
        chrome_removed = max(0, page_chars - sum(len(b.text) + 1 for b in blocks))
        docs.append(RawDoc(
            source_id=src["id"], market=market, language=src.get("language", language), type="web",
            uri=path if base_url else url, title=title.split("|")[0].strip(), blocks=blocks,
            authority=_by_rule(path, src.get("authority_overrides", {}), src["authority"]),
            doc_type=_by_rule(path, src.get("doc_type_rules", {}), src.get("doc_type", "product_info")),
            doc_group=src["doc_group"], effective_date=src.get("effective_date"),
            retrieved_at=_now(), raw_hash=_hash(html), meta={"extractor": used, "chrome_chars_removed": chrome_removed},
        ))
    return docs, failures


def _by_rule(path: str, rules: dict, default):
    for frag, value in rules.items():
        if frag in path:
            return value
    return default


# ── PDF ──

def _line_style(line: dict) -> tuple[float, bool]:
    chars = line.get("chars") or []
    sizes = sorted(round(c["size"], 1) for c in chars) or [0.0]
    return sizes[len(sizes) // 2], any("Bold" in c.get("fontname", "") for c in chars)


def pdf_doc(path: Path, src: dict, market: str, language: str, sources_root: Path) -> RawDoc:
    """Layout-aware PDF parsing: font size/weight identify title and headings; tables are extracted
    separately (pdfplumber) and merged back in reading order by vertical position."""
    pages: list[list[tuple[float, str, object]]] = []  # (top, kind, payload)
    has_images = False
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            has_images = has_images or bool(page.images)
            tables = page.find_tables()
            bboxes = [t.bbox for t in tables]

            def _outside(obj, _b=bboxes):
                return not any(b[0] <= obj.get("x0", 0) <= b[2] and b[1] <= obj.get("top", 0) <= b[3] for b in _b)

            items: list[tuple[float, str, object]] = []
            for ln in page.filter(_outside).extract_text_lines(return_chars=True):
                text = ln["text"].strip()
                if text:
                    items.append((ln["top"], "line", (text, *_line_style(ln))))
            for t in tables:
                rows = [[(c or "").replace("\n", " ").strip() for c in row] for row in t.extract()]
                items.append((t.bbox[1], "table", rows))
            pages.append(sorted(items, key=lambda x: x[0]))
        meta_title = (pdf.metadata or {}).get("Title")
    if not any(any(k == "line" for _, k, _ in p) for p in pages):
        raise ExtractionError("no text layer (scanned image) — OCR required" if has_images else "empty PDF")

    texts = [[p[2][0] for p in page if p[1] == "line"] for page in pages]
    kept, running_removed = strip_running_lines(texts)
    kept_sets = [set(k) for k in kept]
    sizes = [p[2][1] for page in pages for p in page if p[1] == "line"]
    body = max(set(sizes), key=sizes.count)
    title_size = max(sizes)

    blocks: list[Block] = []
    title_parts: list[str] = []
    line_mode = src.get("doc_type") == "form_field"
    for pno, page in enumerate(pages, start=1):
        para: list[str] = []

        def _flush(_p=para, _n=pno):
            if _p:
                blocks.append(Block(kind="paragraph", text=" ".join(_p), page=_n))
                _p.clear()

        for _, kind, payload in page:
            if kind == "table":
                _flush()
                for tb in _table_blocks(payload):
                    tb.page = pno
                    blocks.append(tb)
                continue
            text, size, bold = payload
            if text not in kept_sets[pno - 1]:
                continue
            if pno == 1 and size == title_size and title_size > body + 2:
                title_parts.append(text)
            elif (bold or size > body + 1) and len(text) <= 90:
                _flush()
                blocks.append(Block(kind="heading", text=text, level=2, page=pno))
            elif line_mode:
                blocks.append(Block(kind="paragraph", text=text, page=pno))
            else:
                para.append(text)
                if text.endswith((".", "?", ":")) and len(" ".join(para)) > 200:
                    _flush()
        _flush()
    rel = path.relative_to(sources_root).as_posix()
    return RawDoc(source_id=src["id"], market=market, language=src.get("language", language), type="pdf",
                  uri=rel, title=" ".join(title_parts) or meta_title or path.stem, blocks=blocks,
                  authority=src["authority"], doc_type=src["doc_type"], doc_group=src["doc_group"],
                  effective_date=src.get("effective_date"), retrieved_at=_now(), raw_hash=_hash(path.read_bytes()),
                  meta={"pages": len(pages), "running_lines_removed": running_removed})


# ── Tables ──

def csv_doc(path: Path, src: dict, market: str, language: str, sources_root: Path) -> RawDoc:
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    return _frame_doc(df, src, market, language, path, sources_root, sheet=None)


def xlsx_doc(path: Path, src: dict, market: str, language: str, sources_root: Path) -> RawDoc:
    blocks: list[Block] = []
    for sheet, df in pd.read_excel(path, sheet_name=None, dtype=str).items():
        df = df.fillna("")
        blocks.append(Block(kind="heading", text=sheet, level=2))
        blocks += _frame_doc(df, src, market, language, path, sources_root, sheet=sheet).blocks
    rel = path.relative_to(sources_root).as_posix()
    return RawDoc(source_id=src["id"], market=market, language=language, type="xlsx", uri=rel,
                  title=src.get("title", path.stem), blocks=blocks, authority=src["authority"],
                  doc_type=src["doc_type"], doc_group=src["doc_group"], effective_date=src.get("effective_date"),
                  retrieved_at=_now(), raw_hash=_hash(path.read_bytes()))


def _frame_doc(df: pd.DataFrame, src: dict, market: str, language: str, path: Path, sources_root: Path,
               sheet: str | None) -> RawDoc:
    df.columns = [str(c).strip() for c in df.columns]
    blocks = []
    for _, row in df.iterrows():
        cells = {c: str(row[c]).strip() for c in df.columns}
        if not any(cells.values()):
            continue
        blocks.append(Block(kind="table_row", text=" | ".join(f"{k}: {v}" for k, v in cells.items()), cells=cells))
    rel = path.relative_to(sources_root).as_posix()
    return RawDoc(source_id=src["id"], market=market, language=language, type=path.suffix.lstrip("."), uri=rel,
                  title=src.get("title", path.stem), blocks=blocks, authority=src["authority"],
                  doc_type=src["doc_type"], doc_group=src["doc_group"], effective_date=src.get("effective_date"),
                  retrieved_at=_now(), raw_hash=_hash(path.read_bytes()), meta={"sheet": sheet})


# ── Markdown ──

def markdown_doc(path: Path, src: dict, market: str, language: str, sources_root: Path) -> RawDoc:
    text = path.read_text(encoding="utf-8")
    blocks: list[Block] = []
    title = path.stem
    para: list[str] = []

    def _flush():
        if para:
            blocks.append(Block(kind="paragraph", text=" ".join(para)))
            para.clear()

    for line in text.splitlines():
        s = line.strip()
        m = re.match(r"^(#{1,6})\s+(.*)", s)
        if m:
            _flush()
            if len(m.group(1)) == 1:
                title = m.group(2)
            else:
                blocks.append(Block(kind="heading", text=m.group(2), level=len(m.group(1))))
        elif s.startswith(("- ", "* ")):
            _flush()
            blocks.append(Block(kind="list_item", text=s[2:]))
        elif not s:
            _flush()
        else:
            para.append(s)
    _flush()
    rel = path.relative_to(sources_root).as_posix()
    return RawDoc(source_id=src["id"], market=market, language=src.get("language", language), type="markdown",
                  uri=rel, title=title, blocks=blocks, authority=src["authority"], doc_type=src["doc_type"],
                  doc_group=src["doc_group"], effective_date=src.get("effective_date"),
                  retrieved_at=_now(), raw_hash=_hash(text))


FILE_EXTRACTORS = {"pdf": pdf_doc, "csv": csv_doc, "xlsx": xlsx_doc, "markdown": markdown_doc}
