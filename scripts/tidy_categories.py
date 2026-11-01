"""
Bring an existing finance.db in line with the current rules, without re-uploading anything.

Usage (from the repo root, with the venv active):
    python -m scripts.tidy_categories

Does these idempotent things, in order, and prints how many rows each changed:
  1. adds any starter categorisation rule the database does not have yet;
  2. applies the rules to rows still waiting on a category (Miscellaneous / review queue);
  3. types still-unpaired card payments (DIRECT DEBIT PAYMENT, NAB CARD AUTOPAY) and share-portfolio
     contributions (MLC MKIS debits) as Transfer;
  4. clears the stale category on confident Transfers.
A re-run changes 0 rows. Back up finance.db first.
"""

from __future__ import annotations

import sys

from backend.database import create_tables, session_scope
from categorisation.recategorise import recategorise_unreviewed
from categorisation.seed_rules import add_missing_seed_rules
from transfers.card_payments import reclassify_card_payments
from transfers.investment_contributions import reclassify_investment_contributions
from transfers.cleanup import clear_transfer_categories


def main() -> int:
    create_tables()
    with session_scope() as session:
        print(f"rules added:                  {add_missing_seed_rules(session)}")
        print(f"rows recategorised:           {recategorise_unreviewed(session)}")
        print(f"card payments -> Transfer:    {reclassify_card_payments(session)}")
        print(f"share contributions -> Transfer: {reclassify_investment_contributions(session)}")
        print(f"transfer categories cleared:  {clear_transfer_categories(session)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
