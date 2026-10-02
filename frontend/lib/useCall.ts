"use client";

import { createAudioAnalyser, LocalAudioTrack, RemoteAudioTrack, Room, RoomEvent, Track } from "livekit-client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, CallInfo } from "./api";
import type { Status } from "./orb";

export type Line = { role: "agent" | "customer"; text: string; t: number; citations?: string[]; kind?: string };
export type RagStatus = { query: string; status: string; used: string[]; hits: { record_id: string; title: string; citation: string; dense: number }[] };
export type CallState = {
  stage: string; fields: Record<string, unknown>; missing: string[]; conflicts: { field: string; old: unknown; new: unknown }[];
  eligibility: Record<string, unknown> | null; escalated: boolean; handoff: boolean; callback: { when: string } | null; outcome: string | null;
};
export type UiStatus = Status | "ended";
type Analyser = { calculateVolume: () => number; cleanup: () => void };

const JOIN_TIMEOUT_MS = 30_000;

/** One web call: LiveKit room, the agent's data topics, mic/speaker control and live audio levels for the avatar. */
export function useCall() {
  const [call, setCall] = useState<CallInfo | null>(null);
  const [room, setRoom] = useState<Room | null>(null);
  const [phase, setPhase] = useState<"idle" | "connecting" | "live" | "error" | "ended">("idle");
  const [agent, setAgent] = useState<"listening" | "thinking" | "speaking" | null>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const [state, setState] = useState<CallState | null>(null);
  const [rag, setRag] = useState<RagStatus | null>(null);
  const [escalation, setEscalation] = useState<{ join_url?: string; reason?: string } | null>(null);
  const [ended, setEnded] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");
  const [micOn, setMicOn] = useState(true);
  const [spkOn, setSpkOn] = useState(true);
  const [elapsed, setElapsed] = useState(0);

  const roomRef = useRef<Room | null>(null);
  const spkRef = useRef(true);
  const vols = useRef({ agent: 0, mic: 0 });
  const analysers = useRef<{ agent?: Analyser; mic?: Analyser }>({});
  const joinTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const finished = useRef(false);

  const teardown = useCallback(() => {
    if (joinTimer.current) clearTimeout(joinTimer.current);
    analysers.current.agent?.cleanup();
    analysers.current.mic?.cleanup();
    analysers.current = {};
    vols.current = { agent: 0, mic: 0 };
    roomRef.current?.disconnect();
    roomRef.current = null;
    setRoom(null);
  }, []);

  useEffect(() => {
    const id = setInterval(() => {
      vols.current.agent = analysers.current.agent?.calculateVolume() ?? 0;
      vols.current.mic = analysers.current.mic?.calculateVolume() ?? 0;
    }, 60);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    if (phase !== "live") return;
    const t0 = Date.now() - elapsed * 1000;
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - t0) / 1000)), 1000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase]);

  useEffect(() => () => teardown(), [teardown]);

  const start = useCallback(async (pack: string) => {
    finished.current = false;
    setError(""); setLines([]); setState(null); setRag(null); setEscalation(null); setEnded(null);
    setAgent(null); setElapsed(0); setMicOn(true); setPhase("connecting");
    try {
      const info = await api<CallInfo>("/calls", { method: "POST", body: JSON.stringify({ pack }) });
      setCall(info);
      const r = new Room({ adaptiveStream: true, dynacast: true });
      const decoder = new TextDecoder();
      r.on(RoomEvent.DataReceived, (payload, _p, _k, topic) => {
        let msg;
        try { msg = JSON.parse(decoder.decode(payload)); } catch { return; }
        if (topic === "transcript") setLines((prev) => [...prev, msg]);
        else if (topic === "call-state") setState(msg);
        else if (topic === "rag-status") setRag(msg);
        else if (topic === "escalation") setEscalation(msg);
        else if (topic === "agent-state") {
          if (joinTimer.current) { clearTimeout(joinTimer.current); joinTimer.current = null; }
          setAgent(msg.state);
        } else if (topic === "call-ended") {
          finished.current = true;
          setEnded(msg);
          setTimeout(() => { setPhase("ended"); teardown(); }, 800);
        }
      });
      r.on(RoomEvent.TrackSubscribed, (track) => {
        if (track.kind !== Track.Kind.Audio) return;
        (track as RemoteAudioTrack).setVolume(spkRef.current ? 1 : 0);
        analysers.current.agent?.cleanup();
        analysers.current.agent = createAudioAnalyser(track as RemoteAudioTrack);
      });
      r.on(RoomEvent.LocalTrackPublished, (pub) => {
        if (pub.kind !== Track.Kind.Audio || !pub.track) return;
        analysers.current.mic?.cleanup();
        analysers.current.mic = createAudioAnalyser(pub.track as LocalAudioTrack);
      });
      r.on(RoomEvent.ParticipantDisconnected, (p) => {   // the assistant left (call finished, crashed or restarted): end here too
        if (p.attributes?.role !== "voice_agent") return;   // the copilot and advisors are agents/guests too: only the voice agent ends the call
        setTimeout(() => {
          if (finished.current || roomRef.current !== r) return;
          finished.current = true;
          setError("The assistant left the call.");
          setPhase("ended");
          teardown();
        }, 2500);                                       // the summary message normally arrives first
      });
      r.on(RoomEvent.Disconnected, () => {
        if (finished.current || roomRef.current !== r) return;
        setError("Connection lost"); setPhase("error"); teardown();
      });
      await r.connect(info.url, info.token);
      roomRef.current = r;
      await r.localParticipant.setMicrophoneEnabled(true);
      setRoom(r);
      setPhase("live");
      joinTimer.current = setTimeout(() => {
        setError("The assistant did not join. Check that the voice agent worker is running.");
        setPhase("error"); teardown();
      }, JOIN_TIMEOUT_MS);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setPhase("error");
      teardown();
    }
  }, [teardown]);

  const end = useCallback(() => {
    finished.current = true;
    teardown();
    setPhase("ended");
  }, [teardown]);

  const toggleMic = useCallback(async () => {
    const next = !micOn;
    setMicOn(next);
    await roomRef.current?.localParticipant.setMicrophoneEnabled(next);
  }, [micOn]);

  const toggleSpk = useCallback(() => {
    const next = !spkOn;
    spkRef.current = next;
    setSpkOn(next);
    roomRef.current?.remoteParticipants.forEach((p) => p.audioTrackPublications.forEach((pub) => {
      (pub.track as RemoteAudioTrack | undefined)?.setVolume(next ? 1 : 0);
    }));
  }, [spkOn]);

  const sendText = useCallback(async (text: string) => {
    await roomRef.current?.localParticipant.sendText(text, { topic: "lk.chat" });
  }, []);

  const status: UiStatus = phase === "idle" ? "idle" : phase === "ended" ? "ended" : phase === "error" ? "error"
    : agent === null ? "connecting" : agent === "thinking" ? "processing" : agent;

  return { status, call, room, lines, state, rag, escalation, ended, error, micOn, spkOn, elapsed, vols,
           start, end, toggleMic, toggleSpk, sendText };
}
