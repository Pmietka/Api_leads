"""
SQLite database layer for lead_tool.py.

Tables
------
zip_searches  — one row per US zip code; tracks search status and timestamp
leads         — one row per unique business (Place ID as primary key)
api_usage     — monthly free/paid call counts for quota enforcement
"""

import sqlite3
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def init_db(db_path: str) -> None:
    """Create all tables and indexes if they don't already exist."""
    conn = _connect(db_path)
    with conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS zip_searches (
                zip_code     TEXT PRIMARY KEY,
                state        TEXT NOT NULL,
                latitude     REAL NOT NULL,
                longitude    REAL NOT NULL,
                searched_at  TIMESTAMP,
                result_count INTEGER DEFAULT 0,
                status       TEXT    DEFAULT 'pending'
            );

            CREATE TABLE IF NOT EXISTS leads (
                place_id          TEXT PRIMARY KEY,
                niche             TEXT NOT NULL DEFAULT 'general',
                business_name     TEXT,
                phone             TEXT,
                website           TEXT,
                formatted_address TEXT,
                city              TEXT,
                state             TEXT,
                zip_code          TEXT,
                rating            REAL,
                review_count      INTEGER,
                source_zip        TEXT,
                created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS api_usage (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                year       INTEGER NOT NULL,
                month      INTEGER NOT NULL,
                free_calls INTEGER DEFAULT 0,
                paid_calls INTEGER DEFAULT 0,
                UNIQUE(year, month)
            );

            CREATE INDEX IF NOT EXISTS idx_leads_state      ON leads(state);
            CREATE INDEX IF NOT EXISTS idx_leads_zip        ON leads(zip_code);
            CREATE INDEX IF NOT EXISTS idx_zip_state_status ON zip_searches(state, status);
        """)
    # Migrate existing databases that don't yet have the niche column
    try:
        conn.execute("ALTER TABLE leads ADD COLUMN niche TEXT NOT NULL DEFAULT 'general'")
        conn.commit()
    except Exception:
        pass  # Column already exists — nothing to do
    # Create niche index after ensuring the column exists
    with conn:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_leads_niche ON leads(niche)"
        )
    conn.close()


# ---------------------------------------------------------------------------
# Zip code helpers
# ---------------------------------------------------------------------------

def populate_zipcodes(db_path: str, zip_list: List[Dict]) -> int:
    """
    Bulk-insert zip codes that do not yet exist in the database.
    Returns the number of newly inserted rows.
    """
    conn = _connect(db_path)
    before = conn.execute("SELECT COUNT(*) FROM zip_searches").fetchone()[0]
    with conn:
        conn.executemany(
            "INSERT OR IGNORE INTO zip_searches "
            "(zip_code, state, latitude, longitude) VALUES (?, ?, ?, ?)",
            [(z["zip_code"], z["state"], z["latitude"], z["longitude"])
             for z in zip_list],
        )
    after = conn.execute("SELECT COUNT(*) FROM zip_searches").fetchone()[0]
    conn.close()
    return after - before


def count_zips_by_state(db_path: str) -> Dict[str, int]:
    """Return {state_abbr: zip_count} for all states in the database."""
    conn = _connect(db_path)
    rows = conn.execute(
        "SELECT state, COUNT(*) AS cnt FROM zip_searches GROUP BY state"
    ).fetchall()
    conn.close()
    return {r["state"]: r["cnt"] for r in rows}


def get_pending_zips(
    db_path: str,
    states_ordered: List[str],
    refresh_days: int,
) -> List[Dict]:
    """
    Return unsearched (or stale) zip codes in the given state order.

    refresh_days=0  → only return zips that have never been searched
    refresh_days>0  → also return zips last searched more than N days ago
    """
    conn = _connect(db_path)
    result: List[Dict] = []
    for state in states_ordered:
        rows = conn.execute(
            """
            SELECT zip_code, state, latitude, longitude
            FROM   zip_searches
            WHERE  state = ?
              AND  (
                      searched_at IS NULL
                   OR (? > 0 AND searched_at < datetime('now', '-' || ? || ' days'))
                   )
            ORDER  BY zip_code
            """,
            (state, refresh_days, refresh_days),
        ).fetchall()
        result.extend(dict(r) for r in rows)
    conn.close()
    return result


def mark_zip_searched(
    db_path: str,
    zip_code: str,
    result_count: int,
    error: Optional[str] = None,
) -> None:
    """Record that a zip code search has been completed (or failed)."""
    conn = _connect(db_path)
    with conn:
        conn.execute(
            """
            UPDATE zip_searches
            SET    searched_at  = datetime('now'),
                   result_count = ?,
                   status       = ?
            WHERE  zip_code = ?
            """,
            (result_count, "error" if error else "completed", zip_code),
        )
    conn.close()


# ---------------------------------------------------------------------------
# Lead helpers
# ---------------------------------------------------------------------------

def upsert_lead(db_path: str, lead: Dict) -> bool:
    """
    Insert a lead if its place_id is not already in the database.
    Returns True if this is a new (not duplicate) lead.
    """
    conn = _connect(db_path)
    with conn:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO leads
                (place_id, niche, business_name, phone, website, formatted_address,
                 city, state, zip_code, rating, review_count, source_zip)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lead.get("place_id"),
                lead.get("niche", "general"),
                lead.get("business_name"),
                lead.get("phone"),
                lead.get("website"),
                lead.get("formatted_address"),
                lead.get("city"),
                lead.get("state"),
                lead.get("zip_code"),
                lead.get("rating"),
                lead.get("review_count"),
                lead.get("source_zip"),
            ),
        )
        inserted = cur.rowcount > 0
    conn.close()
    return inserted


def get_lead_count(db_path: str) -> int:
    conn = _connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
    conn.close()
    return count


def get_lead_count_by_state(db_path: str, state: str) -> int:
    conn = _connect(db_path)
    count = conn.execute(
        "SELECT COUNT(*) FROM leads WHERE state = ?", (state,)
    ).fetchone()[0]
    conn.close()
    return count


def get_leads_by_state(db_path: str, state: str) -> List[Dict]:
    conn = _connect(db_path)
    rows = conn.execute(
        "SELECT * FROM leads WHERE state = ? ORDER BY business_name", (state,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_leads(db_path: str) -> List[Dict]:
    conn = _connect(db_path)
    rows = conn.execute(
        "SELECT * FROM leads ORDER BY state, business_name"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_states_with_leads(db_path: str) -> List[str]:
    conn = _connect(db_path)
    rows = conn.execute(
        "SELECT DISTINCT state FROM leads WHERE state IS NOT NULL ORDER BY state"
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_niches_with_leads(db_path: str) -> List[str]:
    """Return a list of distinct niche values that have at least one lead."""
    conn = _connect(db_path)
    rows = conn.execute(
        "SELECT DISTINCT niche FROM leads WHERE niche IS NOT NULL ORDER BY niche"
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_leads_by_niche(db_path: str, niche: str) -> List[Dict]:
    """Return all leads for the given niche, ordered by state then business name."""
    conn = _connect(db_path)
    rows = conn.execute(
        "SELECT * FROM leads WHERE niche = ? ORDER BY state, business_name", (niche,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_leads_by_niche_and_state(db_path: str, niche: str, state: str) -> List[Dict]:
    """Return all leads for the given niche and state, ordered by business name."""
    conn = _connect(db_path)
    rows = conn.execute(
        "SELECT * FROM leads WHERE niche = ? AND state = ? ORDER BY business_name",
        (niche, state),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_states_with_leads_for_niche(db_path: str, niche: str) -> List[str]:
    """Return distinct states that have leads for the given niche."""
    conn = _connect(db_path)
    rows = conn.execute(
        "SELECT DISTINCT state FROM leads WHERE niche = ? AND state IS NOT NULL ORDER BY state",
        (niche,),
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# Grid point helpers (grid_search.py)
# ---------------------------------------------------------------------------

def init_grid_db(db_path: str) -> None:
    """Create all standard tables plus the grid_points table."""
    init_db(db_path)
    conn = _connect(db_path)
    with conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS grid_points (
                point_id     TEXT PRIMARY KEY,
                state        TEXT NOT NULL,
                latitude     REAL NOT NULL,
                longitude    REAL NOT NULL,
                is_dense     INTEGER DEFAULT 0,
                searched_at  TIMESTAMP,
                result_count INTEGER DEFAULT 0,
                new_count    INTEGER DEFAULT 0,
                status       TEXT DEFAULT 'pending'
            );

            CREATE INDEX IF NOT EXISTS idx_grid_state_status
                ON grid_points(state, status);
        """)
    conn.close()


def populate_grid_points(db_path: str, point_list: List[Dict]) -> int:
    """
    Bulk-insert grid points that do not yet exist in the database.
    Returns the number of newly inserted rows.
    """
    conn = _connect(db_path)
    before = conn.execute("SELECT COUNT(*) FROM grid_points").fetchone()[0]
    with conn:
        conn.executemany(
            "INSERT OR IGNORE INTO grid_points "
            "(point_id, state, latitude, longitude, is_dense) "
            "VALUES (?, ?, ?, ?, ?)",
            [(p["point_id"], p["state"], p["latitude"], p["longitude"], p["is_dense"])
             for p in point_list],
        )
    after = conn.execute("SELECT COUNT(*) FROM grid_points").fetchone()[0]
    conn.close()
    return after - before


def get_pending_grid_points(
    db_path: str,
    states_ordered: List[str],
    refresh_days: int,
) -> List[Dict]:
    """
    Return unsearched (or stale) grid points in the given state order.

    refresh_days=0  → only return points that have never been searched
    refresh_days>0  → also return points last searched more than N days ago
    """
    conn = _connect(db_path)
    result: List[Dict] = []
    for state in states_ordered:
        rows = conn.execute(
            """
            SELECT point_id, state, latitude, longitude, is_dense
            FROM   grid_points
            WHERE  state = ?
              AND  (
                      searched_at IS NULL
                   OR (? > 0 AND searched_at < datetime('now', '-' || ? || ' days'))
                   )
            ORDER  BY latitude, longitude
            """,
            (state, refresh_days, refresh_days),
        ).fetchall()
        result.extend(dict(r) for r in rows)
    conn.close()
    return result


def mark_grid_point_searched(
    db_path: str,
    point_id: str,
    result_count: int,
    new_count: int,
    error: Optional[str] = None,
) -> None:
    """Record that a grid point search has been completed (or failed)."""
    conn = _connect(db_path)
    with conn:
        conn.execute(
            """
            UPDATE grid_points
            SET    searched_at  = datetime('now'),
                   result_count = ?,
                   new_count    = ?,
                   status       = ?
            WHERE  point_id = ?
            """,
            (result_count, new_count, "error" if error else "completed", point_id),
        )
    conn.close()


def count_grid_points_by_state(db_path: str) -> Dict[str, int]:
    """Return {state_abbr: point_count} for all states in the database."""
    conn = _connect(db_path)
    rows = conn.execute(
        "SELECT state, COUNT(*) AS cnt FROM grid_points GROUP BY state"
    ).fetchall()
    conn.close()
    return {r["state"]: r["cnt"] for r in rows}


# ---------------------------------------------------------------------------
# API usage / quota helpers
# ---------------------------------------------------------------------------

def get_api_usage(db_path: str, year: int, month: int) -> Dict:
    """Return {free_calls, paid_calls} for the given month, defaults to 0."""
    conn = _connect(db_path)
    row = conn.execute(
        "SELECT free_calls, paid_calls FROM api_usage WHERE year=? AND month=?",
        (year, month),
    ).fetchone()
    conn.close()
    if row:
        return dict(row)
    return {"free_calls": 0, "paid_calls": 0}


def increment_api_calls(
    db_path: str,
    year: int,
    month: int,
    free_count: int = 0,
    paid_count: int = 0,
) -> None:
    """Atomically add to the monthly free/paid call counters."""
    conn = _connect(db_path)
    with conn:
        conn.execute(
            """
            INSERT INTO api_usage (year, month, free_calls, paid_calls)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(year, month) DO UPDATE SET
                free_calls = free_calls + excluded.free_calls,
                paid_calls = paid_calls + excluded.paid_calls
            """,
            (year, month, free_count, paid_count),
        )
    conn.close()
