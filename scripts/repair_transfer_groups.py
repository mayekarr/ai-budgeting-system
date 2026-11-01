"""
Rebuild finance.db's transfer groups with the current matching rules (see transfers/repair.py).

Usage (from the repo root, with the venv active):
    python -m scripts.repair_transfer_groups [--backup db-backups/finance-YYYY-MM-DD-pre-tidy.db]

`--backup` names an older copy of finance.db taken before confident links wiped the category of their
rows; categories of rows this frees are restored from it where it has one. Back up finance.db first.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from backend.database import create_tables, session_scope
from transfers.repair import rebuild_transfer_groups


def _load_backup(path: Path) -> dict[int, tuple[str | None, str | None]]:
    with sqlite3.connect(path) as conn:
        return {
            row[0]: (row[1], row[2])
            for row in conn.execute("select id, category, subcategory from transactions")
        }


def main(argv: list[str]) -> int:
    restore = None
    if "--backup" in argv:
        position = argv.index("--backup")
        if position + 1 >= len(argv):
            print("--backup needs the path of an older copy of finance.db.")
            return 1
        path = Path(argv[position + 1])
        if not path.exists():
            print(f"No backup at {path}.")
            return 1
        restore = _load_backup(path)
    create_tables()
    with session_scope() as session:
        result = rebuild_transfer_groups(session, restore)
    for key, value in result.items():
        print(f"{key.replace('_', ' '):28}{value}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
