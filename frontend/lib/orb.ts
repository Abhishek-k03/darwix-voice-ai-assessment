/** Animation maths for the Mira avatar: each status eases a set of face parameters; audio level drives the mouth. */

export type Status = "idle" | "connecting" | "listening" | "processing" | "speaking" | "error";
type Ex = { U: number; L: number; dr: number; ow: number; pr: number; bL: number; bR: number; tL: number; tR: number; sm: number; mw: number; mx: number; tilt: number; ch: number };

const T: Record<Status, Ex> = {
  idle: { U: 9, L: 6, dr: 1, ow: 2, pr: 10, bL: 0, bR: 0, tL: 0, tR: 0, sm: 3, mw: 1, mx: 0, tilt: 0, ch: 0.14 },
  connecting: { U: 1.5, L: 1.5, dr: 1, ow: 1, pr: 9, bL: 3, bR: 3, tL: 0, tR: 0, sm: 1, mw: 0.8, mx: 0, tilt: 0, ch: 0.06 },
  listening: { U: 13, L: 8, dr: 1, ow: 2, pr: 12, bL: -6, bR: -6, tL: -2, tR: -2, sm: 4, mw: 1, mx: 0, tilt: 4, ch: 0.2 },
  processing: { U: 8, L: 5, dr: 0.8, ow: 2, pr: 9, bL: -1, bR: -9, tL: 2, tR: -2, sm: 1, mw: 0.6, mx: 6, tilt: -5, ch: 0.08 },
  speaking: { U: 10, L: 5, dr: 1, ow: 2.5, pr: 10.5, bL: -3, bR: -3, tL: 0, tR: 0, sm: 4, mw: 1.1, mx: 0, tilt: 0, ch: 0.22 },
  error: { U: 3, L: 3, dr: 1, ow: -3, pr: 8, bL: -1, bR: -1, tL: -6, tR: -6, sm: -3, mw: 0.7, mx: 0, tilt: -3, ch: 0 },
};
const SPEED: Record<Status, number> = { idle: 6, connecting: 40, listening: 14, processing: 90, speaking: 34, error: 1 };

export function targets(st: Status, mic: boolean): Ex {
  const r = { ...T[st] };
  if (st === "listening" && !mic) Object.assign(r, { U: 9, L: 6, pr: 10, bL: 0, bR: 0, sm: 2, ch: 0.1 });
  return r;
}

export type OrbSim = { ex: Ex; spd: number; ph: number; t: number; lvl: number };
export const newSim = (): OrbSim => ({ ex: targets("idle", true), spd: 6, ph: 0, t: 0, lvl: 0 });

/** Advances one animation tick (90 ms). `level` is the live audio level for this status, 0..1. */
export function step(sim: OrbSim, st: Status, mic: boolean, level: number, dt = 90): void {
  sim.t += dt;
  sim.spd += (SPEED[st] - sim.spd) * 0.1;
  sim.ph += sim.spd * 0.09;
  const tx = targets(st, mic);
  for (const k of Object.keys(tx) as (keyof Ex)[]) sim.ex[k] += (tx[k] - sim.ex[k]) * 0.14;
  sim.lvl += (level - sim.lvl) * 0.5;
}

/** Maps raw analyser volume to the 0..1 range the animation was tuned for. */
export function levelFor(st: Status, mic: boolean, agentVol: number, micVol: number): number {
  const clamp = (v: number) => Math.max(0, Math.min(1, v));
  if (st === "speaking") return 0.25 + 0.65 * clamp(agentVol * 2.2);
  if (st === "listening") return mic ? 0.08 + 0.6 * clamp(micVol * 3) : 0.03;
  if (st === "processing" || st === "connecting") return 0.08;
  return 0;
}

export type OrbVals = ReturnType<typeof orbVals>;

export function orbVals(sim: OrbSim, st: Status) {
  const { ex, t, ph, lvl } = sim;
  const f = (v: number) => v.toFixed(1);
  const isP = st === "processing", isS = st === "speaking";
  const bp = t % 3800, blink = bp < 190 ? Math.max(0.08, Math.abs(bp - 95) / 95) : 1;
  const bl = st === "connecting" || st === "error" ? 1 : blink;
  let gx = 0, gy = 0;
  if (st === "idle") { gx = 7 * Math.sin(t / 2600); gy = 2 * Math.sin(t / 3100); }
  else if (st === "listening") { gx = 2 * Math.sin(t / 1700); gy = 0.5; }
  else if (isP) { gx = 10 * Math.sin(t / 1500); gy = -8; }
  else if (isS) { gx = 2.5 * Math.sin(t / 900); gy = 1; }
  else if (st === "error") { gy = 6; }

  const eye = (cx: number, side: number, U: number, L: number) => {
    const u = Math.max(0.8, U * bl), l = Math.max(0.8, L * bl), xo = cx + side * 19, xi = cx - side * 16, yo = 186 - ex.ow, yi = 188;
    const up = `M${xo} ${f(yo)} Q${cx} ${f(186 - 2 * u)} ${xi} ${yi}`;
    const ix = cx + gx * 0.5, iy = 187 + gy * 0.5;
    return {
      up, lid: `${up} Q${cx} ${f(187 + 2 * l)} ${xo} ${f(yo)}Z`,
      flick: `M${xo} ${f(yo)} Q${xo + side * 5} ${f(yo - 1)} ${xo + side * 10} ${f(yo - 5)}`,
      crs: `M${cx + side * 15} 181 Q${cx} ${f(186 - 2 * u - 8)} ${cx - side * 13} 183`,
      ix: f(ix), iy: f(iy), hx: f(ix - 3.5), hy: f(iy - 3.5), h2x: f(ix + 3.5), h2y: f(iy + 3.5),
    };
  };
  const brow = (xo: number, xi: number, b: number, tt: number) => {
    const yo = 158 + b - tt, yi = 158 + b + tt;
    return `M${xo} ${f(yo)} Q${(xo + xi) / 2} ${f((yo + yi) / 2 - 6)} ${xi} ${f(yi)}`;
  };
  const nz = Math.abs(Math.sin(t / 110)) * 0.55 + Math.abs(Math.sin(t / 67 + 1)) * 0.45;
  const open = isS ? lvl * 13 * (0.35 + 0.65 * nz) : 0;
  const hwm = 15 * ex.mw, cxm = 200 + ex.mx, yc = 238, yl = yc - ex.sm * 0.5, xl = cxm - hwm, xr = cxm + hwm, ou = open * 0.22, ol = open * 1.1;
  const mouth = `M${f(xl)} ${f(yl)} C${f(xl + hwm * 0.5)} ${f(yl - 3)} ${f(cxm - hwm * 0.22)} ${f(yc - 4 - ou)} ${f(cxm)} ${f(yc - 2 - ou)}` +
    ` C${f(cxm + hwm * 0.22)} ${f(yc - 4 - ou)} ${f(xr - hwm * 0.5)} ${f(yl - 3)} ${f(xr)} ${f(yl)}` +
    ` C${f(xr - hwm * 0.3)} ${f(yl + 6 + ol)} ${f(xl + hwm * 0.3)} ${f(yl + 6 + ol)} ${f(xl)} ${f(yl)}Z`;

  const amp = 2.5 + (isS ? lvl * 9 : 0) + (st === "listening" ? 2 : 0) + (isP ? 1.5 : 0);
  const strands = (side: number, p0: number) => {
    const X = (x: number) => (side < 0 ? x : 400 - x), pt = (a: number[]) => `${f(X(a[0]))} ${f(a[1])}`;
    const w = (k: number, lag: number) => amp * k * Math.sin(t / 900 + p0 - lag);
    const S = [
      [[200, 96], [150, 92], [118, 130], [120, 190], [122, 240], [110 + w(1, 0), 270], [96 + w(1.6, 1.1), 314]],
      [[200, 100], [160, 100], [132, 140], [134, 190], [136, 232], [128 + w(1, 0), 262], [120 + w(1.6, 1.1), 298]],
      [[200, 98], [172, 104], [148, 138], [148, 178], [148, 205], [144 + w(0.7, 0), 226], [138 + w(1.1, 1.1), 246]],
      [[200, 96], [178, 99], [160, 116], [149, 160]],
    ];
    return S.map((a, i) => ({
      k: `h${i}`,
      d: `M${pt(a[0])} C${pt(a[1])} ${pt(a[2])} ${pt(a[3])}` + (a.length > 4 ? ` C${pt(a[4])} ${pt(a[5])} ${pt(a[6])}` : ""),
    }));
  };
  const hl = strands(-1, 0), hr = strands(1, 1.3);
  const flows = [{ d: hl[0].d, o: f(-((ph * 3.2) % 360)) }, { d: hr[0].d, o: f(-((ph * 3.2 + 160) % 360)) }];
  const ear = (ax: number, sg: number) => {
    const th = (0.2 + lvl * 0.5) * Math.sin(t / 650 + sg);
    return { x: f(ax + 16 * Math.sin(th)), y: f(210 + 16 * Math.cos(th)) };
  };
  const parts = [] as { x: string; y: string; r: string; o: string }[];
  for (let i = 0; i < 6; i++) {
    const q = ((t / 1500) + i / 6) % 1;
    parts.push({ x: f(262 + i * 3 + 12 * Math.sin(q * 6 + i)), y: f(104 - q * 60), r: f(3 * (1 - q) + 0.8), o: isP ? Math.sin(Math.PI * q).toFixed(2) : "0" });
  }
  const spA = (i: number) => isS ? 0.3 + 0.9 * Math.abs(Math.sin(t / 260 + i)) * (0.4 + lvl)
    : st === "listening" ? 0.25 + 0.2 * Math.abs(Math.sin(t / 700 + i))
    : st === "idle" ? 0.15 + 0.15 * Math.abs(Math.sin(t / 1500 + i)) : st === "error" ? 0 : 0.1;
  const sparks = ([[78, 150, 0], [326, 118, 2], [304, 268, 4]] as number[][]).map((k) => ({ x: k[0], y: k[1], s: (spA(k[2]) * 0.65).toFixed(2) }));
  const hx = 2.5 * Math.sin(t / 2300) + (isS ? 1.5 * lvl * Math.sin(t / 190) : 0);
  const hy = 4 * Math.sin(t / 1600) + (isS ? 2.5 * lvl * Math.sin(t / 240) : 0);
  const tl = ex.tilt + Math.sin(t / 2900) + (isS ? 1.2 * lvl * Math.sin(t / 420) : 0);
  const puBase = ex.pr * (st === "listening" ? 0.5 : 0.42);
  return {
    eL: eye(172, -1, ex.U, ex.L), eR: eye(228, 1, ex.U * ex.dr, ex.L * ex.dr),
    pr: f(ex.pr), prR: f(ex.pr * (ex.dr < 1 ? 0.9 : 1)), pu: f(puBase), puR: f(puBase * (ex.dr < 1 ? 0.9 : 1)),
    browL: brow(146, 188, ex.bL, ex.tL), browR: brow(254, 212, ex.bR, ex.tR), mouth, ch: ex.ch.toFixed(2),
    hair: hl.concat(hr), flows, eaL: ear(146, 0), eaR: ear(254, 1.4), ern: f(3.2 + lvl * 1.6),
    arcRot: f(4 * Math.sin(t / 2400)), ringA: f(ph * 2.2),
    hx: hx.toFixed(2), hy: hy.toFixed(2), bx: (hx * 0.4).toFixed(2), by: (hy * 0.4).toFixed(2),
    btilt: (tl * 0.4).toFixed(2), pnr: f(2.8 + lvl * 1.4), tilt: tl.toFixed(2), sparks, parts, lvl: lvl.toFixed(3),
  };
}
