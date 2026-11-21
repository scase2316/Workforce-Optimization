import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import api

BASE = {"name": "Land Navigation", "trigger_type": "standing", "deadline_days": 365, "valid_days": 365,
        "duration_days": 2, "roles": [], "attributes": {}, "prerequisites": []}


@pytest.fixture()
def client(tmp_path):
    api.DB_PATH = str(tmp_path / "t.db"); api._conn = None; api._runs.clear()
    return TestClient(api.app)


def rules(c, pack="marine_corps"):
    return c.get(f"/api/{pack}/rules").json()


def test_attribute_filter_applies_only_to_matching_people(client):
    body = {**BASE, "name": "Infantry only", "trigger_type": "promotion", "roles": ["Sergeant"],
            "attributes": {"mos": ["0311", "0331"]}}
    pv = client.post("/api/marine_corps/rules/preview", json=body).json()
    db = sqlite3.connect(api.DB_PATH); db.row_factory = sqlite3.Row      # app's connection is bound to the server thread
    expect = sum(1 for r in db.execute("SELECT role, attributes FROM person WHERE pack_id='marine_corps'")
                 if r["role"] == "Sergeant" and json.loads(r["attributes"])["mos"] in ("0311", "0331"))
    assert pv["errors"] == [] and pv["applies_to"] == expect > 0


def test_seeded_iulc_rule_is_staff_sergeant_infantry_only(client):
    iulc = next(r for r in rules(client)["rules"] if r["id"] == "iulc")
    assert iulc["roles"] == ["Staff Sergeant"] and iulc["deadline_days"] == 548 and iulc["prerequisites"] == ["sgt_course"]
    people = client.get("/api/marine_corps/people", params={"limit": 300}).json()
    detail = [client.get(f"/api/marine_corps/people/{p['person_id']}").json() for p in people if p["role"] == "Staff Sergeant"]
    holders = [d for d in detail if any(i["requirement_id"] == "iulc" for i in d["items"])]
    assert holders and len(holders) < len(detail)          # filtered: not every Staff Sergeant


def test_create_with_sessions_bumps_version_and_is_schedulable(client):
    v0 = rules(client)["rules_version"]
    r = client.post("/api/marine_corps/rules", json={**BASE, "sessions": {"first_offset_days": 5, "every_days": 20, "seats": 40, "location": "Range"}})
    assert r.status_code == 200 and r.json()["id"] == "land_navigation" and r.json()["session_count"] >= 8
    assert rules(client)["rules_version"] == v0 + 1
    run = client.post("/api/marine_corps/schedule").json()
    assert any(a["requirement_id"] == "land_navigation" for a in run["assignments"])


def test_rule_without_sessions_is_reported_unschedulable(client):
    client.post("/api/marine_corps/rules", json=BASE)
    run = client.post("/api/marine_corps/schedule").json()
    assert any(u["requirement_id"] == "land_navigation" and "No offering" in u["reason"] for u in run["unscheduled"])


@pytest.mark.parametrize("patch,needle", [
    ({"trigger_type": "sometimes"}, "when the requirement starts"),
    ({"name": " "}, "name"),
    ({"deadline_days": 0}, "deadline"),
    ({"prerequisites": ["nope"]}, "Unknown prerequisite"),
    ({"attributes": {"shoe_size": ["9"]}}, "Unknown filter"),
    ({"trigger_type": "hire"}, "no 'hire' events"),
    ({"name": "Cyber Awareness Training", "id": "cyber"}, "already exists"),
])
def test_validation_messages(client, patch, needle):
    r = client.post("/api/marine_corps/rules", json={**BASE, **patch})
    assert r.status_code == 422 and any(needle in e for e in r.json()["detail"])


def test_prerequisite_loop_is_rejected(client):
    r = client.put("/api/marine_corps/rules/cpl_course", json={**BASE, "name": "Corporals Course", "trigger_type": "promotion",
                                                              "roles": ["Corporal"], "prerequisites": ["sgt_course"]})
    assert r.status_code == 422 and any("loop" in e for e in r.json()["detail"])


def test_preview_changes_nothing(client):
    before = json.dumps(rules(client), sort_keys=True)
    pv = client.post("/api/marine_corps/rules/preview", json={**BASE, "deadline_days": 30, "valid_days": 30}).json()
    assert pv["errors"] == [] and pv["applies_to"] == 150
    assert json.dumps(rules(client), sort_keys=True) == before


def test_editing_a_deadline_changes_readiness(client):
    before = client.get("/api/marine_corps/overview").json()["totals"]
    rule = next(r for r in rules(client)["rules"] if r["id"] == "cpl_course")
    body = {k: rule[k] for k in ("name", "trigger_type", "roles", "attributes", "deadline_days", "valid_days", "duration_days", "prerequisites")}
    body["deadline_days"] = 5          # promoted Corporals are now almost all overdue
    assert client.put("/api/marine_corps/rules/cpl_course", json=body).status_code == 200
    after = client.get("/api/marine_corps/overview").json()["totals"]
    assert after["overdue"] > before["overdue"]


def test_delete_guards(client):
    r = client.delete("/api/marine_corps/rules/cpl_course")                  # sgt_course depends on it
    assert r.status_code == 409 and "prerequisite" in r.json()["detail"][0]
    client.post("/api/marine_corps/rules", json={**BASE, "sessions": {"first_offset_days": 5, "every_days": 20, "seats": 40}})
    run = client.post("/api/marine_corps/schedule").json()
    client.post(f"/api/schedule/{run['run_id']}/status", json={"status": "approved"})
    assert client.delete("/api/marine_corps/rules/land_navigation").status_code == 409     # approved plan uses it
    client.post(f"/api/schedule/{run['run_id']}/status", json={"status": "rejected"})
    assert client.delete("/api/marine_corps/rules/land_navigation").status_code == 200
    assert all(r["id"] != "land_navigation" for r in rules(client)["rules"])
    assert client.delete("/api/marine_corps/rules/land_navigation").status_code == 404


def test_plan_goes_stale_after_rule_change_and_reset_restores(client):
    run = client.post("/api/marine_corps/schedule").json()
    client.post("/api/marine_corps/rules", json={**BASE, "sessions": {"first_offset_days": 5, "every_days": 20, "seats": 40}})
    assert run["rules_version"] < client.get("/api/marine_corps/overview").json()["rules_version"]
    n = len(rules(client)["rules"])
    assert client.post("/api/marine_corps/reset").status_code == 200
    assert len(rules(client)["rules"]) == n - 1
    assert client.get("/api/marine_corps/schedule/latest").json() is None


def test_facets_label_specialties(client):
    f = rules(client)["facets"]
    assert f["attributes"]["mos"]["label"] == "MOS"
    assert {"value": "0311", "label": "Rifleman"}.items() <= next(v for v in f["attributes"]["mos"]["values"] if v["value"] == "0311").items()
    assert {t["value"]: t["available"] for t in f["triggers"]} == {"promotion": True, "hire": False, "standing": True}
