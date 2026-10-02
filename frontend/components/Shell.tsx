"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { Book, Radar, Wave } from "./Icons";

const TABS = [
  { href: "/", label: "Voice", Icon: Wave },
  { href: "/kb", label: "Knowledge", Icon: Book },
  { href: "/copilot", label: "Copilot", Icon: Radar },
];

export function Shell({ state = "page", glow = "center", fixed = false, right, children }: {
  state?: string; glow?: "center" | "corner"; fixed?: boolean; right?: ReactNode; children: ReactNode;
}) {
  const path = usePathname() ?? "/";
  const here = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));
  return (
    <div className={fixed ? "app fixed" : "app"} data-state={state}>
      <div className="bgfx" aria-hidden="true">
        {glow === "center" ? <><div className="grid" /><div className="glow" /></> : <><div className="glow top-right" /><div className="glow2" /></>}
      </div>
      <header className="top">
        <Link className="brand" href="/" aria-label="Mira home"><span className="mark" /><span>Mira</span></Link>
        <nav className="nav" aria-label="Primary">
          {TABS.map(({ href, label, Icon }) => (
            <Link key={href} className="tab" href={href} aria-current={here(href) ? "page" : undefined}><Icon size={18} />{label}</Link>
          ))}
        </nav>
        {right ?? <span />}
      </header>
      {children}
    </div>
  );
}
