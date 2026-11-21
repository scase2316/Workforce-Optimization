"""Synthetic data generator. Deterministic for a given (pack, as_of, seed).

All names are randomly combined from generic lists. No real people or data.
Usage:  python -m app.seed --db demo.db --pack all
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
from datetime import date, timedelta
from typing import Optional

from . import db
from .packs import list_pack_ids, load_pack

FIRST = ["Marcus", "Elena", "Jordan", "Priya", "Tyrell", "Hannah", "Diego", "Mei", "Caleb", "Amara",
         "Nolan", "Sofia", "Isaiah", "Grace", "Mateo", "Lena", "Owen", "Naomi", "Dante", "Ruth",
         "Felix", "Tessa", "Andre", "Clara", "Gabriel", "Imani", "Silas", "Wren", "Malik", "June",
         "Rafael", "Piper", "Jamal", "Alina", "Theo", "Camila", "Eli", "Vera", "Cruz", "Nia"]
LAST = ["Hale", "Okafor", "Brandt", "Nakamura", "Reyes", "Lindqvist", "Bishop", "Moreau", "Tran", "Sutton",
        "Calloway", "Ferrer", "Whitlock", "Abara", "Kowalski", "Delgado", "Ashford", "Park", "Mercer", "Quinn",
        "Bellamy", "Ortega", "Stroud", "Yamada", "Pruitt", "Navarro", "Gallagher", "Osei", "Lockhart", "Vega",
        "Thorne", "Castillo", "Rowe", "Adeyemi", "Fitch", "Marlow", "Sandoval", "Keane", "Doyle", "Zhou"]


def clear_pack(conn: sqlite3.Connection, pack_id: str) -> None:
    q = conn.execute
    q("DELETE FROM assignment WHERE run_id IN (SELECT id FROM schedule_run WHERE pack_id = ?)", (pack_id,))
    q("DELETE FROM schedule_run WHERE pack_id = ?", (pack_id,))
    q("DELETE FROM completion WHERE person_id IN (SELECT id FROM person WHERE pack_id = ?)", (pack_id,))
    q("DELETE FROM event_trigger WHERE person_id IN (SELECT id FROM person WHERE pack_id = ?)", (pack_id,))
    for t in ("commitment", "offering", "person"):
        q(f"DELETE FROM {t} WHERE pack_id = ?", (pack_id,))
    q("DELETE FROM grp WHERE pack_id = ?", (pack_id,))
    q("DELETE FROM requirement WHERE pack_id = ?", (pack_id,))
    q("DELETE FROM pack WHERE id = ?", (pack_id,))


def _weighted(rng: random.Random, weights: dict[str, float]) -> str:
    return rng.choices(list(weights), weights=list(weights.values()))[0]


def _split(total: int, weights: list[float]) -> list[int]:
    s = sum(weights)
    sizes = [int(total * w / s) for w in weights]
    for i in range(total - sum(sizes)):
        sizes[i % len(sizes)] += 1
    return sizes


def seed_pack(conn: sqlite3.Connection, pack_id: str, as_of: date,
              seed: int = 42, people: Optional[int] = None) -> dict:
    pack = load_pack(pack_id)
    sc, reqs = pack["scenario"], pack["rules"]["requirements"]
    rng = random.Random(f"{pack_id}:{seed}")
    clear_pack(conn, pack_id)
    iso = lambda d: d.isoformat()

    conn.execute("INSERT INTO pack VALUES (?,?,?)",
                 (pack_id, pack["vocabulary"]["name"], json.dumps(pack["vocabulary"])))
    for r in reqs:
        conn.execute("INSERT INTO requirement VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (r["id"], pack_id, r["name"], r["trigger_type"], json.dumps(r["applies_to"]),
                      r["deadline_days"], json.dumps(r["prerequisites"]), r["valid_days"],
                      r["slots_needed"], r["duration_days"]))
    req_by_id = {r["id"]: r for r in reqs}

    # Groups and people
    total = people or sc["people"]
    sizes = _split(total, [g["weight"] for g in sc["groups"]])
    group_ids: dict[str, int] = {}
    group_people: dict[int, list[int]] = {}
    used_names: set[str] = set()
    lo, hi = sc["tenure_days"]
    person_rows = []
    for g, size in zip(sc["groups"], sizes):
        cur = conn.execute("INSERT INTO grp (pack_id,name,parent_id,min_available) VALUES (?,?,?,?)",
                           (pack_id, g["name"], None, math.ceil(size * g["min_available_pct"])))
        gid = cur.lastrowid
        group_ids[g["name"]] = gid
        group_people[gid] = []
        roles = g.get("roles", sc["default_roles"])
        for _ in range(size):
            while True:
                name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
                if name not in used_names:
                    used_names.add(name)
                    break
                if len(used_names) >= len(FIRST) * len(LAST) - 1:
                    name = f"{name} {len(used_names)}"
                    break
            role = _weighted(rng, roles)
            start = as_of - timedelta(days=rng.randint(lo, hi))
            cur = conn.execute(
                "INSERT INTO person (pack_id,group_id,name,role,start_date,attributes) VALUES (?,?,?,?,?,?)",
                (pack_id, gid, name, role, iso(start), "{}"))
            pid = cur.lastrowid
            group_people[gid].append(pid)
            person_rows.append((pid, role, start))

    # Event triggers
    triggers: dict[int, dict[str, date]] = {}
    for pid, role, start in person_rows:
        ev: dict[str, date] = {}
        trigger_types = {r["trigger_type"] for r in reqs}
        if "hire" in trigger_types:
            ev["hire"] = start
            conn.execute("INSERT INTO event_trigger (person_id,type,date) VALUES (?,?,?)", (pid, "hire", iso(start)))
        if "promotion" in trigger_types:
            if "hire" in ev:
                # Hire-based pack: only managers have a promotion, somewhere after hire.
                if role == "Manager":
                    pdate = start + timedelta(days=rng.randint(0, max(0, (as_of - start).days)))
                    ev["promotion"] = pdate
            else:
                ev["promotion"] = start      # role start == promotion date
            if "promotion" in ev:
                conn.execute("INSERT INTO event_trigger (person_id,type,date) VALUES (?,?,?)",
                             (pid, "promotion", iso(ev["promotion"])))
        triggers[pid] = ev

    # Completions
    def applies(req: dict, role: str, start: date, ev: dict[str, date]) -> Optional[date]:
        roles = req["applies_to"].get("role")
        if roles and role not in roles:
            return None
        if req["trigger_type"] == "standing":
            return start
        return ev.get(req["trigger_type"])

    n_comp = 0
    for pid, role, start in person_rows:
        ev = triggers[pid]
        applicable = {r["id"]: applies(r, role, start, ev) for r in reqs}
        applicable = {k: v for k, v in applicable.items() if v is not None}
        done: dict[str, date] = {}

        def add(req_id: str, completed: date) -> None:
            nonlocal n_comp
            r = req_by_id[req_id]
            exp = completed + timedelta(days=r["valid_days"]) if r["valid_days"] else None
            conn.execute("INSERT INTO completion (person_id,requirement_id,completed_on,expires_on) VALUES (?,?,?,?)",
                         (pid, req_id, iso(completed), iso(exp) if exp else None))
            done[req_id] = completed
            n_comp += 1

        def history(req_id: str, before: date) -> None:
            """Prerequisite that no longer 'applies' (e.g. Corporals Course for a Sergeant)."""
            if req_id in done or req_id in applicable:
                return
            when = before - timedelta(days=rng.randint(60, 700))
            for p in req_by_id[req_id]["prerequisites"]:
                history(p, when)
            if rng.random() < 0.97:
                add(req_id, when)

        for r in reqs:
            if r["id"] not in applicable:
                continue
            trig = applicable[r["id"]]
            for p in r["prerequisites"]:
                history(p, trig)
        for r in reqs:                      # rules.json lists prerequisites first
            rid = r["id"]
            if rid not in applicable:
                continue
            trig = applicable[rid]
            if any(p not in done for p in r["prerequisites"]):
                continue                    # blocked: prerequisite not completed
            earliest = max([trig] + [done[p] for p in r["prerequisites"]])
            if earliest > as_of:
                continue
            if r["valid_days"] is None:
                due = trig + timedelta(days=r["deadline_days"])
                if rng.random() < (0.85 if as_of > due else 0.35):
                    span = (as_of - earliest).days
                    add(rid, earliest + timedelta(days=rng.randint(0, span)))
            elif rng.random() < 0.92:
                completed = max(earliest, as_of - timedelta(days=rng.randint(0, r["valid_days"] + 120)))
                add(rid, completed)

    # Offerings
    horizon = as_of + timedelta(days=sc["horizon_days"])
    n_off = 0
    for t in sc["offerings"]:
        dur = req_by_id[t["requirement_id"]]["duration_days"]
        start = as_of + timedelta(days=t["first_offset_days"])
        while start <= horizon:
            conn.execute("INSERT INTO offering (pack_id,requirement_id,start,end,seats,location) VALUES (?,?,?,?,?,?)",
                         (pack_id, t["requirement_id"], iso(start), iso(start + timedelta(days=dur - 1)),
                          t["seats"], t["location"]))
            n_off += 1
            start += timedelta(days=t["every_days"])

    # Commitments
    n_com = 0
    for t in sc["commitments"]:
        targets = list(group_ids) if t["group"] == "*" else [t["group"]]
        for gname in targets:
            gid = group_ids[gname]
            members = group_people[gid]
            if t["subset_pct"]:
                chosen = sorted(rng.sample(members, max(1, int(len(members) * t["subset_pct"]))))
                ppl = json.dumps(chosen)
            else:
                ppl = None
            s = as_of + timedelta(days=t["offset_days"])
            conn.execute("INSERT INTO commitment (pack_id,group_id,type,name,start,end,people) VALUES (?,?,?,?,?,?,?)",
                         (pack_id, gid, t["type"], t["name"], iso(s), iso(s + timedelta(days=t["duration_days"] - 1)), ppl))
            n_com += 1

    conn.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (f"as_of:{pack_id}", as_of.isoformat()))
    conn.commit()
    return {"pack": pack_id, "people": len(person_rows), "groups": len(group_ids),
            "completions": n_comp, "offerings": n_off, "commitments": n_com}


def main() -> None:
    ap = argparse.ArgumentParser(description="Seed synthetic demo data")
    ap.add_argument("--db", default="demo.db")
    ap.add_argument("--pack", default="all", help="pack id or 'all'")
    ap.add_argument("--as-of", default=date.today().isoformat())
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    conn = db.connect(args.db)
    for pid in (list_pack_ids() if args.pack == "all" else [args.pack]):
        print(seed_pack(conn, pid, date.fromisoformat(args.as_of), args.seed))


if __name__ == "__main__":
    main()
