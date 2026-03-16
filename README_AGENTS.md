## Development Agents Guide

This document explains how to use the project’s **development agents** in two ways:

- Via **Cursor** using `AGENTS.md`
- Programmatically using `tools/agents.py`

Agents:

- **Planner**
- **Coder** (TDD-focused)
- **Reviewer** (code + tests)

---

## 1. Using Agents in Cursor (AGENTS.md)

The file `AGENTS.md` defines the behaviour of three roles:

- **Planner**: designs features and breaks them into concrete tasks.
- **Coder**: implements changes using a TDD-style workflow.
- **Reviewer**: reviews code and tests for correctness, safety, and completeness.

You use them by **framing your prompts** in Cursor.

### 1.1 Planner examples

- **Plan a new feature**

  > Act as the **Planner Agent** (see `AGENTS.md`).  
  > I want to add a feature that lets users filter transactions by minimum and maximum amount in the Streamlit dashboard.  
  > Please:
  > - Give a 2–3 sentence summary.
  > - List numbered implementation tasks.
  > - Mention which files/modules each task will likely touch.

### 1.2 Coder (TDD) examples

Once you have a plan from the Planner:

- **Implement using TDD**

  > Act as the **Coder Agent** and follow TDD as described in `AGENTS.md`.  
  > Based on this plan:  
  > \<paste plan here\>  
  > 1. Propose or update tests first (file paths + test names).  
  > 2. Then show the minimal code changes needed to make those tests pass.  
  > 3. If helpful, propose small refactors while keeping behaviour intact.

### 1.3 Reviewer examples

After the Coder suggests changes:

- **Review code and tests**

  > Act as the **Reviewer Agent** (see `AGENTS.md`).  
  > Review the following changes for:
  > - correctness, error handling, and edge cases  
  > - clarity of types, docstrings, and naming  
  > - consistency between models, APIs, ingestion, categorisation, and Streamlit  
  > - the **correctness and completeness of tests**  
  > Here are the diffs/code:  
  > \<paste relevant diffs or code + tests\>

---

## 2. Using Agents Programmatically (tools/agents.py)

The module `tools/agents.py` codifies the same three agents in Python, using the OpenAI API.

> **Note:** You must set your OpenAI API key, for example:
>
> ```bash
> setx OPENAI_API_KEY "sk-..."   # Windows (PowerShell/cmd)
> # or
> export OPENAI_API_KEY="sk-..." # macOS/Linux
> ```

Install dependencies if you have not already:

```bash
pip install -r requirements.txt
```

### 2.1 Planner: `plan_feature`

```python
from tools.agents import plan_feature

feature = "Add amount range filters to the Streamlit dashboard."

plan_text = plan_feature(feature)
print(plan_text)
```

What it does:

- Calls the **Planner Agent**.
- Returns a short summary plus a numbered list of implementation tasks.
- Mentions which files/modules are likely to be touched.

### 2.2 Coder (TDD): `implement_feature_with_tdd`

Use the Planner’s output as input to the Coder:

```python
from tools.agents import plan_feature, implement_feature_with_tdd

feature = "Add amount range filters to the Streamlit dashboard."

plan_text = plan_feature(feature)
impl_text = implement_feature_with_tdd(plan_text)

print("=== PLAN ===")
print(plan_text)
print("\n=== IMPLEMENTATION (TDD) ===")
print(impl_text)
```

What it returns:

- A TDD-style breakdown:
  - which tests to add/update (file paths + test names)
  - test code snippets
  - implementation code snippets
  - optional refactor suggestions

You can then apply those changes manually (or with tooling) to the codebase.

### 2.3 Reviewer: `review_changes`

Pass either a diff or raw code + tests:

```python
from tools.agents import review_changes

diff_text = """
diff --git a/tests/test_importer.py b/tests/test_importer.py
...
"""

review_text = review_changes(diff_text)
print(review_text)
```

What it focuses on:

- Logical correctness and edge cases.
- Type hints, docstrings, naming.
- Consistency across backend, ingestion, categorisation, frontend.
- **Tests**:
  - whether they reflect requirements and edge cases
  - whether assertions are meaningful
  - which important cases are missing

---

## 3. Example End‑to‑End Script

You can glue the three agents together in a simple script, for example in `tools/run_agent_flow.py`:

```python
from tools.agents import plan_feature, implement_feature_with_tdd, review_changes


def run_agent_flow(feature_request: str) -> None:
    plan = plan_feature(feature_request)
    print("=== PLAN ===")
    print(plan)

    impl = implement_feature_with_tdd(plan)
    print("\n=== IMPLEMENTATION (TDD) ===")
    print(impl)

    review = review_changes(impl)
    print("\n=== REVIEW ===")
    print(review)


if __name__ == "__main__":
    run_agent_flow("Add amount range filters to the Streamlit dashboard.")
```

Run it with:

```bash
python -m tools.run_agent_flow
```

This is not required for normal development, but it shows how to orchestrate **Planner → Coder (TDD) → Reviewer** in a single flow.

---

## 4. When to Use Which Path

- Use **`AGENTS.md` + prompts in Cursor** when:
  - you’re working interactively on this repo
  - you want tight, conversational control of each step

- Use **`tools/agents.py`** when:
  - you want to call agents from scripts, CLIs, or CI
  - you need consistent, repeatable behaviour across runs

Both share the same intent: keep development structured, TDD‑friendly, and review‑oriented for this project.

