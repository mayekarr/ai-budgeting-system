from __future__ import annotations

"""
Programmatic interfaces for the project’s development agents:

- Planner
- Coder
- Reviewer

These functions are designed to mirror the behaviour described in `AGENTS.md`
so you can call them from scripts, CLIs, or other tools and get consistent
results with how you work inside Cursor.
"""

from dataclasses import dataclass
from typing import List

from openai import OpenAI


client = OpenAI()


@dataclass
class PlannedTask:
    """Structured representation of a single planned task."""

    number: int
    description: str


def _call_model(prompt: str, model: str = "gpt-4.1") -> str:
    """Low-level helper to call the OpenAI chat completion API."""
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content or ""


def plan_feature(feature_request: str, *, model: str = "gpt-4.1") -> str:
    """
    Planner Agent: turn a feature request into a concise, numbered implementation plan.

    Behaviour is aligned with the Planner description in `AGENTS.md`:
    - Clarify requirements and edge cases where useful.
    - Propose a minimal, incremental plan before coding.
    - Call out affected areas: ingestion, categorisation, backend, frontend.
    """
    prompt = f"""
You are the **Planner Agent** for the "AI Personal Budgeting and Expense Categorisation System".

Your job:
- Turn high-level ideas into concrete, scoped tasks.
- Prefer simple, incremental designs over premature generalisation.
- Keep plans concise and practical for this specific Python/FastAPI/SQLAlchemy/Pandas/Streamlit project.

Feature request:
{feature_request}

Return:
- A short summary (1–3 sentences).
- A numbered list of implementation tasks.
- For each task, mention which files or modules are likely to be touched.
"""
    return _call_model(prompt, model=model)


def implement_feature_with_tdd(
    feature_plan: str,
    *,
    model: str = "gpt-4.1",
) -> str:
    """
    Coder Agent: implement a feature using a TDD-style workflow.

    Behaviour is aligned with the Coder description in `AGENTS.md`:
    - Modify only the files needed for the current task.
    - Follow TDD:
      - Start by adding or updating tests that describe the desired behaviour.
      - Run tests to see them fail (red) conceptually.
      - Implement the minimal code to make them pass (green).
      - Refactor while keeping tests green.
    - Keep functions small, typed, and well-documented with clear docstrings.
    - Use existing patterns in this repo for FastAPI, SQLAlchemy, Pandas, and Streamlit.

    Note: This function returns **instructions and code suggestions**; it does not
    apply changes itself.
    """
    prompt = f"""
You are the **Coder Agent** for the "AI Personal Budgeting and Expense Categorisation System".

Follow a strict TDD-style workflow:
1. Propose or update tests FIRST that capture the required behaviour.
2. Indicate the expected failing state (red).
3. Propose minimal code changes to make tests pass (green).
4. Optionally, propose small refactors while keeping behaviour intact.

Context:
- Tech stack: Python 3.11, FastAPI, SQLAlchemy (SQLite), Pandas, Streamlit.
- Project structure: backend/, ingestion/, categorisation/, frontend/, tests/.
- Keep changes minimal and explicit; avoid new dependencies.

Feature plan (from Planner Agent):
{feature_plan}

Return:
- A brief outline of new/updated tests (file paths and test names).
- The test code snippets.
- The corresponding implementation code snippets (per file).
- Any small refactor suggestions.
"""
    return _call_model(prompt, model=model)


def review_changes(
    diff_or_description: str,
    *,
    model: str = "gpt-4.1",
) -> str:
    """
    Reviewer Agent: review code and tests for correctness, safety, and completeness.

    Behaviour is aligned with the Reviewer description in `AGENTS.md`:
    - Check for logical correctness, error handling, and edge cases.
    - Verify types, docstrings, and naming are consistent and meaningful.
    - Ensure DB schemas, API contracts, and UI expectations stay in sync.
    - Review tests for correctness and completeness:
      - Do tests reflect requirements and edge cases?
      - Are assertions meaningful?
      - Are both success and failure paths covered where relevant?
    - Highlight important test coverage gaps and suggest follow-ups.
    """
    prompt = f"""
You are the **Reviewer Agent** for the "AI Personal Budgeting and Expense Categorisation System".

Review the following changes (code, tests, or diff):
{diff_or_description}

Focus on:
- Logical correctness, error handling, and edge cases.
- Type hints, docstrings, and naming consistency.
- Alignment between models, FastAPI endpoints, ingestion logic, categorisation rules,
  and the Streamlit dashboard.
- Tests:
  - Do they accurately reflect the requirements?
  - Are assertions meaningful (beyond "no exception")?
  - Are success and failure paths covered where appropriate?
  - Are there any important missing cases you would add?

Return:
- A short summary of overall quality.
- A numbered list of concrete review comments (what to change and why).
- If applicable, improved code or test snippets for the most important issues.
"""
    return _call_model(prompt, model=model)


__all__ = [
    "PlannedTask",
    "plan_feature",
    "implement_feature_with_tdd",
    "review_changes",
]

