# AI Personal Budgeting & Expense Categorisation System — Product Requirements

Status: Draft v9
Owner: Rohan Mayekar
Last updated: 2026-08-18
Source: `Project_objectives_raw.md`

Companion document: a separate **Agentic Development Workflow** doc will cover `.claude/` setup,
`AGENTS.md`, and the brainstorm → plan → design → code → review → test → deploy process. Not
covered here.

## 1. Purpose

A personal tool that ingests bank statements, categorises transactions using AI, presents them in
a dashboard, and forecasts future income/expenses — built as a vehicle for learning agentic AI
engineering practices.

## 2. Users

- Single user (Rohan) for MVP and Phase 2.
- Architecture should not actively block adding more users later, but multi-user support (auth,
  per-user data isolation, roles) is explicitly **out of scope** until requested.

## 3. Scope

### 3.1 In scope for MVP

1. Import bank statement files across **all** of the user's accounts (credit cards, current/
   savings, and investment/brokerage where relevant) — covering both expense-generating and
   income-bearing accounts. This fully replaces the user's prior manual categorisation process (see
   below); going forward, bank statement files are the only ongoing input. Sample files beyond the
   credit-card export are pending (user to provide).
2. Review the user's two existing manually-categorised references (a recent credit-card xlsx and a
   13-year manual expense log + its category parameters), evaluate whether either taxonomy is fit
   for purpose, and design a merged categorisation scheme (informs the taxonomy used by the system).
3. Categorise transactions from statement imports against that taxonomy.
4. Persist categorised transactions.
5. One-time backfill of the user's historical manually-categorised expense log (2012–2025, ~14,300
   transactions) into the system, remapped to the new taxonomy — so the dashboard/forecasting has
   years of real history from day one rather than starting empty.
6. Model investable assets (real estate properties, share holdings, etc.) as first-class entities
   so spend/income can be filtered or rolled up per-asset or across the whole portfolio.
7. Present a dashboard (web UI) showing categorised income/expenses.

### 3.2 In scope for Phase 2

8. Predict future income/expenses using an LLM-assisted forecast with natural-language reasoning
   (not just numbers — explains *why*, referencing patterns, seasonality, known upcoming changes).
9. Deployment to a cloud free tier (from local-only in MVP).
10. Support for additional banks/CSV formats or currencies, if needed.

### 3.3 Out of scope (for now)

- Multi-user support, authentication, roles/permissions.
- Non-CSV statement ingestion (PDF, OFX, bank API/Open Banking integration).
- Multi-currency handling.
- Budgets/goals/alerts (e.g. "notify me if groceries exceed £X") — may become a later phase.
- Mobile app.
- **Manual/ad-hoc transaction entry or editing of the category taxonomy's source data** — the whole
  point of this system is to eliminate the manual `Expense Log` process the user previously
  maintained. Category *corrections* on individual transactions remain in scope (FR-9); manually
  keying in new transactions does not.

## 4. Functional Requirements

### 4.1 Statement Ingestion

- FR-1: The system shall accept CSV bank statement uploads for the user's bank, across the
  account types the user holds (current, savings, credit card, etc.).
- FR-2: The system shall parse each CSV into structured transaction records: date, description,
  amount, direction (debit/credit), account, and any other columns the bank's export provides.
- FR-3: The system shall handle repeated/overlapping statement uploads without duplicating
  transactions (de-duplication).
- FR-4: The system shall surface parsing errors (unrecognised columns, malformed rows) rather than
  silently dropping data.

**Confirmed: real sample files now cover 7 of the user's accounts** (`transaction-files/
BankTransactions - {CC,JC,RC,AC,MAC,MACACC,NBA}.xlsx`, reviewed 2026-08-18), across **three
distinct raw export shapes** — ingestion must support all three, not just one:

| Shape | Accounts | Columns |
|---|---|---|
| NAB-style | CC (credit card), JC (joint classic, Rohan+Anila), RC (Rohan's classic), AC (Anila's classic) | `Date`, `Amount` (signed), `Account Number`, `Transaction Type`, `Transaction Details`, `Balance`, `Category`, `Merchant Name`, `Processed On` |
| Macquarie-style | MAC (Cash Management Account), MACACC (its higher-interest Accelerator sub-account) | `Transaction Date`, `Details`, `Account`, `Category`, `Subcategory`, `Tags`, `Notes`, `Debit`, `Credit` (split, not signed), `Balance`, `Original Description` |
| Headerless CommBank-style | NBA (receives Rohan's payroll, forwards a fixed tranche to RC) | No header row at all: `Date`, `Amount`, `Description`, `Balance` only — ingestion needs a headerless-CSV mode, not just flexible header matching |

`Account Number`/`Account` values seen: `Card ending NNNN` / masked `453030xxxxxx7128` (CC, two
formats for the same linked relationship, per the original finding below), plain numeric account
numbers (JC `147912573`, RC `133500607`, AC `147912186`), and free-text account names (MAC/MACACC).

Note: the repo's existing `transaction-files/sample.csv` (`Date,Description,Amount` only) and
`transaction-files/BankTransactions.xlsx`'s original CC-only layout note below are placeholders that
do **not** match the full real shape diversity — existing ingestion code built against them should
be treated as unverified against real data.

**Confirmed CSV layout (credit card account, CC)** — 347 real transactions, 2026-04-13 to 2026-08-08:

| Column | Notes |
|---|---|
| `Date` | Transaction date |
| `Amount` | Signed; negative = debit/spend, positive = credit (payment received, refund) |
| `Account Number` | Two formats observed for related accounts: `Card ending NNNN` (the card itself) and a masked full number e.g. `453030xxxxxx7128` (the linked account paying off that card) — ingestion needs to handle both without treating them as unrelated accounts |
| `Transaction Type` | Observed values: `CREDIT CARD PURCHASE`, `PURCHASE AUTHORISATION` (pending, not yet settled), `CREDIT CARD PAYMENT` (paying off the card, positive amount), `CREDIT CARD REFUND` |
| `Transaction Details` | Raw merchant descriptor, unclean (e.g. `HILLS MEATS PTY LTDHILLS Forest Hill 036` — no reliable delimiter between merchant name and location) |
| `Balance` | Running balance on the account |
| `Processed On` | Blank for pending/unsettled transactions (e.g. `PURCHASE AUTHORISATION` rows) |

FR-3's de-duplication logic should also account for `PURCHASE AUTHORISATION` (pending) rows that may
later reappear as a settled `CREDIT CARD PURCHASE` — not observed as an active duplicate in the
sample, but a known real-world pattern for card statements.

**Confirmed inter-account transfer examples (2026-08-18)** — real matched pairs found across the new
sample files, validating the FR-9c/9e design with concrete evidence rather than hypothetical cases:

- CC `CREDIT CARD PAYMENT +$8,050.20` (2026-08-05) ↔ JC `AUTOMATIC DRAWING -$8,050.20`, same date;
  JC's description literally contains the CC's linked account number (`4530307001277128`).
- AC `-$5,000 "ONLINE J6657692287 Trans salary MAYEKAR A"` (2026-08-13) ↔ JC `+$5,000`, **identical
  reference number** — Anila routes a fixed $5,000 tranche of her own salary into the joint account
  every pay cycle; several smaller `"AC to JC"`-labeled transfers match the same way (identical
  reference numbers on both sides, e.g. `Q6957221963`, `G8844302108`, `G9089369524`).
- NBA `-$5,000 "Transfer To ROHAN MAYEKAR ... transfer salary"` (2026-08-05) ↔ RC `+$5,000
  "ROHAN MAYEKARtransfer salary"`, same date — the equivalent pattern from Rohan's side; NBA itself
  receives Rohan's payroll (`"Salary STAFF DEPARTMENT 00497982"`) before forwarding the tranche.
- RC → MAC → MACACC: a same-day, same-amount ($1,816.50, 2026-07-27) three-account chain — transfer
  detection (FR-9e) needs to handle chains of more than two legs, not just pairs.

**Design-relevant nuance surfaced by the data:** both AC and NBA send recurring money to
`"ARVAN MAYEKAR"` (guitar lessons, food, a birthday trip) — Arvan is a dependent, not an account
Rohan or Anila holds. Per FR-9d, these must be classified as genuine **Expense** (family/kids
spend), not `Transfer`, even though the bank's own description uses transfer-style language. The
same applies to AC's informal peer-to-peer entries (dinner-split reimbursements from friends,
farewell-drinks contributions) — external counterparties, correctly excluded from `Transfer`
despite the bank's own `Category` column calling several of them `"Transfers in"`/`"Refund"`. This
confirms FR-9e's existing decision to rely on type/description signal + heuristic pairing rather
than trusting bank-assigned categories, which are demonstrably unreliable for this purpose (e.g. RC
labels a real external tradesperson invoice as `"Transfers out"`).

**Still open:** the underlying brokerage/property-loan account ledgers themselves (individual share
buy/sell transactions; the actual mortgage statements behind the `Investment`/`Asset` entity) are
still not sampled — MAC/AC only show the *cash-flow* side (dividends landing, a lump sum leaving to
fund a brokerage) and JC only shows loan *interest* being charged, not the loan account's own
statement. Sufficient to proceed to the design phase (step 5) on data model/API/transfer logic;
still a gap for fully designing the `Investment`/`Asset` entity's Buy/Sell transaction types.

### 4.2 Manual Categorisation Review

- FR-5: The user provided two existing manually-categorised references (see below).
- FR-6: The system (with AI assistance) shall analyse these files' categorisation schemes and
  produce an assessment: are they fit for purpose, what's missing, what's inconsistent, what would
  a better taxonomy look like.
- FR-7: The output of this review shall inform (but not necessarily dictate unchanged) the
  taxonomy used for automated categorisation in 4.3.

**Source 1 — `transaction-files/BankTransactions.xlsx`** (347 real transactions, 2026-04-13 to
2026-08-08, credit-card spend only): 26 flat categories, no income data. See history for full
findings — highly self-consistent (only 1 of 137 merchants had a genuine category conflict), and
`Uncategorised` correlated exactly with an unresolved merchant name.

**Source 2 — `docs/AU COST - Manual categorisation.xlsx`** (`Expense Log` + `Parameters` sheets,
14,349 transactions, 2012-05-09 to 2025-06-07 — the user's real long-running manual budget,
covering **all** accounts including income):

- A `Type` field (`Earning`/`Expense`, 1,323 vs 13,026 rows) plus a formally maintained, dropdown-
  validated taxonomy in `Parameters`: 18 real leaf categories (`Earning`/`Expense` above them is the
  `Type` flag, not a category) with ~78 sub-categories total — corrected 2026-08-18 from an earlier
  "20×85" approximation once the sheet was extracted column-by-column.
- Includes income categories entirely absent from Source 1: `Salary` (624 rows), `Dividend` (77),
  and `Investment`-related income.
- `Investment`'s sub-categories are actually **per-property breakdowns** (`Hillside`, `Alexa`,
  `Sylvania`, `JerichoCt`, each with `_EMI`/`_Rent`/`_Water`/`_Landlord_Ins` variants) — real
  personal finance modelling of rental properties, not a flat category.
- Data-quality noise: case-duplicate categories (`Gifts`/`gifts`, `Rent`/`rent`,
  `Uber`/`uber`, `Salary Anila`/`salary Anila`) — trivial to normalise.
- Historically, `Refund` (487 rows) was modelled as `Type=Earning` — i.e. counted as income. This
  conflicts with the refund decision in 4.3.2 (see below).
- This file's `Expense Log` sheet's raw XML was bloated to ~150MB by Excel formatting applied
  across all 1,048,576 possible rows — a file artifact, not a data quality issue; real data is
  confined to rows 7–14355.

**Decision (2026-08-09) — merged taxonomy, designed jointly with the user:**

- Base the taxonomy on a **fresh merge of both sources**, not either one as-is — Source 1 is more
  granular/everyday (recent card spend), Source 2 is more structurally complete (income, bills,
  insurance, loans, investments) but has 13-year-old category naming and some noise.
- Target **~12–18 top-level categories**, each with sub-categories added only where a category has
  genuine transaction volume/diversity behind it — a category with a handful of historical
  transactions gets an `Other` sub-category slot, not one slot per transaction.
- **`Refund` is not a category** — it nets against the original expense category rather than
  counting as income (see 4.3.2). This deliberately departs from the 13-year precedent in Source 2;
  historical `Refund`/`Earning` rows will be reinterpreted under the new rule during backfill (see
  4.2.1), not literally relabelled as `Refund=Earning`.
- **Investable assets are generalised beyond real estate**: rather than a `Property` entity, model
  an `Investment`/`Asset` entity with a `type` (`Real Estate`, `Shares`, `Managed Fund`, ...) and a
  `name` (`Hillside`, `NAB Shares`, ...). Real-estate assets get EMI/Rent/Water/Insurance-tagged
  transactions; share/fund assets get Dividend/Buy/Sell-tagged transactions. This lets the dashboard
  show a single portfolio view across all investment types, or filter to one asset — directly
  supporting the user's "review all my investments" use case.
**Final merged category list (Decided 2026-08-18)** — 16 top-level categories, synthesized from
Source 1, Source 2's `Parameters` sheet (18 real leaf categories under an `Earning`/`Expense` `Type`
flag, ~78 sub-categories total — corrects the earlier "20×85" approximation), and the 6 additional
real accounts reviewed in §4.1:

| # | Category | Sub-categories |
|---|---|---|
| 1 | `Income` | Salary, Interest, Dividends & Distributions (fallback — see note), Tax Refund, Government Rebate, Other |
| 2 | `Housing` | Rent, Mortgage EMI, Home Insurance, Utility Bills, Maintenance/Content |
| 3 | `Groceries` | — |
| 4 | `Cafes & Restaurants` | Restaurants & Takeaway, Cafes & Coffee |
| 5 | `Transport` | Public Transport, Taxis & Rideshare, Parking & Tolls |
| 6 | `Car` | EMI, Insurance, Petrol, Registration, Other |
| 7 | `Travel & Holidays` | Flights, Accommodation, Attractions & Events, Other |
| 8 | `Shopping` | Clothes, Electronics & Technology, Homeware, Other |
| 9 | `Health & Medical` | Medical, Gym & Fitness |
| 10 | `Insurance` | Life/TPD/Income Protection, Critical Illness, Content (non-home) |
| 11 | `Kids & Family` | School Fees, Childcare, Activities, Pocket Money, Other |
| 12 | `Gifts & Donations` | Gifts, Donations |
| 13 | `Loans & Finance` | Loan Repayment, Loan Interest, Financial Advice Fees |
| 14 | `Services & Subscriptions` | Phone & Internet, Media/Streaming, Other |
| 15 | `Government & Tax` | Tax Paid, Government Fees |
| 16 | `Miscellaneous` | — (genuine small catch-all; failed/low-confidence categorisation routes to the FR-10 review flag, not silently here) |

`Refund` and `Investment` are deliberately **not** on this list: `Refund` is the `is_refund`
attribute (4.3.2), not a category; `Investment` becomes the `Investment`/`Asset` entity above — every
old `Investment` subcat (`Hillside`/`JerichoCt`/`Alexa`/`Sylvania` → Real Estate; `MLC`/`NAB Share`/
`Barkley` → Shares/Managed Fund) becomes one `Asset` record. `Housing` is the *primary residence*
only — investment properties route to the `Investment`/`Asset` entity, not `Housing`.

**Scoped exception to 4.3.2, decided 2026-08-18 (user preference):** an ATO tax refund isn't like a
merchandise refund — it doesn't relate to one specific prior transaction, it's a lump-sum return
against a whole year's `Tax Paid` activity, and netting it away would hide it from view entirely. Tax
refunds are classified as genuine `Income` → `Tax Refund` (not `is_refund=true`), so "how much tax
refund am I getting year-on-year" is a direct filter/group-by-year on that Income subcat, not a
derived number. Scoped to ATO tax refunds specifically; other historical `Refund` subcats still net
per 4.3.2 (see remapping table below) unless the same reasoning is explicitly extended later — e.g.
Medicare benefits (seen bank-tagged `Refund` in the new AC sample data) are arguably the same kind of
case, flagged here, not decided.

#### 4.2.1 Decision: historical backfill — DECIDED

- FR-7a: The system shall perform a one-time import of the `Expense Log`'s ~14,300 historical
  transactions (2012–2025), remapped from the old taxonomy to the new merged taxonomy (4.2), so the
  dashboard and forecasting have multi-year history available immediately rather than starting
  empty.
- Backfilled transactions should be distinguishable from bank-import-sourced ones (e.g. a `source`
  field) for auditability (NFR-5), since they weren't independently re-verified against a bank
  statement.

**Old → new remapping table (Decided 2026-08-18):**

| Old category (Type) | New treatment |
|---|---|
| `Salary` (Earning) | `Income` → Salary |
| `Dividend` / `Earning>Investment` | `Investment`/`Asset` entity if attributable to a named holding, else `Income` → Dividends & Distributions |
| `Earning>Loan` | `Income` → Other — **flagged for manual review**, old sheet's intent unclear from the data alone |
| `Refund` → `Tax Refund` | `Income` → Tax Refund (not netted — see exception above) |
| `Refund` → `Medical Refund` | Nets against `Health & Medical` per 4.3.2 |
| `Refund` → `Childcare Refund` | Nets against `Kids & Family` per 4.3.2 |
| `Refund` → `Interest Refund` | Nets against `Loans & Finance` per 4.3.2 |
| `Refund` → `Misc Refund` / `ADJUSTMENT` | **Flagged for manual review** — no reliable original-category signal |
| `Utility_Bill` | `Housing` → Utility Bills, except `Internet and Phone` → `Services & Subscriptions` |
| `Premium_EMI` | `Insurance`, except `Medical` subcat → `Health & Medical`; stray `Donation` entry → manual review (data-quality noise in the old sheet) |
| `Rent`, `House` | `Housing` |
| `Travel` → `Myki`, `Uber` | `Transport` (everyday commute, reclassified out of holiday travel) |
| `Travel` → `Plane Tickets`, `Other Travel`, `Holiday Membership` | `Travel & Holidays` |
| `Shopping` → `Food and Grocery` | `Groceries` (reclassified) |
| `Shopping` → `Gym` | `Health & Medical` (reclassified) |
| `Shopping` → rest | `Shopping` |
| `Gifts`, `Donations` | `Gifts & Donations` |
| `Loan`, `Financial_Planning` | `Loans & Finance` |
| `Car` | `Car` (1:1) |
| `Arvan_Fees` | `Kids & Family` (1:1) |
| `Medical` | `Health & Medical` |
| `Misc_Expense` → `Tax paid` | `Government & Tax` |
| `Misc_Expense` → `Misc` | `Miscellaneous` |
| `Investment` (all subcats) | `Investment`/`Asset` entity — one `Asset` record per name |

Bank-assigned categories seen on the new accounts that are really `Transfer`-type signals
(`Internal transfers`, `Transfers in`/`out`, `Credit card repayments`) are **not remapped to any
spend category** — they route to `Type = Transfer` per 4.3.3 and are excluded from category totals.

### 4.3 Automated Categorisation

- FR-8: The system shall assign a category to each transaction imported from CSV, using the
  taxonomy from 4.2.
- FR-9: The system shall allow the user to manually correct/override a category, and should be
  able to use those corrections to improve future categorisation (exact mechanism — re-prompting,
  fine-tuning examples, rule updates — is an open decision, see 4.3.1).
- FR-10: The system shall flag low-confidence categorisations for user review rather than silently
  guessing.

#### 4.3.1 Decision: categorisation method — DECIDED

**Rule-based + LLM fallback.** Known/recurring merchants (salary, rent, common subscriptions) are
matched deterministically via rules; the LLM handles the long tail of novel/ambiguous merchants.
Chosen for a balance of low running cost, predictability, and still giving hands-on LLM/agentic
experience on the harder classification cases.

| Option | Pros | Cons |
|---|---|---|
| **Rule-based + LLM fallback (chosen)** | Fast & free for known merchants, predictable, LLM only where needed | Two systems to maintain, rules need seeding/upkeep |
| Pure LLM classification | Simple, flexible, handles novel merchants well, natural fit for "AI" learning goals | Cost/latency per transaction, less deterministic, needs prompt/eval discipline |
| Traditional ML (embeddings + classifier) | No per-call LLM cost at inference, fast | Needs training data volume, less flexible to new merchants, less aligned with "agentic AI" learning goal |

Design-phase follow-ups: how rules are seeded (from the manual xlsx review in 4.2, and/or from
FR-9 corrections), rule format/storage, and the confidence threshold that triggers LLM fallback vs.
FR-10's low-confidence flag. **Resolved in step 5 design** — see `docs/design-data-model-api.md`
(`CategorisationRule` format, 0.7 confidence threshold, rule-seeding source).

**LLM provider: Claude API (Anthropic) — decided 2026-08-18.** Deliberately left open until now;
chosen for consistency with the project's own Claude-Code-based dev workflow. Not a runtime decision
implied by the earlier removal of the `openai` package (that was for the retired dev-tooling script
only, see `docs/agentic-workflow.md`).

#### 4.3.2 Decision: refund handling — DECIDED

**Scoped exception:** ATO tax refunds are classified as `Income` → Tax Refund, not netted under this
rule — see 4.2 for the reasoning (they don't relate to one specific prior transaction the way a
merchandise refund does) and the old→new remapping table for how other historical `Refund` subcats
are treated. Everything below applies to refunds generally, tax refunds excepted.

- FR-9a: Every transaction, including refunds, is stored as its own immutable record — nothing is
  ever merged, deleted, or overwritten as a result of netting. Full transaction history remains
  individually queryable (supports NFR-5 auditability and the user's requirement to "keep a record
  of all transactions for future reference").
- FR-9b: A refund is **not** counted as income. It is tagged (e.g. an `is_refund` attribute) and,
  for reporting/rollup purposes (dashboard totals, category breakdowns, forecasting), nets against
  the *original* category it relates to — e.g. a $340 Electronics purchase later refunded $50 shows
  as $290 net spend under Electronics, not $50 of income. This keeps the income-vs-expense view
  (FR-12) honest: "income" means actual earnings (salary, interest, etc.), not returned spend.
- Reconciling a refund to its original purchase's category (vs. the merchant's typical category, if
  no direct link is found) is a design-phase concern — exact matching logic not fixed here.
- Confirmed 2026-08-09: this deliberately overrides the user's 13-year historical practice (Source
  2 in 4.2 modelled `Refund` as `Type=Earning`). The user confirmed the new netting approach is
  preferred going forward; historical `Refund` rows are reinterpreted under this rule during
  backfill (4.2.1), not preserved as income.

#### 4.3.3 Decision: inter-account transfer handling — DECIDED

- FR-9c: Every transaction has a `Type` of `Income`, `Expense`, or **`Transfer`** — transfers
  between two of the user's own accounts are neither income nor expense and are structurally
  excluded from income-vs-expense totals (FR-12) and category breakdowns (FR-13), rather than
  relying on excluding a specific category by name. Both legs of a transfer remain separate
  immutable records (per FR-9a), linked via a shared identifier so the UI can show the paired
  transaction.
- FR-9d: A transaction is classified `Transfer` only when **both** legs belong to accounts the user
  holds — a payment to or from an external party is a real `Expense`/`Income`, never a `Transfer`,
  regardless of how routine it looks.
- FR-9e: Transfer detection uses two tiers:
  1. **Type/description signal, no counterpart required** — when the bank's own transaction type or
     description already identifies a self-payment between known accounts (e.g. `CREDIT CARD
     PAYMENT`, as seen in `BankTransactions.xlsx` between `Card ending 7128` and
     `453030xxxxxx7128`), tag it as `Transfer` immediately, even if the counterpart account's
     statement hasn't been imported yet.
  2. **Heuristic pairing** — when no such signal exists, match opposite-signed transactions of
     equal (or near-equal) amount within a short date window across two of the user's own accounts;
     lower-confidence matches are flagged for user review (same pattern as FR-10).
- Exact matching tolerance (date window, amount tolerance for fees/rounding) is a design-phase
  concern, not fixed here.

- FR-11: The system shall provide a web UI showing categorised transactions.
- FR-12: The dashboard shall show income vs expenses over a selectable time period (excluding
  `Transfer`-type transactions per 4.3.3, and net of refunds per 4.3.2).
- FR-13: The dashboard shall show a breakdown by category (e.g. chart + table).
- FR-14: The dashboard shall let the user drill into a category to see underlying transactions.
- FR-15: The dashboard shall let the user correct a transaction's category (feeds FR-9).
- FR-15a: The dashboard shall provide an investment/asset view — filterable to a single asset
  (e.g. one property or share holding) or rolled up across the whole portfolio, showing associated
  income and expense transactions (see 4.2's `Investment`/`Asset` entity decision).

**Open decision:** specific chart types, filtering/date-range UX, and visual design are a design-
phase concern, not fixed here.

### 4.5 Forecasting (Phase 2)

- FR-16: The system shall forecast future income and expenses using an LLM that reasons over
  historical categorised transaction data.
- FR-17: The forecast shall include a natural-language explanation of the reasoning (trends,
  seasonality, anomalies, known recurring items), not just numbers.
- FR-18: The forecast horizon and refresh cadence are an open decision — to be defined in Phase 2
  design, not in this MVP-focused document.

## 5. Non-Functional Requirements

- NFR-1 (Deployment): Runs entirely locally for MVP (local web server + local storage, e.g.
  SQLite). No cloud dependency required to use the system end-to-end.
- NFR-2 (Deployment, Phase 2): Deployable to a cloud free tier without a fundamental
  re-architecture — avoid MVP decisions that would block this (e.g. don't hardcode
  localhost-only assumptions where avoidable).
- NFR-3 (Privacy/Security): Financial data is sensitive. Even for local-only MVP, avoid sending
  raw transaction data to third parties beyond the categorisation/forecasting LLM calls the user
  has explicitly opted into. When deployed to cloud (Phase 2), add basic auth before the dashboard
  is reachable over the internet.
- NFR-4 (Cost): LLM calls (categorisation, forecasting) should be mindful of API cost — batch
  where sensible, avoid re-categorising unchanged transactions.
- NFR-5 (Auditability): Since this is also a learning project, categorisation and forecast
  decisions should be traceable (e.g. what prompt/data produced a given category or forecast),
  supporting the "review" step of the intended agentic workflow.
- NFR-6 (Data integrity): Uploading/re-uploading statements must not corrupt or duplicate existing
  data (see FR-3). Individual transaction records (including refunds) are never merged or deleted —
  category rollups/netting (see FR-9b) are computed views over the raw data, not mutations of it.

## 6. Success Criteria (MVP)

- Real bank statement exports across all the user's accounts can be uploaded and parsed without
  manual data-wrangling — replacing the manual `Expense Log` process entirely.
- The AI's review of both manual references produces a concrete, actionable merged taxonomy.
- The 13-year historical expense log is backfilled and browsable in the new system.
- >90% of transactions receive a category without manual correction (rough target, to be
  validated against real data).
- The dashboard lets the user answer "how much did I spend on X last month" and "how is asset Y
  performing" without touching raw data.

## 7. Open Questions Log

These are called out inline above; consolidated here for tracking:

1. ~~Exact CSV column layout~~ — **Confirmed** 2026-08-09 for credit card accounts, extended
   2026-08-18 with 6 more real accounts (JC, RC, AC, MAC, MACACC, NBA) across 3 distinct raw export
   shapes (see 4.1). Still pending: the brokerage/property-loan accounts' own statements (only their
   cash-flow effects are visible via MAC/AC/JC so far).
2. ~~Whether the manual references' taxonomy is kept, revised, or replaced~~ — **Decided**
   2026-08-09, **finalized** 2026-08-18: 16-category merged taxonomy locked in (see 4.2), with
   `Refund` as an attribute (not a category, except a scoped Income exception for ATO tax refunds)
   and investable assets modelled as a generalised `Investment`/`Asset` entity.
3. ~~Final categorisation method~~ — **Decided** 2026-08-09: rule-based + LLM fallback (see 4.3.1).
4. Mechanism for learning from manual category corrections (FR-9).
5. Dashboard chart/UX specifics — deferred to design phase.
6. Forecast horizon, cadence, and confidence-reporting approach — deferred to Phase 2 design.
7. ~~Whether the existing code in `backend/`, `frontend/`, `ingestion/`, `categorisation/` is
   reused, refactored, or discarded~~ — **Decided** 2026-08-17: per-module verdict in §8 —
   `backend/*` and `frontend/dashboard.py` refactor, `ingestion/csv_importer.py` and
   `categorisation/*` discard.
8. How refund transactions are reconciled to their original purchase's category (direct match vs.
   merchant's typical category) — deferred to design phase (see 4.3.2).
9. Account-linking logic for related account identifiers (e.g. `Card ending 7128` vs. the masked
   full number `453030xxxxxx7128` for the same underlying relationship) — deferred to design phase.
10. ~~Whether to backfill the 13-year historical expense log~~ — **Decided** 2026-08-09: yes, one-
    time backfill remapped to the new taxonomy (see 4.2.1). Exact remapping rules deferred to
    design phase.
11. ~~Exact old→new category/sub-category remapping table for backfill~~ — **Decided** 2026-08-18:
    full table in 4.2.1, including 4 items flagged for manual case-by-case review during backfill
    rather than a blanket rule (`Earning>Loan`, stray `Premium_EMI>Donation`, `Misc Refund`,
    `ADJUSTMENT`).
12. CSV/export layout for investment/brokerage account(s), and how buy/sell/dividend transaction
    types map onto the `Investment`/`Asset` entity — **partially addressed** 2026-08-18: MAC shows
    dividend cash-flow from named holdings (Vanguard ETF tickers VGAD/VAP/VAS/VEU/MVW/IFRA/AQLT/
    QUAL, a NAB share dividend, and an employee share plan via Computershare EquatePlus) and a
    recurring lump-sum transfer out to fund a brokerage — but the brokerage's own buy/sell ledger is
    still not sampled.
13. ~~Whether inter-account transfers are a category or a distinct type~~ — **Decided** 2026-08-09:
    a distinct `Transfer` Type, excluded from income/expense totals (see 4.3.3). Exact matching
    tolerance (date window, amount tolerance) deferred to design phase.

## 8. Relationship to Existing Repo Contents

This document originally defined requirements from a clean slate based on `Project_objectives_raw.md`,
deliberately without assessing the existing `backend/`, `frontend/`, `ingestion/`, `categorisation/`,
or `finance.db` — those were reviewed against this document in a follow-up pass on 2026-08-17
(`docs/next-steps.md` step 4). `AGENTS.md`/`README_AGENTS.md` predated this doc entirely and were
retired separately during the agentic-workflow setup (see `docs/agentic-workflow.md`) — not part of
this review.

**Review outcome (2026-08-17):** every module was built against a 3-column placeholder CSV
(`transaction-files/sample.csv`: `Date,Description,Amount`) and a flat `Transaction` table, months
before the taxonomy, `Type` (Income/Expense/Transfer), `is_refund`, and `Investment`/`Asset`
decisions in §4.2–4.3 existed — so nothing works unmodified. Verdicts differ by whether the
*scaffolding* (framework setup) or the *logic* (schema fields, column contracts, category rules) is
at fault:

| Module | Verdict | Why |
|---|---|---|
| `backend/models.py` | Refactor | SQLAlchemy pattern reusable; schema needs `Account`/`Investment`/`Asset` tables and `type`/`is_refund`/`transfer_link_id`/`source` fields — none exist today. |
| `backend/database.py` | Refactor | Session/engine helpers are schema-agnostic and reusable; `save_transaction`/`bulk_save_transactions` are hardcoded to the old 5-field shape with **zero de-dup logic** (FR-3 entirely unaddressed). |
| `backend/api.py` | Refactor | FastAPI scaffolding reusable; every endpoint's request/response shape needs rework, plus net-new endpoints for category correction (FR-9/FR-15) and asset views (FR-15a). |
| `ingestion/csv_importer.py` | Discard | Hard-requires exactly `{date, description, amount}`; the real export has no `Description` column (it has `Transaction Details`, `Account Number`, `Transaction Type`, `Balance`, `Processed On`) and would be rejected outright. |
| `categorisation/merchant_parser.py` | Discard | Assumes clean word-delimited descriptions; the real `Transaction Details` field has no reliable delimiter (e.g. `HILLS MEATS PTY LTDHILLS Forest Hill 036`). |
| `categorisation/categoriser.py` | Discard | 4-entry hardcoded dict against an ad hoc category list, not the merged taxonomy in §4.2; no confidence scoring, no LLM fallback, no refund/transfer awareness. |
| `frontend/dashboard.py` | Refactor | Streamlit skeleton reasonable; currently reads `finance.db` directly (bypasses the API), double-counts refunds as income, no Transfer exclusion, no category-correction UI, no investment/asset view. |
| `transaction-files/sample.csv` | Superseded | Not the real column layout; retire once real-shaped fixtures replace it. |
| Existing tests | Rewrite alongside their target module's rebuild | All pin assertions to the placeholder CSV shape or flat schema; replaced test-first (`tdd-workflow` skill) as each module is rebuilt in step 6, not separately. |

This is a decision record, not yet executed — `backend/api.py` imports directly from
`ingestion/csv_importer.py` and `categorisation/*`, so discarding those modules before their
replacement is designed would break the app rather than leave it merely unfinished. The rework
happens in `docs/next-steps.md` steps 5 (design) and 6 (build), as one coherent unit.
