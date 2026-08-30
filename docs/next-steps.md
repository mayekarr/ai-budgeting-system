# Next Steps

Status: Active
Last updated: 2026-08-25
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

## Next steps (in priority order)

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
   4. ~~**J5 — Needs-review queue**~~ — **Built** 2026-08-30, on branch
      `feature/j5-needs-review-queue`. Tier-2 heuristic transfer matching added to
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
   5. **J6 — Portfolio/asset view**. `Asset` entity, `GET /assets` endpoints, Portfolio page.
   6. **J7 — Tax refund (YoY)**. A filter on top of J2's summary endpoint + a chip on Overview.
   7. **J8 — Historical backfill**. Last, unchanged reasoning: needs the live pipeline proven on
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
