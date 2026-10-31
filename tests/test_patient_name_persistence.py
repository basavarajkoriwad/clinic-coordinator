"""
Comprehensive Unit & Integration Tests for Typed Patient Name Persistence,
Storage, Message Formatting, and Dashboard Privacy.

Verifies:
1. Patient 'Zoya Menon' full booking: payment, expiry, confirmation, reminders,
   and staff tasks contain 'Zoya' and contain none of the banned names.
2. Patient 'Aarav Iyer' on Late Payment and Setmore Outage paths.
3. Name typed once is not asked again in the same session; Reset clears it.
4. Same phone, same name reuses profile; same phone, different name creates new profile.
5. Scenarios 2, 3, 6 start by asking for a name when none is stored.
6. Name containing <script> or HTML is rejected; valid names allowed.
7. Staff dashboard snapshot shows only the first name and last 4 phone digits.
"""

from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
import unittest

# Ensure project root is in sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from src.models import (
    BookingRecord,
    BookingState,
    Clinician,
    PatientProfile,
    TaskPriority,
    TimeSlot,
    format_doctor_name,
)
from src.mock_services import (
    MockPaymentGateway,
    MockSetmoreService,
    MockWhatsAppService,
    TaskManager,
)
from src.coordinator import (
    ClinicBookingCoordinator,
    patient_greeting,
    _format_patient_task_identity,
)
from src.simulator import ScenarioSimulator, seed_demo_data

BANNED_NAMES = ["Rohan", "Arjun", "Meera", "Meghali", "Kavita", "Priya", "Dr. Sharma"]


class TestPatientNamePersistence(unittest.TestCase):
    def setUp(self):
        self.setmore = MockSetmoreService()
        self.gateway = MockPaymentGateway(webhook_secret="test_secret_321")
        self.whatsapp = MockWhatsAppService()
        self.tasks = TaskManager()
        self.coord = ClinicBookingCoordinator(
            setmore_service=self.setmore,
            payment_gateway=self.gateway,
            whatsapp_service=self.whatsapp,
            task_manager=self.tasks,
            slot_ttl_minutes=15,
        )
        self.simulator = ScenarioSimulator(self.coord)
        seed_demo_data(self.coord)

    # -------------------------------------------------------------
    # 1. Zoya Menon full booking flow
    # -------------------------------------------------------------
    def test_zoya_menon_full_booking_contains_zoya_and_no_banned_names(self):
        # Register Zoya Menon
        phone = "+919876543210"
        zoya = self.coord.register_or_get_patient("Zoya Menon", phone)
        self.assertEqual(patient_greeting(zoya), "Zoya")

        # Pick Dr. Rajesh Rao (DOC-102) to verify doctor name formatting
        clinician = self.coord.clinicians["DOC-102"]
        slot = self.coord.setmore.slots["SLOT-R1"]

        # Initiate booking -> payment link message
        booking = self.coord.initiate_booking(
            patient_id=zoya.patient_id,
            clinician_id=clinician.clinician_id,
            slot_id=slot.slot_id,
            service_name=clinician.specialty,
        )

        wa_msgs = self.whatsapp.get_messages_for_phone(phone)
        payment_msg = wa_msgs[-1]["content"]
        self.assertIn("Zoya", payment_msg)
        for banned in BANNED_NAMES:
            self.assertNotIn(banned, payment_msg, f"Found banned name '{banned}' in payment message")

        # Simulate 15m expiry
        self.coord.expire_stale_holds(reference_time=datetime.now() + timedelta(minutes=16))
        wa_msgs_after_exp = self.whatsapp.get_messages_for_phone(phone)
        expiry_msg = wa_msgs_after_exp[-1]["content"]
        self.assertIn("Zoya", expiry_msg)
        for banned in BANNED_NAMES:
            self.assertNotIn(banned, expiry_msg, f"Found banned name '{banned}' in expiry message")

        # Now simulate payment webhook confirmation (re-holding slot)
        self.setmore.hold_slot(slot.slot_id, booking.booking_id, ttl_minutes=15)
        raw_payload = json.dumps(self.gateway.generate_webhook_payload(booking.payment.order_id))
        sig = self.gateway.compute_signature(raw_payload)
        self.coord.handle_payment_webhook(raw_payload, sig)

        wa_msgs_after_pay = self.whatsapp.get_messages_for_phone(phone)
        conf_msg = wa_msgs_after_pay[-1]["content"]
        self.assertIn("Zoya", conf_msg)
        for banned in BANNED_NAMES:
            self.assertNotIn(banned, conf_msg, f"Found banned name '{banned}' in confirmation message")

        # Reminder message check
        reminder_msg = self.coord.generate_reminder_message(booking.booking_id, "24_HOURS_BEFORE")
        self.assertIn("Zoya", reminder_msg)
        for banned in BANNED_NAMES:
            self.assertNotIn(banned, reminder_msg, f"Found banned name '{banned}' in reminder message")

        # Staff task check: create a task for Zoya
        task = self.tasks.create_task(
            patient_id=zoya.patient_id,
            title=f"Review Case: {_format_patient_task_identity(zoya)}",
            description=f"Clinical follow-up for {_format_patient_task_identity(zoya)}",
            priority=TaskPriority.P1_HIGH,
            sla_minutes=60,
        )
        self.assertIn("Zoya", task.title)
        self.assertIn("Zoya", task.description)
        for banned in BANNED_NAMES:
            self.assertNotIn(banned, task.title)
            self.assertNotIn(banned, task.description)

    # -------------------------------------------------------------
    # 2. Aarav Iyer on Late Payment and Setmore Outage paths
    # -------------------------------------------------------------
    def test_aarav_iyer_late_payment_and_setmore_outage(self):
        phone = "+919876543210"

        # Late Payment path
        self.simulator.reset()
        aarav = self.coord.register_or_get_patient("Aarav Iyer", phone)
        res_late = self.simulator.execute_late_payment_with_patient(aarav)

        late_chat_text = " ".join(m["text"] for m in res_late["chat_messages"])
        self.assertIn("Aarav", late_chat_text)
        for banned in BANNED_NAMES:
            self.assertNotIn(banned, late_chat_text)

        late_task = self.coord.tasks.tasks[res_late["task_id"]]
        self.assertIn("Aarav", late_task.title)
        self.assertIn("Aarav", late_task.description)
        for banned in BANNED_NAMES:
            self.assertNotIn(banned, late_task.title)
            self.assertNotIn(banned, late_task.description)

        # Setmore Outage path
        self.simulator.reset()
        aarav2 = self.coord.register_or_get_patient("Aarav Iyer", phone)
        res_outage = self.simulator.execute_setmore_outage_with_patient(aarav2)

        outage_chat_text = " ".join(m["text"] for m in res_outage["chat_messages"])
        self.assertIn("Aarav", outage_chat_text)
        for banned in BANNED_NAMES:
            self.assertNotIn(banned, outage_chat_text)

        outage_task = self.coord.tasks.tasks[res_outage["task_id"]]
        self.assertIn("Aarav", outage_task.title)
        self.assertIn("Aarav", outage_task.description)
        for banned in BANNED_NAMES:
            self.assertNotIn(banned, outage_task.title)
            self.assertNotIn(banned, outage_task.description)

    # -------------------------------------------------------------
    # 3. Name typed once is not asked again; Reset clears it
    # -------------------------------------------------------------
    def test_name_typed_once_not_asked_again_reset_clears(self):
        phone = "+919876543210"
        self.simulator.reset()

        # Step 1: Before typing name, happy path asks for name
        res1 = self.simulator.start_scenario("happy", phone)
        self.assertEqual(res1.get("status"), "request_name")
        self.assertEqual(res1["chat_messages"][-1]["action"], "request_name")

        # Step 2: Patient types name
        self.coord.register_or_get_patient("Zoya Menon", phone)

        # Step 3: Trigger happy path again -> goes straight to doctor picker without asking name
        res2 = self.simulator.start_scenario("happy", phone)
        self.assertEqual(res2.get("status"), "doctor_picker")
        self.assertIn("Welcome back, Zoya", res2["chat_messages"][-1]["text"])

        # Step 4: Reset clears the session
        self.simulator.reset()
        res3 = self.simulator.start_scenario("happy", phone)
        self.assertEqual(res3.get("status"), "request_name")
        self.assertEqual(res3["chat_messages"][-1]["action"], "request_name")

    # -------------------------------------------------------------
    # 4. Same phone same name reuses profile; different name creates new
    # -------------------------------------------------------------
    def test_same_phone_same_name_reuses_different_name_switches(self):
        phone = "+919876543210"
        self.simulator.reset()

        p1 = self.coord.register_or_get_patient("Zoya Menon", phone)
        p2 = self.coord.register_or_get_patient("Zoya Menon", phone)
        self.assertEqual(p1.patient_id, p2.patient_id, "Same name on same phone must reuse profile")

        # Now different name on same phone
        p3 = self.coord.register_or_get_patient("Aarav Iyer", phone)
        self.assertNotEqual(p1.patient_id, p3.patient_id, "Different name on same phone must create new profile")
        self.assertEqual(patient_greeting(p3), "Aarav")

        # Next booking uses new name
        clinician = self.coord.clinicians["DOC-102"]
        slot = self.coord.setmore.slots["SLOT-R1"]
        self.coord.initiate_booking(
            patient_id=p3.patient_id,
            clinician_id=clinician.clinician_id,
            slot_id=slot.slot_id,
            service_name=clinician.specialty,
        )
        latest_msg = self.whatsapp.get_messages_for_phone(phone)[-1]["content"]
        self.assertIn("Aarav", latest_msg)
        self.assertNotIn("Zoya", latest_msg)

    # -------------------------------------------------------------
    # 5. Scenarios 2/3/6 ask for name first when none stored
    # -------------------------------------------------------------
    def test_scenarios_2_3_6_ask_for_name_first(self):
        phone = "+919876543210"

        for sc in ["late_payment", "setmore_outage", "lab_report"]:
            self.simulator.reset()
            res = self.simulator.start_scenario(sc, phone)
            self.assertEqual(res.get("status"), "request_name", f"{sc} must request name when none stored")
            self.assertEqual(res["chat_messages"][-1]["action"], "request_name")
            self.assertEqual(self.coord.get_conversation_state(phone), "AWAITING_NAME")

    # -------------------------------------------------------------
    # 6. Name validation rejects HTML/<script> and accepts valid names
    # -------------------------------------------------------------
    def test_name_validation_rejects_html_and_scripts(self):
        self.assertFalse(self.coord.validate_patient_name("<script>alert(1)</script>"))
        self.assertFalse(self.coord.validate_patient_name("<img src=x onerror=alert(1)>"))
        self.assertFalse(self.coord.validate_patient_name("John <style>"))
        self.assertFalse(self.coord.validate_patient_name("12345"))
        self.assertFalse(self.coord.validate_patient_name("a"))  # < 2 chars
        self.assertFalse(self.coord.validate_patient_name("a" * 61))  # > 60 chars

        # Valid names
        self.assertTrue(self.coord.validate_patient_name("Zoya Menon"))
        self.assertTrue(self.coord.validate_patient_name("Aarav Iyer"))
        self.assertTrue(self.coord.validate_patient_name("Mary-Jane O'Connor"))
        self.assertTrue(self.coord.validate_patient_name("Dr. A. P. J."))

    # -------------------------------------------------------------
    # 7. Staff dashboard snapshot shows only first name and last 4 digits
    # -------------------------------------------------------------
    def test_staff_dashboard_privacy_formatting(self):
        phone = "+919876543210"
        patient = self.coord.register_or_get_patient("Zoya Menon", phone)
        task_identity = _format_patient_task_identity(patient)

        self.assertEqual(task_identity, "Zoya (****3210)")
        self.assertNotIn("Menon", task_identity)
        self.assertNotIn("9876543210", task_identity)


if __name__ == "__main__":
    unittest.main(verbosity=2)
