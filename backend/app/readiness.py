"""Readiness computation.

For each person we work out which requirements apply, whether each is met,
and what is due when. Nothing here is persisted; it is derived from rules and
completion records as of a given date.

Item status:
  complete  - satisfied and not about to lapse
  expiring  - satisfied, but lapses within EXPIRING_WINDOW_DAYS (still counts as ready)
  gap       - not satisfied, deadline still ahead
  overdue   - not satisfied, deadline passed

Colors for the UI: complete=green, expiring/gap=amber, overdue=red.
A gap whose prerequisites are unmet is flagged `blocked`.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta
from typing import Optional

EXPIRING_WINDOW_DAYS = 60


def _d(s: Optional[str]) -> Optional[date]:
    return date.fromisoformat(s) if s else None


@dataclass
class Item:
    requirement_id: str
    name: str
    status: str                      # complete | expiring | gap | overdue
    due: Optional[date] = None       # deadline for a gap; lapse date for expiring
    blocked_by: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return self.status in ("complete", "expiring")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["due"] = self.due.isoformat() if self.due else None
        return d


@dataclass
class PersonReadiness:
    person_id: int
    name: str
    role: str
    group_id: int
    items: list[Item]

    @property
    def applicable(self) -> int:
        return len(self.items)

    @property
    def ready_count(self) -> int:
        return sum(1 for i in self.items if i.ready)

    @property
    def pct(self) -> float:
        return 100.0 if not self.items else 100.0 * self.ready_count / self.applicable

    def to_dict(self) -> dict:
        return {
            "person_id": self.person_id, "name": self.name, "role": self.role,
            "group_id": self.group_id, "readiness_pct": round(self.pct, 1),
            "items": [i.to_dict() for i in self.items],
        }


def _applies(req: sqlite3.Row, person: sqlite3.Row, triggers: list[sqlite3.Row]):
    """Return the date the requirement was triggered for this person, or None."""
    filt = json.loads(req["applies_to"])
    roles = filt.get("role")
    if roles and person["role"] not in roles:
        return None
    attrs = json.loads(person["attributes"] or "{}")
    for key, allowed in (filt.get("attributes") or {}).items():
        if allowed and attrs.get(key) not in allowed:
            return None
    if req["trigger_type"] == "standing":
        return _d(person["start_date"])
    matching = [_d(t["date"]) for t in triggers if t["type"] == req["trigger_type"]]
    return max(matching) if matching else None


def _latest_valid(completions: list[sqlite3.Row], as_of: date) -> Optional[sqlite3.Row]:
    valid = [c for c in completions
             if _d(c["completed_on"]) <= as_of and (c["expires_on"] is None or _d(c["expires_on"]) >= as_of)]
    return max(valid, key=lambda c: c["completed_on"]) if valid else None


def person_readiness(conn: sqlite3.Connection, person_id: int, as_of: date) -> PersonReadiness:
    person = conn.execute("SELECT * FROM person WHERE id = ?", (person_id,)).fetchone()
    reqs = conn.execute("SELECT * FROM requirement WHERE pack_id = ?", (person["pack_id"],)).fetchall()
    triggers = conn.execute("SELECT * FROM event_trigger WHERE person_id = ?", (person_id,)).fetchall()
    comps = conn.execute("SELECT * FROM completion WHERE person_id = ?", (person_id,)).fetchall()
    by_req: dict[str, list[sqlite3.Row]] = {}
    for c in comps:
        by_req.setdefault(c["requirement_id"], []).append(c)

    satisfied = {r["id"] for r in reqs if _latest_valid(by_req.get(r["id"], []), as_of)}
    items: list[Item] = []
    for req in reqs:
        triggered = _applies(req, person, triggers)
        if triggered is None:
            continue
        valid = _latest_valid(by_req.get(req["id"], []), as_of)
        if valid:
            exp = _d(valid["expires_on"])
            if exp and exp - as_of <= timedelta(days=EXPIRING_WINDOW_DAYS):
                items.append(Item(req["id"], req["name"], "expiring", due=exp))
            else:
                items.append(Item(req["id"], req["name"], "complete"))
            continue
        # Not satisfied. Deadline: for a lapsed recurring item, the lapse date
        # (already passed); otherwise trigger date + deadline_days.
        past = [c for c in by_req.get(req["id"], []) if c["expires_on"]]
        if past:
            due = max(_d(c["expires_on"]) for c in past)
        else:
            due = triggered + timedelta(days=req["deadline_days"])
        prereqs = json.loads(req["prerequisites"])
        blocked = [p for p in prereqs if p not in satisfied]
        items.append(Item(req["id"], req["name"], "overdue" if due < as_of else "gap",
                          due=due, blocked_by=blocked))
    return PersonReadiness(person["id"], person["name"], person["role"], person["group_id"], items)


def pack_readiness(conn: sqlite3.Connection, pack_id: str, as_of: date) -> list[PersonReadiness]:
    ids = [r["id"] for r in conn.execute("SELECT id FROM person WHERE pack_id = ? ORDER BY id", (pack_id,))]
    return [person_readiness(conn, i, as_of) for i in ids]


def group_rollup(conn: sqlite3.Connection, pack_id: str, as_of: date) -> list[dict]:
    people = pack_readiness(conn, pack_id, as_of)
    out = []
    for g in conn.execute("SELECT * FROM grp WHERE pack_id = ? ORDER BY id", (pack_id,)):
        mine = [p for p in people if p.group_id == g["id"]]
        applicable = sum(p.applicable for p in mine)
        ready = sum(p.ready_count for p in mine)
        out.append({
            "group_id": g["id"], "name": g["name"], "people": len(mine),
            "readiness_pct": round(100.0 * ready / applicable, 1) if applicable else 100.0,
            "overdue": sum(1 for p in mine for i in p.items if i.status == "overdue"),
            "gaps": sum(1 for p in mine for i in p.items if i.status == "gap"),
            "expiring": sum(1 for p in mine for i in p.items if i.status == "expiring"),
        })
    return out
