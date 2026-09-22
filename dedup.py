"""SQLite-backed dedup store.

Remembers listing IDs already reported, so the daily email contains only NEW
listings. `filter_new` and `mark_seen` are deliberately separate: main.py marks
listings as seen ONLY after the email is successfully sent, so a send failure
never silently swallows listings.

Cross-run persistence on GitHub Actions (which has no disk) is handled by the
workflow, which downloads/uploads this DB file as a Release asset around each run.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from models import Listing

DB_PATH = Path(__file__).with_name("seen.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_listings (
    listing_id TEXT PRIMARY KEY,
    source     TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    price_czk  INTEGER,
    url        TEXT
);
"""


def _conn(path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.execute(_SCHEMA)
    return conn


def filter_new(listings: list[Listing], path: Path = DB_PATH) -> list[Listing]:
    """Return only listings whose id is not already in the store (no writes)."""
    conn = _conn(path)
    try:
        seen = {row[0] for row in conn.execute("SELECT listing_id FROM seen_listings")}
    finally:
        conn.close()
    return [l for l in listings if l.listing_id not in seen]


def mark_seen(listings: list[Listing], path: Path = DB_PATH) -> int:
    """Record listings as seen. Idempotent (INSERT OR IGNORE). Returns rows added."""
    if not listings:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    conn = _conn(path)
    try:
        cur = conn.executemany(
            "INSERT OR IGNORE INTO seen_listings "
            "(listing_id, source, first_seen, price_czk, url) VALUES (?,?,?,?,?)",
            [(l.listing_id, l.source, now, l.price_czk, l.url) for l in listings],
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()
