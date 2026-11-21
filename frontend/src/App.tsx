import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { AIStatus, Overview, PackInfo, Run } from "./types";
import { setBaseYear } from "./util";
import Readiness from "./Readiness";
import Capacity from "./Capacity";
import Schedule from "./Schedule";
import Rules from "./Rules";

type View = "readiness" | "rules" | "capacity" | "schedule";
const NAV: { id: View; label: string }[] = [
  { id: "readiness", label: "Readiness" },
  { id: "rules", label: "Rules" },
  { id: "capacity", label: "Capacity" },
  { id: "schedule", label: "Schedule" },
];

export default function App() {
  const [packs, setPacks] = useState<PackInfo[]>([]);
  const [packId, setPackId] = useState("marine_corps");
  const [view, setView] = useState<View>("readiness");
  const [overview, setOverview] = useState<Overview | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ai, setAi] = useState<AIStatus | null>(null);

  useEffect(() => { api.packs().then(setPacks).catch((e: Error) => setError(e.message)); api.aiStatus().then(setAi).catch(() => setAi(null)); }, []);
  const refreshOverview = useCallback(() => api.overview(packId).then(setOverview), [packId]);

  const load = useCallback(async (id: string) => {
    setOverview(null); setRun(null); setError(null);
    try {
      const [o, r] = await Promise.all([api.overview(id), api.latest(id)]);
      setBaseYear(o.as_of);
      setOverview(o); setRun(r);
    } catch (e) { setError((e as Error).message); }
  }, []);
  useEffect(() => { void load(packId); }, [packId, load]);

  return (
    <div className="app" data-pack={packId}>
      <aside className="rail">
        <h1>Readiness Optimizer</h1>
        <p className="sub">Schedule training around operations.</p>
        <h2>Scenario</h2>
        <div className="packs">
          {packs.map((p) => (
            <button key={p.id} className="pack-btn" aria-current={p.id === packId} onClick={() => setPackId(p.id)}>
              {p.name}<small>{p.tagline}</small>
            </button>
          ))}
        </div>
        <h2>View</h2>
        <nav className="nav">
          {NAV.map((n) => (
            <button key={n.id} aria-current={n.id === view} onClick={() => setView(n.id)}>{n.label}</button>
          ))}
        </nav>
        <p className="note">
          {ai ? (ai.mode === "live" ? `AI on (${ai.model}).` : "AI in demo mode.") : ""}<br />
          {overview?.vocabulary.disclaimer ?? "Synthetic data only."}
        </p>
      </aside>
      <main>
        {error && <div className="error" role="alert">{error}</div>}
        {!overview && !error && <p className="muted">Loading…</p>}
        {overview && view === "readiness" && <Readiness pack={packId} overview={overview} />}
        {overview && view === "rules" && <Rules pack={packId} overview={overview} ai={ai} onChanged={refreshOverview} />}
        {overview && view === "capacity" && <Capacity pack={packId} overview={overview} run={run} goToSchedule={() => setView("schedule")} />}
        {overview && view === "schedule" && <Schedule pack={packId} overview={overview} run={run} setRun={setRun} ai={ai} />}
      </main>
    </div>
  );
}
