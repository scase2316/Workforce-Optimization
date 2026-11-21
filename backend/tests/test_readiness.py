import json
from datetime import date

import pytest

from app import db
from app.readiness import person_readiness, group_rollup, pack_readiness
from app.seed import seed_pack
from app.packs import list_pack_ids

AS_OF = date(2026, 11, 21)


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    c.execute("INSERT INTO pack VALUES ('t','Test','{}')")
    c.execute("INSERT INTO grp (id,pack_id,name,min_available) VALUES (1,'t','G1',0)")
    reqs = [
        ("course_a", "promotion", {"role": ["Sergeant"]}, 365, [], None),
        ("course_b", "promotion", {"role": ["Sergeant"]}, 365, ["course_a"], None),
        ("annual", "standing", {}, 365, [], 365),
    ]
    for rid, trig, applies, dl, pre, valid in reqs:
        c.execute("INSERT INTO requirement VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (rid, "t", rid, trig, json.dumps(applies), dl, json.dumps(pre), valid, 1, 1))
    return c


def add_person(c, pid, role="Sergeant", start="2026-06-01"):
    c.execute("INSERT INTO person (id,pack_id,group_id,name,role,start_date) VALUES (?,?,?,?,?,?)",
              (pid, "t", 1, f"P{pid}", role, start))
    c.execute("INSERT INTO event_trigger (person_id,type,date) VALUES (?,?,?)", (pid, "promotion", start))


def complete(c, pid, req, on, exp=None):
    c.execute("INSERT INTO completion (person_id,requirement_id,completed_on,expires_on) VALUES (?,?,?,?)",
              (pid, req, on, exp))


def status(pr):
    return {i.requirement_id: i for i in pr.items}


def test_gap_has_deadline_and_blocked_prereq(conn):
    add_person(conn, 1)
    s = status(person_readiness(conn, 1, AS_OF))
    assert s["course_a"].status == "gap" and s["course_a"].due == date(2027, 6, 1)
    assert s["course_b"].blocked_by == ["course_a"]


def test_overdue_when_deadline_passed(conn):
    add_person(conn, 1, start="2025-01-01")
    assert status(person_readiness(conn, 1, AS_OF))["course_a"].status == "overdue"


def test_completion_clears_gap_and_unblocks(conn):
    add_person(conn, 1)
    complete(conn, 1, "course_a", "2026-08-01")
    s = status(person_readiness(conn, 1, AS_OF))
    assert s["course_a"].status == "complete"
    assert s["course_b"].blocked_by == []


def test_role_filter(conn):
    add_person(conn, 1, role="Corporal")
    assert set(status(person_readiness(conn, 1, AS_OF))) == {"annual"}


def test_recurring_complete_expiring_and_lapsed(conn):
    add_person(conn, 1)
    complete(conn, 1, "annual", "2026-10-01", "2027-10-01")
    assert status(person_readiness(conn, 1, AS_OF))["annual"].status == "complete"
    add_person(conn, 2)
    complete(conn, 2, "annual", "2025-12-15", "2026-12-15")      # 24 days left
    s2 = status(person_readiness(conn, 2, AS_OF))["annual"]
    assert s2.status == "expiring" and s2.ready and s2.due == date(2026, 12, 15)
    add_person(conn, 3)
    complete(conn, 3, "annual", "2025-06-01", "2026-06-01")      # lapsed
    s3 = status(person_readiness(conn, 3, AS_OF))["annual"]
    assert s3.status == "overdue" and s3.due == date(2026, 6, 1)


def test_pct_counts_expiring_as_ready(conn):
    add_person(conn, 1, role="Corporal")
    complete(conn, 1, "annual", "2025-12-15", "2026-12-15")
    assert person_readiness(conn, 1, AS_OF).pct == 100.0


def test_group_rollup(conn):
    add_person(conn, 1, role="Corporal")      # 1 item: annual, gap/overdue
    add_person(conn, 2, role="Corporal")
    complete(conn, 2, "annual", "2026-10-01", "2027-10-01")
    g = group_rollup(conn, "t", AS_OF)[0]
    assert g["people"] == 2 and g["readiness_pct"] == 50.0


@pytest.mark.parametrize("pack_id", list_pack_ids())
def test_seed_is_deterministic_and_sane(pack_id):
    a, b = db.connect(), db.connect()
    ra, rb = seed_pack(a, pack_id, AS_OF), seed_pack(b, pack_id, AS_OF)
    assert ra == rb and ra["people"] == 150
    dump = lambda c: [tuple(r) for r in c.execute("SELECT * FROM completion ORDER BY id")]
    assert dump(a) == dump(b)
    pct = [p.pct for p in pack_readiness(a, pack_id, AS_OF)]
    assert 55 < sum(pct) / len(pct) < 95          # realistic spread, not all-green or all-red
    assert min(pct) < 100 and max(pct) == 100


def test_reseed_replaces_pack_and_keeps_other_pack():
    c = db.connect()
    seed_pack(c, "marine_corps", AS_OF)
    seed_pack(c, "onboarding", AS_OF)
    seed_pack(c, "marine_corps", AS_OF, seed=7)
    n = lambda p: c.execute("SELECT COUNT(*) FROM person WHERE pack_id=?", (p,)).fetchone()[0]
    assert n("marine_corps") == 150 and n("onboarding") == 150


def test_min_available_never_exceeds_group_size():
    c = db.connect()
    seed_pack(c, "marine_corps", AS_OF)
    for g in c.execute("SELECT id,min_available FROM grp"):
        size = c.execute("SELECT COUNT(*) FROM person WHERE group_id=?", (g["id"],)).fetchone()[0]
        assert 0 < g["min_available"] <= size
