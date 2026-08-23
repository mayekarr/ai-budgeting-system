from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.models import Account, AccountAlias, Base, Transaction
from transfers.detection import process_transfer_detection


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as s:
        yield s


def _account_with_alias(session, name, raw_identifier):
    account = Account(name=name, institution="NAB", owner="Rohan", account_type="Everyday")
    session.add(account)
    session.flush()
    session.add(AccountAlias(account_id=account.id, raw_identifier=raw_identifier))
    session.commit()
    return account


def _tx(session, account, d, amount, raw_description, raw_transaction_type=""):
    tx = Transaction(
        account_id=account.id, date=d, amount=amount, raw_description=raw_description,
        raw_transaction_type=raw_transaction_type,
    )
    session.add(tx)
    session.commit()
    return tx


def test_cc_jc_credit_card_payment_pair_links_via_masked_account_number(session):
    cc = _account_with_alias(session, "CC", "453030xxxxxx7128")
    jc = _account_with_alias(session, "JC", "147912573")

    tx_cc = _tx(session, cc, date(2026, 8, 5), 8050.20, "DIRECT DEBIT PAYMENT", "CREDIT CARD PAYMENT")
    tx_jc = _tx(session, jc, date(2026, 8, 5), -8050.20,
                "4530307001277128 NAB CARD AUTOPAY MRS ANILA ROHAN", "AUTOMATIC DRAWING")

    process_transfer_detection(session, tx_cc)
    process_transfer_detection(session, tx_jc)

    session.refresh(tx_cc)
    session.refresh(tx_jc)
    assert tx_cc.type == "Transfer"
    assert tx_jc.type == "Transfer"
    assert tx_cc.transfer_group_id is not None
    assert tx_cc.transfer_group_id == tx_jc.transfer_group_id


def test_ac_jc_transfer_pair_links_via_shared_reference_number(session):
    ac = _account_with_alias(session, "AC", "147912186")
    jc = _account_with_alias(session, "JC", "147912573")

    tx_ac = _tx(session, ac, date(2026, 8, 13), -5000.00,
                "ONLINE J6657692287 Trans salary MAYEKAR A", "TRANSFER DEBIT")
    tx_jc = _tx(session, jc, date(2026, 8, 13), 5000.00,
                "ONLINE J6657692287 Trans salary MAYEKAR A", "TRANSFER CREDIT")

    process_transfer_detection(session, tx_ac)
    process_transfer_detection(session, tx_jc)

    session.refresh(tx_ac)
    session.refresh(tx_jc)
    assert tx_ac.transfer_group_id == tx_jc.transfer_group_id
    assert tx_ac.type == "Transfer"


def test_nba_rc_transfer_pair_links_via_name_text_alias_not_a_number(session):
    nba = _account_with_alias(session, "NBA", "ROHAN MAYEKAR")
    rc = _account_with_alias(session, "RC", "133500607")

    tx_nba = _tx(session, nba, date(2026, 8, 5), -5000.00,
                 "Transfer To ROHAN MAYEKAR PayID Phone from CommBank App transfer salary")
    tx_rc = _tx(session, rc, date(2026, 8, 5), 5000.00, "ROHAN MAYEKARtransfer salary", "TRANSFER CREDIT")

    process_transfer_detection(session, tx_nba)
    process_transfer_detection(session, tx_rc)

    session.refresh(tx_nba)
    session.refresh(tx_rc)
    assert tx_nba.transfer_group_id == tx_rc.transfer_group_id


def test_three_account_chain_rc_to_mac_leg_links_via_tier1_text_signal(session):
    # Real §4.1 example, RC -> MAC -> MACACC, all same day, all $1,816.50. Empirically, only the
    # RC->MAC leg carries a clean Tier-1 text signal ("Macquarie CM Acc" naming the counterpart
    # account in RC's own description). The MAC->MACACC leg has no shared reference number and no
    # alias text identifying the other side in what the real export actually contains — only
    # same-day/same-amount coincidence, which is Tier-2's heuristic job (deferred to increment 4 /
    # J5), not something Tier-1 signal matching can honestly claim. This test asserts what Tier-1
    # actually delivers on this real example, not an idealized full chain.
    rc = _account_with_alias(session, "RC", "133500607")
    mac = _account_with_alias(session, "MAC", "Macquarie CM Acc")
    macacc = _account_with_alias(session, "MACACC", "Macquarie Cash Management Accelerator Account")

    tx_rc = _tx(session, rc, date(2026, 7, 27), -1816.50,
                "ANILA ROHAN MAYEKAR R7974261326 Macquarie CM Acc", "TRANSFER DEBIT")
    tx_mac_in = _tx(session, mac, date(2026, 7, 27), 1816.50, "Mr Rohan Ashok Mayekar Macquarie Cm Acc")
    tx_mac_out = _tx(session, mac, date(2026, 7, 27), -1816.50,
                      "To Rohan Mayekar & Anila Rohan Mayekar - Internal transfer")
    tx_macacc = _tx(session, macacc, date(2026, 7, 27), 1816.50, "From Rohan Mayekar & Anila Rohan Mayekar")

    for tx in (tx_rc, tx_mac_in, tx_mac_out, tx_macacc):
        process_transfer_detection(session, tx)

    # RC <-> MAC(in) link via the Tier-1 alias-in-description signal.
    assert tx_rc.transfer_group_id is not None
    assert tx_rc.transfer_group_id == tx_mac_in.transfer_group_id
    assert tx_rc.type == "Transfer"

    # MAC(out) <-> MACACC has no Tier-1 signal in the real data available here; correctly stays
    # unlinked for now rather than being guessed at without a genuine signal (FR-10's spirit).
    assert tx_mac_out.transfer_group_id is None
    assert tx_macacc.transfer_group_id is None


def test_dependent_payment_is_never_a_transfer_candidate(session):
    # J10: Arvan isn't a registered account, so this must stay a plain Expense regardless of
    # transfer-style bank wording.
    ac = _account_with_alias(session, "AC", "147912186")
    tx = _tx(session, ac, date(2026, 8, 4), -50.00,
             "ARVAN MAYEKAR T9974201124 AC to Arvan", "TRANSFER DEBIT")

    process_transfer_detection(session, tx)

    session.refresh(tx)
    assert tx.type == "Expense"
    assert tx.transfer_group_id is None


def test_external_tradesperson_invoice_is_never_a_transfer_despite_bank_label(session):
    rc = _account_with_alias(session, "RC", "133500607")
    tx = _tx(session, rc, date(2026, 7, 31), -550.00,
             "One Solution Electr E4155106972 INV-4091", "TRANSFER DEBIT")

    process_transfer_detection(session, tx)

    session.refresh(tx)
    assert tx.type == "Expense"
    assert tx.transfer_group_id is None


def test_alias_match_with_mismatched_amount_does_not_link(session):
    # Two unrelated transactions between the same two accounts, opposite sign, in-window — but
    # different amounts. Naming a counterpart account isn't enough on its own; Tier-1 must also
    # confirm it's actually the same transfer.
    cc = _account_with_alias(session, "CC", "453030xxxxxx7128")
    jc = _account_with_alias(session, "JC", "147912573")

    tx_cc = _tx(session, cc, date(2026, 8, 5), 500.00, "DIRECT DEBIT PAYMENT", "CREDIT CARD PAYMENT")
    tx_jc = _tx(session, jc, date(2026, 8, 5), -30.00,
                "4530307001277128 UNRELATED SMALL DEBIT", "AUTOMATIC DRAWING")

    process_transfer_detection(session, tx_cc)
    process_transfer_detection(session, tx_jc)

    session.refresh(tx_cc)
    session.refresh(tx_jc)
    assert tx_cc.transfer_group_id is None
    assert tx_jc.transfer_group_id is None


def test_incidental_x_in_alias_is_not_treated_as_masking(session):
    # "AMEX" contains an 'x', but it's not a masked account number — a single incidental 'x' must
    # not trigger wildcard splitting, only a genuine masking run (3+ in a row) should.
    amex = _account_with_alias(session, "Amex", "AMEX 1234")
    other = _account_with_alias(session, "Other", "999999999")

    # This description does NOT contain "AMEX 1234" literally — under a bug that wildcard-splits
    # on every 'x', "AM" + \d* + " 1234" could spuriously match unrelated text containing those
    # fragments. It must not match here.
    tx = _tx(session, other, date(2026, 8, 5), -20.00, "AM SOMETHING ELSE 1234 UNRELATED")

    process_transfer_detection(session, tx)

    session.refresh(tx)
    assert tx.transfer_group_id is None


def test_closest_date_match_is_preferred_when_two_same_amount_transfers_exist(session):
    # Two genuinely separate real transfers of the identical amount between the same two accounts,
    # a couple of days apart. Each side must pair with its true (closest-date) counterpart, not an
    # arbitrary "first found" one that would wrongly merge two unrelated transfers into one group
    # and leave the other pair permanently unlinked.
    rc = _account_with_alias(session, "RC", "133500607")
    jc = _account_with_alias(session, "JC", "147912573")

    # RC's description names JC's alias ("147912573"), which is how the counterpart account gets
    # identified; both dates use the identical wording, so date proximity is the only thing that
    # can distinguish which JC-side row is the true match for which RC-side row.
    rc_mon = _tx(session, rc, date(2026, 8, 3), -50.00, "147912573 RC to JC transfer", "TRANSFER DEBIT")
    jc_mon = _tx(session, jc, date(2026, 8, 3), 50.00, "incoming transfer", "TRANSFER CREDIT")
    rc_wed = _tx(session, rc, date(2026, 8, 5), -50.00, "147912573 RC to JC transfer", "TRANSFER DEBIT")
    jc_wed = _tx(session, jc, date(2026, 8, 5), 50.00, "incoming transfer", "TRANSFER CREDIT")

    for tx in (rc_mon, jc_mon, rc_wed, jc_wed):
        process_transfer_detection(session, tx)

    session.refresh(rc_mon)
    session.refresh(jc_mon)
    session.refresh(rc_wed)
    session.refresh(jc_wed)

    assert rc_mon.transfer_group_id == jc_mon.transfer_group_id
    assert rc_wed.transfer_group_id == jc_wed.transfer_group_id
    assert rc_mon.transfer_group_id != rc_wed.transfer_group_id
