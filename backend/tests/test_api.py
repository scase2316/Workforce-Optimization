import pytest
from fastapi.testclient import TestClient

from app import api


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    api.DB_PATH = str(tmp_path_factory.mktemp("db") / "t.db")
    api._conn = None
    api._runs.clear()
    return TestClient(api.app)


def test_packs_and_overview(client):
    packs = client.get("/api/packs").json()
    assert {p["id"] for p in packs} == {"marine_corps", "onboarding"}
    o = client.get("/api/marine_corps/overview").json()
    assert o["totals"]["people"] == 150 and len(o["groups"]) == 5
    assert 0 < o["totals"]["readiness_pct"] < 100
    assert client.get("/api/nope/overview").status_code == 404


def test_people_filter_and_detail(client):
    rows = client.get("/api/marine_corps/people", params={"status": "overdue", "limit": 5}).json()
    assert len(rows) == 5 and all(r["overdue"] > 0 for r in rows)
    d = client.get(f"/api/marine_corps/people/{rows[0]['person_id']}").json()
    assert d["items"] and d["group"]


def test_schedule_whatif_and_approval_flow(client):
    base = client.post("/api/marine_corps/schedule").json()
    assert base["run_status"] == "proposed" and base["summary"]["scheduled"] > 0
    cap = base["capacity"]
    assert len(cap["groups"][0]["planned"]) == 181
    assert all(p <= b for g in cap["groups"] for p, b in zip(g["planned"], g["base"]))

    cid = cap["commitments"][0]["id"]
    wi = client.post(f"/api/marine_corps/schedule/{base['run_id']}/what-if",
                     json={"shift": [{"commitment_id": cid, "days": 14}]}).json()
    assert wi["parent_run_id"] == base["run_id"] and wi["diff"] is not None
    assert wi["run_id"] != base["run_id"]

    ok = client.post(f"/api/schedule/{wi['run_id']}/status", json={"status": "approved"}).json()
    assert ok["run_status"] == "approved"
    assert client.post(f"/api/schedule/{wi['run_id']}/status", json={"status": "weird"}).status_code == 400
    assert client.get("/api/marine_corps/schedule/latest").json()["run_status"] == "approved"


def test_seat_cap_whatif_reduces_scheduling(client):
    base = client.post("/api/onboarding/schedule").json()
    wi = client.post(f"/api/onboarding/schedule/{base['run_id']}/what-if",
                     json={"seat_cap": [{"requirement_id": "product_bootcamp", "seats": 1}]}).json()
    assert wi["summary"]["scheduled"] < base["summary"]["scheduled"]
    assert wi["diff"]["removed"] or wi["diff"]["moved"]


def test_capacity_for_run_reflects_what_if_overrides(client):
    base = client.post("/api/marine_corps/schedule").json()
    cid = base["capacity"]["commitments"][0]["id"]
    wi = client.post(f"/api/marine_corps/schedule/{base['run_id']}/what-if",
                     json={"shift": [{"commitment_id": cid, "days": 20}]}).json()
    c0 = next(c for c in base["capacity"]["commitments"] if c["id"] == cid)
    c1 = next(c for c in client.get("/api/marine_corps/capacity", params={"run_id": wi["run_id"]}).json()["commitments"] if c["id"] == cid)
    assert c1["start"] == c0["start"] + 20


def test_unknown_run_is_404(client):
    assert client.post("/api/schedule/99999/status", json={"status": "approved"}).status_code == 404
