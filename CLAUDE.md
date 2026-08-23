# AI Personal Budgeting & Expense Categorisation System

Personal project with two equally real goals: build a working AI-assisted budgeting tool, and use
it as a hands-on vehicle to learn agentic AI engineering. When proposing workflow/tooling choices
(skills, subagents, commands, review loops), explain the *why*, not just the *what* — the teaching
value is part of the deliverable, not a side effect.

## Source of truth (read these; this file doesn't duplicate them)

- `docs/product-requirements.md` — requirements, decisions, open questions (living doc).
- `docs/next-steps.md` — resumable priority-ordered to-do list. Read this first when resuming work.
- `docs/agentic-workflow.md` — how this repo's AI-assisted dev workflow works and why it's built
  the way it is (skills vs. subagents vs. commands vs. plan mode).

## Tech stack & structure

Python 3.11 · FastAPI (`backend/`) · SQLAlchemy + SQLite (`finance.db`) · Pandas (`ingestion/`) ·
rule-based categorisation (`categorisation/`) · Streamlit (`frontend/`) · pytest (`tests/`).

## Commands

- Backend: `uvicorn backend.api:app --reload`
- Dashboard: `streamlit run frontend/dashboard.py`
- Tests: `pytest`

## Conventions

- Changes to `backend/`, `ingestion/`, `categorisation/`, or `frontend/` interaction logic
  (Streamlit widget/state behaviour, tested via `AppTest`) follow the tests-first workflow in the
  `tdd-workflow` skill (auto-triggers on those paths). Pure visual/layout changes to `frontend/` are
  verified by running the app instead (see the `run` skill) — not this skill's job.
- Run `/code-review` on non-trivial changes before considering them done.
- The original `backend/`, `frontend/`, `ingestion/`, `categorisation/` code (as of the initial MVP
  commit) predated the finalized requirements and was built against a placeholder CSV shape — that
  review is done: see `docs/product-requirements.md` §8 for the per-module reuse/refactor/discard
  verdict (`backend/*` and `frontend/dashboard.py` refactor; `ingestion/csv_importer.py` and
  `categorisation/*` discard) before touching any of those files.
- Before considering **any** change done — code, a decision, or a Plan Mode plan that got approved
  or changed direction mid-task — update `docs/next-steps.md` and, if a decision changed,
  `docs/product-requirements.md`. Don't leave state only in an ephemeral plan file or this
  conversation; those aren't read by a future session, the docs are.
- Keep those docs shaped so a future session (or Rohan, cold) can resume from them alone: a clear
  history of what happened and when, what's next in priority order, and decisions made with the
  reasoning behind them — not just the decision itself. This mirrors the existing pattern of
  "~~old text~~ — **Decided**/**Done** <date>: <what and why>" already used throughout both docs;
  keep using it rather than inventing a new format.
