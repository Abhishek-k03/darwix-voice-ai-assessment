"""Source-error and conflict detection.

- table checks: missing values and >3x outliers within a monotonic series (e.g. premium by age band)
- fact conflicts: the same fact (e.g. PED waiting period) stated with different values by active sources;
  resolved by authority, then recency. Losing records are flagged needs_review and demoted at retrieval.
"""

from __future__ import annotations

import re
from collections import defaultdict
from statistics import median

from .schema import Issue, KBRecord, RawDoc

_UNIT_FACTORS = {"months": {"month": 1, "year": 12}, "days": {"day": 1}, "years": {"year": 1}}


def check_series(doc: RawDoc, src: dict) -> tuple[list[Issue], set[tuple]]:
    issues: list[Issue] = []
    flagged: set[tuple] = set()
    vcol, order = src["value_column"], src["order_column"]
    series: dict[tuple, list] = defaultdict(list)
    for b in doc.blocks:
        if not b.cells:
            continue
        key = tuple(b.cells[k] for k in src["series_by"])
        series[key].append(b.cells)
    for key, rows in series.items():
        vals = []
        for c in rows:
            row_key = (*key, c[order])
            v = c.get(vcol, "").replace(",", "").strip()
            if not v:
                flagged.add(row_key)
                issues.append(Issue(kind="source_error", source_id=doc.source_id, uri=doc.uri,
                                    detail=f"missing {vcol} for {' / '.join(row_key)}"))
                continue
            vals.append((row_key, float(v)))
        for i, (row_key, v) in enumerate(vals):
            neighbours = [x for _, x in vals[max(0, i - 2):i] + vals[i + 1:i + 3]]
            if neighbours and v > 3 * median(neighbours):
                flagged.add(row_key)
                issues.append(Issue(kind="source_error", source_id=doc.source_id, uri=doc.uri,
                                    detail=f"outlier {vcol}={int(v)} for {' / '.join(row_key)} "
                                           f"(>3x neighbouring values {', '.join(str(int(n)) for n in neighbours)})"))
    return issues, flagged


def _normalise(value: str, unit_word: str | None, target: str) -> float:
    num = float(value.replace(",", "."))
    if target == "percent" or not unit_word:
        return num
    u = unit_word.lower().rstrip("s")
    return num * _UNIT_FACTORS.get(target, {}).get(u, 1)


def detect_conflicts(records: list[KBRecord], facts_cfg: dict) -> list[dict]:
    found: dict[tuple[str, str], list[tuple[float, KBRecord, str]]] = defaultdict(list)
    for r in records:
        if r.status != "active":
            continue
        text = f"{r.title}. {r.content}".lower()
        for fact, spec in facts_cfg.get(r.market, {}).items():
            for pat in spec["patterns"]:
                m = re.search(pat, text)
                if m:
                    unit = m.group(2) if m.lastindex and m.lastindex >= 2 else None
                    found[(r.market, fact)].append((_normalise(m.group(1), unit, spec["unit"]), r, m.group(0)))
                    break
    conflicts = []
    for (market, fact), hits in found.items():
        values = {v for v, _, _ in hits}
        if len(values) < 2:
            continue
        winner = max(hits, key=lambda h: (h[1].authority, h[1].effective_date or ""))
        for v, rec, evidence in hits:
            if v != winner[0]:
                rec.needs_review = True
                rec.conflicts.append({"fact": fact, "value": v, "evidence": evidence,
                                      "authoritative_value": winner[0],
                                      "authoritative_record": winner[1].record_id})
        conflicts.append({
            "market": market, "fact": fact, "resolution": winner[0],
            "authoritative_record": winner[1].record_id, "authoritative_source": winner[1].source.uri,
            "values": [{"value": v, "record_id": r.record_id, "source": r.source.uri, "authority": r.authority,
                        "evidence": e} for v, r, e in hits],
        })
    return conflicts
