"""
Unit Tests for Authentication, Password Security, Tokens, CSRF, and Rate Limiting.
"""

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sys
import unittest

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

import config
from src.db import init_db, db_cursor, hash_token
from src.auth import (
    hash_password,
    verify_password,
    create_user,
    verify_user_email,
    resend_verification_token,
    create_password_reset_token,
    reset_user_password,
    create_session,
    get_user_from_session,
    delete_session,
    delete_user_account_and_data,
    generate_csrf_token,
    verify_csrf_token,
    check_rate_limit,
    reset_rate_limit,
    _rate_limit_records,
)


class TestAuthAndSecurity(unittest.TestCase):
    def setUp(self):
        init_db()
        _rate_limit_records.clear()
        # Clean test user data
        with db_cursor() as cur:
            cur.execute("DELETE FROM sessions;")
            cur.execute("DELETE FROM subscriptions;")
            cur.execute("DELETE FROM email_queue;")
            cur.execute("DELETE FROM email_log;")
            cur.execute("DELETE FROM invoices;")
            cur.execute("DELETE FROM users WHERE email LIKE '%@testauth.com';")

    def test_password_hashing_and_verification(self):
        password = "SecurePassword123!"
        pwd_hash, salt = hash_password(password)

        self.assertIsInstance(pwd_hash, str)
        self.assertIsInstance(salt, str)
        self.assertEqual(len(pwd_hash), 64)  # 256 bits = 64 hex characters
        self.assertEqual(len(salt), 32)      # 16 bytes = 32 hex characters

        # Verification succeeds with matching password
        self.assertTrue(verify_password(password, pwd_hash, salt))

        # Verification fails with incorrect password
        self.assertFalse(verify_password("WrongPassword123!", pwd_hash, salt))
        self.assertFalse(verify_password("", pwd_hash, salt))

    def test_create_user_and_verification_token(self):
        email = "patient.one@testauth.com"
        password = "Password987!"

        user_data, raw_token = create_user(email, password)
        self.assertIsNotNone(user_data)
        user_id = user_data["id"]
        self.assertIsNotNone(user_id)
        self.assertIsNotNone(raw_token)
        self.assertGreaterEqual(len(raw_token), 32)

        # Check DB user state
        with db_cursor(commit=False) as cur:
            cur.execute("SELECT email, email_verified, verify_token_hash FROM users WHERE id = ?;", (user_id,))
            row = cur.fetchone()
            self.assertEqual(row["email"], email)
            self.assertEqual(row["email_verified"], 0)
            self.assertEqual(row["verify_token_hash"], hash_token(raw_token))

        # Duplicate email raises ValueError
        with self.assertRaises(ValueError):
            create_user(email, "AnotherPassword!")

    def test_verify_user_email_single_use(self):
        email = "patient.verify@testauth.com"
        user_data, raw_token = create_user(email, "Password123!")
        user_id = user_data["id"]

        # Verify with wrong token fails
        ok, msg = verify_user_email("invalid_token_123456789012345678901234")
        self.assertFalse(ok)

        # Verify with correct token succeeds
        ok, msg = verify_user_email(raw_token)
        self.assertTrue(ok)

        # Check user is verified in DB
        with db_cursor(commit=False) as cur:
            cur.execute("SELECT email_verified, verify_token_hash FROM users WHERE id = ?;", (user_id,))
            row = cur.fetchone()
            self.assertEqual(row["email_verified"], 1)
            self.assertIsNone(row["verify_token_hash"])

        # Second attempt with same token fails (single use)
        ok2, msg2 = verify_user_email(raw_token)
        self.assertFalse(ok2)

    def test_password_reset_flow(self):
        email = "patient.reset@testauth.com"
        user_data, verify_token = create_user(email, "OldPassword123!")
        user_id = user_data["id"]
        verify_user_email(verify_token)

        # Create reset token
        user_res, raw_reset_token = create_password_reset_token(email)
        self.assertIsNotNone(raw_reset_token)

        # Reset password with invalid token fails
        ok, msg = reset_user_password("bad_token", "NewPassword456!")
        self.assertFalse(ok)

        # Reset password with valid token succeeds
        ok, msg = reset_user_password(raw_reset_token, "NewPassword456!")
        self.assertTrue(ok)

        # Reusing the token fails (single-use)
        ok2, msg2 = reset_user_password(raw_reset_token, "NewPassword789!")
        self.assertFalse(ok2)

        # Verify old password no longer works and new password works
        with db_cursor(commit=False) as cur:
            cur.execute("SELECT password_hash, salt FROM users WHERE id = ?;", (user_id,))
            row = cur.fetchone()
            self.assertFalse(verify_password("OldPassword123!", row["password_hash"], row["salt"]))
            self.assertTrue(verify_password("NewPassword456!", row["password_hash"], row["salt"]))

    def test_session_management(self):
        email = "patient.session@testauth.com"
        user_data, verify_token = create_user(email, "Password123!")
        user_id = user_data["id"]
        verify_user_email(verify_token)

        # Create session
        raw_session_token = create_session(user_id)
        self.assertIsNotNone(raw_session_token)

        # Fetch user by session
        user = get_user_from_session(raw_session_token)
        self.assertIsNotNone(user)
        self.assertEqual(user["id"], user_id)
        self.assertEqual(user["email"], email)

        # Revoke session
        delete_session(raw_session_token)
        user_after = get_user_from_session(raw_session_token)
        self.assertIsNone(user_after)

    def test_csrf_token_validation(self):
        session_id = "test_session_id_abcdef123456"
        token = generate_csrf_token(session_id)
        self.assertIsInstance(token, str)

        # Valid CSRF token matches
        self.assertTrue(verify_csrf_token(token, session_id))

        # Tampered CSRF token fails
        self.assertFalse(verify_csrf_token(token + "x", session_id))
        self.assertFalse(verify_csrf_token(token, "different_session"))
        self.assertFalse(verify_csrf_token("", session_id))
        self.assertFalse(verify_csrf_token(None, session_id))

    def test_rate_limiting_sliding_window(self):
        ip = "192.168.1.100"
        action = "login"

        # First 5 attempts within 15 minutes allowed
        for i in range(5):
            allowed, remaining = check_rate_limit(action, ip, max_attempts=5, window_seconds=15 * 60)
            self.assertTrue(allowed, f"Attempt {i+1} should be allowed")

        # 6th attempt is blocked
        allowed, retry_sec = check_rate_limit(action, ip, max_attempts=5, window_seconds=15 * 60)
        self.assertFalse(allowed)
        self.assertGreater(retry_sec, 0)

        # Different IP is allowed
        allowed_other, _ = check_rate_limit(action, "192.168.1.101", max_attempts=5, window_seconds=15 * 60)
        self.assertTrue(allowed_other)

        # Resetting rate limit restores access
        reset_rate_limit(action, ip)
        allowed_after_reset, _ = check_rate_limit(action, ip, max_attempts=5, window_seconds=15 * 60)
        self.assertTrue(allowed_after_reset)

    def test_dpdp_account_deletion_preserves_tax_invoices(self):
        email = "delete.me@testauth.com"
        user_data, token = create_user(email, "Password123!")
        user_id = user_data["id"]
        raw_session = create_session(user_id)

        # Add subscription
        with db_cursor() as cur:
            cur.execute("""
                INSERT INTO subscriptions (user_id, status, consent_text, consent_at, preferences)
                VALUES (?, 'ACTIVE', 'I agree', CURRENT_TIMESTAMP, '{"wellness_tips": 1}');
            """, (user_id,))
            # Add a tax invoice record
            cur.execute("""
                INSERT INTO invoices (invoice_number, booking_id, financial_year, sequence, created_at, pdf_path, total_amount)
                VALUES ('TBC-INV-TEST-001', 'BKG-001', '2026-27', 1, CURRENT_TIMESTAMP, 'invoices/test.pdf', 2500.0);
            """)

        # Perform DPDP Account Deletion
        ok = delete_user_account_and_data(user_id)
        self.assertTrue(ok)

        # Verify user, sessions, subscriptions deleted
        with db_cursor(commit=False) as cur:
            cur.execute("SELECT * FROM users WHERE id = ?;", (user_id,))
            self.assertIsNone(cur.fetchone())

            cur.execute("SELECT * FROM sessions WHERE user_id = ?;", (user_id,))
            self.assertEqual(len(cur.fetchall()), 0)

            cur.execute("SELECT * FROM subscriptions WHERE user_id = ?;", (user_id,))
            self.assertEqual(len(cur.fetchall()), 0)

            # Invoice MUST be retained for statutory tax compliance
            cur.execute("SELECT invoice_number FROM invoices WHERE invoice_number = 'TBC-INV-TEST-001';")
            inv = cur.fetchone()
            self.assertIsNotNone(inv)


if __name__ == "__main__":
    unittest.main()
