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
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT 'New Conversation',
                created_at TEXT NOT NULL
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


def create_conversation(conversation_id: str) -> Dict[str, Any]:
    """
    Create a new conversation.

    Args:
        conversation_id: Unique identifier for the conversation

    Returns:
        New conversation dict
    """
    _ensure_db()

    created_at = datetime.utcnow().isoformat()

    with _get_connection() as conn:
        conn.execute(
            "INSERT INTO conversations (id, title, created_at) VALUES (?, ?, ?)",
            (conversation_id, "New Conversation", created_at)
        )

    return {
        "id": conversation_id,
        "created_at": created_at,
        "title": "New Conversation",
        "messages": []
    }


def get_conversation(conversation_id: str) -> Optional[Dict[str, Any]]:
    """
    Load a conversation from storage.

    Args:
        conversation_id: Unique identifier for the conversation

    Returns:
        Conversation dict or None if not found
    """
    _ensure_db()

    with _get_connection() as conn:
        # Get conversation metadata
        row = conn.execute(
            "SELECT id, title, created_at FROM conversations WHERE id = ?",
            (conversation_id,)
        ).fetchone()

        if row is None:
            return None

        # Get messages
        messages_rows = conn.execute(
            """SELECT role, content, stage1, stage2, stage3
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
                    "stage1": json.loads(msg["stage1"]) if msg["stage1"] else [],
                    "stage2": json.loads(msg["stage2"]) if msg["stage2"] else [],
                    "stage3": json.loads(msg["stage3"]) if msg["stage3"] else {}
                })

        return {
            "id": row["id"],
            "created_at": row["created_at"],
            "title": row["title"],
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
                       (conversation_id, role, stage1, stage2, stage3, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (conversation["id"], "assistant",
                     json.dumps(msg.get("stage1", [])),
                     json.dumps(msg.get("stage2", [])),
                     json.dumps(msg.get("stage3", {})),
                     now)
                )


def list_conversations() -> List[Dict[str, Any]]:
    """
    List all conversations (metadata only).
    This is O(1) with SQLite vs O(N) with JSON files.

    Returns:
        List of conversation metadata dicts
    """
    _ensure_db()

    with _get_connection() as conn:
        rows = conn.execute("""
            SELECT c.id, c.title, c.created_at,
                   COUNT(m.id) as message_count
            FROM conversations c
            LEFT JOIN messages m ON c.id = m.conversation_id
            GROUP BY c.id
            ORDER BY c.created_at DESC
        """).fetchall()

        return [
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "title": row["title"],
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
    stage1: List[Dict[str, Any]],
    stage2: List[Dict[str, Any]],
    stage3: Dict[str, Any]
):
    """
    Add an assistant message with all 3 stages to a conversation.

    Args:
        conversation_id: Conversation identifier
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
               (conversation_id, role, stage1, stage2, stage3, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (conversation_id, "assistant",
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
