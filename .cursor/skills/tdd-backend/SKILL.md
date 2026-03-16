---
name: tdd-backend
description: >-
  Guides the agent to use a strict TDD workflow for backend changes in this
  project (FastAPI, SQLAlchemy, ingestion, categorisation). Use when adding or
  modifying backend features and you want tests written first, then minimal code
  to make them pass.
---

# TDD for Backend Changes

This skill helps the agent follow **Test-Driven Development (TDD)** when working
on this project's backend:

- FastAPI API layer (`backend/api.py`)
- Database models and access (`backend/models.py`, `backend/database.py`)
- Ingestion logic (`ingestion/`)
- Categorisation logic (`categorisation/`)
- Backend-focused tests (`tests/`)

It is designed to complement the **Coder** and **Reviewer** agents defined in
`AGENTS.md`.

## When to Use This Skill

The agent should apply this skill when:

- The user asks to implement or change backend behaviour (API endpoints,
  models, ingestion, categorisation, or DB).
- The user mentions TDD, tests-first, or wants strong test coverage.
- The user is modifying files under:
  - `backend/`
  - `ingestion/`
  - `categorisation/`
  - `tests/`

## TDD Workflow for This Project

When this skill is active, the agent should follow this workflow:

1. **Understand the Change**
   - Identify which part of the system is affected:
     - FastAPI endpoints (`backend/api.py`)
     - Models/DB (`backend/models.py`, `backend/database.py`)
     - Ingestion (`ingestion/csv_importer.py`)
     - Categorisation (`categorisation/*.py`)
     - Tests (`tests/*.py`)

2. **Design Tests First (Red)**
   - Create or update tests in `tests/` that describe the desired behaviour.
   - Prefer small, focused tests with clear names.
   - Cover:
     - Typical success cases
     - Important edge cases
     - Relevant failure/validation paths where appropriate
   - Make sure tests have **meaningful assertions**, not just "no exception".

3. **Run / Simulate Tests and Expect Failure**
   - Assume the user will run `pytest` (or equivalent).
   - Clearly state which tests are expected to fail and **why** (e.g. missing
     endpoint, wrong response shape, missing validation).

4. **Implement Minimal Code (Green)**
   - Modify only the necessary files to make those tests pass.
   - Keep changes minimal and explicit.
   - Maintain existing patterns:
     - FastAPI endpoints and schemas in `backend/api.py`
     - ORM models in `backend/models.py`
     - DB helpers in `backend/database.py`
     - CSV parsing with pandas in `ingestion/csv_importer.py`
     - Rule-based categorisation in `categorisation/`

5. **Refactor While Keeping Tests Green**
   - If the implementation can be simplified or clarified, propose refactors.
   - Ensure behaviour stays the same and tests remain passing.

6. **Review Tests for Completeness**
   - Double-check that tests:
     - Match the feature requirements.
     - Cover both nominal and edge paths.
     - Use clear naming and assertions.
   - If there are gaps, explicitly call them out and, if appropriate, propose
     additional tests.

## Instructions for the Agent

When this skill is relevant:

1. **Announce the TDD approach briefly** to the user (one short sentence).
2. **Show tests first**, then implementation.
3. For each proposed change, clearly separate:
   - Test changes
   - Implementation changes
   - Optional refactors
4. Use the project’s existing style:
   - Type hints where practical.
   - Clear docstrings describing intent and behaviour.
   - Simple, explicit control flow over clever tricks.

## Examples

### Example 1: New FastAPI Endpoint

User request:

> Add a `/transactions/{id}` endpoint that returns a single transaction.

Agent (high level behaviour with this skill):

1. Propose a new test in `tests/test_importer.py` **or** a new `tests/test_api.py`
   that:
   - Creates a sample transaction in the DB.
   - Calls `/transactions/{id}`.
   - Asserts on status code and response body fields.
2. Show the test code.
3. Show minimal changes in `backend/api.py`:
   - New path operation.
   - Dependency-injected DB session.
   - 404 handling for unknown id.
4. Optionally suggest a small refactor if needed (e.g. helper function for
   fetching a transaction).

### Example 2: Ingestion Edge Case

User request:

> Make the CSV importer skip rows with invalid dates instead of failing.

Agent behaviour:

1. Add tests in `tests/test_importer.py`:
   - One CSV row with a valid date and one with an invalid date.
   - Assert that only the valid row is returned.
2. Adjust `ingestion/csv_importer.py` to:
   - Attempt to parse dates row by row or handle parsing errors gracefully.
   - Skip rows with invalid dates, possibly logging or commenting on the
     behaviour in docstrings.

These examples are illustrative; the exact file and test names can vary, but the
**tests-first, then minimal implementation** pattern should always be applied.

