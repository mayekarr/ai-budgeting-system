from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.models import Base, CategorisationRule
from categorisation.rules import match_rule
from categorisation.seed_rules import SEED_RULES, seed_rules_if_empty


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as s:
        yield s


def test_seeds_rules_from_real_source1_data(session):
    inserted = seed_rules_if_empty(session)

    assert inserted == len(SEED_RULES)
    assert session.query(CategorisationRule).filter_by(source="seeded").count() == len(SEED_RULES)

    woolworths = session.query(CategorisationRule).filter_by(pattern="WOOLWORTHS").one()
    assert woolworths.category == "Groceries"


def test_seeding_is_idempotent(session):
    seed_rules_if_empty(session)
    second_call_inserted = seed_rules_if_empty(session)

    assert second_call_inserted == 0
    assert session.query(CategorisationRule).filter_by(source="seeded").count() == len(SEED_RULES)


def test_more_specific_pattern_outranks_generic_one(session):
    # UBER EATS should win over the generic UBER rule for an Uber Eats transaction.
    seed_rules_if_empty(session)

    uber_eats_rule = session.query(CategorisationRule).filter_by(pattern="UBER EATS").one()
    uber_rule = session.query(CategorisationRule).filter_by(pattern="UBER").one()
    assert uber_eats_rule.priority < uber_rule.priority


def test_salary_and_dividend_credits_match_to_income(session):
    # Source 1 (CC, a credit card) has zero income rows, so the original 123 seed rules had zero
    # Income coverage -- harmless while the Claude fallback could still recognise a salary/dividend
    # credit, but a real, silent gap now that the fallback is permanently unavailable (no API key,
    # ever -- docs/product-requirements.md §4.3.1, 2026-09-25): every real income transaction landed
    # in Miscellaneous forever, making GET /summary's total_income permanently $0 regardless of how
    # much real income exists. These three patterns are real, unambiguous, bank/processor-labelled
    # markers pulled from the real AC/JC account data (transaction-files/), not a guess -- unlike
    # the many genuinely ambiguous credits in that same data (informal repayments, unlinked transfer
    # legs), which correctly stay in the needs-review queue rather than being force-categorised.
    seed_rules_if_empty(session)

    salary_rule = session.query(CategorisationRule).filter_by(pattern="SALARY/WAGES").one()
    assert salary_rule.category == "Income"
    assert salary_rule.subcategory == "Salary"

    match = match_rule(session, "SALARY/WAGES ANILA MAYEKAR")
    assert match is not None
    assert match.category == "Income"
    assert match.subcategory == "Salary"

    for real_description in (
        "DV271/00853920 NAB INTERIM DIV ANILA MAYEKAR",
        "CPUSHAREPLANSPTYLTD26999982EquatePlus Dividends",
    ):
        match = match_rule(session, real_description)
        assert match is not None, real_description
        assert match.category == "Income"
        assert match.subcategory == "Dividends & Distributions"


def test_loan_repayment_debit_matches_to_loans_and_finance(session):
    # Same real gap as the Income patterns above, reported live by Rohan: "LOAN REPAYMENT TO A/C
    # 703206283 MAYEKAR A" (a real EMI/bank-loan debit from transaction-files/BankTransactions -
    # AC.xlsx) had zero seed-rule coverage and, with the LLM fallback permanently unavailable,
    # landed in Miscellaneous with no path to ever be recognised.
    seed_rules_if_empty(session)

    match = match_rule(session, "LOAN REPAYMENT TO A/C 703206283 MAYEKAR A")
    assert match is not None
    assert match.category == "Loans & Finance"
    assert match.subcategory == "Loan Repayment"


def test_rohan_transfer_salary_credit_matches_to_income(session):
    # Real gap reported live by Rohan, confirmed as genuine income (not an internal transfer):
    # his employer pays into a CBA account not currently sampled in transaction-files/, which then
    # moves to RC under this description -- the RC-side credit is the only record of that income
    # currently visible to this system, so it must count as Income/Salary, not sit in Miscellaneous
    # or (worse) get treated as a moot internal transfer once CBA statements are eventually added.
    seed_rules_if_empty(session)

    match = match_rule(session, "ROHAN MAYEKARtransfer salary")
    assert match is not None
    assert match.category == "Income"
    assert match.subcategory == "Salary"


def test_investment_property_rent_credit_matches_to_income_rental(session):
    # Real gap reported live by Rohan: "6 Jericho Ct Berwi The Apostoli Gro Anila Mayekar &" (a
    # real rent credit from transaction-files/BankTransactions - JC.xlsx) is rent from an
    # investment property. No "Rental Income" subcategory existed under Income before this --
    # added (Rohan's call, 2026-09-25) rather than filing it under the generic "Other".
    seed_rules_if_empty(session)

    match = match_rule(session, "6 Jericho Ct Berwi The Apostoli Gro Anila Mayekar &")
    assert match is not None
    assert match.category == "Income"
    assert match.subcategory == "Rental Income"


def test_oxfam_donation_matches_to_gifts_and_donations(session):
    # Real gap reported live by Rohan: "P0006175750 OXFAM AUSTRALIA Anila Mayekar" (JC) had zero
    # seed-rule coverage. The bank's own Category/Merchant Name columns for this exact row
    # (Donations / Oxfam Australia) confirm the classification independently.
    seed_rules_if_empty(session)

    match = match_rule(session, "P0006175750 OXFAM AUSTRALIA Anila Mayekar")
    assert match is not None
    assert match.category == "Gifts & Donations"
    assert match.subcategory == "Donations"


def test_childfund_rule_matches_the_real_transaction_text_not_just_the_seed_source(session):
    # Real gap reported live by Rohan: the existing seed rule ("CHILDFUND AUSTRALIA", derived from
    # Source 1/CC) never matches the real recurring donation text actually seen on JC --
    # "CHILDFUNDAU SURRY HILLS", no space, no spelled-out "AUSTRALIA". Broadened to the shorter,
    # still-distinctive "CHILDFUND" so one rule covers both real variants instead of two
    # overlapping ones.
    seed_rules_if_empty(session)

    for real_description in ("CHILDFUND AUSTRALIA", "CHILDFUNDAU SURRY HILLS"):
        match = match_rule(session, real_description)
        assert match is not None, real_description
        assert match.category == "Gifts & Donations"
        assert match.subcategory == "Donations"


def test_allianz_insurance_matches_to_insurance(session):
    # Real gap reported live by Rohan: "ALLIANZ AUSTRALIA INSUR SYDNEY" (recurring, CC) didn't
    # match the pre-existing 'ALLIANZ INSURANCE' rule (different real text -- "INSUR", not
    # "INSURANCE"). Subcategory left unset (None, always valid per taxonomy.is_valid_category)
    # rather than guessing which of Insurance's three subcategories this specific policy is --
    # the bank's own Category (plain "Insurance") doesn't say either.
    seed_rules_if_empty(session)

    match = match_rule(session, "ALLIANZ AUSTRALIA INSUR SYDNEY")
    assert match is not None
    assert match.category == "Insurance"


def test_no_duplicate_allianz_rule(session):
    # /code-review finding: the broader 'ALLIANZ' rule added above fully subsumes the pre-existing,
    # more specific 'ALLIANZ INSURANCE' rule (same category/subcategory outcome for anything the
    # old one matched) -- the old one is dead weight and a future edit to one could silently
    # diverge from the other. Only one ALLIANZ-pattern rule should exist.
    seed_rules_if_empty(session)

    allianz_rules = session.query(CategorisationRule).filter(
        CategorisationRule.pattern.ilike("%ALLIANZ%")
    ).all()
    assert len(allianz_rules) == 1
    assert allianz_rules[0].pattern == "ALLIANZ"


def test_generic_cafe_text_matches_as_a_last_resort_catch_all(session):
    # Real gap reported live by Rohan: "435 BOURKE STREET CAFE MELBOURNE" -- unlike the other three
    # gaps above, the bank's own Category for this exact row is "Uncategorised" (spot-checked
    # against the real xlsx), so there's no bank signal to lean on here either. A low-priority,
    # last-resort "CAFE" substring rule catches this and any future merchant whose name literally
    # says "cafe", without pre-empting a more specific named-merchant rule (e.g. a real coffee
    # chain) that should still win first.
    seed_rules_if_empty(session)

    match = match_rule(session, "435 BOURKE STREET CAFE MELBOURNE")
    assert match is not None
    assert match.category == "Cafes & Restaurants"
    assert match.subcategory == "Cafes & Coffee"

    # A specific, real named-cafe rule must still outrank the generic catch-all.
    specific = session.query(CategorisationRule).filter_by(pattern="HAVEN SPECIALTY COFFEE").one()
    generic = session.query(CategorisationRule).filter_by(pattern="CAFE").one()
    assert specific.priority < generic.priority


def test_hills_meats_butcher_matches_to_groceries_not_services(session):
    # Real defect reported live by Rohan: "HILLS MEATS PTY LTDHILLS Forest Hill 036" is a butcher
    # shop, but the *original* Source 1 seed rule (present since the very first J1 build increment,
    # not something added this session) miscategorised it as Services & Subscriptions/Other.
    seed_rules_if_empty(session)

    match = match_rule(session, "HILLS MEATS PTY LTDHILLS Forest Hill 036")
    assert match is not None
    assert match.category == "Groceries"
    assert match.subcategory is None


def test_evie_ev_charging_matches_to_car_not_travel(session):
    # Rohan's call: EV charging is a vehicle running cost, not a trip cost -- moved from the
    # generic "Travel expenses" bank-category fallback (categorisation/bank_category.py) to a
    # specific Car/Charging rule, which always wins over that fallback since rules run first.
    seed_rules_if_empty(session)

    match = match_rule(session, "EVIE NETWORKS BRISBANE")
    assert match is not None
    assert match.category == "Car"
    assert match.subcategory == "Charging"


def test_evie_rule_does_not_false_positive_on_unrelated_words_containing_the_letters(session):
    # /code-review finding: a bare 'EVIE' substring also matches inside unrelated real words --
    # "REVIEW" contains "EVIE" (R-EVIE-W) -- so this must be a word-boundary match, not a plain
    # substring, or a bank message like "CARD REVIEW REQUIRED" would be silently miscategorised.
    seed_rules_if_empty(session)

    assert match_rule(session, "CARD REVIEW REQUIRED") is None
    assert match_rule(session, "ONLINE PREVIEW STATEMENT") is None
    # The real merchant text must still match with word boundaries in place.
    assert match_rule(session, "EVIE NETWORKS BRISBANE").category == "Car"


def test_wyndham_timeshare_finance_matches_to_loans_not_services(session):
    # Rohan's call: "FINANCE BY WYNDHAM PTY BUNDALL" is structurally a loan repayment financing
    # the timeshare purchase -- distinct from "WYNDHAM VACATION CLUBS SOBUNDALL" (the membership/
    # usage fee, already correctly resolved to Travel & Holidays/Accommodation via the bank's own
    # Category field -- no text rule covers that exact merchant string, see
    # test_categorisation_bank_category.py) -- categorised consistently with the existing AC
    # property loan repayment rule (Loans & Finance/Loan Repayment), regardless of what asset the
    # loan is financing.
    seed_rules_if_empty(session)

    finance_match = match_rule(session, "FINANCE BY WYNDHAM PTY BUNDALL")
    assert finance_match is not None
    assert finance_match.category == "Loans & Finance"
    assert finance_match.subcategory == "Loan Repayment"


def test_arvan_family_transfers_match_to_kids_and_family(session):
    # Real gap surfaced by cross-referencing docs/AU COST - Manual categorisation.xlsx (13 years of
    # Rohan's own manual categorisation, see docs/next-steps.md): "Arvan" is a family member --
    # historically tracked under a dedicated Arvan_Fees category (163 rows, 2012-2025), split
    # across Pocketmoney/School/Swimming/Cricket/Medical/Shopping/Travel depending on what the
    # money was actually for. Today's real 2026 data shows the same real recurring pattern (13
    # rows, all Miscellaneous, all needs_review) -- unrecognisable to any current rule. Category
    # confidently maps to Kids & Family; subcategory deliberately left unset (None, always valid)
    # rather than guessing one fixed purpose onto genuinely varied real spending (food, gym, trip,
    # fees) -- same call as the Allianz fix.
    seed_rules_if_empty(session)

    for real_description in (
        "ARVAN MAYEKAR T9974201124 AC to Arvan",
        "ONLINE P3669392733 For Arvan MAYEKAR A",
        "Matthew Raw J3782058793 ARVAN MAYEKAR FEES",
        "ARVAN MAYEKAR L4728106053 Gym Spotify food",
    ):
        match = match_rule(session, real_description)
        assert match is not None, real_description
        assert match.category == "Kids & Family"


def test_loan_interest_charge_matches_to_loans_and_finance(session):
    # Real gap reported live by Rohan: "INTEREST CHARGED FROM A/C 34-188-5257" (a real loan
    # interest debit from transaction-files/BankTransactions - JC.xlsx) had zero seed-rule coverage
    # -- distinct from the Loan Repayment rule above (a different real subcategory, Loan Interest).
    seed_rules_if_empty(session)

    for real_description in (
        "INTEREST CHARGED FROM A/C 34-188-5257",
        "INTEREST CHARGED FROM A/C 34-189-2465",
    ):
        match = match_rule(session, real_description)
        assert match is not None, real_description
        assert match.category == "Loans & Finance"
        assert match.subcategory == "Loan Interest"
