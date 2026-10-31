"""
Integration Tests for Mail Engine, Queue Processing, Retry Backoff, Fake SMTP, and Coordinator Hooks.
"""

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import smtplib
import sys
import unittest

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

import config
from src.db import init_db, db_cursor
from src.models import Clinician, TimeSlot, PatientProfile, BookingState
from src.mock_services import MockSetmoreService, MockPaymentGateway, MockWhatsAppService, TaskManager
from src.coordinator import ClinicBookingCoordinator
from src.mailer import (
    enqueue_email,
    render_email,
    build_mime_message,
    _process_queue_batch,
    mask_email,
    trigger_weekly_digest_now,
    BACKOFF_DELAYS,
    MAX_ATTEMPTS,
)


class FakeSMTPClient:
    def __init__(self, fail: bool = False):
        self.sent_messages = []
        self.fail = fail

    def send_message(self, msg):
        if self.fail:
            raise smtplib.SMTPException("Fake SMTP Connection Dropped")
        self.sent_messages.append(msg)


class TestEmailSystemIntegration(unittest.TestCase):
    def setUp(self):
        init_db()
        self.orig_mail_mode = config.MAIL_MODE
        with db_cursor() as cur:
            cur.execute("DELETE FROM email_queue;")
            cur.execute("DELETE FROM email_log;")
            cur.execute("DELETE FROM invoices;")
            cur.execute("DELETE FROM subscriptions;")
            cur.execute("DELETE FROM users WHERE email LIKE '%@testintegration.com';")

    def tearDown(self):
        config.MAIL_MODE = self.orig_mail_mode

    def test_enqueue_and_process_in_dev_mode(self):
        config.MAIL_MODE = "dev"
        html_body, text_body = render_email(
            "test_email",
            "Test System Notification",
            "Test Email Notification",
            "Integration test dispatch",
            {
                "recipient_email": "patient@testintegration.com",
                "test_timestamp": "30-Oct-2026 10:30 PM",
                "support_email": config.MAIL_FROM_ADDRESS,
                "clinic_name": config.CLINIC_LEGAL_NAME,
                "year": "2026",
            }
        )

        q_id = enqueue_email(
            to_email="patient@testintegration.com",
            template="test_email",
            subject="Test System Notification",
            html_body=html_body,
            text_body=text_body,
            dedupe_key="test_queue_dev_001",
        )
        self.assertIsNotNone(q_id)

        # Process queue
        processed = _process_queue_batch()
        self.assertEqual(processed, 1)

        # Verify DB status is SENT-IN-DEV
        with db_cursor(commit=False) as cur:
            cur.execute("SELECT status, attempts, sent_at FROM email_queue WHERE id = ?;", (q_id,))
            row = cur.fetchone()
            self.assertEqual(row["status"], "SENT-IN-DEV")
            self.assertEqual(row["attempts"], 1)
            self.assertIsNotNone(row["sent_at"])

            cur.execute("SELECT event FROM email_log WHERE queue_id = ? ORDER BY id ASC;", (q_id,))
            logs = [r["event"] for r in cur.fetchall()]
            self.assertIn("QUEUED", logs)
            self.assertIn("SENT-IN-DEV", logs)

    def test_enqueue_and_process_via_fake_smtp(self):
        config.MAIL_MODE = "smtp"
        fake_smtp = FakeSMTPClient(fail=False)

        html_body, text_body = render_email(
            "test_email",
            "Test SMTP Notification",
            "Test Email Notification",
            "Integration test dispatch",
            {
                "recipient_email": "patient@testintegration.com",
                "test_timestamp": "30-Oct-2026 10:30 PM",
                "support_email": config.MAIL_FROM_ADDRESS,
                "clinic_name": config.CLINIC_LEGAL_NAME,
                "year": "2026",
            }
        )

        q_id = enqueue_email(
            to_email="patient@testintegration.com",
            template="test_email",
            subject="Test SMTP Notification",
            html_body=html_body,
            text_body=text_body,
            dedupe_key="test_queue_smtp_001",
        )

        processed = _process_queue_batch(smtp_client_override=fake_smtp)
        self.assertEqual(processed, 1)
        self.assertEqual(len(fake_smtp.sent_messages), 1)

        msg = fake_smtp.sent_messages[0]
        self.assertEqual(msg["Subject"], "Test SMTP Notification")
        self.assertEqual(msg["To"], "patient@testintegration.com")
        self.assertIn(config.MAIL_FROM_NAME, msg["From"])

        # DB status should be SENT
        with db_cursor(commit=False) as cur:
            cur.execute("SELECT status, attempts FROM email_queue WHERE id = ?;", (q_id,))
            row = cur.fetchone()
            self.assertEqual(row["status"], "SENT")
            self.assertEqual(row["attempts"], 1)

    def test_worker_retry_backoff_and_dead_status(self):
        config.MAIL_MODE = "smtp"
        failing_smtp = FakeSMTPClient(fail=True)

        html_body, text_body = render_email(
            "test_email",
            "Test Failing SMTP",
            "Test Email Notification",
            "Integration test dispatch",
            {
                "recipient_email": "patient.fail@testintegration.com",
                "test_timestamp": "30-Oct-2026 10:30 PM",
                "support_email": config.MAIL_FROM_ADDRESS,
                "clinic_name": config.CLINIC_LEGAL_NAME,
                "year": "2026",
            }
        )

        q_id = enqueue_email(
            to_email="patient.fail@testintegration.com",
            template="test_email",
            subject="Test Failing SMTP",
            html_body=html_body,
            text_body=text_body,
            dedupe_key="test_queue_fail_001",
        )

        # Attempt 1 -> fails -> attempts=1, status=QUEUED, backoff set
        _process_queue_batch(smtp_client_override=failing_smtp)
        with db_cursor(commit=False) as cur:
            cur.execute("SELECT status, attempts FROM email_queue WHERE id = ?;", (q_id,))
            row = cur.fetchone()
            self.assertEqual(row["status"], "QUEUED")
            self.assertEqual(row["attempts"], 1)

        # Attempt 2, 3, 4
        past_str = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        for expected_attempts in [2, 3, 4]:
            # Force next_attempt_at into the past so it gets picked up
            with db_cursor(commit=True) as cur:
                cur.execute("UPDATE email_queue SET next_attempt_at = ? WHERE id = ?;", (past_str, q_id))
            _process_queue_batch(smtp_client_override=failing_smtp)

        # After 4 failed attempts, status must be DEAD
        with db_cursor(commit=False) as cur:
            cur.execute("SELECT status, attempts, last_error FROM email_queue WHERE id = ?;", (q_id,))
            row = cur.fetchone()
            self.assertEqual(row["status"], "DEAD")
            self.assertEqual(row["attempts"], 4)
            self.assertIn("Fake SMTP Connection Dropped", row["last_error"])

            cur.execute("SELECT event FROM email_log WHERE queue_id = ? ORDER BY id ASC;", (q_id,))
            logs = [r["event"] for r in cur.fetchall()]
            self.assertIn("DEAD", logs)

    def test_deduplication_guarantee(self):
        dedupe = "unique_webhook_tx_99999"
        q1 = enqueue_email("pat@testintegration.com", "test_email", "Sub 1", "Body", "Body", dedupe_key=dedupe)
        q2 = enqueue_email("pat@testintegration.com", "test_email", "Sub 2", "Body", "Body", dedupe_key=dedupe)

        # Must return same ID and create exactly 1 row
        self.assertEqual(q1, q2)
        with db_cursor(commit=False) as cur:
            cur.execute("SELECT COUNT(*) as cnt FROM email_queue WHERE dedupe_key = ?;", (dedupe,))
            cnt = cur.fetchone()["cnt"]
            self.assertEqual(cnt, 1)

    def test_list_unsubscribe_headers(self):
        msg = build_mime_message(
            to_email="patient@testintegration.com",
            subject="Weekly Digest",
            html_body="<p>Digest</p>",
            text_body="Digest",
            unsubscribe_url="http://localhost:8000/unsubscribe?token=raw_token_xyz",
        )
        self.assertEqual(msg["List-Unsubscribe"], "<http://localhost:8000/unsubscribe?token=raw_token_xyz>")
        self.assertEqual(msg["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click")

    def test_mask_email_utility(self):
        self.assertEqual(mask_email("zoya.menon@gmail.com"), "z***@gmail.com")
        self.assertEqual(mask_email("ab@gmail.com"), "a***@gmail.com")
        self.assertEqual(mask_email("a@b.com"), "*@b.com")
        self.assertEqual(mask_email(""), "***")

    def test_coordinator_payment_enqueues_confirmation_and_invoice(self):
        import json
        setmore = MockSetmoreService()
        gateway = MockPaymentGateway()
        whatsapp = MockWhatsAppService()
        tasks = TaskManager()
        coord = ClinicBookingCoordinator(setmore, gateway, whatsapp, tasks, slot_ttl_minutes=15)

        # Set up clinician and slot
        clinician = Clinician("doc_1", "Dr. Priya Nair", "Clinical Psychologist", "staff_key_1", 2500, 50)
        coord.clinicians["doc_1"] = clinician
        slot_time = datetime.now() + timedelta(days=2)
        slot = TimeSlot("slot_1", "doc_1", slot_time, slot_time + timedelta(minutes=50))
        coord.setmore.slots["slot_1"] = slot

        # Register patient and initiate booking
        patient_phone = "+919876543210"
        patient = coord.register_or_get_patient(patient_phone, "Zoya Menon")
        booking = coord.initiate_booking(patient.patient_id, "doc_1", "slot_1", "Clinical Consultation")
        self.assertIsNotNone(booking)

        # Set receipt email on booking
        booking.receipt_email = "zoya.menon@testintegration.com"

        # Simulate Payment Webhook
        order_id = booking.payment.order_id
        webhook_dict = gateway.generate_webhook_payload(order_id=order_id)
        raw_body = json.dumps(webhook_dict)
        signature = gateway.compute_signature(raw_body)
        result = coord.handle_payment_webhook(raw_body, signature)

        self.assertEqual(result["status"], "success")
        self.assertEqual(booking.state, BookingState.CONFIRMED)

        # Verify email was enqueued in DB
        with db_cursor(commit=False) as cur:
            cur.execute("""
                SELECT id, to_email, template, subject, attachment_name, attachment_bytes
                FROM email_queue
                WHERE to_email = 'zoya.menon@testintegration.com';
            """)
            email_row = cur.fetchone()
            self.assertIsNotNone(email_row)
            self.assertEqual(email_row["template"], "payment_confirmed")
            self.assertIn("Appointment Confirmed", email_row["subject"])
            self.assertTrue(email_row["attachment_name"].startswith("TBC-INV-"))
            self.assertTrue(email_row["attachment_bytes"].startswith(b"%PDF-1.4"))


if __name__ == "__main__":
    unittest.main()
