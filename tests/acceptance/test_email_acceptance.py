"""
Acceptance Tests for The Bengaluru Clinic Email Engine.
Validates complete end-to-end patient journeys, privacy guarantees,
transactional invoice attachments, reassuring emails, and rotating digests.
"""

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sys
import unittest

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

import config
from src.db import init_db, db_cursor, hash_token
from src.models import Clinician, TimeSlot, PatientProfile, BookingState
from src.mock_services import MockSetmoreService, MockPaymentGateway, MockWhatsAppService, TaskManager
from src.coordinator import ClinicBookingCoordinator
from src.auth import create_user, verify_user_email
from src.mailer import (
    enqueue_email,
    render_email,
    _process_queue_batch,
    trigger_weekly_digest_now,
    get_dev_mailbox_emails,
    get_email_record_by_id,
    get_email_attachment_bytes,
)


class TestEmailAcceptance(unittest.TestCase):
    def setUp(self):
        init_db()
        self.orig_mail_mode = config.MAIL_MODE
        config.MAIL_MODE = "dev"
        # Reset tables
        with db_cursor() as cur:
            cur.execute("DELETE FROM email_queue;")
            cur.execute("DELETE FROM email_log;")
            cur.execute("DELETE FROM invoices;")
            cur.execute("DELETE FROM subscriptions;")
            cur.execute("DELETE FROM users WHERE email LIKE '%@testacceptance.com';")

    def tearDown(self):
        config.MAIL_MODE = self.orig_mail_mode

    def _setup_coordinator(self):
        setmore = MockSetmoreService()
        gateway = MockPaymentGateway()
        whatsapp = MockWhatsAppService()
        tasks = TaskManager()
        coord = ClinicBookingCoordinator(setmore, gateway, whatsapp, tasks, slot_ttl_minutes=15)

        # Register Clinicians
        doc1 = Clinician("doc_priya", "Dr. Priya Nair", "Clinical Psychologist", "staff_key_1", 2500.0, 50)
        doc2 = Clinician("doc_arun", "Dr. Arun Kumar", "Sexologist & Psychiatrist", "staff_key_2", 3000.0, 45)
        coord.clinicians["doc_priya"] = doc1
        coord.clinicians["doc_arun"] = doc2

        # Create available slots
        now = datetime.now()
        s1 = TimeSlot("slot_101", "doc_priya", now + timedelta(days=2, hours=10), now + timedelta(days=2, hours=10, minutes=50))
        s2 = TimeSlot("slot_102", "doc_arun", now + timedelta(days=3, hours=15), now + timedelta(days=3, hours=15, minutes=45))
        coord.setmore.slots["slot_101"] = s1
        coord.setmore.slots["slot_102"] = s2

        return coord, setmore, gateway, whatsapp, tasks

    def test_acceptance_journey_payment_and_invoice_pdf(self):
        """
        Acceptance: A patient books an appointment and pays online.
        They must receive a confirmation email with a signed PDF tax invoice.
        The invoice must be valid PDF 1.4, contain Indian Rupee amount in words,
        and never include any sensitive clinical terms.
        """
        coord, setmore, gateway, whatsapp, tasks = self._setup_coordinator()
        patient_email = "zoya.menon@testacceptance.com"
        patient = coord.register_or_get_patient("Zoya Menon", "+919876543210")

        booking = coord.initiate_booking(patient.patient_id, "doc_priya", "slot_101", "Clinical Consultation")
        self.assertIsNotNone(booking)
        booking.receipt_email = patient_email

        # Simulate Payment Webhook
        order_id = booking.payment.order_id
        webhook_dict = gateway.generate_webhook_payload(order_id=order_id)
        raw_body = json.dumps(webhook_dict)
        signature = gateway.compute_signature(raw_body)

        result = coord.handle_payment_webhook(raw_body, signature)
        self.assertEqual(result["status"], "success")

        # Process email queue
        _process_queue_batch()

        # Verify Dev Mailbox
        emails = get_dev_mailbox_emails(10)
        self.assertEqual(len(emails), 1)
        email_meta = emails[0]
        self.assertEqual(email_meta["to_email"], patient_email)
        self.assertEqual(email_meta["template"], "payment_confirmed")
        self.assertEqual(email_meta["status"], "SENT-IN-DEV")
        self.assertEqual(email_meta["has_attachment"], 1)
        self.assertTrue(email_meta["attachment_name"].startswith("TBC-INV-"))

        # Verify attachment content
        att_res = get_email_attachment_bytes(email_meta["id"])
        self.assertIsNotNone(att_res)
        att_name, att_bytes = att_res
        self.assertTrue(att_bytes.startswith(b"%PDF-1.4"))
        self.assertTrue(att_bytes.strip().endswith(b"%%EOF"))

        pdf_str = att_bytes.decode("latin-1", errors="ignore")
        self.assertIn("INVOICE NO:", pdf_str)
        self.assertIn("Zoya Menon", pdf_str)
        self.assertIn("Two Thousand Five Hundred", pdf_str)

    def test_acceptance_duplicate_webhook_deduplication(self):
        """
        Acceptance: Duplicate webhook deliveries must be deduplicated cleanly.
        Only one confirmation email and tax invoice is ever produced.
        """
        coord, setmore, gateway, whatsapp, tasks = self._setup_coordinator()
        patient_email = "patient.dedupe@testacceptance.com"
        patient = coord.register_or_get_patient("Kabir Sen", "+919876543211")

        booking = coord.initiate_booking(patient.patient_id, "doc_priya", "slot_101", "Clinical Consultation")
        booking.receipt_email = patient_email

        order_id = booking.payment.order_id
        webhook_dict = gateway.generate_webhook_payload(order_id=order_id)
        raw_body = json.dumps(webhook_dict)
        signature = gateway.compute_signature(raw_body)

        # Webhook 1
        res1 = coord.handle_payment_webhook(raw_body, signature)
        self.assertEqual(res1["status"], "success")

        # Webhook 2 (duplicate delivery)
        res2 = coord.handle_payment_webhook(raw_body, signature)
        self.assertEqual(res2["status"], "ok")
        self.assertIn("Duplicate", res2["message"])

        _process_queue_batch()

        # Exactly 1 email in queue
        with db_cursor(commit=False) as cur:
            cur.execute("SELECT COUNT(*) as cnt FROM email_queue WHERE to_email = ?;", (patient_email,))
            self.assertEqual(cur.fetchone()["cnt"], 1)

    def test_acceptance_slot_lost_late_payment_reassurance(self):
        """
        Acceptance: If a patient pays late after the 15-minute hold expired and
        the slot was taken by someone else, send the Slot-Lost Reassurance email
        explaining priority re-booking or immediate refund. Do NOT send an invoice.
        """
        coord, setmore, gateway, whatsapp, tasks = self._setup_coordinator()
        patient_email = "late.patient@testacceptance.com"
        patient = coord.register_or_get_patient("Devika Sharma", "+919876543212")

        booking = coord.initiate_booking(patient.patient_id, "doc_priya", "slot_101", "Clinical Consultation")
        booking.receipt_email = patient_email

        # Hold expires
        booking.hold_expires_at = datetime.now() - timedelta(minutes=5)
        slot = coord.setmore.slots[booking.slot_id]
        slot.is_held = False
        slot.held_by_booking_id = None
        # Another patient takes the slot
        slot.is_booked = True

        # Late payment arrives
        order_id = booking.payment.order_id
        webhook_dict = gateway.generate_webhook_payload(order_id=order_id)
        raw_body = json.dumps(webhook_dict)
        signature = gateway.compute_signature(raw_body)

        res = coord.handle_payment_webhook(raw_body, signature)
        self.assertEqual(res["status"], "exception")
        self.assertEqual(res["state"], BookingState.PAYMENT_RECEIVED_SLOT_LOST)

        _process_queue_batch()

        emails = get_dev_mailbox_emails(10)
        reassurance = [e for e in emails if e["to_email"] == patient_email][0]
        self.assertEqual(reassurance["template"], "slot_lost_reassurance")
        self.assertIn("Priority Rescheduling", reassurance["subject"])
        self.assertEqual(reassurance["has_attachment"], 0)  # No tax invoice

    def test_acceptance_calendar_outage_reassurance(self):
        """
        Acceptance: If Setmore returns 500 error after payment captured,
        reassure patient their payment is safe and staff will confirm within 30 min.
        """
        coord, setmore, gateway, whatsapp, tasks = self._setup_coordinator()
        patient_email = "outage.patient@testacceptance.com"
        patient = coord.register_or_get_patient("Meera Krishnan", "+919876543213")

        booking = coord.initiate_booking(patient.patient_id, "doc_priya", "slot_101", "Clinical Consultation")
        booking.receipt_email = patient_email

        # Simulate Setmore 500
        setmore.simulate_api_failure = True

        order_id = booking.payment.order_id
        webhook_dict = gateway.generate_webhook_payload(order_id=order_id)
        raw_body = json.dumps(webhook_dict)
        signature = gateway.compute_signature(raw_body)

        res = coord.handle_payment_webhook(raw_body, signature)
        self.assertEqual(res["status"], "exception")
        self.assertEqual(res["state"], BookingState.PAYMENT_CAPTURED_BOOKING_FAILED)

        _process_queue_batch()

        emails = get_dev_mailbox_emails(10)
        reassurance = [e for e in emails if e["to_email"] == patient_email][0]
        self.assertEqual(reassurance["template"], "calendar_failed_reassurance")
        self.assertIn("Appointment Update", reassurance["subject"])

    def test_acceptance_weekly_digest_unsubscribed_exclusion(self):
        """
        Acceptance: Rotating newsletter digest is sent to ACTIVE subscribers only.
        Unsubscribed users must never receive it.
        """
        u1, _ = create_user("active.sub@testacceptance.com", "Password123!")
        verify_user_email(_)
        u2, _ = create_user("unsub.user@testacceptance.com", "Password123!")
        verify_user_email(_)

        with db_cursor() as cur:
            # Active subscriber
            cur.execute("""
                INSERT INTO subscriptions (user_id, status, unsub_token_hash, consent_text, consent_at, preferences)
                VALUES (?, 'ACTIVE', ?, 'Agreed', CURRENT_TIMESTAMP, '{"wellness_tips": true}');
            """, (u1["id"], hash_token("unsub_active_123")))
            # Unsubscribed user
            cur.execute("""
                INSERT INTO subscriptions (user_id, status, unsub_token_hash, consent_text, consent_at, preferences)
                VALUES (?, 'UNSUBSCRIBED', ?, 'Agreed', CURRENT_TIMESTAMP, '{"wellness_tips": true}');
            """, (u2["id"], hash_token("unsub_unsub_456")))

        # Trigger digest
        count = trigger_weekly_digest_now()
        self.assertEqual(count, 1)

        _process_queue_batch()

        emails = get_dev_mailbox_emails(10)
        sent_to = [e["to_email"] for e in emails]
        self.assertIn("active.sub@testacceptance.com", sent_to)
        self.assertNotIn("unsub.user@testacceptance.com", sent_to)

    def test_acceptance_zero_diagnostic_terms_across_all_templates(self):
        """
        Acceptance (DPDP Act & Clinical Privacy):
        Zero diagnostic terms, conditions, symptoms, or sensitive terms in ANY
        email subject or body across all HTML and TXT email templates.
        """
        sensitive_terms = [
            "erectile", "dysfunction", "premature", "ejaculation", "depression",
            "anxiety", "schizophrenia", "bipolar", "disorder", "psychiatric medication",
            "vaginismus", "impotence", "suicide", "addiction"
        ]

        templates_dir = ROOT_DIR / "templates" / "email"
        self.assertTrue(templates_dir.exists())

        for template_file in templates_dir.glob("*.*"):
            content = template_file.read_text(encoding="utf-8").lower()
            for term in sensitive_terms:
                self.assertNotIn(
                    term,
                    content,
                    f"Template '{template_file.name}' contains sensitive/diagnostic term '{term}' violation!"
                )


if __name__ == "__main__":
    unittest.main()
