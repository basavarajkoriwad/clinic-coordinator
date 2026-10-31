"""
Unit and Integration Test Suite for all 10 Production Failure Scenarios.
"""

from datetime import datetime, timedelta
from pathlib import Path
import sys
import unittest

root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from src.models import (
    BookingRecord,
    BookingState,
    Clinician,
    PatientProfile,
    PaymentRecord,
    TaskPriority,
    TimeSlot,
)
from src.mock_services import (
    MockPaymentGateway,
    MockSetmoreService,
    MockWhatsAppService,
    TaskManager,
)
from src.coordinator import ClinicBookingCoordinator
from src.failure_scenarios import (
    SecureReportVault,
    handle_after_hours_missed_call,
    handle_late_payment_slot_conflict,
    handle_setmore_api_outage,
    handle_webhook_idempotency,
    intercept_psychiatric_crisis,
    reschedule_and_rebuild_reminders,
    resolve_shared_phone_profiles,
    sweep_and_release_expired_holds,
    verify_hmac_sha256_constant_time,
)


class Test10FailureScenarios(unittest.TestCase):
    def setUp(self):
        self.setmore = MockSetmoreService()
        self.gateway = MockPaymentGateway()
        self.whatsapp = MockWhatsAppService()
        self.tasks = TaskManager()
        self.coordinator = ClinicBookingCoordinator(
            self.setmore, self.gateway, self.whatsapp, self.tasks, slot_ttl_minutes=15
        )

    # 1. Duplicate Webhook Idempotency
    def test_01_webhook_idempotency(self):
        cache = set()
        is_dup, _ = handle_webhook_idempotency("pay_abc123", cache)
        self.assertFalse(is_dup)
        is_dup_second, msg = handle_webhook_idempotency("pay_abc123", cache)
        self.assertTrue(is_dup_second)
        self.assertIn("Duplicate webhook ignored", msg["message"])

    # 2. Late Payment Race Condition (Slot Taken)
    def test_02_late_payment_slot_lost(self):
        patient = PatientProfile(patient_id="PAT-01", full_name="Arjun N", phone_number="+919888800001", discrete_name="Arjun")
        slot = TimeSlot("SLOT-A", "DOC-1", datetime.now(), datetime.now() + timedelta(minutes=50), is_booked=True)
        booking = BookingRecord(patient_id="PAT-01", slot_id="SLOT-A", payment=PaymentRecord("order_1", amount_inr=2500.0))
        
        res = handle_late_payment_slot_conflict(booking, slot, "pay_late_123", patient, self.tasks, self.whatsapp)
        self.assertEqual(booking.state, BookingState.PAYMENT_RECEIVED_SLOT_LOST)
        self.assertEqual(res["status"], "exception")
        p0_tasks = self.tasks.get_open_tasks(TaskPriority.P0_URGENT)
        self.assertTrue(any("Payment Received but Slot Lost" in t.title for t in p0_tasks))

    # 3. Upstream Calendar API 500 Outage
    def test_03_setmore_api_outage(self):
        patient = PatientProfile(patient_id="PAT-02", full_name="Meera J", phone_number="+919888800002", discrete_name="Meera")
        booking = BookingRecord(patient_id="PAT-02", payment=PaymentRecord("order_2", amount_inr=2500.0))
        
        res = handle_setmore_api_outage(booking, "pay_err_456", "Setmore 500 Timeout", patient, self.tasks, self.whatsapp)
        self.assertEqual(booking.state, BookingState.PAYMENT_CAPTURED_BOOKING_FAILED)
        p0_tasks = self.tasks.get_open_tasks(TaskPriority.P0_URGENT)
        self.assertTrue(any("Setmore Booking Failed" in t.title for t in p0_tasks))

    # 4. Constant-Time HMAC Signature Verification
    def test_04_hmac_constant_time(self):
        secret = "clinic_secret_key"
        payload = '{"event":"order.paid"}'
        import hashlib, hmac
        valid_sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        
        self.assertTrue(verify_hmac_sha256_constant_time(secret, payload, valid_sig))
        self.assertFalse(verify_hmac_sha256_constant_time(secret, payload, "tampered_sig"))

    # 5. Shared-Phone Couples Privacy
    def test_05_shared_phone_couples(self):
        phone = "+919876543210"
        p1 = PatientProfile(patient_id="PAT-10", full_name="Pooja K", phone_number=phone)
        p2 = PatientProfile(patient_id="PAT-20", full_name="Sameer K", phone_number=phone)
        repo = {"PAT-10": p1, "PAT-20": p2}
        mapping = {phone: ["PAT-10", "PAT-20"]}

        status, profiles = resolve_shared_phone_profiles(phone, mapping, repo)
        self.assertEqual(status, "MULTIPLE_PROFILES")
        self.assertEqual(len(profiles), 2)
        self.assertNotEqual(profiles[0].patient_id, profiles[1].patient_id)

    # 6. Expired Hold Cleanup
    def test_06_sweep_expired_holds(self):
        patient = PatientProfile(patient_id="PAT-03", full_name="Rohan V", phone_number="+919888800003")
        slot = TimeSlot("SLOT-HOLD", "DOC-1", datetime.now(), datetime.now() + timedelta(minutes=50), is_held=True)
        self.setmore.add_slot(slot)
        
        booking = BookingRecord(
            booking_id="BKG-EXP-1",
            patient_id="PAT-03",
            slot_id="SLOT-HOLD",
            state=BookingState.PAYMENT_PENDING,
            hold_expires_at=datetime.now() - timedelta(minutes=5)
        )
        released = sweep_and_release_expired_holds({"BKG-EXP-1": booking}, self.setmore, self.whatsapp, {"PAT-03": patient})
        self.assertIn("BKG-EXP-1", released)
        self.assertEqual(booking.state, BookingState.HOLD_EXPIRED)

    # 7. Rescheduling & Dynamic Reminders Rebuilding
    def test_07_reschedule_reminders(self):
        doc = Clinician("DOC-1", "Dr. Varma", "Sexology", "key_1", 2500.0, 50)
        self.coordinator.clinicians["DOC-1"] = doc
        
        old_slot = TimeSlot("SLOT-OLD", "DOC-1", datetime.now() + timedelta(days=1), datetime.now() + timedelta(days=1, minutes=50))
        new_slot = TimeSlot("SLOT-NEW", "DOC-1", datetime.now() + timedelta(days=4), datetime.now() + timedelta(days=4, minutes=50))
        self.setmore.add_slot(old_slot)
        self.setmore.add_slot(new_slot)
        
        booking = BookingRecord(booking_id="BKG-RESCHED", patient_id="PAT-01", clinician_id="DOC-1", slot_id="SLOT-OLD", setmore_appointment_id="SET-1")
        res = reschedule_and_rebuild_reminders(booking, new_slot, self.setmore, self.coordinator)
        self.assertEqual(res["status"], "rescheduled")
        self.assertEqual(booking.slot_id, "SLOT-NEW")

    # 8. Lab Report 2FA Token Vault Gate
    def test_08_lab_report_2fa_vault(self):
        vault = SecureReportVault()
        token = vault.generate_expiring_token("REP-900", "PAT-01")
        
        # Wrong OTP -> Access Denied
        ok_wrong, msg_wrong = vault.verify_otp_and_access(token, "000000")
        self.assertFalse(ok_wrong)
        self.assertIn("Incorrect OTP", msg_wrong)
        
        # Correct OTP -> Access Granted
        ok_correct, msg_correct = vault.verify_otp_and_access(token, "842915")
        self.assertTrue(ok_correct)
        self.assertIn("ACCESS_GRANTED", msg_correct)

    # 9. After-Hours Missed Call Callback SLA
    def test_09_after_hours_missed_call(self):
        night_time = datetime(2026, 10, 27, 22, 30)  # 10:30 PM
        task = handle_after_hours_missed_call("+919888800009", night_time, self.tasks, self.whatsapp)
        self.assertEqual(task.assigned_to, "Morning_Receptionist")
        self.assertEqual(task.priority, TaskPriority.P1_HIGH)
        # Verify WhatsApp sent
        messages = self.whatsapp.get_messages_for_phone("+919888800009")
        self.assertIn("9:30 AM", messages[-1]["content"])

    # 10. Psychiatric Crisis Red-Line Interception
    def test_10_psychiatric_crisis_filter(self):
        is_crisis, response = intercept_psychiatric_crisis("I want to end my life", "+919888800010", self.tasks, self.whatsapp)
        self.assertTrue(is_crisis)
        self.assertIn("Tele-MANAS", response)
        p0_tasks = self.tasks.get_open_tasks(TaskPriority.P0_URGENT)
        self.assertTrue(any("CLINICAL RED-LINE" in t.title for t in p0_tasks))


if __name__ == "__main__":
    unittest.main(verbosity=2)
