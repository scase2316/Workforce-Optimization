import json
from datetime import date, timedelta

import pytest

from app import db
from app.packs import list_pack_ids
from app.seed import seed_pack
from app.solver import (load_problem, solve, validate, save_run, set_run_status, diff_schedules)

AS_OF = date(2026, 11, 21)
iso = lambda n: (AS_OF + timedelta(days=n)).isoformat()


# ---------- hand-built scenarios: each isolates one constraint ----------

@pytest.fixture
def conn():
    c = db.connect()
    c.execute("INSERT INTO pack VALUES ('t','Test','{}')")
    c.execute("INSERT INTO grp (id,pack_id,name,min_available) VALUES (1,'t','G1',0)")
    return c


def req(c, rid, valid=365, prereqs=(), trigger="standing", applies=None):
    c.execute("INSERT INTO requirement VALUES (?,?,?,?,?,?,?,?,?,?)",
              (rid, "t", rid, trigger, json.dumps(applies or {}), 365, json.dumps(list(prereqs)), valid, 1, 1))


def people(c, n, start="2025-01-01"):
    for i in range(1, n + 1):
        c.execute("INSERT INTO person (id,pack_id,group_id,name,role,start_date) VALUES (?,?,?,?,?,?)",
                  (i, "t", 1, f"P{i}", "X", start))


def offer(c, rid, day, seats=10, length=1):
    cur = c.execute("INSERT INTO offering (pack_id,requirement_id,start,end,seats) VALUES ('t',?,?,?,?)",
                    (rid, iso(day), iso(day + length - 1), seats))
    return cur.lastrowid


def run(c):
    P = load_problem(c, "t", AS_OF)
    r = solve(P, time_limit=10)
    assert validate(P, r["assignments"]) == []
    return P, r


def test_manning_minimum_limits_concurrent_absences(conn):
    people(conn, 4); req(conn, "annual")
    conn.execute("UPDATE grp SET min_available = 3")          # at most 1 of 4 away at once
    for d in (5, 10, 15, 20):
        offer(conn, "annual", d, seats=4)
    _, r = run(conn)
    per_day = {}
    for a in r["assignments"]:
        per_day[a["start"]] = per_day.get(a["start"], 0) + 1
    assert len(r["assignments"]) == 4 and max(per_day.values()) == 1


def test_manning_disabled_lets_everyone_train_together(conn):
    people(conn, 4); req(conn, "annual")
    for d in (5, 10):
        offer(conn, "annual", d, seats=4)
    _, r = run(conn)
    assert {a["start"] for a in r["assignments"]} == {iso(5)}   # sooner is preferred


def test_seat_quota_spills_to_next_session(conn):
    people(conn, 5); req(conn, "annual")
    offer(conn, "annual", 5, seats=3); offer(conn, "annual", 12, seats=3)
    _, r = run(conn)
    counts = sorted(sum(1 for a in r["assignments"] if a["start"] == iso(d)) for d in (5, 12))
    assert counts == [2, 3]


def test_commitment_blocks_conflicting_session(conn):
    people(conn, 1); req(conn, "annual")
    conn.execute("INSERT INTO commitment (pack_id,group_id,type,name,start,end,people) VALUES ('t',1,'exercise','Field Ex',?,?,NULL)",
                 (iso(3), iso(8)))
    offer(conn, "annual", 5); offer(conn, "annual", 15)
    _, r = run(conn)
    assert r["assignments"][0]["start"] == iso(15)
    assert any(e["reason"] == "conflicts with Field Ex" for e in r["assignments"][0]["rationale"]["earlier_options"])


def test_unschedulable_item_reports_reason(conn):
    people(conn, 1); req(conn, "annual")
    conn.execute("INSERT INTO commitment (pack_id,group_id,type,name,start,end,people) VALUES ('t',1,'deployment','Deploy',?,?,NULL)",
                 (iso(1), iso(30)))
    offer(conn, "annual", 5)
    _, r = run(conn)
    assert r["assignments"] == [] and "conflicts" in r["unscheduled"][0]["reason"]


def test_prerequisite_must_finish_before_next_starts(conn):
    people(conn, 1); req(conn, "a", valid=None); req(conn, "b", valid=None, prereqs=["a"])
    offer(conn, "a", 10); offer(conn, "b", 5); offer(conn, "b", 20)
    _, r = run(conn)
    by = {a["requirement_id"]: a["start"] for a in r["assignments"]}
    assert by == {"a": iso(10), "b": iso(20)}


def test_prerequisite_with_no_session_blocks_dependent(conn):
    people(conn, 1); req(conn, "a", valid=None); req(conn, "b", valid=None, prereqs=["a"])
    offer(conn, "b", 20)
    _, r = run(conn)
    assert r["assignments"] == []


def test_no_double_booking_same_day(conn):
    people(conn, 1); req(conn, "x"); req(conn, "y")
    offer(conn, "x", 5); offer(conn, "y", 5); offer(conn, "y", 9)
    _, r = run(conn)
    days = [a["start"] for a in r["assignments"]]
    assert len(days) == 2 and len(set(days)) == 2


def test_expiring_item_renewed_before_lapse_only(conn):
    people(conn, 1); req(conn, "annual")
    conn.execute("INSERT INTO completion (person_id,requirement_id,completed_on,expires_on) VALUES (1,'annual',?,?)",
                 (iso(-340), iso(25)))                              # 25 days left -> expiring
    offer(conn, "annual", 40); offer(conn, "annual", 10)
    _, r = run(conn)
    assert [a["start"] for a in r["assignments"]] == [iso(10)]


# ---------- seeded packs ----------

@pytest.fixture(scope="module", params=list_pack_ids())
def seeded(request):
    c = db.connect()
    seed_pack(c, request.param, AS_OF)
    P = load_problem(c, request.param, AS_OF)
    return c, request.param, P, solve(P, time_limit=30)


def test_seeded_schedule_is_feasible_and_improves_readiness(seeded):
    _, _, P, r = seeded
    assert r["status"] in ("OPTIMAL", "FEASIBLE")
    assert validate(P, r["assignments"]) == []
    s = r["summary"]
    assert s["scheduled"] > 0.9 * s["items_outstanding"]
    assert s["readiness_after_pct"] > s["readiness_before_pct"] + 10
    assert s["readiness_after_pct"] <= 100.0


def test_every_outstanding_item_is_scheduled_or_explained(seeded):
    _, _, P, r = seeded
    got = {(a["person_id"], a["requirement_id"]) for a in r["assignments"]} | \
          {(u["person_id"], u["requirement_id"]) for u in r["unscheduled"]}
    assert got == {(i.pid, i.req_id) for i in P.items}
    assert all(u["reason"] for u in r["unscheduled"])


def test_resolve_with_prior_is_stable(seeded):
    c, pack, P, r = seeded
    r2 = solve(load_problem(c, pack, AS_OF), time_limit=30, prior=r["assignments"])
    d = diff_schedules(r["assignments"], r2["assignments"])
    assert not d["added"] and not d["removed"] and not d["moved"]


def test_what_if_commitment_shift_stays_valid_and_changes_little(seeded):
    c, pack, _, r = seeded
    cid = c.execute("SELECT id FROM commitment WHERE pack_id=? ORDER BY start LIMIT 1", (pack,)).fetchone()["id"]
    P2 = load_problem(c, pack, AS_OF, {"shift_commitments": {cid: 14}})
    r2 = solve(P2, time_limit=30, prior=r["assignments"])
    assert validate(P2, r2["assignments"]) == []
    d = diff_schedules(r["assignments"], r2["assignments"])
    assert len(d["moved"]) + len(d["added"]) + len(d["removed"]) < 0.5 * len(r["assignments"])


def test_what_if_seat_cut_reduces_or_delays(seeded):
    c, pack, P, r = seeded
    seats = {o.id: 1 for o in P.offerings.values()}
    P2 = load_problem(c, pack, AS_OF, {"seats": seats})
    r2 = solve(P2, time_limit=30)
    assert validate(P2, r2["assignments"]) == []
    assert r2["summary"]["scheduled"] < r["summary"]["scheduled"]


def test_save_approve_and_snapshot(seeded):
    c, pack, _, r = seeded
    run_id = save_run(c, pack, r)
    assert c.execute("SELECT status FROM schedule_run WHERE id=?", (run_id,)).fetchone()[0] == "proposed"
    set_run_status(c, run_id, "approved")
    assert c.execute("SELECT status FROM schedule_run WHERE id=?", (run_id,)).fetchone()[0] == "approved"
    assert c.execute("SELECT COUNT(*) FROM assignment WHERE run_id=?", (run_id,)).fetchone()[0] == len(r["assignments"])
    with pytest.raises(ValueError):
        set_run_status(c, run_id, "bogus")
