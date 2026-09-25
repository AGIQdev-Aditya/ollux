"""
ollux — Local SQLite Storage Engine
Stores chat sessions, message histories, attached file metadata, and user settings.
Zero cloud sync, 100% private, located at ~/.local/share/ollux/ollux.db
"""

import os
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional


class Database:
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            data_dir = os.path.expanduser("~/.local/share/ollux")
            os.makedirs(data_dir, exist_ok=True)
            self.db_path = os.path.join(data_dir, "ollux.db")
        else:
            self.db_path = db_path
        self._init_db()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    model TEXT NOT NULL,
                    thinking_level TEXT DEFAULT 'med',
                    is_pinned INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            try:
                cursor.execute("ALTER TABLE sessions ADD COLUMN is_pinned INTEGER DEFAULT 0")
            except Exception:
                pass
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    thinking_content TEXT DEFAULT '',
                    attachments_json TEXT DEFAULT '[]',
                    metrics_json TEXT DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES sessions (id) ON DELETE CASCADE
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id)")
            conn.commit()

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: Any):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, str(value))
            )
            conn.commit()

    def create_session(self, title: str = "New Chat", model: str = "llama2-uncensored:7b", thinking_level: str = "med") -> str:
        session_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO sessions (id, title, model, thinking_level, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, title, model, thinking_level, now, now)
            )
            conn.commit()
        self.set_setting("last_session_id", session_id)
        return session_id

    def list_sessions(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, title, model, thinking_level, is_pinned, created_at, updated_at FROM sessions ORDER BY is_pinned DESC, updated_at DESC")
            return [dict(row) for row in cursor.fetchall()]

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, title, model, thinking_level, is_pinned, created_at, updated_at FROM sessions WHERE id = ?", (session_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def toggle_pin_session(self, session_id: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT is_pinned FROM sessions WHERE id = ?", (session_id,))
            row = cursor.fetchone()
            if not row:
                return False
            curr = row["is_pinned"] if "is_pinned" in row.keys() else 0
            new_val = 0 if curr else 1
            cursor.execute("UPDATE sessions SET is_pinned = ? WHERE id = ?", (new_val, session_id))
            conn.commit()
            return bool(new_val)

    def update_session(self, session_id: str, title: Optional[str] = None, model: Optional[str] = None, thinking_level: Optional[str] = None):
        updates = []
        params = []
        if title is not None:
            updates.append("title = ?")
            params.append(title)
        if model is not None:
            updates.append("model = ?")
            params.append(model)
        if thinking_level is not None:
            updates.append("thinking_level = ?")
            params.append(thinking_level)
        
        updates.append("updated_at = ?")
        params.append(datetime.now(timezone.utc).isoformat())
        params.append(session_id)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"UPDATE sessions SET {', '.join(updates)} WHERE id = ?", params)
            conn.commit()

    def delete_session(self, session_id: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            conn.commit()
            return True

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        thinking_content: str = "",
        attachments: Optional[List[Dict[str, Any]]] = None,
        metrics: Optional[Dict[str, Any]] = None
    ) -> str:
        msg_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        att_json = json.dumps(attachments or [])
        met_json = json.dumps(metrics or {})
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO messages (id, session_id, role, content, thinking_content, attachments_json, metrics_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (msg_id, session_id, role, content, thinking_content, att_json, met_json, now)
            )
            # Bump session updated_at
            cursor.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
            conn.commit()
        return msg_id

    def get_messages(self, session_id: str) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, session_id, role, content, thinking_content, attachments_json, metrics_json, created_at FROM messages WHERE session_id = ? ORDER BY created_at ASC",
                (session_id,)
            )
            rows = cursor.fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d["attachments"] = json.loads(d.get("attachments_json") or "[]")
                d["metrics"] = json.loads(d.get("metrics_json") or "{}")
                result.append(d)
            return result
