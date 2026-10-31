"""
Unit Tests for Data Models, Enums, and Model Formatting Utilities.
"""

from datetime import datetime
from pathlib import Path
import sys
import unittest

root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from src.models import (
    AuditEntry,
    BookingRecord,
    BookingState,
    Clinician,
    PatientProfile,
    PaymentRecord,
    StaffTask,
    TaskPriority,
    TaskStatus,
    TimeSlot,
    format_doctor_name,
)


class TestModelsUnit(unittest.TestCase):
    def test_enums_values_and_membership(self):
        # BookingState
        self.assertEqual(BookingState.INITIATED.value, "INITIATED")
        self.assertEqual(BookingState.SLOT_HELD.value, "SLOT_HELD")
        self.assertEqual(BookingState.PAYMENT_PENDING.value, "PAYMENT_PENDING")
        self.assertEqual(BookingState.CONFIRMED.value, "CONFIRMED")
        self.assertEqual(BookingState.HOLD_EXPIRED.value, "HOLD_EXPIRED")
        self.assertEqual(BookingState.PAYMENT_CAPTURED_BOOKING_FAILED.value, "PAYMENT_CAPTURED_BOOKING_FAILED")
        self.assertEqual(BookingState.PAYMENT_RECEIVED_SLOT_LOST.value, "PAYMENT_RECEIVED_SLOT_LOST")
        self.assertEqual(BookingState.REFUNDED.value, "REFUNDED")

        # TaskPriority
        self.assertEqual(TaskPriority.P0_URGENT.value, "P0_URGENT")
        self.assertEqual(TaskPriority.P1_HIGH.value, "P1_HIGH")
        self.assertEqual(TaskPriority.P2_MEDIUM.value, "P2_MEDIUM")
        self.assertEqual(TaskPriority.P3_LOW.value, "P3_LOW")

        # TaskStatus
        self.assertEqual(TaskStatus.OPEN.value, "OPEN")
        self.assertEqual(TaskStatus.IN_PROGRESS.value, "IN_PROGRESS")
        self.assertEqual(TaskStatus.RESOLVED.value, "RESOLVED")
        self.assertEqual(TaskStatus.ESCALATED.value, "ESCALATED")

    def test_patient_profile_defaults_and_unique_ids(self):
        p1 = PatientProfile(full_name="Zoya Menon", phone_number="+919876543210")
        p2 = PatientProfile(full_name="Aarav Iyer", phone_number="+919876543211")

        self.assertTrue(p1.patient_id.startswith("PAT-"))
        self.assertTrue(p2.patient_id.startswith("PAT-"))
        self.assertNotEqual(p1.patient_id, p2.patient_id)
        self.assertEqual(p1.failed_pin_attempts, 0)
        self.assertIsNone(p1.locked_until)
        self.assertIsNone(p1.pin_salt)
        self.assertIsNone(p1.pin_hash)
        self.assertTrue(isinstance(p1.created_at, datetime))

    def test_clinician_and_slot_models(self):
        doc = Clinician(
            clinician_id="DOC-1",
            name="Dr. Rajesh Rao",
            specialty="Clinical Psychology",
            setmore_staff_key="key_1",
            consultation_fee=2000.0,
            duration_minutes=45,
            service_label="Psychology Session",
        )
        self.assertEqual(doc.clinician_id, "DOC-1")
        self.assertEqual(doc.consultation_fee, 2000.0)

        slot = TimeSlot(
            slot_id="SLOT-1",
            clinician_id="DOC-1",
            start_time=datetime.now(),
            end_time=datetime.now(),
        )
        self.assertFalse(slot.is_held)
        self.assertFalse(slot.is_booked)
        self.assertIsNone(slot.held_until)
        self.assertIsNone(slot.held_by_booking_id)

    def test_staff_task_and_booking_record_unique_ids(self):
        t1 = StaffTask(patient_id="PAT-1", title="Task 1")
        t2 = StaffTask(patient_id="PAT-2", title="Task 2")
        self.assertTrue(t1.task_id.startswith("TSK-"))
        self.assertTrue(t2.task_id.startswith("TSK-"))
        self.assertNotEqual(t1.task_id, t2.task_id)
        self.assertEqual(t1.status, TaskStatus.OPEN)

        b1 = BookingRecord(patient_id="PAT-1", clinician_id="DOC-1", slot_id="SLOT-1")
        b2 = BookingRecord(patient_id="PAT-2", clinician_id="DOC-1", slot_id="SLOT-2")
        self.assertTrue(b1.booking_id.startswith("BKG-"))
        self.assertTrue(b2.booking_id.startswith("BKG-"))
        self.assertNotEqual(b1.booking_id, b2.booking_id)
        self.assertEqual(b1.state, BookingState.INITIATED)

    def test_audit_entry_fields(self):
        entry = AuditEntry(
            seq=1,
            timestamp=datetime.now().isoformat(),
            category="SECURITY",
            message="Test security event",
            prev_hash="0" * 64,
            hash="abc123hash",
        )
        self.assertEqual(entry.seq, 1)
        self.assertEqual(entry.category, "SECURITY")
        self.assertEqual(entry.prev_hash, "0" * 64)

    def test_format_doctor_name_all_variants(self):
        # Doctor with prefix
        self.assertEqual(format_doctor_name("Dr. Rajesh Rao"), "Dr. Rajesh Rao")
        self.assertEqual(format_doctor_name("Dr. X"), "Dr. X")

        # Lowercase prefix
        self.assertEqual(format_doctor_name("dr. x"), "Dr. x")
        self.assertEqual(format_doctor_name("dr x"), "Dr. x")

        # Without prefix
        self.assertEqual(format_doctor_name("X"), "Dr. X")
        self.assertEqual(format_doctor_name("Rajesh Rao"), "Dr. Rajesh Rao")

        # Double prefix
        self.assertEqual(format_doctor_name("Dr. Dr. X"), "Dr. X")
        self.assertEqual(format_doctor_name("dr. dr. X"), "Dr. X")

        # Empty and None
        self.assertEqual(format_doctor_name(""), "Dr. Clinician")
        self.assertEqual(format_doctor_name(None), "Dr. Clinician")
        self.assertEqual(format_doctor_name("   "), "Dr. Clinician")


if __name__ == "__main__":
    unittest.main()
