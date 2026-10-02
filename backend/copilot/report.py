"""Q4 report: per-component latency (P50/P95) and false-positive analysis.

Sources: audio replays (evidence/q4/replays/<run>/{metrics,events}.jsonl + labels), live calls
(evidence/q4/metrics/<room>.jsonl), hub display acks (evidence/q4/events/<room>.jsonl), plus a deterministic
logic-level ablation (text mode, controls on vs off) over all scripted scenarios.

  uv run python -m copilot.report
"""

from __future__ import annotations

import asyncio
import json
from collections import Counter, defaultdict
from pathlib import Path
from unittest.mock import patch

from .replay import replay_text

ROOT = Path(__file__).resolve().parents[2]
Q4 = ROOT / "evidence" / "q4"
SCRIPTS = ROOT / "backend" / "sim" / "scripts"


def pct(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    return round(s[min(len(s) - 1, int(p * (len(s) - 1) + 0.5))], 1)


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


def _acks(room: str) -> dict[str, float]:
    return {e["nudge_id"]: e["displayed_at"] for e in _jsonl(Q4 / "events" / f"{room}.jsonl") if e.get("type") == "display_ack"}


def _hub_received(room: str) -> dict[str, float]:
    return {e["nudge"]["id"]: e["hub_received_at"] for e in _jsonl(Q4 / "events" / f"{room}.jsonl")
            if e.get("type") == "nudge" and "hub_received_at" in e}


def collect_runs() -> list[dict]:
    runs = []
    for d in sorted((Q4 / "replays").glob("*/")):
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8")) if (d / "meta.json").exists() else {}
        labels = json.loads(Path(meta["labels"]).read_text(encoding="utf-8")) if meta.get("labels") and Path(meta["labels"]).exists() else None
        runs.append({"name": d.name, "kind": "replay", "metrics": _jsonl(d / "metrics.jsonl"), "meta": meta, "labels": labels})
    for f in sorted((Q4 / "metrics").glob("*.jsonl")):
        lab = Q4 / "scripted" / f.stem.removeprefix("live-") / "labels.json"
        runs.append({"name": f.stem, "kind": "live", "metrics": _jsonl(f), "meta": {"room": f.stem, "live": True},
                     "labels": json.loads(lab.read_text(encoding="utf-8")) if f.stem.startswith("live-") and lab.exists() else None})
    return runs


def latency(runs: list[dict]) -> dict:
    comp = defaultdict(list)
    per_run = []
    for r in runs:
        room = r["meta"].get("room", r["name"])
        acks, hub = _acks(room), _hub_received(room)
        n_e2e = []
        for m in r["metrics"]:
            if m["kind"] == "asr":
                comp["asr_final" if m["final"] else "asr_interim"].append(m["asr_latency_ms"])
            elif m["kind"] == "llm" and "error" not in m:
                comp["llm"].append(m["llm_ms"])
            elif m["kind"] == "nudge":
                tl = m["timeline"]
                comp["signal_rules" if tl.get("source") == "rules" else "signal_llm"].append(tl.get("signal_ms", 0))
                comp["nudge_generation"].append(tl["nudge_at"] - tl["signal_at"])
                shown = acks.get(m["id"])
                end = shown or hub.get(m["id"])
                if end:
                    comp["delivery_display" if shown else "delivery_hub"].append(end - tl["nudge_at"])
                    comp["e2e_display" if shown else "e2e_hub"].append(end - tl["audio_received_at"])
                    n_e2e.append(end - tl["audio_received_at"])
                comp["e2e_pre_delivery"].append(tl["nudge_at"] - tl["audio_received_at"])
        per_run.append({"run": r["name"], "kind": r["kind"], "nudges": sum(m["kind"] == "nudge" for m in r["metrics"]),
                        "asr_finals": sum(m["kind"] == "asr" and m["final"] for m in r["metrics"]),
                        "e2e_p50": pct(n_e2e, 0.5), "e2e_p95": pct(n_e2e, 0.95)})
    table = {k: {"n": len(v), "p50": pct(v, 0.5), "p95": pct(v, 0.95), "max": round(max(v), 1) if v else None}
             for k, v in comp.items()}
    return {"components": table, "runs": per_run}


def score(nudges: list[dict], expected: list[dict], t_of) -> dict:
    """Matches emitted nudges to expected windows. Optional expectations never count as misses or FPs."""
    used, tp, fn = set(), [], []
    for e in expected:
        lo, hi = e["window_s"]
        hit = next((n for n in nudges if n["key"] == e["nudge"] and n["id"] not in used and lo - 1 <= t_of(n) <= hi), None)
        if hit:
            used.add(hit["id"])
            tp.append(e["nudge"])
        elif not e.get("optional"):
            fn.append(e["nudge"])
    fp = [n for n in nudges if n["id"] not in used and n["key"] not in {e["nudge"] for e in expected if e.get("optional")}]
    return {"tp": tp, "fn": fn, "fp": [f"{n['key']} @{t_of(n):.1f}s “{n.get('evidence', '')}”" for n in fp]}


def logic_ablation() -> list[dict]:
    async def no_kb(*_a, **_k):
        return {"status": "error", "hits": []}

    rows = []
    with patch("copilot.pipeline.rag.search", no_kb):
        for path in sorted(SCRIPTS.glob("*/*.yaml")):
            for controls in (True, False):
                res = asyncio.run(replay_text(path, use_llm=False, controls_on=controls))
                exp = [{**e, "window_s": [res["line_end_s"][e["line"] - 1], res["line_end_s"][e["line"] - 1] + e.get("within_s", 10)]}
                       for e in res["expected"]]
                nud = [{"id": n["id"], "key": n["key"], "t": n["t_s"], "evidence": n["evidence"]} for n in res["nudges"]]
                sc = score(nud, exp, lambda n: n["t"])
                suppressed = Counter(d["reason"] for d in res["decisions"] if d["decision"] == "suppressed")
                rows.append({"script": res["script"], "controls": "on" if controls else "off", "nudges": len(nud),
                             "tp": len(sc["tp"]), "fn": sc["fn"], "fp": sc["fp"], "suppressed": dict(suppressed)})
    return rows


def audio_quality(runs: list[dict]) -> list[dict]:
    rows = []
    for r in runs:
        if not r["labels"]:
            continue
        start = next((m["start_ms"] for m in r["metrics"] if m["kind"] == "replay_start"), None)
        if start is None and not r["meta"].get("live"):
            continue
        first = min((m["timeline"]["audio_received_at"] for m in r["metrics"] if m["kind"] == "nudge"), default=0)
        nud = [{"id": m["id"], "key": m["key"], "t": (m["timeline"]["nudge_at"] - (start or first)) / 1000, "evidence": m["evidence"]}
               for m in r["metrics"] if m["kind"] == "nudge"]
        lines = r["labels"]["lines"]  # a nudge may fire while the trigger line is still being spoken: window opens at its start
        expected = [{**e, "window_s": [lines[e["line"] - 1]["start_s"], e["window_s"][1]]} if "line" in e else e
                    for e in r["labels"]["expected"]]
        if start is None:   # live room: no replay clock, so match by nudge type only
            expected = [{**e, "window_s": [-1e9, 1e9]} for e in expected]
        sc = score(nud, expected, lambda n: n["t"])
        dec = Counter(m["reason"] for m in r["metrics"] if m["kind"] == "decision" and m.get("decision") == "suppressed")
        rows.append({"run": r["name"], "mode": "live room" if r["meta"].get("live") else "replay", "script": r["labels"]["id"], "noise": r["labels"].get("noise"),
                     "controls": r["meta"].get("controls"), "llm": r["meta"].get("llm"), "nudges": len(nud),
                     "tp": len(sc["tp"]), "fn": sc["fn"], "fp": sc["fp"], "suppressed": dict(dec)})
    return rows


def _fmt(v) -> str:
    return "—" if v is None else str(v)


def main() -> None:
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    runs = collect_runs()
    lat = latency(runs)
    ab = logic_ablation()
    aq = audio_quality(runs)
    Q4.mkdir(parents=True, exist_ok=True)
    (Q4 / "summary.json").write_text(json.dumps({"latency": lat, "logic_ablation": ab, "audio_quality": aq}, indent=2), encoding="utf-8")

    names = {"asr_interim": "ASR (interim results)", "asr_final": "ASR (final segments)", "signal_rules": "Signal extraction: rules",
             "llm": "Signal extraction: LLM call", "signal_llm": "LLM signal latency (emitted)", "nudge_generation": "Nudge generation",
             "e2e_pre_delivery": "Audio → nudge emitted", "delivery_hub": "Delivery to hub", "delivery_display": "Delivery to display (ack)",
             "e2e_hub": "E2E audio → hub", "e2e_display": "E2E audio → display"}
    lines = ["# Q4 latency report", "", f"Runs analysed: {len(runs)} ({sum(r['kind'] == 'replay' for r in runs)} replays, "
             f"{sum(r['kind'] == 'live' for r in runs)} live calls). All times in ms, epoch-ms stage stamps across processes.", "",
             "| component | n | P50 | P95 | max |", "|---|---|---|---|---|"]
    for k, label in names.items():
        c = lat["components"].get(k)
        if c:
            lines.append(f"| {label} | {c['n']} | {_fmt(c['p50'])} | {_fmt(c['p95'])} | {_fmt(c['max'])} |")
    lines += ["", "## Per run", "", "| run | kind | ASR finals | nudges | E2E P50 | E2E P95 |", "|---|---|---|---|---|---|"]
    lines += [f"| {r['run']} | {r['kind']} | {r['asr_finals']} | {r['nudges']} | {_fmt(r['e2e_p50'])} | {_fmt(r['e2e_p95'])} |" for r in lat["runs"]]
    (Q4 / "latency_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    fl = ["# Q4 false-positive analysis", "",
          "## Logic level (perfect transcripts, virtual clock): controls on vs off", "",
          "| script | controls | nudges | TP | missed | false positives | suppressed (reason: count) |", "|---|---|---|---|---|---|---|"]
    for r in ab:
        fl.append(f"| {r['script']} | {r['controls']} | {r['nudges']} | {r['tp']} | {', '.join(r['fn']) or '—'} | "
                  f"{'; '.join(r['fp']) or '—'} | {', '.join(f'{k}: {v}' for k, v in r['suppressed'].items()) or '—'} |")
    on = [r for r in ab if r["controls"] == "on"]
    off = [r for r in ab if r["controls"] == "off"]
    fl += ["", f"Totals: controls ON → {sum(r['nudges'] for r in on)} nudges, {sum(len(r['fp']) for r in on)} FP; "
               f"controls OFF → {sum(r['nudges'] for r in off)} nudges, {sum(len(r['fp']) for r in off)} FP.", "",
           "## Audio level (real-time replay and live-room runs through streaming ASR)", ""]
    if aq:
        fl += ["| run | mode | script | noise | controls | LLM | nudges | TP | missed | false positives | suppressed |", "|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in aq:
            fl.append(f"| {r['run']} | {r['mode']} | {r['script']} | {r['noise'] or '—'} | {r['controls'] if r['controls'] is not None else True} | {r['llm'] if r['llm'] is not None else True} | {r['nudges']} | {r['tp']} | "
                      f"{', '.join(r['fn']) or '—'} | {'; '.join(r['fp']) or '—'} | {', '.join(f'{k}: {v}' for k, v in r['suppressed'].items()) or '—'} |")
        tp, fp = sum(r["tp"] for r in aq), sum(len(r["fp"]) for r in aq)
        fn = sum(len(r["fn"]) for r in aq)
        fl += ["", f"Precision ≈ {tp / (tp + fp):.2f}, recall ≈ {tp / (tp + fn):.2f} over {len(aq)} audio runs (replays and live-room runs)." if tp + fp and tp + fn else ""]
    else:
        fl.append("No audio replays found yet (run sim.make_scripted_call + copilot.replay).")
    (Q4 / "fp_analysis.md").write_text("\n".join(fl) + "\n", encoding="utf-8")
    print((Q4 / "latency_report.md").read_text(encoding="utf-8"))
    print((Q4 / "fp_analysis.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
