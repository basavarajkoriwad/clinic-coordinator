"""
Acceptance Tests: Business Requirements Written as Scenarios.
Verifies the end-to-end user and staff requirements for the clinic.
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
)
from src.coordinator import patient_greeting
from tests.helpers import create_fresh_coordinator, seed_test_clinicians_and_slots


class TestAcceptanceScenarios(unittest.TestCase):
    def setUp(self):
        self.coord = create_fresh_coordinator(slot_ttl_minutes=15)
        seed_test_clinicians_and_slots(self.coord)

    def test_acceptance_scenario_1_happy_path_booking(self):
        """
        Business Requirement:
        Patient must type their own full name, receive doctor options with fee and slots,
        pick a slot to start a 15-minute hold, receive a payment link without exposed date/time,
        complete payment, and receive confirmation addressing them by first name.
        """
        # Step 1: Patient types name
        typed_name = "Zoya Menon"
        phone = "+919876543210"
        self.assertTrue(self.coord.validate_patient_name(typed_name))
        patient = self.coord.register_or_get_patient(typed_name, phone)
        self.assertEqual(patient.discrete_name, "Zoya")

        # Step 2: Available doctors with transparent fees
        avail = self.coord.get_availability()
        self.assertTrue(len(avail) >= 3)
        chosen = avail[0]
        slot = chosen["slots"][0]

        # Step 3: Slot hold & payment link
        booking = self.coord.initiate_booking(patient.patient_id, chosen["clinician_id"], slot["slot_id"], chosen["service_label"])
        self.assertEqual(booking.state, BookingState.PAYMENT_PENDING)

        payment_msgs = self.coord.whatsapp.get_messages_for_phone(phone)
        self.assertIn("15 minutes", payment_msgs[-1]["content"])
        self.assertIn(booking.payment.payment_link_url, payment_msgs[-1]["content"])

        # Step 4: Webhook receipt & confirmation
        payload = json.dumps(self.coord.gateway.generate_webhook_payload(booking.payment.order_id))
        sig = self.coord.gateway.compute_signature(payload)
        res = self.coord.handle_payment_webhook(payload, sig)

        self.assertEqual(res["status"], "success")
        self.assertEqual(booking.state, BookingState.CONFIRMED)

        conf_msgs = self.coord.whatsapp.get_messages_for_phone(phone)
        self.assertIn("Zoya", conf_msgs[-1]["content"])
        self.assertIn("Confirmed", conf_msgs[-1]["content"])

    def test_acceptance_scenario_2_late_payment_slot_lost_protection(self):
        """
        Business Requirement:
        If a patient pays after their 15-minute hold expires and the slot was taken
        by another patient, double-booking is strictly prevented. Payment is captured,
        a P0 task with 15-minute SLA is routed to the front desk, and staff can either
        reschedule or issue an instant 1-click refund.
        """
        doc = self.coord.clinicians["DOC-101"]
        slot = self.coord.setmore.slots["SLOT-101"]

        p1 = self.coord.register_or_get_patient("Aarav Iyer", "+919876543211")
        b1 = self.coord.initiate_booking(p1.patient_id, doc.clinician_id, slot.slot_id, doc.specialty)

        # 15 minutes expire
        b1.hold_expires_at = datetime.now() - timedelta(minutes=1)
        self.coord.setmore.release_hold(slot.slot_id)

        # Walk-in or another patient books slot
        p2 = self.coord.register_or_get_patient("Zoya Menon", "+919876543212")
        b2 = self.coord.initiate_booking(p2.patient_id, doc.clinician_id, slot.slot_id, doc.specialty)
        slot.is_booked = True
        slot.held_by_booking_id = b2.booking_id

        # Patient 1 pays late
        payload = json.dumps(self.coord.gateway.generate_webhook_payload(b1.payment.order_id))
        sig = self.coord.gateway.compute_signature(payload)
        res = self.coord.handle_payment_webhook(payload, sig)

        self.assertEqual(res["status"], "exception")
        self.assertEqual(b1.state, BookingState.PAYMENT_RECEIVED_SLOT_LOST)

        # Verify P0 Task
        p0_tasks = self.coord.tasks.get_open_tasks(priority=TaskPriority.P0_URGENT)
        self.assertTrue(any("Slot Lost" in t.title for t in p0_tasks))

        # Resolution option A: Reschedule
        new_slot = self.coord.setmore.slots["SLOT-A2"]
        resched_res = self.coord.resolve_slot_lost(b1.booking_id, action="reschedule", staff_id="FrontDesk_Lead", new_slot_id=new_slot.slot_id)
        self.assertEqual(resched_res["status"], "rescheduled")
        self.assertEqual(b1.state, BookingState.CONFIRMED)

    def test_acceptance_scenario_3_setmore_500_resilience(self):
        """
        Business Requirement:
        If Setmore calendar crashes with HTTP 500 post-payment, financial capture is preserved,
        the hold is extended to 60 minutes for grace recovery, a P0 task is raised for the Clinic Manager,
        and staff can execute a 1-click retry sync.
        """
        doc = self.coord.clinicians["DOC-102"]
        slot = self.coord.setmore.slots["SLOT-R1"]

        patient = self.coord.register_or_get_patient("Aarav Iyer", "+919876543213")
        booking = self.coord.initiate_booking(patient.patient_id, doc.clinician_id, slot.slot_id, doc.specialty)

        # Setmore fails
        self.coord.setmore.simulate_api_failure = True
        payload = json.dumps(self.coord.gateway.generate_webhook_payload(booking.payment.order_id))
        sig = self.coord.gateway.compute_signature(payload)
        res = self.coord.handle_payment_webhook(payload, sig)

        self.assertEqual(res["status"], "exception")
        self.assertEqual(booking.state, BookingState.PAYMENT_CAPTURED_BOOKING_FAILED)

        # Hold extended to 60m
        self.assertTrue(slot.held_until > datetime.now() + timedelta(minutes=45))

        # Recover and retry
        self.coord.setmore.simulate_api_failure = False
        retry_res = self.coord.retry_failed_booking(booking.booking_id, staff_id="Clinic_Manager")
        self.assertEqual(retry_res["status"], "resolved")
        self.assertEqual(booking.state, BookingState.CONFIRMED)

    def test_acceptance_scenario_4_shared_phone_pin_privacy(self):
        """
        Business Requirement:
        For partners sharing one smartphone, medical identities must be isolated.
        Accessing a profile requires a 4-digit PBKDF2 PIN. 3 wrong attempts must lock the profile
        for 15 minutes and alert staff.
        """
        phone = "+919876500000"
        p_pooja = self.coord.register_or_get_patient("Pooja Kulkarni", phone, discrete_name="Pooja")
        p_sameer = self.coord.register_or_get_patient("Sameer Kulkarni", phone, discrete_name="Sameer")
        self.coord.set_patient_pin(p_pooja.patient_id, "4321")

        # Disambiguation
        status, profiles = self.coord.resolve_patient_by_phone(phone)
        self.assertEqual(status, "MULTIPLE_PROFILES")

        # 3 wrong attempts
        self.coord.verify_patient_pin(p_pooja.patient_id, "0000")
        self.coord.verify_patient_pin(p_pooja.patient_id, "0000")
        ok, msg = self.coord.verify_patient_pin(p_pooja.patient_id, "0000")
        self.assertFalse(ok)
        self.assertIn("locked", msg.lower())

        p1_tasks = self.coord.tasks.get_open_tasks(priority=TaskPriority.P1_HIGH)
        self.assertTrue(any("Lockout" in t.title for t in p1_tasks))

    def test_acceptance_scenario_5_psychiatric_crisis_life_safety(self):
        """
        Business Requirement:
        Any acute crisis / suicidal distress message must immediately mute the automated bot,
        dispatch national 24/7 helplines (Tele-MANAS 14416), and raise a P0 task with 5-minute SLA.
        """
        patient = self.coord.register_or_get_patient("Distressed Patient", "+919999912345")
        task = self.coord.check_psychiatric_crisis(patient.patient_id, "I want to die, I can't go on anymore")

        self.assertIsNotNone(task)
        self.assertEqual(task.priority, TaskPriority.P0_URGENT)
        self.assertEqual(task.assigned_to, "OnCall_Psychiatrist")
        self.assertIn(patient.phone_number, self.coord.ai_muted_phones)

        # Helpline dispatched
        msgs = self.coord.whatsapp.get_messages_for_phone(patient.phone_number)
        self.assertTrue(any("14416" in m["content"] for m in msgs))

    def test_acceptance_scenario_6_name_persistence_throughout_session(self):
        """
        Business Requirement:
        Patient types their name once. It is stored on the backend and frontend
        and used in all subsequent messages, tasks, and receipts without asking again.
        """
        phone = "+919876543288"
        patient = self.coord.register_or_get_patient("Zoya Menon", phone)

        # Greeted by first name
        greeting = patient_greeting(patient)
        self.assertEqual(greeting, "Zoya")

        # Re-accessing with same phone returns same profile
        _, profiles = self.coord.resolve_patient_by_phone(phone)
        self.assertEqual(profiles[0].patient_id, patient.patient_id)
        self.assertEqual(profiles[0].discrete_name, "Zoya")


if __name__ == "__main__":
    unittest.main()
