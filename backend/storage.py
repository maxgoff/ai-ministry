"""SQLite-based storage for conversations."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import DATA_DIR

# Database file path
DB_PATH = Path(DATA_DIR) / "ministry.db"


def _ensure_db():
    """Ensure database and tables exist."""
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)

    with _get_connection() as conn:
        # Create base tables first (without user_id index - handled after migration)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                hashed_password TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_users_email
            ON users(email);

            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT 'New Conversation',
                created_at TEXT NOT NULL,
                user_id TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT,
                stage1 TEXT,
                stage2 TEXT,
                stage3 TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            );

            CREATE INDEX IF NOT EXISTS idx_messages_conversation
            ON messages(conversation_id);
        """)

        # Migration: Add user_id column if it doesn't exist (for existing databases)
        # SQLite doesn't support IF NOT EXISTS for columns, so we check first
        cursor = conn.execute("PRAGMA table_info(conversations)")
        columns = [row[1] for row in cursor.fetchall()]
        if 'user_id' not in columns:
            conn.execute("ALTER TABLE conversations ADD COLUMN user_id TEXT REFERENCES users(id)")
            # Note: Existing conversations will have NULL user_id, which is acceptable

        # Create user_id index after migration ensures column exists
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversations_user_id
            ON conversations(user_id)
        """)

        # Migration: Add stage0 column to messages if it doesn't exist
        msg_cursor = conn.execute("PRAGMA table_info(messages)")
        msg_columns = [row[1] for row in msg_cursor.fetchall()]
        if 'stage0' not in msg_columns:
            conn.execute("ALTER TABLE messages ADD COLUMN stage0 TEXT")


@contextmanager
def _get_connection():
    """Context manager for database connections."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def create_conversation(conversation_id: str, user_id: str) -> Dict[str, Any]:
    """
    Create a new conversation owned by a user.

    Args:
        conversation_id: Unique identifier for the conversation
        user_id: ID of the user who owns this conversation

    Returns:
        New conversation dict
    """
    _ensure_db()

    created_at = datetime.utcnow().isoformat()

    with _get_connection() as conn:
        conn.execute(
            "INSERT INTO conversations (id, title, created_at, user_id) VALUES (?, ?, ?, ?)",
            (conversation_id, "New Conversation", created_at, user_id)
        )

    return {
        "id": conversation_id,
        "created_at": created_at,
        "title": "New Conversation",
        "user_id": user_id,
        "messages": []
    }


def get_conversation(conversation_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Load a conversation from storage with optional ownership validation.

    Args:
        conversation_id: Unique identifier for the conversation
        user_id: If provided, validates that the conversation belongs to this user.
                 Returns None if conversation doesn't belong to user (IDOR protection).

    Returns:
        Conversation dict or None if not found (or not owned by user)
    """
    _ensure_db()

    with _get_connection() as conn:
        # Get conversation metadata with ownership check
        if user_id is not None:
            row = conn.execute(
                "SELECT id, title, created_at, user_id FROM conversations WHERE id = ? AND user_id = ?",
                (conversation_id, user_id)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT id, title, created_at, user_id FROM conversations WHERE id = ?",
                (conversation_id,)
            ).fetchone()

        if row is None:
            return None

        # Get messages
        messages_rows = conn.execute(
            """SELECT role, content, stage0, stage1, stage2, stage3
               FROM messages
               WHERE conversation_id = ?
               ORDER BY id""",
            (conversation_id,)
        ).fetchall()

        messages = []
        for msg in messages_rows:
            if msg["role"] == "user":
                messages.append({
                    "role": "user",
                    "content": msg["content"]
                })
            else:
                messages.append({
                    "role": "assistant",
                    "stage0": json.loads(msg["stage0"]) if msg["stage0"] else None,
                    "stage1": json.loads(msg["stage1"]) if msg["stage1"] else [],
                    "stage2": json.loads(msg["stage2"]) if msg["stage2"] else [],
                    "stage3": json.loads(msg["stage3"]) if msg["stage3"] else {}
                })

        return {
            "id": row["id"],
            "created_at": row["created_at"],
            "title": row["title"],
            "user_id": row["user_id"],
            "messages": messages
        }


def save_conversation(conversation: Dict[str, Any]):
    """
    Save a conversation to storage.
    Note: This replaces all messages. For incremental updates, use add_*_message.

    Args:
        conversation: Conversation dict to save
    """
    _ensure_db()

    with _get_connection() as conn:
        # Upsert conversation metadata
        conn.execute(
            """INSERT INTO conversations (id, title, created_at)
               VALUES (?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET title = excluded.title""",
            (conversation["id"], conversation.get("title", "New Conversation"),
             conversation.get("created_at", datetime.utcnow().isoformat()))
        )

        # Delete existing messages and re-insert
        conn.execute("DELETE FROM messages WHERE conversation_id = ?",
                     (conversation["id"],))

        now = datetime.utcnow().isoformat()
        for msg in conversation.get("messages", []):
            if msg["role"] == "user":
                conn.execute(
                    """INSERT INTO messages
                       (conversation_id, role, content, created_at)
                       VALUES (?, ?, ?, ?)""",
                    (conversation["id"], "user", msg["content"], now)
                )
            else:
                conn.execute(
                    """INSERT INTO messages
                       (conversation_id, role, stage0, stage1, stage2, stage3, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (conversation["id"], "assistant",
                     json.dumps(msg["stage0"]) if msg.get("stage0") else None,
                     json.dumps(msg.get("stage1", [])),
                     json.dumps(msg.get("stage2", [])),
                     json.dumps(msg.get("stage3", {})),
                     now)
                )


def list_conversations(user_id: str) -> List[Dict[str, Any]]:
    """
    List all conversations owned by a user (metadata only).
    This is O(1) with SQLite vs O(N) with JSON files.

    Args:
        user_id: ID of the user whose conversations to list

    Returns:
        List of conversation metadata dicts owned by the user
    """
    _ensure_db()

    with _get_connection() as conn:
        rows = conn.execute("""
            SELECT c.id, c.title, c.created_at, c.user_id,
                   COUNT(m.id) as message_count
            FROM conversations c
            LEFT JOIN messages m ON c.id = m.conversation_id
            WHERE c.user_id = ?
            GROUP BY c.id
            ORDER BY c.created_at DESC
        """, (user_id,)).fetchall()

        return [
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "title": row["title"],
                "user_id": row["user_id"],
                "message_count": row["message_count"]
            }
            for row in rows
        ]


def add_user_message(conversation_id: str, content: str):
    """
    Add a user message to a conversation.

    Args:
        conversation_id: Conversation identifier
        content: User message content
    """
    _ensure_db()

    with _get_connection() as conn:
        # Verify conversation exists
        exists = conn.execute(
            "SELECT 1 FROM conversations WHERE id = ?",
            (conversation_id,)
        ).fetchone()

        if not exists:
            raise ValueError(f"Conversation {conversation_id} not found")

        conn.execute(
            """INSERT INTO messages (conversation_id, role, content, created_at)
               VALUES (?, ?, ?, ?)""",
            (conversation_id, "user", content, datetime.utcnow().isoformat())
        )


def add_assistant_message(
    conversation_id: str,
    stage0: Optional[Dict[str, Any]],
    stage1: List[Dict[str, Any]],
    stage2: List[Dict[str, Any]],
    stage3: Dict[str, Any]
):
    """
    Add an assistant message with all stages to a conversation.

    Args:
        conversation_id: Conversation identifier
        stage0: Research briefing (or None if skipped)
        stage1: List of individual model responses
        stage2: List of model rankings
        stage3: Final synthesized response
    """
    _ensure_db()

    with _get_connection() as conn:
        # Verify conversation exists
        exists = conn.execute(
            "SELECT 1 FROM conversations WHERE id = ?",
            (conversation_id,)
        ).fetchone()

        if not exists:
            raise ValueError(f"Conversation {conversation_id} not found")

        conn.execute(
            """INSERT INTO messages
               (conversation_id, role, stage0, stage1, stage2, stage3, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (conversation_id, "assistant",
             json.dumps(stage0) if stage0 else None,
             json.dumps(stage1), json.dumps(stage2), json.dumps(stage3),
             datetime.utcnow().isoformat())
        )


def update_conversation_title(conversation_id: str, title: str):
    """
    Update the title of a conversation.

    Args:
        conversation_id: Conversation identifier
        title: New title for the conversation
    """
    _ensure_db()

    with _get_connection() as conn:
        result = conn.execute(
            "UPDATE conversations SET title = ? WHERE id = ?",
            (title, conversation_id)
        )

        if result.rowcount == 0:
            raise ValueError(f"Conversation {conversation_id} not found")


def delete_conversation(conversation_id: str):
    """
    Delete a conversation and all its messages.

    Args:
        conversation_id: Conversation identifier
    """
    _ensure_db()

    with _get_connection() as conn:
        conn.execute("DELETE FROM messages WHERE conversation_id = ?",
                     (conversation_id,))
        result = conn.execute("DELETE FROM conversations WHERE id = ?",
                              (conversation_id,))

        if result.rowcount == 0:
            raise ValueError(f"Conversation {conversation_id} not found")


# ============================================================================
# User Management Functions
# ============================================================================


def create_user(user_id: str, email: str, hashed_password: str) -> Dict[str, Any]:
    """
    Create a new user.

    Args:
        user_id: Unique identifier for the user
        email: User's email address (must be unique)
        hashed_password: Pre-hashed password (caller must hash before calling)

    Returns:
        New user dict with id, email, created_at (no password)

    Raises:
        ValueError: If email already exists
    """
    _ensure_db()

    created_at = datetime.utcnow().isoformat()

    with _get_connection() as conn:
        try:
            conn.execute(
                """INSERT INTO users (id, email, hashed_password, created_at)
                   VALUES (?, ?, ?, ?)""",
                (user_id, email, hashed_password, created_at)
            )
        except sqlite3.IntegrityError as e:
            if "UNIQUE constraint failed: users.email" in str(e):
                raise ValueError(f"User with email '{email}' already exists")
            raise

    return {
        "id": user_id,
        "email": email,
        "created_at": created_at
    }


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """
    Get a user by their email address.

    Args:
        email: Email address to look up

    Returns:
        User dict with id, email, hashed_password, created_at, or None if not found
    """
    _ensure_db()

    with _get_connection() as conn:
        row = conn.execute(
            "SELECT id, email, hashed_password, created_at FROM users WHERE email = ?",
            (email,)
        ).fetchone()

        if row is None:
            return None

        return {
            "id": row["id"],
            "email": row["email"],
            "hashed_password": row["hashed_password"],
            "created_at": row["created_at"]
        }


def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    """
    Get a user by their ID.

    Args:
        user_id: User ID to look up

    Returns:
        User dict with id, email, hashed_password, created_at, or None if not found
    """
    _ensure_db()

    with _get_connection() as conn:
        row = conn.execute(
            "SELECT id, email, hashed_password, created_at FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()

        if row is None:
            return None

        return {
            "id": row["id"],
            "email": row["email"],
            "hashed_password": row["hashed_password"],
            "created_at": row["created_at"]
        }


# ============================================================================
# Migration Utilities
# ============================================================================


def migrate_from_json():
    """
    One-time migration from JSON files to SQLite.
    Safe to run multiple times - skips existing conversations.
    """
    import os

    json_dir = Path(DATA_DIR)
    if not json_dir.exists():
        print("[Migration] No JSON data directory found, nothing to migrate.")
        return

    _ensure_db()
    migrated = 0
    skipped = 0

    for filename in os.listdir(json_dir):
        if not filename.endswith('.json'):
            continue

        filepath = json_dir / filename
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)

            # Check if already migrated
            with _get_connection() as conn:
                exists = conn.execute(
                    "SELECT 1 FROM conversations WHERE id = ?",
                    (data["id"],)
                ).fetchone()

                if exists:
                    skipped += 1
                    continue

            # Migrate
            save_conversation(data)
            migrated += 1
            print(f"[Migration] Migrated: {data['id']}")

        except Exception as e:
            print(f"[Migration] Error migrating {filename}: {e}")

    print(f"[Migration] Complete: {migrated} migrated, {skipped} skipped (already exist)")
