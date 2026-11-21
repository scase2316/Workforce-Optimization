import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import type { Capacity as Cap, CommitmentRow, Overview, Run } from "./types";
import { addDays, fmt, useWidth } from "./util";

const LABEL_W = 196, PAD_R = 20, AXIS_H = 28, LANE_H = 16, LANES = 2, AREA_H = 58, GAP = 26;
const ROW_H = LANES * LANE_H + 8 + AREA_H + GAP;

function lanes(cs: CommitmentRow[]): Map<number, number> {
  const out = new Map<number, number>();
  const ends: number[] = [];
  [...cs].sort((a, b) => a.start - b.start).forEach((c) => {
    let l = ends.findIndex((e) => e < c.start);
    if (l < 0) l = ends.length;
    ends[l] = c.end; out.set(c.id, Math.min(l, LANES - 1));
  });
  return out;
}

export default function Capacity({ pack, overview, run, goToSchedule }: { pack: string; overview: Overview; run: Run | null; goToSchedule: () => void }) {
  const v = overview.vocabulary;
  const [base, setBase] = useState<Cap | null>(null);
  useEffect(() => { setBase(null); if (!run) api.capacity(pack).then(setBase); }, [pack, run]);
  const cap = run ? run.capacity : base;
  const [ref, W] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<{ d: number; x: number; y: number } | null>(null);

  const tight = useMemo(() => {
    if (!cap) return null;
    type T = { g: string; d: number; n: number; floor: number; byCommitments: boolean };
    let best: T | null = null;
    for (const g of cap.groups) {
      const s = run ? g.planned : g.base;
      for (let d = 0; d < s.length; d++) {
        const cand: T = { g: g.name, d, n: s[d], floor: g.min_available, byCommitments: g.base[d] < g.min_available };
        if (best === null || cand.n - cand.floor < best.n - best.floor) best = cand;
      }
    }
    return best as T | null;
  }, [cap, run]);

  if (!cap) return <p className="muted">Loading…</p>;
  const H = cap.horizon_days;
  const pw = W - LABEL_W - PAD_R;
  const x = (d: number) => LABEL_W + (d / (H + 1)) * pw;
  const totalH = AXIS_H + cap.groups.length * ROW_H;

  const ticks: { d: number; label: string }[] = [];
  for (let d = 0; d <= H; d++) {
    const iso = addDays(cap.as_of, d);
    if (d === 0 || iso.endsWith("-01")) {
      const yr = iso.endsWith("-01-01") || d === 0;
      ticks.push({ d, label: new Date(iso + "T00:00:00").toLocaleDateString("en-US", { month: "short", ...(yr ? { year: "numeric" } : {}) }) });
    }
  }
  if (ticks.length > 1 && ticks[1].d - ticks[0].d < 20) ticks[0].label = "";   // would collide with the next month

  // Stacked "people away" bands, zero-based. lo/hi are per-day counts.
  const band = (lo: number[], hi: number[], ymax: number, y0: number) => {
    const Y = (n: number) => y0 + AREA_H - (n / ymax) * AREA_H;
    let p = `M ${x(0)} ${Y(hi[0])}`;
    hi.forEach((n, d) => { p += ` L ${x(d)} ${Y(n)} L ${x(d + 1)} ${Y(n)}`; });
    for (let d = lo.length - 1; d >= 0; d--) p += ` L ${x(d + 1)} ${Y(lo[d])} L ${x(d)} ${Y(lo[d])}`;
    return p + " Z";
  };

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const mx = e.clientX - r.left, my = e.clientY - r.top;
    const d = Math.floor(((mx - LABEL_W) / pw) * (H + 1));
    setHover(d >= 0 && d <= H && my > AXIS_H ? { d, x: mx, y: my } : null);
  };

  return (
    <>
      <h1 className="lead">
        {tight ? (tight.n < tight.floor
          ? <>{tight.g} falls {tight.floor - tight.n} below its floor on {fmt(addDays(cap.as_of, tight.d))}{tight.byCommitments ? ", because of commitments alone" : ""}.</>
          : <>The tightest day is {fmt(addDays(cap.as_of, tight.d))}: {tight.g} has {tight.n} available against a floor of {tight.floor}.</>) : "Capacity"}
      </h1>
      <p className="lead-sub">
        Each row stacks who is away each day for the next six months. Training only goes where the stack stays under the dashed line.
        {run ? "" : " The optimizer hasn't run yet, so only commitments are counted."}
      </p>
      {!run && <div className="row-actions" style={{ marginBottom: 24 }}><button className="btn primary" onClick={goToSchedule}>Go to Schedule and optimize</button></div>}

      <div className="legend">
        <span><i className="sw hatch" />Commitment (exercise, deployment, leave)</span>
        <span><i className="sw" style={{ background: "#b8c6cb" }} />People away on commitments</span>
        {run && <span><i className="sw" style={{ background: "var(--accent)" }} />People away in scheduled training</span>}
        <span><i className="sw" style={{ background: "transparent", borderTop: "2px dashed var(--ink)", height: 0, width: 16, borderRadius: 0 }} />Most people who can be away before the floor is breached</span>
      </div>

      <div className="cap-wrap" ref={ref}>
        <svg viewBox={`0 0 ${W} ${totalH}`} height={totalH} onMouseMove={onMove} onMouseLeave={() => setHover(null)} role="img"
          aria-label="Daily availability by group with commitments and the training plan">
          <defs>
            <pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(135)">
              <rect width="6" height="6" fill="#e9eeee" /><line x1="0" y1="0" x2="0" y2="6" stroke="var(--ink-3)" strokeWidth="2" />
            </pattern>
          </defs>
          {ticks.map((t) => (
            <g key={t.d}>
              <line x1={x(t.d)} x2={x(t.d)} y1={AXIS_H - 6} y2={totalH} stroke="var(--line)" strokeWidth="1" />
              <text x={x(t.d) + 5} y={AXIS_H - 10} fontSize="12.5" fill="var(--ink-2)">{t.label}</text>
            </g>
          ))}
          {cap.groups.map((g, i) => {
            const y0 = AXIS_H + i * ROW_H;
            const ay = y0 + LANES * LANE_H + 8;
            const cs = cap.commitments.filter((c) => c.group_id === g.group_id);
            const ln = lanes(cs);
            const ceiling = g.size - g.min_available;
            const away = g.base.map((b) => g.size - b);
            const total = g.planned.map((p) => g.size - p);
            const zeros = away.map(() => 0);
            const ymax = Math.max(1, ceiling, ...total) * 1.15;
            const ceilY = ay + AREA_H - (ceiling / ymax) * AREA_H;
            return (
              <g key={g.group_id}>
                <text x={0} y={ay + 14} fontSize="14" fontWeight="600" fill="var(--ink)">{g.name.length > 24 ? g.name.slice(0, 23) + "…" : g.name}</text>
                <text x={0} y={ay + 32} fontSize="12.5" fill="var(--ink-3)">{g.size} on strength, up to {ceiling} away</text>
                {cs.map((c) => {
                  const x0 = x(Math.max(0, c.start)), x1 = x(Math.min(H + 1, c.end + 1));
                  const w = Math.max(2, x1 - x0);
                  const ly = y0 + (ln.get(c.id) ?? 0) * LANE_H;
                  return (
                    <g key={c.id}>
                      <rect x={x0} y={ly} width={w} height={LANE_H - 3} rx="3" fill="url(#hatch)" stroke="var(--ink-3)" strokeWidth="1">
                        <title>{`${c.name}: ${fmt(addDays(cap.as_of, c.start))} to ${fmt(addDays(cap.as_of, c.end))}${c.people ? `, ${c.people} ${v.people.toLowerCase()}` : ""}`}</title>
                      </rect>
                      {w > 90 && <text x={x0 + 6} y={ly + 10} fontSize="11.5" fontWeight="600" fill="var(--ink)" style={{ paintOrder: "stroke", stroke: "#e9eeee", strokeWidth: 3 }}>{c.name}</text>}
                    </g>
                  );
                })}
                <line x1={LABEL_W} x2={LABEL_W + pw} y1={ay + AREA_H} y2={ay + AREA_H} stroke="var(--ink-3)" />
                <path d={band(zeros, away, ymax, ay)} fill="#b8c6cb" />
                {run && <path d={band(away, total, ymax, ay)} fill="var(--accent)" />}
                <line x1={LABEL_W} x2={LABEL_W + pw} y1={ceilY} y2={ceilY} stroke="var(--ink)" strokeWidth="1.5" strokeDasharray="5 4" />
              </g>
            );
          })}
          {hover && <line x1={x(hover.d + 0.5)} x2={x(hover.d + 0.5)} y1={AXIS_H} y2={totalH} stroke="var(--ink)" strokeWidth="1" />}
        </svg>
        {hover && (
          <div className="cap-tip" style={{ left: hover.x > W - 280 ? hover.x - 250 : hover.x + 14, top: Math.max(0, hover.y - 20) }}>
            <b>{fmt(addDays(cap.as_of, hover.d))}</b>
            <hr />
            {cap.groups.map((g) => {
              const n = run ? g.planned[hover.d] : g.base[hover.d];
              const away = g.size - g.base[hover.d], train = g.base[hover.d] - g.planned[hover.d];
              return (
                <div className="l" key={g.group_id}>
                  <span>{g.name.replace(" Company", "")}</span>
                  <span className={n < g.min_available ? "low" : ""}>
                    {n} of {g.size}{away ? `, ${away} away` : ""}{run && train ? `, ${train} training` : ""}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </>
  );
}
