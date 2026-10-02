# Q1 evidence

| Item | Status | Location |
|---|---|---|
| Flow engine, rules and fast-path unit tests | ✅ passing | `backend/tests/test_engine.py`, `test_quick.py` |
| Recorded test calls: all five scenarios (simulated caller, fast replies on) | ✅ recorded 2026-10-02 | see the table below |
| Live call by a person | ⏳ pending | `evidence/calls/<ts>_in_health_web_<id>/` |

| Scenario | Call | Outcome | What it shows |
|---|---|---|---|
| Cooperative | `20261002-002350_in_health_cooperative_2fb5b84103` | callback_scheduled · **hot** · FamilyShield ₹14,920 | 7 of 10 turns used the short-answer fast path; disclosure before the quote; callback booked |
| Objection | `20261002-010348_in_health_objection_c009bc8adc` | qualified · **warm** · Secure ₹9,280 | Employer-cover and price objections answered from KB records (cited); callback declined, so a polite close with no second push |
| Incomplete / conflicting | `20261002-003816_in_health_conflicting_c5d03b31fa` | callback_scheduled · **warm** | "I'm actually 43, not 34" taken as a correction; unsure pre-existing answer handled by the LLM; budget unknown twice, so skipped |
| Out-of-scope | `20261002-005520_in_health_out_of_scope_7befbe1a99` | callback_scheduled · **hot** · Secure ₹12,900 | Car insurance and mutual-fund questions declined politely; US-treatment question answered from KB |
| Human request | `20261002-010709_in_health_human_request_6072ab07af` | **escalated** | Parents acknowledged; scripted handoff and CRM escalation with join link; one hold line, then silence |

Synthetic voices (Deepgram Aura, US accent) cause some recognition errors on Indian names ("Kiran" → "Kieran"). The native-speaker gap is documented in `docs/limitations_and_roadmap.md`.

Each call directory contains:
- `transcript.md` and `transcript.json`, with timestamps and KB citations per agent turn;
- `result.json`, with outcome, grade, fields, eligibility, CRM lead id, events and per-turn latency;
- `customer.flac`, `agent.flac`, `mixed.flac` and `stereo.flac`.

To generate the recordings: start the five processes in `README.md` → Run locally, then on `/` choose **in_health** and run each scenario (or `POST /sim/start {"pack":"in_health","scenario":"<name>"}`).
