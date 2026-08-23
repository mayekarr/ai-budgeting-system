from __future__ import annotations

"""
Resolves a raw account identifier from a statement (e.g. "Card ending 7128",
"453030xxxxxx7128", a plain account number) to an Account via AccountAlias.

An unrecognised identifier auto-creates a new Account + AccountAlias rather than rejecting the
upload — flagged for the user to confirm/rename later (docs/design-data-model-api.md), not blocking
ingestion on it.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.models import Account, AccountAlias


@dataclass
class ResolvedAccount:
    account: Account
    was_created: bool
    needs_review: bool


def resolve_account(session: Session, raw_identifier: str) -> ResolvedAccount:
    alias = session.query(AccountAlias).filter_by(raw_identifier=raw_identifier).one_or_none()
    if alias is not None:
        return ResolvedAccount(account=alias.account, was_created=False, needs_review=False)

    account = Account(name=raw_identifier, institution=None, owner=None, account_type=None)
    session.add(account)
    session.flush()
    session.add(AccountAlias(account_id=account.id, raw_identifier=raw_identifier))
    session.flush()

    return ResolvedAccount(account=account, was_created=True, needs_review=True)
