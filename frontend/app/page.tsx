"use client";

import { RoomAudioRenderer, RoomContext, StartAudio } from "@livekit/components-react";
import { useEffect, useState } from "react";
import { HangUp, Chat, Mic, MicOff, Speaker, SpeakerOff } from "@/components/Icons";
import { Orb } from "@/components/Orb";
import { Shell } from "@/components/Shell";
import { TranscriptPanel } from "@/components/TranscriptPanel";
import { api, Pack } from "@/lib/api";
import { useCall } from "@/lib/useCall";

const SCENARIOS: Record<string, string[]> = {
  in_health: ["cooperative", "objection", "conflicting", "out_of_scope", "human_request"],
  ph_life: ["cooperative_taglish", "objection_escalation"],
  id_multifinance: ["cooperative_formal", "colloquial_regional"],
};
const PACK_LABEL: Record<string, string> = {
  in_health: "India · English", in_health_hi: "India · Hindi", ph_life: "Philippines · Taglish", id_multifinance: "Indonesia · Bahasa",
};
const mmss = (s: number) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
const label = (s: string) => s.replace(/_/g, " ");

export default function VoicePage() {
  const c = useCall();
  const [packs, setPacks] = useState<Pack[]>([]);
  const [packId, setPackId] = useState("in_health");
  const [panel, setPanel] = useState(false);
  const [scenario, setScenario] = useState("cooperative");
  const [sim, setSim] = useState<{ room: string } | null>(null);
  const [simBusy, setSimBusy] = useState(false);
  const [note, setNote] = useState("");
  const [online, setOnline] = useState<boolean | null>(null);

  useEffect(() => { api<Pack[]>("/packs").then(setPacks).catch((e) => setNote(String(e))); }, []);
  useEffect(() => {      // is the service reachable? (the pill reads Online / Offline when no call is running)
    const ping = () => api("/packs").then(() => setOnline(true)).catch(() => setOnline(false));
    ping();
    const id = setInterval(ping, 10_000);
    return () => clearInterval(id);
  }, []);

  const pack = packs.find((p) => p.id === packId);
  const persona = c.call?.pack.persona ?? pack?.persona ?? "Mira";
  const st = c.status;
  const idle = st === "idle" || st === "ended";
  const connected = st === "connecting" || st === "listening" || st === "processing" || st === "speaking";
  const live = connected && st !== "connecting";
  const orbStatus = st === "ended" ? "idle" : st;
  const last = c.lines[c.lines.length - 1];
  const showCap = !!last && (st === "listening" || st === "processing" || st === "speaking");
  const scenarios = SCENARIOS[packId] ?? [];

  const copy = {
    idle: ["Ready when you are", `Start a conversation and talk to ${persona} like you would a person.`],
    connecting: ["Connecting", "Opening a secure line…"],
    listening: c.micOn ? ["Listening", "Go ahead, I'm all ears."] : ["Mic is muted", "Unmute to continue speaking."],
    processing: ["Thinking", "Working out the best answer…"],
    speaking: ["Speaking", `${persona} is replying.`],
    error: ["Connection lost", c.error || "We couldn't reach the assistant. Check your network and try again."],
    ended: ["Call ended", c.ended ? "Thanks for talking. Here is how the call went." : c.error || "The conversation has finished."],
  }[st];

  async function runSim() {
    setNote(""); setSimBusy(true);
    try { setSim(await api("/sim/start", { method: "POST", body: JSON.stringify({ pack: packId, scenario }) })); }
    catch (e) { setNote(String(e)); }
    finally { setSimBusy(false); }
  }

  const volumes = () => ({ agent: c.vols.current.agent, mic: c.vols.current.mic });

  return (
    <Shell state={st} glow="center" fixed right={
      <div className="pill" role="status"><span className={`dot${idle ? (online ? " on" : online === false ? " off" : "") : ""}`} />
        <span>{idle ? (online === null ? "Checking" : online ? "Online" : "Offline") : { connecting: "Connecting", listening: "Live", processing: "Live", speaking: "Live", error: "Disconnected" }[st as "connecting"]}</span>
        {live && <span className="clock">{mmss(c.elapsed)}</span>}
      </div>
    }>
      <main className="stage enter">
        <Orb status={orbStatus} mic={c.micOn} volumes={volumes} />
        <h1 className="ttl" aria-live="polite">{copy[0]}</h1>
        <p className="sub">{copy[1]}</p>
        <span className="chip" data-live={live ? (c.micOn ? "on" : "off") : "hide"}><Mic size={14} strokeWidth={2} />{c.micOn ? "Microphone live" : "Microphone muted"}</span>
        <div className="cap" data-show={showCap ? "yes" : "no"}>
          <span className="who">{last?.role === "agent" ? persona : "You"}</span><p>{last?.text}</p>
        </div>

        {idle && packs.length > 1 && (
          <div className="packs" role="group" aria-label="Use case and market">
            {packs.map((p) => <button key={p.id} className="pv" data-on={p.id === packId ? "on" : "off"} aria-pressed={p.id === packId}
              onClick={() => { setPackId(p.id); setScenario((SCENARIOS[p.id] ?? [""])[0]); }}>{PACK_LABEL[p.id] ?? p.display_name}</button>)}
          </div>
        )}

        {c.escalation && (
          <div className="card warn notes" role="status">
            <span><b>Handed to a human advisor</b>{c.escalation.reason ? ` (${c.escalation.reason})` : ""}.</span>
            {c.escalation.join_url
              ? <span>Advisor desk: <a href={c.escalation.join_url} target="_blank" rel="noreferrer">open the join link ↗</a>. The live copilot keeps nudging them.</span>
              : <span>No join link: the backend was unreachable.</span>}
          </div>
        )}
        {st === "ended" && c.ended && (
          <div className="card ok notes" role="status">
            <dl className="kv">
              <dt>outcome</dt><dd>{String(c.ended.outcome)}</dd><dt>grade</dt><dd>{String(c.ended.grade ?? "n/a")}</dd><dt>lead</dt><dd>{String(c.ended.lead_id ?? "n/a")}</dd>
            </dl>
          </div>
        )}
        {note && <div className="err" role="alert">{note}</div>}

        <div className="dock">
          {idle && <button className="start" onClick={() => c.start(packId)}><Mic size={22} strokeWidth={2} />{st === "ended" ? "Start a new conversation" : "Start conversation"}</button>}
          {idle && c.lines.length > 0 && (
            <div className="dk"><button className="ib" data-on={panel ? "on" : "off"} aria-pressed={panel} aria-label="Transcript" onClick={() => setPanel(!panel)}><Chat /></button><span className="lab">Transcript</span></div>
          )}
          {st === "error" && <button className="retry" onClick={() => c.start(packId)}>Reconnect</button>}
          {connected && <>
            <div className="dk"><button className="ib" data-on={c.micOn ? "on" : "off"} aria-pressed={c.micOn} aria-label="Microphone" onClick={c.toggleMic}>{c.micOn ? <Mic /> : <MicOff />}</button><span className="lab">{c.micOn ? "Mute" : "Unmute"}</span></div>
            <div className="dk"><button className="ib" data-on={c.spkOn ? "on" : "off"} aria-pressed={c.spkOn} aria-label="Speaker" onClick={c.toggleSpk}>{c.spkOn ? <Speaker /> : <SpeakerOff />}</button><span className="lab">{c.spkOn ? "Speaker" : "Muted"}</span></div>
            <div className="dk"><button className="ib" data-on={panel ? "on" : "off"} aria-pressed={panel} aria-label="Transcript" onClick={() => setPanel(!panel)}><Chat /></button><span className="lab">Transcript</span></div>
            <div className="dk"><button className="end" onClick={() => { c.end(); setPanel(false); }}><HangUp />End call</button><span className="lab">&nbsp;</span></div>
          </>}
        </div>
        {connected && c.call && <a className="chip" data-live="on" href={`/copilot/${c.call.room}`} target="_blank" rel="noreferrer">Open live copilot ↗</a>}
        {sim && idle && <p className="sub">Simulated call running in <code>{sim.room}</code>: <a href={`/copilot/${sim.room}`} target="_blank" rel="noreferrer" style={{ textDecoration: "underline" }}>watch transcript and nudges ↗</a>. Recordings land in <code>evidence/calls/</code>.</p>}
      </main>

      {idle && scenarios.length > 0 && (
        <div className="prev" role="group" aria-label="Simulated caller">
          <span className="mono">Simulated caller</span>
          {scenarios.map((s) => <button key={s} className="pv" data-on={s === scenario ? "on" : "off"} onClick={() => setScenario(s)}>{label(s)}</button>)}
          <button className="pv run" disabled={simBusy} onClick={runSim}>{simBusy ? "Starting…" : "Run"}</button>
        </div>
      )}

      <TranscriptPanel open={panel} onClose={() => setPanel(false)} lines={c.lines} persona={persona} state={c.state} rag={c.rag}
        live={live} onSend={c.sendText} />
      {c.room && <RoomContext.Provider value={c.room}><RoomAudioRenderer /><StartAudio label="Click to enable audio" className="pv" /></RoomContext.Provider>}
    </Shell>
  );
}
