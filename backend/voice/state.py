"""Per-call state with typed field validation and conflict-aware merging (pattern adapted from ai-ear's
confidence merge: a new value never silently overwrites a different one — it becomes a conflict to confirm)."""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from packs import FieldSpec, Pack

STAGES = ("OPENING", "DISCOVERY", "QUALIFICATION", "RECOMMENDATION", "NEXT_STEP", "CLOSE")


@dataclass
class FieldValue:
    value: Any
    confidence: float
    turn: int


@dataclass
class Conflict:
    field: str
    old: Any
    new: Any
    turn: int


@dataclass
class CallState:
    pack_id: str
    call_id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    room: str = ""
    stage: str = "OPENING"
    fields: dict[str, FieldValue] = field(default_factory=dict)
    pending_conflicts: list[Conflict] = field(default_factory=list)
    resolved_conflicts: list[dict] = field(default_factory=list)
    ask_attempts: dict[str, int] = field(default_factory=dict)
    awaiting: str | None = None           # field the last question asked (expected-answer fast path)
    checking: str | None = None           # field whose value was just read back for confirmation
    lowest_offered: bool = False          # the cheapest option was already put to a customer whose budget was too low
    options: list = field(default_factory=list)   # plan sizes offered when the budget was unclear
    awaiting_exact: bool = False          # True when that question was a fixed line (no cue check needed)
    turn: int = 0
    fallback_streak: int = 0
    negative_streak: int = 0
    intents: list[str] = field(default_factory=list)
    objections: list[str] = field(default_factory=list)
    eligibility: dict | None = None
    disclosed_waiting_period: bool = False
    escalated: bool = False
    handoff_active: bool = False
    dnc: bool = False
    callback: dict | None = None
    lead_id: str | None = None
    outcome: str | None = None
    end_requested: bool = False
    started_at: float = field(default_factory=time.time)
    customer: dict = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)

    def get(self, name: str, default: Any = None) -> Any:
        fv = self.fields.get(name)
        return fv.value if fv else default

    def known(self) -> dict[str, Any]:
        return {k: v.value for k, v in self.fields.items()}

    def log(self, kind: str, **data) -> None:
        self.events.append({"t": round(time.time() - self.started_at, 2), "turn": self.turn, "kind": kind, **data})


UNVERIFIED = 0.3
_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def coerce(spec: FieldSpec, raw: Any) -> Any:
    """Validates/normalises an extracted value against the field spec. Raises ValueError if unusable."""
    if raw is None or raw == "":
        raise ValueError("empty")
    t = spec.type
    if t == "bool":
        if isinstance(raw, bool):
            return raw
        s = str(raw).strip().lower()
        if s in ("true", "yes", "y", "haan", "oo", "opo", "iya", "ya", "1"):
            return True
        if s in ("false", "no", "n", "nahi", "hindi", "tidak", "nggak", "0"):
            return False
        raise ValueError(f"not a boolean: {raw!r}")
    if t in ("int", "number"):
        n = raw if isinstance(raw, (int, float)) else float(_NUM.search(str(raw).replace(",", "")).group(0))
        n = int(round(n)) if t == "int" else float(n)
        if spec.min is not None and n < spec.min or spec.max is not None and n > spec.max:
            raise ValueError(f"{spec.name}={n} outside {spec.min}..{spec.max}")
        return n
    if t == "list_int":
        items = raw if isinstance(raw, list) else _NUM.findall(str(raw))
        vals = [int(float(x)) for x in items]
        if not vals:
            raise ValueError("empty list")
        return vals
    if t == "enum":
        s = str(raw).strip().lower()
        if s not in spec.values:
            raise ValueError(f"{s!r} not in {spec.values}")
        return s
    return str(raw).strip()


def _widens(spec: FieldSpec, old: Any, new: Any) -> bool:
    c = spec.widening
    return old in c and new in c and c.index(new) > c.index(old)


def _is_known(spec: FieldSpec, value: Any) -> bool:
    text = str(value).lower()
    if spec.quick == "name":
        return any(w in spec.known for w in text.split())  # whole words: "om" must not match inside "omar"
    return any(k in text for k in spec.known)


def merge(state: CallState, pack: Pack, name: str, raw: Any, confidence: float, correction: bool = False) -> str:
    """Returns 'set' | 'same' | 'confirmed' | 'widened' | 'corrected' | 'conflict' | 'invalid' | 'unknown_field'."""
    spec = pack.field(name)
    if spec is None:
        return "unknown_field"
    try:
        value = coerce(spec, raw)
    except (ValueError, AttributeError, TypeError):
        state.log("invalid_value", field=name, raw=str(raw))
        return "invalid"
    if spec.soft_max is not None and isinstance(value, (int, float)) and value > spec.soft_max:
        confidence = min(confidence, UNVERIFIED)  # "total budget 5 lakh" is not a yearly premium
    if spec.known and not _is_known(spec, value):
        confidence = min(confidence, UNVERIFIED)  # e.g. ASR heard "Pune" as "Ten"
    cur = state.fields.get(name)
    if cur is None:
        state.fields[name] = FieldValue(value, confidence, state.turn)
        return "set"
    pending = next((c for c in state.pending_conflicts if c.field == name), None)
    if cur.value == value:
        cur.confidence = max(cur.confidence, confidence)
        if pending:  # customer re-confirmed the earlier value
            state.pending_conflicts.remove(pending)
            state.resolved_conflicts.append({"field": name, "old": pending.new, "new": value, "turn": state.turn})
            return "confirmed"
        return "same"
    if _widens(spec, cur.value, value):
        state.fields[name] = FieldValue(value, confidence, state.turn)
        state.pending_conflicts = [c for c in state.pending_conflicts if c.field != name]
        state.log("widened", field=name, old=cur.value, new=value)
        return "widened"
    if correction or pending or cur.confidence <= UNVERIFIED:
        state.fields[name] = FieldValue(value, confidence, state.turn)
        state.resolved_conflicts.append({"field": name, "old": cur.value, "new": value, "turn": state.turn})
        state.pending_conflicts = [c for c in state.pending_conflicts if c.field != name]
        return "corrected"
    state.pending_conflicts.append(Conflict(name, cur.value, value, state.turn))
    state.log("conflict", field=name, old=cur.value, new=value)
    return "conflict"


def is_required(spec: FieldSpec, state: CallState) -> bool:
    if spec.required:
        return True
    return any(state.get(k) in vals for k, vals in spec.required_if.items())


def missing_fields(pack: Pack, state: CallState) -> list[FieldSpec]:
    return [f for f in pack.fields if is_required(f, state) and f.name not in state.fields]
