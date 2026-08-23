# Design Phase: Data Model, API & Categorisation Rules

Status: Active
Last updated: 2026-08-18
Companion to: `docs/design-journeys.md` (the storyboard this design is derived from — read that
first), `docs/product-requirements.md` (requirements/decisions), and `docs/next-steps.md`.
This doc serves J1, J4, J5 (rule-learning half), J6, J7, J8 — see `docs/design-journeys.md` for the
journeys themselves. Docs-only; no code changes yet (step 6).

## Data model

**`Account`** (new) — `id`, `name` (e.g. "Rohan's Classic"), `institution` (NAB/Macquarie/
CommBank), `owner` (Rohan/Anila/Joint), `account_type` (Credit Card/Everyday/Cash Management/
Investment). *Serves J1.*

**`AccountAlias`** (new) — `id`, `account_id` FK, `raw_identifier` (unique). One logical `Account`
can have multiple raw identifiers as they appear across statements — `Card ending 7128` and
`453030xxxxxx7128` both alias the same NAB credit card account (§4.1, open question 9). Ingestion
resolves an incoming statement's account identifier through this table rather than assuming 1:1.
*Serves J1's account-resolution step.*

**`Transaction`** (rework of existing `backend/models.py:14-49`) — keeps `id`, `date`, `amount`,
`category`, `subcategory`, `confidence_score`, `created_at`; renames `description`→
`raw_description`; turns `account_id` (currently a bare string) into a real FK to `Account`. Adds:

| Field | Purpose | Journey |
|---|---|---|
| `merchant` | already exists, kept | J1 |
| `type` (Income/Expense/Transfer) | FR-9c | J1, J9, J10 |
| `is_refund` (bool) | FR-9b — `false` for the ATO tax-refund exception (that's `type=Income` instead) | J1, J7 |
| `transfer_group_id` (nullable FK → `TransferGroup`) | FR-9c linked pairing/chains | J1, J9 |
| `asset_id` (nullable FK → `Asset`) | §4.2 Investment/Asset entity | J1, J6 |
| `source` (bank_import/backfill) | NFR-5 auditability | J1, J8 |
| `needs_review` (bool) | FR-10, and FR-9e tier-2 low-confidence matches (the transfer/refund matching logic in `docs/design-logic-and-ux.md` writes here too) | J5 |
| `raw_transaction_type` | preserves the bank's own type string (e.g. `CREDIT CARD PURCHASE`) per FR-2 | J1 |
| `balance` (nullable) | running balance if the bank provides it | J1 |
| `superseded_by_id` (nullable self-FK) | **added 2026-08-18, build time** — links a `PURCHASE AUTHORISATION` (pending) row to its `CREDIT CARD PURCHASE` (settled) counterpart once identified, since a bank can change the transaction date on settlement, which the exact-date de-dup check in FR-3 would otherwise miss (producing a second, double-counted row). Both rows stay individually queryable (NFR-6); rollups exclude `superseded_by_id IS NOT NULL`, the same attribute-based exclusion pattern already used for `Transfer`/`is_refund` — **`GET /summary` (increment 2) must apply this filter**, not built yet. | J1 |

**`Asset`** (new — the `Investment`/`Asset` entity from §4.2) — `id`, `type` (Real Estate/Shares/
Managed Fund), `name` (Hillside/JerichoCt/Alexa/Sylvania/NAB Shares/...), `owner`, `notes`. One row
per named holding. *Serves J6.*

**`TransferGroup`** (new — added 2026-08-18 during the reconciliation pass with
`docs/design-logic-and-ux.md`) — `id`, `detection_tier` (1 or 2), `confidence`, `created_at`. One row
per matched transfer: `Transaction.transfer_group_id` FKs here instead of the originally-proposed
self-FK (`transfer_link_id`), so a group can hold 2 legs (the common pairwise case, e.g. CC↔JC) or 3+
(the real RC→MAC→MACACC same-day chain, J9) without special-casing — "show every leg of this
transfer" is one indexed query (`WHERE transfer_group_id = X`) instead of a linked-list walk.
Resolves this doc's own open item below; full reasoning (the connected-components matching algorithm
that populates it) is in `docs/design-logic-and-ux.md` §2.4. *Serves J9.*

**`CategorisationRule`** (new) — `id`, `pattern`, `match_type` (exact/substring/regex), `category`,
`subcategory`, `priority`, `source` (seeded/user_correction/llm_promoted), `is_active`. *Serves J4
directly — a correction writes here — and J1's rule-matching step.*

**Category/subcategory representation:** a Python-level constant (`categorisation/taxonomy.py`),
validated at the application layer — not a DB lookup table. 16 fixed categories (§4.2) with no
near-term need for runtime editing, consistent with this project's MVP scope. Trade-off flagged, not
silently decided: a DB table would allow renaming categories without a code deploy, at the cost of
an extra join on every categorised query. Recommend the constant.

## API design

Replaces `backend/api.py`'s 3 endpoints; keeps its FastAPI/CORS/dependency-injection scaffolding
(§8 verdict: reusable).

| Endpoint | Purpose | Journey |
|---|---|---|
| `POST /accounts` | Register an account (or auto-created on first statement upload referencing an unrecognised identifier, flagged for confirmation) | J1 |
| `GET /accounts` | List accounts | J1 |
| `POST /transactions/upload` | Upload a statement; auto-detects which of the 3 raw formats by column signature, resolves the account via `AccountAlias`, normalizes to a common shape before persisting | J1 |
| `GET /transactions` | Filterable list: `date_from`/`date_to`, `account_id`, `category`, `type`, `is_refund`, `asset_id`, `needs_review`, `transfer_group_id` (added 2026-08-18 — lets the Transfers review UI fetch every leg of a group in one call) | J2, J3, J6 |
| `PATCH /transactions/{id}` | Category correction; also settable: `is_refund`, `transfer_group_id`, for resolving review-queue items | J4, J5 |
| `GET /transactions/needs-review` | The review queue (low-confidence categorisation *and* low-confidence transfer/refund matches) | J5 |
| `GET /summary` | Income vs. expense over a period, excluding `Transfer`, net of refunds except the `Income`-classified ATO exception | J2, J7 |
| `GET /assets` / `GET /assets/{id}/transactions` | Portfolio view / single-asset drill-in | J6 |
| `POST /backfill/expense-log` | One-time historical import, applies the §4.2.1 remapping table, routes flagged items to the review queue | J8 |

## Categorisation rule format + LLM fallback design

**LLM provider: Claude API (Anthropic) — decided 2026-08-18.** Left open in §4.3.1 originally; the
`openai` dependency removed during the agentic-workflow retirement was for the old dev-tooling script
only, not a runtime commitment either way. Chosen for consistency with the project's Claude-Code-based
dev workflow. `requirements.txt` gets the `anthropic` SDK added in step 6 (Build) — this is a
docs-only design phase, no code changes here.

- **Match order** (serves J1): exact merchant match → substring/regex pattern on raw description →
  `CategorisationRule` table in `priority` order → Claude API fallback for anything unmatched.
- **Confidence:** a rule match is `confidence=1.0`, `needs_review=False`. LLM fallback returns its
  own confidence; below a threshold (proposing **0.7**, tunable) sets `needs_review=True` (J5) —
  never silently guessed (FR-10).
- **Cost control (NFR-4):** an LLM categorisation result for a novel merchant is **persisted as a new
  `CategorisationRule`** (`source=llm_promoted`), not just applied to the one transaction — so a
  repeat merchant hits the rule path next time instead of re-calling the LLM. The same mechanism
  handles J4: a user correction writes/updates a rule (`source=user_correction`), closing the
  "learn from corrections" loop FR-9 left open.
- **Seeding:** initial rules from Source 1's 137-merchant, largely self-consistent mapping (§4.2's
  audit finding) remapped to the new taxonomy, plus recurring merchants already visible in the new
  account samples (`MYKI PAYMENTS`→Transport, `WOOLWORTHS`→Groceries, etc.).

## Reconciliation with `docs/design-logic-and-ux.md` — resolved 2026-08-18

Both open items below are now resolved; `docs/design-logic-and-ux.md` is the source of truth for
the reasoning in each case, this doc just reflects the outcome (see the `TransferGroup` entity and
the `GET /transactions`/`PATCH /transactions/{id}` rows above).

- ~~`transfer_link_id` self-FK vs. a `TransferGroup` table for J9's three-leg chain~~ —
  **Resolved**: `TransferGroup` table added, `transfer_link_id` → `transfer_group_id`. The matching
  algorithm in `docs/design-logic-and-ux.md` (pairwise Tier-1/Tier-2 matches feeding a
  connected-components pass) needed a group, not a chain of self-FKs — see that doc's §2.4.
- ~~Confidence-score scale/threshold (proposed 0.7)~~ — **Confirmed, no change**: the
  matching-confidence design in `docs/design-logic-and-ux.md` (transfer amount/date tiers) is a
  separate scale from the LLM categorisation confidence this 0.7 threshold governs; the two don't
  collide, and that doc explicitly reused 0.7 by reference rather than redefining it (§4).
