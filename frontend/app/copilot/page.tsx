"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Chevron } from "@/components/Icons";
import { Shell } from "@/components/Shell";
import { api, RoomInfo } from "@/lib/api";

export default function CopilotRooms() {
  const [rooms, setRooms] = useState<RoomInfo[] | null>(null);
  const [error, setError] = useState("");
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const load = () => api<RoomInfo[]>("/copilot/rooms").then((r) => { setRooms(r); setNow(Date.now()); setError(""); }).catch((e) => setError(String(e)));
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, []);
  const ago = (t: number) => { const s = Math.max(0, Math.round(now / 1000 - t)); return s < 90 ? `${s}s ago` : `${Math.round(s / 60)} min ago`; };
  return (
    <Shell state="page" glow="corner">
      <main className="dash">
        <div className="dtitle"><h1>Live call copilot</h1><span className="mono">Silent listener · nudges for the human agent</span></div>
        <p className="lead" style={{ margin: 0, maxWidth: 640 }}>The copilot joins every call as a silent participant, tracks compliance, buying signals and frustration, and shows short nudges within seconds. Pick a call below, or start one from the Voice tab.</p>
        {error && <div className="err" role="alert">Could not load calls: {error}</div>}
        <div className="rooms">
          {rooms && !rooms.length && <p className="empty">No calls with the copilot yet. Start a call or a simulated caller from the Voice tab.</p>}
          {rooms?.map((r) => (
            <Link key={r.room} className="rm" href={`/copilot/${r.room}`}>
              <span><code>{r.room}</code><br /><span className="hw">{ago(r.last_seen)} · {r.nudges} nudge{r.nudges === 1 ? "" : "s"}</span></span>
              <Chevron size={18} strokeWidth={2} />
            </Link>
          ))}
        </div>
      </main>
    </Shell>
  );
}
