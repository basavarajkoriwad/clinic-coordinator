"""
Authentication, Security, Password Hashing, Session Management, CSRF, and Rate Limiting.
Adheres strictly to zero-dependency Python standard library:
- PBKDF2-HMAC-SHA256 with 260,000 iterations and random 16-byte salt
- Constant-time hash verification via hmac.compare_digest
- 32-byte cryptographically secure tokens via secrets
- In-memory rate limiting with sliding 15-minute window
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import html
import re
import secrets
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import config
from src.db import db_cursor, hash_token

# Constants
PBKDF2_ITERATIONS = 260000
PASSWORD_MIN_LENGTH = 8
SESSION_EXPIRY_DAYS = 7
VERIFY_TOKEN_EXPIRY_HOURS = 24
RESET_TOKEN_EXPIRY_HOURS = 1
CONFIRM_SUB_EXPIRY_DAYS = 7

# Rate Limiter State: (action, key) -> list of timestamp floats
_rate_limit_lock = threading.Lock()
_rate_limit_records: Dict[Tuple[str, str], List[float]] = defaultdict(list)
RATE_LIMIT_WINDOW_SECONDS = 15 * 60  # 15 minutes
RATE_LIMIT_MAX_ATTEMPTS = 5


def check_rate_limit(action: str, key: str, max_attempts: int = RATE_LIMIT_MAX_ATTEMPTS, window_seconds: int = RATE_LIMIT_WINDOW_SECONDS) -> Tuple[bool, int]:
    """
    Checks if an action exceeds the rate limit.
    Returns (is_allowed, remaining_seconds_or_attempts).
    If not allowed, returns (False, seconds_until_unlock).
    If allowed, records the attempt and returns (True, attempts_left).
    """
    now = time.time()
    clean_key = str(key).strip().lower()
    full_key = (action, clean_key)

    with _rate_limit_lock:
        timestamps = _rate_limit_records[full_key]
        # Prune older than window
        valid = [t for t in timestamps if now - t < window_seconds]
        _rate_limit_records[full_key] = valid

        if len(valid) >= max_attempts:
            oldest = valid[0]
            retry_after = int(window_seconds - (now - oldest)) + 1
            return False, max(1, retry_after)

        valid.append(now)
        attempts_left = max_attempts - len(valid)
        return True, attempts_left


def reset_rate_limit(action: str, key: str):
    """Resets the rate limit for a specific key upon successful completion."""
    clean_key = str(key).strip().lower()
    full_key = (action, clean_key)
    with _rate_limit_lock:
        if full_key in _rate_limit_records:
            del _rate_limit_records[full_key]


# ----------------------------------------------------------------------
# Password Hashing & Verification
# ----------------------------------------------------------------------

def hash_password(password: str) -> Tuple[str, str]:
    """
    Hashes a password with PBKDF2-HMAC-SHA256 (260,000 iterations).
    Returns (password_hash_hex, salt_hex).
    """
    if len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"Password must be at least {PASSWORD_MIN_LENGTH} characters long.")
    
    salt = secrets.token_hex(16)
    pwd_bytes = password.encode("utf-8")
    salt_bytes = salt.encode("utf-8")
    derived = hashlib.pbkdf2_hmac("sha256", pwd_bytes, salt_bytes, PBKDF2_ITERATIONS)
    return derived.hex(), salt


def verify_password(password: str, expected_hash_hex: str, salt_hex: str) -> bool:
    """Verifies a password against the expected PBKDF2-HMAC-SHA256 hash using constant-time comparison."""
    try:
        pwd_bytes = password.encode("utf-8")
        salt_bytes = salt_hex.encode("utf-8")
        derived = hashlib.pbkdf2_hmac("sha256", pwd_bytes, salt_bytes, PBKDF2_ITERATIONS)
        return hmac.compare_digest(derived.hex(), expected_hash_hex)
    except Exception:
        return False


def validate_email_format(email: str) -> bool:
    """Validates standard email address syntax."""
    if not email or len(email) > 254:
        return False
    # Standard RFC 5322 compliant simple regex
    pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    return bool(re.match(pattern, email.strip()))


# ----------------------------------------------------------------------
# CSRF Protection
# ----------------------------------------------------------------------

def generate_csrf_token(session_or_salt: str) -> str:
    """Generates an HMAC-signed CSRF token tied to the user's session or guest identity."""
    timestamp = str(int(time.time()))
    payload = f"{session_or_salt}:{timestamp}"
    signature = hmac.new(config.SECRET_KEY.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}:{signature}"


def verify_csrf_token(token: str, session_or_salt: str, max_age_seconds: int = 86400) -> bool:
    """Verifies an HMAC-signed CSRF token."""
    if not token or ":" not in token:
        return False
    try:
        parts = token.split(":")
        if len(parts) != 3:
            return False
        ident, ts_str, signature = parts
        if not hmac.compare_digest(ident, session_or_salt):
            return False
        
        expected_sig = hmac.new(
            config.SECRET_KEY.encode("utf-8"),
            f"{ident}:{ts_str}".encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        
        if not hmac.compare_digest(signature, expected_sig):
            return False

        ts = int(ts_str)
        if time.time() - ts > max_age_seconds:
            return False
        return True
    except Exception:
        return False


# ----------------------------------------------------------------------
# User Accounts & Tokens
# ----------------------------------------------------------------------

def create_user(email: str, password: str) -> Tuple[Dict[str, Any], str]:
    """
    Creates a new user record in sqlite3.
    Returns (user_dict, raw_verification_token).
    """
    email_clean = email.strip().lower()
    if not validate_email_format(email_clean):
        raise ValueError("Invalid email format.")
    
    pwd_hash, salt = hash_password(password)
    raw_verify_token = secrets.token_urlsafe(32)
    verify_token_hash = hash_token(raw_verify_token)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=VERIFY_TOKEN_EXPIRY_HOURS)

    with db_cursor(commit=True) as cur:
        # Check if email exists
        cur.execute("SELECT id FROM users WHERE email = ?;", (email_clean,))
        if cur.fetchone():
            raise ValueError("An account with this email already exists.")

        cur.execute("""
            INSERT INTO users (
                email, password_hash, salt, email_verified,
                verify_token_hash, verify_token_expires_at,
                created_at, last_login
            ) VALUES (?, ?, ?, 0, ?, ?, ?, NULL);
        """, (
            email_clean, pwd_hash, salt,
            verify_token_hash, expires_at.isoformat(),
            now.isoformat()
        ))
        user_id = cur.lastrowid

    return {
        "id": user_id,
        "email": email_clean,
        "email_verified": False,
        "created_at": now.isoformat(),
    }, raw_verify_token


def verify_user_email(raw_token: str) -> Tuple[bool, str]:
    """
    Verifies a user's email using a single-use verification token.
    Returns (success, message).
    """
    if not raw_token:
        return False, "Missing verification token."
    
    t_hash = hash_token(raw_token.strip())
    now = datetime.now(timezone.utc)

    with db_cursor(commit=True) as cur:
        cur.execute("""
            SELECT id, email, verify_token_expires_at
            FROM users
            WHERE verify_token_hash = ?;
        """, (t_hash,))
        row = cur.fetchone()
        if not row:
            return False, "This verification link is invalid or has already been used."

        expires_at = datetime.fromisoformat(row["verify_token_expires_at"])
        if now > expires_at:
            return False, "This verification link has expired. Please request a new one."

        # Mark verified and invalidate token (single-use)
        cur.execute("""
            UPDATE users
            SET email_verified = 1,
                verify_token_hash = NULL,
                verify_token_expires_at = NULL
            WHERE id = ?;
        """, (row["id"],))

    return True, "Your email address has been successfully verified. You can now log in."


def resend_verification_token(email: str) -> Optional[str]:
    """Generates a new verification token for an unverified user. Returns raw token if applicable."""
    email_clean = email.strip().lower()
    with db_cursor(commit=True) as cur:
        cur.execute("SELECT id, email_verified FROM users WHERE email = ?;", (email_clean,))
        row = cur.fetchone()
        if not row or row["email_verified"] == 1:
            return None

        raw_token = secrets.token_urlsafe(32)
        t_hash = hash_token(raw_token)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=VERIFY_TOKEN_EXPIRY_HOURS)

        cur.execute("""
            UPDATE users
            SET verify_token_hash = ?,
                verify_token_expires_at = ?
            WHERE id = ?;
        """, (t_hash, expires_at.isoformat(), row["id"]))
        return raw_token


def create_password_reset_token(email: str) -> Optional[Tuple[Dict[str, Any], str]]:
    """Creates a single-use password reset token (1 hour expiry). Returns (user, raw_token) if user exists."""
    email_clean = email.strip().lower()
    with db_cursor(commit=True) as cur:
        cur.execute("SELECT id, email, email_verified FROM users WHERE email = ?;", (email_clean,))
        row = cur.fetchone()
        if not row:
            return None

        raw_token = secrets.token_urlsafe(32)
        t_hash = hash_token(raw_token)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=RESET_TOKEN_EXPIRY_HOURS)

        cur.execute("""
            UPDATE users
            SET reset_token_hash = ?,
                reset_token_expires_at = ?
            WHERE id = ?;
        """, (t_hash, expires_at.isoformat(), row["id"]))

        return dict(row), raw_token


def reset_user_password(raw_token: str, new_password: str) -> Tuple[bool, str]:
    """Resets user password with single-use reset token."""
    if not raw_token:
        return False, "Missing reset token."
    if len(new_password) < PASSWORD_MIN_LENGTH:
        return False, f"Password must be at least {PASSWORD_MIN_LENGTH} characters long."

    t_hash = hash_token(raw_token.strip())
    now = datetime.now(timezone.utc)

    with db_cursor(commit=True) as cur:
        cur.execute("""
            SELECT id, email, reset_token_expires_at
            FROM users
            WHERE reset_token_hash = ?;
        """, (t_hash,))
        row = cur.fetchone()
        if not row:
            return False, "This password reset link is invalid or has already been used."

        expires_at = datetime.fromisoformat(row["reset_token_expires_at"])
        if now > expires_at:
            return False, "This password reset link has expired. Please request a new one."

        pwd_hash, salt = hash_password(new_password)
        # Update password, invalidate token, and revoke all active sessions for security
        cur.execute("""
            UPDATE users
            SET password_hash = ?,
                salt = ?,
                reset_token_hash = NULL,
                reset_token_expires_at = NULL
            WHERE id = ?;
        """, (pwd_hash, salt, row["id"]))

        cur.execute("DELETE FROM sessions WHERE user_id = ?;", (row["id"],))

    return True, "Your password has been reset successfully. You may now log in with your new password."


# ----------------------------------------------------------------------
# Session Management
# ----------------------------------------------------------------------

def create_session(user_id: int) -> str:
    """Creates a secure session token and persists its SHA-256 hash in sqlite3."""
    raw_token = secrets.token_urlsafe(32)
    t_hash = hash_token(raw_token)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=SESSION_EXPIRY_DAYS)

    with db_cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO sessions (token_hash, user_id, expires_at, created_at)
            VALUES (?, ?, ?, ?);
        """, (t_hash, user_id, expires_at.isoformat(), now.isoformat()))

        # Update last_login
        cur.execute("UPDATE users SET last_login = ? WHERE id = ?;", (now.isoformat(), user_id))

    return raw_token


def get_user_from_session(raw_token: Optional[str]) -> Optional[Dict[str, Any]]:
    """Retrieves authenticated user from session token if valid and unexpired."""
    if not raw_token:
        return None
    
    t_hash = hash_token(raw_token.strip())
    now = datetime.now(timezone.utc)

    with db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT s.expires_at, u.id, u.email, u.email_verified, u.created_at, u.last_login
            FROM sessions s
            JOIN users u ON s.user_id = u.id
            WHERE s.token_hash = ?;
        """, (t_hash,))
        row = cur.fetchone()
        if not row:
            return None

        expires_at = datetime.fromisoformat(row["expires_at"])
        if now > expires_at:
            # Session expired
            return None

        return {
            "id": row["id"],
            "email": row["email"],
            "email_verified": bool(row["email_verified"]),
            "created_at": row["created_at"],
            "last_login": row["last_login"],
        }


def delete_session(raw_token: str):
    """Revokes a session by deleting it from the database."""
    if not raw_token:
        return
    t_hash = hash_token(raw_token.strip())
    with db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM sessions WHERE token_hash = ?;", (t_hash,))


def delete_user_account_and_data(user_id: int) -> bool:
    """
    Deletes user profile, active sessions, and subscriptions under DPDP Act 2023.
    Retains statutory invoices as required by GST / tax law (with notice).
    """
    with db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM subscriptions WHERE user_id = ?;", (user_id,))
        cur.execute("DELETE FROM sessions WHERE user_id = ?;", (user_id,))
        cur.execute("DELETE FROM users WHERE id = ?;", (user_id,))
    return True
