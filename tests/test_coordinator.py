"""
Comprehensive Unit & Integration Tests for ClinicBookingCoordinator.
Verifies happy path, failure exceptions, cryptographic webhook security,
shared phone number disambiguation, and reminder scheduling.
"""

from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
import unittest

# Ensure project root is in sys.path so this file can be run directly
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from src.models import (
    BookingState,
    Clinician,
    PatientProfile,
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
from src.coordinator import ClinicBookingCoordinator


class TestClinicBookingCoordinator(unittest.TestCase):
    def setUp(self):
        self.setmore = MockSetmoreService()
        self.gateway = MockPaymentGateway(webhook_secret="super_secret_test_key")
        self.whatsapp = MockWhatsAppService()
        self.tasks = TaskManager()
        self.coordinator = ClinicBookingCoordinator(
            setmore_service=self.setmore,
            payment_gateway=self.gateway,
            whatsapp_service=self.whatsapp,
            task_manager=self.tasks,
            slot_ttl_minutes=15,
        )

        # Register Clinician (Dr. Ananya Sharma - Clinical Psychologist & Sexologist)
        self.clinician = Clinician(
            clinician_id="DOC-101",
            name="Dr. Ananya Sharma",
            specialty="Sexual & Relationship Health",
            setmore_staff_key="staff_key_doc101",
            consultation_fee=2500.0,
            duration_minutes=50,
        )
        self.coordinator.clinicians[self.clinician.clinician_id] = self.clinician

        # Setup standard slot (tomorrow at 11:00 AM)
        self.tomorrow = datetime.now() + timedelta(days=1)
        self.slot_time_start = datetime(self.tomorrow.year, self.tomorrow.month, self.tomorrow.day, 11, 0)
        self.slot_time_end = self.slot_time_start + timedelta(minutes=50)
        self.slot = TimeSlot(
            slot_id="SLOT-101",
            clinician_id=self.clinician.clinician_id,
            start_time=self.slot_time_start,
            end_time=self.slot_time_end,
        )
        self.setmore.add_slot(self.slot)

    # -----------------------------------------------------------------
    # Test 1: Happy Path - End-to-End Booking and Webhook Confirmation
    # -----------------------------------------------------------------
    def test_happy_path_booking(self):
        # 1. Register Patient
        patient = self.coordinator.register_or_get_patient(
            full_name="Meghali sacchdeva",
            phone_number="+919888811111",
            discrete_name="MEGHALI",
        )
        self.assertEqual(patient.full_name, "Meghali sacchdeva")

        # 2. Initiate Booking (Slot Held + Payment Link Generated)
        booking = self.coordinator.initiate_booking(
            patient_id=patient.patient_id,
            clinician_id=self.clinician.clinician_id,
            slot_id=self.slot.slot_id,
            service_name="Relationship Consultation",
            mode="IN_PERSON",
        )
        self.assertEqual(booking.state, BookingState.PAYMENT_PENDING)
        self.assertTrue(self.slot.is_held)
        self.assertIsNotNone(booking.payment.payment_link_url)

        # Check discreet WhatsApp message (no slot day/time exposed to patient)
        messages = self.whatsapp.get_messages_for_phone("+919888811111")
        self.assertEqual(len(messages), 1)
        self.assertIn("15 minutes", messages[0]["content"])
        self.assertNotIn("Friday", messages[0]["content"])
        self.assertNotIn("11:00", messages[0]["content"])
        self.assertNotIn("Sexual", messages[0]["content"])  # Privacy guardrail!

        # 3. Simulate Payment Gateway Webhook
        order_id = booking.payment.order_id
        webhook_dict = self.gateway.generate_webhook_payload(order_id=order_id)
        raw_body = json.dumps(webhook_dict)
        signature = self.gateway.compute_signature(raw_body)

        result = self.coordinator.handle_payment_webhook(raw_body, signature)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["state"], BookingState.CONFIRMED)

        # Verify Setmore status
        self.assertTrue(self.slot.is_booked)
        self.assertFalse(self.slot.is_held)
        self.assertIsNotNone(booking.setmore_appointment_id)

        # Check confirmation message sent
        messages_after = self.whatsapp.get_messages_for_phone("+919888811111")
        self.assertEqual(len(messages_after), 2)
        self.assertIn("Appointment Confirmed", messages_after[1]["content"])
        self.assertIn("receipt", messages_after[1]["content"])

    # -----------------------------------------------------------------
    # Test 2: Failure Case 1 - Payment Received but Slot Lost (Late Payment)
    # -----------------------------------------------------------------
    def test_failure_late_payment_slot_lost(self):
        patient1 = self.coordinator.register_or_get_patient(
            full_name="Meghali sacchdeva",
            phone_number="+919888822222",
        )
        booking1 = self.coordinator.initiate_booking(
            patient_id=patient1.patient_id,
            clinician_id=self.clinician.clinician_id,
            slot_id=self.slot.slot_id,
            service_name="Therapy",
        )

        # Simulate hold expiration (time jumped 20 minutes ahead)
        booking1.hold_expires_at = datetime.now() - timedelta(minutes=5)

        # In the meantime, another patient (walk-in or online) books that same slot
        self.slot.is_booked = True
        self.slot.held_by_booking_id = "ANOTHER_PATIENT_BKG_999"

        # Now, Meghali finally completes her payment via UPI
        order_id = booking1.payment.order_id
        webhook_dict = self.gateway.generate_webhook_payload(order_id=order_id)
        raw_body = json.dumps(webhook_dict)
        signature = self.gateway.compute_signature(raw_body)

        result = self.coordinator.handle_payment_webhook(raw_body, signature)

        # Assertions
        self.assertEqual(result["status"], "exception")
        self.assertEqual(booking1.state, BookingState.PAYMENT_RECEIVED_SLOT_LOST)

        # Verify that an urgent P0 Staff Task was created
        open_p0_tasks = self.tasks.get_open_tasks(priority=TaskPriority.P0_URGENT)
        self.assertTrue(any("Payment Received but Slot Lost" in t.title for t in open_p0_tasks))

        # Verify patient received reassuring message about personal coordinator call
        messages = self.whatsapp.get_messages_for_phone("+919888822222")
        self.assertIn("our clinic manager is personally finalizing your slot", messages[-1]["content"])

    # -----------------------------------------------------------------
    # Test 3: Failure Case 2 - Payment Succeeded but Setmore Booking Failed
    # -----------------------------------------------------------------
    def test_failure_setmore_api_outage(self):
        patient = self.coordinator.register_or_get_patient(
            full_name="Meera Joshi",
            phone_number="+919888833333",
        )
        booking = self.coordinator.initiate_booking(
            patient_id=patient.patient_id,
            clinician_id=self.clinician.clinician_id,
            slot_id=self.slot.slot_id,
            service_name="Psychiatric Consultation",
        )

        # Inject simulated Setmore 500 API Outage / Network Timeout
        self.setmore.simulate_api_failure = True

        order_id = booking.payment.order_id
        webhook_dict = self.gateway.generate_webhook_payload(order_id=order_id)
        raw_body = json.dumps(webhook_dict)
        signature = self.gateway.compute_signature(raw_body)

        result = self.coordinator.handle_payment_webhook(raw_body, signature)

        # Assertions
        self.assertEqual(result["status"], "exception")
        self.assertEqual(booking.state, BookingState.PAYMENT_CAPTURED_BOOKING_FAILED)

        # Verify P0 Critical Task created for Clinic Manager with 10-minute SLA
        open_p0_tasks = self.tasks.get_open_tasks(priority=TaskPriority.P0_URGENT)
        target_task = next(t for t in open_p0_tasks if "Payment Succeeded but Setmore Booking Failed" in t.title)
        self.assertEqual(target_task.priority, TaskPriority.P0_URGENT)
        self.assertEqual(target_task.assigned_to, "Clinic_Manager")
        self.assertIn("Setmore API Error 500", target_task.description)

    # -----------------------------------------------------------------
    # Test 4: Idempotency - Duplicate Webhook Replay
    # -----------------------------------------------------------------
    def test_duplicate_webhook_idempotency(self):
        patient = self.coordinator.register_or_get_patient(
            full_name="Dev Patel",
            phone_number="+919888844444",
        )
        booking = self.coordinator.initiate_booking(
            patient_id=patient.patient_id,
            clinician_id=self.clinician.clinician_id,
            slot_id=self.slot.slot_id,
            service_name="Relationship Guidance",
        )
        order_id = booking.payment.order_id
        webhook_dict = self.gateway.generate_webhook_payload(order_id=order_id, payment_id="pay_unique_123")
        raw_body = json.dumps(webhook_dict)
        signature = self.gateway.compute_signature(raw_body)

        # First webhook arrival
        res1 = self.coordinator.handle_payment_webhook(raw_body, signature)
        self.assertEqual(res1["status"], "success")

        # Second identical webhook arrival (replayed by network or gateway retry)
        res2 = self.coordinator.handle_payment_webhook(raw_body, signature)
        self.assertEqual(res2["status"], "ok")
        self.assertIn("Duplicate webhook ignored", res2["message"])

        # Verify no duplicate appointment records were created
        self.assertEqual(len(self.setmore.appointments), 1)

    # -----------------------------------------------------------------
    # Test 5: Shared Phone Number Disambiguation
    # -----------------------------------------------------------------
    def test_shared_phone_number_disambiguation(self):
        shared_phone = "+919876500000"

        # Register Partner A (Pooja)
        patient_a = self.coordinator.register_or_get_patient(
            full_name="Pooja Kulkarni",
            phone_number=shared_phone,
            discrete_name="Pooja",
        )

        # Register Partner B (Sameer) on the exact SAME phone number
        patient_b = self.coordinator.register_or_get_patient(
            full_name="Sameer Kulkarni",
            phone_number=shared_phone,
            discrete_name="Sameer",
        )

        # Assert they received distinct UUIDs and records
        self.assertNotEqual(patient_a.patient_id, patient_b.patient_id)
        self.assertEqual(patient_a.phone_number, patient_b.phone_number)

        # Test phone resolution
        status, profiles = self.coordinator.resolve_patient_by_phone(shared_phone)
        self.assertEqual(status, "MULTIPLE_PROFILES")
        self.assertEqual(len(profiles), 2)
        names = [p.full_name for p in profiles]
        self.assertIn("Pooja Kulkarni", names)
        self.assertIn("Sameer Kulkarni", names)

    # -----------------------------------------------------------------
    # Test 6: Security - Invalid Webhook Signature Rejected
    # -----------------------------------------------------------------
    def test_invalid_webhook_signature_rejected(self):
        patient = self.coordinator.register_or_get_patient(
            full_name="Fake User",
            phone_number="+919888899999",
        )
        booking = self.coordinator.initiate_booking(
            patient_id=patient.patient_id,
            clinician_id=self.clinician.clinician_id,
            slot_id=self.slot.slot_id,
            service_name="Consultation",
        )
        order_id = booking.payment.order_id
        webhook_dict = self.gateway.generate_webhook_payload(order_id=order_id)
        raw_body = json.dumps(webhook_dict)

        # Tampered / invalid signature
        tampered_signature = "bad_forged_signature_0000000000000000"

        result = self.coordinator.handle_payment_webhook(raw_body, tampered_signature)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["message"], "Invalid webhook signature")
        self.assertEqual(booking.state, BookingState.PAYMENT_PENDING)  # Not confirmed!

        # Check that security task was created
        open_security_tasks = self.tasks.get_open_tasks(priority=TaskPriority.P0_URGENT)
        self.assertTrue(any("Invalid Webhook Signature" in t.title for t in open_security_tasks))

    # -----------------------------------------------------------------
    # Test 7: Reminder Scheduling Logic (Short-Notice vs Advance Bookings)
    # -----------------------------------------------------------------
    def test_reminder_schedule_filtering(self):
        # Scenario A: Appointment in 5 days (All 3 reminders active: 72h, 24h, morning)
        booking_now = datetime(2026, 10, 20, 10, 0)
        appt_in_5_days = datetime(2026, 10, 25, 14, 0)
        reminders_5d = self.coordinator.calculate_active_reminders(appt_in_5_days, booking_now)
        self.assertEqual(len(reminders_5d), 3)

        # Scenario B: Short-notice booking made today for tomorrow at 2:00 PM
        booking_short_notice = datetime(2026, 10, 24, 15, 0)
        appt_tomorrow = datetime(2026, 10, 25, 14, 0)
        reminders_short = self.coordinator.calculate_active_reminders(appt_tomorrow, booking_short_notice)
        labels = [r["label"] for r in reminders_short]
        self.assertNotIn("72_HOURS_BEFORE", labels)  # 72 hours before was Oct 22, already passed!
        self.assertIn("MORNING_OF_APPOINTMENT", labels)

    # -----------------------------------------------------------------
    # Test 8: Real Payment Link & 15-Minute Deadline Message Dispatched
    # -----------------------------------------------------------------
    def test_payment_link_sent_with_15min_hold_and_deadline(self):
        patient = self.coordinator.register_or_get_patient(
            full_name="Vikram Malhotra",
            phone_number="+919876543299",
            discrete_name="Vikram",
        )
        booking = self.coordinator.initiate_booking(
            patient_id=patient.patient_id,
            clinician_id=self.clinician.clinician_id,
            slot_id=self.slot.slot_id,
            service_name="Mental Health Consultation",
        )
        self.assertEqual(booking.state, BookingState.PAYMENT_PENDING)
        self.assertIsNotNone(booking.payment.payment_link_url)
        self.assertTrue(booking.payment.payment_link_url.startswith("https://pay.bengaluru-clinic.in/pay/"))

        # Verify WhatsApp message contains required text elements without slot day/time
        messages = self.whatsapp.get_messages_for_phone(patient.phone_number)
        self.assertTrue(len(messages) >= 1)
        latest_msg = messages[-1]["content"]

        self.assertIn(booking.payment.payment_link_url, latest_msg)
        self.assertIn("15 minutes", latest_msg)
        self.assertIn("expire automatically", latest_msg)
        self.assertIn("confirmation will be sent", latest_msg)
        self.assertNotIn("Friday", latest_msg)
        self.assertNotIn("11:00", latest_msg)

    # -----------------------------------------------------------------
    # Test 9: Backend 15-Minute Expiry Mechanism (Sweep & Re-booking Offer)
    # -----------------------------------------------------------------
    def test_backend_15min_hold_expiry(self):
        patient = self.coordinator.register_or_get_patient(
            full_name="Sunita Deshmukh",
            phone_number="+919876543288",
            discrete_name="Sunita",
        )
        booking = self.coordinator.initiate_booking(
            patient_id=patient.patient_id,
            clinician_id=self.clinician.clinician_id,
            slot_id=self.slot.slot_id,
            service_name="Relationship Guidance",
        )
        self.assertTrue(self.slot.is_held)
        self.assertEqual(booking.state, BookingState.PAYMENT_PENDING)

        # Simulate 16 minutes passing (past the 15-minute hold)
        future_time = datetime.now() + timedelta(minutes=16)
        expired_bookings = self.coordinator.expire_stale_holds(reference_time=future_time)

        self.assertEqual(len(expired_bookings), 1)
        self.assertEqual(expired_bookings[0].booking_id, booking.booking_id)
        self.assertEqual(booking.state, BookingState.HOLD_EXPIRED)

        # Verify slot released back to open inventory
        self.assertFalse(self.slot.is_held)
        self.assertIsNone(self.slot.held_until)
        self.assertTrue(self.setmore.check_availability(self.slot.slot_id))

        # Verify patient received expiry notification without slot day/time and no 'Dr. Dr.' bug
        messages = self.whatsapp.get_messages_for_phone(patient.phone_number)
        expiry_msg = messages[-1]["content"]
        self.assertIn("payment window", expiry_msg)
        self.assertIn("released", expiry_msg)
        self.assertIn("book again", expiry_msg)
        self.assertNotIn("Dr. Dr.", expiry_msg)
        self.assertNotIn("Friday", expiry_msg)
        self.assertNotIn("11:00", expiry_msg)

    # -----------------------------------------------------------------
    # Test 10: Inbound Call Capture (Missed Call SLA & WhatsApp Ack)
    # -----------------------------------------------------------------
    def test_inbound_missed_call_creates_callback_task_and_whatsapp_ack(self):
        caller_phone = "+919845011223"
        
        # Inbound call during working hours (e.g. 11:30 AM)
        work_time = datetime(2026, 10, 28, 11, 30)
        res = self.coordinator.handle_inbound_call(
            caller_phone=caller_phone,
            call_status="MISSED",
            call_time=work_time,
            caller_name="Anand Sharma"
        )
        self.assertEqual(res["status"], "missed_call_captured")
        self.assertEqual(res["sla_minutes"], 30)

        # Check task created in TaskManager
        open_tasks = self.tasks.get_open_tasks(priority=TaskPriority.P1_HIGH)
        target_task = next(t for t in open_tasks if caller_phone[-4:] in t.title)
        self.assertIsNotNone(target_task)
        self.assertEqual(target_task.assigned_to, "FrontDesk_Lead")

        # Check WhatsApp acknowledgment sent to caller
        messages = self.whatsapp.get_messages_for_phone(caller_phone)
        self.assertEqual(len(messages), 1)
        self.assertIn("missed your call", messages[0]["content"])
        self.assertIn("within 30 minutes", messages[0]["content"])

    # -----------------------------------------------------------------
    # Test 11: Outbound Call Dispatch & Task Auto-Resolution
    # -----------------------------------------------------------------
    def test_outbound_call_resolves_callback_task(self):
        caller_phone = "+919845044556"
        call_res = self.coordinator.handle_inbound_call(
            caller_phone=caller_phone,
            call_status="MISSED",
            call_time=datetime.now(),
        )
        task_id = call_res["task_id"]
        patient_id = call_res["call_record"]["patient_id"]

        # Staff receptionist initiates outbound call to patient
        out_res = self.coordinator.initiate_outbound_call(
            patient_id=patient_id,
            staff_id="Priya_FrontDesk",
            reason="Missed call callback",
        )
        self.assertEqual(out_res["status"], "outbound_call_initiated")
        self.assertIn(task_id, out_res["resolved_task_ids"])

        # Verify task is marked resolved
        task = self.tasks.tasks[task_id]
        self.assertEqual(task.status, TaskStatus.RESOLVED)
        self.assertIn("Resolved by Priya_FrontDesk", task.resolution_notes)

    # -----------------------------------------------------------------
    # Test 12: PBKDF2 PIN Authentication & 3-Attempt Lockout
    # -----------------------------------------------------------------
    def test_pin_setting_and_lockout(self):
        patient = self.coordinator.register_or_get_patient("Pooja Kulkarni", "+919876500000")
        self.coordinator.set_patient_pin(patient.patient_id, "4321")

        # Correct PIN
        ok, msg = self.coordinator.verify_patient_pin(patient.patient_id, "4321")
        self.assertTrue(ok)
        self.assertIn("verified", msg.lower())

        # Attempt 1 wrong
        ok1, msg1 = self.coordinator.verify_patient_pin(patient.patient_id, "0000")
        self.assertFalse(ok1)
        self.assertIn("2 attempt(s) remaining", msg1)

        # Attempt 2 wrong
        ok2, msg2 = self.coordinator.verify_patient_pin(patient.patient_id, "0000")
        self.assertFalse(ok2)
        self.assertIn("1 attempt(s) remaining", msg2)

        # Attempt 3 wrong -> Lockout
        ok3, msg3 = self.coordinator.verify_patient_pin(patient.patient_id, "0000")
        self.assertFalse(ok3)
        self.assertIn("locked", msg3.lower())
        self.assertIsNotNone(patient.locked_until)

        # Open P1 task generated
        p1_tasks = self.tasks.get_open_tasks(priority=TaskPriority.P1_HIGH)
        lockout_task = next(t for t in p1_tasks if "Lockout" in t.title)
        self.assertIsNotNone(lockout_task)

    # -----------------------------------------------------------------
    # Test 13: Crisis Intercept & False Positive Immunity
    # -----------------------------------------------------------------
    def test_psychiatric_crisis_detection_and_no_false_positive(self):
        patient = self.coordinator.register_or_get_patient("Crisis Test", "+919999988888")
        
        # False positives: words like "diet", "studied", "audience" MUST NOT trigger crisis
        self.assertIsNone(self.coordinator.check_psychiatric_crisis(patient.patient_id, "I started a new diet today."))
        self.assertIsNone(self.coordinator.check_psychiatric_crisis(patient.patient_id, "I studied medicine in college."))
        self.assertNotIn("+919999988888", self.coordinator.ai_muted_phones)

        # Genuine crisis message
        crisis_text = "I feel so hopeless, I want to end my life"
        task = self.coordinator.check_psychiatric_crisis(patient.patient_id, crisis_text)
        self.assertIsNotNone(task)
        self.assertEqual(task.priority, TaskPriority.P0_URGENT)
        self.assertEqual(task.assigned_to, "OnCall_Psychiatrist")
        self.assertIn("+919999988888", self.coordinator.ai_muted_phones)

        # Helpline message dispatched
        messages = self.whatsapp.get_messages_for_phone("+919999988888")
        self.assertTrue(any("14416" in m["content"] for m in messages))

        # Staff resolves crisis -> unmutes AI
        res = self.coordinator.resolve_crisis(task.task_id, "Dr. Maya", "Patient safe with family")
        self.assertEqual(res["status"], "resolved")
        self.assertNotIn("+919999988888", self.coordinator.ai_muted_phones)

    # -----------------------------------------------------------------
    # Test 14: Tamper-Evident SHA256 Audit Chain
    # -----------------------------------------------------------------
    def test_sha256_audit_hash_chain(self):
        import hashlib
        self.coordinator.audit_log.clear()

        e1 = self.coordinator.audit("SYSTEM", "First entry")
        e2 = self.coordinator.audit("BOOKING", "Second entry")
        e3 = self.coordinator.audit("SECURITY", "Third entry")

        self.assertEqual(e1.prev_hash, "0" * 64)
        self.assertEqual(e2.prev_hash, e1.hash)
        self.assertEqual(e3.prev_hash, e2.hash)

        # Verify cryptographic integrity of e3
        expected_str = f"{e3.prev_hash}|{e3.seq}|{e3.timestamp}|{e3.category}|{e3.message}"
        computed_hash = hashlib.sha256(expected_str.encode("utf-8")).hexdigest()
        self.assertEqual(e3.hash, computed_hash)

    # -----------------------------------------------------------------
    # Test 15: Doctor Name Normalization Guardrail
    # -----------------------------------------------------------------
    def test_format_doctor_name(self):
        from src.models import format_doctor_name
        self.assertEqual(format_doctor_name("Dr. Dr. Ananya Sharma"), "Dr. Ananya Sharma")
        self.assertEqual(format_doctor_name("Dr. Rajesh Rao"), "Dr. Rajesh Rao")
        self.assertEqual(format_doctor_name("Meera Nambiar"), "Dr. Meera Nambiar")
        self.assertEqual(format_doctor_name("dr. kavita"), "Dr. kavita")

    # -----------------------------------------------------------------
    # Test 16: Patient Name Validation (Valid and Invalid)
    # -----------------------------------------------------------------
    def test_patient_name_validation(self):
        from src.coordinator import ClinicBookingCoordinator
        # Valid names
        self.assertTrue(ClinicBookingCoordinator.validate_patient_name("Zoya Menon"))
        self.assertTrue(ClinicBookingCoordinator.validate_patient_name("Mary Jane O'Connor"))
        self.assertTrue(ClinicBookingCoordinator.validate_patient_name("Dr. J. Smith"))
        self.assertTrue(ClinicBookingCoordinator.validate_patient_name("Jean-Luc"))

        # Invalid names
        self.assertFalse(ClinicBookingCoordinator.validate_patient_name("12345"))
        self.assertFalse(ClinicBookingCoordinator.validate_patient_name("A"))  # < 2 chars
        self.assertFalse(ClinicBookingCoordinator.validate_patient_name("This name is way too long because it exceeds sixty characters in total length and should fail"))
        self.assertFalse(ClinicBookingCoordinator.validate_patient_name(""))
        self.assertFalse(ClinicBookingCoordinator.validate_patient_name(None))
        self.assertFalse(ClinicBookingCoordinator.validate_patient_name("Bad<script>"))

    # -----------------------------------------------------------------
    # Test 17: Per-Phone Conversation State Machine
    # -----------------------------------------------------------------
    def test_conversation_state_machine(self):
        phone = "+919876543210"
        self.assertEqual(self.coordinator.get_conversation_state(phone), "IDLE")

        self.coordinator.set_conversation_state(phone, "AWAITING_NAME")
        self.assertEqual(self.coordinator.get_conversation_state(phone), "AWAITING_NAME")

        self.coordinator.set_conversation_state(phone, "AWAITING_SLOT")
        self.assertEqual(self.coordinator.get_conversation_state(phone), "AWAITING_SLOT")

        self.coordinator.set_conversation_state(phone, "IDLE")
        self.assertEqual(self.coordinator.get_conversation_state(phone), "IDLE")

        self.coordinator.set_conversation_state(phone, "AWAITING_NAME")
        self.coordinator.reset_conversation_states()
        self.assertEqual(self.coordinator.get_conversation_state(phone), "IDLE")

    # -----------------------------------------------------------------
    # Test 18: Live Availability Engine Strips Internal Keys & Filters
    # -----------------------------------------------------------------
    def test_get_availability_filters_and_strips_internal_keys(self):
        # Doc 101 has 1 available slot (SLOT-101)
        avail = self.coordinator.get_availability()
        self.assertEqual(len(avail), 1)
        doc = avail[0]
        self.assertEqual(doc["clinician_id"], "DOC-101")
        self.assertIn("display_name", doc)
        self.assertIn("fee", doc)
        self.assertNotIn("setmore_staff_key", doc)

        # Slots must contain slot_id, label, start_iso, end_iso
        self.assertEqual(len(doc["slots"]), 1)
        slot_info = doc["slots"][0]
        self.assertEqual(slot_info["slot_id"], "SLOT-101")
        self.assertIn("label", slot_info)
        self.assertNotIn("setmore_staff_key", slot_info)

        # When slot is held or booked, it disappears from availability
        self.setmore.hold_slot(self.slot.slot_id, "BKG-HOLD-1", ttl_minutes=15)
        avail_after_hold = self.coordinator.get_availability()
        self.assertEqual(len(avail_after_hold[0]["slots"]), 0)

    # -----------------------------------------------------------------
    # Test 19: Slot Booking Concurrency & 409 Conflict
    # -----------------------------------------------------------------
    def test_slot_booking_conflict_409(self):
        # Patient 1 registers and holds slot
        p1 = self.coordinator.register_or_get_patient("Zoya Menon", "+919888800001")
        booking1 = self.coordinator.initiate_booking(
            patient_id=p1.patient_id,
            clinician_id=self.clinician.clinician_id,
            slot_id=self.slot.slot_id,
            service_name="Therapy Session",
        )
        self.assertEqual(booking1.state, BookingState.PAYMENT_PENDING)

        # Patient 2 attempts to book the same slot -> must fail immediately
        p2 = self.coordinator.register_or_get_patient("Farhan Akhtar", "+919888800002")
        with self.assertRaises(RuntimeError) as ctx:
            self.coordinator.initiate_booking(
                patient_id=p2.patient_id,
                clinician_id=self.clinician.clinician_id,
                slot_id=self.slot.slot_id,
                service_name="Therapy Session",
            )
        self.assertIn("already held or booked", str(ctx.exception))

    # -----------------------------------------------------------------
    # Test 20: Payment Record Fee Matches Chosen Doctor's Fee
    # -----------------------------------------------------------------
    def test_dynamic_consultation_fees(self):
        # Doc 2 with fee 2000
        doc2 = Clinician("DOC-102", "Dr. Rajesh Rao", "Clinical Psychology", "staff_102", 2000.0, 45)
        self.coordinator.clinicians[doc2.clinician_id] = doc2
        slot2 = TimeSlot("SLOT-R1", doc2.clinician_id, self.slot_time_start, self.slot_time_end)
        self.setmore.add_slot(slot2)

        # Doc 3 with fee 3000
        doc3 = Clinician("DOC-103", "Dr. Meera Nambiar", "Psychiatry", "staff_103", 3000.0, 60)
        self.coordinator.clinicians[doc3.clinician_id] = doc3
        slot3 = TimeSlot("SLOT-M1", doc3.clinician_id, self.slot_time_start, self.slot_time_end)
        self.setmore.add_slot(slot3)

        p = self.coordinator.register_or_get_patient("Zoya Menon", "+919888800001")
        b2 = self.coordinator.initiate_booking(p.patient_id, doc2.clinician_id, slot2.slot_id, "Psychology")
        self.assertEqual(b2.payment.amount_inr, 2000.0)

        b3 = self.coordinator.initiate_booking(p.patient_id, doc3.clinician_id, slot3.slot_id, "Psychiatry")
        self.assertEqual(b3.payment.amount_inr, 3000.0)

    # -----------------------------------------------------------------
    # Test 21: No Hold Placed Before Confirmation
    # -----------------------------------------------------------------
    def test_no_hold_before_confirmation(self):
        # Merely viewing availability or typing name places NO hold
        p = self.coordinator.register_or_get_patient("Zoya Menon", "+919888800001")
        avail = self.coordinator.get_availability()
        self.assertTrue(self.setmore.check_availability("SLOT-101"))
        self.assertFalse(self.slot.is_held)
        self.assertEqual(len(self.coordinator.bookings), 0)

    # -----------------------------------------------------------------
    # Test 22: Outbound WhatsApp Message uses Typed Name (Zoya Menon)
    # -----------------------------------------------------------------
    def test_outbound_whatsapp_uses_typed_patient_name(self):
        p = self.coordinator.register_or_get_patient("Zoya Menon", "+919777711111")
        b = self.coordinator.initiate_booking(p.patient_id, self.clinician.clinician_id, self.slot.slot_id, "Consultation")
        
        # Payment confirmation
        raw_payload = json.dumps(self.gateway.generate_webhook_payload(b.payment.order_id))
        sig = self.gateway.compute_signature(raw_payload)
        self.coordinator.handle_payment_webhook(raw_payload, sig)

        msgs = self.whatsapp.get_messages_for_phone("+919777711111")
        # Confirmation message sent
        conf_msg = msgs[-1]["content"]
        self.assertIn("Appointment Confirmed", conf_msg)
        # Old hardcoded names MUST NOT appear
        self.assertNotIn("Rohan", conf_msg)
        self.assertNotIn("Arjun", conf_msg)
        self.assertNotIn("Meera Joshi", conf_msg)

    # -----------------------------------------------------------------
    # Test 23: Crisis Check Preempts Name Entry
    # -----------------------------------------------------------------
    def test_crisis_check_preempts_name_entry(self):
        phone = "+919666655555"
        self.coordinator.set_conversation_state(phone, "AWAITING_NAME")
        crisis_text = "I feel so hopeless, I want to end my life"

        # Create temporary profile as done in app.py
        p = self.coordinator.register_or_get_patient("Patient", phone)
        task = self.coordinator.check_psychiatric_crisis(p.patient_id, crisis_text)
        self.assertIsNotNone(task)
        self.assertEqual(task.priority, TaskPriority.P0_URGENT)
        self.assertIn(phone, self.coordinator.ai_muted_phones)


if __name__ == "__main__":
    unittest.main(verbosity=2)
