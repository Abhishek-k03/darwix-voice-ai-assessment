# Known limitations and production-improvement plan

## Limitations (honest status)

| Area | Limitation |
|---|---|
| Data | All sources are synthetic, fictional brands built to exercise the pipeline. Real corpora bring scale, more formats (DOCX, scanned forms) and messier HTML. |
| KB | No OCR for scanned PDFs (flagged only); JS-rendered pages flagged, not rendered; gate thresholds calibrated on a small labelled set; Hinglish queries are weak (the held-out Hinglish query was rejected). |
| PII | spaCy small English NER; Tagalog and Indonesian names are covered only by patterns and context rules. |
| Voice | Free-tier LLM (Groq Llama 3.3 70B) and Azure F0 TTS. Rate limits cap concurrent calls. The deterministic engine keeps quality stable, but phrasing still varies per run. |
| Turn-taking | The base repo's arbiter LLM stage has a 100 ms timeout, so on the free tier it mostly falls back to regex heuristics (by design). |
| Telephony | Web calling only by default. A SIP number needs a LiveKit SIP trunk (Twilio or Telnyx), documented but not provisioned. |
| Test callers | Q1/Q3 recordings use an LLM persona caller with neural voices. Indonesian regional accents use Javanese/Sundanese voices as a proxy. Native speakers would score worse and are the real test. |
| Compliance | Regulatory rules (IRDAI-style disclosures, PH IC/BSP/DPA, ID OJK POJK 22/2023) are summarised from public knowledge, with no legal review; call windows are not enforced (no dialer). |
| Q4 | Speaker separation relies on separate tracks. The keyword-rule tier is language-specific and needs per-market maintenance. Latency is measured on one host (shared clock). |
| Recording | The bot channel is tapped at capture time. Audio flushed by a barge-in up to 400 ms later is still in the recording. |
| Security | The hub ingest uses a shared token; dashboards are unauthenticated; CORS is restricted to the frontend origin only. |

## Production-improvement plan

1. **Telephony and identity:** LiveKit SIP inbound/outbound trunks, number provisioning, an outbound dialer with call-window enforcement and DNC suppression, and stronger customer verification (OTP to the registered mobile on official channels).
2. **KB operations:**
   - a CMS-style ingestion queue with a human review UI for `needs_review`, quarantined and superseded items;
   - OCR (Tesseract or a cloud OCR) and Playwright rendering;
   - scheduled re-crawls with diffing, so changed policies auto-bump versions;
   - an active-version switch with rollback.
3. **Retrieval quality:** a larger labelled set per market, the multilingual cross-encoder rerank as the gate, Hinglish/Taglish query rewriting, and a feedback loop from agent citations and supervisor corrections.
4. **Voice quality:**
   - per-market LLM evaluation (naturalness, register, language lock) to pick models;
   - prompt caching;
   - native-speaker review of every script line;
   - ElevenLabs or Cartesia multilingual voices, and a custom Taglish lexicon for the TTS.
5. **Observability:** OpenTelemetry/Langfuse traces per turn (STT, extraction, KB, LLM TTFT, TTS first byte), per-call cost (the base repo's FINOPS counters wired to Redis), and alerts on fallback and escalation rates.
6. **Q4 at scale:** a Redis or NATS hub, stateless hub replicas, a ClickHouse metrics sink, batched LLM classification, per-tenant signal configs, a supervisor feedback button ("useful / not useful") feeding the threshold calibration, and diarization for mono recordings.
7. **Security and privacy:** dashboards behind SSO; per-tenant LiveKit projects; recordings encrypted at rest with retention policies; PII redaction on transcripts before storage; signed hub tokens per room.
8. **Testing:**
   - a nightly simulation suite (persona callers × packs) with LLM-judge scoring of groundedness, compliance and language lock;
   - load tests reusing ai-ear's concurrent-room isolation test;
   - the chaos scenarios in `CHAOS_TESTING.md`.
