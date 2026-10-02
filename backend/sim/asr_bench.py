"""Q3 ASR bake-off per market: code-switched / colloquial / finance-term utterances, synthesised with native
voices (and a Javanese/Sundanese voice reading Indonesian as a regional-accent proxy), streamed in real time
through every candidate STT. Reports WER/CER, finance-term recall and final-result latency.

  uv run python -m sim.asr_bench --market ph_life
  uv run python -m sim.asr_bench --market id_multifinance
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
from pathlib import Path

import jiwer
import numpy as np
from dotenv import find_dotenv, load_dotenv

from packs import load_pack
from sim.make_scripted_call import SR, synth

load_dotenv(find_dotenv())
OUT = Path(__file__).resolve().parents[2] / "evidence" / "q3"

SETS = {
    "ph_life": {
        "voices": {"native": [{"provider": "azure", "voice": "fil-PH-AngeloNeural", "language": "fil-PH"}],
                   "native_female": [{"provider": "azure", "voice": "fil-PH-BlessicaNeural", "language": "fil-PH"}]},
        "terms": ["premium", "policy", "grace period", "lapse", "beneficiary", "rider", "coverage", "gcash", "due"],
        "utterances": [
            ("taglish", "Pwede ko bang bayaran yung premium sa GCash next week?"),
            ("taglish", "Ma-la-lapse ba agad yung policy ko pag na-late ako ng isang linggo?"),
            ("taglish", "Gusto ko sanang palitan yung beneficiary ko, yung asawa ko na lang."),
            ("taglish", "Kasama ba sa coverage yung rider for critical illness?"),
            ("filipino", "Wala pa po akong pera ngayon, sa sweldo pa po ako makakabayad."),
            ("filipino", "Kakausapin ko muna po ang asawa ko bago ako magdesisyon."),
            ("english", "When is my next premium due and how long is the grace period?"),
            ("colloquial", "Naku, gipit talaga kami ngayon eh, pwede bang sa katapusan na lang?"),
        ],
    },
    "id_multifinance": {
        "voices": {"native": [{"provider": "azure", "voice": "id-ID-ArdiNeural", "language": "id-ID"}],
                   "javanese_accent": [{"provider": "azure", "voice": "jv-ID-DimasNeural", "language": "jv-ID"}],
                   "sundanese_accent": [{"provider": "azure", "voice": "su-ID-JajangNeural", "language": "su-ID"}]},
        "terms": ["angsuran", "cicilan", "tenor", "denda", "dp", "jatuh tempo", "virtual account", "indomaret", "restrukturisasi"],
        "utterances": [
            ("formal", "Saya akan membayar angsuran sebelum tanggal jatuh tempo melalui virtual account."),
            ("formal", "Berapa denda keterlambatan jika saya terlambat tiga hari?"),
            ("loanwords", "DP saya dua puluh persen dan tenornya dua puluh empat bulan."),
            ("loanwords", "Saya mau transfer lewat mobile banking, nomor virtual account-nya berapa?"),
            ("colloquial", "Belum gajian nih Mbak, cicilannya nanti aja ya pas tanggal muda."),
            ("colloquial", "Udah bayar kok kemarin di Indomaret, kok masih ditagih sih?"),
            ("colloquial", "Usaha lagi sepi banget, bisa nggak dapat restrukturisasi?"),
            ("javanese_mix", "Nggih Mbak, angsurane kulo bayar minggu ngarep, mboten saget sakniki."),
        ],
    },
}
CANDIDATES = {
    "ph_life": [{"provider": "azure", "language": "fil-PH"}, {"provider": "gladia", "languages": ["tl", "en"]},
                {"provider": "deepgram", "model": "nova-3", "language": "multi"}],
    "id_multifinance": [{"provider": "deepgram", "model": "nova-3", "language": "id"},
                        {"provider": "deepgram", "model": "nova-2", "language": "id"},
                        {"provider": "azure", "language": "id-ID"}, {"provider": "gladia", "languages": ["id", "en"]}],
}
KEYS = {"deepgram": "DEEPGRAM_API_KEY", "azure": "AZURE_SPEECH_KEY", "gladia": "GLADIA_API_KEY"}


def norm(t: str) -> str:
    t = t.lower().replace("-", " ")
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", t)).strip()


async def transcribe(engine, pcm: np.ndarray, chunk_ms: int = 100) -> tuple[str, float]:
    from livekit import rtc
    from livekit.agents import stt as lk_stt

    stream = engine.stream()
    finals: list[str] = []
    done = asyncio.Event()
    last_final_at = [0.0]

    async def read():
        async for ev in stream:
            if ev.type == lk_stt.SpeechEventType.FINAL_TRANSCRIPT and ev.alternatives and ev.alternatives[0].text.strip():
                finals.append(ev.alternatives[0].text.strip())
                last_final_at[0] = time.monotonic()
        done.set()

    task = asyncio.ensure_future(read())
    step = SR * chunk_ms // 1000
    padded = np.concatenate([np.zeros(SR // 2, dtype=np.int16), pcm, np.zeros(SR * 2, dtype=np.int16)])
    t0 = time.monotonic()
    audio_end = None
    for i in range(0, len(padded), step):
        await asyncio.sleep(max(0.0, t0 + i / SR - time.monotonic()))
        chunk = padded[i:i + step]
        if len(chunk) < step:
            chunk = np.pad(chunk, (0, step - len(chunk)))
        stream.push_frame(rtc.AudioFrame(chunk.tobytes(), SR, 1, step))
        if audio_end is None and i >= SR // 2 + len(pcm):
            audio_end = time.monotonic()
    stream.end_input()
    try:
        await asyncio.wait_for(done.wait(), 8)
    except asyncio.TimeoutError:
        pass
    task.cancel()
    await stream.aclose()
    latency = (last_final_at[0] - audio_end) * 1000 if last_final_at[0] and audio_end else float("nan")
    return " ".join(finals), latency


async def run(market: str) -> dict:
    import aiohttp

    from stt_provider import build_stt

    pack = load_pack(market)
    spec = SETS[market]
    clips = []
    for vname, chain in spec["voices"].items():
        for kind, text in spec["utterances"]:
            try:
                pcm, _ = synth(text, chain)
            except Exception as exc:  # noqa: BLE001
                print(f"skip voice {vname}: {exc}")
                break
            clips.append({"voice": vname, "kind": kind, "text": text, "pcm": pcm})
    rows = []
    async with aiohttp.ClientSession() as http:
        for cand in CANDIDATES[market]:
            if not os.getenv(KEYS[cand["provider"]]):
                print(f"skip {cand}: no credentials")
                continue
            label = f"{cand['provider']}:{cand.get('model', '')}:{cand.get('language') or cand.get('languages')}"
            object.__setattr__(pack, "stt", [cand])
            for c in clips:
                engine = build_stt(pack, http_session=http, endpointing_ms=300)
                try:
                    hyp, lat = await transcribe(engine, c["pcm"])
                except Exception as exc:  # noqa: BLE001
                    hyp, lat = f"<error: {exc}>", float("nan")
                ref_n, hyp_n = norm(c["text"]), norm(hyp)
                terms = [t for t in spec["terms"] if t in ref_n]
                rows.append({"stt": label, "voice": c["voice"], "kind": c["kind"], "ref": c["text"], "hyp": hyp,
                             "wer": round(jiwer.wer(ref_n, hyp_n or "-"), 3), "cer": round(jiwer.cer(ref_n, hyp_n or "-"), 3),
                             "terms": len(terms), "terms_hit": sum(t in hyp_n for t in terms), "latency_ms": round(lat)})
                print(f"{label:<40} {c['voice']:<16} wer={rows[-1]['wer']:.2f} {hyp}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"asr_{market}.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUT / f"asr_{market}.md").write_text(render(market, rows), encoding="utf-8")
    return {"rows": len(rows)}


def render(market: str, rows: list[dict]) -> str:
    def agg(rs):
        lat = sorted(r["latency_ms"] for r in rs if r["latency_ms"] == r["latency_ms"])
        t = sum(r["terms"] for r in rs)
        return (f"{np.mean([r['wer'] for r in rs]):.2f}", f"{np.mean([r['cer'] for r in rs]):.2f}",
                f"{sum(r['terms_hit'] for r in rs)}/{t}" if t else "—", f"{lat[len(lat) // 2]}" if lat else "—")

    out = [f"# ASR bake-off — {market}", "", "Synthetic utterances (native TTS voices; accent rows use regional voices as a proxy).",
           "WER/CER on normalised text; latency = last final result after the end of audio.", "",
           "| STT | voice | n | WER | CER | finance terms | latency P50 (ms) |", "|---|---|---|---|---|---|---|"]
    for stt in dict.fromkeys(r["stt"] for r in rows):
        for voice in dict.fromkeys(r["voice"] for r in rows):
            rs = [r for r in rows if r["stt"] == stt and r["voice"] == voice]
            if rs:
                w, c, t, lat = agg(rs)
                out.append(f"| {stt} | {voice} | {len(rs)} | {w} | {c} | {t} | {lat} |")
    out += ["", "| STT | kind | WER |", "|---|---|---|"]
    for stt in dict.fromkeys(r["stt"] for r in rows):
        for kind in dict.fromkeys(r["kind"] for r in rows):
            rs = [r for r in rows if r["stt"] == stt and r["kind"] == kind]
            if rs:
                out.append(f"| {stt} | {kind} | {np.mean([r['wer'] for r in rs]):.2f} |")
    out += ["", "## Errors observed", ""]
    out += [f"- `{r['stt']}` [{r['voice']}/{r['kind']}] ref: “{r['ref']}” → hyp: “{r['hyp']}”" for r in rows if r["wer"] > 0.25][:40]
    return "\n".join(out) + "\n"


def main() -> None:
    import rtc_warmup
    rtc_warmup.warm()
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=list(SETS), required=True)
    asyncio.run(run(ap.parse_args().market))


if __name__ == "__main__":
    main()
