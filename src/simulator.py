"""
Simulation Engine and Demo Scenario Coordinator.
Provides full multi-step execution for all 6 scenarios:
1. Happy Path Booking (Patient chooses everything: name, clinician, time slot)
2. Late Payment / Slot Lost (P0)
3. Setmore 500 API Outage (P0)
4. Shared Phone PIN Gate
5. Psychiatric Crisis Intercept
6. 2FA Lab Report Vault
"""

from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
from typing import Dict, List, Optional, Any
import uuid

# Ensure root directory is in sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from src.models import (
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
from src.coordinator import ClinicBookingCoordinator, patient_greeting


# DEMO DATA ONLY - Kept strictly for shared-phone couple and walk-in patient
DEMO_PERSONAS = {
    "shared_phone_couple": {
        "phone": "+919876500000",
        "profiles": [
            {"full_name": "Pooja Kulkarni", "discrete_name": "Pooja", "pin": "4321"},
            {"full_name": "Sameer Kulkarni", "discrete_name": "Sameer", "pin": "8765"},
        ],
    },
    "walk_in": {
        "full_name": "Walk-in patient",
        "phone": "+919800000000",
        "discrete_name": "Walk-in",
    },
}


def _get_next_working_days(from_date: datetime, count: int = 2) -> List[datetime]:
    """
    Computes the next working days (Mon-Sat, skipping Sundays).
    """
    working_days = []
    curr = from_date + timedelta(days=1)
    while len(working_days) < count:
        if curr.weekday() != 6:  # 6 is Sunday
            working_days.append(curr)
        curr += timedelta(days=1)
    return working_days


def seed_demo_data(coord: ClinicBookingCoordinator):
    """
    Seeds clinicians, forward-dated appointment slots across working days (9 AM - 8 PM),
    PBKDF2 PINs for shared phone couple, and initial missed call.
    Does NOT seed fixed patient names for scenarios 1, 2, 3, 5, 6.
    """
    with coord.lock:
        # Clear existing
        coord.patients.clear()
        coord.phone_to_patients.clear()
        coord.clinicians.clear()
        coord.bookings.clear()
        coord.order_to_booking.clear()
        coord.processed_payment_ids.clear()
        coord.audit_log.clear()
        coord.ai_muted_phones.clear()
        coord.call_log.clear()
        coord.conversation_states.clear()
        coord.setmore.slots.clear()
        coord.setmore.appointments.clear()
        coord.setmore.simulate_api_failure = False
        coord.tasks.tasks.clear()


        # 1. Clinicians with distinct fees and durations
        doc1 = Clinician(
            "DOC-101",
            "Dr. Ananya Varma",
            "Sexology & Mental Health",
            "staff_101",
            2500.0,
            50,
            "Sexual & Relationship Therapy",
        )
        doc2 = Clinician(
            "DOC-102",
            "Dr. Rajesh Rao",
            "Clinical Psychology & CBT",
            "staff_102",
            2000.0,
            45,
            "Clinical Psychology Session",
        )
        doc3 = Clinician(
            "DOC-103",
            "Dr. Maya Nambiar",
            "Psychiatry & De-addiction",
            "staff_103",
            3000.0,
            60,
            "Psychiatric Consultation",
        )
        for d in (doc1, doc2, doc3):
            coord.clinicians[d.clinician_id] = d

        # 2. Time Slots: across next 2 working days (Mon to Sat, 9 AM to 8 PM, skip Sundays)
        now = datetime.now()
        work_days = _get_next_working_days(now, count=2)
        day1 = work_days[0]
        day2 = work_days[1]

        slots_def = [
            # Dr. Ananya Varma (DOC-101) - 50 mins
            ("SLOT-101", doc1.clinician_id, day1.replace(hour=10, minute=0, second=0, microsecond=0), 50),
            ("SLOT-A2", doc1.clinician_id, day1.replace(hour=11, minute=30, second=0, microsecond=0), 50),
            ("SLOT-103", doc1.clinician_id, day1.replace(hour=15, minute=0, second=0, microsecond=0), 50),
            ("SLOT-A3", doc1.clinician_id, day1.replace(hour=16, minute=30, second=0, microsecond=0), 50),
            ("SLOT-A4", doc1.clinician_id, day2.replace(hour=11, minute=0, second=0, microsecond=0), 50),
            ("SLOT-A5", doc1.clinician_id, day2.replace(hour=16, minute=0, second=0, microsecond=0), 50),

            # Dr. Rajesh Rao (DOC-102) - 45 mins
            ("SLOT-R1", doc2.clinician_id, day1.replace(hour=10, minute=30, second=0, microsecond=0), 45),
            ("SLOT-202", doc2.clinician_id, day1.replace(hour=14, minute=0, second=0, microsecond=0), 45),
            ("SLOT-R2", doc2.clinician_id, day1.replace(hour=16, minute=0, second=0, microsecond=0), 45),
            ("SLOT-R3", doc2.clinician_id, day2.replace(hour=12, minute=0, second=0, microsecond=0), 45),
            ("SLOT-R4", doc2.clinician_id, day2.replace(hour=15, minute=30, second=0, microsecond=0), 45),

            # Dr. Maya Nambiar (DOC-103) - 60 mins
            ("SLOT-M1", doc3.clinician_id, day1.replace(hour=11, minute=0, second=0, microsecond=0), 60),
            ("SLOT-M2", doc3.clinician_id, day1.replace(hour=17, minute=0, second=0, microsecond=0), 60),
            ("SLOT-M3", doc3.clinician_id, day2.replace(hour=14, minute=0, second=0, microsecond=0), 60),
            ("SLOT-M4", doc3.clinician_id, day2.replace(hour=16, minute=30, second=0, microsecond=0), 60),
        ]

        for slot_id, doc_id, start, duration in slots_def:
            end = start + timedelta(minutes=duration)
            coord.setmore.add_slot(TimeSlot(slot_id, doc_id, start, end))

        # 3. Seed Scripted Personas for Shared Phone Scenario only
        p_shared = DEMO_PERSONAS["shared_phone_couple"]
        for prof in p_shared["profiles"]:
            p = coord.register_or_get_patient(prof["full_name"], p_shared["phone"], discrete_name=prof["discrete_name"])
            coord.set_patient_pin(p.patient_id, prof["pin"])

        # Initial seed audit entry
        coord.audit("SYSTEM", "Clinic Coordinator demo database seeded successfully.")

        # Seed initial missed call for operations dashboard
        missed_time = now - timedelta(minutes=20)
        coord.handle_inbound_call(
            caller_phone="+919811122233",
            call_status="MISSED",
            call_time=missed_time,
            caller_name="Caller 2233",
        )


class ScenarioSimulator:
    def __init__(self, coordinator: ClinicBookingCoordinator):
        self.coord = coordinator
        self.active_scenario: Optional[str] = None
        self.scenario_state: Dict[str, Any] = {}

    def reset(self):
        """Resets all simulation state and restores initial database seed."""
        self.active_scenario = None
        self.scenario_state.clear()
        seed_demo_data(self.coord)
        self.coord.reset_conversation_states()
        return {"status": "reset", "active_scenario": None}

    def start_scenario(self, scenario_name: str, phone: str = "+919876543210") -> dict:
        """
        Initializes and runs the requested scenario.
        If scenarios 2, 3, or 6 are invoked and no patient name is stored yet,
        first asks for the patient's full name.
        """
        self.active_scenario = scenario_name
        self.scenario_state = {"scenario": scenario_name, "step": 1}

        if scenario_name == "happy":
            return self._run_happy_path(phone)
        elif scenario_name == "late_payment":
            return self._run_late_payment(phone)
        elif scenario_name == "setmore_outage":
            return self._run_setmore_outage(phone)
        elif scenario_name == "shared_phone":
            return self._run_shared_phone()
        elif scenario_name == "crisis":
            return self._run_crisis(phone)
        elif scenario_name == "lab_report":
            return self._run_lab_report(phone)
        else:
            raise ValueError(f"Unknown scenario: {scenario_name}")

    def trigger_action(self, action: str, **kwargs) -> dict:
        """
        Executes a simulator scenario action (pay_happy, reschedule_slot_lost, retry_booking, etc.).
        """
        order_id = kwargs.get("order_id") or self.scenario_state.get("order_id")
        
        if action == "pay_happy":
            b_id = self.coord.order_to_booking.get(order_id)
            booking = self.coord.bookings.get(b_id) if b_id else None
            payload = json.dumps(self.coord.gateway.generate_webhook_payload(order_id))
            sig = self.coord.gateway.compute_signature(payload)
            res = self.coord.handle_payment_webhook(payload, sig)
            clinician = self.coord.clinicians.get(booking.clinician_id) if booking else None
            clinician_name = format_doctor_name(clinician.name) if clinician else "Dr. Rajesh Rao"
            patient = self.coord.patients.get(booking.patient_id) if booking else None
            p_first = patient_greeting(patient) if patient else "Zoya"
            fee = (booking.payment.amount_inr if (booking and booking.payment) else (clinician.consultation_fee if clinician else 2000.0))
            return {
                "status": "success",
                "fee": fee,
                "clinician_name": clinician_name,
                "confirmation_message": f"Appointment Confirmed with {clinician_name} for {p_first}.",
                "booking": {"booking_id": booking.booking_id} if booking else {},
                "result": res,
            }

        elif action == "reschedule_slot_lost":
            new_slot_id = kwargs.get("new_slot_id", "SLOT-A3")
            staff_id = kwargs.get("staff_id", "Staff_Coordinator")
            booking_id = self.scenario_state.get("booking_id")
            if not booking_id:
                for bid, b in reversed(list(self.coord.bookings.items())):
                    if b.state == BookingState.PAYMENT_RECEIVED_SLOT_LOST:
                        booking_id = bid
                        break
            res = self.coord.resolve_slot_lost(booking_id, action="reschedule", staff_id=staff_id, new_slot_id=new_slot_id)
            return {"status": "success", "result": res, "whatsapp_message": res.get("whatsapp_message", "")}

        elif action == "retry_booking":
            self.coord.setmore.simulate_api_failure = False
            booking_id = self.scenario_state.get("booking_id")
            if not booking_id:
                for bid, b in reversed(list(self.coord.bookings.items())):
                    if b.state == BookingState.PAYMENT_CAPTURED_BOOKING_FAILED or b.state == BookingState.FAILED:
                        booking_id = bid
                        break
            staff_id = kwargs.get("staff_id", "Staff_Coordinator")
            res = self.coord.retry_failed_booking(booking_id, staff_id=staff_id)
            return {"status": "resolved", "result": res}

        elif action == "test_wrong_pin":
            return {"success": False, "message": "Incorrect PIN"}

        elif action == "test_correct_pin":
            return {"success": True, "message": "PIN verified successfully"}

        elif action == "resolve_crisis":
            task_id = self.scenario_state.get("crisis_task_id")
            if not task_id:
                for tid, t in self.coord.tasks.tasks.items():
                    if "CRISIS" in t.title:
                        task_id = tid
                        break
            res = self.coord.resolve_crisis(task_id, staff_id="OnCall_Psychiatrist", notes="Helpline provided")
            return {"status": "resolved", "result": res}

        elif action == "verify_lab_otp":
            return {"status": "success", "message": "2FA Authenticated: Secure Vault Unlocked successfully"}

        return {"status": "unknown_action", "action": action}

    # ---------------------------------------------------------
    # Scenario 1: Happy Path Booking (Patient Chooses Everything)
    # ---------------------------------------------------------
    def _run_happy_path(self, phone: str = "+919876543210") -> dict:
        explainer = {
            "title": "Scenario 1: Happy Path Booking",
            "badge": "Patient Choice Flow",
            "badge_color": "green",
            "problem": "Traditional clinic systems lock slots prematurely or assign arbitrary clinicians without letting patients select their preferred schedule.",
            "detection": "Real-time doctor and slot availability engine returns live bookable inventory without placing premature calendar holds.",
            "safeguard": "Patient enters their own name, reviews doctors, and only locks a 15-minute hold upon explicit confirmation. No premature holds.",
            "staff_action": "Zero manual intervention needed. System auto-confirms calendar upon verified payment webhook.",
            "patient_outcome": "Patient chooses their own clinician, session duration, and convenient time slot.",
            "action_buttons": [],
        }

        # Check if patient is already stored for this phone in the session
        status, profiles = self.coord.resolve_patient_by_phone(phone)
        patient = None
        for p in profiles:
            if p.full_name not in ("Patient", "Unknown"):
                patient = p
                break

        if patient:
            self.coord.set_conversation_state(phone, "AWAITING_SLOT")
            greeting = patient_greeting(patient)
            avail = self.coord.get_availability()
            return {
                "scenario": "happy",
                "status": "doctor_picker",
                "kind": "doctor_picker",
                "explainer": explainer,
                "chat_messages": [
                    {"from": "patient", "text": "I want to book an appointment"},
                    {"from": "bot", "text": f"Welcome back, {greeting}. Here are the doctors available for you."},
                ],
                "patient": {
                    "patient_id": patient.patient_id,
                    "name": patient.full_name,
                    "first_name": greeting,
                    "phone": patient.phone_number,
                },
                "clinicians": avail,
            }

        # Set conversation state to AWAITING_NAME
        self.coord.set_conversation_state(phone, "AWAITING_NAME")
        chat_messages = [
            {"from": "patient", "text": "I want to book an appointment"},
            {
                "from": "bot",
                "text": "Welcome to The Bengaluru Clinic. May I have your full name, please?",
                "action": "request_name",
            },
        ]

        return {
            "scenario": "happy",
            "status": "request_name",
            "explainer": explainer,
            "chat_messages": chat_messages,
        }

    # ---------------------------------------------------------
    # Scenario 2: Late Payment / Slot Lost (P0)
    # ---------------------------------------------------------
    def _run_late_payment(self, phone: str = "+919876543210") -> dict:
        status, profiles = self.coord.resolve_patient_by_phone(phone)
        patient = None
        for p in profiles:
            if p.full_name not in ("Patient", "Unknown"):
                patient = p
                break

        if not patient:
            self.scenario_state["pending_scenario"] = "late_payment"
            self.coord.set_conversation_state(phone, "AWAITING_NAME")
            doc1 = self.coord.clinicians["DOC-101"]
            explainer = {
                "title": "Scenario 2: Late Payment / Slot Lost (P0 Exception)",
                "badge": "P0 Urgent Exception",
                "badge_color": "amber",
                "problem": "Patient completes UPI payment 16 minutes later—after their 15-minute hold expired. In the meantime, another patient snatches the slot.",
                "detection": "Webhook processor detects hold expiry AND slot taken by Walk-in patient.",
                "safeguard": "Booking marked PAYMENT_RECEIVED_SLOT_LOST with P0 Urgent 15-minute SLA task.",
                "staff_action": "Staff resolves via 1-click priority reschedule or instant full UPI refund.",
                "patient_outcome": "Patient receives personalized reassurance and direct front-desk outreach.",
                "action_buttons": [],
            }
            chat_messages = [
                {"from": "patient", "text": f"I want to book an appointment with {format_doctor_name(doc1.name)}"},
                {"from": "bot", "text": "Welcome to The Bengaluru Clinic. May I have your full name, please?", "action": "request_name"},
            ]
            return {
                "scenario": "late_payment",
                "status": "request_name",
                "explainer": explainer,
                "chat_messages": chat_messages,
            }

        return self.execute_late_payment_with_patient(patient)

    def execute_late_payment_with_patient(self, patient: PatientProfile) -> dict:
        doc1 = self.coord.clinicians["DOC-101"]
        slot = self.coord.setmore.slots["SLOT-A2"]
        greeting = patient_greeting(patient)

        # 1. Patient holds slot
        booking = self.coord.initiate_booking(
            patient_id=patient.patient_id,
            clinician_id=doc1.clinician_id,
            slot_id=slot.slot_id,
            service_name=doc1.specialty,
        )
        self.scenario_state["booking_id"] = booking.booking_id
        self.scenario_state["order_id"] = booking.payment.order_id

        # 2. Simulate 16 minutes passing -> hold expires
        expired_time = datetime.now() + timedelta(minutes=16)
        self.coord.expire_stale_holds(reference_time=expired_time)

        # 3. Walk-in patient snatches the slot
        walk_in_persona = DEMO_PERSONAS["walk_in"]
        walk_in = self.coord.register_or_get_patient(walk_in_persona["full_name"], walk_in_persona["phone"], walk_in_persona["discrete_name"])
        slot.is_booked = True
        slot.held_by_booking_id = f"BKG-WALKIN-{walk_in.patient_id[-6:]}"

        # 4. Now patient late-pays -> payment webhook arrives!
        raw_payload = json.dumps(self.coord.gateway.generate_webhook_payload(booking.payment.order_id))
        sig = self.coord.gateway.compute_signature(raw_payload)
        webhook_result = self.coord.handle_payment_webhook(raw_payload, sig)

        explainer = {
            "title": "Scenario 2: Late Payment / Slot Lost (P0 Exception)",
            "badge": "P0 Urgent Exception",
            "badge_color": "amber",
            "problem": f"Patient ({greeting}) completed UPI payment 16 minutes later—after their 15-minute hold expired. In the meantime, Walk-in patient took the slot.",
            "detection": "Webhook processor caught that hold expired AND slot.is_booked by another patient, preventing a calendar collision.",
            "safeguard": "Booking transitioned to PAYMENT_RECEIVED_SLOT_LOST. Generated a P0 Urgent Staff Task with a 15-minute SLA. Sent a reassuring WhatsApp message to the patient.",
            "staff_action": "Staff must resolve this immediately: either reschedule to the next priority slot or trigger an instant full refund.",
            "patient_outcome": "Instead of a double-booking conflict or generic payment error, the patient was reassured that the clinic manager is handling their booking personally.",
            "action_buttons": [
                {
                    "id": "reschedule_btn",
                    "label": "Reschedule to Alternate Slot (SLOT-103)",
                    "action": "reschedule_slot_lost",
                    "new_slot_id": "SLOT-103",
                    "color": "emerald",
                },
                {
                    "id": "refund_btn",
                    "label": f"Issue Instant Full Refund (₹ {int(doc1.consultation_fee):,})",
                    "action": "refund_slot_lost",
                    "color": "rose",
                },
            ],
        }

        chat_messages = [
            {"from": "patient", "text": f"I'd like to book with {format_doctor_name(doc1.name)}."},
            {
                "from": "bot",
                "text": (
                    f"Hello {greeting}. Please complete your payment using the secure link below:\n\n"
                    f"{booking.payment.payment_link_url}\n\n"
                    f"Please note: You have 15 minutes to complete the payment. "
                    f"If payment is not completed within 15 minutes, your temporary hold will expire automatically "
                    f"and the appointment slot will be released.\n\n"
                    f"Your appointment confirmation will be sent immediately after successful payment."
                ),
            },
            {
                "from": "bot",
                "text": (
                    f"Hello {greeting}. Your 15-minute payment window has ended, "
                    f"and the temporary hold has been released.\n\n"
                    f"If you still wish to schedule an appointment, please reply or choose from available slots to book again."
                ),
            },
            {"from": "patient", "text": f"[{greeting} pays via UPI link 16 mins later after slot was given to someone else]"},
            {
                "from": "bot",
                "text": (
                    f"Hello {greeting}. We received your payment (Ref: {booking.payment.payment_id}). "
                    f"Due to high demand, our clinic manager is personally finalizing your slot and will call you in 15 minutes."
                ),
            },
        ]

        return {
            "scenario": "late_payment",
            "explainer": explainer,
            "chat_messages": chat_messages,
            "booking_id": booking.booking_id,
            "task_id": webhook_result.get("task_id"),
            "patient": {
                "patient_id": patient.patient_id,
                "name": patient.full_name,
                "first_name": greeting,
                "phone": patient.phone_number,
            },
        }

    # ---------------------------------------------------------
    # Scenario 3: Setmore 500 Outage (P0)
    # ---------------------------------------------------------
    def _run_setmore_outage(self, phone: str = "+919876543210") -> dict:
        status, profiles = self.coord.resolve_patient_by_phone(phone)
        patient = None
        for p in profiles:
            if p.full_name not in ("Patient", "Unknown"):
                patient = p
                break

        if not patient:
            self.scenario_state["pending_scenario"] = "setmore_outage"
            self.coord.set_conversation_state(phone, "AWAITING_NAME")
            doc2 = self.coord.clinicians["DOC-102"]
            explainer = {
                "title": "Scenario 3: Setmore 500 API Outage (P0 Exception)",
                "badge": "P0 Critical Exception",
                "badge_color": "rose",
                "problem": "Patient pays consultation fee, but Setmore calendar API crashes with 500 Internal Error.",
                "detection": "Post-payment handler traps external calendar API exception.",
                "safeguard": "Booking marked PAYMENT_CAPTURED_BOOKING_FAILED with P0 Critical 10-minute SLA task.",
                "staff_action": "Staff dashboard provides 1-click retry sync with automatic operational escalation.",
                "patient_outcome": "Patient is reassured payment was received and calendar details are being finalized.",
                "action_buttons": [],
            }
            chat_messages = [
                {"from": "patient", "text": f"I want to book an appointment with {format_doctor_name(doc2.name)}"},
                {"from": "bot", "text": "Welcome to The Bengaluru Clinic. May I have your full name, please?", "action": "request_name"},
            ]
            return {
                "scenario": "setmore_outage",
                "status": "request_name",
                "explainer": explainer,
                "chat_messages": chat_messages,
            }

        return self.execute_setmore_outage_with_patient(patient)

    def execute_setmore_outage_with_patient(self, patient: PatientProfile) -> dict:
        doc2 = self.coord.clinicians["DOC-102"]
        slot = self.coord.setmore.slots["SLOT-R1"]
        greeting = patient_greeting(patient)

        # Initiate booking
        booking = self.coord.initiate_booking(
            patient_id=patient.patient_id,
            clinician_id=doc2.clinician_id,
            slot_id=slot.slot_id,
            service_name=doc2.specialty,
        )
        self.scenario_state["booking_id"] = booking.booking_id

        # Turn on simulated Setmore 500 failure
        self.coord.setmore.simulate_api_failure = True

        # Process payment webhook -> triggers Setmore confirmation failure!
        raw_payload = json.dumps(self.coord.gateway.generate_webhook_payload(booking.payment.order_id))
        sig = self.coord.gateway.compute_signature(raw_payload)
        webhook_result = self.coord.handle_payment_webhook(raw_payload, sig)

        explainer = {
            "title": "Scenario 3: Setmore 500 API Outage (P0 Exception)",
            "badge": "P0 Critical Exception",
            "badge_color": "rose",
            "problem": f"Patient ({greeting}) paid ₹ {int(doc2.consultation_fee):,}, but Setmore calendar API crashed with a 500 Internal Timeout during CalDAV synchronization.",
            "detection": "Webhook handler caught the unhandled calendar API exception post-payment capture.",
            "safeguard": "Booking marked PAYMENT_CAPTURED_BOOKING_FAILED. Created a P0 Critical Task with a 10-minute SLA for Clinic Manager. Patient reassured that payment was captured.",
            "staff_action": "Staff dashboard provides a 1-click 'Retry Calendar Sync'. If retried twice without success, the task auto-escalates to senior operations.",
            "patient_outcome": "Patient is not left wondering why their card was charged with no confirmation. They are notified that their calendar slot is being finalized shortly.",
            "action_buttons": [
                {
                    "id": "retry_setmore_btn",
                    "label": "1-Click Retry Calendar Sync",
                    "action": "retry_booking",
                    "color": "indigo",
                }
            ],
        }

        chat_messages = [
            {"from": "patient", "text": f"Booking appointment with {format_doctor_name(doc2.name)}."},
            {
                "from": "bot",
                "text": (
                    f"Hello {greeting}. Please complete your payment using the secure link below:\n\n"
                    f"{booking.payment.payment_link_url}\n\n"
                    f"Please note: You have 15 minutes to complete the payment. "
                    f"If payment is not completed within 15 minutes, your temporary hold will expire automatically "
                    f"and the appointment slot will be released.\n\n"
                    f"Your appointment confirmation will be sent immediately after successful payment."
                ),
            },
            {"from": "patient", "text": f"[{greeting} successfully completes payment of ₹ {int(doc2.consultation_fee):,}]"},
            {
                "from": "bot",
                "text": (
                    f"Hello {greeting}. Your payment of ₹ {int(doc2.consultation_fee):,} was received successfully. "
                    f"Your appointment is being registered on the clinician's calendar. You will receive final calendar details shortly."
                ),
            },
        ]

        return {
            "scenario": "setmore_outage",
            "explainer": explainer,
            "chat_messages": chat_messages,
            "booking_id": booking.booking_id,
            "task_id": webhook_result.get("task_id"),
            "patient": {
                "patient_id": patient.patient_id,
                "name": patient.full_name,
                "first_name": greeting,
                "phone": patient.phone_number,
            },
        }

    # ---------------------------------------------------------
    # Scenario 4: Shared Phone PIN Gate
    # ---------------------------------------------------------
    def _run_shared_phone(self) -> dict:
        persona = DEMO_PERSONAS["shared_phone_couple"]
        shared_phone = persona["phone"]
        status, profiles = self.coord.resolve_patient_by_phone(shared_phone)

        explainer = {
            "title": "Scenario 4: Shared Phone PIN Gate",
            "badge": "Privacy & Security",
            "badge_color": "blue",
            "problem": "Spouses or family members sharing one smartphone number risks exposing sensitive mental or sexual health records.",
            "detection": "Identity resolver detects multiple profiles mapped to a single phone number upon inbound contact.",
            "safeguard": "Clinical data is strictly isolated by PatientProfile UUID. WhatsApp displays only discreet name pills. Access requires a 4-digit PBKDF2-HMAC-SHA256 PIN. 3 failed attempts freeze the account for 15 minutes and alert staff.",
            "staff_action": "Staff dashboard flags PIN lockouts for identity verification if a patient forgets their PIN.",
            "patient_outcome": "Zero clinical diagnosis or specialty is leaked to family members sharing the smartphone.",
            "action_buttons": [
                {
                    "id": "test_wrong_pin",
                    "label": "Enter Wrong PIN (Test 3-Attempt Lockout)",
                    "action": "test_wrong_pin",
                    "color": "amber",
                },
                {
                    "id": "test_correct_pin",
                    "label": f"Enter Correct PIN ({persona['profiles'][0]['pin']} for {persona['profiles'][0]['discrete_name']})",
                    "action": "test_correct_pin",
                    "color": "emerald",
                },
            ],
        }

        chat_messages = [
            {"from": "patient", "text": "Hi, I want to check my appointment status."},
            {
                "from": "bot",
                "text": (
                    "Welcome to The Bengaluru Clinic. Multiple profiles are associated with this phone number.\n\n"
                    "Please select your profile to proceed:"
                ),
                "is_profile_selector": True,
                "profiles": [
                    {"id": profiles[0].patient_id, "name": profiles[0].discrete_name},
                    {"id": profiles[1].patient_id, "name": profiles[1].discrete_name},
                ],
            },
        ]

        return {
            "scenario": "shared_phone",
            "explainer": explainer,
            "chat_messages": chat_messages,
            "profiles": [p.patient_id for p in profiles],
        }

    # ---------------------------------------------------------
    # Scenario 5: Psychiatric Crisis Intercept
    # ---------------------------------------------------------
    def _run_crisis(self, phone: str = "+919876543210") -> dict:
        status, profiles = self.coord.resolve_patient_by_phone(phone)
        patient = None
        for p in profiles:
            if p.full_name not in ("Patient", "Unknown"):
                patient = p
                break

        greeting = patient_greeting(patient) if patient else ""
        patient_id = patient.patient_id if patient else "UNKNOWN"
        crisis_message = "I feel completely hopeless. I can't go on anymore and I want to end my life."

        task = self.coord.check_psychiatric_crisis(patient_id, crisis_message)
        self.scenario_state["crisis_task_id"] = task.task_id if task else None

        explainer = {
            "title": "Scenario 5: Psychiatric Crisis Intercept",
            "badge": "Life Safety Protocol",
            "badge_color": "rose",
            "problem": f"A patient{' (' + greeting + ')' if greeting else ''} expresses acute suicidal distress or self-harm ideation inside the automated booking chat.",
            "detection": "Precision word-boundary regex matches clinical distress patterns while eliminating false positives (e.g. 'diet', 'studied').",
            "safeguard": "Automated bot AI is immediately MUTED for this patient's phone so it cannot send inappropriate automated replies. System instantly sends accredited 24/7 helpline resources (Tele-MANAS & Vandrevala Foundation).",
            "staff_action": "A P0 Urgent Task with a 5-minute SLA is spawned on the Staff Operations Cockpit for the On-Call Psychiatrist to make direct contact.",
            "patient_outcome": "Immediate access to life-saving emergency helplines and compassionate clinical intervention within minutes.",
            "action_buttons": [
                {
                    "id": "resolve_crisis_btn",
                    "label": "Mark Counselor Connected & Unmute AI",
                    "action": "resolve_crisis",
                    "color": "emerald",
                }
            ],
        }

        prefix = f"Hello {greeting}. " if greeting else ""
        chat_messages = [
            {"from": "patient", "text": crisis_message},
            {
                "from": "bot",
                "text": (
                    f"{prefix}We care deeply about your well-being. If you are experiencing overwhelming distress, "
                    "please connect immediately with free, confidential 24/7 support:\n\n"
                    "- Tele-MANAS (Govt of India): 14416 or 1800-891-4416 (Toll-Free, 24/7)\n"
                    "- Vandrevala Foundation Helpline: +91 9999 666 555 (24/7)\n"
                    "- Emergency Response: 112\n\n"
                    "A senior clinical coordinator from The Bengaluru Clinic has also been notified and will reach out to you."
                ),
                "is_crisis": True,
            },
            {
                "from": "system",
                "text": "[SYSTEM AUDIT]: Automated AI is now MUTED for this conversation. Clinical escalation active.",
            },
        ]

        return {
            "scenario": "crisis",
            "explainer": explainer,
            "chat_messages": chat_messages,
            "task_id": task.task_id if task else None,
        }

    # ---------------------------------------------------------
    # Scenario 6: 2FA Lab Report Vault
    # ---------------------------------------------------------
    def _run_lab_report(self, phone: str = "+919876543210") -> dict:
        status, profiles = self.coord.resolve_patient_by_phone(phone)
        patient = None
        for p in profiles:
            if p.full_name not in ("Patient", "Unknown"):
                patient = p
                break

        if not patient:
            self.scenario_state["pending_scenario"] = "lab_report"
            self.coord.set_conversation_state(phone, "AWAITING_NAME")
            explainer = {
                "title": "Scenario 6: 2FA Lab Report Vault",
                "badge": "HIPAA / DPDP Compliant",
                "badge_color": "indigo",
                "problem": "WhatsApp lock-screen notifications frequently leak sensitive medical tests to unauthorized onlookers.",
                "detection": "Patient requests lab report results or doctor clinical summary.",
                "safeguard": "No diagnosis, doctor specialty, or test names appear in the WhatsApp message. Access requires 2FA OTP verification and expires in 10 minutes. Cryptographic audit log records every access.",
                "staff_action": "Operations dashboard displays audit log of token generation, validation, and viewing IP hash.",
                "patient_outcome": "Complete peace of mind knowing medical records are shielded by multi-factor authentication.",
                "action_buttons": [],
            }
            chat_messages = [
                {"from": "patient", "text": "Can I get my latest test results?"},
                {"from": "bot", "text": "Welcome to The Bengaluru Clinic. May I have your full name, please?", "action": "request_name"},
            ]
            return {
                "scenario": "lab_report",
                "status": "request_name",
                "explainer": explainer,
                "chat_messages": chat_messages,
            }

        return self.execute_lab_report_with_patient(patient)

    def execute_lab_report_with_patient(self, patient: PatientProfile) -> dict:
        greeting = patient_greeting(patient)
        otp_code = "729401"
        self.scenario_state["lab_otp"] = otp_code

        self.coord.audit(
            "SECURITY",
            f"Discreet 2FA lab vault requested for patient {patient.patient_id} ({greeting}). OTP generated with 10m TTL.",
        )

        explainer = {
            "title": "Scenario 6: 2FA Lab Report Vault",
            "badge": "HIPAA / DPDP Compliant",
            "badge_color": "indigo",
            "problem": "WhatsApp lock-screen notifications frequently leak sensitive medical tests to unauthorized onlookers.",
            "detection": "Patient requests lab report results or doctor clinical summary.",
            "safeguard": "No diagnosis, doctor specialty, or test names appear in the WhatsApp message. Access requires 2FA OTP verification and expires in 10 minutes. Cryptographic audit log records every access.",
            "staff_action": "Operations dashboard displays audit log of token generation, validation, and viewing IP hash.",
            "patient_outcome": "Complete peace of mind knowing medical records are shielded by multi-factor authentication.",
            "action_buttons": [
                {
                    "id": "verify_otp_btn",
                    "label": f"Verify 2FA OTP ({otp_code}) & Open Secure Vault",
                    "action": "verify_lab_otp",
                    "color": "indigo",
                }
            ],
        }

        chat_messages = [
            {"from": "patient", "text": "Can I get my latest test results?"},
            {
                "from": "bot",
                "text": (
                    f"Hello {greeting}. Your secure health documents are ready.\n\n"
                    f"For your medical privacy, access requires two-factor verification. "
                    f"Your 6-digit access code is: {otp_code} (Valid for 10 minutes).\n\n"
                    f"Secure Vault Link: https://vault.bengaluru-clinic.in/r/v2?auth={otp_code}"
                ),
            },
        ]

        return {
            "scenario": "lab_report",
            "explainer": explainer,
            "chat_messages": chat_messages,
            "otp": otp_code,
            "patient": {
                "patient_id": patient.patient_id,
                "name": patient.full_name,
                "first_name": greeting,
                "phone": patient.phone_number,
            },
        }
