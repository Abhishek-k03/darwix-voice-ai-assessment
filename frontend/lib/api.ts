export const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
export const WS_BACKEND = BACKEND.replace(/^http/, "ws");

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BACKEND}${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

export type Pack = { id: string; display_name: string; language: string; market: string; persona: string; company: string };
export type CallInfo = { token: string; url: string; room: string; call_id: string; copilot_url: string; pack: Pack };

export type KBHit = {
  record_id: string; title: string; content: string; category: string; doc_type: string; product: string | null;
  citation: string; version: string; effective_date: string | null; needs_review: boolean;
  conflicts: { fact: string; authoritative_record: string }[]; score: number; dense: number; coverage: number;
  matched_terms: string[]; source: { uri: string; page: number | null; section: string | null; type: string };
};
export type KBResult = { query: string; market: string; status: "ok" | "no_match" | "error"; latency_ms: number; kb_version: string; hits: KBHit[] };

export type Nudge = {
  id: string; type: string; priority: number; title: string; text: string; confidence: number; evidence?: string;
  citation?: string | null; topic?: string; status: "active" | "resolved" | "expired" | "superseded";
  created_at: number; expires_at: number; displayed_at?: number; reason?: string; escalated?: boolean;
  timeline?: Record<string, number>;
};
export type AnswerSeg = { t: string; c?: number };
export type AnswerSource = { n: number; record_id: string; title: string; path: string; snippet: string; rel: number; needs_review: boolean };
export type AnswerResult = {
  status: "ok" | "no_match"; query: string; market: string; kb_version: string; mode?: "llm" | "extractive";
  answer: AnswerSeg[][] | null; sources: AnswerSource[]; followups: string[]; search_ms: number; total_ms?: number;
};
export type RoomInfo = { room: string; last_seen: number; nudges: number };

export type CopilotTranscript = {
  type: "transcript"; utterance_id: string; speaker: "agent" | "customer"; text: string; final: boolean;
  asr_latency_ms?: number; confidence?: number; t?: number; start_s?: number; end_s?: number;
};
