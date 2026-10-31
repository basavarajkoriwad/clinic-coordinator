"""
Integration Tests for Happy Path Booking Lifecycle & 15-Minute Slot Expiry.
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
    Clinician,
    TimeSlot,
    format_doctor_name,
)
from tests.helpers import create_fresh_coordinator, seed_test_clinicians_and_slots


class TestBookingFlowIntegration(unittest.TestCase):
    def setUp(self):
        self.coord = create_fresh_coordinator(slot_ttl_minutes=15)
        seed_test_clinicians_and_slots(self.coord)

    def test_full_happy_path_booking_flow(self):
        patient_name = "Zoya Menon"
        phone = "+919876543210"

        # 1. Name validation & patient registration
        self.assertTrue(self.coord.validate_patient_name(patient_name))
        patient = self.coord.register_or_get_patient(patient_name, phone)
        self.assertEqual(patient.discrete_name, "Zoya")

        # 2. Availability lookup
        avail = self.coord.get_availability()
        self.assertTrue(len(avail) >= 3)
        chosen_clinician = avail[0]
        self.assertTrue(len(chosen_clinician["slots"]) > 0)
        chosen_slot = chosen_clinician["slots"][0]

        # 3. Hold & Order Creation
        booking = self.coord.initiate_booking(
            patient_id=patient.patient_id,
            clinician_id=chosen_clinician["clinician_id"],
            slot_id=chosen_slot["slot_id"],
            service_name=chosen_clinician["service_label"],
        )
        self.assertEqual(booking.state, BookingState.PAYMENT_PENDING)
        self.assertIsNotNone(booking.payment.order_id)
        self.assertIsNotNone(booking.hold_expires_at)

        # 4. Payment Link WhatsApp message verification (Strictly NO slot day or time shown)
        wa_msgs = self.coord.whatsapp.get_messages_for_phone(phone)
        self.assertTrue(len(wa_msgs) >= 1)
        payment_msg = wa_msgs[-1]["content"]
        self.assertIn(booking.payment.payment_link_url, payment_msg)
        self.assertIn("15 minutes", payment_msg)
        self.assertIn("expire automatically", payment_msg)
        self.assertNotIn("Tomorrow", payment_msg)
        self.assertNotIn("Today", payment_msg)
        self.assertNotIn("AM", payment_msg)
        self.assertNotIn("PM", payment_msg)

        # 5. Webhook processing (Razorpay order.paid event)
        order_id = booking.payment.order_id
        webhook_payload = json.dumps(self.coord.gateway.generate_webhook_payload(order_id))
        sig = self.coord.gateway.compute_signature(webhook_payload)
        res = self.coord.handle_payment_webhook(webhook_payload, sig)

        self.assertEqual(res["status"], "success")
        self.assertEqual(booking.state, BookingState.CONFIRMED)
        self.assertIsNotNone(booking.setmore_appointment_id)

        # 6. Confirmation message verification
        confirmed_wa_msgs = self.coord.whatsapp.get_messages_for_phone(phone)
        latest_confirmation = confirmed_wa_msgs[-1]["content"]
        self.assertIn("Appointment Confirmed", latest_confirmation)
        self.assertIn(format_doctor_name(chosen_clinician["display_name"]), latest_confirmation)
        self.assertIn("Zoya", latest_confirmation)
        self.assertIn("receipt", latest_confirmation.lower())

    def test_15_minute_hold_expiry_sweep_and_rebooking(self):
        patient = self.coord.register_or_get_patient("Aarav Iyer", "+919876543222")
        avail = self.coord.get_availability()
        clinician = avail[0]
        slot_id = clinician["slots"][0]["slot_id"]

        booking = self.coord.initiate_booking(
            patient_id=patient.patient_id,
            clinician_id=clinician["clinician_id"],
            slot_id=slot_id,
            service_name=clinician["service_label"],
        )
        self.assertEqual(booking.state, BookingState.PAYMENT_PENDING)
        self.assertFalse(self.coord.setmore.check_availability(slot_id))

        # Advance time by 16 minutes (hold expired)
        future_time = datetime.now() + timedelta(minutes=16)
        expired_bookings = self.coord.expire_stale_holds(reference_time=future_time)

        self.assertEqual(len(expired_bookings), 1)
        self.assertEqual(booking.state, BookingState.HOLD_EXPIRED)

        # Verify slot released back to inventory
        self.assertTrue(self.coord.setmore.check_availability(slot_id))

        # Verify expiry message sent to patient without day/time
        msgs = self.coord.whatsapp.get_messages_for_phone(patient.phone_number)
        expiry_msg = msgs[-1]["content"]
        self.assertIn("Aarav", expiry_msg)
        self.assertIn("15-minute payment window has ended", expiry_msg)
        self.assertIn("released", expiry_msg)

        # Slot can now be booked by another patient
        patient2 = self.coord.register_or_get_patient("Zoya Menon", "+919876543333")
        rebooking = self.coord.initiate_booking(
            patient_id=patient2.patient_id,
            clinician_id=clinician["clinician_id"],
            slot_id=slot_id,
            service_name=clinician["service_label"],
        )
        self.assertEqual(rebooking.state, BookingState.PAYMENT_PENDING)
        self.assertFalse(self.coord.setmore.check_availability(slot_id))


if __name__ == "__main__":
    unittest.main()
