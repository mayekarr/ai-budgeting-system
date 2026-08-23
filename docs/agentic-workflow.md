# Agentic Development Workflow

Status: Active
Last updated: 2026-08-17
Companion to: `docs/product-requirements.md` (requirements) and `docs/next-steps.md` (to-do list)

This doc explains how AI-assisted development works in this repo, and — since this project exists
partly to teach agentic AI engineering — *why* it's built this way rather than just documenting the
mechanics. It replaces an earlier Cursor + OpenAI-API setup (`AGENTS.md`, `README_AGENTS.md`,
`tools/agents.py`, `.cursor/skills/`) that predated the move to Claude Code.

## 1. The five primitives

Claude Code gives you five different tools for shaping how an AI agent works on a codebase. They
overlap in what they *can* do, which is exactly why picking the right one matters — using a
subagent where a skill would do just burns context and adds indirection for no benefit.

| Primitive | What it is | Cost/overhead | Good for |
|---|---|---|---|
| **CLAUDE.md** | A file auto-loaded into every session's context | Always paid, every turn | Facts the agent needs *every* session: stack, commands, conventions |
| **Plan Mode** | A mode that forces explore→design→approve before any edit | One round-trip per non-trivial task | Getting alignment before code changes, especially when several approaches exist |
| **Skills** | Instructions that auto-load into the *current* context when their description matches the task | Cheap — no new context window | Reusable "how we do X here" playbooks (a workflow, a house style) |
| **Subagents** | A *separate* context window with its own tools/system prompt, invoked explicitly, returns only a summary | Expensive — full new context | Isolating large/parallel work (research, audits) so it doesn't pollute the main conversation |
| **Slash commands** | A named prompt template, invoked explicitly by the user | Cheap — just a stored prompt | Repeating a specific multi-step *ask* consistently (not a capability the agent should reach for on its own) |

The old setup used one shape (a Cursor rules file + Python functions calling the OpenAI API
directly) to represent four different *roles* (Planner, Coder, Reviewer, Build & Run). That's the
wrong level of abstraction — those four roles actually need three different primitives, and one of
them Claude Code already provides for free.

## 2. Mapping the old roles

**Planner → Plan Mode (built in, not custom).** The old `AGENTS.md` Planner was a prompting
convention: *"act as the Planner Agent and give me a plan before I paste it back for the Coder."*
Claude Code's Plan Mode does the same job natively — it blocks edits until you approve a plan drawn
from actually exploring the code, and it's triggered automatically for non-trivial work (see
§4 below) rather than requiring you to remember to ask for it. Building a custom subagent to
duplicate this would be strictly worse: two competing planning mechanisms, more context spent, no
new capability.

**Reviewer → the `code-review` skill (built in, not custom).** Already available in this
environment — invoke with `/code-review`. It reviews the current diff (or a PR/branch) for
correctness and simplification issues, at a configurable effort level. Again: a purpose-built,
already-integrated tool beats re-deriving the same capability from scratch.

**Build & Run → the `run` skill (built in, not custom).** Already available in this environment.
It launches and drives this project's app (FastAPI backend, Streamlit dashboard) to confirm a
change actually works, not just that tests pass.

**Coder → the `tdd-workflow` skill (`.claude/skills/tdd-workflow/SKILL.md`, custom, ported from
the old Cursor skill).** This is the one role with no Claude-Code built-in, because it encodes
*this project's specific* tests-first convention for `backend/`, `ingestion/`, and
`categorisation/` — the "how we work" is repo-specific, so it has to live in the repo. It
auto-triggers by description match (see §3) rather than needing to be invoked by name.

The lesson generalizes beyond this project: **before building custom agent infrastructure, check
what the platform already gives you.** Three of four roles needed zero new code.

## 3. Skills vs. subagents, concretely

`tdd-workflow` is a **skill**, not a subagent, because the work it governs — reading a few files,
writing a test, writing the implementation, running `pytest` — belongs in the *same* context as the
rest of the conversation. A subagent would return only a summary, forcing you to re-fetch file
contents you already had; that's pure overhead here.

A subagent earns its cost when the work is genuinely separable: large, exploratory, or
parallelizable, where you want the bulk of the intermediate reading kept *out* of the main
conversation and only the conclusion brought back. This project doesn't need one yet, but a good
future candidate exists: once real categorisation rules and a backfilled transaction history are in
place (`docs/next-steps.md` steps 5–6), a **categorisation-quality auditor** subagent could run over
thousands of transactions, checking rule coverage and flagging systematic misclassifications, and
report back a compact findings list — exactly the shape of task where isolating the noisy work pays
off. Not built now; noted here so it's not reinvented from scratch when the time comes.

## 4. The pipeline, stage by stage

| Stage | Mechanism |
|---|---|
| Brainstorm | Plain conversation — ask questions, don't assume, before scoping anything |
| Plan | Plan Mode — auto-triggers for non-trivial/multi-file/ambiguous work; explores the code, proposes an approach, waits for approval |
| Design | Conversation + `docs/product-requirements.md` as the living source of truth — check it before inventing a new decision |
| Code | Default implementation, with `tdd-workflow` auto-triggering for `backend/`/`ingestion/`/`categorisation/` changes |
| Review | `/code-review` on the resulting diff |
| Test | `pytest`, plus the `run` skill for anything UI- or endpoint-visible |
| Deploy | Out of scope for MVP (local-only, NFR-1); Phase 2 concern |

The `/feature <description>` command (`.claude/commands/feature.md`) stitches all seven stages into
one entry point specific to this project, so you don't have to remember the sequence — it's a
concrete, readable example of what a slash command actually is (a stored prompt, not code).

## 5. Worked example

Request: *"Add a `GET /transactions/{id}` endpoint that returns a single transaction."*

1. **Brainstorm** — request is unambiguous; no clarification needed.
2. **Plan** — small, single-file change with a clear existing pattern (`backend/api.py`); Plan Mode
   may reasonably be skipped for something this contained, or used briefly to confirm the 404
   behaviour.
3. **Design** — check `docs/product-requirements.md` FR-11–FR-15 for any relevant constraint on
   transaction shape; none beyond what's already modeled.
4. **Code** — `tdd-workflow` triggers (touches `backend/`): add a test in `tests/` asserting
   `200` + correct fields for a known id and `404` for an unknown one; run `pytest`, confirm it
   fails; add the minimal FastAPI route; run `pytest`, confirm it passes.
5. **Review** — `/code-review` on the diff.
6. **Test** — `pytest` green; start the backend (`run` skill) and hit `/docs` to confirm the route
   behaves as expected interactively.
7. **Deploy** — not applicable (local-only MVP).

## 6. Notes on verification

`CLAUDE.md`, project-scoped skills (`.claude/skills/`), and project-scoped commands
(`.claude/commands/`) are discovered once, at session start. If you've just added or edited one of
these, it won't take effect in the *current* conversation — start a new Claude Code session in this
repo to confirm `/feature` is listed and `tdd-workflow` shows up as an available skill.
