"""KB data model: extraction blocks -> documents -> records (the indexed, citable unit)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

BlockKind = Literal["heading", "paragraph", "list_item", "table_row", "quote"]


class SourceRef(BaseModel):
    source_id: str
    type: str
    uri: str
    section: str | None = None
    page: int | None = None
    retrieved_at: str | None = None
    content_hash: str | None = None

    def cite(self) -> str:
        loc = f" p.{self.page}" if self.page else ""
        sec = f" › {self.section}" if self.section else ""
        return f"{self.uri.rsplit('/', 1)[-1]}{loc}{sec}"


class Block(BaseModel):
    kind: BlockKind
    text: str
    level: int = 0
    page: int | None = None
    cells: dict[str, str] | None = None
    also_found_in: list[SourceRef] = Field(default_factory=list)


class RawDoc(BaseModel):
    source_id: str
    market: str
    language: str
    type: str
    uri: str
    title: str
    blocks: list[Block]
    authority: int
    doc_type: str
    doc_group: str
    effective_date: str | None = None
    retrieved_at: str
    raw_hash: str
    status: Literal["active", "superseded"] = "active"
    meta: dict = Field(default_factory=dict)


class KBRecord(BaseModel):
    record_id: str = ""
    title: str
    content: str
    category: str = ""
    subcategory: str | None = None
    doc_type: str
    product: str | None = None
    market: str
    language: str
    source: SourceRef
    version: str = "1.0"
    effective_date: str | None = None
    status: Literal["active", "superseded"] = "active"
    authority: int
    pii: bool = False
    pii_types: list[str] = Field(default_factory=list)
    also_found_in: list[SourceRef] = Field(default_factory=list)
    conflicts: list[dict] = Field(default_factory=list)
    needs_review: bool = False
    tags: list[str] = Field(default_factory=list)
    parent_id: str | None = None
    chunk_index: int = 0
    token_count: int = 0
    content_hash: str = ""
    stable_key: str = ""
    kb_version: str | None = None

    def citation(self) -> str:
        return f"[{self.record_id}] {self.title} — {self.source.cite()}"


class Issue(BaseModel):
    """Extraction failure, quarantine, or detected source error — surfaced in the build report."""
    kind: Literal["extraction_failure", "quarantined", "source_error", "conflict", "warning"]
    source_id: str
    uri: str
    detail: str
