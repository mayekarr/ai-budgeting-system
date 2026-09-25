# Next Steps

Status: Active
Last updated: 2026-09-25
Companion to: `docs/product-requirements.md` (Draft v9) — read that first for full requirements
detail; this doc is a resumable to-do list, not a requirements source of truth.

## Where things stand

Requirements gathering is well underway. Decided so far (all detailed in
`docs/product-requirements.md`):

- Categorisation method: rule-based + LLM fallback, LLM provider **decided** 2026-08-18: Claude API
  (Anthropic), for consistency with the project's own Claude-Code-based dev workflow.
- Merged taxonomy: **finalized** 2026-08-18 — 16 categories, synthesized from both manual
  references plus the 7 real bank accounts (§4.2), with a full old→new remapping table for backfill.
- Refunds: an attribute that nets against the original category, not counted as income — except a
  scoped exception for ATO tax refunds, which are `Income` (user preference, so year-on-year "how
  much tax refund" is a direct filter, not a derived/netted number).
- Investable assets: a generalised `Investment`/`Asset` entity (type + name), covering both real
  estate and shares — not a flat category.
- Historical backfill: the 13-year `Expense Log` (~14,300 transactions, 2012–2025) will be
  one-time imported and remapped into the new taxonomy.
- Inter-account transfers: a distinct `Type` (`Income`/`Expense`/`Transfer`), structurally excluded
  from income/expense totals, with two-tier detection (type/description signal, or heuristic
  pairing).
- Scope reframed: the manual `Expense Log` process is being retired entirely — going forward, bank
  statement exports across **all** accounts are the only input.

## Pending work — start here (consolidated priority order, updated 2026-09-25)

Everything still open, in one place, in the order to do it. The detailed history and reasoning for
each item lives further down this doc (and in `docs/product-requirements.md`); this list is the
index. Performance items P1–P5 come from a measured review on 2026-09-25 (Rohan reported the app
feeling slow) — kept in their recommended relative order, interleaved with the journey work by when
each one actually matters.

1. ~~**P1 — Reuse one HTTP client in the dashboard**~~ — **Done** 2026-09-25. Root cause of the
   slowness: every `httpx.get(...)`/`httpx.patch(...)` call built a brand-new client, costing
   ~202ms on this machine (~233ms per request vs ~9ms reused). `frontend/api_client.py` now holds
   one `httpx.Client` per process (`functools.cache`; `httpx.Client` is thread-safe, and Streamlit
   serves each session from its own thread). Backend read endpoints were never the problem (~10ms,
   DB indexes already in place).
2. ~~**P2 — Cache dashboard reads**~~ — **Done** 2026-09-25. The three read functions use
   `st.cache_data(ttl=30)`; all five writes now go through one `_patch_transaction` helper that
   clears every read cache — in a `finally`, so even a failed write refetches (the backend may
   have applied part of it). Errors aren't cached, so an API hiccup doesn't stick. The 30-second
   TTL exists because the dashboard has **no upload control** — statements are uploaded straight to
   the API, which the dashboard can't see, so new uploads take up to 30s (or a dashboard restart)
   to appear. (That also means `docs/demo-feature-list.md` was wrong to say "via the dashboard's
   upload control" — corrected to give the real API routes.)
   **Measured against the live backend with the real 422-row dataset, per click (Streamlit rerun),
   HEAD vs new**: Needs Review 2,644ms → **71ms**; Category Drill-in 278ms → **21ms**; Overview
   242ms → **10ms**. Overview's ~2.35s *first* render is unchanged either way — a one-off
   chart-library load on the first page in a fresh process, not API time; not in scope here.
   Tests-first: new `tests/test_frontend_api_client.py` (11 tests — one client reused across
   calls, unchanged request paths/params, cache hits/misses by argument, every write invalidating
   every read, failed write still invalidating, failed read not cached). Existing dashboard tests
   were unaffected (they patch these functions wholesale). 216 tests passing. `/code-review
   medium` — **0 findings**. One edge case it noted and deliberately left alone: with two browser
   tabs open, a read still in flight in one tab while the other saves a change could cache
   pre-change data, shown for at most 30s. Not worth the complexity for a single-user local app.
3. **J6 — Portfolio/asset view.** `Asset` entity, `GET /assets`, Portfolio page — **and** decide the
   Account↔Asset link (e.g. "JC is the account 6 Jericho Ct's rent lands in and its loan interest
   is charged from"), including whether a loan is its own `Asset`-like entity or a flag on
   `Account`, so categorisation can key off account context instead of fragile text patterns.
4. **J7 — Tax refund (YoY).** A filter on top of `GET /summary` + a chip on Overview.
5. **MAC/MACACC/NBA statement parsers** (README-documented fast-follow — only the NAB-style CC/RC/
   AC/JC formats parse today). Unblocks the full RC→MAC→MACACC transfer chain (§4.1) and should
   supply the missing counterparts for the 7 unlinked `-$5,000 "... Trans salary MAYEKAR A"` AC
   debits.
6. **`possible_transfer_no_counterpart` review reason** — explicitly deferred by Rohan until a
   complete extract from all accounts exists (i.e. after item 5). Reuse Tier-1's existing
   reference-token extraction on the "no match found" path so the queue says "looks like a
   transfer, no match found" instead of a generic flag. Must **not** change `type` or totals — only
   a real linked counterpart can safely be excluded from expenses.
7. **P3 — Remove Needs Review's per-row lookups — before J8** (moved here 2026-09-25, Rohan's
   call). One suggested-match or transfer-group fetch per queue row; return the queue with that
   data already attached, in one call (`docs/design-data-model-api.md` already plans a
   `GET /transactions/needs-review` endpoint that never got built). Re-measured after P1/P2: the 9
   lookups on today's 51-item queue cost **~17ms total**, only on a cold cache (first render or
   right after a save) — invisible today. It only pays off at scale: the lookups grow with queue
   size, so do it before J8's backfill can push hundreds of rows into Needs Review.
8. **P4 — Batch the upload pipeline's DB queries — before J8.** A 347-row upload runs 2,637 SQL
   queries (~7.6 per row: rules and accounts reloaded per row, plus per-row dedup/refund/transfer
   lookups) — ~1.1s today, fine. J8's 14,349 rows would be ~110k queries, and Tier-2 transfer
   candidate scans grow with table size. Load rules/accounts once per upload. (Same efficiency
   finding deferred back in J1.)
9. **J8 — Historical backfill** from `docs/AU COST - Manual categorisation.xlsx` (Source 2).
   Already proven valuable as a categorisation reference (the "Arvan" finding, 2026-09-25) — worth a
   broader pattern-mining pass over the whole file as part of this.
10. **P5 — Move the repo and `.venv` out of OneDrive.** Independent of everything above — can be
    done any time. Likely cause of the slow/flaky local tests (2026-08-30 note), the `git checkout`
    reflog errors (2026-09-19 note), and the repeated statement-file locks on 2026-09-25. Tradeoff:
    loses OneDrive's backup, but GitHub now covers the code (real data files are gitignored and
    would need their own backup).

**Lower priority / no deadline:**
- Dashboard read cache, multi-tab staleness (found by two `/code-review` passes on P2, 2026-09-25;
  Rohan's call: backlog, not fix now). With two browser tabs open, a read still in flight in one
  tab while the other saves a change can put pre-change data back into the shared `st.cache_data`
  just after `_patch_transaction` cleared it, so every tab shows stale numbers for up to 30s.
  Single-tab use is unaffected. Fix if it ever bites: a module-level "cache generation" counter
  bumped on every write and passed as an extra argument to the cached reads, so anything fetched
  before a write can never be served after it (~15 lines + a test).
- CI/CD: register a self-hosted runner and watch one CD run complete (see the CI/CD section below).
- Account rename/merge tooling — `unrecognised_account` rows are currently visibility-only, with
  no resolution action in the UI.
- FR-9e refinement from J1: tag a lone signal-only transaction (e.g. `CREDIT CARD PAYMENT` uploaded
  before its counterpart) as `Transfer` immediately, rather than only once both sides exist.
- Cosmetic: null out `category` once a row becomes `type=Transfer` (18 linked rows still carry a
  moot `Miscellaneous` value — invisible in every view, but misleading in a raw DB query).
- Open question (`docs/product-requirements.md` §4.2): whether Medicare benefits should get the
  same `Income` treatment as ATO tax refunds — flagged, not decided.

## Next steps (in priority order)

_History of the original build plan, kept for context. For what to do next, use "Pending work —
start here" above; it supersedes the ordering of the remaining items (J6–J8) below._

1. ~~**Provide remaining sample files**~~ — **Substantially done** 2026-08-18. 6 more real accounts
   arrived (JC, RC, AC, MAC, MACACC, NBA), covering both salary sources, 3 distinct raw export
   shapes, and confirmed real inter-account transfer examples (full detail in
   `docs/product-requirements.md` §4.1). Still open: the brokerage/property-loan accounts' own
   statements (only their cash-flow effects are visible so far) — not blocking, revisit if the
   Investment/Asset buy/sell design in step 5 needs it.

2. ~~**Finalize the merged taxonomy**~~ — **Done** 2026-08-18. 16-category final list + full old→new
   remapping table locked in `docs/product-requirements.md` §4.2/§4.2.1, grounded in the real
   category signal across all 7 sample accounts, not just the two original manual references. 4 items
   flagged for manual case-by-case review during backfill rather than a blanket rule. One scoped
   design exception: ATO tax refunds are `Income`, not netted (user preference).

3. ~~**Set up the Agentic Development Workflow**~~ — **Done** 2026-08-17. The old Cursor + OpenAI-
   API setup (`AGENTS.md`, `README_AGENTS.md`, `tools/agents.py`, `.cursor/skills/`) was retired and
   replaced with a Claude-Code-native one: root `CLAUDE.md` (always-loaded project context),
   `.claude/skills/tdd-workflow/SKILL.md` (tests-first workflow for `backend/`/`ingestion/`/
   `categorisation/`), `.claude/commands/feature.md` (`/feature` — full pipeline in one command),
   and `docs/agentic-workflow.md` (the full explanation: which primitive maps to which old role and
   why, skills vs. subagents, a worked example). Planner/Reviewer/Build&Run roles turned out not to
   need custom subagents — Claude Code's built-in Plan Mode, `/code-review`, and `run` skill already
   cover them.

4. ~~**Review existing repo code**~~ — **Done** 2026-08-17, via three parallel Explore-agent audits
   run through Plan Mode. Verdict (full detail + per-FR gaps in `docs/product-requirements.md` §8):
   `backend/models.py`/`database.py`/`api.py` and `frontend/dashboard.py` are **refactor**
   (framework scaffolding reusable, schema/logic isn't); `ingestion/csv_importer.py` and
   `categorisation/merchant_parser.py`/`categoriser.py` are **discard** (built against the
   placeholder CSV shape, wrong assumptions about the real data). Not yet executed — `backend/api.py`
   imports directly from the discard-verdict modules, so removing them now (before step 5 designs
   their replacement) would break the app rather than just leave it unfinished.

5. ~~**Design phase**~~ — **Done** 2026-08-18, run as two parallel design efforts sharing one
   storyboard so neither invented its own version of an overlapping journey:
   - `docs/design-journeys.md` — 10 user journeys, storyboarded first — the design-phase equivalent
     of writing the test before the implementation — before either architecture doc below.
   - `docs/design-data-model-api.md` — data model (`Account`/`AccountAlias`/`Transaction`/`Asset`/
     `CategorisationRule`/`TransferGroup`), API design, categorisation rule format + LLM fallback
     design (LLM provider: Claude API) — traced to J1, J4, J5, J6, J7, J8.
   - `docs/design-logic-and-ux.md` — transfer/refund matching logic (J1/J9/J10) and dashboard UX
     (J2/J3/J5/J6/J7). Dropped an earlier draft's idea of a transaction-to-transaction refund link in
     favor of category-level netting, matching the existing §4.2.1 precedent.
   - `docs/design-architecture-diagram.html` — a visual walkthrough of the full pipeline with all
     10 journeys tagged at the stage they touch.
   - `docs/design-wiring-diagram.html` — added 2026-08-18, before Build: a layered technical
     architecture diagram (client/API/service/data layers, Claude API as the one external
     dependency) plus a request-level sequence-flow diagram per journey (J1–J10), so step 6 has an
     exact call sequence to implement against, not just the conceptual pipeline view above.
   Both design docs build on the §8 code-review verdict (reuse `backend`/`frontend` scaffolding, not
   the discarded ingestion/categorisation logic) and the finalized taxonomy (§4.2). One open item —
   whether `Transaction.transfer_link_id` (a single self-FK) could represent J9's 3-account transfer
   chain — was resolved during a reconciliation pass (2026-08-18): a `TransferGroup` table was added
   instead (`Transaction.transfer_link_id` → `transfer_group_id`; `GET /transactions` gained a
   `transfer_group_id` filter), now reflected in `docs/design-data-model-api.md` as the source of
   truth for the schema. The reconciliation also confirmed the 0.7 LLM-confidence threshold and the
   transfer-matching confidence tiers are separate scales that don't collide. Both design docs are
   field-name-consistent with each other. Docs-only throughout — no code changes yet, that's step 6.

6. **Build** (next) — MVP scope per `docs/product-requirements.md` §3.1. Follows the `tdd-workflow`
   skill for `backend/`/`ingestion/`/`categorisation/`/`frontend/` interaction logic (auto-triggers
   on those paths per `CLAUDE.md`). **Journey-driven, not layered** — corrected 2026-08-18: an
   earlier layer-by-layer order (schema → ingestion → logic → API → dashboard → backfill) produced
   nothing shippable until nearly everything was built. Building by journey instead gives a walking
   skeleton — each increment is a real slice through every layer, demoable on its own, the same TDD
   instinct (prove one thing fully before the next) applied at the feature level. Not every journey
   is its own increment: **J9 (transfer chain) and J10 (dependent payment ≠ Transfer) are test
   scenarios inside J1's transfer-detection logic, not separate slices.**

   Order:
   1. ~~**J1 — Upload a statement**~~ (the walking skeleton) — **Done** 2026-08-18. New schema
      (`Account`/`AccountAlias`/`Transaction`/`TransferGroup`/`CategorisationRule` in
      `backend/models.py`) replaces the discard-verdict `ingestion/csv_importer.py` and
      `categorisation/merchant_parser.py`/`categoriser.py` (both deleted). NAB-style parser
      (`ingestion/nab_format.py`, covers CC/JC/RC/AC); rule matching seeded with 123 real rules
      derived from Source 1's actual merchant/category data, remapped to the final taxonomy
      (`categorisation/seed_rules.py`); Claude Haiku 4.5 fallback with the 0.7 threshold
      (`categorisation/claude_fallback.py`); Tier-1 transfer signal matching + refund detection
      (`transfers/detection.py`, `transfers/refunds.py`); `POST /transactions/upload` +
      `GET /transactions` (`backend/api.py`). 42 tests passing (`pytest`), including J9's chain and
      J10's Arvan-exclusion as real scenarios per the plan, plus an end-to-end smoke test against a
      real slice of `BankTransactions - CC.xlsx`.
      **Two honest gaps found and recorded, not silently absorbed:**
      (a) the real RC→MAC→MACACC chain only links RC↔MAC via Tier-1 — the MAC→MACACC leg has no
      clean text signal in the data captured so far (no shared reference number or alias text),
      only same-day/same-amount coincidence, which is Tier-2's job — deferred to step 4 (J5) as
      planned, confirmed empirically rather than assumed;
      (b) a lone signal-only transaction (e.g. `CREDIT CARD PAYMENT` uploaded before its JC
      counterpart) doesn't yet get tagged `Transfer` immediately per FR-9e's letter — it currently
      only links once both sides exist. The core linking mechanism is fully proven against every
      real paired example in §4.1; this "tag before the counterpart arrives" refinement is a
      reasonable fast-follow, not a blocker.
      `frontend/dashboard.py` is now unrunnable against the new schema, as planned — step 2 rebuilds
      it. `README.md` updated to match.
      **Follow-up fix, same day:** Rohan identified that the exact-date de-dup key misses a bank
      changing a transaction's date between pending authorization and settlement — a real,
      previously-only-flagged-in-theory case (§4.1). Fixed via a new `superseded_by_id` self-FK
      (`backend/models.py`) and symmetric pending↔settled reconciliation in `backend/database.py`
      (10-day window, chosen to cover real settlement lag while staying well short of a ~30-day
      recurring-charge gap) — both rows kept (NFR-6), only the settled one counts as active.
      **`GET /summary` (step 2 below) must filter `superseded_by_id IS NOT NULL`, same as it must
      exclude `Transfer` — noted here so it isn't rediscovered as a bug.**
      The same `/code-review` pass (run against the full increment-1 diff) surfaced 6 further
      correctness bugs, fixed together with the above since several touched the same code: ATO
      refund detection ignoring amount sign (a debit paying the ATO isn't Income), Tier-1 transfer
      matching not checking amount magnitude (only sign — two different-amount transactions could
      wrongly link), the upload handler's transfer re-scan using attempted-row-count instead of
      actually-saved rows (wrong on any upload with duplicates), `_is_duplicate` not using the
      already-captured `balance` field (two identical same-day purchases could wrongly collapse to
      one), unvalidated Claude fallback results being promoted into permanent rules even when
      taxonomy-invalid, and the alias-masking regex treating any single "x" as a wildcard (would
      mis-match a real alias like "AMEX"). 3 lower-priority efficiency findings (repeated per-row
      DB scans) were deliberately deferred — real, but negligible at this app's actual data volume;
      revisit if that changes.
      **Second `/code-review` pass, same day, against the fixed diff — 6 more findings, fixed:**
      `needs_review_count` in the upload response was a whole-table count, not this upload's
      count (misreported on every upload after the first — now computed from the rows this
      request actually saved); the ATO override left a stale `needs_review=True` on rows whose
      earlier low-confidence category it had just replaced with a confident deterministic one
      (now cleared); no error handling around reading the uploaded file or persisting it — a
      regression versus the original implementation, which had it (unhandled exceptions would
      leak as raw 500s with no rollback; now wrapped, tested by simulating a persistence failure);
      Tier-1 alias-based transfer matching could pick an arbitrary candidate when two genuinely
      separate transfers of the same amount existed between the same two accounts within the date
      window, wrongly merging them (now picks the closest-date candidate, which resolves the
      concrete two-transfer scenario without needing to touch Tier-2's territory); `match_rule`
      sorted rules twice (SQL + Python) for no reason. The remaining finding (repeated per-row DB
      scans) is the same efficiency point already deferred above — not re-litigated.
      **Third `/code-review` pass, against the fixed diff — 6 more findings, fixed:**
      `transfers/refunds.py`'s counterparty check used a plain substring match instead of the
      masking-aware matcher `transfers/detection.py` already had, so a masked alias (e.g.
      `453030xxxxxx7128`) resolved for transfers but not refunds — extracted the shared logic into
      a new `transfers/aliases.py` (also fixes a latent case: an alias that's *purely* masking
      characters with no literal digits would have degenerated into a wildcard matching every
      string; it now matches nothing instead, since it carries zero identifying signal either way);
      `ingestion/nab_format.py` stringified a blank required cell into the literal text `"nan"`
      instead of treating it as missing — a regression versus the old importer's explicit
      empty-description guard — now raises `NabFormatError` for a blank account number/transaction
      type/description, per FR-4; the pending/settled reconciliation in `backend/database.py` had
      the same arbitrary-`.first()`-pick bug just fixed in transfer detection, now given the same
      closest-date tie-break; the Claude fallback promoted rules using the full raw description as
      an exact match, which real messy NAB text (store numbers, suffixes) rarely repeats verbatim —
      undermining the module's own "never call the API twice for this merchant" claim — now asks
      Claude to also extract a stable `merchant_pattern` substring and promotes a `substring` rule
      on that instead (with a hallucination guard: falls back to the old exact-match behaviour if
      the returned pattern isn't actually present in the description it came from); the post-upload
      transfer-detection pass could overwrite a deliberately-classified ATO tax refund into a
      `Transfer` if a coincidental amount/date match existed on another account — now explicitly
      excluded. 66 tests passing.
   2. ~~**J2 + J3 — View & drill into spending**~~ — **Done** 2026-08-23. `GET /summary`
      (`backend/api.py`) buckets by `category`, not `type`: every income source is seeded under the
      `Income` category, so grouping by category alone correctly nets a genuine refund credit
      against the category it's refunding (FR-9b) rather than counting it as income — without
      touching the upload pipeline's amount-sign-based `type` assignment. `GET /transactions`
      already supported `category`/`date_from`/`date_to` filtering from J1, so J3's drill-in needed
      no new endpoint, just test coverage confirming the combination works.
      Dashboard rebuilt as a Streamlit multi-page app (`frontend/pages/`), since `frontend/
      dashboard.py` was unrunnable against the new schema as planned: **Overview**
      (KPI row + category spend breakdown chart from `GET /summary`, date-range presets) and
      **Category Drill-in** (transaction list + refund/transfer badges from `GET /transactions`).
      Both pages' category selectors are scoped to categories actually present in the selected date
      range (not the static 16-category taxonomy) plus an "All Categories" option — added after
      Rohan flagged there was no way to see everything unfiltered. Overview's list stays spend-only
      (mirrors `GET /summary`'s `by_category`, which excludes `Income`); Drill-in derives its own
      option list from the raw transaction set instead, so `Income` transactions (salary, etc.)
      remain browsable there even though Overview's spend chart doesn't surface them.
      `frontend/api_client.py` (new): the dashboard now calls the FastAPI backend over HTTP
      (`httpx`) instead of reading SQLite directly, closing a gap the design docs specified
      (`docs/design-logic-and-ux.md` §3.1) that the original `dashboard.py` never actually followed.
      19 new tests (97 total): `GET /summary` netting/filtering/sort order, pure date-range-preset
      logic, and dashboard interaction logic via Streamlit `AppTest` (category selection →
      session_state handoff, client-side filtering, empty-state handling).
      **Two `/code-review` passes, same day, against the pushed branch — 3 more findings, fixed:**
      a stale-selection bug (Streamlit persists a widget's `session_state` entry by `key=` across
      reruns and ignores `index=` once that entry exists, so a second Overview→Drill-in handoff
      with a different category left the first visit's selection stuck — fixed by syncing the
      widget's key directly whenever the incoming category changes); an AppTest false-positive
      (`AppTest.from_file()` on a subpage in isolation has no page registry, so `st.page_link`
      threw `KeyError('url_pathname')` even though the real app — loaded via its actual entrypoint
      — never hits this; no test asserted `at.exception`, so it was silently swallowed rather than
      failing loudly — both frontend test files now load via `dashboard.py` + `switch_page()`,
      matching real usage, with `at.exception` asserted throughout); and a real data-consistency
      gap — `GET /transactions` (used by Drill-in) didn't exclude `Transfer`-typed or superseded
      rows the way `GET /summary` does, so clicking a category from Overview's Transfer-excluded
      total could show a transaction that was never counted in it, or a duplicate-looking
      pending+settled pair. **Design correction, not just a bug fix**: `docs/design-logic-and-ux.md`
      §3.2 originally called for an inline "⇄ transfer" badge on Drill-in rows, but FR-9c/FR-13
      (`docs/product-requirements.md`) are explicit that Transfer rows are structurally excluded
      from category breakdowns, and FR-14 defines drill-in as showing that same breakdown's
      transactions — so Transfer rows are now excluded from Drill-in entirely (matching
      `GET /summary`) rather than shown-with-badge; the badge branch was dead code once transfers
      can't reach the page, so it was removed rather than defensively patched. A pandas gotcha
      surfaced in the process and is now moot rather than fixed-in-place: mixing `None` and a real
      int in one DataFrame column upcasts the whole column to float64 (`None` → `NaN`), and `NaN is
      not None` is `True` — the old `row.get("transfer_group_id") is not None` check would have
      badged every non-transfer row too, reproduced directly before the exclusion fix removed the
      code path. 100 tests passing.
   3. ~~**J4 — Correct a miscategorisation**~~ — **Done** 2026-08-25, on branch
      `feature/j4-correct-miscategorisation`. `PATCH /transactions/{id}` (`backend/api.py`) accepts
      `category` (required) and `subcategory` (optional); validates the pair against
      `categorisation/taxonomy.py` (400 if invalid), 404s on an unknown id, clears `needs_review`
      and sets `confidence_score=1.0` on success (the correction resolves the exact uncertainty
      FR-10's flag exists for). Writes/updates a `source=user_correction` `CategorisationRule` —
      exact match on the transaction's `raw_description`, priority `0` (below every seeded/
      llm_promoted rule, so a same-text future match takes the correction over anything automatic)
      — closing FR-9's "learn from corrections" loop the same way `claude_fallback.py`'s LLM
      promotion already does. Deliberately **not** retroactive: only future transactions with the
      same raw description benefit, matching FR-9's wording; already-imported rows with the same
      text are left as-is.
      `frontend/pages/2_Category_Drill_in.py` gained a "Correct a transaction's category" section
      below the table (shown only when the table isn't empty): a transaction picker over the
      currently-displayed rows, a category dropdown (`categorisation/taxonomy.CATEGORIES`), a
      subcategory dropdown scoped to the chosen category (reset via the same
      last-seen-value-in-session_state pattern the category filter above it already uses, since a
      category change can leave the subcategory widget's persisted key value outside the new
      option list), and a save button calling the new `frontend/api_client.correct_transaction_category`.
      Scope deliberately excludes `is_refund`/`transfer_group_id` correction — the design doc lists
      both as PATCH-settable, but they're J5's concern (resolving review-queue items), not J4's.
      16 new tests (116 total): 9 backend (`tests/test_api_transaction_correction.py` — correction,
      rule write-back incl. update-not-duplicate and outranking a seeded rule, validation, 404) + 7
      frontend `AppTest` (`tests/test_frontend_transaction_correction.py` — control visibility,
      subcategory scoping, save call args incl. no-subcategory→`None`, success/error messaging).
      One `AppTest` gotcha hit and resolved during the frontend tests: `Selectbox.select_index(i)`
      sets the widget's value to `options[i]` (the *rendered label string*), not the underlying
      option object — fine for plain-string options, but breaks a `format_func`-based selectbox
      (like the transaction picker here, which maps id→label) on the next rerun, since `format_func`
      gets called again with the label instead of the id. Tests use `.select(<id>)` instead.
      `/code-review medium` run against the full diff: 0 findings.
      **Second `/code-review` pass (default effort), same day — 3 findings, 2 fixed:** the
      find-or-create lookup for the `user_correction` rule used a case-sensitive, untrimmed `==`
      comparison, diverging from `categorisation/rules.py`'s own exact-match semantics
      (`pattern_matches`, which is case-insensitive/trimmed) — two corrections whose
      `raw_description` differed only by case/whitespace would wrongly create two overlapping
      rules; fixed with a `func.upper(func.trim(...))` comparison matching that canonical
      semantics (test added). The drill-in correction handler showed a success toast but never
      refetched, so the table above (built from a fetch that ran *before* the button handler in
      that same script pass) kept showing the pre-correction category until some later, unrelated
      interaction happened to trigger another fetch — fixed by rerunning (`st.rerun()`) after a
      successful save, with the success message deferred via `session_state` so it still renders
      after the rerun restarts the script from the top (test added, asserts the extra fetch).
      **Third finding, deliberately not fixed, documented in `backend/api.py`**: the same
      find-or-create has a check-then-act race — two concurrent `PATCH` requests for two
      transactions sharing a `raw_description` could both miss the existing rule and both insert,
      since there's no unique constraint on `(pattern, match_type, source)`. Not worth the added
      complexity for a single local user driving one correction at a time through the dashboard
      (NFR-1); revisit if this ever gets a second concurrent caller. 118 tests passing.
   4. ~~**J5 — Needs-review queue**~~ — **Built** 2026-08-30 on branch
      `feature/j5-needs-review-queue`, **merged to `main`** 2026-09-19 via PR #2 (CI green, merge
      commit `f7b7237`). Tier-2 heuristic transfer matching added to
      `transfers/detection.py` (`process_transfer_detection` falls back to it whenever Tier-1
      finds nothing): three confidence bands per `docs/design-logic-and-ux.md` §2.3 — High (exact
      amount, same day) auto-links with no review; Medium (exact amount in the ±2-business-day
      window, or near-equal amount same day) auto-links as `Transfer` but flags
      `needs_review=True` as a soft, non-blocking confirmation; Low (near-equal amount, in-window
      only) is deliberately **not** auto-tagged — flagged for review with the candidate
      recomputed on demand (`find_suggested_transfer_match`) rather than persisted, since it was
      never confirmed.
      **Schema addition beyond the design doc**: a new `Transaction.needs_review_reason` column
      (`backend/models.py`, values in the new `backend/needs_review_reasons.py`) — the design doc
      calls for the queue to be "filterable by reason" but the pre-J5 schema had no way to tell a
      low-confidence category flag apart from an unresolved-account flag or a refund-ambiguity
      flag after the fact (all three only ever showed up as the same bare `needs_review=True`
      with no other distinguishing marker). Reason precedence when more than one applies at
      upload time: `unrecognised_account` > `refund_ambiguity` > `low_confidence_category`
      (`backend/api.py`'s upload handler). A later Tier-2 medium/low transfer match
      (`_flag_transfer_match` in `transfers/detection.py`) only sets `needs_review_reason` if the
      row doesn't already have one — first reason set wins, never overwritten — after a
      `/code-review` pass caught the original always-overwrite version silently dropping an
      `unrecognised_account`/`refund_ambiguity` flag with no way to revisit it (see the review
      note below). `finance.db` was deleted and recreated fresh for this (no
      migration tooling exists in this project, and the only local copy held 4 leftover
      manual-test rows, not real backfilled data — J8 hasn't run yet).
      **`PATCH /transactions/{id}` extended** (`category`/`subcategory` now optional, not
      required, so a request can target just one concern): `is_refund` resolves refund-ambiguity
      rows; `confirm_transfer_match` resolves an already-linked Medium match (cascades
      `needs_review=False` to every leg of the group); `confirm_transfer_with_id` links a
      not-yet-linked Low suggestion at full (user-confirmed) confidence; `reject_transfer_match`
      unlinks an auto-tagged group (reverting `type` to what the amount sign implies, deleting the
      now-orphaned `TransferGroup`) or, for an unlinked Low suggestion, just dismisses the flag.
      New `GET /transactions/{id}/suggested-transfer-match` backs the Low-confidence case's UI.
      `GET /transactions` gained `needs_review_reason` and `transfer_group_id` filters.
      `frontend/pages/3_Needs_Review.py` (new): one combined queue per
      `docs/design-logic-and-ux.md` §3.2, reason-filterable, with a per-reason action — category
      correction (reusing Drill-in's pattern), refund confirm/not-a-refund, and transfer
      confirm/reject (with the suggested counterpart shown for the Low case). `unrecognised_account`
      rows (and future J8 `backfill_flagged` rows) are shown for visibility only — resolving an
      unrecognised account needs account rename/merge tooling no journey has built yet; a known,
      deliberately out-of-scope gap, not silently hidden.
      **Deliberate deviation from the design doc's literal "3 members" chain language**: the real
      RC→MAC→MACACC chain (§4.1) now fully links — MAC(out)↔MACACC complete via Tier-2 High
      (same-day/exact-amount coincidence) exactly as planned — but as **two separate 2-member
      `TransferGroup`s** (RC↔MAC(in) via Tier-1, MAC(out)↔MACACC via Tier-2), not one 3-4-member
      group. The matching algorithm's graph has transactions as nodes and pairwise matches as
      edges; MAC's inbound and outbound legs are different transaction rows with no edge between
      them (no same-account "pass-through" rule was specified), so they don't collapse into one
      connected component. Every leg is still correctly `type=Transfer` and excluded from
      Income/Expense totals either way — this is a graph-modeling gap in the design doc, not a
      functional one, and is called out in `tests/test_transfer_detection.py`'s
      `test_mac_out_macacc_leg_links_via_tier2_after_tier1_leaves_it_unlinked`.
      **Known, deliberately deferred gap**: a transaction already `needs_review` for a
      category/refund reason that later gets auto-linked as a high-confidence Transfer (Tier-1 or
      Tier-2 High) keeps that stale flag — `_link` in `transfers/detection.py` doesn't touch
      `needs_review`/`needs_review_reason` on the confidence-band-driven path, matching Tier-1's
      pre-existing behaviour rather than adding reason-aware clearing logic under time pressure.
      Real but low-priority (the row still surfaces in the queue, just under a reason that no
      longer fully applies); revisit if it causes confusion in practice.
      `/code-review medium` run against the full diff, same day — 2 findings, both fixed:
      `_find_tier2_candidates` didn't exclude a candidate already linked into some other
      `TransferGroup`, so an unrelated already-resolved transfer leg could be pulled into a new,
      unrelated group via pure amount/date coincidence — now excludes `transfer_group_id IS NOT
      NULL` rows from the candidate pool (test added:
      `test_tier2_does_not_pull_an_already_linked_transaction_into_a_new_group`); the same pass
      also caught the `needs_review_reason` overwrite bug described just above before it shipped
      (this doc's wording already reflects the fixed, non-overwriting behaviour — test added:
      `test_tier2_does_not_overwrite_an_existing_unrelated_needs_review_reason`). 152 tests
      passing after fixes.
      **Second `/code-review` pass (default effort), same day — 5 findings, all addressed:**
      `_confirm_transfer_with_id` didn't validate the given counterpart was a real, distinct
      opposite-sign transaction on a different account — a same-id/same-account/same-sign
      counterpart id would pass every existing check and produce a corrupted single-real-member
      `TransferGroup`; now rejected with 400 (3 tests added). The `needs_review_reason`
      preservation fix from the first pass was itself too broad: it preserved
      `low_confidence_category`/`refund_ambiguity` even for a Medium-band match that actually
      changes `type` to `Transfer` — since category is moot on a Transfer row (`GET /summary`
      excludes them outright) but the Needs-Review page dispatches purely on
      `needs_review_reason`, the stale reason meant the page never offered the transfer
      confirmation, and resolving the stale reason (e.g. a category fix) would clear
      `needs_review` and permanently strand the row as an unreviewed Transfer link — fixed by only
      preserving those two reasons when the match *didn't* change `type` (Low band);
      `unrecognised_account` is still never overwritten regardless of band, since it's about the
      account, not this transaction, and (per `ingestion/account_resolution.py`) is only ever
      raised once per account (2 tests added, one per band). `TransactionCorrection` had no
      `extra="forbid"` and no "at least one action" check, so a misspelled field or an empty `{}`
      body silently succeeded and changed nothing — fixed (2 tests added). The duplicated
      category/subcategory correction widget (Drill-in and Needs-Review each hand-rolled the same
      reset-on-category-change logic) was extracted into
      `frontend/category_correction.py::render_category_correction_widget`, used by both pages —
      pure reuse, no behaviour change (existing tests cover it). Finally, the deliberate
      RC→MAC→MACACC "two separate 2-member groups, not one chain" deviation from
      `docs/product-requirements.md`'s own §4.1 wording was previously only recorded in this file;
      CLAUDE.md requires updating the requirements doc too when a decision changes it, so
      §4.1 now carries the same explanation inline (a `~~struck~~` + **Built** note, matching this
      project's established doc-update pattern). 159 tests passing after this pass.
      **Third `/code-review` pass (default effort), same day — 10 findings; 8 fixed, 2 already
      documented/confirmed intended:**
      `_confirm_transfer_with_id` didn't validate the counterpart was a real, distinct opposite-
      sign transaction on a different account — a same-id/same-account/same-sign counterpart would
      pass every prior check and produce a corrupted single-real-member `TransferGroup`; now
      rejected with 400 (3 tests added). `render_category_correction_widget`'s reset-on-change
      guard fired unconditionally on first render (its `last_seen_key` marker isn't set yet), so
      it always blanked the subcategory even when `default_category` matched the transaction's
      existing, correct category — silently dropping an existing subcategory on save; fixed by
      adding a `default_subcategory` param and seeding it alongside the category on first render.
      `_confirm_transfer_match`/`_confirm_transfer_with_id`/`_reject_transfer_match` all
      unconditionally wiped `needs_review_reason` on every group member — the exact "sibling leg's
      unrelated reason gets clobbered" bug class the detection-time supersession fix (above) exists
      to prevent, just not applied to these manual action paths; fixed via a shared
      `_clear_transfer_review_flag` helper consulting the same precedence rule (4 tests added).
      That precedence rule itself was duplicated across two unrelated mechanisms (an if/elif chain
      in the upload handler vs. a frozenset + gate in detection) — consolidated into one ranked
      table (`highest_priority_reason`/`should_supersede` in `backend/needs_review_reasons.py`)
      both call sites now consult, so a future reason's precedence can't be decided inconsistently
      in two places. `_best_tier2_candidate` broke a genuine tie (e.g. two same-amount/same-day
      candidates on different accounts) via arbitrary DB row order, silently auto-linking a High
      match with no review flag when picking the true counterpart was actually ambiguous — fixed
      by detecting ties and downgrading to Medium (auto-linked but flagged) instead (test added).
      `GET /transactions/{id}/suggested-transfer-match` had no guard against being called on an
      already-linked row, which could surface an unrelated transaction as a false suggestion — now
      returns null immediately for a linked row (test added). The Needs-Review page's already-
      linked (Medium) branch showed only a bare group id, asking the user to confirm blind — now
      fetches and shows the matched counterpart's date/description/amount via the existing
      `GET /transactions?transfer_group_id=...` filter (test added). The duplicated
      `needs_review=False; needs_review_reason=None` pattern (6 call sites) was folded into the
      same shared helper above. **Confirmed already covered, no further change**: the High-band
      "stale reason on an already-needs_review row that gets auto-linked" gap is the same one this
      doc already discloses just above; a Low-band match's inability to surface a second, distinct
      reason alongside an existing one (single-field schema) is the accepted, documented
      consequence of `needs_review_reason` being one field, not a new bug — the precedence-table
      consolidation just makes that tradeoff more clearly intentional than before. 165 tests
      passing after this pass.
      **Fourth `/code-review` pass (default effort), same day — 5 findings, all fixed:**
      `_apply_category_correction` and the `is_refund` PATCH branch both still unconditionally
      cleared `needs_review`/`needs_review_reason` — the same "wipes a sibling's unrelated reason"
      bug class the third pass fixed for the transfer confirm/reject actions, just not applied to
      these two older (J4-era) paths, most exposed via Category Drill-in since (unlike
      Needs-Review) it isn't reason-gated and will happily show a correction control for a row
      whose real, live reason is `unrecognised_account`; fixed via a new `_resolve_review_flag`
      helper that only clears when the stored reason is the one the action actually addresses (2
      tests added). A genuine multi-way Tier-2 tie (e.g. one anchor transaction matching two
      same-amount/same-day candidates on different accounts) linked/flagged the winner but left
      the losing candidate completely unflagged once excluded from future candidate pools —
      `_best_tier2_candidate` now also returns the other tied candidates so `_process_tier2` can
      flag them too, unlinked (test extended). The Needs-Review page didn't exclude superseded
      (pending-shadow) rows the way Category Drill-in already does, so a row no rollup will ever
      count could still appear as an actionable item — fixed with the same client-side filter
      (test added). Five of the six action buttons had no error handling (unlike the
      category-correction save button), so a backend 400/500 would surface as a raw Streamlit
      traceback instead of an inline message — consolidated into one `_perform_action` helper used
      by all six (test added). 169 tests passing after this pass.
      **Fifth `/code-review` pass (default effort), same day — 4 findings, all fixed:**
      `unrecognised_account` outranks `transfer_match` in the precedence table (by design — it's
      never superseded), which meant a row could have a live `TransferGroup` (Tier-2 Medium
      auto-linked it) while its *displayed* reason stayed `unrecognised_account` — and that
      reason's branch offered no action at all, so a possibly-wrong auto-link had literally no way
      to be rejected. Fixed by extracting the linked-transfer confirm/reject controls into
      `_render_linked_transfer_controls` and rendering them whenever `transfer_group_id` is set,
      regardless of which reason won the display precedence race (test added). `_confirm_
      transfer_with_id` didn't exclude a superseded (PENDING-shadow) counterpart the way
      `transfers/detection.py`'s own Tier-2 candidate search does, so a stale suggestion or a
      direct PATCH call could link a row rollups already ignore into a live `TransferGroup` — now
      rejected with 400 (test added). That same handler also hand-rolled the group-creation logic
      `transfers/detection.py` already has as `_link` — renamed to the public `link_transfer_pair`
      and reused from both places, so the two can't silently drift apart. Needs-Review's own
      "Save category" button (the low-confidence-category action) was the one action left not
      using the `_perform_action` helper the fourth pass introduced specifically to consolidate
      this pattern — switched over. 171 tests passing after this pass.
   5. ~~**Compile a demo-ready feature list**~~ — **Done** 2026-09-25, `docs/demo-feature-list.md`.
      Built from a real upload run through the live app (backend + dashboard via the `run` skill),
      not written from memory. **Two real gaps found in the process, not previously exercised
      end-to-end**:
      (a) only 4 of the 7 real sample account files (CC/RC/AC/JC — all NAB-style) actually parse;
      MAC/MACACC/NBA use a different export shape, confirming in practice the README's already-
      documented "Macquarie-style and headerless-CommBank-style formats are a fast-follow" gap —
      so the full RC→MAC→MACACC transfer chain (§4.1) still can't be demoed end-to-end, only the
      AC↔JC and JC↔CC pairs;
      (b) no `ANTHROPIC_API_KEY` is set in this environment (Rohan has a Claude Pro subscription,
      not separate console.anthropic.com API billing — these are different products/billing), so
      every upload with an unmatched merchant 500'd and rolled back entirely (`claude_fallback.py`
      has no error handling around the API call itself — only around file I/O/persistence, per the
      earlier J1 review fix). Worked around for this session only by stubbing
      `categorise_with_fallback` at the process level (same seam the test suite mocks) so the real
      parsing/rule-matching/transfer/refund/needs-review pipeline could still run on real data
      without a key — **not a code change**, a throwaway driver script, nothing committed. Real,
      concrete examples pulled from that run for J1 (clean rule matches, an AC↔JC salary transfer
      pair, a JC↔CC credit-card-autopay transfer pair, a Spotlight refund), J2/J3, J4 (live-tested:
      corrected `435 BOURKE STREET CAFE MELBOURNE` via `PATCH /transactions/6`, confirmed
      `needs_review` cleared and the *other two* real occurrences of the same merchant elsewhere in
      the upload stayed unchanged — confirms the "not retroactive" design decision live, not just
      by reading the code), and J5 (real `unrecognised_account`/`refund_ambiguity`/`transfer_match`
      examples — none of those three reasons touch the LLM, so they're genuine, not stub artifacts).
      **`finance.db` currently holds that stubbed run's data** — flagged prominently in the new doc
      (don't quote its Overview totals; the stub dumped every LLM-fallback row into `Miscellaneous`,
      including real salary credits that should be `Income`). Left in place rather than deleted
      (sandbox denied the delete as a destructive action outside an explicit user ask) — **before
      the real demo or before starting J6, get a real API key from console.anthropic.com, delete
      `finance.db`, and re-upload fresh** so J6's asset work and the actual demo both start from
      genuine data, not this session's placeholder categorisation.
      **Same day, follow-up**: Rohan asked for a step-by-step "how to run this demo" guide, plus a
      built-vs-coming-soon feature summary, added to the same doc rather than a separate file — a
      "What's built vs. what's coming" table (J1–J5 done, J6/J7/J8 + Phase 2 next, sourced from this
      doc so it can't drift) and an 8-step "How to run this demo" section (get/set a real API key,
      reset `finance.db`, start backend, start dashboard, upload CC→RC→AC→JC in that order and why,
      walk the journeys, shut down) upstream of the detailed per-journey talking points, so a cold
      reader (or Rohan, cold) can actually run it start to finish, not just know what to say once
      it's running.
      **Same day, second follow-up — real code fix, not just a demo workaround**: Rohan confirmed
      he will not purchase console.anthropic.com API billing, ever (Claude Pro is a separate
      product). That makes "no `ANTHROPIC_API_KEY`" this user's permanent operating mode, not a
      temporary environment gap — so `categorisation/claude_fallback.py`'s unhandled-crash-on-
      missing-auth (the 500-and-rollback behaviour from earlier this same day) is a real bug now,
      not a one-off. Fixed tests-first per the `tdd-workflow` skill (touches `categorisation/`):
      two new tests (`test_no_api_key_configured_flags_needs_review_instead_of_raising` in
      `tests/test_categorisation_claude_fallback.py`; `test_upload_succeeds_without_configured_llm_
      credentials` in `tests/test_api_upload.py`) confirmed red against the real, unmocked
      `anthropic.Anthropic()` client (no `client=` injected, `ANTHROPIC_API_KEY` explicitly
      unset) — both hit the SDK's own `TypeError` for unresolvable auth, proving the crash was real
      end-to-end, not just theorised. Fix: `categorise_with_fallback`'s API call is now wrapped in
      `except (anthropic.AnthropicError, TypeError)` — `AnthropicError` covers real API failures
      (auth rejected, network, rate limit, outage); the bare `TypeError` is the SDK's own documented
      client-side behaviour for no api_key/auth_token/credentials configured at all, raised before
      any request is sent. Either way, degrades to `category=Miscellaneous`, `confidence=0.0`,
      `needs_review=True`, no rule promoted — the same outcome a genuinely low-confidence LLM result
      already produces, just reached without ever calling the API. Verified live against the real,
      unmodified `uvicorn backend.api:app` (no stub script): a brand-new, rule-unmatched merchant
      now imports successfully and lands in the needs-review queue instead of 500ing.
      **`/code-review medium` pass 1 — 2 findings, both fixed**: (a) catching bare `TypeError`
      broadly around the API call would also swallow an unrelated future programming error (e.g. a
      bad argument to `messages.create`), silently downgrading a real bug to "flagged for review" —
      fixed by checking the exception message for the SDK's own specific "Could not resolve
      authentication method" text and re-raising anything else (test added:
      `test_unrelated_type_error_from_the_api_call_is_not_swallowed`). (b) a missing/invalid API
      credential (a systemic, every-upload outage) and a genuine low-confidence LLM judgement for
      one merchant both reported as the same `needs_review_reason=low_confidence_category`,
      indistinguishable in the queue — an operator would misdiagnose a total outage as isolated
      per-merchant uncertainty. Fixed by adding a new `needs_review_reason` value,
      `llm_unavailable` (`backend/needs_review_reasons.py`, same precedence tier as
      `low_confidence_category`), threaded from `FallbackResult.reason` through
      `backend/api.py`'s upload handler; `_resolve_review_flag` widened to accept multiple
      addressed reasons so a category correction clears either one
      (`_resolve_review_flag(tx, LOW_CONFIDENCE_CATEGORY, LLM_UNAVAILABLE)`); the Needs-Review page
      routes `llm_unavailable` through the same category-correction widget as
      `low_confidence_category`, not the `unrecognised_account` visibility-only dead end. 4 more
      tests added across the categorisation/API/frontend layers. **`/code-review medium` pass 2,
      against the fixed diff — 0 findings.** 176 tests passing (171 + 5 new across both passes).
      `docs/product-requirements.md` §4.3.1 updated with this as a standing decision (LLM fallback
      is realistically never invoked for this user; rule-based matching carries more real weight
      than originally designed for — revisit rule-seeding effort if the needs-review queue stays
      permanently large in practice, and watch the `llm_unavailable` reason specifically once it
      exists as a queue filter). `docs/demo-feature-list.md`'s run guide and J1/J5 sections updated
      to drop the mandatory-API-key framing, the now-unnecessary stub script, and to name
      `llm_unavailable` as the reason this demo will show most.
      **Same day, third follow-up — a round of real defects found running the actual demo, not
      code review**: Rohan ran the live app after the `llm_unavailable` fix and reported "a lot of
      defects", starting with Overview's `total_income` KPI reading $0 despite real salary/dividend
      rows in the uploaded data. Root cause, confirmed against the live `finance.db`: the 123 seed
      rules were derived only from Source 1 (CC, a credit card — zero income rows ever pass through
      a credit card), so there was **zero rule coverage for the `Income` category** — and with the
      LLM fallback now permanently unavailable, every real income transaction had no path to ever
      be recognised, landing in `Miscellaneous` forever. Fixed tests-first: three new seed rules
      for the real, unambiguous, bank/processor-labelled patterns actually present in the AC/JC
      data (`SALARY/WAGES` → Income/Salary, `NAB INTERIM DIV` and `EQUATEPLUS DIVIDENDS` → Income/
      Dividends & Distributions) — deliberately **not** a blanket rule catching every credit, since
      the same real data has plenty of genuinely ambiguous credits (informal friend repayments, an
      unlinked transfer leg) that correctly belong in the needs-review queue, not force-categorised.
      `total_income` went from $0 to $48,585.90 against the real uploaded data (12 rows now
      correctly `category=Income`). Test: `test_summary_includes_earnings_breakdown_by_subcategory`
      plus a full upload-to-summary end-to-end test with no API key configured, matching this user's
      real environment.
      Rohan then asked for a drill-down for earnings (mirroring Category Drill-in's spend UX).
      Added `by_income_category` to `GET /summary` (Income rows grouped by `subcategory` — Salary/
      Dividends/Tax Refund/... is the meaningful earnings axis, since every income row already
      shares `category=Income`) and a new "Earnings by Source" chart on Overview. Deliberately
      reused the *existing* "Drill into a category" selector/link for the actual drill-through
      (append `"Income"` to its options) rather than adding a second, competing selector — two
      unconditional "sync `drill_in_category` on every render" writers side by side would race each
      other for control of the same `st.session_state` key every rerun, silently breaking whichever
      one rendered first. `Category Drill-in` already listed Income as a selectable category and
      showed `subcategory` per row (built in J2/J3, just never linked from Overview) — no change
      needed there.
      Rohan then reported two more, both traced to real rows in the live data: (a) several more
      `SALARY/WAGES`-adjacent Income rows *still* showing `Miscellaneous`, and (b) no category for
      EMI/bank-loan payments. Investigation found these were two **different** root causes, not one:
      - (b) was simple and real: zero seed-rule coverage for `Loans & Finance`, same class of gap as
        the Income fix. Added one rule (`LOAN REPAYMENT` → Loans & Finance/Loan Repayment) for the
        real `LOAN REPAYMENT TO A/C 703206283 MAYEKAR A` EMI debit.
      - (a) turned out to be **two distinct cases**, only one of which was a real bug:
        1. **Real bug, fixed**: the two real AC↔JC "Trans salary" pairs that Tier-1 *does*
           successfully link into a `TransferGroup` still showed `Miscellaneous`/`needs_review=True`
           even after linking — `link_transfer_pair` (`transfers/detection.py`, shared by Tier-1 and
           Tier-2 High) set `type=Transfer` on both legs but never touched `needs_review` at all.
           This is the exact "known, deliberately deferred gap" already called out in this doc under
           J5 (§ above) — previously low-priority because it was rare; now common and visibly
           confusing because `llm_unavailable` fires on nearly every unmatched row. Fixed: a
           confident (Tier-1 or Tier-2 High) link now clears a pre-existing `needs_review` flag on
           both legs, using the same `should_supersede` precedence rule already used everywhere else
           in this codebase (`unrecognised_account` still never cleared). Category is moot on a
           Transfer row either way (`GET /summary` excludes `type=Transfer` outright), matching
           `docs/design-logic-and-ux.md` §2.3's own "High confidence... auto-links with no review."
           4 new tests (`test_tier1_link_clears_a_moot_pre_existing_review_reason`,
           `test_tier1_link_never_clears_unrecognised_account`,
           `test_tier2_high_band_clears_a_moot_pre_existing_review_reason`, plus strengthening the
           pre-existing Tier-2-High test which only checked the default-False case and couldn't
           actually have caught this bug).
        2. **Not a bug — a real, currently-unfixable data gap, called out rather than papered over**:
           7 more `-$5,000 "Trans salary"` debits (AC-side) have **no matching credit leg anywhere
           in the currently-uploaded data** — their counterpart almost certainly landed on MAC,
           MACACC, or NBA (the account export formats the parser doesn't support yet — same
           already-documented gap as the RC→MAC→MACACC chain above) or outside JC's uploaded date
           range. They correctly stay `type=Expense`, flagged `needs_review`/`llm_unavailable` —
           forcing them to `Income` or `Transfer` without a real second leg would be actively wrong,
           not a fix. Revisit once MAC/MACACC/NBA parsing exists (or more months of JC/AC data).
      `/code-review medium` run against this diff — **0 findings** (a fourth clean pass in a row on
      this session's work). 186 tests passing (171 → 186 across this whole session's follow-ups).
      `finance.db` reset and the 4 real files (CC/RC/AC/JC) re-uploaded after each fix so the live
      demo reflects current behaviour — both new seed rules and the transfer-link fix only apply
      going forward through the upload pipeline, not retroactively to already-persisted rows.
      **Same day, fourth follow-up — one more defect-triage round**: Rohan kept driving the live
      app and found three more real rows still in `Miscellaneous`: (a) a $5,000 "ROHAN MAYEKARtransfer
      salary" credit (RC account) with no matching debit anywhere in the uploaded data; (b) a
      $2,704.86 "6 Jericho Ct Berwi The Apostoli Gro..." credit (JC account); (c) two
      "INTEREST CHARGED FROM A/C ..." debits (JC account). Unlike the earlier fixes, (a) and (b)
      were genuine judgement calls, not derivable from the data alone — asked Rohan directly rather
      than guess:
      - (a) confirmed **genuine income**, not an internal transfer: Rohan's employer pays into a
        CBA account not yet sampled in `transaction-files/`, which then moves to RC under this
        text — the RC-side credit is currently the *only* visible record of that income. New seed
        rule: `TRANSFER SALARY` → Income/Salary (deliberately distinct substring from Anila's own
        already-correctly-linked `Trans salary` transfer pattern, so it can't collide).
      - (b) confirmed real investment-property rent; Rohan asked for a proper `Rental Income`
        subcategory rather than filing it under the generic `Other`, even though Income's
        subcategory list was explicitly marked finalized 2026-08-18 — added, and
        `docs/product-requirements.md` §4.2's table updated (the one addition since finalization).
        New seed rule: `THE APOSTOLI GRO` (the managing agent's name) → Income/Rental Income.
      - (c) unambiguous, same pattern as the `LOAN REPAYMENT` fix already made: new seed rule
        `INTEREST CHARGED` → Loans & Finance/Loan Interest.
      3 new tests (`test_rohan_transfer_salary_credit_matches_to_income`,
      `test_investment_property_rent_credit_matches_to_income_rental`,
      `test_loan_interest_charge_matches_to_loans_and_finance`). `/code-review medium` run against
      this diff — **0 findings**. 189 tests passing.
      `total_income` against the real uploaded data: $48,585.90 → **$61,290.76**
      (Salary $57,797.95, Rental Income $2,704.86, Dividends & Distributions $787.95).
      **Design idea raised by Rohan, deliberately deferred to J6 rather than bolted on now**: every
      fix in both defect-triage rounds has been a text-pattern seed rule, which is inherently
      fragile (a new agent name, a new bank reference format, and the same real-world income/expense
      silently stops matching again). Rohan asked whether recording the investment property and
      loan account details explicitly would make this more robust — yes: `CategorisationRule` today
      has zero account-scoping (matches purely on description text, regardless of which `Account`
      a transaction is on), and `Account` has no link to what it represents. `docs/design-data-
      model-api.md` already designs an `Asset` entity (type + name) for J6, covering real estate and
      shares — the natural extension is linking specific `Account`s to an `Asset` (e.g., "JC is the
      account 6 Jericho Ct's rent lands in and its loan interest is charged from"), so
      categorisation/reporting could reason at the account level instead of hoping text patterns
      stay stable forever. Rohan's call: fold this into J6's design rather than design it ad hoc
      mid-fix — **J6 must now explicitly consider an Account↔Asset link (not just the Asset entity
      alone) as part of its design pass**, including whether a loan is modeled as its own
      `Asset`-like entity or a flag/link on `Account`.
      **Same day, fifth follow-up — a real architecture change, not another one-off rule**: Rohan
      then reported three more `Miscellaneous` misses (OXFAM, CHILDFUND, ALLIANZ) plus one obvious
      one (a cafe whose own name literally says "cafe") and asked directly: is
      `categorisation/rules.py` even using the bank's own `Category`/`Merchant Name` columns? It
      wasn't — `Category` was read only as a narrow refund-detection signal
      (transfers/refunds.py), and `Merchant Name` was parsed by pandas and discarded entirely,
      despite `Transaction.merchant` already existing as a column (always persisted `None`).
      Quantified before building anything: **409 of 422 real rows (97%) across CC/RC/AC/JC carry a
      non-blank bank Category**, and every manually-checked case (Donations/Oxfam, Insurance/
      Allianz, Cafe & coffee) was accurate — confirming this is a different, narrower question than
      §4.1's finding (bank categories unreliable *as a transfer/refund type signal* — a real
      invoice mislabelled "Transfers out" — says nothing about their reliability for general spend/
      income classification). After that quantified finding, Rohan's explicit instruction: use the
      bank's own data as the general mechanism instead of continuing to hand-write one-off text
      rules for every merchant found live.
      Built tests-first: `ingestion/nab_format.py`'s `ParsedRow` gained `raw_merchant` (now stored
      on `Transaction.merchant`, closing the separate discard-it gap); new
      `categorisation/bank_category.py` — a small, curated, hand-reviewed mapping from ~26 real
      observed bank `Category` values to this project's own taxonomy, **deliberately excluding**
      exactly the transfer/refund-labelled values §4.1 already found unreliable (`Internal
      transfers`/`Transfers out`/`Transfers in`/`Refund`/`Credit card repayments`) plus
      `Uncategorised` (no signal), so this doesn't reintroduce that finding. Wired into
      `backend/api.py`'s upload handler as a third categorisation tier — a `CategorisationRule`
      match (including a user correction) always wins first, this bank-category mapping is the new
      second line of defence, the Claude fallback (permanently unavailable, §4.3.1) is last —
      rather than promoting a rule the way the LLM fallback does (the bank's own data is present on
      essentially every row of a supported export already, so there's no cost to re-derive it fresh
      each upload, unlike an API call).
      8 new tests across `tests/test_ingestion_nab.py`, `tests/test_categorisation_bank_category.py`
      (new file), and `tests/test_api_upload.py`. Two `/code-review medium` passes: **pass 1 found
      1 finding** (the module-level docstring in `ingestion/nab_format.py` still claimed bank
      Category is "never trusted as the classification output," contradicting the new mechanism a
      few lines below it — fixed); **pass 2 — 0 findings**. 199 tests passing.
      **Verified live against the real uploaded data (CC/RC/AC — JC was mid-upload, file-locked by
      Excel at the time)**: `Miscellaneous` dropped to 60 of 409 rows (14.7%), and — checked, not
      assumed — every one of those 60 remaining rows' real bank `Category` value was confirmed to
      be exactly `Uncategorised` or a deliberately-excluded transfer/refund label, meaning the
      mapping isn't missing any legitimate case; what's left is genuinely unresolvable without more
      data (MAC/MACACC/NBA support) or human judgement. With JC included once unlocked: 422 total
      rows, 68 `Miscellaneous` (16.1%), `total_income` $61,290.76 (unchanged from before this round
      — JC's specific rows were already fixed by the previous round's text rules; this round's win
      is entirely on rows *those* rules didn't cover).
      **Same day, sixth follow-up — real seed-data + taxonomy-boundary fixes, not more one-off
      rules**: Rohan reviewed the remaining `Miscellaneous` rows and found: (a) "HILLS MEATS PTY
      LTDHILLS Forest Hill 036" (a butcher) miscategorised `Services & Subscriptions/Other` — a bug
      in the *original* 123-rule Source 1 seed set itself, present since the very first J1 build
      increment, not introduced this session; (b) Evie (an EV-charging network) landing in
      `Travel & Holidays/Other` via the new bank-category fallback's generic "Travel expenses"
      entry; (c) "FINANCE BY WYNDHAM PTY BUNDALL" (a timeshare finance/loan repayment) in
      `Services & Subscriptions/Other`, distinct from the real "WYNDHAM VACATION CLUBS ..."
      membership fee (correctly `Travel & Holidays/Accommodation` via the bank-category mapping,
      no text rule of its own); (d) an explicit question — is `Transport` vs. `Travel & Holidays`
      confusing? (b) and (c) were genuine judgement calls, not derivable from the data alone —
      asked Rohan directly:
      - (a) fixed: `HILLS MEATS` → Groceries (no subcategory).
      - (b) Rohan's call: EV charging is a vehicle running cost, not a trip cost. New `Car/Charging`
        subcategory added (taxonomy.py, same precedent as Rental Income); broadened
        `EVIE AUSTRALIA` (never matched the real recurring "EVIE NETWORKS BRISBANE" text) to `EVIE`
        → Car/Charging.
      - (c) Rohan's call: a loan repayment is `Loans & Finance` regardless of what asset it's
        financing, consistent with the AC property loan repayment rule already in place. Fixed
        `FINANCE BY WYNDHAM` → Loans & Finance/Loan Repayment.
      - (d) Rohan confirmed documenting the resulting boundary as explicit guidance, rather than
        leaving it implicit: `docs/product-requirements.md` §4.2 now states the working rule —
        `Transport` = everyday getting-around costs by mode, regardless of trip context;
        `Car` = vehicle ownership/running costs, regardless of trip context; `Travel & Holidays` =
        the trip itself (flights/accommodation/attractions/travel-specific financing like a
        timeshare *usage* fee) — never a transport mode, vehicle cost, or loan repayment that's
        merely incidental to (or financing) a trip.
      4 new tests, 202 tests passing pre-review. Verified live against all 4 real files fresh at
      that point: `Miscellaneous` 68/422 (16.1%, unchanged count — these 4 fixes moved specific
      rows between non-Miscellaneous categories, not out of Miscellaneous); HILLS MEATS →
      Groceries, EVIE → Car/Charging, FINANCE BY WYNDHAM → Loans & Finance/Loan Repayment all
      confirmed live.
      **`/code-review medium` pass 1 — 2 findings, both fixed**: (a) broadening `EVIE AUSTRALIA` to
      a bare substring `EVIE` also matches inside unrelated real words — "REVIEW" contains "EVIE"
      (R-**EVIE**-W) — so a bank message like "CARD REVIEW REQUIRED" would have been silently
      miscategorised Car/Charging; fixed by switching that one rule to a word-boundary regex
      (`r'\bEVIE\b'`, `match_type="regex"` — the one rule in the seed set that needs it) rather than
      plain substring (test added:
      `test_evie_rule_does_not_false_positive_on_unrelated_words_containing_the_letters`). (b) the
      new broad `ALLIANZ` rule fully subsumed a pre-existing, more specific `ALLIANZ INSURANCE`
      rule (same `Insurance`/`None` outcome for anything the old one matched) — the old rule was
      dead weight, two rules that could silently drift apart on a future edit to just one; removed
      it (test added: `test_no_duplicate_allianz_rule`). 204 tests passing.
      **`/code-review medium` pass 2 — 2 more findings, both documentation-accuracy issues from
      *earlier* rounds this session, not new bugs, both fixed**: (a) the stale-needs_review-flag
      fix's docstring (`transfers/detection.py::link_transfer_pair`, added a few rounds back)
      wrongly claimed Tier-2 Medium-band matches "go through `_flag_transfer_match` instead" of
      this function — they don't; `_process_tier2` calls `link_transfer_pair` for Medium too,
      immediately followed by `_flag_transfer_match(type_changed=True)`, which re-flags
      `needs_review` back to `True`/`TRANSFER_MATCH` right after. Today's behaviour is correct
      (existing tests `test_tier2_exact_amount_within_window_auto_links_medium_confidence_flagged`
      etc. already cover the true end state) only because those two calls always run back-to-back
      — a real landmine for a future refactor that reorders or separates them, silently leaving a
      Medium match unflagged and invisible to the Needs-Review queue. Docstring corrected to state
      this dependency explicitly as a "do not reorder without re-verifying" note, rather than
      claiming an invariant the code doesn't actually have; no behaviour change (already covered by
      existing tests). (b) the bank-category mechanism's own `ParsedRow.raw_merchant` comment
      claimed it was "consulted by categorisation/bank_category.py" — it isn't;
      `categorise_from_bank_category()` only ever reads `raw_bank_category`. Comment corrected.
      204 tests passing, unchanged (both were comment-only fixes). CC.xlsx freed up shortly after
      and was re-uploaded — all 4 real files confirmed live with this round's fixes.
      **Same day, seventh follow-up — a measurement bug on my (the assistant's) side, plus a real,
      explicitly deferred to-do**: Rohan reported seeing 50 Miscellaneous rows live, not the 68 I'd
      reported. Root cause: my "68" was a raw `category='Miscellaneous'` count across *all*
      transactions, including 18 rows that are actually `type='Transfer'` (successfully linked,
      correctly excluded from every real view — Drill-in, `GET /summary`) but still carry a
      leftover, functionally-moot `category='Miscellaneous'` text value from before they were
      linked (nothing clears `category` once a row becomes a Transfer, since it stops mattering for
      any rollup either way). 68 raw − 18 stale-but-harmless = 50, matching what Rohan actually saw
      in the UI. Not a functional bug — every view that matters already excludes these rows
      correctly — but confirms the "68" figure I'd quoted earlier this session was the wrong
      measurement to compare against the UI; `50` (Drill-in/Needs-Review-visible) is the number
      that reflects the app's real behaviour, `68` (raw DB count) doesn't. **Minor, non-blocking
      cleanup idea, not actioned**: `category` could be nulled (or left, it's harmless) on a row
      once `type` becomes `Transfer`, purely so a raw DB inspection doesn't show a misleading value
      — no user-facing effect either way.
      Separately, Rohan flagged that many of the 7 unlinked `-$5,000 "... Trans salary MAYEKAR A"`
      debits (all on the AC account, first surfaced two follow-ups ago) are confidently internal
      transfers whose credit counterparts exist in accounts not yet uploaded. Confirmed technically:
      `transfers/detection.py`'s own Tier-1 reference-token regex
      (`_REFERENCE_TOKEN_RE = r"\b[A-Za-z]{1,3}\d{6,}\b"`) extracts a real reference number from
      every one of these (e.g. `R7194058725`) — the same signal Tier-1 already uses to link a
      confirmed pair — but no transaction anywhere in the currently-uploaded data has that same
      reference number at the opposite amount, so no link is possible with the data on hand.
      **TO-DO, explicitly deferred by Rohan rather than built now — revisit once a complete extract
      from all accounts is available (i.e. once MAC/MACACC/NBA parsing exists, or more months of
      JC/AC data close the gap)**: surface this specific case as its own `needs_review_reason`
      (e.g. `possible_transfer_no_counterpart`) — reusing Tier-1's existing reference-token
      extraction even on the "no match found" path, not new detection logic — so the Needs-Review
      queue explains "this looks like a transfer, but no match was found" instead of the generic
      `llm_unavailable` flag it shows today. Deliberately would **not** change `type` or
      `total_expense` — only a confirmed, linked counterpart can safely be excluded from totals;
      this is purely about the queue explaining itself more clearly for an interim, known data gap.
      **Same day, eighth follow-up — a real find from cross-referencing historical data, not
      another live-drive report**: Rohan asked whether `docs/AU COST - Manual categorisation.xlsx`
      (Source 2, §4.2 — 14,349 real transactions, 2012-05-09 to 2025-06-07, the user's own 13-year
      manual budget, already the designated source for J8) would add value if cross-referenced
      against the current live state. Investigated by actually reading the file (`Expense Log`
      sheet), not just recalling §4.2's summary: its `Description` column is free-text shorthand the
      user typed himself ("Salary", "Transfer to Arvan", "ATO payment"), not raw bank text, and the
      date ranges don't even overlap (log ends 2025-06-07, live data starts 2026-04) — so it can't
      serve as a transaction-level cross-check. But it's valuable a different way: as 13 years of
      Rohan's own real categorisation judgement, independent of any bank-provided or rule-derived
      signal. Immediately paid off: searching it for "Arvan" (a family member) found **163
      historical rows**, consistently tracked under a dedicated `Arvan_Fees` category (Pocketmoney/
      School/Swimming/Cricket subcategories, shifting to "Transfer to Arvan" entries by 2024-2025 as
      Arvan grew older) — the *same real person* behind 13 currently-live 2026 transactions
      (`ARVAN MAYEKAR ... food`/`gym`/`trip`/`fees`), all sitting unrecognised in `Miscellaneous`
      today. Rohan's call: fix it now. New seed rule: `ARVAN` → Kids & Family (subcategory
      deliberately left unset — real 2026 spending purpose varies too much, food/gym/trip/fees, to
      force one fixed subcategory the way the historical log's own more granular per-purpose
      subcategories did; this project's current taxonomy has no exact equivalent for that
      granularity). 1 new test (`test_arvan_family_transfers_match_to_kids_and_family`, 4 real
      description variants). 205 tests passing. `/code-review medium` run against this diff —
      **0 findings**.
      **Verified live against CC/RC/AC (409 rows) — JC blocked mid-verification by an unrelated,
      real data issue, not a code problem**: 12 of the 13 real Arvan rows confirmed
      `Kids & Family`/`needs_review=False`; the 13th is on JC, which failed to re-upload with
      `"Row 3: invalid amount ' '"` — cell B3 of `transaction-files/BankTransactions - JC.xlsx`
      (the `ONLINE J6657692287 Trans salary MAYEKAR A` row, one of the two AC↔JC transfer legs
      confirmed correctly linking multiple times earlier this same session) now contains a literal
      whitespace character instead of `5000`. Not present in any earlier successful read today,
      cause unknown (the `.xlsx` files under `transaction-files/` aren't git-tracked, so there's no
      diff to inspect) — flagged to Rohan rather than silently worked around or "fixed" by the
      assistant, since it's his real source data; possibly an accidental edit from the file being
      open in Excel for an extended period this session (see the CC/RC/JC file-lock notes above).
      **Not yet resolved as of this note.**
   6. **J6 — Portfolio/asset view**. `Asset` entity, `GET /assets` endpoints, Portfolio page.
      **Scope note added 2026-09-25** (see the design-idea paragraph just above): the design pass
      must also decide how/whether to link specific `Account`s to an `Asset` (or a loan-bearing
      account to whatever represents a loan), so categorisation/reporting can key off account-level
      context instead of purely per-transaction text patterns — not just the Asset entity in
      isolation as originally scoped.
   7. **J7 — Tax refund (YoY)**. A filter on top of J2's summary endpoint + a chip on Overview.
   8. **J8 — Historical backfill**. Last, unchanged reasoning: needs the live pipeline proven on
      real imports first, and `backend/api.py` currently imports the discard-verdict
      `ingestion`/`categorisation` modules directly (§8) — those get replaced as part of step 1
      above, not removed ahead of their replacement.

   Forecasting and cloud deployment are Phase 2.

## Local test environment note (2026-08-30)

`main` was fast-forward-merged locally to `origin/main` (PR #1, J4) — full suite: 116 passed, 2
failed on first run, both pre-existing frontend `AppTest` tests unrelated to J4's diff
(`test_frontend_overview.py::test_overview_renders_kpis_from_summary`,
`test_frontend_category_drill_in.py::test_drill_in_fetches_the_date_range_unfiltered_by_category`),
both hitting Streamlit's internal 15s script-run timeout rather than a real assertion failure. On
rerun, the overview one passed (flaky) and the drill-in one failed again with the same timeout. The
full suite also took ~4.5 minutes locally — slow for ~120 tests. Suspected but not confirmed cause:
this repo lives under a OneDrive-synced folder, and OneDrive's on-access file scanning/sync can slow
local file I/O enough to blow Streamlit's fixed internal timeouts under load. Not something to fix
via test code — if it recurs, the fix (if the OneDrive theory holds) is running/cloning the repo
outside a synced folder, not adjusting test logic. CI runs on a GitHub-hosted runner (no OneDrive),
so this has never shown up there. Not blocking; noted so a slow/flaky local frontend test run isn't
mistaken for a real regression next time.

## Local environment note (2026-09-19)

While merging J5's PR (#2), two local tooling gaps surfaced, both environment-only — not code bugs:

- ~~**Local Python is broken**~~ — **Fixed** 2026-09-19: `.venv/pyvenv.cfg` pointed at
  `C:\Python313\python.exe`, which no longer existed on this machine (the venv's own recorded
  creation path also showed a different Windows username — `rohan_ow776hq` — suggesting a
  profile/path change since it was created); neither `python` nor `python3` on PATH resolved to a
  real interpreter (Windows Store stub only). Installed Python 3.11 via
  `winget install --id Python.Python.3.11`, recreated `.venv` from it, reinstalled
  `requirements.txt`; bare `pytest` (the command `CLAUDE.md` documents, venv activated) now passes
  all 171 tests locally in ~2.5 min. `.venv/` was untracked but not gitignored — added to
  `.gitignore`. Wasn't a code regression at any point — CI (GitHub-hosted runner, no local Python
  dependency) stayed green throughout and is what gated the J5 merge above.
- **`git checkout` can fail mid-switch under OneDrive sync** (`unable to append to
  '.git/logs/HEAD': Invalid argument`) — same OneDrive-sync suspicion already noted below for
  Streamlit's `AppTest` timeouts, now hitting git's own ref-log writes. No data was lost (the
  target branch ref itself is untouched; only the reflog append failed), but it leaves the
  worktree/index checked out to the target while `HEAD` still names the old branch until retried.
  Fixed by `git config core.windows.appendAtomically false`, then re-running the checkout — this
  config is now unclear if it's local-only or should go in a tracked git config; recorded here so
  a future session recognizes the error instead of assuming corruption.
- **GitHub CLI (`gh`) is now installed** (via `winget install --id GitHub.cli --source winget`) and
  authenticated as `mayekarr`, enabling PR-based merges from this session going forward (used for
  PR #2). Wasn't set up as of J4's PR #1, which had to be created/merged manually.

## CI/CD (added 2026-08-23, off `main` — not part of a numbered journey)

- **TODO, no deadline: register a self-hosted runner and confirm CD actually works.** CI is live and
  green on `main` (fixed 2026-08-23 — see below). CD is built but inert: its first-ever trigger
  (commit `c1d730d`) sat `queued` with no eligible runner and was cancelled by Rohan the same day,
  which is the correct call — nothing is lost by leaving this queued rather than configuring a
  runner under time pressure. Whenever picked back up: follow the runner setup steps below, then
  actually watch one CD run complete (not just queue) to verify or refute the process-cleanup risk
  flagged further down, before trusting it unattended.
- **CI** — `.github/workflows/ci.yml`: runs `pytest` on every push/PR to `main`, GitHub-hosted
  runner. No secrets needed — the Claude API client is always mocked in tests.
  **Broke on its first-ever real run, fixed same day (2026-08-23) — two root causes, both
  invisible locally the whole time:** (1) bare `pytest` (the command `CLAUDE.md` documents) doesn't
  add the repo root to `sys.path` the way `python -m pytest` does — every local run this project's
  been developed against used the `-m` form, so `ModuleNotFoundError` on `backend`/`frontend`/etc.
  never surfaced until CI's fresh checkout hit it. Fixed at the root with `pyproject.toml`'s
  `pythonpath = ["."]`, not by changing CI's invocation, so bare `pytest` now genuinely works
  everywhere as documented. (2) Streamlit's `AppTest.from_file`'s relative-path resolution differs
  across versions — `requirements.txt` doesn't pin `streamlit`, so CI installed a version that
  always resolves relative to the calling test file's directory, unlike the locally-installed one.
  Fixed by passing absolute paths in the two frontend AppTest test files instead of relying on
  that ambiguity. Both fixes verified against the real `pytest.exe` console script (true bare
  `pytest`, matching CI's exact invocation), not just `python -m pytest`.
- **CD** — `.github/workflows/cd.yml` + `scripts/deploy_local.ps1`: "deploy" means restart the two
  local servers with the latest code (NFR-1 — this project is local-only for the MVP, so there's no
  cloud target to push to yet). Triggers only after CI succeeds on `main`, and requires a
  **self-hosted runner registered against this repo — not yet done.** To set one up: repo Settings →
  Actions → Runners → New self-hosted runner on GitHub.com, follow the generated PowerShell
  commands, and install it as a Windows service (`./svc install` / `./svc start`) so it survives
  reboots/logouts rather than only running while a terminal is open.
- **Known risk, not yet solved**: GitHub Actions' self-hosted runner has a built-in post-job process
  cleanup that kills child processes still running when a job finishes — this would very likely kill
  the servers `deploy_local.ps1` starts the moment the CD job completes, silently defeating the
  point. Verified the script itself works standalone (`Start-Process` detachment survives the
  invoking shell exiting), but couldn't verify against an actual runner job since none is registered
  yet. The documented fix, deferred until a runner exists to test against rather than solved
  speculatively: have Windows Task Scheduler own the two server processes (independent of the
  runner's job tree) and have the CD script just stop/restart those scheduled tasks instead of
  spawning raw background processes itself.
- **Automated code review in CI — considered 2026-08-23, deferred.** Rohan asked for `/code-review`
  to gate every merge, failing CI if issues are found. Researched `anthropics/claude-code-action`
  (the official GitHub Action): it requires its own pay-as-you-go Anthropic API key (a GitHub secret
  — GitHub Actions can't use a Claude subscription, only console.anthropic.com API billing), costing
  roughly $0.20–$2 per PR reviewed. **Decided: not now** — keep `/code-review` as the manual,
  pre-merge step per `CLAUDE.md`'s existing convention, no new cost or account setup. If revisited,
  the blocking mechanism should be a required PR review (Claude submits `gh pr review
  --request-changes`/`--approve`, `main`'s branch protection requires it to pass) rather than
  parsing the action's free-text output or exit code — the latter has multiple open upstream bugs
  (spurious non-zero exits after a successful review, silent hangs), so it isn't a reliable signal
  to gate a merge on.

## Open questions still tracked

See `docs/product-requirements.md` §7 (Open Questions Log) for the full list with numbering —
currently 13 items, most already resolved and dated; remaining ones mostly depend on step 1 above.
