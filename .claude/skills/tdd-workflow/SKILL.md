---
name: tdd-workflow
description: >-
  Tests-first (TDD) workflow for this project's backend, ingestion, categorisation,
  and dashboard interaction code. Use whenever implementing or changing behaviour in
  backend/ (FastAPI, SQLAlchemy models/DB), ingestion/ (CSV parsing),
  categorisation/ (merchant parsing, category rules), or frontend/ interaction logic
  (Streamlit widget/state behaviour, via AppTest) — or their tests/.
---

# TDD for Backend, Ingestion, Categorisation & Dashboard-Logic Changes

This skill governs how to work on this project's data-handling core, plus the dashboard's
*interaction logic*:

- FastAPI API layer (`backend/api.py`)
- Database models and access (`backend/models.py`, `backend/database.py`)
- Ingestion logic (`ingestion/`)
- Categorisation logic (`categorisation/`)
- Streamlit **interaction logic** in `frontend/` — filters producing the right result set, a
  category click navigating to the right drill-in, a confirm/reject action in the review queue
  calling the right endpoint and updating state — tested via `streamlit.testing.v1.AppTest`
  (scripts widget interactions and asserts on session state / rendered output, no browser needed)
- Their tests (`tests/`)

**Visual/layout** in `frontend/` (does the chart look right, is spacing sane, does it read well) is
explicitly **not** this skill's job — that's verified by running the app and looking at it (see the
`run` skill). A test asserting on pixel layout or chart appearance is testing the wrong thing here;
if the change is purely visual, skip this skill and use `run` instead.

## When to Use This Skill

Apply this workflow when the user asks to implement or change behaviour in any of the paths above,
mentions TDD / tests-first / test coverage, or is adding/changing dashboard interaction logic
(filters, navigation, actions that call the API) as opposed to pure visual polish.

## Workflow

1. **Understand the change** — identify which layer is affected (API, models/DB, ingestion,
   categorisation, or dashboard interaction logic) and which existing tests already cover that area.

2. **Design tests first (red)** — add or update tests in `tests/` that describe the desired
   behaviour before touching implementation code.
   - Prefer small, focused tests with clear names.
   - Cover the typical success case, at least one meaningful edge case, and relevant
     failure/validation paths.
   - Assertions must be meaningful (check actual values/shape/status codes/session state — not just
     "no exception raised").
   - For dashboard interaction logic, use `AppTest.from_file(...)`, simulate the widget interaction
     (`.selectbox("...").select(...)`, `.button("...").click()`, etc.), call `.run()`, then assert on
     `.session_state` or the rendered elements — not on layout/appearance.

3. **Run the tests and confirm they fail** — actually run `pytest` (don't just simulate mentally)
   and confirm the new/changed tests fail for the expected reason (missing endpoint, wrong response
   shape, missing validation, missing widget/handler, etc.) before writing implementation code.

4. **Implement the minimal code to pass (green)** — modify only the files needed. Keep the existing
   separation of concerns:
   - FastAPI endpoints/schemas → `backend/api.py`
   - ORM models → `backend/models.py`
   - DB helpers → `backend/database.py`
   - CSV parsing (Pandas) → `ingestion/csv_importer.py`
   - Rule-based categorisation → `categorisation/`
   - Streamlit pages/interaction logic → `frontend/pages/`
   - Run `pytest` again and confirm the target tests now pass.

5. **Refactor while green** — if the implementation can be simplified or clarified, do it now, then
   re-run `pytest` to confirm behaviour didn't change.

6. **Check test completeness** — before finishing, confirm the tests actually match the
   requirement (cross-check against `docs/product-requirements.md` if the change touches a
   numbered FR), cover nominal + edge paths, and call out any gap explicitly rather than silently
   leaving it uncovered.

## Style

- Type hints where practical; short docstrings only where intent isn't obvious from the code.
- Simple, explicit control flow over clever one-liners.
- Don't introduce new dependencies unless the task genuinely requires one.

## Examples

### Example 1: New FastAPI endpoint

Request: "Add a `/transactions/{id}` endpoint that returns a single transaction."

1. Add a test (`tests/test_api.py` or similar) that creates a sample transaction in the DB, calls
   `GET /transactions/{id}`, and asserts on status code and response body fields — including a 404
   case for an unknown id.
2. Run `pytest`, confirm it fails (no such route yet).
3. Add the minimal FastAPI path operation in `backend/api.py`, with DB-session dependency injection
   and 404 handling.
4. Run `pytest`, confirm it passes.
5. Refactor only if a shared "fetch transaction or 404" helper would remove duplication.

### Example 2: Dashboard interaction logic (AppTest)

Request: "In the Needs-Review page, confirming a suggested transfer match should write
`transfer_group_id` and remove the item from the queue."

1. Add a test (`tests/test_frontend_review_queue.py` or similar):
   ```python
   from streamlit.testing.v1 import AppTest

   def test_confirm_transfer_match_removes_item_from_queue():
       at = AppTest.from_file("frontend/pages/needs_review.py")
       at.run()
       at.button(key="confirm_transfer_1").click().run()
       assert at.session_state["queue_ids"] == []  # item resolved, no longer listed
   ```
   Assert on `session_state`/rendered output (what the user's next view shows), not on pixel layout.
2. Run `pytest`, confirm it fails (no such button/handler yet).
3. Implement the minimal page logic in `frontend/pages/needs_review.py`: the confirm button calls
   `PATCH /transactions/{id}` with `transfer_group_id` set, then removes the resolved item from the
   displayed queue.
4. Run `pytest`, confirm it passes.
5. Refactor only if duplicated confirm/reject handling across categorisation and transfer items
   would benefit from a shared helper.
6. Visual check (chart readability, spacing, does the queue look right) is separate — use the `run`
   skill to actually look at it; this test doesn't cover that and shouldn't try to.
