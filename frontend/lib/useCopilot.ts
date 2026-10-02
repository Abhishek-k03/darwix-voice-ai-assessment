"use client";

import { useEffect, useRef, useState } from "react";
import { CopilotTranscript, Nudge, WS_BACKEND } from "./api";

export type SignalEvent = { type: string; label?: string; confidence: number; source: string; speaker?: string; evidence?: string; t: number };
export type Stats = { e2e: number[]; asr: number[]; delivery: number[]; suppressed: Record<string, number> };

/** Subscribes to the copilot hub for one room; acks each nudge when rendered (display latency). */
export function useCopilot(room: string | null) {
  const [transcript, setTranscript] = useState<CopilotTranscript[]>([]);
  const [nudges, setNudges] = useState<Record<string, Nudge>>({});
  const [signals, setSignals] = useState<SignalEvent[]>([]);
  const [stats, setStats] = useState<Stats>({ e2e: [], asr: [], delivery: [], suppressed: {} });
  const [connected, setConnected] = useState(false);
  const ws = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!room) return;
    let closed = false;
    let retry: ReturnType<typeof setTimeout>;

    const handle = (ev: Record<string, unknown>) => {
      switch (ev.type) {
        case "transcript": {
          const t = ev as unknown as CopilotTranscript;
          setTranscript((prev) => {
            const i = prev.findIndex((p) => p.utterance_id === t.utterance_id);
            if (i >= 0) { const next = prev.slice(); next[i] = t; return next; }
            return [...prev.slice(-200), t];
          });
          if (t.final && typeof t.asr_latency_ms === "number") {
            setStats((s) => ({ ...s, asr: [...s.asr.slice(-500), t.asr_latency_ms as number] }));
          }
          break;
        }
        case "nudge":
        case "nudge_update": {
          const n = ev.nudge as Nudge;
          setNudges((prev) => ({ ...prev, [n.id]: { ...(prev[n.id] ?? {}), ...n } }));
          if (ev.type === "nudge" && ws.current?.readyState === WebSocket.OPEN) {
            const displayed = Date.now();
            requestAnimationFrame(() =>
              ws.current?.send(JSON.stringify({ type: "ack", nudge_id: n.id, displayed_at: displayed })),
            );
            const tl = n.timeline ?? {};
            if (tl.audio_received_at) {
              setStats((s) => ({
                ...s,
                e2e: [...s.e2e.slice(-500), displayed - tl.audio_received_at],
                delivery: tl.nudge_at ? [...s.delivery.slice(-500), displayed - tl.nudge_at] : s.delivery,
              }));
            }
          }
          break;
        }
        case "signal":
          setSignals((prev) => [...prev.slice(-100), { ...(ev.signal as SignalEvent), t: Date.now() }]);
          break;
        case "suppressed":
          setStats((s) => ({ ...s, suppressed: { ...s.suppressed, [String(ev.reason)]: (s.suppressed[String(ev.reason)] ?? 0) + 1 } }));
          break;
        case "snapshot":
          (ev.events as Record<string, unknown>[]).forEach((e) => { if (e.type !== "nudge") handle(e); else {
            const n = e.nudge as Nudge; setNudges((prev) => ({ ...prev, [n.id]: { ...(prev[n.id] ?? {}), ...n } }));
          } });
          break;
      }
    };

    const connect = () => {
      const sock = new WebSocket(`${WS_BACKEND}/ws/copilot/${room}`);
      ws.current = sock;
      sock.onopen = () => setConnected(true);
      sock.onclose = () => { setConnected(false); if (!closed) retry = setTimeout(connect, 1500); };
      sock.onmessage = (m) => handle(JSON.parse(m.data));
    };
    connect();
    return () => { closed = true; clearTimeout(retry); ws.current?.close(); };
  }, [room]);

  return { transcript, nudges: Object.values(nudges), signals, stats, connected };
}

const TURN_GAP_S = 2.5;

/** STT finalises long speech in several segments; show consecutive same-speaker segments as one turn. */
export function groupTurns(segments: CopilotTranscript[]): CopilotTranscript[] {
  const turns: CopilotTranscript[] = [];
  for (const s of segments) {
    const last = turns[turns.length - 1];
    const gap = (s.start_s ?? 0) - (last?.end_s ?? 0);
    if (last && last.speaker === s.speaker && last.final && gap < TURN_GAP_S) {
      turns[turns.length - 1] = {
        ...s, utterance_id: last.utterance_id, text: `${last.text} ${s.text}`,
        asr_latency_ms: s.final ? s.asr_latency_ms : last.asr_latency_ms,
      };
    } else {
      turns.push(s);
    }
  }
  return turns;
}

export function percentile(xs: number[], p: number): number | null {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  return Math.round(s[Math.min(s.length - 1, Math.floor(p * (s.length - 1)))]);
}
