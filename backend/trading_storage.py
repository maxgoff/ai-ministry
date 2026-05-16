"""SQLite storage for trading sessions and settings.

Uses the same ministry.db database and follows the patterns in storage.py.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import DATA_DIR

DB_PATH = Path(DATA_DIR) / "ministry.db"


@contextmanager
def _get_connection():
    """Context manager for database connections."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_trading_tables():
    """Create trading tables if they don't exist."""
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)

    with _get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS trading_settings (
                user_id TEXT PRIMARY KEY,
                settings_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS trading_sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT 'Trading Session',
                created_at TEXT NOT NULL,
                global_settings_json TEXT NOT NULL DEFAULT '{}',
                selected_traders_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'running',
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE INDEX IF NOT EXISTS idx_trading_sessions_user_id
            ON trading_sessions(user_id);

            CREATE TABLE IF NOT EXISTS trading_analyses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                trader_id TEXT NOT NULL,
                trader_name TEXT NOT NULL,
                prompt_text TEXT,
                stage0 TEXT,
                stage1 TEXT,
                stage2 TEXT,
                stage3 TEXT,
                metadata TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES trading_sessions(id)
            );

            CREATE INDEX IF NOT EXISTS idx_trading_analyses_session
            ON trading_analyses(session_id);

            CREATE TABLE IF NOT EXISTS trading_master_synthesis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL UNIQUE,
                prompt_text TEXT,
                stage1 TEXT,
                stage2 TEXT,
                stage3 TEXT,
                metadata TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES trading_sessions(id)
            );
        """)


# Run on import
_ensure_trading_tables()


# ============================================================================
# Settings
# ============================================================================

def save_trading_settings(user_id: str, settings: Dict[str, Any]) -> None:
    """Save or update a user's global trading settings."""
    now = datetime.utcnow().isoformat()
    with _get_connection() as conn:
        conn.execute(
            """INSERT INTO trading_settings (user_id, settings_json, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                   settings_json = excluded.settings_json,
                   updated_at = excluded.updated_at""",
            (user_id, json.dumps(settings), now),
        )


def get_trading_settings(user_id: str) -> Dict[str, Any]:
    """Get a user's global trading settings. Returns empty dict if none saved."""
    with _get_connection() as conn:
        row = conn.execute(
            "SELECT settings_json FROM trading_settings WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row:
            return json.loads(row["settings_json"])
        return {}


# ============================================================================
# Sessions
# ============================================================================

def create_trading_session(
    session_id: str,
    user_id: str,
    global_settings: Dict[str, Any],
    selected_traders: List[str],
) -> Dict[str, Any]:
    """Create a new trading session."""
    now = datetime.utcnow().isoformat()
    title = f"Trading Session {now[:10]}"
    with _get_connection() as conn:
        conn.execute(
            """INSERT INTO trading_sessions
               (id, user_id, title, created_at, global_settings_json, selected_traders_json, status)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                user_id,
                title,
                now,
                json.dumps(global_settings),
                json.dumps(selected_traders),
                "running",
            ),
        )
    return {
        "id": session_id,
        "user_id": user_id,
        "title": title,
        "created_at": now,
        "global_settings": global_settings,
        "selected_traders": selected_traders,
        "status": "running",
    }


def list_trading_sessions(user_id: str) -> List[Dict[str, Any]]:
    """List all trading sessions for a user (metadata only)."""
    with _get_connection() as conn:
        rows = conn.execute(
            """SELECT id, title, created_at, status, selected_traders_json
               FROM trading_sessions
               WHERE user_id = ?
               ORDER BY created_at DESC""",
            (user_id,),
        ).fetchall()

        return [
            {
                "id": row["id"],
                "title": row["title"],
                "created_at": row["created_at"],
                "status": row["status"],
                "selected_traders": json.loads(row["selected_traders_json"]),
            }
            for row in rows
        ]


def get_trading_session(session_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """Get a full trading session with all analyses and master synthesis."""
    with _get_connection() as conn:
        row = conn.execute(
            """SELECT id, user_id, title, created_at, global_settings_json,
                      selected_traders_json, status
               FROM trading_sessions
               WHERE id = ? AND user_id = ?""",
            (session_id, user_id),
        ).fetchone()

        if not row:
            return None

        # Get analyses
        analyses_rows = conn.execute(
            """SELECT trader_id, trader_name, prompt_text, stage0, stage1, stage2, stage3, metadata, created_at
               FROM trading_analyses
               WHERE session_id = ?
               ORDER BY id""",
            (session_id,),
        ).fetchall()

        analyses = []
        for a in analyses_rows:
            analyses.append({
                "trader_id": a["trader_id"],
                "trader_name": a["trader_name"],
                "stage0": json.loads(a["stage0"]) if a["stage0"] else None,
                "stage1": json.loads(a["stage1"]) if a["stage1"] else [],
                "stage2": json.loads(a["stage2"]) if a["stage2"] else [],
                "stage3": json.loads(a["stage3"]) if a["stage3"] else {},
                "metadata": json.loads(a["metadata"]) if a["metadata"] else None,
            })

        # Get master synthesis
        master_row = conn.execute(
            """SELECT prompt_text, stage1, stage2, stage3, metadata, created_at
               FROM trading_master_synthesis
               WHERE session_id = ?""",
            (session_id,),
        ).fetchone()

        master = None
        if master_row:
            master = {
                "stage1": json.loads(master_row["stage1"]) if master_row["stage1"] else [],
                "stage2": json.loads(master_row["stage2"]) if master_row["stage2"] else [],
                "stage3": json.loads(master_row["stage3"]) if master_row["stage3"] else {},
                "metadata": json.loads(master_row["metadata"]) if master_row["metadata"] else None,
            }

        return {
            "id": row["id"],
            "title": row["title"],
            "created_at": row["created_at"],
            "status": row["status"],
            "global_settings": json.loads(row["global_settings_json"]),
            "selected_traders": json.loads(row["selected_traders_json"]),
            "analyses": analyses,
            "master_synthesis": master,
        }


def save_trading_analysis(
    session_id: str,
    trader_id: str,
    trader_name: str,
    prompt_text: str,
    stage0: Optional[Dict],
    stage1: List[Dict],
    stage2: List[Dict],
    stage3: Dict,
    metadata: Optional[Dict] = None,
) -> None:
    """Save one trader's analysis results."""
    now = datetime.utcnow().isoformat()
    with _get_connection() as conn:
        conn.execute(
            """INSERT INTO trading_analyses
               (session_id, trader_id, trader_name, prompt_text, stage0, stage1, stage2, stage3, metadata, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                trader_id,
                trader_name,
                prompt_text,
                json.dumps(stage0) if stage0 else None,
                json.dumps(stage1),
                json.dumps(stage2),
                json.dumps(stage3),
                json.dumps(metadata) if metadata else None,
                now,
            ),
        )


def save_master_synthesis(
    session_id: str,
    prompt_text: str,
    stage1: List[Dict],
    stage2: List[Dict],
    stage3: Dict,
    metadata: Optional[Dict] = None,
) -> None:
    """Save the master trader synthesis results."""
    now = datetime.utcnow().isoformat()
    with _get_connection() as conn:
        conn.execute(
            """INSERT INTO trading_master_synthesis
               (session_id, prompt_text, stage1, stage2, stage3, metadata, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(session_id) DO UPDATE SET
                   prompt_text = excluded.prompt_text,
                   stage1 = excluded.stage1,
                   stage2 = excluded.stage2,
                   stage3 = excluded.stage3,
                   metadata = excluded.metadata,
                   created_at = excluded.created_at""",
            (
                session_id,
                prompt_text,
                json.dumps(stage1),
                json.dumps(stage2),
                json.dumps(stage3),
                json.dumps(metadata) if metadata else None,
                now,
            ),
        )


def update_trading_session_status(session_id: str, status: str) -> None:
    """Update a trading session's status (running/complete/error)."""
    with _get_connection() as conn:
        conn.execute(
            "UPDATE trading_sessions SET status = ? WHERE id = ?",
            (status, session_id),
        )
