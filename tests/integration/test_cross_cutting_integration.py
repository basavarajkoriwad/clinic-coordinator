"""
Integration Tests for Cross-Cutting Concerns:
- Patient typed name propagation
- Elimination of deprecated names
- Profile reuse vs creation on same phone
- SHA-256 tamper-evident audit ledger
- Staff dashboard privacy snapshot formatting
"""

from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
import unittest

root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from src.models import (
    BookingState,
    TaskPriority,
)
from tests.helpers import create_fresh_coordinator, seed_test_clinicians_and_slots


BANNED_NAMES = ["Rohan", "Arjun", "Meera", "Meghali", "Kavita", "Priya", "Dr. Sharma"]


class TestCrossCuttingIntegration(unittest.TestCase):
    def setUp(self):
        self.coord = create_fresh_coordinator(slot_ttl_minutes=15)
        seed_test_clinicians_and_slots(self.coord)

    def test_zoya_menon_name_propagation_and_banned_names_absence(self):
        patient = self.coord.register_or_get_patient("Zoya Menon", "+919876543210")
        doc = self.coord.clinicians["DOC-101"]
        slot = self.coord.setmore.slots["SLOT-101"]

        # Hold & Order
        booking = self.coord.initiate_booking(patient.patient_id, doc.clinician_id, slot.slot_id, doc.specialty)

        # Payment Webhook
        raw_payload = json.dumps(self.coord.gateway.generate_webhook_payload(booking.payment.order_id))
        sig = self.coord.gateway.compute_signature(raw_payload)
        self.coord.handle_payment_webhook(raw_payload, sig)

        # Check all messages sent to Zoya
        messages = self.coord.whatsapp.get_messages_for_phone(patient.phone_number)
        all_message_text = " ".join(m["content"] for m in messages)

        # Must contain "Zoya"
        self.assertIn("Zoya", all_message_text)

        # Banned names must be absent from messages
        for banned in BANNED_NAMES:
            self.assertNotIn(banned, all_message_text)

        # Banned names must be absent from tasks
        for task in self.coord.tasks.tasks.values():
            for banned in BANNED_NAMES:
                self.assertNotIn(banned, task.title)
                self.assertNotIn(banned, task.description)

    def test_aarav_iyer_name_propagation(self):
        patient = self.coord.register_or_get_patient("Aarav Iyer", "+919876543211")
        doc = self.coord.clinicians["DOC-102"]
        slot = self.coord.setmore.slots["SLOT-R1"]

        booking = self.coord.initiate_booking(patient.patient_id, doc.clinician_id, slot.slot_id, doc.specialty)
        raw_payload = json.dumps(self.coord.gateway.generate_webhook_payload(booking.payment.order_id))
        sig = self.coord.gateway.compute_signature(raw_payload)
        self.coord.handle_payment_webhook(raw_payload, sig)

        messages = self.coord.whatsapp.get_messages_for_phone(patient.phone_number)
        all_message_text = " ".join(m["content"] for m in messages)
        self.assertIn("Aarav", all_message_text)

        for banned in BANNED_NAMES:
            self.assertNotIn(banned, all_message_text)

    def test_same_phone_same_name_reuses_different_name_creates(self):
        phone = "+919845012345"

        # 1. Register Zoya Menon
        p1 = self.coord.register_or_get_patient("Zoya Menon", phone)
        id1 = p1.patient_id

        # 2. Register same name on same phone -> REUSES profile
        p1_reuse = self.coord.register_or_get_patient("Zoya Menon", phone)
        self.assertEqual(p1_reuse.patient_id, id1)

        # 3. Register different name on same phone -> CREATES new profile
        p2 = self.coord.register_or_get_patient("Aarav Iyer", phone)
        self.assertNotEqual(p2.patient_id, id1)
        self.assertEqual(p2.phone_number, phone)

        # 4. Resolve phone returns multiple profiles
        status, profiles = self.coord.resolve_patient_by_phone(phone)
        self.assertEqual(status, "MULTIPLE_PROFILES")
        self.assertEqual(len(profiles), 2)

    def test_state_transitions_generate_verifiable_audit_chain(self):
        p = self.coord.register_or_get_patient("Zoya Menon", "+919876543210")
        doc = self.coord.clinicians["DOC-101"]
        slot = self.coord.setmore.slots["SLOT-101"]

        # Hold
        b = self.coord.initiate_booking(p.patient_id, doc.clinician_id, slot.slot_id, doc.specialty)

        # Webhook
        raw_payload = json.dumps(self.coord.gateway.generate_webhook_payload(b.payment.order_id))
        sig = self.coord.gateway.compute_signature(raw_payload)
        self.coord.handle_payment_webhook(raw_payload, sig)

        # Verify audit chain
        self.assertTrue(len(self.coord.audit_log) >= 3)
        valid, broken_seq = self.coord.verify_audit_chain()
        self.assertTrue(valid)
        self.assertIsNone(broken_seq)

    def test_dashboard_snapshot_privacy_formatting(self):
        phone = "+919876543210"
        patient = self.coord.register_or_get_patient("Zoya Menon", phone)

        # Create task
        task = self.coord.tasks.create_task(
            patient_id=patient.patient_id,
            title=f"Callback Request: Zoya (****{phone[-4:]})",
            priority=TaskPriority.P1_HIGH,
            sla_minutes=30,
        )

        # Verify task identity formatting
        self.assertIn("Zoya (****3210)", task.title)
        self.assertNotIn("+919876543210", task.title)
        self.assertNotIn("Sexology", task.title)


if __name__ == "__main__":
    unittest.main()
