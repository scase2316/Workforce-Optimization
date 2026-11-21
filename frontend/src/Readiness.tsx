import { useEffect, useState } from "react";
import { api } from "./api";
import type { GroupRow, Overview, PersonDetail, PersonRow } from "./types";
import { fmt, plural, STATUS_LABEL } from "./util";

function Segments({ g }: { g: GroupRow }) {
  const total = g.complete + g.expiring + g.gap + g.overdue || 1;
  const parts: [keyof GroupRow & string, number][] = [["complete", g.complete], ["expiring", g.expiring], ["gap", g.gap], ["overdue", g.overdue]];
  return (
    <div className="seg" role="img" aria-label={`${g.complete} ready, ${g.expiring} expiring, ${g.gap} open, ${g.overdue} overdue`}>
      {parts.filter(([, n]) => n > 0).map(([k, n]) => <i key={k} data-s={k} style={{ flex: n / total }} title={`${STATUS_LABEL[k]}: ${n}`} />)}
    </div>
  );
}

function Drawer({ pack, id, onClose }: { pack: string; id: number; onClose: () => void }) {
  const [d, setD] = useState<PersonDetail | null>(null);
  useEffect(() => {
    api.person(pack, id).then(setD);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [pack, id, onClose]);
  const order = ["overdue", "gap", "expiring", "complete"];
  return (
    <>
      <div className="drawer-back" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label="Person detail">
        <button className="btn quiet close" onClick={onClose}>Close</button>
        {!d ? <p className="muted">Loading…</p> : (
          <>
            <h3>{d.name}</h3>
            <div className="muted">{d.role}, {d.group}. Since {fmt(d.start_date)}. {d.readiness_pct}% ready.</div>
            <ul>
              {[...d.items].sort((a, b) => order.indexOf(a.status) - order.indexOf(b.status)).map((i) => (
                <li key={i.requirement_id}>
                  <div className="top"><span>{i.name}</span><span className="chip" data-s={i.status}>{STATUS_LABEL[i.status]}</span></div>
                  {i.status === "overdue" && <span className="muted">Was due {fmt(i.due)}</span>}
                  {i.status === "gap" && <span className="muted">Due {fmt(i.due)}</span>}
                  {i.status === "expiring" && <span className="muted">Lapses {fmt(i.due)}</span>}
                  {i.blocked_by.length > 0 && <span className="muted">Waiting on a prerequisite first</span>}
                </li>
              ))}
            </ul>
          </>
        )}
      </aside>
    </>
  );
}

export default function Readiness({ pack, overview }: { pack: string; overview: Overview }) {
  const v = overview.vocabulary;
  const t = overview.totals;
  const [groupId, setGroupId] = useState<number | null>(null);
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<PersonRow[]>([]);
  const [limit, setLimit] = useState(25);
  const [open, setOpen] = useState<number | null>(null);

  useEffect(() => { setGroupId(null); setStatus(""); setQ(""); setLimit(25); }, [pack]);
  useEffect(() => {
    const p = new URLSearchParams({ limit: String(limit + 1) });
    if (groupId) p.set("group_id", String(groupId));
    if (status) p.set("status", status);
    if (q) p.set("q", q);
    api.people(pack, p).then(setRows);
  }, [pack, groupId, status, q, limit]);

  const groupName = (id: number) => overview.groups.find((g) => g.group_id === id)?.name ?? "";
  const worstReq = [...overview.requirements].sort((a, b) => b.overdue - a.overdue);
  const maxOver = Math.max(1, ...worstReq.map((r) => r.overdue));
  const lapsing = t.expiring;

  return (
    <>
      <h1 className="lead">{v.people} are {t.readiness_pct}% ready across {plural(overview.groups.length, v.group.toLowerCase())}.</h1>
      <p className="lead-sub">
        {plural(t.overdue, "requirement")} {t.overdue === 1 ? "is" : "are"} overdue, and {lapsing} more lapse within 60 days.
        Pick a {v.group.toLowerCase()} to see who is behind.
      </p>

      <div className="legend" aria-label="Legend">
        <span><i className="sw" style={{ background: "var(--ready)" }} />Ready</span>
        <span><i className="sw" style={{ background: "var(--expiring)" }} />Ready, lapses within 60 days</span>
        <span><i className="sw" style={{ background: "var(--open)" }} />Open, deadline ahead</span>
        <span><i className="sw" style={{ background: "var(--overdue)" }} />Overdue</span>
      </div>
      <div className="groups">
        <div className="grow head" aria-hidden>
          <span>{v.group}</span><span className="seg-cell" /><span className="num">Ready</span><span className="num hide-sm">Expiring</span><span className="num hide-sm">Open</span><span className="num hide-sm">Overdue</span>
        </div>
        {overview.groups.map((g) => (
          <button key={g.group_id} className="grow" aria-pressed={groupId === g.group_id}
            onClick={() => setGroupId(groupId === g.group_id ? null : g.group_id)}>
            <span className="gname">{g.name}<small>{plural(g.people, v.person.toLowerCase())}</small></span>
            <span className="seg-cell"><Segments g={g} /></span>
            <span className="num pct">{g.readiness_pct}%</span>
            <span className="num hide-sm">{g.expiring}</span>
            <span className="num hide-sm">{g.gap}</span>
            <span className="num hide-sm">{g.overdue}</span>
          </button>
        ))}
      </div>

      <h2 className="section">Where the overdue work sits</h2>
      <p className="section-note">Overdue count by requirement, across everyone.</p>
      <div className="reqs">
        {worstReq.map((r) => (
          <div key={r.id} style={{ display: "contents" }}>
            <span>{r.name}</span>
            <span className="bar" aria-hidden><i style={{ width: `${(100 * r.overdue) / maxOver}%` }} /></span>
            <span className="n">{r.overdue}</span>
          </div>
        ))}
      </div>

      <h2 className="section">{v.people}</h2>
      <p className="section-note">Sorted by most overdue first. Select a row for the full list.</p>
      <div className="filters">
        <input placeholder={`Search ${v.people.toLowerCase()}`} value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search by name" />
        <select value={groupId ?? ""} onChange={(e) => setGroupId(e.target.value ? Number(e.target.value) : null)} aria-label={v.group}>
          <option value="">All {v.groups.toLowerCase()}</option>
          {overview.groups.map((g) => <option key={g.group_id} value={g.group_id}>{g.name}</option>)}
        </select>
        <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status">
          <option value="">Any status</option>
          <option value="overdue">Has overdue items</option>
          <option value="expiring">Has expiring items</option>
          <option value="gap">Has open items</option>
        </select>
      </div>
      {rows.length === 0 ? <div className="empty"><p>No {v.people.toLowerCase()} match these filters.</p></div> : (
        <table>
          <thead><tr><th>Name</th><th>Role</th><th>{v.group}</th><th className="r">Ready</th><th className="r">Overdue</th><th className="r">Open</th><th className="r">Expiring</th></tr></thead>
          <tbody>
            {rows.slice(0, limit).map((r) => (
              <tr key={r.person_id} className="click" tabIndex={0} onClick={() => setOpen(r.person_id)}
                onKeyDown={(e) => e.key === "Enter" && setOpen(r.person_id)}>
                <td><b>{r.name}</b></td><td>{r.role}</td><td className="muted">{groupName(r.group_id)}</td>
                <td className="r">{r.readiness_pct}%</td><td className="r">{r.overdue}</td><td className="r">{r.gap}</td><td className="r">{r.expiring}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {rows.length > limit && <p><button className="btn" onClick={() => setLimit(limit + 50)}>Show more</button></p>}
      {open !== null && <Drawer pack={pack} id={open} onClose={() => setOpen(null)} />}
    </>
  );
}
