## AI Personal Budgeting and Expense Categorisation System

A minimal but production-quality MVP for importing bank transactions from CSV, automatically categorising expenses, and visualising spending in a simple dashboard.

### Features

- **CSV Import**: Upload bank transactions as CSV via FastAPI.
- **Database Storage**: Transactions are stored in a local SQLite database using SQLAlchemy ORM.
- **Automatic Categorisation**:
  - Extracts merchant names from transaction descriptions.
  - Applies rule-based mapping to categories (e.g. Uber → Transport).
- **Dashboard** (Streamlit):
  - Total spending and income metrics.
  - Spending by category (bar chart).
  - Filterable transaction table.

---

### Tech Stack

- **Language**: Python 3.11
- **Backend**: FastAPI
- **Database**: SQLite + SQLAlchemy ORM
- **Frontend**: Streamlit
- **Data Processing**: Pandas

---

### Project Structure

```text
ai-budgeting-system/
  backend/
    models.py
    database.py
    api.py
  ingestion/
    csv_importer.py
  categorisation/
    merchant_parser.py
    categoriser.py
  frontend/
    dashboard.py
  tests/
    test_importer.py
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

3. **Install dependencies**

   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. (Optional) **Run tests**

   ```bash
   pip install pytest
   pytest
   ```

---

### Running the Backend (FastAPI)

From the project root (`ai-budgeting-system`):

```bash
uvicorn backend.api:app --reload
```

The API will be available at:

- `http://127.0.0.1:8000`
- Interactive docs: `http://127.0.0.1:8000/docs`

#### Endpoints

- **POST `/upload-transactions`**

  - Content-Type: `multipart/form-data`
  - Field name: `file` (CSV file)
  - Example CSV format:

    ```csv
    Date,Description,Amount
    2026-01-05,UBER TRIP,-22.40
    2026-01-06,WOOLWORTHS,-85.20
    2026-01-08,NETFLIX,-15.99
    ```

- **GET `/transactions`**

  - Returns all stored transactions.

- **GET `/summary`**

  - Returns spending summarised by category.

The backend automatically creates the `finance.db` SQLite database in the project root on first run.

---

### Running the Dashboard (Streamlit)

From the project root (`ai-budgeting-system`):

```bash
streamlit run frontend/dashboard.py
```

The dashboard will open in your browser (typically `http://localhost:8501`).

> **Note:** The dashboard reads directly from the `finance.db` SQLite file. Make sure:
> - You run Streamlit from the project root so the relative DB path matches.
> - You have imported some CSV transactions via the FastAPI backend first.

---

### Usage Flow

1. **Start the backend**

   ```bash
   uvicorn backend.api:app --reload
   ```

2. **Import transactions**

   - Open `http://127.0.0.1:8000/docs`.
   - Use the `/upload-transactions` endpoint.
   - Upload a CSV file with columns: `Date`, `Description`, `Amount`.

3. **Start the dashboard**

   ```bash
   streamlit run frontend/dashboard.py
   ```

4. **Explore spending**

   - View total spending, income, and net cash flow.
   - See spending by category as a bar chart.
   - Browse and filter individual transactions.

---

### Categorisation Rules

- **Merchant Extraction** (`categorisation/merchant_parser.py`)

  Examples:

  - `"UBER TRIP"` → `Uber`
  - `"WOOLWORTHS 3345"` → `Woolworths`
  - `"NETFLIX.COM"` → `Netflix`
  - Unknown or unrecognised patterns → `Unknown`

- **Expense Categorisation** (`categorisation/categoriser.py`)

  | Merchant    | Category       |
  | ----------- | -------------- |
  | Uber        | Transport      |
  | Woolworths  | Groceries      |
  | Netflix     | Entertainment  |
  | Amazon      | Shopping       |
  | (fallback)  | Other          |

---

### Notes

- Amounts are stored as floats; negative values represent debits (spending), positive values represent credits.
- This MVP is intentionally simple but structured for extension.

