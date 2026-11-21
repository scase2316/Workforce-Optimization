# Readiness Optimizer

A demo of a workforce readiness and training-scheduling tool. Requirements are
triggered by events (promotion, hire), compared against each person's record,
and scheduled around operational capacity. A human approves every schedule.

The core is organization-agnostic. A **scenario pack** (rules, vocabulary,
synthetic data) adapts it to a use case. Two ship today:

- `marine_corps`: promotion-driven schools, annual training, ops tempo
- `onboarding`: new-hire compliance and enablement around team delivery cycles

**All data is synthetic.** Course names and intervals are illustrative.

## Status

Stages 1-3 of 5 done: foundation, CP-SAT optimizer, and the UI (readiness dashboard,
capacity timeline, schedule with what-if, diff, and approval). Agent layer and polish are next.

## Run

```bash
make install     # Python deps + npm install (first time)
make run         # builds the UI, serves everything at http://localhost:8000
make test        # backend test suite
```

For development use two terminals: `make dev-api` and `make dev-ui` (UI at :5173).
Demo data is created on first start in `demo.db`; delete the file to reset.

## Layout

```
backend/app/db.py          SQLite schema
backend/app/readiness.py   gaps, expiring items, per-person and per-group readiness
backend/app/seed.py        synthetic data generator
backend/app/solver.py      CP-SAT optimizer, what-if overrides, validate(), diff, save/approve
backend/app/api.py         FastAPI endpoints (async, one SQLite connection)
frontend/src/              React + TypeScript UI: Readiness, Capacity, Schedule
backend/app/packs/<id>/    rules.json, vocabulary.json, scenario.json
```
