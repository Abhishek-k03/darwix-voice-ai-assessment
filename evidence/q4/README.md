# Q4 evidence

| Item | Status | Location |
|---|---|---|
| Copilot logic unit tests (scenarios + controls) | ✅ passing (10) | `backend/tests/test_copilot.py` |
| Logic-level false-positive analysis (controls on vs off, 6 scenarios) | ✅ generated | `fp_analysis.md` |
| Scenario audio (two tracks, labels, babble noise at 5 dB SNR) | ✅ 5 English scenarios rendered (Indonesian one needs Azure voices) | `scripted/<scenario>/` |
| Real-time replays through streaming ASR (10 runs: 5 scenarios, 3 controls-off ablations, 2 recorded Q1 calls) | ✅ | `replays/<run>/`, `latency_report.md`, `fp_analysis.md` |
| Live-room runs (scripted audio played into LiveKit with the copilot dispatched, headless dashboard acks) | ✅ 4 runs | `metrics/live-*.jsonl`, `events/live-*.jsonl` |
| Browser dashboard demo for the video | ⏳ user task: open `/copilot/<room>` while running `sim.publish_wav` | — |

Result: precision and recall 1.00 over 12 audio runs, noisy call quiet; E2E audio → display P50 1.75 s, P95 4.4 s (headless client). Method, signal design, fixes found by the replays and limitations: `docs/q4_realtime.md`.

Regenerate the reports with `uv run python -m copilot.report` (from `backend/`). Method, signal design, nudge logic and scale/noise limitations: `docs/q4_realtime.md`.
