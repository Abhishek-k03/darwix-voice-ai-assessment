"""Structure-aware chunking: FAQ pair / policy section / table-row group / rule row / form schema -> KBRecord."""

from __future__ import annotations

import re
from collections import OrderedDict

from .normalize import Normalizer
from .schema import Block, KBRecord, RawDoc, SourceRef

MAX_TOKENS = 320
_WORD = re.compile(r"\w+", re.UNICODE)


def token_count(text: str) -> int:
    return int(len(_WORD.findall(text)) * 1.3)


def format_inr(value: str | int) -> str:
    n = int(float(value))
    s = str(n)
    if len(s) <= 3:
        return f"₹{s}"
    head, tail = s[:-3], s[-3:]
    head = re.sub(r"(\d)(?=(\d{2})+$)", r"\1,", head)
    return f"₹{head},{tail}"


def _src(doc: RawDoc, section: str | None, page: int | None) -> SourceRef:
    return SourceRef(source_id=doc.source_id, type=doc.type, uri=doc.uri, section=section, page=page,
                     retrieved_at=doc.retrieved_at, content_hash=doc.raw_hash)


def _record(doc: RawDoc, *, title: str, content: str, section: str | None, page: int | None,
            idx: int, blocks: list[Block] | None = None, parent: str | None = None) -> KBRecord:
    seen_also = {}
    for b in blocks or []:
        for s in b.also_found_in:
            seen_also[(s.uri, s.page)] = s
    return KBRecord(
        title=title, content=content, doc_type=doc.doc_type, market=doc.market, language=doc.language,
        source=_src(doc, section, page), effective_date=doc.effective_date, status=doc.status,
        authority=doc.authority, also_found_in=list(seen_also.values()), parent_id=parent,
        chunk_index=idx, token_count=token_count(content),
        stable_key=f"{doc.source_id}|{doc.uri}|{doc.meta.get('sheet') or ''}|{section or ''}|{idx}",
    )


def _block_line(b: Block) -> str:
    return f"- {b.text}" if b.kind == "list_item" else b.text


def chunk_doc(doc: RawDoc, src: dict, norm: Normalizer, flagged_rows: set[tuple] | None = None) -> list[KBRecord]:
    if doc.doc_type == "premium_table":
        return _premium_chunks(doc, src, flagged_rows or set())
    if doc.doc_type == "form_field":
        return _form_chunks(doc, norm)
    if doc.type == "xlsx":
        return _sheet_chunks(doc)
    return _section_chunks(doc)


def _sections(doc: RawDoc) -> list[tuple[str | None, list[Block]]]:
    sections: list[tuple[str | None, list[Block]]] = []
    current: str | None = None
    buf: list[Block] = []
    for b in doc.blocks:
        if b.kind == "heading":
            if buf:
                sections.append((current, buf))
            current, buf = b.text, []
        else:
            buf.append(b)
    if buf:
        sections.append((current, buf))
    return sections


def _section_chunks(doc: RawDoc) -> list[KBRecord]:
    out: list[KBRecord] = []
    for section, blocks in _sections(doc):
        is_qa = bool(section and section.rstrip().endswith("?"))
        title = section if is_qa else (f"{doc.title} › {section}" if section else doc.title)
        windows: list[list[Block]] = []
        cur: list[Block] = []
        for b in blocks:
            if cur and token_count(" ".join(x.text for x in cur + [b])) > MAX_TOKENS:
                windows.append(cur)
                cur = [] if is_qa else cur[-1:]
            cur.append(b)
        if cur:
            windows.append(cur)
        parent = f"{doc.source_id}:{doc.uri}:{section or ''}"
        for i, win in enumerate(windows):
            content = "\n".join(_block_line(b) for b in win)
            if len(content) < 25:
                continue
            out.append(_record(doc, title=title, content=content, section=section,
                               page=win[0].page, idx=i, blocks=win, parent=parent))
    return out


def _premium_chunks(doc: RawDoc, src: dict, flagged: set[tuple]) -> list[KBRecord]:
    groups: OrderedDict[tuple, list[Block]] = OrderedDict()
    keys = src["group_by"]
    for b in doc.blocks:
        if b.cells:
            groups.setdefault(tuple(b.cells[k] for k in keys), []).append(b)
    out = []
    for i, (gk, rows) in enumerate(groups.items()):
        product, band = gk[0], gk[1]
        lines = []
        for r in rows:
            c = r.cells
            row_key = tuple(c[k] for k in (*src["series_by"], src["order_column"]))
            value = c[src["value_column"]]
            if row_key in flagged or not value:
                price = "premium unavailable (flagged for review)"
            else:
                price = f"{format_inr(value)} per year"
            lines.append(f"- {c['members']}, sum insured ₹{c['sum_insured']}: {price}")
        lines.append("Zone A rates. Zone B is 10% lower and Zone C 20% lower. Indicative only; final premium is subject to underwriting.")
        out.append(_record(doc, title=f"Indicative annual premium — {product}, age band {band}",
                           content="\n".join(lines), section=f"{product} {band}", page=None, idx=i, blocks=rows))
    return out


def _sheet_chunks(doc: RawDoc) -> list[KBRecord]:
    out: list[KBRecord] = []
    for sheet, rows in _sections(doc):
        rows = [r for r in rows if r.cells]
        if len(rows) > 8:
            for i, r in enumerate(rows):
                c = r.cells
                rid = c.get("rule_id") or str(i + 1)
                text = "; ".join(f"{k.replace('_', ' ')}: {v}" for k, v in c.items() if v and k != "rule_id")
                out.append(_record(doc, title=f"{doc.title} › {sheet} › {rid}", content=f"Rule {rid}: {text}",
                                   section=f"{sheet} {rid}", page=None, idx=0, blocks=[r]))
        elif rows:
            content = "\n".join("- " + "; ".join(f"{k.replace('_', ' ')}: {v}" for k, v in r.cells.items() if v) for r in rows)
            out.append(_record(doc, title=f"{doc.title} › {sheet}", content=content, section=sheet,
                               page=None, idx=0, blocks=rows))
    return out


_BLANK_VALUE = re.compile(r"^[_\s]*$|^[A-Za-z]+( / [A-Za-z]+)+$")


def _form_chunks(doc: RawDoc, norm: Normalizer) -> list[KBRecord]:
    fields, questions, other = [], [], []
    for b in doc.blocks:
        if b.kind == "heading":
            continue
        text = b.text.strip()
        if text.endswith("(Y/N)"):
            questions.append(text.replace("(Y/N)", "").strip())
        elif ":" in text and b.kind != "table_row":
            label, value = text.split(":", 1)
            canon = norm.form_field(label) or re.sub(r"\W+", "_", label.lower()).strip("_")
            options = value.strip() if not set(value.strip()) <= {"_", " "} else ""
            fields.append(f"{canon} ({label.strip()}{'; options: ' + options if options else ''})")
        elif b.kind == "table_row" and b.cells:
            other.append("Members table columns: " + ", ".join(b.cells.keys()))
        else:
            other.append(text)
    content = "Fields collected: " + "; ".join(fields) + "."
    if questions:
        content += "\nMedical questions (Y/N): " + " | ".join(questions)
    if other:
        content += "\n" + "\n".join(dict.fromkeys(other))
    return [_record(doc, title=f"Proposal form fields — {doc.title}", content=content,
                    section="form schema", page=1, idx=0, blocks=doc.blocks)]
