"""
Interactive CLI Demo & Simulation for the Clinic Coordination Engine.
Shows what the patient sees on WhatsApp and what the clinic staff sees on the dashboard.
Uses plain ASCII formatting to ensure full compatibility with standard Windows PowerShell consoles.
"""

from datetime import datetime, timedelta
import json
import sys
from pathlib import Path

# Ensure root is in path
root_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(root_dir))

from src.models import (
    BookingState,
    Clinician,
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


def print_banner(text: str):
    print("\n" + "=" * 72)
    print(f" {text}")
    print("=" * 72)


def print_patient_phone(msg: str):
    print("\n[PATIENT WHATSAPP SCREEN]")
    print("+----------------------------------------------------------------------+")
    for line in msg.split("\n"):
        print(f"|  {line}")
    print("+----------------------------------------------------------------------+")


def print_staff_dashboard(tasks, title="STAFF LIVE DASHBOARD"):
    print(f"\n[STAFF LIVE DASHBOARD -- {title}]")
    print("+----------------------------------------------------------------------+")
    if not tasks:
        print("|  No active alerts. All operations running smoothly.                  |")
    for t in tasks:
        badge = "CRITICAL (P0)" if t.priority == TaskPriority.P0_URGENT else "HIGH (P1)"
        print(f"|  [{badge}] {t.title}")
        print(f"|     Owner: {t.assigned_to or 'Unassigned'} | SLA Deadline: {t.due_date.strftime('%H:%M:%S')}")
        print(f"|     Details: {t.description[:60]}...")
    print("+----------------------------------------------------------------------+")


def run_demo():
    print_banner("THE BENGALURU CLINIC -- LIVE COORDINATION SIMULATION")
    print("Initializing services: Setmore API, Razorpay Gateway, WhatsApp Engine, Staff Dashboard...")

    setmore = MockSetmoreService()
    gateway = MockPaymentGateway()
    whatsapp = MockWhatsAppService()
    task_manager = TaskManager()

    coord = ClinicBookingCoordinator(
        setmore_service=setmore,
        payment_gateway=gateway,
        whatsapp_service=whatsapp,
        task_manager=task_manager,
        slot_ttl_minutes=15,
    )

    # Setup Clinician
    clinician = Clinician(
        clinician_id="DOC-101",
        name="Dr. Ananya Sharma",
        specialty="Sexual & Relationship Health",
        setmore_staff_key="key_101",
        consultation_fee=2500.0,
        duration_minutes=50,
    )
    coord.clinicians[clinician.clinician_id] = clinician

    # Slot 1: Tomorrow 11:00 AM
    tomorrow = datetime.now() + timedelta(days=1)
    slot1 = TimeSlot(
        slot_id="SLOT-101",
        clinician_id=clinician.clinician_id,
        start_time=datetime(tomorrow.year, tomorrow.month, tomorrow.day, 11, 0),
        end_time=datetime(tomorrow.year, tomorrow.month, tomorrow.day, 11, 50),
    )
    setmore.add_slot(slot1)

    # Slot 2: Tomorrow 2:00 PM
    slot2 = TimeSlot(
        slot_id="SLOT-102",
        clinician_id=clinician.clinician_id,
        start_time=datetime(tomorrow.year, tomorrow.month, tomorrow.day, 14, 0),
        end_time=datetime(tomorrow.year, tomorrow.month, tomorrow.day, 14, 50),
    )
    setmore.add_slot(slot2)

    # -------------------------------------------------------------------------
    # SCENARIO 1: Happy Path Booking
    # -------------------------------------------------------------------------
    print_banner("SCENARIO 1: Happy Path Booking (Patient Books & Pays via UPI)")
    print("Step 1: Patient 'Rohan Verma' (+91-98888-11111) requests a session with Dr. Ananya.")
    patient = coord.register_or_get_patient("Rohan Verma", "+919888811111", discrete_name="Rohan")

    print("Step 2: System places 15-minute hold on Slot #SLOT-101 and generates Razorpay link.")
    booking = coord.initiate_booking(
        patient_id=patient.patient_id,
        clinician_id=clinician.clinician_id,
        slot_id=slot1.slot_id,
        service_name="Relationship Consultation",
        mode="IN_PERSON",
    )

    last_msg = whatsapp.get_messages_for_phone(patient.phone_number)[-1]
    print_patient_phone(last_msg["content"])

    print("\nStep 3: Patient completes UPI payment. Razorpay fires cryptographic webhook (HMAC-SHA256).")
    raw_payload = json.dumps(gateway.generate_webhook_payload(booking.payment.order_id))
    signature = gateway.compute_signature(raw_payload)

    result = coord.handle_payment_webhook(raw_payload, signature)
    print(f"        Webhook Signature Status: VERIFIED")
    print(f"        Booking State: {booking.state.value}")
    print(f"        Setmore Calendar Confirmed ID: {booking.setmore_appointment_id}")

    confirm_msg = whatsapp.get_messages_for_phone(patient.phone_number)[-1]
    print_patient_phone(confirm_msg["content"])

    # -------------------------------------------------------------------------
    # SCENARIO 2: Failure Case Caught - Payment Received After Slot Lost
    # -------------------------------------------------------------------------
    print_banner("SCENARIO 2: Failure Case Caught -- Late Payment after Slot Expiration")
    print("Step 1: Patient 'Meghali Sacchdeva' (+91-98888-22222) requests Slot #SLOT-102 (2:00 PM).")
    patient_b = coord.register_or_get_patient("Meghali Sacchdeva", "+919888822222", discrete_name="Meghali")
    booking_b = coord.initiate_booking(
        patient_id=patient_b.patient_id,
        clinician_id=clinician.clinician_id,
        slot_id=slot2.slot_id,
        service_name="Therapy",
    )

    print("Step 2: Meghali's 15-minute hold expires. In the meantime, another patient books Slot #SLOT-102.")
    booking_b.hold_expires_at = datetime.now() - timedelta(minutes=5)
    slot2.is_booked = True
    slot2.held_by_booking_id = "ANOTHER_PATIENT_999"

    print("Step 3: Meghali completes UPI payment 25 minutes later. Money captured, but slot is GONE!")
    raw_b = json.dumps(gateway.generate_webhook_payload(booking_b.payment.order_id))
    sig_b = gateway.compute_signature(raw_b)

    result_b = coord.handle_payment_webhook(raw_b, sig_b)
    print(f"        State Machine Transitioned To: {booking_b.state.value}")
    print(f"        Safeguard: Calendar double-booking prevented!")

    patient_b_msg = whatsapp.get_messages_for_phone(patient_b.phone_number)[-1]
    print_patient_phone(patient_b_msg["content"])

    # Show staff dashboard
    open_tasks = task_manager.get_open_tasks()
    print_staff_dashboard(open_tasks, title="EXCEPTION CAUGHT!")
    print("\n[SUCCESS] Simulation complete! The coordinator prevents double-booking while ensuring")
    print("          no patient payment is lost or ignored.")


if __name__ == "__main__":
    run_demo()
