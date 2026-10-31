"""
Unit Tests for Service Mock Adapters (Setmore, Payment Gateway, WhatsApp, Task Manager).
"""

from datetime import datetime, timedelta
from pathlib import Path
import sys
import unittest

root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from src.models import (
    BookingRecord,
    TaskPriority,
    TaskStatus,
    TimeSlot,
)
from src.mock_services import (
    MockPaymentGateway,
    MockSetmoreService,
    MockWhatsAppService,
    TaskManager,
)


class TestMockServicesUnit(unittest.TestCase):
    def setUp(self):
        self.setmore = MockSetmoreService()
        self.gateway = MockPaymentGateway(webhook_secret="test_secret_123")
        self.whatsapp = MockWhatsAppService()
        self.tasks = TaskManager()

    # -------------------------------------------------------------
    # Setmore Service Tests
    # -------------------------------------------------------------
    def test_setmore_hold_release_extend_lifecycle(self):
        slot = TimeSlot(
            slot_id="SLOT-U1",
            clinician_id="DOC-1",
            start_time=datetime.now() + timedelta(days=1),
            end_time=datetime.now() + timedelta(days=1, minutes=50),
        )
        self.setmore.add_slot(slot)

        # 1. Check availability
        self.assertTrue(self.setmore.check_availability("SLOT-U1"))

        # 2. Hold slot
        held = self.setmore.hold_slot("SLOT-U1", "BKG-1", ttl_minutes=15)
        self.assertTrue(held)
        self.assertFalse(self.setmore.check_availability("SLOT-U1"))
        self.assertTrue(slot.is_held)
        self.assertEqual(slot.held_by_booking_id, "BKG-1")

        # 3. Cannot double-hold
        double_held = self.setmore.hold_slot("SLOT-U1", "BKG-2", ttl_minutes=15)
        self.assertFalse(double_held)

        # 4. Extend hold by 60 mins
        extended = self.setmore.extend_hold("SLOT-U1", additional_minutes=60)
        self.assertTrue(extended)
        self.assertTrue(slot.held_until > datetime.now() + timedelta(minutes=40))

        # 5. Release hold
        self.setmore.release_hold("SLOT-U1")
        self.assertFalse(slot.is_held)
        self.assertIsNone(slot.held_until)
        self.assertTrue(self.setmore.check_availability("SLOT-U1"))

    def test_setmore_confirm_and_cancel_appointment(self):
        slot = TimeSlot(
            slot_id="SLOT-U2",
            clinician_id="DOC-1",
            start_time=datetime.now() + timedelta(days=2),
            end_time=datetime.now() + timedelta(days=2, minutes=50),
        )
        self.setmore.add_slot(slot)
        self.setmore.hold_slot("SLOT-U2", "BKG-CONFIRM", ttl_minutes=15)

        booking = BookingRecord(
            booking_id="BKG-CONFIRM",
            patient_id="PAT-1",
            clinician_id="DOC-1",
            slot_id="SLOT-U2",
            service_name="Therapy",
        )

        apt_id = self.setmore.confirm_appointment(booking)
        self.assertTrue(apt_id.startswith("SETMORE-APT-"))
        self.assertTrue(slot.is_booked)
        self.assertFalse(slot.is_held)
        self.assertFalse(self.setmore.check_availability("SLOT-U2"))

        # Canceling appointment frees the slot
        cancelled = self.setmore.cancel_appointment(apt_id)
        self.assertTrue(cancelled)
        self.assertEqual(self.setmore.appointments[apt_id]["status"], "CANCELLED")
        self.assertFalse(slot.is_booked)
        self.assertTrue(self.setmore.check_availability("SLOT-U2"))

    def test_setmore_simulate_api_failure(self):
        slot = TimeSlot(
            slot_id="SLOT-U3",
            clinician_id="DOC-1",
            start_time=datetime.now() + timedelta(days=1),
            end_time=datetime.now() + timedelta(days=1, minutes=50),
        )
        self.setmore.add_slot(slot)
        booking = BookingRecord(booking_id="BKG-ERR", slot_id="SLOT-U3", clinician_id="DOC-1")

        self.setmore.simulate_api_failure = True
        with self.assertRaises(RuntimeError) as ctx:
            self.setmore.confirm_appointment(booking)
        self.assertIn("Setmore API Error 500", str(ctx.exception))

    # -------------------------------------------------------------
    # Payment Gateway Tests
    # -------------------------------------------------------------
    def test_gateway_order_creation_and_payload(self):
        record = self.gateway.create_order("BKG-99", 2500.0, "+919876543210")
        self.assertEqual(record.order_id, "order_bkg_99")
        self.assertEqual(record.amount_inr, 2500.0)
        self.assertIn("https://pay.bengaluru-clinic.in/pay/order_bkg_99", record.payment_link_url)

        payload = self.gateway.generate_webhook_payload("order_bkg_99", payment_id="pay_test_123")
        self.assertEqual(payload["event"], "order.paid")
        self.assertEqual(payload["payload"]["payment"]["entity"]["amount"], 250000)  # Paise
        self.assertEqual(payload["payload"]["payment"]["entity"]["id"], "pay_test_123")

    def test_gateway_hmac_computation_and_verification(self):
        body = '{"event":"order.paid","amount":250000}'
        genuine_sig = self.gateway.compute_signature(body)

        # Genuine signature verifies
        self.assertTrue(self.gateway.verify_webhook_signature(body, genuine_sig))

        # Tampered signature fails
        self.assertFalse(self.gateway.verify_webhook_signature(body, "tampered_sig_12345"))

        # Empty signature fails
        self.assertFalse(self.gateway.verify_webhook_signature(body, ""))

        # Modified body fails
        self.assertFalse(self.gateway.verify_webhook_signature('{"event":"order.paid","amount":100}', genuine_sig))

    def test_gateway_process_refund(self):
        rfnd_id = self.gateway.process_refund("pay_abc", 2500.0, "Patient requested reschedule")
        self.assertTrue(rfnd_id.startswith("rfnd_"))
        self.assertIn(rfnd_id, self.gateway.refunds)
        self.assertEqual(self.gateway.refunds[rfnd_id]["amount_inr"], 2500.0)

    # -------------------------------------------------------------
    # WhatsApp Service Tests
    # -------------------------------------------------------------
    def test_whatsapp_discreet_messaging(self):
        phone = "+919876543210"
        msg = "Your confidential therapy session for Sexual Dysfunction is booked."
        self.whatsapp.send_discreet_message(phone, msg, message_type="CONFIRMATION")

        sent = self.whatsapp.get_messages_for_phone(phone)
        self.assertEqual(len(sent), 1)
        # Verify diagnosis is stripped for privacy
        self.assertNotIn("Sexual Dysfunction", sent[0]["content"])
        self.assertIn("Consultation", sent[0]["content"])

    # -------------------------------------------------------------
    # Task Manager Tests
    # -------------------------------------------------------------
    def test_task_manager_create_filter_and_resolve(self):
        t_p0 = self.tasks.create_task(
            patient_id="PAT-1",
            title="P0 Crisis",
            priority=TaskPriority.P0_URGENT,
            sla_minutes=5,
            assigned_to="Psychiatrist",
        )
        t_p1 = self.tasks.create_task(
            patient_id="PAT-2",
            title="P1 Missed Call",
            priority=TaskPriority.P1_HIGH,
            sla_minutes=30,
            assigned_to="FrontDesk",
        )

        self.assertEqual(len(self.tasks.get_open_tasks()), 2)
        p0_only = self.tasks.get_open_tasks(priority=TaskPriority.P0_URGENT)
        self.assertEqual(len(p0_only), 1)
        self.assertEqual(p0_only[0].task_id, t_p0.task_id)

        # Resolve task
        resolved = self.tasks.resolve_task(
            t_p0.task_id,
            resolved_by="Staff_Lead",
            resolution_notes="Contact made via phone",
        )
        self.assertTrue(resolved)
        self.assertEqual(t_p0.status, TaskStatus.RESOLVED)
        self.assertEqual(t_p0.resolved_by, "Staff_Lead")

        # Now only 1 open task remains
        self.assertEqual(len(self.tasks.get_open_tasks()), 1)


if __name__ == "__main__":
    unittest.main()
