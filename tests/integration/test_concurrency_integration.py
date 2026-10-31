"""
Integration Tests for Multithreaded Concurrency & Race Conditions.
"""

from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
import threading
import time
import unittest

root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from src.models import BookingState
from tests.helpers import create_fresh_coordinator, seed_test_clinicians_and_slots


class TestConcurrencyIntegration(unittest.TestCase):
    def setUp(self):
        self.coord = create_fresh_coordinator(slot_ttl_minutes=15)
        seed_test_clinicians_and_slots(self.coord)

    def test_twenty_threads_racing_for_same_slot_single_winner(self):
        """
        Tests 20 concurrent threads trying to book the exact same slot at the exact same millisecond.
        Exactly 1 thread must succeed; the other 19 must receive an unavailable/conflict exception.
        """
        clinician = self.coord.clinicians["DOC-101"]
        target_slot_id = "SLOT-101"

        success_bookings = []
        rejected_errors = []
        lock = threading.Lock()

        # Barrier to release all 20 threads simultaneously
        barrier = threading.Barrier(20)

        def worker(thread_idx: int):
            phone = f"+9198000000{thread_idx:02d}"
            name = f"Patient {thread_idx}"
            patient = self.coord.register_or_get_patient(name, phone)

            barrier.wait()  # Synchronized release

            try:
                booking = self.coord.initiate_booking(
                    patient_id=patient.patient_id,
                    clinician_id=clinician.clinician_id,
                    slot_id=target_slot_id,
                    service_name=clinician.specialty,
                )
                with lock:
                    success_bookings.append(booking)
            except Exception as e:
                with lock:
                    rejected_errors.append(str(e))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exactly 1 winner
        self.assertEqual(len(success_bookings), 1, f"Expected 1 winner, got {len(success_bookings)}")
        self.assertEqual(len(rejected_errors), 19, f"Expected 19 rejections, got {len(rejected_errors)}")
        for err in rejected_errors:
            self.assertTrue("already held or booked" in err.lower() or "slot" in err.lower())

        # Slot state is held
        slot = self.coord.setmore.slots[target_slot_id]
        self.assertTrue(slot.is_held)
        self.assertEqual(slot.held_by_booking_id, success_bookings[0].booking_id)

    def test_webhook_and_expiry_worker_concurrency(self):
        """
        Tests webhook processing thread and 15-min expiry worker thread running
        simultaneously against overlapping bookings to verify zero deadlocks or corrupt state.
        """
        doc = self.coord.clinicians["DOC-102"]
        slots = list(self.coord.setmore.slots.values())[:5]

        bookings = []
        for i, s in enumerate(slots):
            p = self.coord.register_or_get_patient(f"Patient {i}", f"+91988880000{i}")
            b = self.coord.initiate_booking(p.patient_id, s.clinician_id, s.slot_id, "Session")
            bookings.append(b)

        # Mark half as expired, half as active
        now = datetime.now()
        bookings[0].hold_expires_at = now - timedelta(minutes=1)
        bookings[1].hold_expires_at = now - timedelta(minutes=1)

        errors = []

        def expiry_worker():
            try:
                for _ in range(10):
                    self.coord.expire_stale_holds(reference_time=now + timedelta(minutes=2))
                    time.sleep(0.01)
            except Exception as e:
                errors.append(e)

        def webhook_worker():
            try:
                for b in bookings:
                    raw_payload = json.dumps(self.coord.gateway.generate_webhook_payload(b.payment.order_id))
                    sig = self.coord.gateway.compute_signature(raw_payload)
                    self.coord.handle_payment_webhook(raw_payload, sig)
                    time.sleep(0.01)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=expiry_worker)
        t2 = threading.Thread(target=webhook_worker)

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(len(errors), 0, f"Concurrent workers raised exceptions: {errors}")


if __name__ == "__main__":
    unittest.main()
