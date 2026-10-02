"""Retrieval evaluation -> evidence/q2/retrieval_report.md. Run: uv run python -m kb.eval [--k 3]"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

import yaml

from .retriever import Retriever, SearchResult

ROOT = Path(__file__).resolve().parents[2]
QUERIES = Path(__file__).parent / "eval_queries.yaml"
OUT = ROOT / "evidence" / "q2"


def _holds(hit: dict, cond: dict) -> bool:
    title, content = hit["title"].lower(), hit["content"].lower()
    text = f"{title} {content}"
    if any(s.lower() not in title for s in cond.get("title_contains", [])):
        return False
    if any(s.lower() not in content for s in cond.get("content_contains", [])):
        return False
    if any(s.lower() not in text for s in cond.get("any_text", [])):
        return False
    if cond.get("doc_type") and hit["doc_type"] not in cond["doc_type"]:
        return False
    if cond.get("not_needs_review") and hit["needs_review"]:
        return False
    return True


def relevant(hit: dict, q: dict) -> bool:
    if "any_of" in q:
        return any(_holds(hit, c) for c in q["any_of"])
    return _holds(hit, q.get("expect", {}))


def explain(hit: dict, ok: bool) -> str:
    terms = ", ".join(hit["matched_terms"]) or "none"
    return (f"{'Matches' if ok else 'Does not match'} the expected record. Lexical overlap: {terms}; dense similarity "
            f"{hit['dense']:.3f}; doc type {hit['doc_type']}; category {hit['category']}"
            + ("; flagged needs_review (lost a source conflict)" if hit["needs_review"] else ""))


def evaluate(k: int = 3) -> dict:
    retriever = Retriever()
    qs = yaml.safe_load(QUERIES.read_text(encoding="utf-8"))["queries"]
    rows, latencies, rr = [], [], []
    calib = {"positive": [], "negative": []}
    for q in qs:
        res: SearchResult = retriever.search(q["question"], q["market"], k=k)
        latencies.append(res.latency_ms)
        d = res.to_dict()
        hits = d["hits"]
        top = hits[0] if hits else None
        if top:
            calib["negative" if q.get("no_match") else "positive"].append((top["dense"], top["coverage"]))
        if q.get("no_match"):
            verdict = "correct" if res.status == "no_match" else "incorrect"
            explanation = ("Out-of-scope query rejected by the no-match gate" if verdict == "correct"
                           else f"Should have been rejected; top hit dense {top['dense']:.3f}, coverage {top['coverage']:.2f}")
            rr.append(None)
        else:
            ranks = [i for i, h in enumerate(hits) if relevant(h, q)] if res.status == "ok" else []
            verdict = "correct" if ranks and ranks[0] == 0 else "partially correct" if ranks else "incorrect"
            rr.append(1 / (ranks[0] + 1) if ranks else 0.0)
            explanation = explain(top, bool(ranks and ranks[0] == 0)) if top else "no hits"
            if res.status != "ok":
                explanation = "Rejected by the no-match gate (false negative). " + explanation
        rows.append({"id": q["id"], "type": q["type"], "market": q["market"], "question": q["question"],
                     "status": res.status, "top": top, "verdict": verdict, "explanation": explanation,
                     "latency_ms": round(res.latency_ms, 1)})
    pos = [r for r in rr if r is not None]
    lat = sorted(latencies)
    summary = {
        "kb_version": retriever.kb_version, "queries": len(qs), "k": k,
        "correct": sum(r["verdict"] == "correct" for r in rows),
        "partially_correct": sum(r["verdict"] == "partially correct" for r in rows),
        "incorrect": sum(r["verdict"] == "incorrect" for r in rows),
        "hit_at_1": round(sum(1 for r in pos if r == 1.0) / len(pos), 3),
        "hit_at_k": round(sum(1 for r in pos if r > 0) / len(pos), 3),
        "mrr": round(sum(pos) / len(pos), 3),
        "negatives_rejected": f"{sum(1 for r in rows if r['type'] == 'negative' and r['verdict'] == 'correct')}"
                              f"/{sum(1 for r in rows if r['type'] == 'negative')}",
        "latency_p50_ms": round(statistics.median(lat), 1), "latency_p95_ms": round(lat[int(0.95 * (len(lat) - 1))], 1),
        "calibration": {k2: [(round(a, 3), round(b, 2)) for a, b in v] for k2, v in calib.items()},
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "retrieval_results.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUT / "retrieval_report.md").write_text(render(summary, rows), encoding="utf-8")
    return summary


def render(s: dict, rows: list[dict]) -> str:
    out = [f"# Retrieval test report (KB v{s['kb_version']})", "",
           f"{s['queries']} queries · correct {s['correct']} · partially correct {s['partially_correct']} · incorrect {s['incorrect']}",
           "", f"- hit@1 {s['hit_at_1']} · hit@{s['k']} {s['hit_at_k']} · MRR {s['mrr']} (in-scope queries)",
           f"- out-of-scope rejected: {s['negatives_rejected']}",
           f"- retrieval latency p50 {s['latency_p50_ms']} ms · p95 {s['latency_p95_ms']} ms (CPU, no rerank)", "",
           "| # | type | market | question | retrieved record | source | verdict |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        t = r["top"]
        rec = f"`{t['record_id']}` {t['title'][:60]}" if t and r["status"] == "ok" else "— (NO_RELEVANT_INFO)"
        src = t["citation"].split(" — ", 1)[-1] if t and r["status"] == "ok" else "—"
        out.append(f"| {r['id']} | {r['type']} | {r['market']} | {r['question']} | {rec} | {src} | **{r['verdict']}** |")
    out += ["", "## Details", ""]
    for r in rows:
        t = r["top"]
        out += [f"### {r['id']} — {r['question']}", "",
                f"- **Status:** {r['status']} · **Verdict:** {r['verdict']} · latency {r['latency_ms']} ms"]
        if t and r["status"] == "ok":
            out += [f"- **Retrieved:** `{t['record_id']}` — {t['title']}",
                    f"- **Chunk:** {t['content'][:300].replace(chr(10), ' ')}{'…' if len(t['content']) > 300 else ''}",
                    f"- **Source:** {t['citation']}"]
        out += [f"- **Relevance:** {r['explanation']}", ""]
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=3)
    s = evaluate(ap.parse_args().k)
    print(json.dumps({k: v for k, v in s.items() if k != "calibration"}, indent=2))
    print("calibration (dense, coverage) positives:", s["calibration"]["positive"])
    print("calibration (dense, coverage) negatives:", s["calibration"]["negative"])


if __name__ == "__main__":
    main()
