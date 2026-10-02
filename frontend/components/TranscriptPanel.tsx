"use client";

import { Fragment, useEffect, useRef, useState } from "react";
import type { CallState, Line, RagStatus } from "@/lib/useCall";
import { Close, Copy, Download, Send } from "./Icons";

const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
type Tab = "chat" | "lead" | "sources";

export function TranscriptPanel({ open, onClose, lines, persona, state, rag, live, onSend }: {
  open: boolean; onClose: () => void; lines: Line[]; persona: string; state: CallState | null; rag: RagStatus | null;
  live: boolean; onSend: (text: string) => Promise<void>;
}) {
  const [tab, setTab] = useState<Tab>("chat");
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { if (open) end.current?.scrollIntoView({ behavior: "smooth" }); }, [lines, open, tab]);

  const who = (l: Line) => (l.role === "agent" ? persona : "You");
  const plain = () => lines.map((l) => `[${mmss(l.t ?? 0)}] ${who(l)}: ${l.text}`).join("\n");
  const download = () => {
    const url = URL.createObjectURL(new Blob([plain()], { type: "text/plain" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: "conversation.txt" });
    a.click();
    URL.revokeObjectURL(url);
  };
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const text = draft.trim();
    if (!text || sending) return;
    setSending(true);
    try { await onSend(text); setDraft(""); } finally { setSending(false); }
  }
  const elig = state?.eligibility as Record<string, unknown> | null | undefined;

  return (
    <aside className="panel" data-open={open ? "true" : "false"} aria-label="Conversation transcript">
      <div className="ph">
        <div><div className="mono">Live call</div><div className="pt">Conversation</div></div>
        <div className="pb">
          <button className="sb" aria-label="Copy transcript" title="Copy" onClick={() => navigator.clipboard?.writeText(plain())}><Copy size={18} /></button>
          <button className="sb" aria-label="Download transcript" title="Download" onClick={download}><Download size={18} /></button>
          <button className="sb" aria-label="Close transcript" title="Close" onClick={onClose}><Close size={18} /></button>
        </div>
      </div>
      <div className="ptabs" role="tablist">
        {([["chat", "Conversation"], ["lead", "Lead"], ["sources", "Sources"]] as [Tab, string][]).map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k} className="ptab" onClick={() => setTab(k)}>{label}</button>
        ))}
      </div>

      {tab === "chat" && <>
        <div className="msgs">
          {!lines.length && <p className="empty">The transcript appears here as you talk.</p>}
          {lines.map((l, i) => (
            <div key={i} className="msg" data-role={l.role === "agent" ? "agent" : "user"}>
              <span className="mw">{who(l)} · {mmss(l.t ?? 0)}</span>
              <p>{l.text}{!!l.citations?.length && <> <span className="cites">[{l.citations.join(", ")}]</span></>}</p>
            </div>
          ))}
          <div ref={end} />
        </div>
        <form className="cmp" onSubmit={submit}>
          <input aria-label="Type a message" placeholder={live ? "Type instead of speaking" : "Start a call to type"} value={draft}
            disabled={!live} onChange={(e) => setDraft(e.target.value)} />
          <button className="send" aria-label="Send message" disabled={!live || !draft.trim() || sending}><Send size={20} strokeWidth={2} /></button>
        </form>
      </>}

      {tab === "lead" && <div className="tabbody">
        {!state ? <p className="empty">Qualification details appear after the first customer turn.</p> : <>
          <div className="mono">Stage · {state.stage}{state.outcome ? ` · ${state.outcome}` : ""}</div>
          <dl className="kv">{Object.entries(state.fields).map(([k, v]) => <Fragment key={k}><dt>{k}</dt><dd>{JSON.stringify(v)}</dd></Fragment>)}</dl>
          {!!state.missing.length && <div className="mono">Still needed · {state.missing.join(", ")}</div>}
          {!!state.conflicts.length && <div className="row"><b>Needs confirming</b>{state.conflicts.map((c) => <span key={c.field}>{c.field}: {String(c.old)} → {String(c.new)}</span>)}</div>}
          {elig && <div className="row">
            {elig.eligible
              ? <><span className="t">{String(elig.product)}</span><span>Cover {String(elig.sum_insured_lakh)} lakh · indicative premium ₹{String(elig.indicative_premium_inr ?? "n/a")}</span><span className="mono">Grade · {String(elig.grade)}</span></>
              : <><span className="t">Not eligible</span><span>{(elig.reasons as string[] | undefined)?.join("; ")}</span></>}
          </div>}
        </>}
      </div>}

      {tab === "sources" && <div className="tabbody">
        {!rag ? <p className="empty">The agent looks up the knowledge base on every customer turn.</p> : <>
          <div className="mono">“{rag.query}” · {rag.status}</div>
          {rag.hits.map((h) => (
            <div key={h.record_id} className={`row ${rag.used.includes(h.record_id) ? "used" : ""}`}>
              <span className="t">{h.title}</span>
              <span className="mono">{h.record_id}{rag.used.includes(h.record_id) ? " · used in the answer" : ""}</span>
              <div className="rel"><span>Match</span><span className="rb"><i style={{ width: `${Math.round((h.dense ?? 0) * 100)}%` }} /></span><span>{Math.round((h.dense ?? 0) * 100)}%</span></div>
            </div>
          ))}
          {!rag.hits.length && <p className="empty">Nothing relevant: the agent says it does not have that information.</p>}
        </>}
      </div>}
    </aside>
  );
}
