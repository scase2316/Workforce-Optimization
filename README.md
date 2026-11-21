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

Stage 1 of 5 (foundation): schema, scenario packs, deterministic seed
generator, readiness computation, tests. Solver, UI, and agent layer are next.

## Run

```bash
make test        # run the test suite
make seed        # create demo.db with both packs
```

## Layout

```
backend/app/db.py          SQLite schema
backend/app/readiness.py   gaps, expiring items, per-person and per-group readiness
backend/app/seed.py        synthetic data generator
backend/app/packs/<id>/    rules.json, vocabulary.json, scenario.json
```
