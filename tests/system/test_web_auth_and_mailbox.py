"""
System HTTP Tests for Web Auth, Accounts, Sessions, Dev Mailbox, and Security Endpoints.
"""

from datetime import datetime, timezone
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import random
import re
import sys
import time
import unittest
from urllib.error import HTTPError
import urllib.parse
import urllib.request

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

import config
from src.db import init_db, db_cursor, hash_token
from tests.helpers import AppServerFixture


class TestWebAuthAndMailbox(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.fixture = None
        cls.base_url = "http://127.0.0.1:8000"
        try:
            req = urllib.request.Request(f"{cls.base_url}/api/status")
            with urllib.request.urlopen(req, timeout=0.5) as res:
                if res.status == 200:
                    return
        except Exception:
            pass

        cls.fixture = AppServerFixture()
        cls.fixture.start()
        cls.base_url = f"http://127.0.0.1:{cls.fixture.port}"

    @classmethod
    def tearDownClass(cls):
        if cls.fixture:
            cls.fixture.stop()

    def setUp(self):
        self.client_ip = f"10.{random.randint(1, 200)}.{random.randint(1, 200)}.{random.randint(1, 200)}"
        self.cookie_jar = CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookie_jar),
            urllib.request.HTTPRedirectHandler(),
        )
        # Clean test user data
        with db_cursor() as cur:
            cur.execute("DELETE FROM sessions;")
            cur.execute("DELETE FROM subscriptions;")
            cur.execute("DELETE FROM email_queue;")
            cur.execute("DELETE FROM email_log;")
            cur.execute("DELETE FROM invoices;")
            cur.execute("DELETE FROM users WHERE email LIKE '%@testsystem.com';")

    def _open(self, url_or_path: str, data: bytes = None, headers: dict = None, method: str = None):
        url = url_or_path if url_or_path.startswith("http") else f"{self.base_url}{url_or_path}"
        hdrs = {"X-Forwarded-For": self.client_ip}
        if headers:
            hdrs.update(headers)
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        return self.opener.open(req)

    def _extract_csrf_token(self, html_text: str) -> str:
        match = re.search(r'name=["\']csrf_token["\']\s+value=["\']([^"\']+)["\']', html_text)
        if not match:
            match = re.search(r'value=["\']([^"\']+)["\']\s+name=["\']csrf_token["\']', html_text)
        self.assertIsNotNone(match, "CSRF token not found in HTML form")
        return match.group(1)

    def test_signup_verify_login_account_journey(self):
        email = f"patient.journey.{int(time.time() * 1000)}@testsystem.com"
        password = "SecurePassword123!"

        # 1. GET /signup -> returns form with CSRF token
        with self._open("/signup") as res:
            self.assertEqual(res.status, 200)
            html = res.read().decode("utf-8")
            self.assertIn("Create Patient Account", html)
            csrf_token = self._extract_csrf_token(html)

        # 2. POST /signup -> creates user, queues verification email
        post_data = urllib.parse.urlencode({
            "email": email,
            "password": password,
            "csrf_token": csrf_token,
        }).encode("utf-8")
        with self._open("/signup", data=post_data, headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST") as res:
            self.assertEqual(res.status, 200)

        # 3. Check Dev Mailbox API for verification email
        with self._open("/api/dev/emails") as res:
            data = json.loads(res.read().decode("utf-8"))
            emails = data.get("emails", [])
            self.assertGreaterEqual(len(emails), 1)
            verify_email_row = [e for e in emails if e["to_email"] == email and e["template"] == "verify_email"][0]
            self.assertIn("Verify Your Email Address", verify_email_row["subject"])

        # Extract verify link from email in DB
        with db_cursor(commit=False) as cur:
            cur.execute("SELECT html_body FROM email_queue WHERE id = ?;", (verify_email_row["id"],))
            email_body = cur.fetchone()["html_body"]

        verify_token_match = re.search(r'/verify\?token=([a-zA-Z0-9_-]+)', email_body)
        self.assertIsNotNone(verify_token_match)
        raw_verify_token = verify_token_match.group(1)

        # 4. Attempt login BEFORE email verification -> MUST return 403
        with self._open("/login") as res:
            login_csrf = self._extract_csrf_token(res.read().decode("utf-8"))

        unverified_post = urllib.parse.urlencode({
            "email": email,
            "password": password,
            "csrf_token": login_csrf,
        }).encode("utf-8")
        try:
            with self._open("/login", data=unverified_post, headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST") as res:
                self.fail("Should have failed with 403 for unverified user")
        except HTTPError as e:
            self.assertEqual(e.code, 403)
            self.assertIn("not been verified yet", e.read().decode("utf-8").lower())

        # 5. GET /verify?token=... -> Successfully verifies user
        with self._open(f"/verify?token={raw_verify_token}") as res:
            self.assertEqual(res.status, 200)
            verify_html = res.read().decode("utf-8")
            self.assertIn("verified", verify_html.lower())

        # 6. POST /login with verified credentials -> Sets session cookie and redirects to /account
        with self._open("/login") as res:
            login_csrf2 = self._extract_csrf_token(res.read().decode("utf-8"))

        login_post = urllib.parse.urlencode({
            "email": email,
            "password": password,
            "csrf_token": login_csrf2,
        }).encode("utf-8")
        with self._open("/login", data=login_post, headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST") as res:
            self.assertEqual(res.status, 200)
            account_html = res.read().decode("utf-8")
            self.assertIn("Patient Profile", account_html)
            self.assertIn(email, account_html)

        # 7. Consent to subscription -> Double Opt-in
        account_csrf = self._extract_csrf_token(account_html)
        consent_post = urllib.parse.urlencode({
            "consent": "1",
            "csrf_token": account_csrf,
        }).encode("utf-8")
        with self._open("/consent", data=consent_post, headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST") as res:
            self.assertEqual(res.status, 200)
            consent_resp = res.read().decode("utf-8")
            self.assertIn("confirmation link", consent_resp.lower())

        # 8. Check Dev Mailbox for Confirm Subscription Email
        with self._open("/api/dev/emails") as res:
            data = json.loads(res.read().decode("utf-8"))
            confirm_email_row = [e for e in data["emails"] if e["to_email"] == email and e["template"] == "confirm_subscription"][0]
            self.assertIn("Confirm Your Subscription", confirm_email_row["subject"])

        # Extract confirm link
        with db_cursor(commit=False) as cur:
            cur.execute("SELECT html_body FROM email_queue WHERE id = ?;", (confirm_email_row["id"],))
            confirm_body = cur.fetchone()["html_body"]

        confirm_token_match = re.search(r'/confirm-subscription\?token=([a-zA-Z0-9_-]+)', confirm_body)
        self.assertIsNotNone(confirm_token_match)
        raw_confirm_token = confirm_token_match.group(1)

        # 9. GET /confirm-subscription?token=... -> Status becomes ACTIVE and Welcome / About email is queued
        with self._open(f"/confirm-subscription?token={raw_confirm_token}") as res:
            self.assertEqual(res.status, 200)
            confirm_page = res.read().decode("utf-8")
            self.assertIn("Subscription Confirmed", confirm_page)

        # 10. Check Dev Mailbox for Welcome / About Email
        with self._open("/api/dev/emails") as res:
            data = json.loads(res.read().decode("utf-8"))
            welcome_email = [e for e in data["emails"] if e["to_email"] == email and e["template"] == "welcome_about"][0]
            self.assertIn("Welcome to The Bengaluru Clinic", welcome_email["subject"])

        with db_cursor(commit=False) as cur:
            cur.execute("SELECT html_body FROM email_queue WHERE id = ?;", (welcome_email["id"],))
            welcome_body = cur.fetchone()["html_body"]

        self.assertIn("Indiranagar", welcome_body)
        self.assertIn("WhatsApp", welcome_body)

        # 11. Unsubscribe via one-click link
        unsub_match = re.search(r'/unsubscribe\?token=([a-zA-Z0-9_-]+)', welcome_body)
        self.assertIsNotNone(unsub_match)
        unsub_token = unsub_match.group(1)

        with self._open(f"/unsubscribe?token={unsub_token}") as res:
            self.assertEqual(res.status, 200)
            unsub_page = res.read().decode("utf-8")
            self.assertIn("Unsubscribed", unsub_page)

        # Check DB subscription status
        with db_cursor(commit=False) as cur:
            cur.execute("SELECT s.status FROM subscriptions s JOIN users u ON s.user_id = u.id WHERE u.email = ?;", (email,))
            sub_status = cur.fetchone()["status"]
            self.assertEqual(sub_status, "UNSUBSCRIBED")

    def test_unauthenticated_account_redirects_to_login(self):
        # Open fresh opener without cookies
        fresh_opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler())
        req = urllib.request.Request(f"{self.base_url}/account", headers={"X-Forwarded-For": self.client_ip})
        with fresh_opener.open(req) as res:
            self.assertEqual(res.status, 200)
            self.assertIn("Patient Account Login", res.read().decode("utf-8"))

    def test_csrf_missing_token_rejected(self):
        post_data = urllib.parse.urlencode({
            "email": "nocsrf@testsystem.com",
            "password": "Password123!",
        }).encode("utf-8")
        try:
            with self._open("/signup", data=post_data, headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST") as res:
                self.fail("Should have failed with 403 CSRF error")
        except HTTPError as e:
            self.assertEqual(e.code, 403)

    def test_privacy_page_disclosures(self):
        with self._open("/privacy") as res:
            self.assertEqual(res.status, 200)
            html = res.read().decode("utf-8")
            self.assertIn("DPDP Act 2023", html)
            self.assertIn("Zero-Diagnosis", html)
            self.assertIn("Digital Personal Data Protection", html)

    def test_dev_mailbox_ui(self):
        with self._open("/dev/mailbox") as res:
            self.assertEqual(res.status, 200)
            html = res.read().decode("utf-8")
            self.assertIn("DEV MAILBOX", html)
            self.assertIn("The Bengaluru Clinic", html)

    def test_invalid_invoice_token_returns_404(self):
        try:
            with self._open("/invoice/invalid_fake_token_123456") as res:
                self.fail("Should have returned 404 for invalid token")
        except HTTPError as e:
            self.assertEqual(e.code, 404)


if __name__ == "__main__":
    unittest.main()
