"""SQLite schema and connection helpers.

All data in this demo is synthetic. Readiness is computed from these tables
(see readiness.py), never stored.
"""
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS pack (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    vocabulary TEXT NOT NULL            -- JSON
);
CREATE TABLE IF NOT EXISTS grp (
    id INTEGER PRIMARY KEY,
    pack_id TEXT NOT NULL REFERENCES pack(id),
    name TEXT NOT NULL,
    parent_id INTEGER REFERENCES grp(id),
    min_available INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS person (
    id INTEGER PRIMARY KEY,
    pack_id TEXT NOT NULL REFERENCES pack(id),
    group_id INTEGER NOT NULL REFERENCES grp(id),
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    start_date TEXT NOT NULL,           -- hire date / date of current role
    attributes TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS event_trigger (
    id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES person(id),
    type TEXT NOT NULL,                 -- promotion | hire | role_change
    date TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS requirement (
    id TEXT NOT NULL,
    pack_id TEXT NOT NULL REFERENCES pack(id),
    name TEXT NOT NULL,
    trigger_type TEXT NOT NULL,         -- promotion | hire | standing
    applies_to TEXT NOT NULL,           -- JSON, e.g. {"role": ["Sergeant"]}
    deadline_days INTEGER NOT NULL,
    prerequisites TEXT NOT NULL DEFAULT '[]',
    valid_days INTEGER,                 -- NULL = one-time, never expires
    slots_needed INTEGER NOT NULL DEFAULT 1,
    duration_days INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (pack_id, id)
);
CREATE TABLE IF NOT EXISTS completion (
    id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES person(id),
    requirement_id TEXT NOT NULL,
    completed_on TEXT NOT NULL,
    expires_on TEXT                     -- NULL = does not expire
);
CREATE TABLE IF NOT EXISTS offering (
    id INTEGER PRIMARY KEY,
    pack_id TEXT NOT NULL REFERENCES pack(id),
    requirement_id TEXT NOT NULL,
    start TEXT NOT NULL,
    end TEXT NOT NULL,
    seats INTEGER NOT NULL,
    location TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS commitment (
    id INTEGER PRIMARY KEY,
    pack_id TEXT NOT NULL REFERENCES pack(id),
    group_id INTEGER NOT NULL REFERENCES grp(id),
    type TEXT NOT NULL,                 -- exercise | deployment | leave | sprint | pto
    name TEXT NOT NULL,
    start TEXT NOT NULL,
    end TEXT NOT NULL,
    people TEXT                         -- JSON list of person ids; NULL = whole group
);
CREATE TABLE IF NOT EXISTS schedule_run (
    id INTEGER PRIMARY KEY,
    pack_id TEXT NOT NULL REFERENCES pack(id),
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'proposed',   -- proposed | approved | rejected
    constraints_snapshot TEXT NOT NULL DEFAULT '{}',
    score REAL
);
CREATE TABLE IF NOT EXISTS assignment (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES schedule_run(id),
    person_id INTEGER NOT NULL REFERENCES person(id),
    offering_id INTEGER NOT NULL REFERENCES offering(id),
    rationale TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_person_pack ON person(pack_id);
CREATE INDEX IF NOT EXISTS idx_completion_person ON completion(person_id);
"""


def connect(path: str = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn
