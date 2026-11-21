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

Stages 1-4 done: foundation, CP-SAT optimizer, UI, and rules + AI. Remaining: polish
(business case panel, architecture diagram, demo script, one-page write-up).

## Rules and AI

Requirements are data. The **Rules** screen lets you add, edit, and delete them: who they apply to
(role plus filters such as specialty), when they start, the deadline, how long a completion lasts,
prerequisites, and sessions. A live preview shows how many people a rule touches before you save.

AI is optional and always human-confirmed. It never schedules anything; the solver does.

| Feature | What it does |
|---|---|
| Draft rules | Turns policy text into proposed rules; you review each in the editor before it is saved |
| Say a change in words | "Move the field exercise two weeks later" becomes a structured change; you confirm, then the solver runs |
| Ask about a plan | Answers from the plan's own data only, with the relevant facts sent to the model, not the whole roster |

Without `ANTHROPIC_API_KEY` the app runs in **demo mode**: a free pattern matcher that handles simple
phrasings. With a key it uses Claude with structured tool output. Settings (environment variables):

- `ANTHROPIC_API_KEY`: turns on live mode
- `READINESS_AI_MODEL`: default `claude-haiku-5-5` (small and cheap; fine for these tasks)
- `READINESS_AI_DAILY_LIMIT`: default 100 requests per day, to cap cost

Policy text is treated as untrusted data. The live path has been tested against a fake model client and
the SDK's call signature; it has not yet been run against the real API.

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
backend/app/rules.py       requirement CRUD, validation, preview
backend/app/ai.py          optional AI: rule drafting, change parsing, grounded Q&A (live + demo modes)
backend/app/api.py         FastAPI endpoints (async, one SQLite connection)
frontend/src/              React + TypeScript UI: Readiness, Rules, Capacity, Schedule
backend/app/packs/<id>/    rules.json, vocabulary.json, scenario.json
```
