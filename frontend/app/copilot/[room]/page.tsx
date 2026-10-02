"use client";

import { use } from "react";
import { NudgeFeed } from "@/components/NudgeFeed";
import { Shell } from "@/components/Shell";
import { groupTurns, percentile, useCopilot } from "@/lib/useCopilot";

export default function CopilotDashboard({ params }: { params: Promise<{ room: string }> }) {
  const { room } = use(params);
  const { transcript, nudges, signals, stats, connected } = useCopilot(room);
  const stat = (xs: number[]) => (xs.length ? `${percentile(xs, 0.5)} / ${percentile(xs, 0.95)} ms` : "—");
  const suppressed = Object.entries(stats.suppressed);
  return (
    <Shell state={connected ? "page" : "error"} glow="corner" right={
      <div className="pill" role="status"><span className="dot" /><span>{connected ? "Connected" : "Reconnecting"}</span></div>
    }>
      <main className="dash">
        <div className="dtitle"><h1>Live call copilot</h1><code>{room}</code></div>
        <section className="stats" aria-label="Latency">
          <div className="stat"><span className="mono">End to end · P50 / P95</span><b>{stat(stats.e2e)}</b></div>
          <div className="stat"><span className="mono">ASR lag · P50 / P95</span><b>{stat(stats.asr)}</b></div>
          <div className="stat"><span className="mono">Delivery · P50 / P95</span><b>{stat(stats.delivery)}</b></div>
          <div className="stat"><span className="mono">Suppressed</span><b>{suppressed.length ? suppressed.map(([k, v]) => `${k} ${v}`).join(" · ") : "0"}</b></div>
        </section>
        <div className="cols">
          <section className="box">
            <h2>Transcript</h2>
            <div className="scroll" style={{ maxHeight: "34rem" }}>
              {!transcript.length && <p className="empty">Waiting for audio from the call.</p>}
              {groupTurns(transcript).map((t) => (
                <div key={t.utterance_id} className="turn" data-who={t.speaker} data-final={t.final}>
                  <span className="mw">{t.speaker === "agent" ? "Agent" : "Customer"}{t.asr_latency_ms ? ` · ${t.asr_latency_ms} ms` : ""}</span>
                  <p>{t.text}</p>
                </div>
              ))}
            </div>
          </section>
          <section className="box">
            <h2>Nudges</h2>
            <div className="scroll" style={{ maxHeight: "24rem" }}><NudgeFeed nudges={nudges} /></div>
            <h2 style={{ marginTop: 6 }}>Signal timeline</h2>
            <ul className="tl scroll" style={{ maxHeight: "9rem" }}>
              {!signals.length && <li>No signals yet.</li>}
              {[...signals].reverse().map((s, i) => (
                <li key={i}>{s.source} · {s.type}{s.label ? `/${s.label}` : ""} · {Math.round(s.confidence * 100)}%{s.evidence ? ` · “${s.evidence}”` : ""}</li>
              ))}
            </ul>
          </section>
        </div>
      </main>
    </Shell>
  );
}
