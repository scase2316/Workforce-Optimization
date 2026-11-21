import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import type { Assignment, Capacity, Overview, Run } from "./types";
import { fmt, plural, STATUS_LABEL } from "./util";

function why(a: Assignment): string {
  const r = a.rationale;
  const lead =
    r.status === "overdue" ? `Overdue since ${fmt(r.due)}.`
    : r.status === "expiring" ? `Renewed before it lapses on ${fmt(r.due)}.`
    : r.meets_deadline ? `Due ${fmt(r.due)}, on track.` : `Due ${fmt(r.due)}, misses by ${plural(r.days_after_deadline, "day")}.`;
  const e = r.earlier_options[0];
  return `${lead} ${e ? `Earlier session on ${fmt(e.start)} ${e.reason}.` : "Earliest session that fits."}`;
}

export default function Schedule({ pack, overview, run, setRun }: { pack: string; overview: Overview; run: Run | null; setRun: (r: Run | null) => void }) {
  const v = overview.vocabulary;
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [cap, setCap] = useState<Capacity | null>(null);
  const [shiftId, setShiftId] = useState<number | null>(null);
  const [days, setDays] = useState(14);
  const [reqId, setReqId] = useState(overview.requirements[0]?.id ?? "");
  const [seats, setSeats] = useState(4);
  const [groupFilter, setGroupFilter] = useState(0);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => { setShiftId(null); setReqId(overview.requirements[0]?.id ?? ""); setErr(null); }, [pack, overview]);
  useEffect(() => { api.capacity(pack).then(setCap); }, [pack]);
  const commitments = (run?.capacity ?? cap)?.commitments ?? [];
  const groupName = (id: number) => overview.groups.find((g) => g.group_id === id)?.name ?? "";
  useEffect(() => { if (shiftId === null && commitments.length) setShiftId(commitments[0].id); }, [commitments, shiftId]);

  const act = async (label: string, fn: () => Promise<Run | null>) => {
    setBusy(label); setErr(null);
    try { const r = await fn(); if (r) setRun(r); } catch (e) { setErr((e as Error).message); } finally { setBusy(null); }
  };

  const rows = useMemo(() => (run?.assignments ?? []).filter((a) => !groupFilter || a.group_id === groupFilter)
    .sort((a, b) => a.start.localeCompare(b.start) || a.person.localeCompare(b.person)), [run, groupFilter]);
  const shown = showAll ? rows : rows.slice(0, 40);

  if (!run) {
    return (
      <>
        <h1 className="lead">No schedule yet.</h1>
        <p className="lead-sub">
          The optimizer places every outstanding requirement into the earliest session that fits: seats, prerequisites, each person's commitments,
          and the minimum number of {v.people.toLowerCase()} each {v.group.toLowerCase()} needs on hand every day.
        </p>
        {err && <div className="error" role="alert">{err}</div>}
        <button className="btn primary" disabled={!!busy} onClick={() => act("opt", () => api.optimize(pack))}>{busy ? "Optimizing…" : "Optimize schedule"}</button>
      </>
    );
  }

  const s = run.summary;
  const d = run.diff;
  return (
    <>
      <h1 className="lead">
        {s.scheduled} of {s.items_outstanding} outstanding items are scheduled. Readiness goes from {s.readiness_before_pct}% to {s.readiness_after_pct}%.
      </h1>
      <p className="lead-sub">
        {s.unscheduled > 0 ? `${plural(s.unscheduled, "item")} could not be placed; the reasons are listed below. ` : ""}
        Nothing takes effect until someone approves the plan.
      </p>

      {err && <div className="error" role="alert">{err}</div>}
      <div className="approve-bar">
        <span className="chip" data-s={run.run_status}>{run.run_status === "proposed" ? "Proposed" : run.run_status === "approved" ? "Approved" : "Rejected"}</span>
        <button className="btn primary" disabled={!!busy || run.run_status === "approved"}
          onClick={() => act("approve", async () => { await api.setStatus(run.run_id, "approved"); return { ...run, run_status: "approved" }; })}>Approve schedule</button>
        <button className="btn" disabled={!!busy || run.run_status === "rejected"}
          onClick={() => act("reject", async () => { await api.setStatus(run.run_id, "rejected"); return { ...run, run_status: "rejected" }; })}>Reject</button>
        <button className="btn quiet" disabled={!!busy} onClick={() => act("opt", () => api.optimize(pack))}>Start over</button>
        {run.run_status === "approved" && <span className="muted">In a live deployment this step would reserve seats and update calendars.</span>}
      </div>

      <div className="summary">
        <div><div className="v">{s.overdue_cleared}</div><div className="k">overdue items cleared</div></div>
        <div><div className="v">{s.on_time}</div><div className="k">other items placed before their deadline</div></div>
        <div><div className="v">{Math.round(run.runtime_s * 1000)} ms</div><div className="k">to {run.optimal ? "solve to optimal" : "find this plan"}</div></div>
      </div>

      <h2 className="section">Test a change</h2>
      <p className="section-note">Move a commitment or limit seats, then re-optimize. You'll see only what changed from the plan above.</p>
      <div className="whatif">
        <div className="line">
          <span>Move</span>
          <select value={shiftId ?? ""} onChange={(e) => setShiftId(Number(e.target.value))} aria-label="Commitment">
            {commitments.map((c) => <option key={c.id} value={c.id}>{groupName(c.group_id)}: {c.name}</option>)}
          </select>
          <span>by</span>
          <input type="number" min={-60} max={90} value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Days to move" />
          <span>days</span>
          <button className="btn" disabled={!!busy || shiftId === null || days === 0}
            onClick={() => act("shift", () => api.whatIf(pack, run.run_id, { shift: [{ commitment_id: shiftId!, days }] }))}>
            {busy === "shift" ? "Re-optimizing…" : "Move and re-optimize"}
          </button>
        </div>
        <div className="line">
          <span>Limit seats for</span>
          <select value={reqId} onChange={(e) => setReqId(e.target.value)} aria-label="Requirement">
            {overview.requirements.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
          </select>
          <span>to</span>
          <input type="number" min={0} max={200} value={seats} onChange={(e) => setSeats(Number(e.target.value))} aria-label="Seats per session" />
          <span>per session</span>
          <button className="btn" disabled={!!busy || !reqId}
            onClick={() => act("seats", () => api.whatIf(pack, run.run_id, { seat_cap: [{ requirement_id: reqId, seats }] }))}>
            {busy === "seats" ? "Re-optimizing…" : "Limit and re-optimize"}
          </button>
        </div>
      </div>
      {d && run.compared_to && (
        <div className="diff">
          <p><b>Compared with the previous plan:</b> {plural(d.moved.length, "item")} moved, {plural(d.removed.length, "item")} no longer scheduled,
            {" "}{plural(d.added.length, "item")} newly scheduled. {run.compared_to.summary.readiness_after_pct === s.readiness_after_pct ? `Readiness is unchanged at ${s.readiness_after_pct}%.` : `Readiness ${run.compared_to.summary.readiness_after_pct}% to ${s.readiness_after_pct}%.`}</p>
          {(d.moved.length > 0 || d.removed.length > 0) && (
            <ul>
              {d.moved.slice(0, 6).map((m, i) => <li key={`m${i}`}>{m.person}, {m.requirement}: {fmt(m.from)} to {fmt(m.to)}</li>)}
              {d.removed.slice(0, 4).map((r, i) => <li key={`r${i}`}>{r.person}, {r.requirement}: no longer fits ({fmt(r.start)})</li>)}
              {d.moved.length + d.removed.length > 10 && <li>and {d.moved.length + d.removed.length - 10} more</li>}
            </ul>
          )}
          {run.parent_run_id && (
            <button className="btn quiet" disabled={!!busy} onClick={() => act("back", () => api.run(run.parent_run_id!))}>Go back to the previous plan</button>
          )}
        </div>
      )}

      {run.unscheduled.length > 0 && (
        <>
          <h2 className="section">Not scheduled</h2>
          <p className="section-note">These need a person to decide: add a session, free up a date, or accept the gap.</p>
          <table>
            <thead><tr><th>Name</th><th>Requirement</th><th>Status</th><th>Why</th></tr></thead>
            <tbody>
              {run.unscheduled.slice(0, 15).map((u, i) => (
                <tr key={i}><td><b>{u.person}</b></td><td>{u.requirement}</td>
                  <td><span className="chip" data-s={u.status}>{STATUS_LABEL[u.status]}</span></td><td className="why">{u.reason}</td></tr>
              ))}
            </tbody>
          </table>
          {run.unscheduled.length > 15 && <p className="muted">and {run.unscheduled.length - 15} more.</p>}
        </>
      )}

      <h2 className="section">The plan</h2>
      <p className="section-note">Every assignment with the reason it landed where it did.</p>
      <div className="filters">
        <select value={groupFilter} onChange={(e) => setGroupFilter(Number(e.target.value))} aria-label={v.group}>
          <option value={0}>All {v.groups.toLowerCase()}</option>
          {overview.groups.map((g) => <option key={g.group_id} value={g.group_id}>{g.name}</option>)}
        </select>
      </div>
      <table>
        <thead><tr><th>Starts</th><th>Name</th><th>Requirement</th><th>Where</th><th>Why this slot</th></tr></thead>
        <tbody>
          {shown.map((a) => (
            <tr key={`${a.person_id}-${a.requirement_id}`}>
              <td>{fmt(a.start)}{a.end !== a.start && <span className="muted"> to {fmt(a.end)}</span>}</td>
              <td><b>{a.person}</b></td><td>{a.requirement}</td><td className="muted">{a.location}</td><td className="why">{why(a)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {!showAll && rows.length > shown.length && (
        <p><button className="btn" onClick={() => setShowAll(true)}>Show all {rows.length}</button></p>
      )}
    </>
  );
}
