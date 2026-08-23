# Design Phase: Shared User Journeys

Status: Active
Last updated: 2026-08-18
Companion to: `docs/product-requirements.md` (requirements/decisions) and `docs/next-steps.md`
(resumable to-do list). This doc is step 5's storyboard — what the user actually does, step by step,
and what the system should do in response — written **before** architecture (data model, API,
dashboard UX) so that architecture is derived from concrete usage rather than the other way round.
The step-5 design work (data model/API/rules, and transfer-logic/dashboard-UX) designs against this
doc, so a journey that touches both halves (e.g. J4, J5) has one consistent definition instead of
two independently-invented ones.

See `docs/design-architecture-diagram.html` for a visual walkthrough of the pipeline these journeys
sit on — open it directly in a browser.

Each journey below is grounded in a specific FR number and, where possible, a real example already
documented in `docs/product-requirements.md` §4.1/§4.2 — not a hypothetical.

## J1 — Upload a new bank statement

**FRs:** FR-1, FR-2, FR-3, FR-4

Trigger: Rohan uploads a CSV/xlsx export from any of his 7 accounts (3 distinct raw formats — see
§4.1).

System: detects the raw format, resolves the account (via an alias table for accounts with multiple
raw identifiers, e.g. `Card ending 7128` / `453030xxxxxx7128` — or flags an unrecognised identifier
for confirmation rather than silently creating a duplicate account), parses rows, de-duplicates
against existing data, categorises each transaction (rule match, then LLM fallback), detects
`Transfer`-type transactions (two-tier per FR-9e), tags `is_refund` where applicable, links to an
`Asset` where identifiable.

Outcome: transactions persisted; parsing errors are surfaced, never silently dropped (FR-4);
low-confidence categorisations or matches land in the review queue (J5), not silently guessed.

**Acceptance example:** uploading JC's statement after CC's already exists auto-links the $8,050.20
`CREDIT CARD PAYMENT` (CC) / `AUTOMATIC DRAWING` (JC) pair as `Transfer` via the description-embedded
linked account number — tier 1 of FR-9e, no manual review needed.

## J2 — View income vs. expense over a period

**FRs:** FR-11, FR-12, FR-13

Trigger: Rohan opens the dashboard and picks a date range.

System: computes income vs. expense totals excluding `Transfer`-type transactions, net of refunds
(except the `Income`-classified ATO tax-refund exception, §4.2), plus a category breakdown.

Outcome: "how much did I spend on X last month" is answered directly (§6 success criteria) — no
manual reconciliation of raw transactions required.

## J3 — Drill into a category

**FRs:** FR-14

Trigger: Rohan clicks a category (e.g. "Groceries") in the breakdown from J2.

System: returns the underlying transactions for that category and period.

Outcome: no dead end from a summary number to the transactions behind it.

## J4 — Correct a miscategorised transaction

**FRs:** FR-9, FR-15

Trigger: Rohan finds a transaction wrongly categorised (e.g. `"Hills Meats"` tagged `Services`
instead of `Groceries`) and corrects it.

System: updates the transaction's category, **and** writes or updates a categorisation rule tied to
that merchant, sourced from the correction (not just a one-off fix).

Outcome: the *next* `"Hills Meats"` transaction auto-categorises correctly without another manual
correction — this is the concrete meaning of "learn from corrections," which FR-9 left as an open
mechanism.

## J5 — Resolve the needs-review queue

**FRs:** FR-10, FR-9e (tier 2)

Trigger: Rohan opens a "Needs Review" view.

System: lists transactions flagged for either low-confidence categorisation (FR-10) or
low-confidence transfer/refund pairing (FR-9e's heuristic tier).

Outcome: Rohan confirms or corrects each; a confirmed category may seed a new rule (J4's mechanism);
a confirmed transfer link persists and both legs are excluded from income/expense totals.

**Acceptance example:** the real RC→MAC→MACACC $1,816.50 same-day three-account chain (§4.1) is a
plausible candidate for landing here if match confidence is borderline, rather than being silently
auto-linked without review.

## J6 — View the investment/asset portfolio

**FRs:** FR-15a

Trigger: Rohan opens "Investments."

System: shows a portfolio-wide roll-up across all `Asset` entities, or filters to a single one — e.g.
"Hillside" showing its EMI/Rent/Water/Insurance transactions and net cash flow, or "NAB Shares"
showing dividend history.

Outcome: "how is asset Y performing" is answered directly (§6 success criteria).

## J7 — Track ATO tax refund year-on-year

**FRs:** §4.2 scoped exception, decided 2026-08-18

Trigger: Rohan filters `Income` by the `Tax Refund` subcategory, grouped by year.

System: returns a direct grouped sum — no netting or derivation involved, since tax refunds are
classified as `Income`, not `is_refund`.

Outcome: the exact question that prompted this design exception, answered in one filter.

## J8 — One-time historical backfill

**FRs:** FR-7a, §4.2.1

Trigger (once, at setup): Rohan triggers import of the 13-year `Expense Log`.

System: imports ~14,300 historical transactions tagged `source=backfill`, applies the §4.2.1
old→new remapping table, and routes the 4 explicitly-flagged items (`Earning>Loan`, the stray
`Premium_EMI>Donation` entry, `Misc Refund`, `ADJUSTMENT`) to the J5 review queue rather than
guessing a category for them.

Outcome: the dashboard and future forecasting have full multi-year history available from day one,
auditably distinguishable from bank-imported data (NFR-5).

## J9 — A transfer chain spanning 3+ accounts

**FRs:** FR-9e, extended beyond the two-leg case

Trigger: statements for RC, MAC, and MACACC covering 2026-07-27 are all uploaded.

System: detects the real $1,816.50 same-day chain across all three legs (RC → MAC → MACACC) and
links them together as one chain, not just as an isolated pair.

Outcome: no double-counting of the same money moving through three of Rohan's own accounts.

## J10 — A payment to a dependent is not a Transfer

**FRs:** FR-9d

Trigger: AC and NBA statements show recurring payments described as `"ARVAN MAYEKAR"` (guitar
lessons, food, a birthday trip).

System: because Arvan isn't a registered `Account` belonging to Rohan or Anila, these transactions
classify as genuine `Expense` (`Kids & Family`) — never `Transfer` — regardless of how routine or
"internal" the bank's own description language makes them sound.

Outcome: real family spend stays visible in the `Kids & Family` category, not silently excluded from
totals the way an actual transfer would be.

## Design ownership against these journeys

- **Data model, API, and categorisation-rule design** serves J1, J4, J5 (the rule-learning half),
  J6, J7, J8 — see `docs/design-data-model-api.md`.
- **Transfer/refund matching logic and dashboard UX** serves the matching logic behind J1/J9/J10,
  and the UX for J2/J3/J5 (review-queue screen)/J6/J7 — see `docs/design-logic-and-ux.md`.

Where a journey is claimed by both (J1, J4, J5), each design doc should be traceable back to its
specific slice of that journey rather than silently assuming the other half.
