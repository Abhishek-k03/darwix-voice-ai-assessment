"use client";

import { useEffect, useRef, useState } from "react";
import { levelFor, newSim, orbVals, step, Status } from "@/lib/orb";

type Props = { status: Status; mic: boolean; volumes: () => { agent: number; mic: number } };

export function Orb({ status, mic, volumes }: Props) {
  const sim = useRef(newSim());
  const live = useRef({ status, mic, volumes });
  const [v, setV] = useState(() => orbVals(newSim(), status));
  useEffect(() => { live.current = { status, mic, volumes }; });
  useEffect(() => {
    const id = setInterval(() => {
      const { status: st, mic: m, volumes: vol } = live.current;
      const { agent, mic: micVol } = vol();
      step(sim.current, st, m, levelFor(st, m, agent, micVol));
      setV(orbVals(sim.current, st));
    }, 90);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="orb" style={{ "--lvl": v.lvl } as React.CSSProperties} aria-hidden="true">
      <div className="halo" />
      <svg className="art" viewBox="0 0 400 400">
        <defs>
          <linearGradient id="hairG" gradientUnits="userSpaceOnUse" x1="0" y1="90" x2="0" y2="320"><stop offset="0" style={{ stopColor: "var(--c)", stopOpacity: 1 }} /><stop offset=".6" style={{ stopColor: "var(--c2)", stopOpacity: 0.85 }} /><stop offset="1" style={{ stopColor: "var(--c2)", stopOpacity: 0.1 }} /></linearGradient>
          <linearGradient id="jg" gradientUnits="userSpaceOnUse" x1="0" y1="150" x2="0" y2="268"><stop offset="0" style={{ stopColor: "var(--c2)", stopOpacity: 0.1 }} /><stop offset="1" style={{ stopColor: "var(--c2)", stopOpacity: 1 }} /></linearGradient>
          <linearGradient id="nk" gradientUnits="userSpaceOnUse" x1="0" y1="262" x2="0" y2="400"><stop offset="0" style={{ stopColor: "var(--c2)", stopOpacity: 0 }} /><stop offset=".18" style={{ stopColor: "var(--c2)", stopOpacity: 0.9 }} /><stop offset=".8" style={{ stopColor: "var(--c2)", stopOpacity: 0.6 }} /><stop offset="1" style={{ stopColor: "var(--c2)", stopOpacity: 0 }} /></linearGradient>
          <radialGradient id="chk"><stop offset="0" stopColor="#FF7A1A" stopOpacity=".9" /><stop offset="1" stopColor="#FF7A1A" stopOpacity="0" /></radialGradient>
          <clipPath id="eyeLc"><path d={v.eL.lid} /></clipPath>
          <clipPath id="eyeRc"><path d={v.eR.lid} /></clipPath>
        </defs>
        <g transform={`rotate(${v.arcRot} 200 190)`}><path className="arc" d="M97.8 131 A118 118 0 0 1 302.2 131" /><path className="arc2" d="M85.7 124 A132 132 0 0 1 314.3 124" /></g>
        <g className="rot" style={{ transform: `rotate(${v.ringA}deg)` }}><circle className="pring" cx="200" cy="190" r="146" pathLength="360" strokeDasharray="40 20 90 30 60 20 50 50" /></g>
        <g className="hd" style={{ transform: `translate(${v.bx}px, ${v.by}px) rotate(${v.btilt}deg)` }}>
          <path className="nk" d="M184 262 C184 288 182 306 168 318 C150 331 118 338 90 357 C76 366 66 380 60 398" />
          <path className="nk" d="M216 262 C216 288 218 306 232 318 C250 331 282 338 310 357 C324 366 334 380 340 398" />
          <path className="nk2" d="M176 332 C160 346 130 352 104 372 C94 380 88 390 84 400" />
          <path className="nk2" d="M224 332 C240 346 270 352 296 372 C306 380 312 390 316 400" />
          <path className="nk" d="M168 322 Q200 354 232 322" opacity=".75" />
          <circle className="pnd" cx="200" cy="341" r={v.pnr} />
        </g>
        <g className="hd" style={{ transform: `translate(${v.hx}px, ${v.hy}px) rotate(${v.tilt}deg)` }}>
          <g className="hair">{v.hair.map((h, i) => <path key={i} className={`hs ${h.k}`} d={h.d} />)}</g>
          {v.flows.map((fl, i) => <path key={i} className="hfl" d={fl.d} strokeDasharray="34 420" strokeDashoffset={fl.o} />)}
          <path className="jaw" d="M146 168 C146 220 168 258 200 266 C232 258 254 220 254 168" />
          <circle cx="160" cy="228" r="17" fill="url(#chk)" opacity={v.ch} />
          <circle cx="240" cy="228" r="17" fill="url(#chk)" opacity={v.ch} />
          <line className="erl" x1="146" y1="210" x2={v.eaL.x} y2={v.eaL.y} /><circle className="ern" cx={v.eaL.x} cy={v.eaL.y} r={v.ern} />
          <line className="erl" x1="254" y1="210" x2={v.eaR.x} y2={v.eaR.y} /><circle className="ern" cx={v.eaR.x} cy={v.eaR.y} r={v.ern} />
          <path className="br" d={v.browL} /><path className="br" d={v.browR} />
          <path className="crs" d={v.eL.crs} /><path className="crs" d={v.eR.crs} />
          <path className="ef" d={v.eL.lid} />
          <g clipPath="url(#eyeLc)"><circle className="iris" cx={v.eL.ix} cy={v.eL.iy} r={v.pr} /><circle className="pup" cx={v.eL.ix} cy={v.eL.iy} r={v.pu} /><circle cx={v.eL.hx} cy={v.eL.hy} r="2.6" fill="#fff" opacity=".92" /><circle cx={v.eL.h2x} cy={v.eL.h2y} r="1.2" fill="#fff" opacity=".8" /></g>
          <path className="lid" d={v.eL.up} /><path className="lid" d={v.eL.flick} />
          <path className="ef" d={v.eR.lid} />
          <g clipPath="url(#eyeRc)"><circle className="iris" cx={v.eR.ix} cy={v.eR.iy} r={v.prR} /><circle className="pup" cx={v.eR.ix} cy={v.eR.iy} r={v.puR} /><circle cx={v.eR.hx} cy={v.eR.hy} r="2.6" fill="#fff" opacity=".92" /><circle cx={v.eR.h2x} cy={v.eR.h2y} r="1.2" fill="#fff" opacity=".8" /></g>
          <path className="lid" d={v.eR.up} /><path className="lid" d={v.eR.flick} />
          <path className="mo" d={v.mouth} />
        </g>
        {v.sparks.map((k, i) => <path key={i} className="spk" d="M0 -9 L1.2 -1.2 L9 0 L1.2 1.2 L0 9 L-1.2 1.2 L-9 0 L-1.2 -1.2Z" transform={`translate(${k.x} ${k.y}) scale(${k.s})`} />)}
        {v.parts.map((q, i) => <circle key={i} className="pcl" cx={q.x} cy={q.y} r={q.r} opacity={q.o} />)}
      </svg>
    </div>
  );
}
