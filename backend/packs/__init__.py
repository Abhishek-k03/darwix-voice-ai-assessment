"""Use-case / market packs: one voice worker, many configurations (Q1 India health, Q3 PH life, Q3 ID multifinance).

A pack bundles persona prompt, script lines, field schema + business rules, compliance checks, STT/TTS/LLM
choices and the turn-taking lexicon. FAQs, objections and policy facts are NOT in the pack — they live in the KB.
"""

from __future__ import annotations

import functools
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

PACKS_DIR = Path(__file__).parent
SALUTATIONS = {
    "in_health": ("Asia/Kolkata", [(12, "good morning"), (17, "good afternoon"), (24, "good evening")]),
    "ph_life": ("Asia/Manila", [(12, "magandang umaga"), (18, "magandang hapon"), (24, "magandang gabi")]),
    "id_multifinance": ("Asia/Jakarta", [(11, "Selamat pagi"), (15, "Selamat siang"), (18, "Selamat sore"), (24, "Selamat malam")]),
}


@dataclass(frozen=True)
class FieldSpec:
    name: str
    type: str = "str"
    required: bool = False
    required_if: dict = field(default_factory=dict)
    ask: str = ""
    values: tuple = ()
    min: float | None = None
    max: float | None = None
    description: str = ""
    widening: tuple = ()  # narrow->wide enum chain: moving up it refines the value, it is not a conflict
    soft_max: float | None = None  # above this a number is plausible but unlikely: kept low-confidence and confirmed once
    known: tuple = ()  # recognised values; anything else is kept low-confidence and confirmed once
    quick: str = ""  # fast-path answer kind: yesno | consent | confirm | number | amount | city | name
    cues: tuple = ()  # words an LLM-phrased question must contain before a short answer is mapped to this field
    on_no: str = ""  # intent a quick "no" implies (e.g. busy for "is this a good time?")


@dataclass(frozen=True)
class Pack:
    id: str
    market: str
    display_name: str
    language: str
    locale: str
    persona: str
    company: str
    use_case: str
    stt: dict
    tts: tuple
    llm: dict
    turn_lexicon: str
    prompt: str
    lines: dict
    fields: tuple[FieldSpec, ...]
    rules: dict
    compliance: dict
    extraction_hints: str = ""
    demo_customer: str | None = None
    greeting_awaits: str = ""  # field the greeting's question asks (fast path for the first answer)
    extends: str = ""  # pack whose rules, compliance and script lines this one reuses (a language variant)

    def salutation(self) -> str:
        """Time-of-day greeting in the market's language and local time zone."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        tz, table = SALUTATIONS.get(self.market, SALUTATIONS["in_health"])
        hour = datetime.now(ZoneInfo(tz)).hour
        return next(word for limit, word in table if hour < limit)

    def line(self, key: str, **kw) -> str:
        text = self.lines.get(key, "")
        text = text[0] if isinstance(text, list) else text
        return text.format(persona=self.persona, company=self.company, **kw) if text else ""

    def variant(self, key: str, pick: int, **kw) -> str:
        """One of a line's variants (YAML list), skipping those that need a value we don't have (e.g. {name})."""
        options = self.lines.get(key) or []
        options = [options] if isinstance(options, str) else options
        usable = [o for o in options if all(kw.get(k) for k in re.findall(r"{(\w+)}", o) if k not in ("persona", "company"))]
        return usable[pick % len(usable)].format(persona=self.persona, company=self.company, **kw) if usable else ""

    def field(self, name: str) -> FieldSpec | None:
        return next((f for f in self.fields if f.name == name), None)

    def public(self) -> dict:
        return {"id": self.id, "display_name": self.display_name, "language": self.language, "market": self.market,
                "use_case": self.use_case, "persona": self.persona, "company": self.company}


def _read(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}


def _field(f: dict, rules: dict, roots: tuple[Path, ...], extra_cues: dict) -> FieldSpec:
    known = f.get("known") or ()
    if known == "zones":
        known = [c for z in rules.get("zones", {}).values() for c in z["cities"]]
    if isinstance(known, str) and known.endswith(".txt"):
        known = next((r / known for r in roots if (r / known).exists()), roots[0] / known).read_text(encoding="utf-8").split()
    return FieldSpec(**{**f, "values": tuple(f.get("values", ())), "widening": tuple(f.get("widening", ())),
                        "known": tuple(known),
                        "cues": tuple(f.get("cues", ())) + tuple(extra_cues.get(f["name"], ()))})


@functools.lru_cache(maxsize=None)
def load_pack(pack_id: str | None = None) -> Pack:
    pack_id = pack_id or os.getenv("DEFAULT_PACK", "in_health")
    root = PACKS_DIR / pack_id
    if not (root / "pack.yaml").exists():
        raise ValueError(f"unknown pack {pack_id!r}")
    meta = _read(root / "pack.yaml")
    parent = PACKS_DIR / meta["extends"] if meta.get("extends") else root
    meta = {**_read(parent / "pack.yaml"), **meta}
    rules = _read(root / "rules.yaml") or _read(parent / "rules.yaml")
    fields = tuple(_field(f, rules, (root, parent), meta.get("cues", {})) for f in rules.pop("fields", []))
    return Pack(
        id=pack_id, market=meta["market"], display_name=meta["display_name"], language=meta["language"],
        locale=meta.get("locale", meta["language"]), persona=meta["persona"], company=meta["company"],
        use_case=meta["use_case"], stt=meta.get("stt", {}), tts=tuple(meta.get("tts", [])), llm=meta.get("llm", {}),
        turn_lexicon=meta.get("turn_lexicon", "en"), prompt=(root / "prompt.md").read_text(encoding="utf-8"),
        lines={**_read(parent / "script.yaml"), **_read(root / "script.yaml")}, fields=fields, rules=rules,
        compliance=_read(root / "compliance.yaml") or _read(parent / "compliance.yaml"),
        extraction_hints=meta.get("extraction_hints", ""), demo_customer=meta.get("demo_customer"),
        greeting_awaits=meta.get("greeting_awaits", ""), extends=meta.get("extends", ""),
    )


def list_packs() -> list[Pack]:
    return [load_pack(p.name) for p in sorted(PACKS_DIR.iterdir()) if (p / "pack.yaml").exists()]
