---
description: Run a feature request through this project's full brainstorm-to-deploy pipeline
---

Feature request: $ARGUMENTS

Work through this project's agentic development workflow (full explanation in
`docs/agentic-workflow.md`) for the feature request above:

1. **Brainstorm / clarify** — if the request is ambiguous or has several reasonable
   interpretations, ask before assuming.
2. **Plan** — for anything beyond a trivial fix, enter plan mode: explore the relevant code,
   design an approach, and get it approved before writing code.
3. **Design** — note data model, API, and UX impacts explicitly; check whether
   `docs/product-requirements.md` already has a relevant decision before inventing a new one.
4. **Code** — implement the plan. The `tdd-workflow` skill will auto-trigger for anything under
   `backend/`, `ingestion/`, or `categorisation/`; for `frontend/`-only changes, verify by running
   the app instead of writing tests.
5. **Review** — run `/code-review` on the resulting diff before calling the change done.
6. **Test** — run `pytest`; for anything UI- or endpoint-visible, actually start the backend/
   dashboard and exercise it (see the `run` skill) rather than relying on unit tests alone.
7. **Deploy** — out of scope for the MVP (local-only, see NFR-1 in the requirements doc). If this
   feature touches deployment, flag it as a Phase 2 concern rather than acting on it.
