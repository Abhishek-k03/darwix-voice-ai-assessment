"use client";

import { RoomAudioRenderer, RoomContext, StartAudio } from "@livekit/components-react";
import { Room } from "livekit-client";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { HangUp, Mic } from "@/components/Icons";
import { NudgeFeed } from "@/components/NudgeFeed";
import { Shell } from "@/components/Shell";
import { groupTurns, useCopilot } from "@/lib/useCopilot";

function AdvisorDesk() {
  const params = useSearchParams();
  const roomName = params.get("room");
  const token = params.get("token");
  const [room, setRoom] = useState<Room | null>(null);
  const [error, setError] = useState("");
  const { transcript, nudges, connected } = useCopilot(roomName);

  async function join() {
    try {
      const r = new Room();
      await r.connect(process.env.NEXT_PUBLIC_LIVEKIT_URL ?? params.get("url") ?? "", token ?? "");
      await r.localParticipant.setMicrophoneEnabled(true);
      setRoom(r);
    } catch (e) { setError(String(e)); }
  }

  if (!roomName || !token) return <Shell><main className="dash"><div className="err">Missing room or token. Use the join link from an escalation.</div></main></Shell>;
  return (
    <Shell state={room ? "listening" : "page"} glow="corner" right={
      <div className="pill" role="status"><span className="dot" /><span>{room ? "On the call" : connected ? "Copilot ready" : "Connecting"}</span></div>
    }>
      <main className="dash">
        <div className="dtitle"><h1>Advisor desk · escalated call</h1><code>{roomName}</code></div>
        <p className="lead" style={{ margin: 0, maxWidth: 680 }}>The AI assistant has gone silent. The live copilot keeps listening and nudges you with what matters.</p>
        <div className="advisor">
          {!room
            ? <button className="start" style={{ height: 52 }} onClick={join}><Mic size={20} strokeWidth={2} />Join call</button>
            : <button className="end" onClick={() => { room.disconnect(); setRoom(null); }}><HangUp />Leave</button>}
        </div>
        {error && <div className="err" role="alert">{error}</div>}
        <div className="cols">
          <section className="box"><h2>Conversation so far</h2>
            <div className="scroll" style={{ maxHeight: "32rem" }}>
              {!transcript.length && <p className="empty">The conversation appears here.</p>}
              {groupTurns(transcript).filter((t) => t.final).map((t) => (
                <div key={t.utterance_id} className="turn" data-who={t.speaker} data-final>
                  <span className="mw">{t.speaker === "agent" ? "Assistant" : "Customer"}</span><p>{t.text}</p>
                </div>
              ))}
            </div>
          </section>
          <section className="box"><h2>Nudges for you</h2><NudgeFeed nudges={nudges} showInactive={false} /></section>
        </div>
      </main>
      {room && <RoomContext.Provider value={room}><RoomAudioRenderer /><StartAudio label="Enable audio" className="pv" /></RoomContext.Provider>}
    </Shell>
  );
}

export default function AdvisorPage() {
  return <Suspense fallback={<p style={{ padding: 24, color: "#A3A9B8" }}>Loading…</p>}><AdvisorDesk /></Suspense>;
}
