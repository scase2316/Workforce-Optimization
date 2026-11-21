import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import type { Facets, Preview, Rule, RuleDraft, SessionPlan } from "./types";
import { MONTH } from "./util";

type Unit = "days" | "months";
const toDays = (n: number, u: Unit) => Math.max(0, Math.round(u === "months" ? n * MONTH : n));
function fromDays(d: number): { n: number; u: Unit } {
  const m = d / MONTH;
  return d >= 60 && Math.abs(m - Math.round(m)) < 0.02 ? { n: Math.round(m), u: "months" } : { n: d, u: "days" };
}

interface Props {
  pack: string; facets: Facets; rules: Rule[]; people: string;
  initial: RuleDraft | null; editingId: string | null; note?: string;
  onClose: () => void; onSaved: () => void;
}

export default function RuleEditor({ pack, facets, rules, people, initial, editingId, note, onClose, onSaved }: Props) {
  const blank: RuleDraft = { name: "", trigger_type: "promotion", roles: [], attributes: {}, deadline_days: 365, valid_days: null, duration_days: 1, prerequisites: [] };
  const start = initial ?? blank;
  const [name, setName] = useState(start.name);
  const [trigger, setTrigger] = useState(start.trigger_type);
  const [roles, setRoles] = useState<string[]>(start.roles);
  const [attrs, setAttrs] = useState<Record<string, string[]>>(start.attributes);
  const dl = fromDays(start.deadline_days);
  const [dlN, setDlN] = useState(dl.n); const [dlU, setDlU] = useState<Unit>(dl.u);
  const vl = fromDays(start.valid_days ?? 365);
  const [expires, setExpires] = useState(start.valid_days !== null);
  const [vlN, setVlN] = useState(vl.n); const [vlU, setVlU] = useState<Unit>(vl.u);
  const [length, setLength] = useState(start.duration_days);
  const [prereqs, setPrereqs] = useState<string[]>(start.prerequisites);
  const wasNew = editingId === null;
  const [withSessions, setWithSessions] = useState(wasNew);
  const [sess, setSess] = useState<SessionPlan>({ first_offset_days: 5, every_days: 30, seats: 10, location: "" });
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const draft: RuleDraft = useMemo(() => ({
    name, trigger_type: trigger, roles, attributes: Object.fromEntries(Object.entries(attrs).filter(([, v]) => v.length)),
    deadline_days: toDays(dlN, dlU), valid_days: expires ? toDays(vlN, vlU) : null, duration_days: length,
    prerequisites: prereqs, sessions: withSessions ? sess : null,
  }), [name, trigger, roles, attrs, dlN, dlU, expires, vlN, vlU, length, prereqs, withSessions, sess]);

  const seq = useRef(0);
  useEffect(() => {
    const id = ++seq.current;
    const t = setTimeout(() => {
      api.previewRule(pack, { ...draft, sessions: undefined }, editingId ?? undefined)
        .then((p) => { if (id === seq.current) setPreview(p); })
        .catch((e: Error) => { if (id === seq.current) setPreview({ errors: [e.message] }); });
    }, 350);
    return () => clearTimeout(t);
  }, [pack, draft, editingId]);

  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);

  const toggle = (list: string[], v: string) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);
  const save = async () => {
    setBusy(true); setErr(null);
    try { if (editingId) await api.updateRule(pack, editingId, draft); else await api.createRule(pack, draft); onSaved(); }
    catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const remove = async () => {
    setBusy(true); setErr(null);
    try { await api.deleteRule(pack, editingId!); onSaved(); } catch (e) { setErr((e as Error).message); setConfirmDelete(false); } finally { setBusy(false); }
  };
  const bs = preview?.by_status;
  const blocked = !!preview?.errors.length;

  return (
    <>
      <div className="drawer-back" onClick={onClose} />
      <aside className="drawer editor" role="dialog" aria-label={editingId ? "Edit requirement" : "New requirement"}>
        <button className="btn quiet close" onClick={onClose}>Close</button>
        <h3>{editingId ? "Edit requirement" : "New requirement"}</h3>
        {note && <p className="muted" style={{ marginTop: 4 }}>{note}</p>}

        <label className="field">Name
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Infantry Unit Leaders Course" />
        </label>

        <label className="field">When it starts
          <select value={trigger} onChange={(e) => setTrigger(e.target.value)}>
            {facets.triggers.map((t) => <option key={t.value} value={t.value} disabled={!t.available}>{t.label}{t.available ? "" : " (no such events in this scenario)"}</option>)}
          </select>
        </label>

        <fieldset className="field"><legend>Applies to</legend>
          <div className="hint">Leave a group empty to include everyone in it.</div>
          <div className="checks"><b>Role</b>{facets.roles.map((r) => (
            <label key={r.value}><input type="checkbox" checked={roles.includes(r.value)} onChange={() => setRoles(toggle(roles, r.value))} />{r.value} <span className="muted">{r.count}</span></label>))}
          </div>
          {Object.entries(facets.attributes).map(([k, a]) => (
            <div className="checks" key={k}><b>{a.label}</b>{a.values.map((v) => (
              <label key={v.value}><input type="checkbox" checked={(attrs[k] ?? []).includes(v.value)}
                onChange={() => setAttrs({ ...attrs, [k]: toggle(attrs[k] ?? [], v.value) })} />{v.label} <span className="muted">{v.count}</span></label>))}
            </div>
          ))}
        </fieldset>

        <div className="field"><span>Deadline after it starts</span>
          <div className="inline">
            <input type="number" min={1} value={dlN} onChange={(e) => setDlN(Number(e.target.value))} aria-label="Deadline amount" />
            <select value={dlU} onChange={(e) => setDlU(e.target.value as Unit)} aria-label="Deadline unit"><option value="days">days</option><option value="months">months</option></select>
            <span className="muted">{draft.deadline_days} days</span>
          </div>
        </div>

        <div className="field"><span>How long a completion lasts</span>
          <div className="inline">
            <select value={expires ? "yes" : "no"} onChange={(e) => setExpires(e.target.value === "yes")} aria-label="Expires">
              <option value="no">Never expires</option><option value="yes">Expires after</option></select>
            {expires && <>
              <input type="number" min={1} value={vlN} onChange={(e) => setVlN(Number(e.target.value))} aria-label="Valid amount" />
              <select value={vlU} onChange={(e) => setVlU(e.target.value as Unit)} aria-label="Valid unit"><option value="days">days</option><option value="months">months</option></select></>}
          </div>
        </div>

        <label className="field">Course length (days)
          <input type="number" min={1} max={365} value={length} onChange={(e) => setLength(Number(e.target.value))} style={{ width: 90 }} />
        </label>

        {rules.filter((r) => r.id !== editingId).length > 0 && (
          <fieldset className="field"><legend>Must finish first</legend>
            <div className="checks">{rules.filter((r) => r.id !== editingId).map((r) => (
              <label key={r.id}><input type="checkbox" checked={prereqs.includes(r.id)} onChange={() => setPrereqs(toggle(prereqs, r.id))} />{r.name}</label>))}</div>
          </fieldset>
        )}

        <fieldset className="field"><legend>Sessions</legend>
          {!wasNew && <label className="check1"><input type="checkbox" checked={withSessions} onChange={(e) => setWithSessions(e.target.checked)} />Replace this requirement's sessions</label>}
          {!wasNew && !withSessions && <div className="hint">Keeping the current {rules.find((r) => r.id === editingId)?.session_count ?? 0} sessions.</div>}
          {withSessions && (
            <div className="inline wrap">
              <span>First in</span><input type="number" min={1} value={sess.first_offset_days} onChange={(e) => setSess({ ...sess, first_offset_days: Number(e.target.value) })} aria-label="First session in days" /><span>days, then every</span>
              <input type="number" min={1} value={sess.every_days} onChange={(e) => setSess({ ...sess, every_days: Number(e.target.value) })} aria-label="Repeat every days" /><span>days with</span>
              <input type="number" min={1} max={500} value={sess.seats} onChange={(e) => setSess({ ...sess, seats: Number(e.target.value) })} aria-label="Seats" /><span>seats at</span>
              <input value={sess.location} onChange={(e) => setSess({ ...sess, location: e.target.value })} placeholder="Location" aria-label="Location" />
            </div>)}
          {wasNew && !withSessions && <div className="hint">Without sessions the optimizer can't place anyone, and will say so.</div>}
        </fieldset>

        <div className="preview" aria-live="polite">
          {!preview && <span className="muted">Checking…</span>}
          {preview && blocked && <ul className="errs">{preview.errors.map((e, i) => <li key={i}>{e}</li>)}</ul>}
          {preview && !blocked && bs && (
            <span>Applies to <b>{preview.applies_to}</b> of {preview.people_total} {people.toLowerCase()}. Today: {bs.overdue} overdue, {bs.gap} open, {bs.expiring} expiring, {bs.complete} ready.
              {" "}Overall readiness {preview.readiness_before_pct}% → {preview.readiness_after_pct}%.</span>)}
        </div>
        {err && <div className="error" role="alert">{err}</div>}

        <div className="row-actions" style={{ marginTop: 18 }}>
          <button className="btn primary" disabled={busy || blocked || !preview} onClick={save}>{busy ? "Saving…" : editingId ? "Save changes" : "Add requirement"}</button>
          <button className="btn" onClick={onClose}>Cancel</button>
          {editingId && !confirmDelete && <button className="btn quiet" onClick={() => setConfirmDelete(true)}>Delete</button>}
        </div>
        {confirmDelete && (
          <div className="diff" style={{ marginTop: 14 }}>
            <p>Delete this requirement and its sessions? Completion history stays on record.</p>
            <div className="row-actions"><button className="btn" disabled={busy} onClick={remove}>Delete requirement</button><button className="btn quiet" onClick={() => setConfirmDelete(false)}>Keep it</button></div>
          </div>)}
      </aside>
    </>
  );
}
