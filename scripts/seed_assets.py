"""
Set up assets and loan accounts from config/assets.local.json (J6).

Usage (from the repo root, with the venv active):
    python -m scripts.seed_assets [path/to/config.json]

Copy config/assets.example.json to config/assets.local.json and fill in real values first. Safe to
re-run after editing the file.
"""

from __future__ import annotations

import sys
from pathlib import Path

from assets.seed import load_config, seed_assets
from backend.database import create_tables, session_scope

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "assets.local.json"


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT_CONFIG
    if not path.exists():
        print(f"No config at {path}. Copy config/assets.example.json there and fill it in.")
        return 1
    create_tables()
    with session_scope() as session:
        result = seed_assets(session, load_config(path))
    print(f"Seeded {result['assets']} assets and {result['loans']} loans; asset tag changed on {result['tagged']} existing transactions.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
