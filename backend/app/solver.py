"""Schedule optimizer (OR-Tools CP-SAT).

Chooses, for every outstanding requirement item, at most one offering per
person so that readiness gained is maximized subject to:

  * offering seat quotas
  * no overlap with the person's commitments (exercise, deployment, leave, ...)
  * a person can't be in two offerings on the same day
  * prerequisite ordering (a prerequisite session must END before the next starts)
  * per-group minimum availability on every day (commitments + training absences)
  * expiring items must be renewed before they lapse

The LLM never produces schedules; it only edits `overrides` (what-if) and calls
`solve`. Every assignment carries a rationale built from solver data.

Overrides (all optional) never touch the database:
  shift_commitments  {commitment_id: days}
  remove_commitments [commitment_id]
  add_commitments    [{group_id, name, type, start, end, people?}]
  seats              {offering_id: seats}
  cancel_offerings   [offering_id]
  min_available      {group_id: n}
"""
from __future__ import annotations

import json
import sqlite3
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from ortools.sat.python import cp_model

from .readiness import person_readiness

BASE_WEIGHT = {"overdue": 1000, "gap": 700, "expiring": 300}
START_PENALTY = 2        # per day until the session starts (prefer sooner)
LATE_PENALTY = 5         # per day after the deadline, capped at LATE_CAP days
LATE_CAP = 60
STICKY_BONUS = 25        # keep an assignment from a prior run (stable what-if diffs)


@dataclass
class Item:
    pid: int
    req_id: str
    status: str
    due: Optional[int]                     # ordinal
    prereqs: list[str]                     # unsatisfied prerequisites


@dataclass
class Commitment:
    id: int
    gid: int
    type: str
    name: str
    start: int
    end: int
    people: Optional[set[int]]             # None = whole group


@dataclass
class Offering:
    id: int
    req_id: str
    start: int
    end: int
    seats: int
    location: str


@dataclass
class Problem:
    pack_id: str
    as_of: date
    people: dict[int, dict]                # pid -> {gid, name, role}
    groups: dict[int, dict]                # gid -> {name, min_available, size}
    offerings: dict[int, Offering]
    commitments: list[Commitment]
    items: list[Item]
    req_names: dict[str, str]
    overrides: dict = field(default_factory=dict)
    current_ready: dict[int, tuple[int, int]] = field(default_factory=dict)   # pid -> (ready, applicable)

    def person_busy(self, pid: int) -> list[Commitment]:
        gid = self.people[pid]["gid"]
        return [c for c in self.commitments
                if c.gid == gid and (c.people is None or pid in c.people)]


def _o(s: str) -> int:
    return date.fromisoformat(s).toordinal()


def load_problem(conn: sqlite3.Connection, pack_id: str, as_of: date,
                 overrides: Optional[dict] = None) -> Problem:
    ov = overrides or {}
    people = {r["id"]: {"gid": r["group_id"], "name": r["name"], "role": r["role"]}
              for r in conn.execute("SELECT * FROM person WHERE pack_id = ?", (pack_id,))}
    sizes: dict[int, int] = defaultdict(int)
    for p in people.values():
        sizes[p["gid"]] += 1
    groups = {}
    for g in conn.execute("SELECT * FROM grp WHERE pack_id = ?", (pack_id,)):
        mn = ov.get("min_available", {}).get(g["id"], ov.get("min_available", {}).get(str(g["id"]), g["min_available"]))
        groups[g["id"]] = {"name": g["name"], "min_available": mn, "size": sizes[g["id"]]}

    cancelled = set(ov.get("cancel_offerings", []))
    seats_ov = {int(k): v for k, v in ov.get("seats", {}).items()}
    offerings = {}
    for r in conn.execute("SELECT * FROM offering WHERE pack_id = ?", (pack_id,)):
        if r["id"] in cancelled:
            continue
        offerings[r["id"]] = Offering(r["id"], r["requirement_id"], _o(r["start"]), _o(r["end"]),
                                      seats_ov.get(r["id"], r["seats"]), r["location"])

    shift = {int(k): v for k, v in ov.get("shift_commitments", {}).items()}
    removed = set(ov.get("remove_commitments", []))
    commitments = []
    for r in conn.execute("SELECT * FROM commitment WHERE pack_id = ?", (pack_id,)):
        if r["id"] in removed:
            continue
        d = shift.get(r["id"], 0)
        commitments.append(Commitment(r["id"], r["group_id"], r["type"], r["name"],
                                      _o(r["start"]) + d, _o(r["end"]) + d,
                                      set(json.loads(r["people"])) if r["people"] else None))
    for i, a in enumerate(ov.get("add_commitments", [])):
        commitments.append(Commitment(-(i + 1), a["group_id"], a.get("type", "exercise"), a["name"],
                                      _o(a["start"]), _o(a["end"]),
                                      set(a["people"]) if a.get("people") else None))

    req_names = {r["id"]: r["name"] for r in conn.execute("SELECT id,name FROM requirement WHERE pack_id = ?", (pack_id,))}
    items, current_ready = [], {}
    for pid in people:
        pr = person_readiness(conn, pid, as_of)
        current_ready[pid] = (pr.ready_count, pr.applicable)
        for it in pr.items:
            if it.status == "complete":
                continue
            items.append(Item(pid, it.requirement_id, it.status,
                              it.due.toordinal() if it.due else None, list(it.blocked_by)))
    return Problem(pack_id, as_of, people, groups, offerings, commitments, items, req_names, ov, current_ready)


def _overlap(a0: int, a1: int, b0: int, b1: int) -> bool:
    return a0 <= b1 and b0 <= a1


def solve(problem: Problem, time_limit: float = 20.0, prior: Optional[list[dict]] = None,
          workers: int = 8) -> dict:
    t0 = time.time()
    P = problem
    asof = P.as_of.toordinal()
    prior_keys = {(a["person_id"], a["requirement_id"], a["offering_id"]) for a in (prior or [])}
    by_req: dict[str, list[Offering]] = defaultdict(list)
    for o in P.offerings.values():
        by_req[o.req_id].append(o)
    busy = {pid: P.person_busy(pid) for pid in P.people}
    item_key = {(it.pid, it.req_id): it for it in P.items}

    m = cp_model.CpModel()
    x: dict[tuple[int, str, int], cp_model.IntVar] = {}
    value: dict[tuple[int, str, int], int] = {}
    unscheduled_reason: dict[tuple[int, str], str] = {}
    candidate_counts: dict[tuple[int, str], int] = {}

    for it in P.items:
        cands = []
        for o in by_req.get(it.req_id, []):
            if o.start <= asof:
                continue
            if it.status == "expiring" and it.due is not None and o.end > it.due:
                continue                                     # must renew before it lapses
            cands.append(o)
        candidate_counts[(it.pid, it.req_id)] = len(cands)
        if not by_req.get(it.req_id):
            unscheduled_reason[(it.pid, it.req_id)] = "No offering of this requirement exists in the planning window."
            continue
        missing = [q for q in it.prereqs if (it.pid, q) not in item_key]
        if missing:
            unscheduled_reason[(it.pid, it.req_id)] = (
                f"Prerequisite '{P.req_names.get(missing[0], missing[0])}' is not complete and cannot be scheduled.")
            continue
        usable = [o for o in cands if not any(_overlap(o.start, o.end, c.start, c.end) for c in busy[it.pid])]
        if not usable:
            unscheduled_reason[(it.pid, it.req_id)] = (
                "Every available session conflicts with this person's commitments." if cands
                else ("This lapses before the next session starts. Add an earlier session or accept a short lapse."
                      if it.status == "expiring" else "No session of this requirement is left before the planning window ends."))
            continue
        for o in usable:
            k = (it.pid, it.req_id, o.id)
            x[k] = m.NewBoolVar(f"x_{it.pid}_{it.req_id}_{o.id}")
            late = 0
            if it.status != "expiring" and it.due is not None:
                late = min(max(0, o.end - it.due), LATE_CAP)
            value[k] = (BASE_WEIGHT[it.status] - START_PENALTY * (o.start - asof) - LATE_PENALTY * late
                        + (STICKY_BONUS if k in prior_keys else 0))

    # at most one offering per (person, requirement)
    per_item: dict[tuple[int, str], list] = defaultdict(list)
    per_off: dict[int, list] = defaultdict(list)
    per_person_day: dict[tuple[int, int], list] = defaultdict(list)
    per_group_day: dict[tuple[int, int], list] = defaultdict(list)
    for (pid, rid, oid), v in x.items():
        o = P.offerings[oid]
        per_item[(pid, rid)].append(v)
        per_off[oid].append(v)
        gid = P.people[pid]["gid"]
        for d in range(o.start, o.end + 1):
            per_person_day[(pid, d)].append(v)
            per_group_day[(gid, d)].append(v)
    for vs in per_item.values():
        m.Add(sum(vs) <= 1)
    for oid, vs in per_off.items():
        m.Add(sum(vs) <= P.offerings[oid].seats)
    for vs in per_person_day.values():
        if len(vs) > 1:
            m.Add(sum(vs) <= 1)

    # minimum availability per group per day
    unavailable: dict[tuple[int, int], set[int]] = defaultdict(set)
    for c in P.commitments:
        members = [p for p, info in P.people.items() if info["gid"] == c.gid and (c.people is None or p in c.people)]
        for d in range(c.start, c.end + 1):
            unavailable[(c.gid, d)].update(members)
    for (gid, d), vs in per_group_day.items():
        cap = max(0, P.groups[gid]["size"] - len(unavailable.get((gid, d), ())) - P.groups[gid]["min_available"])
        if len(vs) > cap:
            m.Add(sum(vs) <= cap)

    # prerequisite ordering: the prerequisite session must end before this one starts
    for (pid, rid, oid), v in x.items():
        it = item_key[(pid, rid)]
        o = P.offerings[oid]
        for q in it.prereqs:
            before = [x[(pid, q, o2.id)] for o2 in by_req[q] if (pid, q, o2.id) in x and o2.end < o.start]
            if before:
                m.Add(v <= sum(before))
            else:
                m.Add(v == 0)

    m.Maximize(sum(value[k] * v for k, v in x.items()))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = workers
    solver.parameters.random_seed = 7
    solver.parameters.relative_gap_limit = 0.0   # exact: solves take well under a second here, and stable diffs depend on it
    status = solver.Solve(m)
    status_name = solver.StatusName(status)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {"status": status_name, "assignments": [], "unscheduled": [], "objective": 0}

    chosen = {k for k, v in x.items() if solver.Value(v)}
    load: dict[int, int] = defaultdict(int)
    for (_, _, oid) in chosen:
        load[oid] += 1

    def to_date(n: int) -> str:
        return date.fromordinal(n).isoformat()

    assignments = []
    for (pid, rid, oid) in sorted(chosen):
        it, o = item_key[(pid, rid)], P.offerings[oid]
        earlier = []
        for o2 in sorted(by_req[rid], key=lambda z: z.start):
            if o2.start >= o.start:
                break
            if o2.start <= asof or (it.status == "expiring" and it.due and o2.end > it.due):
                continue
            clash = next((c for c in busy[pid] if _overlap(o2.start, o2.end, c.start, c.end)), None)
            if clash:
                why = f"conflicts with {clash.name}"
            elif load[o2.id] >= o2.seats:
                why = "session is full"
            elif it.prereqs and not any(o3.end < o2.start and (pid, q, o3.id) in chosen
                                        for q in it.prereqs for o3 in by_req[q]):
                why = "prerequisite not yet complete"
            else:
                why = "capacity used elsewhere (manning minimum or seat trade-off)"
            earlier.append({"offering_id": o2.id, "start": to_date(o2.start), "reason": why})
        assignments.append({
            "person_id": pid, "person": P.people[pid]["name"], "group_id": P.people[pid]["gid"],
            "requirement_id": rid, "requirement": P.req_names.get(rid, rid), "offering_id": oid,
            "start": to_date(o.start), "end": to_date(o.end), "location": o.location,
            "rationale": {
                "status": it.status, "due": to_date(it.due) if it.due else None,
                "days_until_start": o.start - asof,
                "meets_deadline": (o.end <= it.due) if it.due else True,
                "days_after_deadline": max(0, o.end - it.due) if it.due else 0,
                "earlier_options": earlier[:3],
            },
        })

    unscheduled = []
    for it in P.items:
        if (it.pid, it.req_id) in {(a["person_id"], a["requirement_id"]) for a in assignments}:
            continue
        reason = unscheduled_reason.get((it.pid, it.req_id)) or (
            "Capacity limits (seats or group manning minimum) left no feasible slot.")
        unscheduled.append({"person_id": it.pid, "person": P.people[it.pid]["name"],
                            "requirement_id": it.req_id, "requirement": P.req_names.get(it.req_id, it.req_id),
                            "status": it.status, "reason": reason})

    # Projected readiness if every assigned session is completed
    added = defaultdict(int)
    for a in assignments:
        if a["rationale"]["status"] != "expiring":      # renewals keep a person ready; they don't add readiness
            added[a["person_id"]] += 1
    grp_before, grp_after = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    for pid, (rdy, app) in P.current_ready.items():
        gid = P.people[pid]["gid"]
        grp_before[gid][0] += rdy; grp_before[gid][1] += app
        grp_after[gid][0] += rdy + added[pid]; grp_after[gid][1] += app
    pct = lambda a: round(100.0 * a[0] / a[1], 1) if a[1] else 100.0
    tot_b = [sum(v[0] for v in grp_before.values()), sum(v[1] for v in grp_before.values())]
    tot_a = [sum(v[0] for v in grp_after.values()), sum(v[1] for v in grp_after.values())]

    # Manning after scheduled training
    trained: dict[tuple[int, int], int] = defaultdict(int)
    for (pid, rid, oid) in chosen:
        o = P.offerings[oid]
        for d in range(o.start, o.end + 1):
            trained[(P.people[pid]["gid"], d)] += 1
    manning = []
    horizon_days = sorted({d for (_, d) in list(unavailable) + list(trained)})
    for gid, g in P.groups.items():
        worst = None
        for d in horizon_days:
            avail = g["size"] - len(unavailable.get((gid, d), ())) - trained.get((gid, d), 0)
            if worst is None or avail < worst[0]:
                worst = (avail, d)
        manning.append({"group_id": gid, "group": g["name"], "min_available": g["min_available"],
                        "lowest_available": worst[0] if worst else g["size"],
                        "on": to_date(worst[1]) if worst else None,
                        "breached_by_commitments_alone": any(
                            g["size"] - len(unavailable.get((gid, d), ())) < g["min_available"] for d in horizon_days
                            if (gid, d) in unavailable)})

    return {
        "status": status_name, "optimal": status == cp_model.OPTIMAL,
        "objective": int(solver.ObjectiveValue()), "runtime_s": round(time.time() - t0, 2),
        "assignments": assignments, "unscheduled": unscheduled,
        "summary": {
            "items_outstanding": len(P.items), "scheduled": len(assignments), "unscheduled": len(unscheduled),
            "overdue_cleared": sum(1 for a in assignments if a["rationale"]["status"] == "overdue"),
            "on_time": sum(1 for a in assignments if a["rationale"]["status"] != "overdue" and a["rationale"]["meets_deadline"]),
            "readiness_before_pct": pct(tot_b), "readiness_after_pct": pct(tot_a),
            "by_group": [{"group_id": gid, "group": P.groups[gid]["name"],
                          "before_pct": pct(grp_before[gid]), "after_pct": pct(grp_after[gid])} for gid in P.groups],
        },
        "manning": manning,
        "constraints_snapshot": {"as_of": P.as_of.isoformat(), "overrides": P.overrides},
    }


def validate(problem: Problem, assignments: list[dict]) -> list[str]:
    """Independent check of a schedule against every hard constraint. Returns violations."""
    P, bad = problem, []
    asof = P.as_of.toordinal()
    seats = defaultdict(int)
    per_person_days: dict[tuple[int, int], int] = defaultdict(int)
    trained: dict[tuple[int, int], int] = defaultdict(int)
    done: dict[tuple[int, str], int] = {}
    seen = set()
    for a in assignments:
        pid, rid, oid = a["person_id"], a["requirement_id"], a["offering_id"]
        o = P.offerings[oid]
        if (pid, rid) in seen:
            bad.append(f"duplicate item {pid}/{rid}")
        seen.add((pid, rid))
        seats[oid] += 1
        done[(pid, rid)] = o.end
        if o.start <= asof:
            bad.append(f"offering {oid} not in the future")
        for c in P.person_busy(pid):
            if _overlap(o.start, o.end, c.start, c.end):
                bad.append(f"person {pid} double-booked with commitment {c.name}")
        for d in range(o.start, o.end + 1):
            per_person_days[(pid, d)] += 1
            trained[(P.people[pid]["gid"], d)] += 1
    for oid, n in seats.items():
        if n > P.offerings[oid].seats:
            bad.append(f"offering {oid} over capacity")
    for (pid, d), n in per_person_days.items():
        if n > 1:
            bad.append(f"person {pid} in two sessions on day {d}")
    item_key = {(it.pid, it.req_id): it for it in P.items}
    for a in assignments:
        it = item_key[(a["person_id"], a["requirement_id"])]
        start = P.offerings[a["offering_id"]].start
        for q in it.prereqs:
            if done.get((a["person_id"], q), 10**9) >= start:
                bad.append(f"prerequisite {q} not finished before {a['requirement_id']} for person {a['person_id']}")
    unavailable: dict[tuple[int, int], set[int]] = defaultdict(set)
    for c in P.commitments:
        for p, info in P.people.items():
            if info["gid"] == c.gid and (c.people is None or p in c.people):
                for d in range(c.start, c.end + 1):
                    unavailable[(c.gid, d)].add(p)
    for (gid, d), n in trained.items():
        base_margin = P.groups[gid]["size"] - len(unavailable.get((gid, d), ())) - P.groups[gid]["min_available"]
        if n > max(0, base_margin):
            bad.append(f"group {gid} below minimum availability on day {d}")
    return bad


def save_run(conn: sqlite3.Connection, pack_id: str, result: dict, status: str = "proposed") -> int:
    cur = conn.execute(
        "INSERT INTO schedule_run (pack_id,created_at,status,constraints_snapshot,score) VALUES (?,?,?,?,?)",
        (pack_id, datetime.now(timezone.utc).isoformat(), status,
         json.dumps(result["constraints_snapshot"]), result["objective"]))
    run_id = cur.lastrowid
    for a in result["assignments"]:
        conn.execute("INSERT INTO assignment (run_id,person_id,offering_id,rationale) VALUES (?,?,?,?)",
                     (run_id, a["person_id"], a["offering_id"], json.dumps(a["rationale"])))
    conn.commit()
    return run_id


def set_run_status(conn: sqlite3.Connection, run_id: int, status: str) -> None:
    if status not in ("proposed", "approved", "rejected"):
        raise ValueError(status)
    conn.execute("UPDATE schedule_run SET status = ? WHERE id = ?", (status, run_id))
    conn.commit()


def diff_schedules(before: list[dict], after: list[dict]) -> dict:
    key = lambda a: (a["person_id"], a["requirement_id"])
    b, a_ = {key(x): x for x in before}, {key(x): x for x in after}
    moved = [{"person": a_[k]["person"], "requirement": a_[k]["requirement"],
              "from": b[k]["start"], "to": a_[k]["start"]}
             for k in b if k in a_ and b[k]["offering_id"] != a_[k]["offering_id"]]
    return {
        "added": [a_[k] for k in a_ if k not in b],
        "removed": [b[k] for k in b if k not in a_],
        "moved": moved,
        "unchanged": sum(1 for k in b if k in a_ and b[k]["offering_id"] == a_[k]["offering_id"]),
    }


def availability(problem: Problem, assignments: list[dict], horizon_days: int = 180) -> dict[int, dict]:
    """Per-group daily head-count series (index 0 = as_of): `base` after commitments only,
    `planned` after commitments and the scheduled training."""
    P = problem
    asof = P.as_of.toordinal()
    out = {}
    for gid, g in P.groups.items():
        away = [set() for _ in range(horizon_days + 1)]
        for c in P.commitments:
            if c.gid != gid:
                continue
            members = [p for p, info in P.people.items() if info["gid"] == gid and (c.people is None or p in c.people)]
            for d in range(max(c.start, asof), min(c.end, asof + horizon_days) + 1):
                away[d - asof].update(members)
        base = [g["size"] - len(a) for a in away]
        trained = [0] * (horizon_days + 1)
        for a in assignments:
            if a["group_id"] != gid:
                continue
            o = P.offerings[a["offering_id"]]
            for d in range(max(o.start, asof), min(o.end, asof + horizon_days) + 1):
                trained[d - asof] += 1
        out[gid] = {"base": base, "planned": [b - t for b, t in zip(base, trained)]}
    return out
