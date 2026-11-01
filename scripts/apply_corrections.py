"""
Apply the per-transaction one-off tags from config/corrections.local.json (FR-9j/FR-9k).

Usage (from the repo root, with the venv active):
    python -m scripts.apply_corrections [--dry-run] [path/to/corrections.json]

Idempotent: a re-run changes 0 rows, so it is safe to replay after rebuilding finance.db. See
config/corrections.example.json for the format.
"""

from __future__ import annotations

import sys
from pathlib import Path

from backend.database import create_tables, session_scope
from categorisation.one_off_corrections import apply_corrections, load_corrections

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "corrections.local.json"


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if a != "--dry-run"]
    dry_run = "--dry-run" in argv[1:]
    path = Path(args[0]) if args else DEFAULT_CONFIG
    if not path.exists():
        print(f"No corrections file at {path}. Copy config/corrections.example.json there and fill it in.")
        return 1
    create_tables()
    with session_scope() as session:
        try:
            entries = load_corrections(path)
        except ValueError as exc:
            print(exc)
            return 1
        result = apply_corrections(session, entries, commit=False)
        if dry_run:
            session.rollback()
    print(("DRY RUN (rolled back). " if dry_run else "") +
          f"changed {result['changed']}, already applied {result['already_applied']}")
    problems = 0
    for key in ("not_found", "ambiguous", "invalid", "skipped_grouped"):
        for entry in result[key]:
            problems += 1
            if isinstance(entry, dict):
                print(f"  {key}: {entry.get('date')} {entry.get('amount')} {entry.get('description')!r}")
            else:
                print(f"  {key}: {entry!r}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
