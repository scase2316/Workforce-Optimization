"""Requirement rules: read, validate, preview, create, edit, delete.

Everything the optimizer needs is data in the `requirement` table, so editing a rule
changes readiness and scheduling immediately. No AI involved here; the AI layer (ai.py)
only proposes rules in this same structure for a person to confirm.
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from datetime import date
from typing import Optional

from .packs import load_pack
from .readiness import pack_readiness
from .seed import generate_offerings

TRIGGERS = ("promotion", "hire", "standing")
TRIGGER_LABELS = {"promotion": "On promotion", "hire": "On hire", "standing": "Everyone, recurring"}


class RuleError(ValueError):
    def __init__(self, errors: list[str], status: int = 422):
        super().__init__("; ".join(errors))
        self.errors, self.status = errors, status


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40] or "rule"


def _to_rule(r: sqlite3.Row, session_count: int = 0) -> dict:
    f = json.loads(r["applies_to"])
    return {"id": r["id"], "name": r["name"], "trigger_type": r["trigger_type"],
            "roles": f.get("role", []), "attributes": f.get("attributes", {}),
            "deadline_days": r["deadline_days"], "valid_days": r["valid_days"],
            "duration_days": r["duration_days"], "prerequisites": json.loads(r["prerequisites"]),
            "session_count": session_count}


def list_rules(conn: sqlite3.Connection, pack: str) -> list[dict]:
    counts = {r[0]: r[1] for r in conn.execute(
        "SELECT requirement_id, COUNT(*) FROM offering WHERE pack_id = ? GROUP BY requirement_id", (pack,))}
    return [_to_rule(r, counts.get(r["id"], 0))
            for r in conn.execute("SELECT * FROM requirement WHERE pack_id = ? ORDER BY rowid", (pack,))]


def facets(conn: sqlite3.Connection, pack: str) -> dict:
    vocab = load_pack(pack)["vocabulary"]
    roles = Counter(); attrs: dict[str, Counter] = {}
    for r in conn.execute("SELECT role, attributes FROM person WHERE pack_id = ?", (pack,)):
        roles[r["role"]] += 1
        for k, v in json.loads(r["attributes"] or "{}").items():
            attrs.setdefault(k, Counter())[v] += 1
    labels, names = vocab.get("attribute_labels", {}), vocab.get("attribute_values", {})
    events = {r[0] for r in conn.execute(
        "SELECT DISTINCT type FROM event_trigger WHERE person_id IN (SELECT id FROM person WHERE pack_id = ?)", (pack,))}
    return {
        "roles": [{"value": k, "count": n} for k, n in sorted(roles.items(), key=lambda kv: -kv[1])],
        "attributes": {k: {"label": labels.get(k, k), "values": [
            {"value": v, "label": names.get(k, {}).get(v, v), "count": n} for v, n in sorted(c.items(), key=lambda kv: -kv[1])]}
            for k, c in attrs.items()},
        "triggers": [{"value": t, "label": TRIGGER_LABELS[t], "available": t == "standing" or t in events} for t in TRIGGERS],
    }


def _has_cycle(graph: dict[str, list[str]]) -> bool:
    state: dict[str, int] = {}
    def visit(n: str) -> bool:
        if state.get(n) == 1: return True
        if state.get(n) == 2: return False
        state[n] = 1
        if any(visit(m) for m in graph.get(n, [])): return True
        state[n] = 2
        return False
    return any(visit(n) for n in graph)


def validate(conn: sqlite3.Connection, pack: str, rule: dict, existing_id: Optional[str]) -> list[str]:
    errs: list[str] = []
    name = (rule.get("name") or "").strip()
    if not name or len(name) > 80: errs.append("Give the requirement a name (80 characters or fewer).")
    if rule.get("trigger_type") not in TRIGGERS: errs.append("Choose when the requirement starts: on promotion, on hire, or for everyone.")
    if not 1 <= int(rule.get("deadline_days") or 0) <= 3650: errs.append("The deadline must be between 1 day and 10 years.")
    if rule.get("valid_days") is not None and not 1 <= int(rule["valid_days"]) <= 3650: errs.append("'Valid for' must be between 1 day and 10 years, or left empty for never expires.")
    if not 1 <= int(rule.get("duration_days") or 0) <= 365: errs.append("Course length must be between 1 and 365 days.")
    rid = existing_id or rule.get("id") or slugify(name)
    if not re.fullmatch(r"[a-z0-9_]{2,40}", rid): errs.append("The id may use lowercase letters, numbers, and underscores only.")
    existing = {r["id"]: json.loads(r["prerequisites"]) for r in conn.execute("SELECT id, prerequisites FROM requirement WHERE pack_id = ?", (pack,))}
    if not existing_id and rid in existing: errs.append(f"A requirement with the id '{rid}' already exists. Pick a different name.")
    prereqs = list(rule.get("prerequisites") or [])
    for p in prereqs:
        if p == rid: errs.append("A requirement can't be its own prerequisite.")
        elif p not in existing: errs.append(f"Unknown prerequisite '{p}'.")
    graph = {**existing, rid: prereqs}
    if not errs and _has_cycle(graph): errs.append("Those prerequisites form a loop. Remove one so each course has a clear order.")
    known = set(facets(conn, pack)["attributes"])
    for k in (rule.get("attributes") or {}):
        if k not in known: errs.append(f"Unknown filter '{k}'. Available: {', '.join(sorted(known)) or 'none'}.")
    if rule.get("trigger_type") in ("promotion", "hire"):
        if not any(t["value"] == rule["trigger_type"] and t["available"] for t in facets(conn, pack)["triggers"]):
            errs.append(f"This scenario has no '{rule['trigger_type']}' events, so the rule would never apply.")
    s = rule.get("sessions")
    if s and (s["every_days"] < 1 or not 1 <= s["seats"] <= 500 or s["first_offset_days"] < 1):
        errs.append("Sessions need a start at least 1 day out, a repeat of at least 1 day, and 1 to 500 seats.")
    return errs


def _applies_json(rule: dict) -> str:
    f: dict = {}
    if rule.get("roles"): f["role"] = list(rule["roles"])
    attrs = {k: list(v) for k, v in (rule.get("attributes") or {}).items() if v}
    if attrs: f["attributes"] = attrs
    return json.dumps(f)


def _guard_offerings(conn: sqlite3.Connection, pack: str, rid: str) -> None:
    used = conn.execute(
        "SELECT 1 FROM assignment a JOIN offering o ON o.id = a.offering_id JOIN schedule_run s ON s.id = a.run_id "
        "WHERE o.pack_id = ? AND o.requirement_id = ? AND s.status = 'approved' LIMIT 1", (pack, rid)).fetchone()
    if used:
        raise RuleError(["An approved plan uses sessions of this requirement. Reject that plan first, then try again."], 409)


def _drop_offerings(conn: sqlite3.Connection, pack: str, rid: str) -> None:
    ids = [r[0] for r in conn.execute("SELECT id FROM offering WHERE pack_id = ? AND requirement_id = ?", (pack, rid))]
    for i in ids:
        conn.execute("DELETE FROM assignment WHERE offering_id = ?", (i,))
    conn.execute("DELETE FROM offering WHERE pack_id = ? AND requirement_id = ?", (pack, rid))


def _write(conn: sqlite3.Connection, pack: str, rule: dict, rid: str, existing: bool, as_of: date, horizon: int) -> None:
    vals = (rule["name"].strip(), rule["trigger_type"], _applies_json(rule), int(rule["deadline_days"]),
            json.dumps(list(rule.get("prerequisites") or [])), rule.get("valid_days"), int(rule.get("duration_days") or 1))
    if existing:
        conn.execute("UPDATE requirement SET name=?, trigger_type=?, applies_to=?, deadline_days=?, prerequisites=?, "
                     "valid_days=?, duration_days=? WHERE pack_id=? AND id=?", (*vals, pack, rid))
        conn.execute("UPDATE offering SET end = date(start, ?) WHERE pack_id = ? AND requirement_id = ?",
                     (f"+{int(rule.get('duration_days') or 1) - 1} days", pack, rid))
    else:
        conn.execute("INSERT INTO requirement VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (rid, pack, vals[0], vals[1], vals[2], vals[3], vals[4], vals[5], 1, vals[6]))
    s = rule.get("sessions")
    if s:
        if existing:
            _guard_offerings(conn, pack, rid)
            _drop_offerings(conn, pack, rid)
        generate_offerings(conn, pack, rid, int(rule.get("duration_days") or 1), as_of, horizon,
                           s["first_offset_days"], s["every_days"], s["seats"], s.get("location", ""))


def get_version(conn: sqlite3.Connection, pack: str) -> int:
    r = conn.execute("SELECT value FROM meta WHERE key = ?", (f"rules_version:{pack}",)).fetchone()
    return int(r[0]) if r else 1


def bump_version(conn: sqlite3.Connection, pack: str) -> int:
    v = get_version(conn, pack) + 1
    conn.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (f"rules_version:{pack}", str(v)))
    return v


def save(conn: sqlite3.Connection, pack: str, rule: dict, existing_id: Optional[str], as_of: date, horizon: int) -> dict:
    errs = validate(conn, pack, rule, existing_id)
    if errs: raise RuleError(errs)
    rid = existing_id or rule.get("id") or slugify(rule["name"])
    try:
        _write(conn, pack, rule, rid, bool(existing_id), as_of, horizon)
        bump_version(conn, pack)
        conn.commit()
    except Exception:
        conn.rollback(); raise
    return next(r for r in list_rules(conn, pack) if r["id"] == rid)


def delete(conn: sqlite3.Connection, pack: str, rid: str) -> None:
    if not conn.execute("SELECT 1 FROM requirement WHERE pack_id = ? AND id = ?", (pack, rid)).fetchone():
        raise RuleError(["No such requirement."], 404)
    dependants = [r["name"] for r in conn.execute("SELECT name, prerequisites FROM requirement WHERE pack_id = ?", (pack,))
                  if rid in json.loads(r["prerequisites"])]
    if dependants:
        raise RuleError([f"'{dependants[0]}' needs this as a prerequisite. Change that requirement first."], 409)
    _guard_offerings(conn, pack, rid)
    try:
        _drop_offerings(conn, pack, rid)
        conn.execute("DELETE FROM requirement WHERE pack_id = ? AND id = ?", (pack, rid))
        bump_version(conn, pack)
        conn.commit()
    except Exception:
        conn.rollback(); raise


def preview(conn: sqlite3.Connection, pack: str, rule: dict, existing_id: Optional[str], as_of: date, horizon: int) -> dict:
    """What would this rule do right now? Writes inside a savepoint and rolls it back."""
    errs = validate(conn, pack, rule, existing_id)
    if errs: return {"errors": errs}
    rid = existing_id or rule.get("id") or slugify(rule["name"])
    before = pack_readiness(conn, pack, as_of)
    pct = lambda ps: round(100 * sum(p.ready_count for p in ps) / max(1, sum(p.applicable for p in ps)), 1)
    conn.execute("SAVEPOINT preview")
    try:
        _write(conn, pack, {**rule, "sessions": None}, rid, bool(existing_id), as_of, horizon)
        after = pack_readiness(conn, pack, as_of)
    finally:
        conn.execute("ROLLBACK TO preview"); conn.execute("RELEASE preview")
    items = [i for p in after for i in p.items if i.requirement_id == rid]
    c = Counter(i.status for i in items)
    return {"errors": [], "applies_to": len(items), "people_total": len(after),
            "by_status": {k: c[k] for k in ("complete", "expiring", "gap", "overdue")},
            "readiness_before_pct": pct(before), "readiness_after_pct": pct(after)}
