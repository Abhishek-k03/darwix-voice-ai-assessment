# Q4: Live insights and nudges from call audio

The copilot is a silent LiveKit participant (`call-copilot`), dispatched into the **same room** as every call. It never publishes audio. It transcribes each participant's track separately, extracts signals in real time, and pushes short nudges to the agent's screen within seconds. This works in three settings:
- AI calls (Q1/Q3);
- human advisors after an escalation (`/agent` shows nudges beside the call);
- replayed recordings.

## Streaming input (three ways in, one pipeline)

| Mode | Command | What it proves |
|---|---|---|
| Live room | automatic for every web call / sim call | Production path: WebRTC audio, per-speaker tracks |
| Live replay | `uv run python -m sim.publish_wav <stereo.wav>` | A recording replayed in real time (10 ms frames) as two LiveKit participants, with the copilot dispatched |
| Offline replay | `uv run python -m copilot.replay <stereo.wav>` | The same recording streamed at real-time speed in 100 ms chunks straight into streaming STT, with no LiveKit; reproducible latency runs |
| Text replay | `uv run python -m copilot.replay <script.yaml> --text` | Perfect transcripts on a virtual clock; deterministic logic tests and ablation |

**Speaker separation:** agent and customer are separate tracks (WebRTC participants, or the L/R channels of the stereo recordings). Separation is therefore exact, with no diarization errors. A single-channel recording would need diarization (Deepgram `diarize`), which is noted as a limitation.

## Pipeline

```
audio frames (per speaker) ── mark table (frame arrival epoch-ms)
   └─► streaming STT (Deepgram Nova-3, interim + final, endpointing 300 ms)
         └─► Utterance{speaker, text, confidence, audio_received_at, asr_at}
               ├─► Tier 1 rules (<1 ms): compliance state machine, risky statements, opportunities
               │     (+ missed-opportunity escalation), buying / payment / callback / human, frustration EMA
               ├─► Tier 2 fast LLM (debounced ≥4 s, 8-turn window, 2.5 s cap, evidence-quote verification)
               └─► Nudge engine (controls) ─► hub WS ─► dashboard / advisor desk (display ack)
```

- **Transcription latency per chunk:** each STT result's `end_time` (audio seconds into the stream) is mapped through a frame-arrival table, ported from ai-ear, to the moment that audio reached the copilot. `asr_latency_ms = result_received − audio_end_received`. It is recorded for every interim and final result.

## Signal design (`packs/*/copilot.yaml`, `copilot/signals_rules.py`)

| Signal | Detection | Nudge (priority) |
|---|---|---|
| Compliance gap | A premium is quoted (agent) before the waiting-period / grace-period / late-fee disclosure | "Disclose waiting periods before quoting" (P1) |
| Recording disclosure | No "recorded" from the agent within 30 s of their first words | P1 |
| Risky statement | "claims are guaranteed", "covered from day one" for PED, asking for OTP/PIN, "not a deposit" confusion (PH), repossession or police threats (ID) | P1, with the correct statement |
| Cross-sell / opportunity | Customer mentions parents, family, illness or hardship, and the agent hasn't already covered it | P3 with the KB citation |
| **Missed opportunity** | The opportunity is not addressed within 2 agent turns or 25–30 s (auto-resolves if addressed) | P2, replaces the P3 card |
| Payment difficulty | "can't afford", "wala pa akong pera", "belum gajian", "kena PHK"… | P2 with the approved playbook citation |
| Buying signal | "how do I pay", "send the link", "bisa bayar sekarang" | P3 |
| Callback need | "call me tomorrow", "busy now", "lagi nyetir" | P3 |
| Human request | "talk to a real person", "makausap ang tao", "sambungkan ke petugas" | P2 |
| Rising frustration | EMA of lexicon hits, repetition of earlier statements (fuzzy) and LLM sentiment; fires only when the score is rising above 0.45 | P2 |
| Topic / intent shift | LLM `topic` per window, logged in metrics | informational |

The fast LLM tier adds signals the rules don't cover. Its evidence quote must appear (fuzzy ≥ 85) in the transcript window, or the signal is dropped: a hallucination guard.

## Nudge controls (`copilot/nudge_engine.py`)

Every candidate goes through these checks in order, and each decision is logged with its reason:
1. **Confidence threshold:** rules ≥ 0.6, LLM ≥ 0.75.
2. **Noise gate:** ASR confidence ≥ 0.6 (P1 exempt); customer utterances need at least 3 words.
3. **Repetition cap:** 2 per key per call; the second becomes "Reminder: …".
4. **Cooldown:** 60 s per key. A duplicate while the card is still active just refreshes its expiry.
5. **Topic grouping:** a same-topic, non-P1 signal merges into the active card's evidence.
6. **Priority replace:** a higher-priority card on the same topic supersedes the lower one (missed opportunity replaces the hint).
7. **Global rate limit:** at most one coaching nudge per 8 s. P1 compliance alerts bypass it and don't consume it.
8. **Max active cards:** 3. A new card displaces a lower-priority one; P1 is never hidden.

Cards also leave the screen by:
- **Expiry:** a TTL per template (30–60 s).
- **Auto-resolve:** when the agent says the disclosure or addresses the opportunity, the card closes with `resolved: agent_addressed`.

## Latency measurement

Stage stamps are epoch milliseconds (same clock in the copilot, hub and browser on one host):

`audio_received_at → asr_at → signal_at → nudge_at → sent_at → hub_received_at → displayed_at (browser ack)`

`uv run python -m copilot.report` produces `evidence/q4/latency_report.md`. It gives P50/P95 for:
- ASR (interim and final);
- rules;
- the LLM call;
- nudge generation;
- delivery (hub and display);
- end-to-end audio → display.

The live dashboard also shows running P50/P95.

**Results** (`evidence/q4/latency_report.md`: 10 real-time replays and 4 live-room runs; ms):

| stage | n | P50 | P95 |
|---|---|---|---|
| ASR, interim results | 756 | 488 | 1096 |
| ASR, final segments | 260 | 958 | 2413 |
| Signal extraction: rules | 27 | 0.1 | 0.2 |
| Signal extraction: LLM call | 54 | 564 | 1184 |
| Nudge generation | 28 | 0.0 | 0.1 |
| Delivery hub → display (ack) | 8 | 4.4 | 5.3 |
| Audio → nudge emitted | 28 | 942 | 2373 |
| End to end, audio → display | 8 | 1750 | 4442 |

- Speech recognition dominates: rules and nudge generation cost well under 1 ms, and the LLM tier runs in parallel and only adds a nudge when the rules miss it.
- The display figure comes from a **headless WebSocket client** (`copilot/dashboard_probe.py`) that acks on arrival, so it measures hub → client delivery, not browser rendering.
- Live-room runs play the scripted audio into a real LiveKit room with the copilot worker dispatched (`sim.publish_wav`); replays stream it directly into the pipeline (`copilot.replay`). Same code path from ASR onward.
- The longest end-to-end values are time-based nudges (for example "no recording disclosure in the first 30 s"), which fire on a timer rather than on an utterance.

## False-positive analysis

`copilot.report` produces `evidence/q4/fp_analysis.md` at two levels.

**1. Logic level** (perfect transcripts, deterministic), with controls on vs off on the six scripted scenarios:

| | nudges | true positives | false positives |
|---|---|---|---|
| Controls ON | 12 | all expected found | **0** |
| Controls OFF | 17 | all expected found | 3 (duplicate frustration and payment-difficulty cards) |

The benign scenarios (`clean_compliant`, `noisy_ambiguous` as text) produce at most one optional buying-signal nudge.

**2. Audio level:** the same scripts rendered to two-track audio by `sim.make_scripted_call` (synthetic Deepgram voices, babble at 5 dB SNR for `noisy_ambiguous`), replayed through streaming ASR in real time and also played into a live LiveKit room.

| | runs | nudges | true positives | missed | false positives |
|---|---|---|---|---|---|
| Controls ON (5 replays + 4 live-room runs) | 9 | 17 | 17 | 0 | 0 |
| Controls OFF (3 replays) | 3 | 9 | 8 | 0 | 0 (the extra card is a repeated `callback_need`, an optional expected nudge) |

Precision and recall are 1.00 over 12 audio runs. The noisy call produced no nudges. What the controls absorbed: `max_active` held back two lower-priority cards on the compliance call, `duplicate_active_refreshed` merged repeated frustration lines into one card, and `low_confidence` dropped one weak frustration reading.

**What the audio runs found (and fixed):**
1. ASR splits one agent question into two final segments, which counted as two agent turns and raised "missed opportunity" about 10 s early. Agent segments between customer turns now count once.
2. A "missed opportunity" held back by the global rate limit was never raised again. It is now retried after about 9 s.
3. On a noisy live-room run the copilot flagged "disclose waiting periods" because ASR garbled the agent's disclosure but still caught the quote. Absence-based compliance flags (`waiting_period_before_quote`, `recording_missing`) are now suppressed as `noisy_agent_audio` when the agent's last 30 s of audio was transcribed below 0.82 confidence. Statements that are present in the transcript ("guaranteed", "covered from day one") are not gated. This trades some recall in noise for fewer false alarms; it is unit-tested, and the specific false positive did not recur on the re-run because ASR output varies between runs.
4. Scoring windows opened when the trigger line ended, but nudges fire while it is spoken; they now open at the line start.

**Caveats:** the voices are clean synthetic English, so real phone audio will be harder. Under 5 dB babble ASR transcribed only 4 to 7 segments of the noisy call, so "no nudges" there is partly because little was heard. The Indonesian `collection_ethics` script is covered at logic level only until native Bahasa voices are available (Azure).

Required test coverage:

| Requirement | Scripted scenario |
|---|---|
| Missed cross-sell | `missed_cross_sell` (parents mentioned, ignored twice; hint then "Missed opportunity") |
| Skipped disclosure / risky statement | `compliance_risky` (quote before disclosure, "covered from day one", "claims are guaranteed", no recording disclosure); `collection_ethics` (ID: repossession threat) |
| Rising frustration | `rising_frustration` (re-asked questions, escalating complaints) |
| Noisy / ambiguous call | `noisy_ambiguous` (hesitations and backchannels, babble at 5 dB SNR; expect no nudges) |
| Clean call baseline | `clean_compliant` (false-positive control) |

Compliance example: `compliance_risky` and `collection_ethics`. Missed-opportunity example: `missed_cross_sell` and `collection_ethics` (hardship ignored).

## Limitations at 10x scale

| Pressure | What breaks | Mitigation |
|---|---|---|
| Concurrent streams | Each call opens 2 STT streams plus 1 fast-LLM call per ~4 s of customer speech. At 10x, Groq free-tier RPM/TPM is exhausted first. | Paid tier or self-hosted small model; batch classification across calls; rules-first with LLM only on ambiguity |
| Hub | Single-process in-memory fan-out | Redis pub/sub or NATS keyed by room; stateless hub replicas behind a load balancer; sticky WS |
| Workers | One copilot job per room | LiveKit dispatch already load-balances across worker processes; scale horizontally with `load_threshold` |
| Storage | JSONL metrics/events on local disk | Stream to ClickHouse/BigQuery; Langfuse/OTel traces |
| Clock skew | Cross-host stage stamps drift | NTP/PTP, or monotonic deltas measured per host and joined by event id |

## Limitations with noisy audio

- Noise lowers ASR confidence and WER rises, so keyword rules miss or misfire. The ASR-confidence gate (non-P1) and minimum-words gate suppress most noise-driven nudges. P1 compliance rules are only checked on agent audio, which is usually clean (headset).
- Babble and crosstalk on a single mixed channel would break speaker attribution. The design depends on separate tracks; mono recordings need diarization.
- Backchannels and hesitations ("hmm… okay… mm") are deliberately not signals.
- The LLM tier only runs on utterances of 3 words or more and must quote verbatim evidence.
- Optional WebRTC APM pre-processing before STT can be enabled with `COPILOT_APM=ns,hpf` (ported from ai-ear; it cut pure-noise RMS by about 70% in a self-check). ai-ear's own A/B found its effect on accuracy within run-to-run noise; a noise-robust STT is the bigger lever.
