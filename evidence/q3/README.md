# Q3 evidence

| Item | Status | Location |
|---|---|---|
| Reminder-flow unit tests (verification, privacy, spoken forms, resolution paths) | ✅ passing (7) | `backend/tests/test_reminder.py` |
| Turn-taking lexicons (tl / id backchannels and connectors) | ✅ verified | `backend/turn_arbiter.py` |
| ASR bake-off: Philippines | ⏳ pending (needs Azure; Gladia/Deepgram optional) | `asr_ph_life.md` / `.json` |
| ASR bake-off: Indonesia (incl. Javanese/Sundanese accent proxy) | ⏳ pending (needs Deepgram + Azure) | `asr_id_multifinance.md` / `.json` |
| Recorded calls: PH `cooperative_taglish`, `objection_escalation` | ⏳ pending live run | `evidence/calls/*ph_life*` |
| Recorded calls: ID `cooperative_formal`, `colloquial_regional` | ⏳ pending live run | `evidence/calls/*id_multifinance*` |

Configurations, terminology, localization examples, code-switching notes, comparison and known gaps: `docs/q3_localization.md`.
