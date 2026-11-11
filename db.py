from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional


def connect(database: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(database), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(database: str | Path) -> None:
    Path(database).parent.mkdir(parents=True, exist_ok=True)
    with connect(database) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def get_user_by_id(conn: sqlite3.Connection, uid: int) -> Optional[dict]:
    row = conn.execute(
        "SELECT id, name, email FROM users WHERE id=?", (uid,)
    ).fetchone()
    return dict(row) if row else None


def get_user_by_email(conn: sqlite3.Connection, email: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT id, password_hash FROM users WHERE email=?", (email,)
    ).fetchone()


def create_user(
    conn: sqlite3.Connection, name: str, email: str, password_hash: str
) -> int:
    cur = conn.execute(
        "INSERT INTO users(name, email, password_hash) VALUES (?, ?, ?)",
        (name, email, password_hash),
    )
    conn.commit()
    return cur.lastrowid
