"""Render scripted two-party calls (sim/scripts/<pack>/<id>.yaml) to audio for the Q4 replay:
separate agent/customer tracks (16 kHz), stereo (L=agent, R=customer), optional noise at a target SNR,
and labels.json with line timings + expected nudges. TTS results are cached to avoid re-billing.

  uv run python -m sim.make_scripted_call sim/scripts/in_health/*.yaml
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import httpx
import numpy as np
import soundfile as sf
import yaml
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "evidence" / "q4" / "scripted"
CACHE = ROOT / "data" / "tts_cache"
SR = 16000


def _azure(text: str, voice: str, language: str) -> np.ndarray:
    import azure.cognitiveservices.speech as speechsdk
    from xml.sax.saxutils import escape

    cfg = speechsdk.SpeechConfig(subscription=os.environ["AZURE_SPEECH_KEY"], region=os.environ["AZURE_SPEECH_REGION"])
    cfg.set_speech_synthesis_output_format(speechsdk.SpeechSynthesisOutputFormat.Raw16Khz16BitMonoPcm)
    synth = speechsdk.SpeechSynthesizer(speech_config=cfg, audio_config=None)
    ssml = (f"<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='{language}'>"
            f"<voice name='{voice}'>{escape(text)}</voice></speak>")
    res = synth.speak_ssml_async(ssml).get()
    if res.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
        raise RuntimeError(f"azure tts failed: {res.cancellation_details.error_details if res.cancellation_details else res.reason}")
    return np.frombuffer(res.audio_data, dtype=np.int16)


def _deepgram(text: str, voice: str) -> np.ndarray:
    r = httpx.post("https://api.deepgram.com/v1/speak", timeout=30,
                   params={"model": voice, "encoding": "linear16", "sample_rate": SR, "container": "none"},
                   headers={"Authorization": f"Token {os.environ['DEEPGRAM_API_KEY']}"}, json={"text": text})
    r.raise_for_status()
    return np.frombuffer(r.content, dtype=np.int16)


def synth(text: str, chain: list[dict]) -> tuple[np.ndarray, str]:
    for v in chain:
        p = v["provider"]
        if p == "azure" and not os.getenv("AZURE_SPEECH_KEY") or p == "deepgram" and not os.getenv("DEEPGRAM_API_KEY"):
            continue
        key = hashlib.sha1(f"{p}|{v['voice']}|{text}".encode()).hexdigest()[:16]
        cached = CACHE / f"{key}.npy"
        if cached.exists():
            return np.load(cached), f"{p}:{v['voice']}"
        pcm = _azure(text, v["voice"], v.get("language", "en-US")) if p == "azure" else _deepgram(text, v["voice"])
        CACHE.mkdir(parents=True, exist_ok=True)
        np.save(cached, pcm)
        return pcm, f"{p}:{v['voice']}"
    raise RuntimeError("no TTS credentials (AZURE_SPEECH_KEY or DEEPGRAM_API_KEY)")


def _rms(x: np.ndarray) -> float:
    x = x.astype(np.float64)
    voiced = x[np.abs(x) > 100]
    return float(np.sqrt(np.mean(voiced ** 2))) if len(voiced) else 1.0


def add_noise(track: np.ndarray, noise: np.ndarray, snr_db: float) -> np.ndarray:
    scale = _rms(track) / (_rms(noise) * 10 ** (snr_db / 20))
    mixed = track.astype(np.float64) + noise[: len(track)].astype(np.float64) * scale
    return np.clip(mixed, -32768, 32767).astype(np.int16)


def render(script_path: Path, seed: int = 7) -> Path:
    s = yaml.safe_load(script_path.read_text(encoding="utf-8"))
    rng = np.random.default_rng(seed)
    clips, voices = [], {}
    for spk, text in s["lines"]:
        pcm, used = synth(text, s["voices"][spk])
        voices[spk] = used
        clips.append((spk, text, pcm))
    total = int(SR * (1.0 + sum(len(c[2]) / SR + 0.9 for c in clips)))
    tracks = {"agent": np.zeros(total, dtype=np.int16), "customer": np.zeros(total, dtype=np.int16)}
    cursor, lines = 0.5, []
    for i, (spk, text, pcm) in enumerate(clips, start=1):
        start = int(cursor * SR)
        tracks[spk][start:start + len(pcm)] = pcm
        end = cursor + len(pcm) / SR
        lines.append({"line": i, "speaker": spk, "text": text, "start_s": round(cursor, 2), "end_s": round(end, 2)})
        cursor = end + float(rng.uniform(0.45, 0.9))
    n = int((cursor + 0.5) * SR)
    a, c = tracks["agent"][:n], tracks["customer"][:n]
    noise_cfg = s.get("noise")
    if noise_cfg:
        if noise_cfg["type"] == "babble":
            pool = np.concatenate([p for _, _, p in clips]).astype(np.float64)
            babble = sum(np.roll(np.resize(pool, n), int(rng.integers(0, len(pool)))) for _ in range(5))
            noise = babble
        else:
            noise = rng.normal(0, 1000, n)
        a, c = add_noise(a, noise, noise_cfg["snr_db"]), add_noise(c, np.roll(noise, SR), noise_cfg["snr_db"])
    out = OUT / s["id"]
    out.mkdir(parents=True, exist_ok=True)
    sf.write(out / "agent.wav", a, SR)
    sf.write(out / "customer.wav", c, SR)
    sf.write(out / "stereo.wav", np.stack([a, c], axis=1), SR)
    sf.write(out / "mixed.wav", np.clip(a.astype(np.int32) + c.astype(np.int32), -32768, 32767).astype(np.int16), SR)
    expected = []
    for e in s.get("expected", []):
        end = lines[e["line"] - 1]["end_s"]
        expected.append({**e, "window_s": [lines[e["line"] - 1]["start_s"], round(end + e.get("within_s", 10), 2)]})
    labels = {"id": s["id"], "pack": s["pack"], "description": s.get("description"), "voices": voices,
              "noise": noise_cfg, "duration_s": round(n / SR, 2), "lines": lines, "expected": expected}
    (out / "labels.json").write_text(json.dumps(labels, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scripts", nargs="+")
    for p in ap.parse_args().scripts:
        try:
            print("rendered", render(Path(p)))
        except Exception as exc:  # noqa: BLE001
            print(f"failed {p}: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
