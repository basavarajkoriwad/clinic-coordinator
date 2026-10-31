"""
Unit Tests for Coordinator Helper Functions and Algorithms.
"""

from datetime import datetime, timedelta
import hashlib
from pathlib import Path
import sys
import unittest

root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from src.models import (
    PatientProfile,
    format_doctor_name,
)
from src.coordinator import (
    CRISIS_PATTERN,
    ClinicBookingCoordinator,
    patient_greeting,
)
from tests.helpers import create_fresh_coordinator


class TestCoordinatorHelpersUnit(unittest.TestCase):
    def setUp(self):
        self.coord = create_fresh_coordinator()

    # -------------------------------------------------------------
    # Name Formatting and Greetings
    # -------------------------------------------------------------
    def test_format_doctor_name(self):
        self.assertEqual(format_doctor_name("Dr. X"), "Dr. X")
        self.assertEqual(format_doctor_name("dr. x"), "Dr. x")
        self.assertEqual(format_doctor_name("X"), "Dr. X")
        self.assertEqual(format_doctor_name("dr x"), "Dr. x")
        self.assertEqual(format_doctor_name("Dr. Dr. X"), "Dr. X")
        self.assertEqual(format_doctor_name(""), "Dr. Clinician")
        self.assertEqual(format_doctor_name(None), "Dr. Clinician")

    def test_patient_greeting(self):
        p1 = PatientProfile(full_name="Zoya Menon", discrete_name="Zoya")
        self.assertEqual(patient_greeting(p1), "Zoya")

        p2 = PatientProfile(full_name="Aarav Iyer")
        self.assertEqual(patient_greeting(p2), "Aarav")

        self.assertEqual(patient_greeting("Zoya Menon"), "Zoya")
        self.assertEqual(patient_greeting(""), "")
        self.assertEqual(patient_greeting(None), "")

    # -------------------------------------------------------------
    # Name Validation
    # -------------------------------------------------------------
    def test_validate_patient_name(self):
        # Valid names
        self.assertTrue(self.coord.validate_patient_name("Zoya Menon"))
        self.assertTrue(self.coord.validate_patient_name("Aarav Iyer"))
        self.assertTrue(self.coord.validate_patient_name("Dr. O'Connor-Smith"))
        self.assertTrue(self.coord.validate_patient_name("Renée Duprès"))  # Unicode letters
        self.assertTrue(self.coord.validate_patient_name("A. B. C."))

        # Too short (< 2 chars)
        self.assertFalse(self.coord.validate_patient_name(""))
        self.assertFalse(self.coord.validate_patient_name("A"))
        self.assertFalse(self.coord.validate_patient_name("   "))

        # Too long (> 60 chars)
        self.assertFalse(self.coord.validate_patient_name("A" * 61))

        # Digits forbidden
        self.assertFalse(self.coord.validate_patient_name("Zoya123"))
        self.assertFalse(self.coord.validate_patient_name("12345"))

        # HTML / Scripts forbidden
        self.assertFalse(self.coord.validate_patient_name("<script>alert(1)</script>"))
        self.assertFalse(self.coord.validate_patient_name("Zoya<img src=x>"))
        self.assertFalse(self.coord.validate_patient_name("Zoya; DROP TABLE;"))

        # Punctuation without letters
        self.assertFalse(self.coord.validate_patient_name("..."))
        self.assertFalse(self.coord.validate_patient_name("---"))

    # -------------------------------------------------------------
    # Reminder Scheduling Logic
    # -------------------------------------------------------------
    def test_calculate_active_reminders_skips_elapsed(self):
        booking_time = datetime(2026, 10, 20, 10, 0)

        # 5 days in advance -> all 3 reminders active
        appt_5d = datetime(2026, 10, 25, 14, 0)
        reminders_5d = self.coord.calculate_active_reminders(appt_5d, booking_time)
        labels_5d = [r["label"] for r in reminders_5d]
        self.assertEqual(len(reminders_5d), 3)
        self.assertIn("72_HOURS_BEFORE", labels_5d)
        self.assertIn("24_HOURS_BEFORE", labels_5d)
        self.assertIn("MORNING_OF_APPOINTMENT", labels_5d)

        # Short notice: booked Oct 24 for Oct 25 -> 72h reminder was Oct 22 (elapsed, skipped!)
        short_booking = datetime(2026, 10, 24, 15, 0)
        reminders_short = self.coord.calculate_active_reminders(appt_5d, short_booking)
        labels_short = [r["label"] for r in reminders_short]
        self.assertNotIn("72_HOURS_BEFORE", labels_short)
        self.assertIn("MORNING_OF_APPOINTMENT", labels_short)

        # Same-day booking afternoon -> morning reminder already passed
        same_day_booking = datetime(2026, 10, 25, 11, 0)
        reminders_same_day = self.coord.calculate_active_reminders(appt_5d, same_day_booking)
        self.assertEqual(len(reminders_same_day), 0)

    # -------------------------------------------------------------
    # PBKDF2 PIN Authentication & Lockout
    # -------------------------------------------------------------
    def test_pin_pbkdf2_and_lockout_expiry(self):
        patient = self.coord.register_or_get_patient("Pooja Kulkarni", "+919876500000")
        self.coord.set_patient_pin(patient.patient_id, "4321")

        # Salt and hash stored
        self.assertIsNotNone(patient.pin_salt)
        self.assertIsNotNone(patient.pin_hash)

        # Valid PIN
        ok, msg = self.coord.verify_patient_pin(patient.patient_id, "4321")
        self.assertTrue(ok)
        self.assertEqual(patient.failed_pin_attempts, 0)

        # Attempt 1 incorrect
        ok1, msg1 = self.coord.verify_patient_pin(patient.patient_id, "0000")
        self.assertFalse(ok1)
        self.assertEqual(patient.failed_pin_attempts, 1)
        self.assertIn("2 attempt(s) remaining", msg1)

        # Attempt 2 incorrect
        ok2, msg2 = self.coord.verify_patient_pin(patient.patient_id, "0000")
        self.assertFalse(ok2)
        self.assertEqual(patient.failed_pin_attempts, 2)
        self.assertIn("1 attempt(s) remaining", msg2)

        # Attempt 3 incorrect -> 15-min lockout!
        ok3, msg3 = self.coord.verify_patient_pin(patient.patient_id, "0000")
        self.assertFalse(ok3)
        self.assertEqual(patient.failed_pin_attempts, 3)
        self.assertIn("locked", msg3.lower())
        self.assertIsNotNone(patient.locked_until)

        # Locked attempt
        ok_locked, msg_locked = self.coord.verify_patient_pin(patient.patient_id, "4321")
        self.assertFalse(ok_locked)
        self.assertIn("locked for security", msg_locked.lower())

        # Fast-forward past lockout window
        patient.locked_until = datetime.now() - timedelta(minutes=1)
        ok_unlocked, _ = self.coord.verify_patient_pin(patient.patient_id, "4321")
        self.assertTrue(ok_unlocked)
        self.assertEqual(patient.failed_pin_attempts, 0)

    # -------------------------------------------------------------
    # Crisis Regex & False Positive Immunity
    # -------------------------------------------------------------
    def test_crisis_regex_catches_distress_and_ignores_false_positives(self):
        # Genuine crisis phrases
        phrases = [
            "I want to commit suicide",
            "Feeling suicidal today",
            "I will kill myself",
            "I want to end my life",
            "I am ending my life tonight",
            "I want to die right now",
            "Thinking about how to hang myself",
            "Urges of self harm",
            "Struggling with self-harm",
            "I can't go on anymore",
            "I cannot go on like this",
        ]
        for phrase in phrases:
            self.assertTrue(bool(CRISIS_PATTERN.search(phrase)), f"Failed to match: {phrase}")

        # False positives immunity: words like diet, studied, audience
        false_positives = [
            "I started a new diet today",
            "I studied biology in college",
            "I gave a speech to an audience",
            "The candidate gave an interview",
            "My friend is a dietician",
        ]
        for fp in false_positives:
            self.assertFalse(bool(CRISIS_PATTERN.search(fp)), f"Falsely matched: {fp}")

    # -------------------------------------------------------------
    # After-Hours SLA Calculation
    # -------------------------------------------------------------
    def test_calculate_missed_call_sla(self):
        # Daytime working hours: 11:30 AM -> 30m SLA to FrontDesk_Lead
        day_time = datetime(2026, 10, 28, 11, 30)
        sla_day, due_day, agent_day = self.coord.calculate_missed_call_sla(day_time)
        self.assertEqual(sla_day, 30)
        self.assertEqual(due_day, datetime(2026, 10, 28, 12, 0))
        self.assertEqual(agent_day, "FrontDesk_Lead")

        # Night time after hours: 10:30 PM (22:30) -> SLA until next 9:30 AM to Morning_Receptionist
        night_time = datetime(2026, 10, 28, 22, 30)
        sla_night, due_night, agent_night = self.coord.calculate_missed_call_sla(night_time)
        self.assertEqual(due_night, datetime(2026, 10, 29, 9, 30))
        self.assertEqual(sla_night, int((datetime(2026, 10, 29, 9, 30) - night_time).total_seconds() / 60))
        self.assertEqual(agent_night, "Morning_Receptionist")

        # Early morning before 9 AM: 07:00 AM -> SLA until 09:30 AM same day
        early_time = datetime(2026, 10, 28, 7, 0)
        sla_early, due_early, agent_early = self.coord.calculate_missed_call_sla(early_time)
        self.assertEqual(due_early, datetime(2026, 10, 28, 9, 30))
        self.assertEqual(sla_early, 150)
        self.assertEqual(agent_early, "Morning_Receptionist")

    # -------------------------------------------------------------
    # Audit Hash Chain & Tamper Detection
    # -------------------------------------------------------------
    def test_audit_hash_chain_and_tamper_detection(self):
        self.coord.audit_log.clear()

        self.coord.audit("SYSTEM", "System initialized")
        self.coord.audit("BOOKING", "Slot held for Zoya Menon")
        self.coord.audit("PAYMENT", "Payment captured INR 2500")

        # Chain verifies as valid
        valid, broken_seq = self.coord.verify_audit_chain()
        self.assertTrue(valid)
        self.assertIsNone(broken_seq)

        # Tampering with entry 2 breaks the chain!
        self.coord.audit_log[1].message = "Tampered message by attacker"
        tampered_valid, tampered_seq = self.coord.verify_audit_chain()
        self.assertFalse(tampered_valid)
        self.assertEqual(tampered_seq, 2)

    # -------------------------------------------------------------
    # OTP Generation and Verification
    # -------------------------------------------------------------
    def test_otp_generation_and_verification(self):
        patient_id = "PAT-OTP-TEST"
        otp = self.coord.generate_otp(patient_id, ttl_minutes=5)

        # 6 digits
        self.assertEqual(len(otp), 6)
        self.assertTrue(otp.isdigit())

        # Wrong OTP gives remaining attempts
        ok_wrong, msg_wrong = self.coord.verify_otp(patient_id, "000000")
        self.assertFalse(ok_wrong)
        self.assertIn("2 attempt(s) remaining", msg_wrong)

        # Correct OTP succeeds
        ok_correct, msg_correct = self.coord.verify_otp(patient_id, otp)
        self.assertTrue(ok_correct)
        self.assertIn("successfully", msg_correct)

    def test_otp_expiry_and_max_attempts(self):
        patient_id = "PAT-OTP-EXP"
        otp = self.coord.generate_otp(patient_id, ttl_minutes=5)

        # Expire OTP
        self.coord.active_otps[patient_id]["expires_at"] = datetime.now() - timedelta(minutes=1)
        ok_exp, msg_exp = self.coord.verify_otp(patient_id, otp)
        self.assertFalse(ok_exp)
        self.assertIn("expired", msg_exp.lower())

        # Re-generate and test 3 wrong attempts lockout
        new_otp = self.coord.generate_otp(patient_id, ttl_minutes=5)
        self.coord.verify_otp(patient_id, "111111")
        self.coord.verify_otp(patient_id, "222222")
        ok_3, msg_3 = self.coord.verify_otp(patient_id, "333333")
        self.assertFalse(ok_3)
        self.assertIn("Maximum attempts exceeded", msg_3)

    # -------------------------------------------------------------
    # Idempotency Cache
    # -------------------------------------------------------------
    def test_idempotency_cache(self):
        pid = "pay_unique_test_99"
        self.assertNotIn(pid, self.coord.processed_payment_ids)
        self.coord.processed_payment_ids.add(pid)
        self.assertIn(pid, self.coord.processed_payment_ids)


if __name__ == "__main__":
    unittest.main()
