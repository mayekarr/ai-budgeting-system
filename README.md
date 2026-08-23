## AI Personal Budgeting and Expense Categorisation System

A personal tool that ingests real bank statements, categorises transactions using rule-based
matching with a Claude API fallback, detects inter-account transfers and refunds, and (once later
build increments land) presents everything in a dashboard.

Full requirements/design live in `docs/` — see `CLAUDE.md` for where to start. This README covers
setup and what's runnable today.

### Features (build increment 1 — J1, "upload a statement")

- **Statement import**: upload a NAB-style bank statement CSV/xlsx via FastAPI (Macquarie-style and
  headerless-CommBank-style formats are a fast-follow, not yet supported).
- **Account resolution**: maps a statement's raw account identifier to one of the user's `Account`
  records via `AccountAlias`, auto-creating and flagging unrecognised ones.
- **Categorisation**: rule-based matching (seeded from real historical data) first, falling back to
  Claude API (Haiku 4.5) for anything unmatched — low-confidence results are flagged for review, not
  silently guessed.
- **Transfer/refund detection**: Tier-1 signal-based matching links inter-account transfers into a
  `TransferGroup`; refunds are tagged, with a scoped exception routing ATO tax refunds to `Income`.
- **De-duplication**: re-uploading an overlapping statement never creates duplicate rows.

**Not yet built**: the dashboard (`frontend/dashboard.py` predates this schema and won't run against
it until build increment 2 rebuilds it — see `docs/next-steps.md` step 6), category corrections,
the needs-review queue UI, the investment/asset view, and historical backfill.

---

### Tech Stack

- **Language**: Python 3.11
- **Backend**: FastAPI
- **Database**: SQLite + SQLAlchemy ORM
- **Categorisation fallback**: Claude API (Anthropic), model `claude-haiku-4-5-20251001`
- **Frontend** (not yet rebuilt against the current schema): Streamlit
- **Data Processing**: Pandas
- **Tests**: pytest, tests-first per the `tdd-workflow` skill

---

### Project Structure

```text
ai-budgeting-system/
  backend/
    models.py          # Account, AccountAlias, Transaction, TransferGroup, CategorisationRule
    database.py         # session management, de-duped persistence
    api.py               # FastAPI app: /transactions/upload, /transactions
  ingestion/
    nab_format.py        # NAB-style statement parser
    account_resolution.py
  categorisation/
    taxonomy.py           # the 16-category merged taxonomy
    rules.py               # rule matching
    claude_fallback.py      # Claude API fallback for unmatched merchants
    seed_rules.py             # starter rules from real historical data
  transfers/
    detection.py             # Tier-1 transfer signal matching + TransferGroup linking
    refunds.py                # is_refund detection, incl. the ATO tax-refund exception
  frontend/
    dashboard.py               # predates the current schema — not runnable yet
  tests/
  docs/                          # requirements, design docs, diagrams
  requirements.txt
  README.md
```

---

### Setup & Installation

1. **Navigate to the project folder**

   ```bash
   cd "c:\Users\rohan_ow776hq\OneDrive\Documents\Rohan stuff\Tech Projects and Learnings\Tech_workspace\ai-budgeting-system"
   ```

2. **Create and activate a virtual environment (recommended)**

   ```bash
   python -m venv .venv
   # Windows (PowerShell)
   .venv\Scripts\Activate.ps1
   # or cmd
   .venv\Scripts\activate.bat
   ```

3. **Install dependencies** (includes `pytest`/`httpx`/`openpyxl`/`anthropic` — all required to run
   the app and its test suite, not optional extras)

   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. **Set your Claude API key** (only needed for the real fallback path — the test suite mocks it)

   ```bash
   setx ANTHROPIC_API_KEY "sk-ant-..."   # Windows
   # or: export ANTHROPIC_API_KEY="sk-ant-..."
   ```

5. **Run tests**

   ```bash
   pytest
   ```

---

### Running the Backend (FastAPI)

From the project root:

```bash
uvicorn backend.api:app --reload
```

- API: `http://127.0.0.1:8000`
- Interactive docs: `http://127.0.0.1:8000/docs`

The backend creates `finance.db` (SQLite) and seeds starter categorisation rules on first run.

#### Endpoints

- **POST `/transactions/upload`**

  - Content-Type: `multipart/form-data`, field name: `file` — a NAB-style statement (CSV or xlsx)
  - Real column layout expected:

    ```csv
    Date,Amount,Account Number,Transaction Type,Transaction Details,Balance,Category,Merchant Name,Processed On
    2026-08-08,-38.66,Card ending 2957,PURCHASE AUTHORISATION,HILLS MEATS PTY LTDHILLS Forest Hill 036,-4131.90,Services,Hills Meats,
    ```

    (`Category`/`Merchant Name` are the bank's own values — read as a detection signal only, never
    trusted as the output category; see `docs/product-requirements.md` §4.1.)

- **GET `/transactions`**

  - Filters: `date_from`, `date_to`, `account_id`, `category`, `type`, `needs_review`.

---

### Notes

- Amounts are signed floats; negative = debit/spend, positive = credit.
- Every design decision behind this build is traceable to `docs/design-journeys.md`,
  `docs/design-data-model-api.md`, and `docs/design-logic-and-ux.md` — read those before extending
  this code, not just this README.
