"use client";

import { useEffect, useState } from "react";
import { Nudge } from "@/lib/api";

const PRIORITY: Record<number, string> = { 1: "Compliance / risk", 2: "Customer care", 3: "Opportunity", 4: "Info" };

export function NudgeFeed({ nudges, showInactive = true }: { nudges: Nudge[]; showInactive?: boolean }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 500); return () => clearInterval(t); }, []);
  const sorted = [...nudges].sort((a, b) => {
    const aa = a.status === "active" && a.expires_at > now, ba = b.status === "active" && b.expires_at > now;
    if (aa !== ba) return aa ? -1 : 1;
    return aa ? a.priority - b.priority || b.created_at - a.created_at : b.created_at - a.created_at;
  });
  const visible = showInactive ? sorted : sorted.filter((n) => n.status === "active" && n.expires_at > now);
  if (!visible.length) return <p className="empty">No nudges yet: the copilot stays quiet unless something matters.</p>;
  return (
    <ul className="nudges">
      {visible.map((n) => {
        const active = n.status === "active" && n.expires_at > now;
        const left = Math.max(0, Math.round((n.expires_at - now) / 1000));
        return (
          <li key={n.id} className="nudge" data-p={n.priority} data-active={active}>
            <div className="nh">
              <span>{PRIORITY[n.priority] ?? PRIORITY[4]}{n.escalated ? " · repeated" : ""}</span>
              <span>{active ? `${left}s` : n.status}{n.reason ? ` (${n.reason})` : ""} · {Math.round(n.confidence * 100)}%</span>
            </div>
            <div className="nt">{n.title}</div>
            <div className="nx">{n.text}</div>
            {n.evidence && <div className="ne">“{n.evidence}”</div>}
            {n.citation && <div className="ne">Source: {n.citation}</div>}
          </li>
        );
      })}
    </ul>
  );
}
