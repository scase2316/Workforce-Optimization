import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import RuleEditor from "./RuleEditor";
import type { AIStatus, Facets, Overview, Proposal, Rule, RuleDraft } from "./types";
import { plural, span } from "./util";

const STARTS: Record<string, string> = { promotion: "After promotion", hire: "After hire", standing: "Everyone, repeating" };

function appliesTo(r: { roles: string[]; attributes: Record<string, string[]> }, f: Facets, people: string): string {
  const who = r.roles.length ? r.roles.join(" or ") : `All ${people.toLowerCase()}`;
  const filters = Object.entries(r.attributes).filter(([, v]) => v.length).map(([k, v]) => {
    const a = f.attributes[k];
    return `${a?.label ?? k}: ${v.map((x) => a?.values.find((y) => y.value === x)?.label ?? x).join(", ")}`;
  });
  return filters.length ? `${who}; ${filters.join("; ")}` : who;
}

export default function Rules({ pack, overview, ai, onChanged }: { pack: string; overview: Overview; ai: AIStatus | null; onChanged: () => void }) {
  const v = overview.vocabulary;
  const [rules, setRules] = useState<Rule[]>([]);
  const [facets, setFacets] = useState<Facets | null>(null);
  const [editor, setEditor] = useState<{ initial: RuleDraft | null; id: string | null; note?: string } | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [result, setResult] = useState<{ proposals: Proposal[]; unclear: string[] } | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);

  const load = useCallback(() => api.rules(pack).then((r) => { setRules(r.rules); setFacets(r.facets); }), [pack]);
  useEffect(() => { void load(); setResult(null); setText(""); setErr(null); }, [load]);

  const example = pack === "marine_corps"
    ? "SSgts have 18 months from promotion to complete Cold Weather Course."
    : "New hires have 30 days from hire to complete Data Privacy Training.";

  const draft = async () => {
    setBusy(true); setErr(null); setResult(null);
    try { setResult(await api.aiRules(pack, text)); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const saved = () => { setEditor(null); void load(); onChanged(); };
  const reset = async () => { await api.reset(pack); setConfirmReset(false); void load(); onChanged(); };
  if (!facets) return <p className="muted">Loading…</p>;

  return (
    <>
      <h1 className="lead">{plural(rules.length, "requirement")} decide who is ready.</h1>
      <p className="lead-sub">
        Change a rule and readiness updates straight away. Any schedule made before a change is flagged until you optimize again.
      </p>
      <div className="row-actions">
        <button className="btn primary" onClick={() => setEditor({ initial: null, id: null })}>New requirement</button>
        {!confirmReset
          ? <button className="btn quiet" onClick={() => setConfirmReset(true)}>Reset this scenario</button>
          : <span className="row-actions"><span className="muted">Restore the original rules, data, and plans?</span>
              <button className="btn" onClick={reset}>Reset</button><button className="btn quiet" onClick={() => setConfirmReset(false)}>Keep my changes</button></span>}
      </div>

      <h2 className="section">Describe a rule in plain English</h2>
      <p className="section-note">
        {ai?.mode === "live"
          ? `Using ${ai.model}. Paste a sentence or a paragraph of policy. Nothing is saved until you review it and add it.`
          : "Demo mode: understands simple sentences without any AI service. Add an API key on the server for full language understanding. Nothing is saved until you review it."}
      </p>
      <textarea className="askbox" rows={3} value={text} onChange={(e) => setText(e.target.value)} placeholder={example} aria-label="Describe a rule" />
      <div className="row-actions" style={{ marginTop: 8 }}>
        <button className="btn" disabled={busy || !text.trim()} onClick={draft}>{busy ? "Reading…" : "Draft rules"}</button>
        <button className="btn quiet" onClick={() => setText(example)}>Use an example</button>
      </div>
      {err && <div className="error" role="alert" style={{ marginTop: 12 }}>{err}</div>}
      {result && (
        <div style={{ marginTop: 16 }}>
          {result.proposals.length === 0 && <div className="empty"><p>No rules found.</p>{result.unclear.map((u, i) => <p key={i}>{u}</p>)}</div>}
          {result.proposals.map((p, i) => (
            <div className="proposal" key={i}>
              <div className="top"><b>{p.rule.name || "Untitled"}</b><span className="chip" data-s={p.confidence === "high" ? "complete" : p.confidence === "low" ? "overdue" : "gap"}>{p.confidence} confidence</span></div>
              <div>Applies to {appliesTo(p.rule, facets, v.people)}. Starts {STARTS[p.rule.trigger_type].toLowerCase()}; {span(p.rule.deadline_days)} to finish;
                {p.rule.valid_days ? ` valid for ${span(p.rule.valid_days)}` : " never expires"}.</div>
              {p.preview && !p.errors.length && <div className="muted">Would apply to {p.preview.applies_to} of {p.preview.people_total} {v.people.toLowerCase()}; {p.preview.by_status?.overdue ?? 0} would be overdue today.</div>}
              {p.errors.map((e, j) => <div className="err1" key={j}>{e}</div>)}
              {p.assumptions.map((a, j) => <div className="muted" key={j}>Assumed: {a}</div>)}
              {p.source_quote && <div className="quote">From your text: “{p.source_quote}”</div>}
              <div className="row-actions" style={{ marginTop: 8 }}>
                <button className="btn primary" onClick={() => setEditor({ initial: p.rule, id: null, note: "Check each field, then add it. Nothing has been saved yet." })}>Review and add</button>
              </div>
            </div>
          ))}
          {result.proposals.length > 0 && result.unclear.map((u, i) => <p className="muted" key={i}>Unclear: {u}</p>)}
        </div>
      )}

      <h2 className="section">All requirements</h2>
      <p className="section-note">Select a row to edit it.</p>
      <table>
        <thead><tr><th>Requirement</th><th>Applies to</th><th>Starts</th><th>Deadline</th><th>Lasts</th><th>Needs first</th><th className="r">Sessions</th></tr></thead>
        <tbody>
          {rules.map((r) => (
            <tr key={r.id} className="click" tabIndex={0} onClick={() => setEditor({ initial: r, id: r.id })} onKeyDown={(e) => e.key === "Enter" && setEditor({ initial: r, id: r.id })}>
              <td><b>{r.name}</b></td><td className="why">{appliesTo(r, facets, v.people)}</td><td>{STARTS[r.trigger_type]}</td>
              <td>{span(r.deadline_days)}</td><td>{r.valid_days ? span(r.valid_days) : <span className="muted">Never expires</span>}</td>
              <td className="why">{r.prerequisites.map((p) => rules.find((x) => x.id === p)?.name ?? p).join(", ") || <span className="muted">None</span>}</td>
              <td className="r">{r.session_count === 0 ? <span className="chip" data-s="overdue">None</span> : r.session_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {editor && <RuleEditor key={editor.id ?? editor.initial?.name ?? "new"} pack={pack} facets={facets} rules={rules} people={v.people}
        initial={editor.initial} editingId={editor.id} note={editor.note} onClose={() => setEditor(null)} onSaved={saved} />}
    </>
  );
}
