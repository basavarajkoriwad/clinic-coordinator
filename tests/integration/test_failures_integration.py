"""
Integration Tests for Production Failure Scenarios & Edge Cases.
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
    TaskStatus,
    TimeSlot,
)
from tests.helpers import create_fresh_coordinator, seed_test_clinicians_and_slots


class TestFailuresIntegration(unittest.TestCase):
    def setUp(self):
        self.coord = create_fresh_coordinator(slot_ttl_minutes=15)
        seed_test_clinicians_and_slots(self.coord)

    # -------------------------------------------------------------
    # 1. Late Payment Scenarios
    # -------------------------------------------------------------
    def test_late_payment_slot_lost_and_resolvers(self):
        doc = self.coord.clinicians["DOC-101"]
        slot = self.coord.setmore.slots["SLOT-101"]

        # Patient 1 initiates booking
        p1 = self.coord.register_or_get_patient("Aarav Iyer", "+919876500001")
        b1 = self.coord.initiate_booking(p1.patient_id, doc.clinician_id, slot.slot_id, doc.specialty)

        # 16 minutes pass -> hold expires
        b1.hold_expires_at = datetime.now() - timedelta(minutes=1)
        self.coord.setmore.release_hold(slot.slot_id)

        # Patient 2 books the exact same slot
        p2 = self.coord.register_or_get_patient("Zoya Menon", "+919876500002")
        b2 = self.coord.initiate_booking(p2.patient_id, doc.clinician_id, slot.slot_id, doc.specialty)
        slot.is_booked = True
        slot.held_by_booking_id = b2.booking_id

        # Now Patient 1's webhook arrives (late payment!)
        raw_payload = json.dumps(self.coord.gateway.generate_webhook_payload(b1.payment.order_id))
        sig = self.coord.gateway.compute_signature(raw_payload)
        res = self.coord.handle_payment_webhook(raw_payload, sig)

        # Assert double-booking prevented, P0 task created
        self.assertEqual(res["status"], "exception")
        self.assertEqual(b1.state, BookingState.PAYMENT_RECEIVED_SLOT_LOST)
        self.assertEqual(b1.payment.status, "CAPTURED")

        p0_tasks = self.coord.tasks.get_open_tasks(priority=TaskPriority.P0_URGENT)
        self.assertTrue(any("Slot Lost" in t.title for t in p0_tasks))

        # Test Reschedule Resolver
        new_slot = self.coord.setmore.slots["SLOT-A2"]
        res_resched = self.coord.resolve_slot_lost(b1.booking_id, action="reschedule", staff_id="Staff_Coordinator", new_slot_id=new_slot.slot_id)
        self.assertEqual(res_resched["status"], "rescheduled")
        self.assertEqual(b1.state, BookingState.CONFIRMED)
        self.assertEqual(b1.slot_id, new_slot.slot_id)

        # Test Refund Resolver on another booking
        b_refund = self.coord.initiate_booking(p1.patient_id, doc.clinician_id, "SLOT-103", doc.specialty)
        b_refund.state = BookingState.PAYMENT_RECEIVED_SLOT_LOST
        b_refund.payment.payment_id = "pay_test_refund_123"
        res_refund = self.coord.resolve_slot_lost(b_refund.booking_id, action="refund", staff_id="Staff_Coordinator")
        self.assertEqual(res_refund["status"], "refunded")
        self.assertEqual(b_refund.state, BookingState.REFUNDED)

    def test_late_payment_slot_still_free_confirms_normally(self):
        doc = self.coord.clinicians["DOC-101"]
        slot = self.coord.setmore.slots["SLOT-101"]

        patient = self.coord.register_or_get_patient("Aarav Iyer", "+919876500003")
        booking = self.coord.initiate_booking(patient.patient_id, doc.clinician_id, slot.slot_id, doc.specialty)

        # Hold expired, but slot NOT taken by anyone else
        booking.hold_expires_at = datetime.now() - timedelta(minutes=1)

        raw_payload = json.dumps(self.coord.gateway.generate_webhook_payload(booking.payment.order_id))
        sig = self.coord.gateway.compute_signature(raw_payload)
        res = self.coord.handle_payment_webhook(raw_payload, sig)

        self.assertEqual(res["status"], "success")
        self.assertEqual(booking.state, BookingState.CONFIRMED)

    # -------------------------------------------------------------
    # 2. Setmore 500 Outage & Retry Escalation
    # -------------------------------------------------------------
    def test_setmore_outage_hold_extension_and_retry_lifecycle(self):
        doc = self.coord.clinicians["DOC-102"]
        slot = self.coord.setmore.slots["SLOT-R1"]

        patient = self.coord.register_or_get_patient("Aarav Iyer", "+919876500004")
        booking = self.coord.initiate_booking(patient.patient_id, doc.clinician_id, slot.slot_id, doc.specialty)

        # Inject Setmore 500 Outage
        self.coord.setmore.simulate_api_failure = True

        raw_payload = json.dumps(self.coord.gateway.generate_webhook_payload(booking.payment.order_id))
        sig = self.coord.gateway.compute_signature(raw_payload)
        res = self.coord.handle_payment_webhook(raw_payload, sig)

        self.assertEqual(res["status"], "exception")
        self.assertEqual(booking.state, BookingState.PAYMENT_CAPTURED_BOOKING_FAILED)

        # Verify hold was extended to 60 minutes
        self.assertTrue(slot.held_until > datetime.now() + timedelta(minutes=45))

        # Check P0 task with 10-minute SLA
        p0_tasks = self.coord.tasks.get_open_tasks(priority=TaskPriority.P0_URGENT)
        target_task = next(t for t in p0_tasks if "Setmore Booking Failed" in t.title)
        self.assertEqual(target_task.assigned_to, "Clinic_Manager")

        # Retry 1 fails
        res1 = self.coord.retry_failed_booking(booking.booking_id, staff_id="Staff_Coordinator")
        self.assertEqual(res1["status"], "failed")
        self.assertEqual(booking.retry_count, 1)

        # Retry 2 fails -> escalates task!
        res2 = self.coord.retry_failed_booking(booking.booking_id, staff_id="Staff_Coordinator")
        self.assertEqual(res2["status"], "failed")
        self.assertEqual(booking.retry_count, 2)
        self.assertEqual(target_task.status, TaskStatus.ESCALATED)

        # System recovers -> Retry 3 succeeds!
        self.coord.setmore.simulate_api_failure = False
        res3 = self.coord.retry_failed_booking(booking.booking_id, staff_id="Staff_Coordinator")
        self.assertEqual(res3["status"], "resolved")
        self.assertEqual(booking.state, BookingState.CONFIRMED)
        self.assertEqual(target_task.status, TaskStatus.RESOLVED)

    # -------------------------------------------------------------
    # 3. Webhook Safety & Security Edge Cases
    # -------------------------------------------------------------
    def test_webhook_safety_edge_cases(self):
        doc = self.coord.clinicians["DOC-101"]
        slot = self.coord.setmore.slots["SLOT-101"]
        patient = self.coord.register_or_get_patient("Zoya Menon", "+919876500005")
        booking = self.coord.initiate_booking(patient.patient_id, doc.clinician_id, slot.slot_id, doc.specialty)
        order_id = booking.payment.order_id

        # 1. Forged Signature
        body = json.dumps(self.coord.gateway.generate_webhook_payload(order_id))
        res_forged = self.coord.handle_payment_webhook(body, "bad_forged_sig")
        self.assertEqual(res_forged["status"], "error")
        self.assertIn("Invalid webhook signature", res_forged["message"])

        # 2. Malformed signed body
        sig_malformed = self.coord.gateway.compute_signature("{bad json")
        res_malformed = self.coord.handle_payment_webhook("{bad json", sig_malformed)
        self.assertEqual(res_malformed["status"], "error")
        self.assertIn("Malformed JSON", res_malformed["message"])

        # 3. Wrong event type (e.g. order.created)
        payload_wrong_event = self.coord.gateway.generate_webhook_payload(order_id, event="order.created")
        body_wrong_event = json.dumps(payload_wrong_event)
        sig_wrong_event = self.coord.gateway.compute_signature(body_wrong_event)
        res_wrong_event = self.coord.handle_payment_webhook(body_wrong_event, sig_wrong_event)
        self.assertEqual(res_wrong_event["status"], "ignored")

        # 4. Wrong amount (expected ₹2500, sent ₹1000)
        payload_wrong_amount = self.coord.gateway.generate_webhook_payload(order_id)
        payload_wrong_amount["payload"]["payment"]["entity"]["amount"] = 100000  # ₹1000
        body_wrong_amount = json.dumps(payload_wrong_amount)
        sig_wrong_amount = self.coord.gateway.compute_signature(body_wrong_amount)
        res_wrong_amount = self.coord.handle_payment_webhook(body_wrong_amount, sig_wrong_amount)
        self.assertEqual(res_wrong_amount["status"], "error")
        self.assertIn("mismatch", res_wrong_amount["message"])

        # 5. Unmapped order ID
        payload_unmapped = self.coord.gateway.generate_webhook_payload("order_non_existent_999")
        body_unmapped = json.dumps(payload_unmapped)
        sig_unmapped = self.coord.gateway.compute_signature(body_unmapped)
        res_unmapped = self.coord.handle_payment_webhook(body_unmapped, sig_unmapped)
        self.assertEqual(res_unmapped["status"], "error")
        self.assertIn("not associated with any active booking", res_unmapped["message"])

        # 6. Duplicate delivery
        valid_payload = json.dumps(self.coord.gateway.generate_webhook_payload(order_id, payment_id="pay_dup_100"))
        valid_sig = self.coord.gateway.compute_signature(valid_payload)
        res_first = self.coord.handle_payment_webhook(valid_payload, valid_sig)
        self.assertEqual(res_first["status"], "success")

        # Second delivery with same payment_id
        res_second = self.coord.handle_payment_webhook(valid_payload, valid_sig)
        self.assertEqual(res_second["status"], "ok")
        self.assertIn("idempotent", res_second["message"])

    # -------------------------------------------------------------
    # 4. Shared Phone Disambiguation & PIN Lockout
    # -------------------------------------------------------------
    def test_shared_phone_pin_flow_and_lockout(self):
        shared_phone = "+919876500000"
        p_pooja = self.coord.register_or_get_patient("Pooja Kulkarni", shared_phone, discrete_name="Pooja")
        p_sameer = self.coord.register_or_get_patient("Sameer Kulkarni", shared_phone, discrete_name="Sameer")
        self.coord.set_patient_pin(p_pooja.patient_id, "4321")
        self.coord.set_patient_pin(p_sameer.patient_id, "8765")

        status, profiles = self.coord.resolve_patient_by_phone(shared_phone)
        self.assertEqual(status, "MULTIPLE_PROFILES")
        self.assertEqual(len(profiles), 2)

        # 3 wrong attempts triggers P1 task and lock
        self.coord.verify_patient_pin(p_pooja.patient_id, "0000")
        self.coord.verify_patient_pin(p_pooja.patient_id, "0000")
        ok3, msg3 = self.coord.verify_patient_pin(p_pooja.patient_id, "0000")
        self.assertFalse(ok3)
        self.assertIn("locked", msg3.lower())

        p1_tasks = self.coord.tasks.get_open_tasks(priority=TaskPriority.P1_HIGH)
        self.assertTrue(any("PIN Brute-Force Lockout" in t.title for t in p1_tasks))

    # -------------------------------------------------------------
    # 5. Psychiatric Crisis Intercept & Overdue Escalation
    # -------------------------------------------------------------
    def test_crisis_intercept_and_overdue_escalation(self):
        patient = self.coord.register_or_get_patient("Crisis Test", "+919999900001")
        task = self.coord.check_psychiatric_crisis(patient.patient_id, "I cannot go on anymore and want to end my life")

        self.assertIsNotNone(task)
        self.assertEqual(task.priority, TaskPriority.P0_URGENT)
        self.assertEqual(task.assigned_to, "OnCall_Psychiatrist")
        self.assertIn(patient.phone_number, self.coord.ai_muted_phones)

        # Overdue escalation check: advance 6 minutes past 5m SLA
        future_time = datetime.now() + timedelta(minutes=6)
        escalated = self.coord.escalate_overdue_tasks(reference_time=future_time)
        self.assertTrue(any(t.task_id == task.task_id for t in escalated))
        self.assertEqual(task.status, TaskStatus.ESCALATED)

        # Unmute only via resolve_crisis
        self.coord.resolve_crisis(task.task_id, staff_id="Dr. Maya Nambiar", notes="Counseling completed.")
        self.assertNotIn(patient.phone_number, self.coord.ai_muted_phones)

    # -------------------------------------------------------------
    # 6. Telephony Inbound & Outbound Tasks
    # -------------------------------------------------------------
    def test_inbound_and_outbound_calls(self):
        caller_phone = "+919845099999"

        # Inbound missed call during day
        res_day = self.coord.handle_inbound_call(
            caller_phone=caller_phone,
            call_status="MISSED",
            call_time=datetime(2026, 10, 28, 14, 0),
        )
        task_id = res_day["task_id"]
        task = self.coord.tasks.tasks[task_id]
        self.assertEqual(task.priority, TaskPriority.P1_HIGH)
        self.assertEqual(task.assigned_to, "FrontDesk_Lead")

        # Outbound call resolves callback task
        out_res = self.coord.initiate_outbound_call(task.patient_id, staff_id="Staff_Coordinator")
        self.assertIn(task_id, out_res["resolved_task_ids"])
        self.assertEqual(task.status, TaskStatus.RESOLVED)


if __name__ == "__main__":
    unittest.main()
