# Demo-Ready Feature List (J1–J5)

Status: Draft
Last updated: 2026-09-25
Purpose: a walkthrough of what's actually demoable today, in demo language — what to upload/click,
what it shows, what it proves — not a restatement of the technical changelog in `docs/next-steps.md`.
Built from a real upload run through the live app (backend + dashboard), using the real sample
statement files in `transaction-files/`, not synthetic data.

## What's built vs. what's coming

**Built and demoable today (J1–J5):**

| Journey | What it does |
|---|---|
| J1 — Upload a statement | Parse a real NAB-style bank export, resolve the account, categorise (rule-based first, Claude API fallback second), detect inter-account transfers and refunds, de-duplicate re-uploads. |
| J2 + J3 — View & drill into spending | Overview page: KPI row + spend-by-category chart. Drill-in: the transactions behind any category, with the same transfer/refund exclusions applied. |
| J4 — Correct a miscategorisation | Fix a category/subcategory from Drill-in; the correction is remembered as a rule for future transactions from the same merchant (not retroactive). |
| J5 — Needs-review queue | One combined, reason-filterable queue for anything uncertain: an unresolved account, an ambiguous refund, or a transfer match that isn't a sure thing — each with a one-click resolution. |

**Not built yet — coming next, in this order (see `docs/next-steps.md` for the live-tracked list):**

| Journey | What it'll add |
|---|---|
| J6 — Portfolio/asset view | An `Asset` entity (real estate, shares) and a Portfolio page — investments as a first-class view, not just cash flow. |
| J7 — Tax refund (YoY) | A filter on top of J2's summary endpoint plus a chip on Overview, for "how much tax refund, year on year." |
| J8 — Historical backfill | One-time import of the 13-year, ~14,300-row manual `Expense Log` (2012–2025), remapped into the current taxonomy. Deliberately last — needs the live pipeline proven on real imports first. |

Also not built: forecasting and cloud deployment (Phase 2, out of scope for now).

## How to run this demo, step by step

No API key is required — as of 2026-09-25, `categorisation/claude_fallback.py` degrades gracefully
with no `ANTHROPIC_API_KEY` configured (any unmatched merchant routes straight to the needs-review
queue instead of crashing the upload). Rohan has decided not to purchase separate
console.anthropic.com API billing (Claude Pro is a different product/billing), so this is the
project's standing operating mode, not a temporary gap — plain `uvicorn backend.api:app` just works.

1. *(Optional)* **Get a real Claude API key** only if you specifically want to see a live LLM
   categorisation in the J1 walkthrough below, instead of everything unmatched landing in
   `Miscellaneous`/needs-review. Go to console.anthropic.com, sign in, add billing, Settings → API
   Keys → Create Key, then `setx ANTHROPIC_API_KEY "sk-ant-..."` and open a fresh terminal (`setx`
   doesn't affect an already-open shell). Skip this entirely for the normal demo.
2. **Reset the database for a clean run.** `finance.db` (project root) may already contain data from
   a prior session (see the note in J2/J3 below about its Overview totals). Delete `finance.db` if
   it exists; the backend recreates the schema and re-seeds the 123 starter categorisation rules on
   first run.
3. **Start the backend** (from the project root, with the venv activated):
   ```powershell
   .venv\Scripts\Activate.ps1
   uvicorn backend.api:app --reload
   ```
   Confirm it's up at `http://127.0.0.1:8000/docs`.
4. **Start the dashboard**, in a second terminal:
   ```powershell
   .venv\Scripts\Activate.ps1
   streamlit run frontend/dashboard.py
   ```
   It opens at `http://localhost:8501`.
5. **Upload the sample statements**, in this order, via the API — the dashboard has no upload
   control yet. Easiest is the interactive docs at `http://127.0.0.1:8000/docs` →
   `POST /transactions/upload` → "Try it out"; or from a terminal in the project root:
   ```powershell
   curl.exe -F "file=@transaction-files/BankTransactions - CC.xlsx" http://127.0.0.1:8000/transactions/upload
   ```
   Files: `BankTransactions - CC.xlsx`, then `- RC.xlsx`, then `- AC.xlsx`, then `- JC.xlsx` — all
   in `transaction-files/`. The dashboard caches reads for up to 30 seconds, so give it that long
   (or restart it) before new uploads appear. **Skip MAC, MACACC, and NBA** — a different
   export shape the parser doesn't support yet (see "What's not in this demo" below). Uploading
   CC first matters: the seed rules were derived from CC's own historical data, so it has the
   highest rule-match rate and gives the cleanest "instant categorisation" moment before you get to
   the unmatched rows.
6. **Walk the journeys in order**, using the concrete real examples in the sections below as your
   talking points:
   - J1: point out a clean rule match, then an unmatched row landing in needs-review (or a live LLM
     result if you set up a key in step 1), then a transfer pair, then a refund.
   - J2/J3: Overview → click a category bar → Drill-in.
   - J4: correct one miscategorised row live, then show the *other* occurrence of the same merchant
     elsewhere in the data didn't change (the "not retroactive" moment).
   - J5: open the Needs-Review queue, filter by reason, resolve one live (the Arvan/Nando's
     near-match transfer flag below is a good one — it's genuinely ambiguous, not staged).
7. **Shut down** when done: `Ctrl+C` in both terminals.

## J1 — Upload a statement

**Do**: Upload `transaction-files/BankTransactions - CC.xlsx`.

**Shows**: 347 rows imported in one shot, `needs_review_count` in the response.

**Proves**: the parser handles a real, messy NAB-style export (store numbers, suffixes, blank
optional fields) without manual cleanup first.

### Clean rule-matched categorisation (no review needed)

Real rows from the CC upload, categorised instantly from the 123 seed rules with no API call:

| Description | Amount | Category | Subcategory |
|---|---|---|---|
| `WOOLWORTHS/GLEBE ST & LOOFOREST HILL 036` | -$142.64 | Groceries | — |
| `MYKI PAYMENTS MELBOURNE` | -$50.00 | Transport | Public Transport |
| `Hilton Melbourne LQS Melbourne` | -$224.24 | Travel & Holidays | Accommodation |

**Demo line**: "That's real merchant text from a real statement — no cleanup, instantly bucketed."

### Unmatched merchants → needs-review (the normal path, no API key)

Any CC row a rule doesn't cover — e.g. `435 BOURKE STREET CAFE MELBOURNE`, `ALLIANZ AUSTRALIA
INSUR SYDNEY` — falls through to the Claude Haiku 4.5 fallback. Without a key configured (this
project's standing setup, decided 2026-09-25), that call degrades gracefully instead of erroring:
the row lands as `Miscellaneous`/`needs_review=True`/`needs_review_reason=llm_unavailable` — kept
distinct from a genuine low-confidence LLM result (`low_confidence_category`) precisely because
this reason means *every* future upload hits the same wall, not just this one merchant. This is
what feeds J5's needs-review queue below. *If* you set up a key in step 1 of the run guide, the
same row would instead get a confident LLM result promoted straight into a new rule (so the *next*
transaction from that merchant skips the API call entirely — the NFR-4 cost-control story) — a
nice contrast to show, but not required for the demo.

### Transfer detection (real, auto-linked pairs)

From the AC + JC uploads, two real self-transfers auto-linked into `TransferGroup`s and excluded
from Income/Expense totals:

- `ONLINE J6657692287 Trans salary MAYEKAR A` — **-$5,000.00** on AC / **+$5,000.00** on JC (same
  day, same reference number — a salary sweep between the user's own accounts).
- `ONLINE Q6957221963 AC to JC MAYEKAR A` — **-$317.55** / **+$317.55**, same pattern.
- Across JC and CC: `4530307001277128 NAB CARD AUTOPAY MRS ANILA R...` (-$8,050.20 on JC) linked to
  `DIRECT DEBIT PAYMENT` (+$8,050.20 on CC) — a credit card autopay, correctly excluded from spend
  rollups rather than double-counted as both a JC expense and a CC "income."

**Demo line**: "Money moving between the user's own accounts never inflates income or spend — even
across three different account types (everyday, savings, credit card)."

### Refund detection (nets against the category, not counted as income)

`SPOTLIGHT BOX HILL BOX HILL SOUT` — a **+$10.00** credit, tagged `is_refund=True`, category
`Shopping`. It nets against Shopping spend in `GET /summary` instead of inflating `total_income`.

**Demo line**: "A refund isn't income — it just gives money back to the category it came from."

## J2 + J3 — View & drill into spending

**Do**: Open the Overview page, then click into a category (e.g. Groceries) to drill in.

**Shows**: KPI row + spend-by-category chart from `GET /summary`; the transaction list behind any
bar via `GET /transactions?category=...`.

**Proves**: the same netting/exclusion rules from J1 (refunds netted, transfers excluded) hold at
the aggregate level, not just per-row — and drilling into a category shows exactly the transactions
that produced that bar, no more, no less (Transfer-typed and superseded rows excluded from both).

**Earnings by Source (added 2026-09-25)**: Overview also shows an income breakdown chart —
`Salary` and `Dividends & Distributions` as separate bars, summing the real uploaded data to
**$47,797.95** and **$787.95**. This exists as a second, separate chart from Spending by Category
rather than folded into it: every income row shares `category=Income` (by design — see J1's netting
note above), so `subcategory` is the meaningful breakdown axis for earnings, a different grouping
than spend's category axis. "Income" is also now an option in the same "Drill into a category"
selector below the charts — click it to see every income row, subcategory visible per row.

**Note**: this relies on `categorisation/seed_rules.py` having real Income-category coverage
(`SALARY/WAGES`, `NAB INTERIM DIV`, `EQUATEPLUS DIVIDENDS` — added 2026-09-25, after `total_income`
was found showing $0 live). If you're on an older `finance.db` from before that fix, reset it (run
guide step 2) and re-upload.

## J4 — Correct a miscategorisation

**Do**: On Category Drill-in, find `435 BOURKE STREET CAFE MELBOURNE` (-$4.50, 2026-08-06) — a real
rule-unmatched row, currently `Miscellaneous`/`needs_review_reason=llm_unavailable` (this project's
standing no-API-key setup; with a real key configured this would instead be a genuine LLM result —
either way, the correction flow itself is identical). Correct it to `Cafes & Restaurants` /
`Cafes & Coffee` and save.

**Shows** (verified live via `PATCH /transactions/{id}`): the row updates instantly — `needs_review`
clears, confidence jumps to 1.0 — and the drill-in table refreshes without a manual page reload.

**Proves — and this is the subtle part worth calling out live**: the *same merchant* appears twice
more in this upload (`435 BOURKE STREET CAFE MELBOURNE`, -$9.00 on 2026-07-24 and -$4.25 on
2026-07-23) and **neither one changes** when you correct the first. The correction writes a rule
that applies going forward, not retroactively — a deliberate design choice (FR-9's wording), not a
bug. Good moment to explain *why* in the demo: retroactively rewriting history on every correction
would make past reports change underneath the user without them asking.

## J5 — Needs-review queue

**Do**: Open the Needs-Review page, filter by reason.

**Shows** (real examples pulled from a live run — these needs-review flags are produced by account
resolution, refund ambiguity, and transfer-matching logic, none of which touch the Claude API, so
they show up whether or not you have a real key set):

- **`llm_unavailable`** (added 2026-09-25) — the reason you'll see most in this demo, given the
  no-API-key decision above. Any rule-unmatched merchant lands here — e.g.
  `ALLIANZ AUSTRALIA INSUR SYDNEY` — distinct from `low_confidence_category` (a genuine model
  judgement that happened to be uncertain) precisely because this one means *every* future upload
  hits the same wall until a key is configured, not just this one merchant. Resolved the same way:
  pick a category and save. Real coverage keeps closing this gap on the rule side instead — Income
  (`SALARY/WAGES`, dividend patterns) and `Loans & Finance` (`LOAN REPAYMENT`) rules were added
  2026-09-25 after showing up here live; `LOAN REPAYMENT TO A/C 703206283 MAYEKAR A` is a good
  concrete "before" example if you want to demo a fresh rule gap being found and closed.
  **A genuinely unresolvable case, not a bug**: several `-$5,000 "Trans salary"` debits have no
  matching credit anywhere in the uploaded data (their counterpart is almost certainly on MAC/
  MACACC/NBA — the unsupported export formats) — correctly stuck here rather than guessed at.
  Good moment to contrast with the next bullet's genuinely-resolved transfer pairs.
- **`unrecognised_account`** — `HILLS MEATS PTY LTDHILLS Forest Hill 036` (-$38.66) — its statement
  account identifier couldn't be confidently resolved to a known account, shown for visibility (no
  resolution UI exists yet — a known, documented gap, not hidden).
- **`refund_ambiguity`** — `330011294 AYWQ MCARE BENEFITS ANILA MAYEKAR` (+$61.80), a Medicare
  benefit credit — looks refund-shaped but isn't clearly tied to a prior spend, so it's flagged for
  a human decision instead of auto-netted. Also two "rocking girls dinner" repayment-style credits
  (`Mrs Gayathri Sreekum...`, `HELEN SPURR...`, ~$59–61.50) — could be a genuine refund or just a
  friend paying back a shared cost; exactly the kind of case a rule can't safely auto-decide.
- **`transfer_match` (Medium band — auto-linked but flagged for confirm/reject)**:
  `ONLINE N6414309103 Arvan food MAYEKAR A` (+$30.00) auto-linked to `NANDOS BURWOOD` (-$29.60),
  same day, amounts close but not exact. **This is a great live-demo moment**: click reject and
  explain that a near-amount coincidence auto-links as a *soft* guess, not a silent fact — the
  queue exists precisely to catch a case like this before it silently misclassifies a real dinner
  expense as an internal transfer.

**Demo line**: "Nothing gets silently guessed wrong forever — anything uncertain surfaces here with
the reason why, and one click resolves it."

## What's not in this demo (documented gaps, not surprises)

- MAC/MACACC/NBA statement formats — parser doesn't support them yet (README-documented fast-follow).
- The full 3-account RC→MAC→MACACC transfer chain — depends on the above; only the AC↔JC and JC↔CC
  pairs above are demoable today.
- Unrecognised-account resolution UI (rename/merge) — flagged for visibility only, no fix-it action.
- J6/J7/J8 and Phase 2 (forecasting, cloud deployment) — see the table at the top of this doc.
