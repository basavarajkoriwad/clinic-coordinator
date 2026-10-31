"""
Database storage engine for The Bengaluru Clinic using SQLite3.
Provides schema initialization, parameterized queries, and thread-safe connection management.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
from typing import Any, Dict, Generator, List, Optional, Tuple

import config


# Ensure data directory and invoice storage exist
config.DATA_DIR.mkdir(parents=True, exist_ok=True)
config.INVOICES_DIR.mkdir(parents=True, exist_ok=True)

_db_lock = threading.RLock()


def hash_token(token: str) -> str:
    """Computes a SHA-256 hex digest of a token for secure database storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def get_db_connection() -> sqlite3.Connection:
    """Creates a new sqlite3 connection with row_factory set to sqlite3.Row."""
    conn = sqlite3.connect(
        str(config.DATABASE_PATH),
        timeout=20.0,
        check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    # Enable WAL mode and foreign keys for high-performance concurrent reads
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


@contextmanager
def db_cursor(commit: bool = True) -> Generator[sqlite3.Cursor, None, None]:
    """Thread-safe context manager yielding a database cursor."""
    with _db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            yield cursor
            if commit:
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def init_db():
    """Initializes all required database tables if they do not already exist."""
    with db_cursor(commit=True) as cur:
        # 1. Users Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                email_verified INTEGER DEFAULT 0,
                verify_token_hash TEXT,
                verify_token_expires_at TEXT,
                reset_token_hash TEXT,
                reset_token_expires_at TEXT,
                created_at TEXT NOT NULL,
                last_login TEXT
            );
        """)

        # 2. Sessions Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
        """)

        # 3. Subscriptions Table (Double Opt-In Consent)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                user_id INTEGER PRIMARY KEY,
                status TEXT NOT NULL, -- PENDING, ACTIVE, UNSUBSCRIBED
                confirm_token_hash TEXT,
                unsub_token_hash TEXT,
                consent_text TEXT,
                consent_at TEXT,
                consent_ip_hash TEXT,
                preferences TEXT NOT NULL, -- JSON string
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
        """)

        # 4. Email Queue Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS email_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                to_email TEXT NOT NULL,
                template TEXT NOT NULL,
                subject TEXT NOT NULL,
                html_body TEXT NOT NULL,
                text_body TEXT NOT NULL,
                attachment_name TEXT,
                attachment_bytes BLOB,
                status TEXT NOT NULL, -- QUEUED, SENT, SENT-IN-DEV, FAILED, DEAD
                attempts INTEGER DEFAULT 0,
                next_attempt_at TEXT,
                last_error TEXT,
                created_at TEXT NOT NULL,
                sent_at TEXT,
                dedupe_key TEXT UNIQUE
            );
        """)

        # 5. Email Log Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS email_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                queue_id INTEGER,
                event TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (queue_id) REFERENCES email_queue(id) ON DELETE CASCADE
            );
        """)

        # 6. Invoices Table (Sequential, Never Reused)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS invoices (
                invoice_number TEXT PRIMARY KEY,
                booking_id TEXT UNIQUE NOT NULL,
                financial_year TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                pdf_path TEXT NOT NULL,
                access_token_hash TEXT,
                access_token_expires_at TEXT,
                total_amount REAL NOT NULL
            );
        """)

        # Indexes for fast queue queries and lookups
        cur.execute("CREATE INDEX IF NOT EXISTS idx_email_queue_status ON email_queue(status, next_attempt_at);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);")


# Automatically initialize schema on module import
init_db()
