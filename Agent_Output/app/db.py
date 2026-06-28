"""SQLite result cache keyed by ISO week (see docs/03 STEP 2).

Caching is best-effort (docs/05 EH-3): any SQLite error is logged and swallowed so a cache
problem can never break the app.
"""
import io
import logging
import sqlite3
from datetime import date, datetime, timezone

import pandas as pd

from app.config import DB_PATH

logger = logging.getLogger(__name__)


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cache (
            key        TEXT PRIMARY KEY,
            payload    TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def get_cache(key: str):
    """Return the cached DataFrame for `key`, or None on miss/any error (best-effort)."""
    try:
        init_db()
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT payload FROM cache WHERE key = ?", (key,)).fetchone()
        conn.close()
        if not row:
            return None
        # pandas 3.x needs a file-like object; a literal JSON string is read as a path.
        return pd.read_json(io.StringIO(row[0]))
    except Exception as e:
        logger.warning("cache read failed for %s: %s", key, e)
        return None


def set_cache(key: str, df: pd.DataFrame) -> None:
    """Write-through cache (parameterized SQL). Errors are logged and swallowed."""
    try:
        init_db()
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT OR REPLACE INTO cache(key, payload, created_at) VALUES(?, ?, ?)",
            (key, df.to_json(), datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning("cache write failed for %s: %s", key, e)


def current_week_key(prefix: str = "plan") -> str:
    # %G-W%V == ISO year and ISO week number, e.g. "2026-W26"
    return f"{prefix}:{date.today().strftime('%G-W%V')}"
