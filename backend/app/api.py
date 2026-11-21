"""HTTP API. Thin layer over readiness.py and solver.py.

Run:  uvicorn app.api:app --reload      (from backend/)
Serves the built frontend from ../frontend/dist when present.
"""
from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db
from .packs import list_pack_ids, load_pack
from . import ai as ai_mod
from . import rules as rules_mod
from .readiness import pack_readiness, person_readiness
from .seed import seed_pack
from .solver import (availability, diff_schedules, load_problem, save_run, set_run_status, solve)

DB_PATH = os.environ.get("READINESS_DB", str(Path(__file__).resolve().parents[2] / "demo.db"))
HORIZON = 180

app = FastAPI(title="Readiness Optimizer")
_conn = None
# Endpoints are async on purpose: one shared SQLite connection, used only from the event-loop thread.
_runs: dict[int, dict] = {}          # run_id -> full response payload (cache; DB keeps the record)


def conn():
    global _conn
    if _conn is None:
        c = db.connect(DB_PATH)
        c.row_factory = db.sqlite3.Row
        for pid in list_pack_ids():
            if not c.execute("SELECT 1 FROM pack WHERE id = ?", (pid,)).fetchone():
                seed_pack(c, pid, date.today())
        _conn = c
    return _conn


def as_of(pack: str) -> date:
    r = conn().execute("SELECT value FROM meta WHERE key = ?", (f"as_of:{pack}",)).fetchone()
    if not r:
        raise HTTPException(404, f"unknown pack: {pack}")
    return date.fromisoformat(r[0])


@app.get("/api/packs")
async def packs():
    out = []
    for pid in list_pack_ids():
        v = load_pack(pid)["vocabulary"]
        out.append({"id": pid, "name": v["name"], "tagline": v["tagline"], "vocabulary": v})
    return out


@app.get("/api/{pack}/overview")
async def overview(pack: str):
    d = as_of(pack)
    people = pack_readiness(conn(), pack, d)
    groups = {g["id"]: g for g in conn().execute("SELECT * FROM grp WHERE pack_id = ? ORDER BY id", (pack,))}
    rows, req_counts = [], defaultdict(Counter)
    for gid, g in groups.items():
        mine = [p for p in people if p.group_id == gid]
        c = Counter(i.status for p in mine for i in p.items)
        n = sum(c.values())
        rows.append({"group_id": gid, "name": g["name"], "people": len(mine), "min_available": g["min_available"],
                     "complete": c["complete"], "expiring": c["expiring"], "gap": c["gap"], "overdue": c["overdue"],
                     "readiness_pct": round(100 * (c["complete"] + c["expiring"]) / n, 1) if n else 100.0})
    for p in people:
        for i in p.items:
            req_counts[i.requirement_id][i.status] += 1
    reqs = [{"id": r["id"], "name": r["name"], **{k: req_counts[r["id"]][k] for k in ("complete", "expiring", "gap", "overdue")}}
            for r in conn().execute("SELECT id,name FROM requirement WHERE pack_id = ?", (pack,))]
    tot = Counter(i.status for p in people for i in p.items)
    n = sum(tot.values())
    return {
        "as_of": d.isoformat(), "vocabulary": load_pack(pack)["vocabulary"], "rules_version": rules_mod.get_version(conn(), pack),
        "totals": {"people": len(people), "items": n, "complete": tot["complete"], "expiring": tot["expiring"],
                   "gap": tot["gap"], "overdue": tot["overdue"],
                   "readiness_pct": round(100 * (tot["complete"] + tot["expiring"]) / n, 1) if n else 100.0},
        "groups": rows, "requirements": reqs,
    }


@app.get("/api/{pack}/people")
async def people(pack: str, group_id: Optional[int] = None, status: Optional[str] = None, q: str = "", limit: int = 300):
    out = []
    for p in pack_readiness(conn(), pack, as_of(pack)):
        if group_id and p.group_id != group_id:
            continue
        if q and q.lower() not in p.name.lower():
            continue
        c = Counter(i.status for i in p.items)
        if status and not c[status]:
            continue
        out.append({"person_id": p.person_id, "name": p.name, "role": p.role, "group_id": p.group_id,
                    "readiness_pct": round(p.pct, 1), "overdue": c["overdue"], "gap": c["gap"], "expiring": c["expiring"]})
    out.sort(key=lambda r: (-r["overdue"], r["readiness_pct"], r["name"]))
    return out[:limit]


@app.get("/api/{pack}/people/{pid}")
async def person(pack: str, pid: int):
    row = conn().execute("SELECT * FROM person WHERE id = ? AND pack_id = ?", (pid, pack)).fetchone()
    if not row:
        raise HTTPException(404, "no such person")
    d = person_readiness(conn(), pid, as_of(pack)).to_dict()
    d["group"] = conn().execute("SELECT name FROM grp WHERE id = ?", (row["group_id"],)).fetchone()[0]
    d["start_date"] = row["start_date"]
    return d


def _capacity_payload(pack: str, P, avail) -> dict:
    d = P.as_of
    return {
        "as_of": d.isoformat(), "horizon_days": HORIZON,
        "groups": [{"group_id": gid, "name": g["name"], "size": g["size"], "min_available": g["min_available"],
                    "base": avail[gid]["base"], "planned": avail[gid]["planned"]} for gid, g in P.groups.items()],
        "commitments": [{"id": c.id, "group_id": c.gid, "type": c.type, "name": c.name,
                         "start": (c.start - d.toordinal()), "end": (c.end - d.toordinal()),
                         "people": len(c.people) if c.people else None} for c in P.commitments],
    }


@app.get("/api/{pack}/capacity")
async def capacity(pack: str, run_id: Optional[int] = None):
    d = as_of(pack)
    overrides, assignments = {}, []
    if run_id:
        payload = _get_run(run_id)
        overrides, assignments = payload["constraints_snapshot"]["overrides"], payload["assignments"]
    P = load_problem(conn(), pack, d, overrides)
    return _capacity_payload(pack, P, availability(P, assignments, HORIZON))


class WhatIf(BaseModel):
    shift: list[dict] = []            # [{commitment_id, days}]
    seat_cap: list[dict] = []         # [{requirement_id, seats}]
    cancel_offerings: list[int] = []
    min_available: dict[int, int] = {}


def _overrides(pack: str, w: WhatIf) -> dict:
    ov: dict = {}
    if w.shift:
        ov["shift_commitments"] = {x["commitment_id"]: x["days"] for x in w.shift}
    if w.seat_cap:
        caps = {x["requirement_id"]: x["seats"] for x in w.seat_cap}
        rows = conn().execute("SELECT id, requirement_id FROM offering WHERE pack_id = ?", (pack,)).fetchall()
        ov["seats"] = {r["id"]: caps[r["requirement_id"]] for r in rows if r["requirement_id"] in caps}
    if w.cancel_offerings:
        ov["cancel_offerings"] = w.cancel_offerings
    if w.min_available:
        ov["min_available"] = w.min_available
    return ov


def _build(pack: str, overrides: dict, prior: Optional[list[dict]], parent_run_id: Optional[int]) -> dict:
    d = as_of(pack)
    P = load_problem(conn(), pack, d, overrides)
    r = solve(P, time_limit=20, prior=prior)
    if r["status"] not in ("OPTIMAL", "FEASIBLE"):
        raise HTTPException(422, f"No feasible schedule ({r['status']}). Loosen a constraint and try again.")
    r["constraints_snapshot"]["rules_version"] = rules_mod.get_version(conn(), pack)
    run_id = save_run(conn(), pack, r)
    payload = {**r, "run_id": run_id, "rules_version": r["constraints_snapshot"]["rules_version"], "run_status": "proposed", "parent_run_id": parent_run_id,
               "capacity": _capacity_payload(pack, P, availability(P, r["assignments"], HORIZON)),
               "diff": None}
    if parent_run_id:
        parent = _get_run(parent_run_id)
        payload["diff"] = diff_schedules(parent["assignments"], r["assignments"])
        payload["compared_to"] = {"run_id": parent_run_id, "summary": parent["summary"]}
    _runs[run_id] = payload
    return payload


def _get_run(run_id: int) -> dict:
    if run_id in _runs:
        return _runs[run_id]
    row = conn().execute("SELECT * FROM schedule_run WHERE id = ?", (run_id,)).fetchone()
    if not row:
        raise HTTPException(404, "no such run")
    snap = json.loads(row["constraints_snapshot"])
    ov = {k: v for k, v in snap.get("overrides", {}).items()}
    # JSON turned int keys into strings; load_problem accepts both
    P = load_problem(conn(), row["pack_id"], date.fromisoformat(snap["as_of"]), ov)
    r = solve(P, time_limit=20)
    payload = {**r, "run_id": run_id, "run_status": row["status"], "parent_run_id": None, "rules_version": snap.get("rules_version", 0),
               "capacity": _capacity_payload(row["pack_id"], P, availability(P, r["assignments"], HORIZON)), "diff": None}
    _runs[run_id] = payload
    return payload


@app.post("/api/{pack}/schedule")
async def propose(pack: str):
    """Optimize the current plan. Starts a fresh baseline proposal."""
    as_of(pack)
    return _build(pack, {}, None, None)


@app.post("/api/{pack}/schedule/{run_id}/what-if")
async def what_if(pack: str, run_id: int, w: WhatIf):
    """Re-optimize with changed constraints; the response carries the diff against `run_id`."""
    base = _get_run(run_id)
    return _build(pack, _overrides(pack, w), base["assignments"], run_id)


@app.get("/api/{pack}/schedule/latest")
async def latest(pack: str):
    row = conn().execute("SELECT id FROM schedule_run WHERE pack_id = ? ORDER BY id DESC LIMIT 1", (pack,)).fetchone()
    if not row:
        return None
    return _get_run(row[0])


class SessionsBody(BaseModel):
    first_offset_days: int = 3
    every_days: int = 14
    seats: int = 10
    location: str = ""


class RuleBody(BaseModel):
    id: Optional[str] = None
    name: str
    trigger_type: str
    roles: list[str] = []
    attributes: dict[str, list[str]] = {}
    deadline_days: int
    valid_days: Optional[int] = None
    duration_days: int = 1
    prerequisites: list[str] = []
    sessions: Optional[SessionsBody] = None


def _rule_errors(e: rules_mod.RuleError):
    raise HTTPException(e.status, e.errors)


@app.get("/api/{pack}/rules")
async def get_rules(pack: str):
    as_of(pack)
    return {"rules": rules_mod.list_rules(conn(), pack), "facets": rules_mod.facets(conn(), pack),
            "rules_version": rules_mod.get_version(conn(), pack)}


@app.post("/api/{pack}/rules/preview")
async def preview_rule(pack: str, body: RuleBody, rule_id: Optional[str] = None):
    return rules_mod.preview(conn(), pack, body.model_dump(), rule_id, as_of(pack), HORIZON)


@app.post("/api/{pack}/rules")
async def create_rule(pack: str, body: RuleBody):
    try:
        return rules_mod.save(conn(), pack, body.model_dump(), None, as_of(pack), HORIZON)
    except rules_mod.RuleError as e:
        _rule_errors(e)


@app.put("/api/{pack}/rules/{rule_id}")
async def update_rule(pack: str, rule_id: str, body: RuleBody):
    try:
        return rules_mod.save(conn(), pack, body.model_dump(), rule_id, as_of(pack), HORIZON)
    except rules_mod.RuleError as e:
        _rule_errors(e)


@app.delete("/api/{pack}/rules/{rule_id}")
async def delete_rule(pack: str, rule_id: str):
    as_of(pack)
    try:
        rules_mod.delete(conn(), pack, rule_id)
    except rules_mod.RuleError as e:
        _rule_errors(e)
    return {"deleted": rule_id}


@app.post("/api/{pack}/reset")
async def reset_pack(pack: str):
    """Restore this scenario's rules, people, sessions, and plans to the original synthetic data."""
    as_of(pack)
    seed_pack(conn(), pack, date.today())
    _runs.clear()          # cached plans; the database record of other scenarios' runs is untouched
    return {"reset": pack}


# ---------------------------------------------------------------- optional AI layer (see ai.py)

class TextBody(BaseModel):
    text: str


class WhatIfText(BaseModel):
    text: str
    run_id: int


class AskBody(BaseModel):
    question: str
    run_id: int


def _ai_call(fn, *a):
    try:
        return fn(*a)
    except ai_mod.AIBudgetError as e:
        raise HTTPException(429, [str(e)])
    except ai_mod.AIFailure as e:
        raise HTTPException(422, [str(e)])


@app.get("/api/ai/status")
async def ai_status():
    return ai_mod.status()


@app.post("/api/{pack}/ai/rules")
async def ai_rules(pack: str, body: TextBody):
    d = as_of(pack)
    return _ai_call(ai_mod.draft_rules, conn(), pack, body.text, d, HORIZON)


@app.post("/api/{pack}/ai/what-if")
async def ai_what_if(pack: str, body: WhatIfText):
    run = _get_run(body.run_id)
    names = {g["group_id"]: g["name"] for g in run["capacity"]["groups"]}
    commitments = [{"id": c["id"], "group": names[c["group_id"]], "name": c["name"], "start": c["start"], "end": c["end"]}
                   for c in run["capacity"]["commitments"]]
    return _ai_call(ai_mod.parse_what_if, conn(), pack, body.text, commitments)


@app.post("/api/{pack}/ai/ask")
async def ai_ask(pack: str, body: AskBody):
    as_of(pack)
    return _ai_call(ai_mod.ask, body.question, _get_run(body.run_id))


@app.get("/api/schedule/{run_id}")
async def get_run(run_id: int):
    return _get_run(run_id)


class StatusBody(BaseModel):
    status: str


@app.post("/api/schedule/{run_id}/status")
async def set_status(run_id: int, body: StatusBody):
    if body.status not in ("approved", "rejected", "proposed"):
        raise HTTPException(400, "status must be approved, rejected, or proposed")
    _get_run(run_id)
    set_run_status(conn(), run_id, body.status)
    _runs[run_id]["run_status"] = body.status
    return {"run_id": run_id, "run_status": body.status}


DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    async def spa(path: str):
        f = DIST / path
        return FileResponse(f if path and f.is_file() else DIST / "index.html")
