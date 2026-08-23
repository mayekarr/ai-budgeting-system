# Design Phase: Transfer/Refund Matching Logic & Dashboard UX

Status: Active
Last updated: 2026-08-18
Companion to: `docs/design-journeys.md` (the storyboard this design is derived from — read that
first), `docs/design-data-model-api.md` (the data model/API this logic builds on — field names
below are theirs, not invented here), `docs/product-requirements.md` (requirements/decisions), and
`docs/next-steps.md`.

Per `docs/design-journeys.md`, this doc serves the matching logic behind J1/J9/J10, and the
dashboard UX for J2/J3/J5 (review-queue screen)/J6/J7. See `docs/design-architecture-diagram.html`
for where this logic and these views sit in the pipeline. Docs-only — no code changes yet (step 6),
and no edits to `docs/design-data-model-api.md` itself: where this doc's logic implies a schema
change, it's written here as a recommendation for the reconciliation pass to merge.

## 1. Refund logic

`docs/design-data-model-api.md`'s schema has no transaction-to-transaction refund link field — `is_refund` is a flag on
the `Transaction` row, and every row (refund or not) already gets a `category` from the normal
rule/LLM pipeline (`docs/design-journeys.md` J1: categorise, *then* tag `is_refund`). This matches
the existing precedent in `docs/product-requirements.md` §4.2.1's remapping table, which nets
refunds by **subcategory** (`Medical Refund` → nets against `Health & Medical`) — never by linking
to one specific original purchase row. So this design nets by category, not by a manufactured
transaction-to-transaction link.

### 1.1 `is_refund` detection

Ranked signals, first match wins:

1. **Explicit bank signal** — transaction type/category text directly says refund: NAB-style
   `CREDIT CARD REFUND`, Macquarie-style `Category`/`Subcategory` containing `"Refund"`.
2. **Description keyword backstop** — for formats with no dedicated type column (NBA's headerless
   export), a keyword match (`REFUND`, `RETURN`) on the description text.
3. **Legacy backfill passthrough** — Source 2 rows already tagged `Refund` under the old taxonomy
   (§4.2.1) carry straight through as `is_refund=true` during J8, with subcategory remapped per that
   table (`Medical Refund` → nets `Health & Medical`, `Childcare Refund` → nets `Kids & Family`,
   `Interest Refund` → nets `Loans & Finance`, `Misc Refund`/`ADJUSTMENT` → flagged for manual
   review per the existing 4-item flagged list, unchanged).

**The ATO tax-refund override runs before all three of the above, not after.** A transaction
matching the tax-refund pattern (ATO-related description, or the `Tax Refund`-seeded
`CategorisationRule`) is routed to `type=Income`, `is_refund=false` first — so §4.2's exception is
structural (a short-circuit), not a race between two detectors that happen to both fire.

### 1.2 Shared counterparty-resolution step

Re-reading `docs/product-requirements.md` §4.1's real examples surfaces a case that detection
signal 1 above doesn't handle correctly on its own: AC's dinner-split and farewell-drinks
reimbursements are bank-labeled `Category = "Refund"`, but they're money from a friend paying back
their share — not a merchant refund. This is the *exact same* "is this a registered account/known
business, or an external person" question J10 already has to answer for transfers (§3.1 below).
Rather than build two separate heuristics, this design uses one shared check:

> Does the transaction's description/merchant resolve to a known `AccountAlias` (a registered
> account — feeds transfer detection) **or** a known `CategorisationRule` merchant pattern (a
> recognised business — supports genuine merchant-refund detection)? If neither, the counterparty is
> unresolved.

Refund detection on an unresolved counterparty (a personal name, no merchant rule match) sets
`needs_review=true` instead of silently netting — it might be a genuine reimbursement (Income, not
netted) or a mislabeled refund; a human call, not a guess. This directly protects against the AC
P2P case without a bespoke rule for it.

### 1.3 Category = whatever the normal pipeline assigned

No separate "merchant-typical fallback" tier is needed beyond what `docs/design-data-model-api.md`
already specifies: refund transactions run through the same rule-match → LLM-fallback pipeline as
any transaction, and whatever category that assigns is the category the refund nets against. If
that categorisation was itself low-confidence, it already carries `needs_review` from the
LLM-fallback design in `docs/design-data-model-api.md` (threshold 0.7) — refund netting inherits that signal rather than duplicating
it with a second confidence system.

### 1.4 Netting semantics

`GET /summary` nets `is_refund` credits against their own category **in the period the refund
transaction itself lands in** — not retroactively restated into the original purchase's month (e.g.
bought in July, refunded in August: August's category total drops, July's is untouched). Rejected
alternative: attributing the net back to the purchase's month, which would require re-computing
already-reported historical periods every time a late refund arrives — less auditable, and directly
against NFR-6 ("rollups/netting are computed views over raw data, not mutations of it"). The simpler
rule wins.

### 1.5 Flagged, not decided

Carried forward unresolved, matching `docs/product-requirements.md` §4.2's own flag: **Medicare
benefit refunds** (bank-tagged `Refund` in the AC sample) — arguably deserve the same "lump-sum,
don't net" treatment as the ATO exception, but that's a scope decision for the requirements doc, not
this one. Left open.

## 2. Transfer detection & reconciliation logic

### 2.1 Candidate pool

Every tier below only ever considers transactions on accounts in `Account`/`AccountAlias`
(`docs/design-data-model-api.md`'s tables) as transfer candidates. This is the single mechanism that keeps J10's external
payments out — Arvan's guitar-lesson/food/birthday-trip payments, and AC's P2P reimbursements, are
never candidates in the first place because no alias for "Arvan" or "a friend" exists — not because
of a special-case exclusion rule bolted on afterward. Simpler and structurally safer than a
denylist.

### 2.2 Tier 1 — signal match (high confidence, no counterpart required)

Tags `Transfer` immediately, even if the counterpart account's statement hasn't been imported yet
(per FR-9e), using one of:

a. **Bank type/category signal** — the transaction type or bank category text already identifies a
   self-payment (`CREDIT CARD PAYMENT`, Macquarie `"Internal transfer"`-style category text).
b. **Alias match in description** — the description contains another known account's
   `AccountAlias.raw_identifier`. Must match **both shapes** seen in the real data: numeric (CC's
   masked `453030xxxxxx7128` appearing inside JC's `AUTOMATIC DRAWING` description) and name-pattern
   (NBA↔RC's match is on `"ROHAN MAYEKAR"` text, not a number — an alias-matching rule that only
   looks for digit strings would miss this real pair).
c. **Reference-number match** — extract bank reference numbers from description text (regex over
   alphanumeric tokens of minimum length, mixing letters and digits — matches the real
   `Q6957221963`/`G8844302108`/`G9089369524`-style tokens in the AC↔JC examples) and index them for
   cross-account lookup. Treated as Tier 1, not a heuristic: an identical bank-assigned reference
   number on two of the user's own accounts is a join key the bank already gave us, not a
   probabilistic guess.

Import-time behaviour: when a new statement lands, re-run Tier 1/2 matching against existing
unlinked `Transfer`-tagged rows first, before falling through to heuristic pairing against ordinary
rows — this is what lets a Tier-1 tag made before the counterpart arrived (FR-9e) get linked once it
does.

### 2.3 Tier 2 — heuristic pairing (medium/low confidence)

Runs only over the Account/AccountAlias candidate pool (§2.1). Scored on:

- **Amount**: exact match = high signal; near-equal (tolerance ≤ \$2 or 1%, whichever is larger —
  covers fees/rounding) = medium signal.
- **Date window**: same day = high; within ±2 business days = medium (covers processing lag; the
  real CC↔JC pair matched same-day, but slower interbank transfers need the wider window).
- **Sign**: must be opposite (one debit, one credit) — non-negotiable, not scored.
- **Description similarity** (optional boost, not required): shared normalized-merchant/substring
  overlap.

Three confidence bands:

| Band | Signal | Behaviour |
|---|---|---|
| High | Exact amount + same day, or any Tier-1 signal | Auto-tag `Transfer` |
| Medium | Exact amount + within window, or near-equal + same day | Auto-tag, surfaced in the review queue as a soft confirmation (not blocking) |
| Low | Near-equal amount + within window only, no other signal | **Not** auto-tagged — `needs_review=true`, suggested match shown, user confirms/rejects (J5) |

### 2.4 Decision: introduce a `TransferGroup` table

`docs/design-data-model-api.md` flagged this explicitly as an open item:
`Transaction.transfer_link_id` (a single self-FK) represents a two-leg pair cleanly, but J9's real
3-account chain (RC → MAC → MACACC, same-day, same \$1,816.50) needs more.

**Decision: yes, add `TransferGroup`.** A self-FK forces picking one "primary" leg per transaction
and a linked-list walk to render "all legs of this transfer" — awkward for exactly the case J9
describes, and it doesn't generalise past 3 without further special-casing. Instead:

- New table: **`TransferGroup`** — `id`, `detection_tier` (1 or 2, per §2.2/2.3), `confidence`,
  `created_at`.
- `Transaction.transfer_link_id` → **`Transaction.transfer_group_id`**, FK to `TransferGroup.id`.

Matching algorithm: pairwise Tier-1/Tier-2 matches build a graph (nodes = transactions, edges =
confirmed pairwise matches); each **connected component** becomes one `TransferGroup` row. A normal
two-leg transfer (CC↔JC) is simply a group with 2 members; the RC→MAC→MACACC chain is a group with
3 — no schema special-casing for chains, only the matching algorithm's graph step differs from a
naive pairwise-only approach. This also makes "show me every leg of this transfer" a single indexed
query (`WHERE transfer_group_id = X`), which both the Transfers view in the review queue (§3) and
J9's own outcome ("linked together as one chain, not just as an isolated pair") need directly.

This was a recommendation traced to `docs/design-data-model-api.md`'s explicit open item; the
reconciliation pass (2026-08-18) merged it back into that doc — the `TransferGroup` entity and the
`transfer_group_id` field/filter now live there as the source of truth for the schema itself.

### 2.5 Worked validation against the real §4.1 examples

| Example | Tier | Why |
|---|---|---|
| CC `CREDIT CARD PAYMENT +$8,050.20` ↔ JC `AUTOMATIC DRAWING -$8,050.20` | 1b | JC's description literally contains CC's masked account number `4530307001277128` |
| AC `-$5,000` ↔ JC `+$5,000`, and smaller `"AC to JC"` transfers | 1c | Identical bank reference numbers on both legs (`Q6957221963` etc.) |
| NBA `-$5,000 "Transfer To ROHAN MAYEKAR..."` ↔ RC `+$5,000 "ROHAN MAYEKARtransfer salary"` | 1b | Alias match on **name text**, not a numeric id — confirms §2.2b's dual-shape requirement |
| RC → MAC → MACACC, \$1,816.50, same day | 1b/2 + §2.4 | Pairwise matches on each leg feed the connected-components pass; one `TransferGroup` with 3 members, not 2 separate pairs |
| AC/NBA → `"ARVAN MAYEKAR"` (guitar lessons, food, birthday trip) | *not a candidate* | Arvan has no `AccountAlias` — never enters the pool (§2.1); stays `Expense` → `Kids & Family`, per J10 |
| AC's dinner-split/farewell-drinks P2P entries | *not a candidate* | Same reasoning — external counterparty, no alias, despite bank `Category` calling them `"Transfers in"`/`"Refund"` |
| RC's real tradesperson invoice, bank-labeled `"Transfers out"` | *not a candidate* | Tradesperson isn't a held account — Tier 1a's bank-text signal is **never trusted alone**; it must also pass the Account/AccountAlias check (§2.1), which this fails, so it correctly falls through to ordinary `Expense` |

The last row is the concrete justification for why §2.1's candidate-pool restriction applies to
*every* tier, including Tier 1's bank-provided signal — `docs/product-requirements.md` §4.1 already
flags bank-assigned categories as demonstrably unreliable for this purpose, and this table shows
the restriction catching that exact case.

## 3. Dashboard UX

### 3.1 Current state

Confirmed via a direct read before this design: `frontend/dashboard.py` is a single-page Streamlit
script — sidebar date-range + category filters, 3 `st.metric` cards (Total Spending/Income/Net,
computed from raw amount sign, no Transfer exclusion or refund netting today), one native
`st.bar_chart` for category spend, one raw `st.dataframe` of transactions — that reads SQLite
directly via `pd.read_sql`, bypassing the API entirely. `backend/api.py` has 3 routes today
(`POST /upload-transactions`, `GET /transactions`, `GET /summary`), none of which support
refund/transfer/correction views yet. §8's verdict (refactor, not discard) applies: the design below
builds on this scaffolding — same framework, same general shape — rather than assuming a rewrite.

### 3.2 Proposed structure: Streamlit multi-page

Move from one script to `frontend/pages/`, since scope now spans 4 distinct views plus an
embedded review queue — a single script covering all of it becomes unwieldy to reason about, let
alone extend.

**Overview (serves J2, plus J7 as a shortcut)**
- Date-range presets (This Month / Last Month / YTD / Last 12 Months / Custom) + account
  multi-select filter (default: all).
- KPI row: Income, Expense, Net — computed from `GET /summary`, which per
  `docs/design-data-model-api.md` already excludes `type=Transfer` and nets `is_refund` per §1.4
  above. This page does no
  Transfer/refund special-casing itself; it just renders what the API already computed correctly.
- Monthly trend: income vs. expense over the selected range.
- Category breakdown: **horizontal** bar chart (16 categories read poorly as a pie/donut past ~6–8
  slices; horizontal bars stay legible and sort naturally by spend), each bar clickable through to
  Category Drill-in (J3).
- **Tax Refund (YoY) shortcut** (serves J7): a filter chip, not a separate page — queries
  `GET /summary` with `category=Income, subcategory=Tax Refund, group_by=year`. J7 in
  `docs/design-journeys.md` is literally "filter Income by Tax Refund, grouped by year"; the
  architecture diagram's 5th dashboard box is the logical view this satisfies, not a mandate for its
  own route.

**Category Drill-in (serves J3, plus J4's UI extension)**
- Transaction list for the clicked category + active date range, sourced from `GET /transactions`
  filtered by `category`/`date_from`/`date_to`.
- ~~Inline badges on refund/transfer rows (e.g. "↩ refund", "⇄ transfer ↔ {other account}") so a
  linked transaction is identifiable without a separate lookup.~~ — **Corrected** 2026-08-23, during
  a `/code-review` pass on the build: this conflicts with FR-9c/FR-13 (`docs/product-requirements.md`),
  which structurally exclude `Transfer` rows from category breakdowns — and FR-14 defines drill-in
  as showing that same breakdown's transactions. Transfer rows are excluded from Drill-in entirely
  (matching `GET /summary`), not shown with a badge. Only the "↩ refund" badge stands: a refund
  keeps its category and nets within it (§1 above), so it legitimately belongs in the drill-in list.
- Inline category-correction control per row, calling `docs/design-data-model-api.md`'s
  `PATCH /transactions/{id}`. J4 wasn't given explicit UX ownership in `docs/design-journeys.md`'s
  split (the rule-learning mechanism lives in `docs/design-data-model-api.md`), but a correction has
  to be triggered from *somewhere*, and this list is its only sensible home — included here as a
  thin UI hook into that existing endpoint, not a redesign of the rule-learning loop itself.

**Needs-Review (serves J5)**
- One queue, not three separate pages — matches the architecture diagram's single `needs_review`
  box, which already combines FR-10 (low-confidence categorisation), FR-9e tier-2 (low-confidence
  transfer/refund matches, §1.2 and §2.3 above), and J8's 4 explicitly-flagged backfill items
  (`Earning>Loan`, stray `Premium_EMI>Donation`, `Misc Refund`, `ADJUSTMENT`).
- Filterable by reason (category / transfer match / refund confidence / backfill-flagged) within
  the one page, rather than fragmenting into separate screens — the reviewer already has the
  relevant context from which filter they picked.
- Confirm/reject actions call `PATCH /transactions/{id}`: confirming a category may seed a new
  `CategorisationRule` (the rule-learning loop in `docs/design-data-model-api.md`); confirming a
  suggested transfer match writes `transfer_group_id` (§2.4) and both/all legs leave the queue
  together.

**Portfolio / Asset View (serves J6)**
- Asset selector: full-portfolio rollup, or filter to one `Asset` (e.g. "Hillside", "NAB Shares").
- Associated income/expense transactions and net cash flow via
  `GET /assets/{id}/transactions`.

### 3.3 Chart library

No chart library beyond Streamlit's native `st.bar_chart` exists today. Recommend keeping it for a
first cut — zero new dependencies, matches current scaffolding, and every chart above (trend,
category breakdown) is expressible natively. Flag `st.plotly_chart` (Plotly) as the upgrade path
once click-to-drill-down interactivity is wanted (native `st.bar_chart` has no click events) — not
required to ship the views above.

## 4. Cross-cutting notes

- **Field-name discipline**: every field referenced above (`type`, `is_refund`, `needs_review`,
  `asset_id`, `source`, `CategorisationRule`, `Account`/`AccountAlias`) is
  `docs/design-data-model-api.md`'s, used as given. The one new concept this doc introduces —
  `TransferGroup`, and renaming `transfer_link_id`→`transfer_group_id` — is explicitly flagged as a
  recommendation answering that doc's own open item (§2.4), not asserted as already-final; the
  reconciliation pass merges it.
- **Flagged, not decided** (carried forward, not resolved by this doc): Medicare benefit refunds
  (§1.5).
- **Tunable defaults, not locked**: transfer amount tolerance (≤\$2 or 1%), transfer date window
  (±2 business days), LLM confidence threshold (0.7, defined in `docs/design-data-model-api.md`,
  referenced not redefined here). Revisit once real data volume exists in Build (step 6).
