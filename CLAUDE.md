# Readiness Optimizer: project context

Portfolio demo of a workforce readiness and training-scheduling tool. Org-agnostic
core; "scenario packs" (backend/app/packs/<id>/) adapt it (marine_corps, onboarding).
All data is synthetic. Goal: show problem-spotting and solutions engineering, so
polish, a tight demo path, and honest framing matter more than feature count.

## Hard rules
- The LLM never produces schedules. It edits structured rules/constraint overrides and
  calls `solver.solve`. Explanations come from solver rationale data.
- Nothing is "scheduled" without human approval (schedule_run.status).
- Mock adapters only; document the real-integration path in the README. Don't overclaim.
- Readiness is computed (readiness.py), never stored.

## Stages
1. Foundation: DONE (schema, packs, seed, readiness)
2. Solver: DONE (solver.py: overrides, validate, diff_schedules, save_run)
3. UI: DONE (frontend/src: Readiness, Capacity timeline, Schedule + what-if + approve; pack accent switches per scenario)
4. Agent layer (Claude API; canned-response fallback when no key): rule intake with confirmation, what-if, explanations
5. Polish: business case panel, README + architecture diagram, 3-minute demo script, one-page write-up, one-command run

Check in with the user after each stage. Keep scope tight (see README for cuts).

## UI notes
- Design: cool-grey paper, ink rail, one accent per pack (data-pack attr), Schibsted Grotesk. Signature element is the Capacity chart (people away, stacked, vs. a dashed ceiling). Keep everything else quiet.
- Avoid `tabular-nums` on prose: this font widens punctuation. Only numeric cells use it.
- Verified with headless Chrome screenshots (desktop + 390px). No frontend unit tests yet.

## Commands
- `make run` builds UI and serves at :8000; `make test` runs pytest; `make seed` creates demo.db
- Setup: `make install`
