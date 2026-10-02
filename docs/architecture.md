# Architecture

The four questions are built as one system. Q2 records feed Q1 answers, the Q3 market bots and Q4 nudge content. Q3 reuses the Q1 voice worker through configuration packs. Q4 listens to the same live LiveKit room as the call.

```mermaid
flowchart LR
  subgraph Browser["Next.js frontend"]
    C["/ call console<br/>(web calling, transcript,<br/>state, citations)"]
    K["/kb retrieval UI"]
    D["/copilot/[room]<br/>live nudge dashboard"]
    A["/agent advisor desk<br/>(escalation join + nudges)"]
  end

  subgraph API["FastAPI backend"]
    T["/calls, /sim/start<br/>token + explicit dispatch"]
    KB["/kb/search<br/>hybrid retriever (Q2)"]
    CRM["/crm/*<br/>leads, callbacks,<br/>escalations + webhook"]
    HUB["Copilot hub<br/>WS fan-out, polling,<br/>display acks"]
  end

  subgraph Room["LiveKit room (one per call)"]
    CU(("customer<br/>web / SIP / sim"))
    VA["voice-agent worker<br/>(Q1 / Q3 packs)"]
    CP["call-copilot worker<br/>(Q4, silent)"]
    ADV(("human advisor<br/>after escalation"))
  end

  C -- POST /calls --> T
  T -. dispatch .-> VA
  T -. dispatch .-> CP
  C <== WebRTC audio + data ==> Room
  VA -- per turn --> KB
  VA -- actions --> CRM
  CRM -- join link --> A
  A <== WebRTC ==> Room
  CP -- events --> HUB
  HUB -- WS --> D
  HUB -- WS --> A
  K --> KB
  CP -- citations --> KB

  subgraph Build["Offline KB build (Q2)"]
    SRC["web crawl, PDF, CSV/XLSX, MD"] --> PIPE["clean → normalize → PII → dedupe →<br/>conflicts → chunk → version"] --> IDX[("Chroma kb-x.y.z<br/>+ records.jsonl")]
  end
  IDX --> KB
```

## Voice agent turn (Q1/Q3)

```mermaid
sequenceDiagram
  participant U as Customer audio
  participant V as VAD + STT(pack)
  participant T as SemanticTurnCoordinator
  participant E as on_user_turn_completed
  participant L as LLM (Groq)
  participant S as TTS worker (persistent WS)
  U->>V: speech frames
  V->>T: interim / final transcripts, VAD silence
  T->>T: backchannel? pause on connector? (regex fast path, lexicon per language)
  T->>E: commit turn (barge-in kills bot audio)
  par in parallel
    E->>E: fast-LLM field extraction (JSON, 1.5 s cap)
    E->>E: KB /kb/search (~10 ms)
  end
  E->>E: FlowEngine: merge + conflicts + eligibility/pricing or reminder rules + actions
  alt pre-approved line (escalation, DNC, confirm, close)
    E->>S: script.yaml line (LLM skipped)
  else
    E->>L: [CALL STATE][KNOWLEDGE][NEXT STEP] note
    L->>S: token stream → clause buffer → audio
  end
  S->>U: own LiveKit audio track (+ recorder tap)
```

## Components

| Component | File(s) | Role |
|---|---|---|
| Voice worker | `backend/agent.py` | Base repo pipeline (manual turns, barge-in, idle watchdog, persistent TTS) plus the per-call controller, recorder and data-channel state |
| Packs | `backend/packs/<id>/` | Persona prompt, script lines, field schema and rules, compliance, STT/TTS chain, turn lexicon, copilot signals |
| Flow engine | `backend/voice/engine.py`, `rules.py`, `state.py`, `extract.py` | Deterministic qualification and reminder logic. The LLM only phrases replies. |
| KB | `backend/kb/` | Offline build pipeline, hybrid retriever, eval harness |
| Copilot | `backend/copilot/` | Per-speaker streaming STT, rule and LLM signals, nudge controls, hub client, replay, report |
| Simulation | `backend/sim/` | LLM persona caller, scripted two-track calls, real-time WAV publisher, ASR bench |
| API | `backend/main.py`, `backend/api/` | KB service, calls/dispatch, mock CRM, copilot hub |
| Frontend | `frontend/app/` | Voice console, knowledge page, copilot rooms and dashboard, advisor desk |

## Latency budget (voice turn)

| Stage | Target | Notes |
|---|---|---|
| VAD silence | 400 ms | Silero `min_silence_duration`; 1,200 ms when the speaker pauses on a connector |
| Extraction ∥ retrieval | ≤ 600 ms (extract), ~10 ms (KB) | Run in parallel, hard 1.5 s cap; on timeout the turn proceeds |
| LLM TTFT | 150–350 ms | Groq Llama 3.3 70B |
| TTS first audio | 100–300 ms | Azure (per clause) / Deepgram Aura (WebSocket) |

Measured per-turn values are logged in each call's `result.json` (`events` → `trace` / `llm_metrics`).
