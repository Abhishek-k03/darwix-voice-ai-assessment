"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { Arrow, Check, Chevron, Copy, Search, Sparkle, Thumb, Wave } from "@/components/Icons";
import { Shell } from "@/components/Shell";
import { AnswerResult, api } from "@/lib/api";

type Manifest = { kb_version: string; records_active: number; embedding_model: string };
type Item = { key: string; q: string; market: string; at: number; result: AnswerResult };

const MARKETS = [["in_health", "India"], ["ph_life", "Philippines"], ["id_multifinance", "Indonesia"]] as const;
const SCOPES: Record<string, string[] | undefined> = {
  All: undefined, Policies: ["policy_rule", "qualification_rule"], FAQs: ["faq"], Objections: ["objection"], Products: ["product_info"],
};
const EXAMPLES: Record<string, string[]> = {
  in_health: ["How long is the waiting period for pre-existing diseases?", "Can I add my 68 year old mother to the family floater?", "The customer says it's too expensive"],
  ph_life: ["Ilang araw ang grace period bago ma-lapse yung policy ko?", "Wala pa po akong pera pambayad ng premium ngayon"],
  id_multifinance: ["Kalau telat bayar cicilan kena denda berapa?", "Saya baru kena PHK, apa ada keringanan angsuran?"],
};
const STEPS = ["Searching the knowledge base", "Ranking relevant passages", "Writing a grounded answer"];
const STORE = "mira.kb.history";

function when(at: number) {
  const days = Math.floor((new Date().setHours(0, 0, 0, 0) - new Date(at).setHours(0, 0, 0, 0)) / 86_400_000);
  return Date.now() - at < 60_000 ? "Just now" : days <= 0 ? "Today" : days === 1 ? "Yesterday" : new Date(at).toLocaleDateString();
}

const listeners = new Set<() => void>();
const readStore = () => { try { return localStorage.getItem(STORE) ?? "[]"; } catch { return "[]"; } };
const subscribe = (cb: () => void) => { listeners.add(cb); return () => { listeners.delete(cb); }; };

export default function KnowledgePage() {
  const [q, setQ] = useState("");
  const [market, setMarket] = useState("in_health");
  const [scope, setScope] = useState("All");
  const [phase, setPhase] = useState<"empty" | "loading" | "answered" | "none" | "error">("empty");
  const [step, setStep] = useState(0);
  const [result, setResult] = useState<AnswerResult | null>(null);
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [fb, setFb] = useState<"up" | "down" | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");
  const raw = useSyncExternalStore(subscribe, readStore, () => "[]");
  const history = useMemo<Item[]>(() => { try { return JSON.parse(raw); } catch { return []; } }, [raw]);
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    api<Manifest>("/kb/manifest").then(setManifest).catch(() => undefined);
    const t = timers.current;
    return () => t.forEach(clearTimeout);
  }, []);

  function remember(items: Item[]) {
    try { localStorage.setItem(STORE, JSON.stringify(items)); } catch { /* storage unavailable */ }
    listeners.forEach((cb) => cb());
  }

  async function run(text?: string) {
    const query = (text ?? q).trim();
    if (!query) return;
    timers.current.forEach(clearTimeout);
    setQ(query); setPhase("loading"); setStep(0); setFb(null); setError(""); setCopied(false);
    timers.current = [setTimeout(() => setStep(1), 700), setTimeout(() => setStep(2), 1400)];
    try {
      const res = await api<AnswerResult>("/kb/answer", { method: "POST", body: JSON.stringify({ q: query, market, doc_types: SCOPES[scope], k: 4 }) });
      timers.current.forEach(clearTimeout);
      setStep(3); setResult(res);
      if (res.status === "ok") {
        const key = `h${Date.now()}`;
        setActiveKey(key); setPhase("answered");
        remember([{ key, q: query, market, at: Date.now(), result: res }, ...history.filter((h) => h.q !== query)].slice(0, 20));
      } else { setActiveKey(null); setPhase("none"); }
    } catch (e) {
      timers.current.forEach(clearTimeout);
      setError(e instanceof Error ? e.message : String(e)); setPhase("error");
    }
  }

  function open(h: Item) {
    timers.current.forEach(clearTimeout);
    setQ(h.q); setMarket(h.market); setResult(h.result); setActiveKey(h.key); setPhase("answered"); setFb(null);
  }
  const plain = result?.answer?.map((p) => p.map((s) => s.t).join("").trim()).join("\n\n") ?? "";
  const suggestions = history.length ? history.slice(0, 3).map((h) => h.q) : EXAMPLES[market];

  return (
    <Shell state="page" glow="corner" right={<Link className="callbtn" href="/"><Wave size={16} strokeWidth={2} /><span>Talk to Mira</span></Link>}>
      <div className="body">
        <aside className="side" aria-label="Query history">
          <span className="mono">History</span>
          {!history.length && <span className="hw" style={{ padding: "0 12px" }}>Your questions appear here.</span>}
          {history.map((h) => (
            <button key={h.key} className="hi" data-on={h.key === activeKey ? "on" : "off"} onClick={() => open(h)}>
              <span className="hq">{h.q}</span><span className="hw">{when(h.at)}</span>
            </button>
          ))}
        </aside>

        <main className="main">
          <div>
            <h1 className="h1">What do you need to know?</h1>
            <p className="lead">Ask in plain language. Answers come only from your knowledge base, with sources you can check.
              {manifest && <> <span className="mono">KB v{manifest.kb_version} · {manifest.records_active} records</span></>}</p>
          </div>

          <form className="ask" onSubmit={(e) => { e.preventDefault(); run(); }}>
            <Search style={{ color: "#A3A9B8", flex: "none" }} />
            <input aria-label="Ask the knowledge base" placeholder="Ask about policies, waiting periods, objections…" value={q} onChange={(e) => setQ(e.target.value)} />
            <button className="go" aria-label="Ask"><span>Ask</span><Arrow size={18} strokeWidth={2.2} /></button>
          </form>
          <div className="scopes" role="group" aria-label="Market">
            <span className="mono">Market</span>
            {MARKETS.map(([id, name]) => <button key={id} className="sc" data-on={market === id ? "on" : "off"} aria-pressed={market === id} onClick={() => setMarket(id)}>{name}</button>)}
          </div>
          <div className="scopes" role="group" aria-label="Search scope">
            <span className="mono">Scope</span>
            {Object.keys(SCOPES).map((s) => <button key={s} className="sc" data-on={scope === s ? "on" : "off"} aria-pressed={scope === s} onClick={() => setScope(s)}>{s}</button>)}
          </div>

          {phase === "empty" && (
            <div className="sug">
              <span className="mono">Try asking</span>
              {suggestions.map((s) => <button key={s} className="sg" onClick={() => run(s)}><span>{s}</span><Chevron size={18} strokeWidth={2} /></button>)}
            </div>
          )}

          {phase === "loading" && (
            <div className="card" role="status" aria-live="polite">
              <div className="steps">
                {STEPS.map((label, i) => (
                  <div key={label} className="st" data-s={i < step ? "done" : i === step ? "active" : "pending"}>
                    <span className="si">{i < step && <Check size={12} strokeWidth={3} />}</span>{label}
                  </div>
                ))}
              </div>
              <div className="skw"><div className="sk" style={{ width: "96%" }} /><div className="sk" style={{ width: "88%" }} /><div className="sk" style={{ width: "62%" }} /></div>
            </div>
          )}

          {phase === "error" && <div className="err" role="alert">Could not reach the knowledge base: {error}</div>}

          {phase === "answered" && result?.answer && <>
            <div className="card ans">
              <div className="ah"><span className="ai"><Sparkle size={16} strokeWidth={2} /></span>
                <span className="mono">Answer · grounded in {result.sources.length} sources{result.mode === "extractive" ? " · quoted from the records" : ""}</span></div>
              {result.answer.map((para, i) => (
                <p key={i}>{para.map((seg, j) => <span key={j}>{seg.t}{seg.c && <a className="cite" href={`#src-${seg.c}`} aria-label={`Source ${seg.c}`}>{seg.c}</a>}</span>)}</p>
              ))}
              <div className="acts">
                <button className="ab" onClick={() => { navigator.clipboard?.writeText(plain); setCopied(true); }}><Copy size={16} />{copied ? "Copied" : "Copy"}</button>
                <button className="ab" data-on={fb === "up" ? "on" : "off"} aria-pressed={fb === "up"} onClick={() => setFb(fb === "up" ? null : "up")}><Thumb size={16} />Helpful</button>
                <button className="ab" data-on={fb === "down" ? "on" : "off"} aria-pressed={fb === "down"} onClick={() => setFb(fb === "down" ? null : "down")}><Thumb size={16} style={{ transform: "rotate(180deg)" }} />Not helpful</button>
              </div>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <span className="mono">Sources</span>
              <div className="srcs">
                {result.sources.map((s, i) => (
                  <article key={s.n} className="sr" id={`src-${s.n}`} style={{ animationDelay: `${120 + i * 90}ms` }}>
                    <div className="sn"><span className="cite">{s.n}</span><span className="stt">{s.title}</span></div>
                    <span className="spth">{s.path}</span>
                    {s.needs_review && <span className="flag">Conflicting source flagged</span>}
                    <p className="ssn">{s.snippet}</p>
                    <div className="rel"><span>Match</span><span className="rb"><i style={{ width: `${s.rel}%` }} /></span><span>{s.rel}%</span></div>
                  </article>
                ))}
              </div>
            </div>
            {!!result.followups.length && (
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                <span className="mono">Follow up</span>
                <div className="fu">{result.followups.map((f) => <button key={f} className="fc" onClick={() => run(f)}>{f}</button>)}</div>
              </div>
            )}
          </>}

          {phase === "none" && (
            <div className="card none">
              <h2>No confident answer found</h2>
              <p>Nothing in the knowledge base matched closely enough, so Mira won&apos;t guess. On a call it would say the information is unavailable and offer an advisor callback. Try rephrasing, or talk to Mira.</p>
              <Link className="btn yel" href="/"><Wave size={16} strokeWidth={2} />Talk to Mira</Link>
            </div>
          )}
        </main>
      </div>
    </Shell>
  );
}
