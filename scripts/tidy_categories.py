"""
Bring an existing finance.db in line with the current rules, without re-uploading anything.

Usage (from the repo root, with the venv active):
    python -m scripts.tidy_categories

Does these idempotent things, in order, and prints how many rows each changed:
  1. adds any starter categorisation rule the database does not have yet;
  2. applies the rules to rows still waiting on a category (Miscellaneous / review queue);
  3. types still-unpaired card payments (DIRECT DEBIT PAYMENT, NAB CARD AUTOPAY) as Transfer, and
     tags loan drawdowns/paydowns and share-portfolio contributions as capital events;
  4. types debits to the Macquarie account as Transfer;
  5. re-pairs rows that lost their pair but still share a reference and an exact amount;
  6. clears the stale category on final (Tier-1) Transfers.
A re-run changes 0 rows. Back up finance.db first.
"""

from __future__ import annotations

import sys

from backend.database import create_tables, session_scope
from categorisation.capital_events import reclassify_capital_events
from categorisation.recategorise import recategorise_unreviewed
from categorisation.seed_rules import add_missing_seed_rules
from transfers.card_payments import reclassify_card_payments
from transfers.cleanup import clear_transfer_categories
from transfers.own_accounts import reclassify_own_account_transfers
from transfers.repair import relink_by_reference


def main() -> int:
    create_tables()
    with session_scope() as session:
        print(f"rules added:                  {add_missing_seed_rules(session)}")
        print(f"rows recategorised:           {recategorise_unreviewed(session)}")
        print(f"card payments -> Transfer:    {reclassify_card_payments(session)}")
        print(f"capital events tagged:        {reclassify_capital_events(session)}")
        print(f"own-account transfers (MAC):  {reclassify_own_account_transfers(session)}")
        print(f"re-linked by reference:       {relink_by_reference(session)}")
        print(f"transfer categories cleared:  {clear_transfer_categories(session)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
