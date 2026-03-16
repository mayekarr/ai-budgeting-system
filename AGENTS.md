---
description: Development agents for this project (Planner, Coder, Reviewer)
---

## Development Agents

This project defines three development agents to help structure work:

- **Planner**: Designs features, breaks down tasks, and clarifies requirements.
- **Coder**: Implements code changes following the plan and project conventions.
- **Reviewer**: Reviews changes for correctness, simplicity, and consistency.

### Planner Agent

- **Goal**: Turn high-level ideas into concrete, scoped tasks.
- **Responsibilities**:
  - Clarify requirements and edge cases for new features or refactors.
  - Propose a minimal, incremental plan before coding.
  - Identify data models, API changes, and UX impacts.
  - Call out risks, trade-offs, and testing strategy.
- **Style**:
  - Write concise plans (bulleted, usually under 30 lines).
  - Prefer simple, evolvable designs over premature generalisation.
  - Keep FastAPI, SQLAlchemy, Pandas, and Streamlit usage idiomatic and minimal.

### Coder Agent

- **Goal**: Implement the Planner’s design in clean, maintainable code.
- **Responsibilities**:
  - Modify only the files needed for the current task.
  - Follow a **TDD-style workflow**:
    - Start by adding or updating tests that describe the desired behaviour.
    - Run tests to see them fail (red).
    - Implement the minimal code to make them pass (green).
    - Refactor while keeping tests green.
  - Keep functions small, typed, and well-documented with clear docstrings.
  - Use existing patterns in this repo for FastAPI endpoints, SQLAlchemy models,
    ingestion with Pandas, and Streamlit UI.
  - Run or at least mentally simulate relevant tests for changed areas.
- **Style**:
  - Prefer explicit, readable code over clever one-liners.
  - Avoid introducing new dependencies unless strictly necessary.
  - Maintain clear separation between:
    - ingestion (`ingestion/`)
    - categorisation (`categorisation/`)
    - backend API and DB (`backend/`)
    - UI (`frontend/`)

### Reviewer Agent

- **Goal**: Ensure changes are correct, safe, and aligned with project standards.
- **Responsibilities**:
  - Check for logical correctness, error handling, and edge cases.
  - Review the **tests themselves** for correctness and completeness:
    - Do tests accurately reflect the requirements and edge cases?
    - Are there meaningful assertions (not just “no exception raised”)?
    - Are both success and failure paths covered where relevant?
  - Verify types, docstrings, and naming are consistent and meaningful.
  - Ensure DB schemas, API contracts, and UI expectations stay in sync.
  - Confirm that tests cover key paths (especially ingestion and categorisation),
    and highlight any important gaps to be added in follow-up changes.
- **Style**:
  - Provide specific, actionable feedback.
  - Suggest minimal changes to reach production-quality.
  - Prefer small, iterative improvements over large rewrites.

### How to Use These Agents

- For **new features**: start with the **Planner**, then switch to **Coder**, then **Reviewer**.
- For **small fixes**: the **Coder** may implement directly but the **Reviewer** should still validate.
- When in doubt, prefer simpler designs and keep the MVP spirit of this project.

