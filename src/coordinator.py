"""
Central Clinic Booking Coordinator and State Machine.
Handles shared-phone resolution, TTL slot reservations, cryptographic webhook verification,
idempotency, automated Setmore confirmation, P0 failure exceptions, crisis intercept,
PBKDF2 PIN authentication, and tamper-evident SHA256 audit logging.
"""

from datetime import datetime, timedelta
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
import sys
import threading
from typing import Dict, List, Optional, Tuple, Any
import uuid

# Ensure root directory is in sys.path when run directly
root_dir = Path(__file__).resolve().parent.parent
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
from src.mock_services import (
    MockPaymentGateway,
    MockSetmoreService,
    MockWhatsAppService,
    TaskManager,
)
import config
from src.pdf_generator import get_next_invoice_number, generate_tax_invoice_pdf
from src.mailer import enqueue_email, render_email, mask_email


CRISIS_PATTERN = re.compile(
    r"\b(suicide|suicidal|kill myself|end my life|ending my life|want to die|hang myself|self harm|self-harm|can't go on|cannot go on)\b",
    re.IGNORECASE,
)


def patient_greeting(patient: Any) -> str:
    """
    Returns the first name / discrete name for patient-facing greetings.
    Single source of truth across all messages, notifications, and tasks.
    """
    if not patient:
        return ""
    if isinstance(patient, str):
        trimmed = patient.strip()
        return trimmed.split()[0] if trimmed else ""
    discrete = getattr(patient, "discrete_name", None)
    if discrete and str(discrete).strip():
        return str(discrete).strip()
    full = getattr(patient, "full_name", None)
    if full and str(full).strip():
        return str(full).strip().split()[0]
    return ""


def _mask_phone(phone: str) -> str:
    """Masks phone number for privacy in audit logs: e.g. +91 98*** **210."""
    if not phone:
        return "UNKNOWN"
    cleaned = phone.strip()
    if len(cleaned) <= 6:
        return cleaned
    return f"{cleaned[:4]}****{cleaned[-4:]}"


def _format_patient_task_identity(patient: Any, phone: Optional[str] = None) -> str:
    """Formats patient identity for staff task titles and descriptions: FirstName (****Last4)."""
    first_name = patient_greeting(patient) or "Patient"
    phone_str = getattr(patient, "phone_number", None) or phone or ""
    last4 = phone_str.strip()[-4:] if len(phone_str.strip()) >= 4 else "0000"
    return f"{first_name} (****{last4})"


class ClinicBookingCoordinator:
    def __init__(
        self,
        setmore_service: MockSetmoreService,
        payment_gateway: MockPaymentGateway,
        whatsapp_service: MockWhatsAppService,
        task_manager: TaskManager,
        slot_ttl_minutes: int = 15,
    ):
        self.setmore = setmore_service
        self.gateway = payment_gateway
        self.whatsapp = whatsapp_service
        self.tasks = task_manager
        self.slot_ttl_minutes = slot_ttl_minutes

        # Concurrency Lock
        self.lock = threading.RLock()

        # Internal repositories
        self.patients: Dict[str, PatientProfile] = {}          # patient_id -> PatientProfile
        self.phone_to_patients: Dict[str, List[str]] = {}      # phone -> [patient_id, ...]
        self.clinicians: Dict[str, Clinician] = {}            # clinician_id -> Clinician
        self.bookings: Dict[str, BookingRecord] = {}          # booking_id -> BookingRecord
        self.order_to_booking: Dict[str, str] = {}            # order_id -> booking_id
        self.processed_payment_ids: set = set()               # Idempotency cache
        self.active_otps: Dict[str, dict] = {}                # patient_id -> OTP record

        # Security & Audit
        self.audit_log: List[AuditEntry] = []
        self.ai_muted_phones: set = set()                     # Phones muted during clinical crisis
        self.call_log: List[dict] = []                        # Telephony log
        self.conversation_states: Dict[str, str] = {}         # phone -> "IDLE" | "AWAITING_NAME" | "AWAITING_SLOT"

    def _get_recipient_email(self, booking: Optional[BookingRecord], patient: Optional[PatientProfile]) -> Optional[str]:
        """Resolves recipient email from booking receipt_email or patient profile."""
        if booking and getattr(booking, "receipt_email", None):
            return booking.receipt_email.strip().lower()
        if patient and getattr(patient, "email", None):
            return patient.email.strip().lower()
        return None

    # ---------------------------------------------------------
    # Conversation State Management & Validation
    # ---------------------------------------------------------
    def get_conversation_state(self, phone: str) -> str:
        with self.lock:
            return self.conversation_states.get(phone, "IDLE")

    def set_conversation_state(self, phone: str, state: str):
        with self.lock:
            self.conversation_states[phone] = state

    def reset_conversation_states(self):
        with self.lock:
            self.conversation_states.clear()

    @staticmethod
    def validate_patient_name(name: str) -> bool:
        """
        Validates typed patient name: 2 to 60 characters, letters (including Unicode),
        spaces, dots, apostrophes, hyphens only. Must contain at least one letter.
        """
        if not name or not isinstance(name, str):
            return False
        trimmed = name.strip()
        if len(trimmed) < 2 or len(trimmed) > 60:
            return False
        return any(c.isalpha() for c in trimmed) and all(c.isalpha() or c in " .'-" for c in trimmed)

    @staticmethod
    def _format_slot_label(dt: datetime) -> str:
        now = datetime.now()
        if dt.date() == (now + timedelta(days=1)).date():
            return f"Tomorrow, {dt.strftime('%I:%M %p').lstrip('0')}"
        elif dt.date() == now.date():
            return f"Today, {dt.strftime('%I:%M %p').lstrip('0')}"
        return f"{dt.strftime('%a %d %b, %I:%M %p').replace(' 0', ' ')}"

    def get_availability(self) -> List[dict]:
        """
        Returns real-time availability: clinicians, service labels, fees,
        and currently available time slots sorted chronologically.
        Does NOT expose internal keys such as setmore_staff_key.
        """
        with self.lock:
            result = []
            for clinician_id, c in sorted(self.clinicians.items(), key=lambda item: item[1].name):
                avail_slots = []
                for s in sorted(self.setmore.slots.values(), key=lambda s: s.start_time):
                    if s.clinician_id == clinician_id and self.setmore.check_availability(s.slot_id):
                        avail_slots.append({
                            "slot_id": s.slot_id,
                            "start_iso": s.start_time.isoformat(),
                            "end_iso": s.end_time.isoformat(),
                            "label": self._format_slot_label(s.start_time),
                        })
                result.append({
                    "clinician_id": c.clinician_id,
                    "display_name": format_doctor_name(c.name),
                    "service_label": getattr(c, "service_label", "") or c.specialty,
                    "specialty": c.specialty,
                    "duration_minutes": c.duration_minutes,
                    "fee": float(c.consultation_fee),
                    "slots": avail_slots,
                })
            return result

    # ---------------------------------------------------------
    # 0. Cryptographic Tamper-Evident Audit Ledger
    # ---------------------------------------------------------
    def audit(self, category: str, message: str) -> AuditEntry:
        """
        Appends an immutable entry to the SHA256 audit hash chain.
        """
        with self.lock:
            seq = len(self.audit_log) + 1
            now_iso = datetime.now().isoformat()
            prev_hash = self.audit_log[-1].hash if self.audit_log else "0" * 64
            entry_str = f"{prev_hash}|{seq}|{now_iso}|{category}|{message}"
            entry_hash = hashlib.sha256(entry_str.encode("utf-8")).hexdigest()
            entry = AuditEntry(
                seq=seq,
                timestamp=now_iso,
                category=category,
                message=message,
                prev_hash=prev_hash,
                hash=entry_hash,
            )
            self.audit_log.append(entry)
            return entry

    def verify_audit_chain(self) -> Tuple[bool, Optional[int]]:
        """
        Verifies the cryptographic SHA-256 integrity of the audit log chain.
        Returns (True, None) if intact, or (False, broken_seq) if tampered.
        """
        with self.lock:
            prev = "0" * 64
            for entry in self.audit_log:
                if entry.prev_hash != prev:
                    return False, entry.seq
                recomputed = hashlib.sha256(
                    f"{entry.prev_hash}|{entry.seq}|{entry.timestamp}|{entry.category}|{entry.message}".encode("utf-8")
                ).hexdigest()
                if entry.hash != recomputed:
                    return False, entry.seq
                prev = entry.hash
            return True, None

    # ---------------------------------------------------------
    # 2FA OTP Generation & Verification (5m Expiry, Max 3 Attempts)
    # ---------------------------------------------------------
    def generate_otp(self, patient_id: str, ttl_minutes: int = 5) -> str:
        """
        Generates a cryptographically random 6-digit OTP with 5-minute expiry and max 3 attempts.
        """
        with self.lock:
            otp = f"{secrets.randbelow(1_000_000):06d}"
            now = datetime.now()
            self.active_otps[patient_id] = {
                "otp": otp,
                "expires_at": now + timedelta(minutes=ttl_minutes),
                "attempts": 0,
                "max_attempts": 3,
                "verified": False,
            }
            self.audit("SECURITY", f"6-digit 2FA OTP generated for patient {patient_id} (TTL: {ttl_minutes}m)")
            return otp

    def verify_otp(self, patient_id: str, entered_otp: str) -> Tuple[bool, str]:
        """
        Verifies 6-digit OTP with 5-minute expiry and max 3 attempts.
        """
        with self.lock:
            record = self.active_otps.get(patient_id)
            if not record:
                return False, "No active OTP found. Please request a new code."

            now = datetime.now()
            if now > record["expires_at"]:
                return False, "OTP has expired. Please request a new code."

            if record["attempts"] >= record["max_attempts"]:
                return False, "Maximum OTP attempts exceeded. Please request a new code."

            record["attempts"] += 1
            if not hmac.compare_digest(record["otp"], entered_otp.strip()):
                remaining = record["max_attempts"] - record["attempts"]
                if remaining <= 0:
                    return False, "Incorrect OTP. Maximum attempts exceeded. Code invalidated."
                return False, f"Incorrect OTP. {remaining} attempt(s) remaining."

            record["verified"] = True
            self.audit("SECURITY", f"OTP verified successfully for patient {patient_id}")
            return True, "OTP verified successfully."

    @staticmethod
    def calculate_missed_call_sla(call_time: datetime) -> Tuple[int, datetime, str]:
        """
        Calculates missed call callback SLA:
        - Working hours (09:00 - 20:00): 30 minutes SLA assigned to FrontDesk_Lead.
        - After hours / overnight (>= 20:00 or < 09:00): SLA until next 09:30 AM assigned to Morning_Receptionist.
        Returns (sla_minutes, due_date, assigned_to).
        """
        is_after_hours = call_time.hour >= 20 or call_time.hour < 9
        if is_after_hours:
            due_date = datetime(call_time.year, call_time.month, call_time.day, 9, 30)
            if call_time.hour >= 20:
                due_date += timedelta(days=1)
            sla_minutes = max(1, int((due_date - call_time).total_seconds() / 60))
            assigned_to = "Morning_Receptionist"
        else:
            due_date = call_time + timedelta(minutes=30)
            sla_minutes = 30
            assigned_to = "FrontDesk_Lead"
        return sla_minutes, due_date, assigned_to

    # ---------------------------------------------------------
    # 1. Patient Profile & Shared Phone Disambiguation
    # ---------------------------------------------------------
    def register_or_get_patient(
        self,
        full_name: str,
        phone_number: str,
        discrete_name: Optional[str] = None,
        email: Optional[str] = None,
    ) -> PatientProfile:
        """
        Registers a new patient or retrieves by exact identity.
        Supports multiple distinct profiles on the same phone number.
        """
        with self.lock:
            existing_ids = self.phone_to_patients.get(phone_number, [])
            for pid in existing_ids:
                p = self.patients.get(pid)
                if p and p.full_name.strip().lower() == full_name.strip().lower():
                    return p

            first_name = discrete_name or full_name.strip().split()[0]
            profile = PatientProfile(
                full_name=full_name.strip(),
                phone_number=phone_number.strip(),
                discrete_name=first_name,
                email=email,
            )
            self.patients[profile.patient_id] = profile
            if phone_number not in self.phone_to_patients:
                self.phone_to_patients[phone_number] = []
            self.phone_to_patients[phone_number].append(profile.patient_id)

            self.audit(
                "SYSTEM",
                f"Patient profile registered: {profile.patient_id} ({profile.discrete_name}) on {_mask_phone(phone_number)}",
            )
            return profile

    def resolve_patient_by_phone(self, phone_number: str) -> Tuple[str, List[PatientProfile]]:
        """
        Returns resolution status: 'SINGLE', 'MULTIPLE_PROFILES', or 'NOT_FOUND'.
        Guarantees clinical record separation on shared family phones.
        """
        with self.lock:
            pids = self.phone_to_patients.get(phone_number, [])
            if not pids:
                return "NOT_FOUND", []
            if len(pids) == 1:
                return "SINGLE", [self.patients[pids[0]]]
            return "MULTIPLE_PROFILES", [self.patients[pid] for pid in pids]

    # ---------------------------------------------------------
    # 1b. PIN Security for Shared Phones (PBKDF2-HMAC-SHA256)
    # ---------------------------------------------------------
    def set_patient_pin(self, patient_id: str, pin: str):
        """
        Sets a 4-digit PIN for a patient using PBKDF2-HMAC-SHA256 with 100,000 iterations.
        """
        with self.lock:
            patient = self.patients.get(patient_id)
            if not patient:
                raise ValueError(f"Patient {patient_id} not found")
            salt = secrets.token_hex(16)
            key = hashlib.pbkdf2_hmac("sha256", pin.strip().encode("utf-8"), salt.encode("utf-8"), 100_000)
            patient.pin_salt = salt
            patient.pin_hash = key.hex()
            patient.failed_pin_attempts = 0
            patient.locked_until = None
            self.audit("SECURITY", f"PIN set for patient {patient_id}")

    def verify_patient_pin(self, patient_id: str, pin: str) -> Tuple[bool, str]:
        """
        Verifies patient PIN. Enforces 3-attempt lockout with 15-minute freeze and P1 task.
        """
        with self.lock:
            patient = self.patients.get(patient_id)
            if not patient:
                return False, f"Patient {patient_id} not found"

            now = datetime.now()
            if patient.locked_until and now < patient.locked_until:
                mins_left = max(1, int((patient.locked_until - now).total_seconds() / 60))
                return False, f"Account locked for security. Please try again in {mins_left} minutes or contact reception."

            if not patient.pin_hash or not patient.pin_salt:
                return True, "No PIN set"

            key = hashlib.pbkdf2_hmac(
                "sha256",
                pin.strip().encode("utf-8"),
                patient.pin_salt.encode("utf-8"),
                100_000,
            )
            candidate_hash = key.hex()

            if hmac.compare_digest(patient.pin_hash, candidate_hash):
                patient.failed_pin_attempts = 0
                patient.locked_until = None
                self.audit("SECURITY", f"PIN verified successfully for patient {patient_id}")
                return True, "PIN verified successfully."

            # Failed attempt
            patient.failed_pin_attempts += 1
            if patient.failed_pin_attempts >= 3:
                patient.locked_until = now + timedelta(minutes=15)
                self.tasks.create_task(
                    patient_id=patient.patient_id,
                    title=f"PIN Brute-Force Lockout: {_format_patient_task_identity(patient)}",
                    description=(
                        f"Patient {_format_patient_task_identity(patient)} "
                        f"reached 3 consecutive failed PIN attempts. Profile locked for 15 minutes."
                    ),
                    priority=TaskPriority.P1_HIGH,
                    sla_minutes=15,
                    assigned_to="FrontDesk_Lead",
                )
                self.audit("SECURITY", f"PIN brute-force lockout triggered for patient {patient_id}")
                return False, "Too many failed attempts. Profile locked for 15 minutes for your security. Staff notified."

            remaining = 3 - patient.failed_pin_attempts
            self.audit("SECURITY", f"Failed PIN attempt for patient {patient_id}. {remaining} remaining.")
            return False, f"Incorrect PIN. {remaining} attempt(s) remaining."

    # ---------------------------------------------------------
    # 2. Slot Holding & Payment Request Flow
    # ---------------------------------------------------------
    def initiate_booking(
        self,
        patient_id: str,
        clinician_id: str,
        slot_id: str,
        service_name: str,
        mode: str = "IN_PERSON",
    ) -> BookingRecord:
        with self.lock:
            patient = self.patients.get(patient_id)
            if not patient:
                raise ValueError(f"Patient {patient_id} not found")

            clinician = self.clinicians.get(clinician_id)
            if not clinician:
                raise ValueError(f"Clinician {clinician_id} not found")

            # 1. Validate requested slot exists and is available
            slot = self.setmore.slots.get(slot_id)
            if not slot:
                raise ValueError(f"Requested appointment slot {slot_id} does not exist in Setmore.")
            if slot.clinician_id != clinician_id:
                raise ValueError(f"Requested appointment slot {slot_id} does not belong to clinician {clinician_id}.")
            if not self.setmore.check_availability(slot_id):
                raise RuntimeError("Selected time slot is already held or booked. Please pick another slot.")

            # Create booking record
            booking = BookingRecord(
                patient_id=patient_id,
                clinician_id=clinician_id,
                slot_id=slot_id,
                service_name=service_name,
                mode=mode,
                state=BookingState.INITIATED,
            )
            self.bookings[booking.booking_id] = booking

            # 2 & 3. Create a temporary appointment hold lasting exactly 15 minutes
            hold_success = self.setmore.hold_slot(
                slot_id=slot_id,
                booking_id=booking.booking_id,
                ttl_minutes=self.slot_ttl_minutes,
            )
            if not hold_success:
                booking.state = BookingState.CANCELLED
                booking.cancellation_reason = "Slot no longer available"
                raise RuntimeError("Selected time slot is already held or booked. Please pick another slot.")

            booking.state = BookingState.SLOT_HELD
            booking.hold_expires_at = datetime.now() + timedelta(minutes=self.slot_ttl_minutes)

            # 4. Generate payment link using payment gateway integration
            payment = self.gateway.create_order(
                booking_id=booking.booking_id,
                amount_inr=clinician.consultation_fee,
                patient_phone=patient.phone_number,
            )
            booking.payment = payment
            booking.state = BookingState.PAYMENT_PENDING
            self.order_to_booking[payment.order_id] = booking.booking_id

            # 5. Send discreet payment link over WhatsApp (Strictly NO slot day/time shown)
            greeting = patient_greeting(patient)
            prefix = f"Hello {greeting}. " if greeting else ""
            message = (
                f"{prefix}Please complete your payment using the secure link below:\n\n"
                f"{payment.payment_link_url}\n\n"
                f"Please note: You have {self.slot_ttl_minutes} minutes to complete the payment. "
                f"If payment is not completed within {self.slot_ttl_minutes} minutes, your temporary hold will expire automatically "
                f"and the appointment slot will be released.\n\n"
                f"Your appointment confirmation will be sent immediately after successful payment."
            )
            self.whatsapp.send_discreet_message(patient.phone_number, message, message_type="PAYMENT_REQUEST")

            self.audit(
                "BOOKING",
                f"Hold created (TTL: {self.slot_ttl_minutes}m) for booking {booking.booking_id}. Payment link sent.",
            )
            return booking

    # ---------------------------------------------------------
    # 2b. Backend 15-Minute Expiry Mechanism (Sweep & Release)
    # ---------------------------------------------------------
    def expire_stale_holds(self, reference_time: Optional[datetime] = None) -> List[BookingRecord]:
        """
        Backend 15-minute TTL expiry sweep.
        Releases slot back into open inventory and notifies the patient.
        Never mentions slot day/time in expiry notification.
        """
        with self.lock:
            now = reference_time or datetime.now()
            expired_list: List[BookingRecord] = []

            for booking in self.bookings.values():
                if booking.state in (BookingState.SLOT_HELD, BookingState.PAYMENT_PENDING):
                    if booking.hold_expires_at and now >= booking.hold_expires_at:
                        booking.state = BookingState.HOLD_EXPIRED
                        self.setmore.release_hold(booking.slot_id)
                        expired_list.append(booking)

                        patient = self.patients.get(booking.patient_id)
                        clinician = self.clinicians.get(booking.clinician_id)
                        doc_name = format_doctor_name(clinician.name if clinician else "")

                        if patient:
                            greeting = patient_greeting(patient)
                            expiry_msg = (
                                f"Hello {greeting}. Your 15-minute payment window has ended, "
                                f"and the temporary hold has been released.\n\n"
                                f"If you still wish to schedule an appointment, please reply or choose from available slots to book again."
                            )
                            self.whatsapp.send_discreet_message(
                                patient.phone_number,
                                expiry_msg,
                                message_type="HOLD_EXPIRED",
                            )

                        # Gentle hold expired email
                        try:
                            recip_email = self._get_recipient_email(booking, patient)
                            if recip_email:
                                html_b, text_b = render_email(
                                    template_name="hold_expired",
                                    subject="The Bengaluru Clinic · Slot Reservation Notice",
                                    header_title="Slot Reservation Notice",
                                    header_subtitle="Your 15-minute reservation window has ended",
                                    context={
                                        "patient_first_name": patient_greeting(patient),
                                    }
                                )
                                enqueue_email(
                                    to_email=recip_email,
                                    template="hold_expired",
                                    subject="The Bengaluru Clinic · Slot Reservation Notice",
                                    html_body=html_b,
                                    text_body=text_b,
                                    dedupe_key=f"hold_expired_{booking.booking_id}",
                                )
                                self.audit("EMAIL", f"Patient {patient.patient_id}: Hold expired email enqueued for {mask_email(recip_email)}")
                        except Exception as email_err:
                            self.audit("EMAIL", f"Hold expired email error: {str(email_err)}")

                        self.audit(
                            "BOOKING",
                            f"Hold expired for booking {booking.booking_id}. Slot {booking.slot_id} released.",
                        )

            return expired_list

    # ---------------------------------------------------------
    # 3. Webhook Handling & State Transitions
    # ---------------------------------------------------------
    def handle_payment_webhook(self, raw_payload_body: str, signature: str) -> dict:
        """
        Processes verified webhook from Payment Gateway.
        Enforces cryptographic verification, idempotency, amount matching,
        graceful late payment handling, and Setmore error capture.
        """
        with self.lock:
            # 1. Cryptographic HMAC check
            if not self.gateway.verify_webhook_signature(raw_payload_body, signature):
                task = self.tasks.create_task(
                    patient_id="SYSTEM",
                    title="SECURITY: Invalid Webhook Signature Rejected",
                    description="Received untrusted webhook payload with invalid HMAC signature.",
                    priority=TaskPriority.P0_URGENT,
                    sla_minutes=15,
                    assigned_to="Security_Lead",
                )
                self.audit("SECURITY", "Invalid webhook signature rejected.")
                return {"status": "error", "message": "Invalid webhook signature", "task_id": task.task_id}

            try:
                data = json.loads(raw_payload_body)
            except Exception as e:
                task = self.tasks.create_task(
                    patient_id="SYSTEM",
                    title="SECURITY: Malformed Webhook JSON",
                    description=f"Received unparseable JSON payload: {str(e)}",
                    priority=TaskPriority.P0_URGENT,
                    sla_minutes=15,
                )
                self.audit("SECURITY", f"Malformed webhook JSON rejected: {str(e)}")
                return {"status": "error", "message": "Malformed JSON payload", "task_id": task.task_id}

            event_type = data.get("event")
            if event_type and event_type != "order.paid":
                self.audit("PAYMENT", f"Ignored non-payment webhook event: {event_type}")
                return {"status": "ignored", "message": f"Unhandled event {event_type}"}

            try:
                payment_entity = data["payload"]["payment"]["entity"]
                order_entity = data["payload"]["order"]["entity"]
                payment_id = payment_entity["id"]
                order_id = order_entity["id"]
                amount_paise = payment_entity.get("amount", 0)
            except KeyError as e:
                task = self.tasks.create_task(
                    patient_id="SYSTEM",
                    title="WEBHOOK: Missing Payload Fields",
                    description=f"Webhook missing key field: {str(e)}",
                    priority=TaskPriority.P0_URGENT,
                    sla_minutes=15,
                )
                return {"status": "error", "message": f"Missing field: {str(e)}", "task_id": task.task_id}

            # 2. Idempotency Check
            if payment_id in self.processed_payment_ids:
                self.audit("PAYMENT", f"Duplicate webhook for payment {payment_id} ignored.")
                return {"status": "ok", "message": "Duplicate webhook ignored (idempotent)"}

            # 3. Order mapping
            booking_id = self.order_to_booking.get(order_id)
            if not booking_id or booking_id not in self.bookings:
                task = self.tasks.create_task(
                    patient_id="UNKNOWN",
                    title=f"UNMAPPED PAYMENT: {payment_id} for order {order_id}",
                    description=f"Payment of {amount_paise / 100} INR received with no matching booking record.",
                    priority=TaskPriority.P0_URGENT,
                    sla_minutes=15,
                )
                self.audit("PAYMENT", f"Unmapped payment {payment_id} received.")
                return {"status": "error", "message": "Order ID not associated with any active booking", "task_id": task.task_id}

            booking = self.bookings[booking_id]
            patient = self.patients[booking.patient_id]
            clinician = self.clinicians[booking.clinician_id]

            # 4. Amount Verification
            expected_paise = int(clinician.consultation_fee * 100)
            if amount_paise != expected_paise:
                task = self.tasks.create_task(
                    patient_id=patient.patient_id,
                    title=f"P0 PAYMENT MISMATCH: {payment_id} ({_format_patient_task_identity(patient)})",
                    description=(
                        f"Expected {expected_paise/100} INR but received {amount_paise/100} INR. "
                        f"Payment held; booking not confirmed."
                    ),
                    priority=TaskPriority.P0_URGENT,
                    sla_minutes=15,
                    assigned_to="Clinic_Manager",
                )
                self.audit("PAYMENT", f"Payment amount mismatch for booking {booking_id}: got {amount_paise/100}, expected {expected_paise/100}")
                return {"status": "error", "message": "Payment amount mismatch", "task_id": task.task_id}

            # Record payment details
            if not booking.payment:
                booking.payment = PaymentRecord(order_id=order_id)
            booking.payment.payment_id = payment_id
            booking.payment.status = "CAPTURED"
            booking.payment.signature_verified = True
            booking.payment.paid_at = datetime.now()
            self.processed_payment_ids.add(payment_id)

            self.audit("PAYMENT", f"Payment {payment_id} (INR {booking.payment.amount_inr}) CAPTURED for booking {booking_id}")

            # 5. Check Late Payment / Slot Lost Condition
            now = datetime.now()
            hold_is_expired = booking.hold_expires_at and now > booking.hold_expires_at
            slot = self.setmore.slots.get(booking.slot_id)

            # Slot is taken if booked or held by another booking
            slot_taken = slot and (
                slot.is_booked or
                (slot.is_held and slot.held_until and slot.held_until > now and slot.held_by_booking_id != booking.booking_id)
            )

            if hold_is_expired and slot_taken:
                booking.state = BookingState.PAYMENT_RECEIVED_SLOT_LOST
                task = self.tasks.create_task(
                    patient_id=patient.patient_id,
                    title=f"P0 EXCEPTION: Payment Received but Slot Lost ({_format_patient_task_identity(patient)})",
                    description=(
                        f"Patient {_format_patient_task_identity(patient)} paid INR {booking.payment.amount_inr} "
                        f"after 15m hold expired. Slot {booking.slot_id} was reallocated. "
                        f"Payment ID: {payment_id}. Action: Reschedule with priority or issue instant refund."
                    ),
                    priority=TaskPriority.P0_URGENT,
                    sla_minutes=15,
                    assigned_to="FrontDesk_Lead",
                )
                self.whatsapp.send_discreet_message(
                    patient.phone_number,
                    f"Hello {patient_greeting(patient)}. We received your payment (Ref: {payment_id}). "
                    f"Due to high demand, our clinic manager is personally finalizing your slot and will call you in 15 minutes.",
                )
                self.audit("BOOKING", f"Late payment captured for booking {booking_id}, but slot {booking.slot_id} was lost.")

                # Reassurance email: Slot lost
                try:
                    recip_email = self._get_recipient_email(booking, patient)
                    if recip_email:
                        html_b, text_b = render_email(
                            template_name="slot_lost_reassurance",
                            subject="The Bengaluru Clinic · Priority Rescheduling Notice",
                            header_title="Payment Received · Priority Rescheduling",
                            header_subtitle="Your consultation payment is 100% secure",
                            context={
                                "patient_first_name": patient_greeting(patient),
                                "amount_inr": f"{float(booking.payment.amount_inr):,.2f}",
                                "payment_ref": payment_id,
                                "booking_id": booking.booking_id,
                            }
                        )
                        enqueue_email(
                            to_email=recip_email,
                            template="slot_lost_reassurance",
                            subject="The Bengaluru Clinic · Priority Rescheduling Notice",
                            html_body=html_b,
                            text_body=text_b,
                            dedupe_key=f"slot_lost_{booking.booking_id}",
                        )
                        self.audit("EMAIL", f"Patient {patient.patient_id}: Slot-lost reassurance enqueued for {mask_email(recip_email)}")
                    else:
                        self.audit("EMAIL", f"Patient {patient.patient_id}: No email on file; skipped slot-lost email.")
                except Exception as email_err:
                    self.audit("EMAIL", f"Slot-lost email error: {str(email_err)}")

                return {
                    "status": "exception",
                    "state": booking.state.value,
                    "task_id": task.task_id,
                    "booking_id": booking.booking_id,
                    "message": "Payment captured but slot expired and taken by another patient",
                }

            # 6. Attempt Setmore Confirmation
            try:
                appointment_id = self.setmore.confirm_appointment(booking)
                booking.setmore_appointment_id = appointment_id
                booking.state = BookingState.CONFIRMED
                booking.confirmed_at = datetime.now()

                receipt_url = f"https://invoices.bengaluru-clinic.in/receipt/{booking.booking_id}"
                doc_name = format_doctor_name(clinician.name)
                greeting = patient_greeting(patient)
                prefix = f"Hello {greeting}. " if greeting else ""
                confirmation_msg = (
                    f"{prefix}Appointment Confirmed with {doc_name} on {slot.start_time.strftime('%A, %d %b at %I:%M %p')}. "
                    f"Mode: {booking.mode}. Your receipt is available here: {receipt_url}"
                )
                self.whatsapp.send_discreet_message(
                    patient.phone_number,
                    confirmation_msg,
                    message_type="BOOKING_CONFIRMATION",
                )
                self.audit("BOOKING", f"Appointment confirmed in Setmore: {appointment_id} for booking {booking_id}")

                # Transactional Email: Payment Confirmed + Pure Python PDF Tax Invoice
                try:
                    recip_email = self._get_recipient_email(booking, patient)
                    if recip_email:
                        fee_float = float(booking.payment.amount_inr)
                        inv_num, seq, token = get_next_invoice_number(booking.booking_id, fee_float)
                        doc_name = format_doctor_name(clinician.name)
                        doc_slot = slot or self.setmore.slots.get(booking.slot_id)
                        slot_time = doc_slot.start_time if doc_slot else datetime.now()
                        inv_pdf_bytes, inv_pdf_path = generate_tax_invoice_pdf(
                            invoice_number=inv_num,
                            invoice_date=datetime.now(),
                            patient_full_name=patient.full_name or "Patient",
                            doctor_name=doc_name,
                            appointment_time=slot_time,
                            fee_inr=fee_float,
                            payment_reference=payment_id or booking.payment.order_id,
                            booking_id=booking.booking_id,
                        )
                        inv_download_url = f"{config.BASE_URL}/invoice/{token}"
                        html_b, text_b = render_email(
                            template_name="payment_confirmed",
                            subject="The Bengaluru Clinic · Appointment Confirmed & Tax Invoice",
                            header_title="Appointment Confirmed",
                            header_subtitle=f"{doc_name} · {slot_time.strftime('%A, %d %B at %I:%M %p')}",
                            context={
                                "patient_first_name": patient_greeting(patient),
                                "doctor_name": doc_name,
                                "appointment_time_str": slot_time.strftime("%A, %d %B %Y at %I:%M %p"),
                                "appointment_mode": "In-Person · Suite 302, Indiranagar",
                                "amount_inr": f"{fee_float:,.2f}",
                                "payment_ref": payment_id or booking.payment.order_id,
                                "invoice_number": inv_num,
                                "invoice_download_url": inv_download_url,
                                "invoice_filename": f"{inv_num}.pdf",
                            }
                        )
                        enqueue_email(
                            to_email=recip_email,
                            template="payment_confirmed",
                            subject="The Bengaluru Clinic · Appointment Confirmed & Tax Invoice",
                            html_body=html_b,
                            text_body=text_b,
                            attachment_name=f"{inv_num}.pdf",
                            attachment_bytes=inv_pdf_bytes,
                            dedupe_key=f"payment_confirmed_{booking.booking_id}",
                        )
                        self.audit("EMAIL", f"Patient {patient.patient_id}: Payment confirmation & invoice {inv_num} enqueued for {mask_email(recip_email)}")
                    else:
                        self.audit("EMAIL", f"Patient {patient.patient_id}: No email on file; skipped confirmation & invoice email.")
                except Exception as email_err:
                    self.audit("EMAIL", f"Payment confirmation email error: {str(email_err)}")

                return {"status": "success", "state": booking.state.value, "appointment_id": appointment_id, "booking_id": booking.booking_id}

            except Exception as e:
                # Extend slot hold to 60 minutes for staff recovery grace period
                self.setmore.extend_hold(booking.slot_id, 60)
                slot = self.setmore.slots.get(booking.slot_id)
                if slot and slot.held_until:
                    booking.hold_expires_at = slot.held_until
                else:
                    booking.hold_expires_at = datetime.now() + timedelta(minutes=60)

                booking.state = BookingState.PAYMENT_CAPTURED_BOOKING_FAILED
                task = self.tasks.create_task(
                    patient_id=patient.patient_id,
                    title=f"P0 CRITICAL: Payment Succeeded but Setmore Booking Failed ({_format_patient_task_identity(patient)})",
                    description=(
                        f"Payment ID: {payment_id} was CAPTURED for INR {booking.payment.amount_inr}, "
                        f"but Setmore API failed with error: '{str(e)}'. "
                        f"Patient {_format_patient_task_identity(patient)} has paid but has NO confirmed calendar appointment! One-click sync retry needed."
                    ),
                    priority=TaskPriority.P0_URGENT,
                    sla_minutes=10,
                    assigned_to="Clinic_Manager",
                )
                self.whatsapp.send_discreet_message(
                    patient.phone_number,
                    f"Hello {patient_greeting(patient)}. Your payment of INR {booking.payment.amount_inr} was received successfully. "
                    f"Your appointment is being registered on the clinician's calendar. You will receive final calendar details shortly.",
                )
                self.audit("BOOKING", f"Setmore confirmation failed post-payment for booking {booking_id}: {str(e)}")

                # Reassurance email: Calendar outage
                try:
                    recip_email = self._get_recipient_email(booking, patient)
                    if recip_email:
                        html_b, text_b = render_email(
                            template_name="calendar_failed_reassurance",
                            subject="The Bengaluru Clinic · Appointment Update",
                            header_title="Payment Confirmed · Appointment Safe",
                            header_subtitle="Calendar synchronization in progress",
                            context={
                                "patient_first_name": patient_greeting(patient),
                                "amount_inr": f"{float(booking.payment.amount_inr):,.2f}",
                                "payment_ref": payment_id,
                                "booking_id": booking.booking_id,
                            }
                        )
                        enqueue_email(
                            to_email=recip_email,
                            template="calendar_failed_reassurance",
                            subject="The Bengaluru Clinic · Appointment Update",
                            html_body=html_b,
                            text_body=text_b,
                            dedupe_key=f"calendar_failed_{booking.booking_id}",
                        )
                        self.audit("EMAIL", f"Patient {patient.patient_id}: Calendar outage reassurance enqueued for {mask_email(recip_email)}")
                    else:
                        self.audit("EMAIL", f"Patient {patient.patient_id}: No email on file; skipped calendar outage email.")
                except Exception as email_err:
                    self.audit("EMAIL", f"Calendar outage email error: {str(email_err)}")
                return {
                    "status": "exception",
                    "state": booking.state.value,
                    "task_id": task.task_id,
                    "booking_id": booking.booking_id,
                    "error": str(e),
                    "message": "Payment captured, but upstream booking service failed.",
                }

    # ---------------------------------------------------------
    # 4. Staff Task Actions & Exception Resolvers
    # ---------------------------------------------------------
    def retry_failed_booking(self, booking_id: str, staff_id: str) -> dict:
        """
        One-click calendar sync retry for P0 PAYMENT_CAPTURED_BOOKING_FAILED.
        Increments retry_count; escalates to ESCALATED status after 2 failed attempts.
        """
        with self.lock:
            booking = self.bookings.get(booking_id)
            if not booking:
                raise ValueError(f"Booking {booking_id} not found")

            booking.retry_count += 1
            clinician = self.clinicians.get(booking.clinician_id)
            slot = self.setmore.slots.get(booking.slot_id)
            patient = self.patients.get(booking.patient_id)

            try:
                appointment_id = self.setmore.confirm_appointment(booking)
                booking.setmore_appointment_id = appointment_id
                booking.state = BookingState.CONFIRMED
                booking.confirmed_at = datetime.now()

                # Resolve open task
                for t in self.tasks.get_open_tasks():
                    if t.patient_id == booking.patient_id and "Setmore Booking Failed" in t.title:
                        self.tasks.resolve_task(
                            t.task_id,
                            resolved_by=staff_id,
                            resolution_notes=f"Confirmed in Setmore on retry #{booking.retry_count}. Apt ID: {appointment_id}",
                        )

                # Send WhatsApp confirmation
                if patient and clinician and slot:
                    doc_name = format_doctor_name(clinician.name)
                    receipt_url = f"https://invoices.bengaluru-clinic.in/receipt/{booking.booking_id}"
                    greeting = patient_greeting(patient)
                    prefix = f"Hello {greeting}. " if greeting else ""
                    confirmation_msg = (
                        f"{prefix}Appointment Confirmed with {doc_name} on {slot.start_time.strftime('%A, %d %b at %I:%M %p')}. "
                        f"Mode: {booking.mode}. Your receipt is available here: {receipt_url}"
                    )
                    self.whatsapp.send_discreet_message(patient.phone_number, confirmation_msg, "BOOKING_CONFIRMATION")

                self.audit("STAFF", f"Booking {booking_id} confirmed on retry #{booking.retry_count} by {staff_id}")
                return {"status": "resolved", "appointment_id": appointment_id, "state": booking.state.value}

            except Exception as e:
                if booking.retry_count >= 2:
                    for t in self.tasks.get_open_tasks():
                        if t.patient_id == booking.patient_id and "Setmore Booking Failed" in t.title:
                            t.status = TaskStatus.ESCALATED
                            t.description += f" | Escalate: Retries exhausted ({booking.retry_count}). Error: {str(e)}"
                self.audit("STAFF", f"Retry #{booking.retry_count} failed for booking {booking_id}: {str(e)}")
                return {"status": "failed", "retry_count": booking.retry_count, "error": str(e)}

    def resolve_slot_lost(
        self,
        booking_id: str,
        action: str,
        staff_id: str,
        new_slot_id: Optional[str] = None,
    ) -> dict:
        """
        Resolves PAYMENT_RECEIVED_SLOT_LOST exception via priority reschedule or instant refund.
        """
        with self.lock:
            booking = self.bookings.get(booking_id)
            if not booking:
                raise ValueError(f"Booking {booking_id} not found")

            patient = self.patients.get(booking.patient_id)
            clinician = self.clinicians.get(booking.clinician_id)

            if action == "reschedule":
                if not new_slot_id or new_slot_id not in self.setmore.slots:
                    raise ValueError("A valid new_slot_id is required to reschedule")

                new_slot = self.setmore.slots[new_slot_id]
                booking.slot_id = new_slot_id
                self.setmore.hold_slot(new_slot_id, booking.booking_id, ttl_minutes=60)
                appointment_id = self.setmore.confirm_appointment(booking)
                booking.setmore_appointment_id = appointment_id
                booking.state = BookingState.CONFIRMED
                booking.confirmed_at = datetime.now()

                # Resolve task
                for t in self.tasks.get_open_tasks():
                    if t.patient_id == booking.patient_id and "Slot Lost" in t.title:
                        self.tasks.resolve_task(
                            t.task_id,
                            resolved_by=staff_id,
                            resolution_notes=f"Patient rescheduled to slot {new_slot_id}. Confirmed ID: {appointment_id}",
                        )

                msg = ""
                if patient and clinician:
                    doc_name = format_doctor_name(clinician.name)
                    msg = (
                        f"Hello {patient_greeting(patient)}. Your appointment with {doc_name} has been confirmed for "
                        f"{new_slot.start_time.strftime('%A, %d %b at %I:%M %p')}. Thank you for your patience."
                    )
                    self.whatsapp.send_discreet_message(
                        patient.phone_number,
                        msg,
                    )

                # Enqueue rescheduled email
                try:
                    recip_email = self._get_recipient_email(booking, patient)
                    if recip_email:
                        doc_n = format_doctor_name(clinician.name if clinician else "")
                        html_b, text_b = render_email(
                            template_name="rescheduled",
                            subject="The Bengaluru Clinic · Rescheduled Appointment Details",
                            header_title="Appointment Rescheduled",
                            header_subtitle=f"{doc_n} · {new_slot.start_time.strftime('%A, %d %B at %I:%M %p')}",
                            context={
                                "patient_first_name": patient_greeting(patient),
                                "doctor_name": doc_n,
                                "appointment_time_str": new_slot.start_time.strftime("%A, %d %B %Y at %I:%M %p"),
                                "booking_id": booking.booking_id,
                            }
                        )
                        enqueue_email(
                            to_email=recip_email,
                            template="rescheduled",
                            subject="The Bengaluru Clinic · Rescheduled Appointment Details",
                            html_body=html_b,
                            text_body=text_b,
                            dedupe_key=f"rescheduled_{booking.booking_id}_{new_slot_id}",
                        )
                        self.audit("EMAIL", f"Patient {patient.patient_id}: Rescheduled email enqueued for {mask_email(recip_email)}")
                    else:
                        self.audit("EMAIL", f"Patient {patient.patient_id}: No email on file; skipped reschedule email.")
                except Exception as email_err:
                    self.audit("EMAIL", f"Rescheduled email error: {str(email_err)}")

                self.audit("STAFF", f"Slot lost for booking {booking_id} resolved by {staff_id} via reschedule to {new_slot_id}")
                return {"status": "rescheduled", "appointment_id": appointment_id, "state": booking.state.value, "whatsapp_message": msg}

            elif action == "refund":
                payment_id = booking.payment.payment_id if booking.payment else "UNKNOWN"
                refund_id = self.gateway.process_refund(
                    payment_id=payment_id,
                    amount_inr=booking.payment.amount_inr if booking.payment else 0.0,
                    reason="Patient opted for refund after slot lost",
                )
                booking.state = BookingState.REFUNDED

                # Resolve task
                for t in self.tasks.get_open_tasks():
                    if t.patient_id == booking.patient_id and "Slot Lost" in t.title:
                        self.tasks.resolve_task(
                            t.task_id,
                            resolved_by=staff_id,
                            resolution_notes=f"Instant refund processed ({refund_id}) by {staff_id}.",
                        )

                msg = ""
                if patient:
                    msg = (
                        f"Hello {patient_greeting(patient)}. An instant full refund of INR {booking.payment.amount_inr} "
                        f"(Ref: {refund_id}) has been processed to your original payment method."
                    )
                    self.whatsapp.send_discreet_message(
                        patient.phone_number,
                        msg,
                    )

                # Enqueue refund processed email
                try:
                    recip_email = self._get_recipient_email(booking, patient)
                    if recip_email:
                        html_b, text_b = render_email(
                            template_name="refund_processed",
                            subject="The Bengaluru Clinic · Refund Processed",
                            header_title="Refund Processed",
                            header_subtitle=f"INR {booking.payment.amount_inr:,.2f} refunded",
                            context={
                                "patient_first_name": patient_greeting(patient),
                                "amount_inr": f"{booking.payment.amount_inr:,.2f}",
                                "refund_ref": refund_id,
                                "booking_id": booking.booking_id,
                            }
                        )
                        enqueue_email(
                            to_email=recip_email,
                            template="refund_processed",
                            subject="The Bengaluru Clinic · Refund Processed",
                            html_body=html_b,
                            text_body=text_b,
                            dedupe_key=f"refund_{booking.booking_id}_{refund_id}",
                        )
                        self.audit("EMAIL", f"Patient {patient.patient_id}: Refund email enqueued for {mask_email(recip_email)}")
                    else:
                        self.audit("EMAIL", f"Patient {patient.patient_id}: No email on file; skipped refund email.")
                except Exception as email_err:
                    self.audit("EMAIL", f"Refund email error: {str(email_err)}")

                self.audit("STAFF", f"Slot lost for booking {booking_id} resolved by {staff_id} via refund {refund_id}")
                return {"status": "refunded", "refund_id": refund_id, "state": booking.state.value, "whatsapp_message": msg}

            else:
                raise ValueError(f"Unknown resolution action '{action}'. Must be 'reschedule' or 'refund'.")

    def escalate_overdue_tasks(self, reference_time: Optional[datetime] = None) -> List[StaffTask]:
        """
        Periodic worker check: transitions OPEN tasks with breached SLAs to ESCALATED.
        """
        with self.lock:
            now = reference_time or datetime.now()
            escalated = []
            for task in self.tasks.tasks.values():
                if task.status == TaskStatus.OPEN and task.due_date and now >= task.due_date:
                    task.status = TaskStatus.ESCALATED
                    escalated.append(task)
                    self.audit("STAFF", f"Task {task.task_id} ({task.title}) breached SLA and was ESCALATED")
            return escalated

    # ---------------------------------------------------------
    # 5. Psychiatric Crisis Intercept & Safety Protocol
    # ---------------------------------------------------------
    def check_psychiatric_crisis(self, patient_id: str, message_text: str) -> Optional[StaffTask]:
        """
        Scans inbound patient message using word-boundary regex.
        If crisis keywords are detected:
        1. Mutes automated bot for this phone
        2. Dispatches supportive emergency helpline message
        3. Spawns P0 urgent task with 5-minute SLA for staff psychiatrist
        """
        with self.lock:
            if not CRISIS_PATTERN.search(message_text):
                return None

            patient = self.patients.get(patient_id)
            phone = patient.phone_number if patient else "UNKNOWN"

            # 1. Mute bot
            self.ai_muted_phones.add(phone)

            # 2. Spawn P0 Task (5 min SLA)
            greeting = patient_greeting(patient)
            task_identity = f"{greeting} (****{phone[-4:]})" if greeting and len(phone) >= 4 else (f"****{phone[-4:]}" if len(phone) >= 4 else phone)
            task = self.tasks.create_task(
                patient_id=patient_id,
                title=f"CRISIS INTERCEPT: Distress Signals from {task_identity}",
                description=(
                    f"Patient {task_identity} sent: \"{message_text.strip()[:100]}\". "
                    f"Automated bot is MUTED. Immediate clinical outreach or welfare protocol required."
                ),
                priority=TaskPriority.P0_URGENT,
                sla_minutes=5,
                assigned_to="OnCall_Psychiatrist",
            )

            # 3. Dispatch Empathetic Resource Message
            prefix = f"Hello {greeting}. " if greeting else ""
            helpline_msg = (
                f"{prefix}We care deeply about your well-being. If you are experiencing overwhelming distress, "
                "please connect immediately with free, confidential 24/7 support:\n\n"
                "- Tele-MANAS (Govt of India): 14416 or 1800-891-4416 (Toll-Free, 24/7)\n"
                "- Vandrevala Foundation Helpline: +91 9999 666 555 (24/7)\n"
                "- Emergency Response: 112\n\n"
                "A senior clinical coordinator from The Bengaluru Clinic has also been notified and will reach out to you."
            )
            self.whatsapp.send_discreet_message(phone, helpline_msg, message_type="CRISIS_RESOURCE")

            self.audit("CRISIS", f"Psychiatric crisis intercepted for {patient_id} ({_mask_phone(phone)}). P0 task {task.task_id} created.")
            return task

    def check_crisis_message(self, message_text: str) -> bool:
        """Helper to test if a message matches psychiatric crisis patterns."""
        return bool(CRISIS_PATTERN.search(message_text))

    def handle_crisis_trigger(self, phone: str, message_text: str) -> Optional[StaffTask]:
        """Convenience method to trigger crisis protocol by phone and message text."""
        with self.lock:
            self.ai_muted_phones.add(phone)
            status_res, profiles = self.resolve_patient_by_phone(phone)
            patient = profiles[0] if profiles else None
            if not patient:
                patient = self.register_or_get_patient("Patient", phone)
            return self.check_psychiatric_crisis(patient.patient_id, message_text)

    def resolve_crisis(self, task_id: str, staff_id: str, notes: str) -> dict:
        """
        Staff marks crisis intervention complete, un-muting automated chat for the patient.
        """
        with self.lock:
            task = self.tasks.tasks.get(task_id)
            if not task:
                raise ValueError(f"Task {task_id} not found")

            self.tasks.resolve_task(task_id, resolved_by=staff_id, resolution_notes=notes)
            patient = self.patients.get(task.patient_id)
            if patient and patient.phone_number in self.ai_muted_phones:
                self.ai_muted_phones.remove(patient.phone_number)

            self.audit("CRISIS", f"Crisis task {task_id} resolved by {staff_id}. AI un-muted for {task.patient_id}.")
            return {"status": "resolved", "task_id": task_id}

    # ---------------------------------------------------------
    # 6. Phone Calling Functionality (Inbound & Outbound Telephony)
    # ---------------------------------------------------------
    def handle_inbound_call(
        self,
        caller_phone: str,
        call_status: str = "ANSWERED",
        call_time: Optional[datetime] = None,
        agent_id: Optional[str] = None,
        duration_seconds: int = 0,
        caller_name: Optional[str] = None,
    ) -> dict:
        """
        Handles incoming patient calls routed from the single clinic phone number (+91 80 4000 0000).
        - Answered calls: logged with duration, agent, and timestamp.
        - Missed calls: creates callback task with SLA (30 mins working hours / 9:30 AM morning)
          and dispatches an immediate WhatsApp acknowledgment.
        """
        with self.lock:
            now = call_time or datetime.now()

            # Disambiguate or register patient
            status, profiles = self.resolve_patient_by_phone(caller_phone)
            if status == "SINGLE":
                patient = profiles[0]
            elif status == "MULTIPLE_PROFILES":
                patient = profiles[0]
            else:
                patient = self.register_or_get_patient(
                    full_name=caller_name or f"Caller {caller_phone[-4:]}",
                    phone_number=caller_phone,
                )

            call_id = f"CALL-{uuid.uuid4().hex[:8].upper()}"
            call_record = {
                "call_id": call_id,
                "caller_phone": caller_phone,
                "caller_phone_masked": _mask_phone(caller_phone),
                "patient_id": patient.patient_id,
                "patient_name": patient.discrete_name,
                "status": call_status.upper(),
                "timestamp": now.isoformat(),
                "duration_seconds": duration_seconds,
                "agent_id": agent_id,
            }

            if call_status.upper() in ("MISSED", "UNANSWERED", "BUSY"):
                sla_minutes, due_date, assigned_to = self.calculate_missed_call_sla(now)
                is_after_hours = now.hour >= 20 or now.hour < 9

                greeting = patient_greeting(patient)
                task_identity = f"{greeting} (****{caller_phone[-4:]})"
                task = self.tasks.create_task(
                    patient_id=patient.patient_id,
                    title=f"Missed Call from {task_identity}",
                    description=(
                        f"Inbound call from {task_identity} was unanswered at {now.strftime('%I:%M %p')}. "
                        f"{'After-hours call. Morning callback required by 9:30 AM.' if is_after_hours else 'Requires callback within 30 minutes.'}"
                    ),
                    priority=TaskPriority.P1_HIGH,
                    sla_minutes=sla_minutes,
                    assigned_to=assigned_to,
                )
                call_record["task_id"] = task.task_id

                # Dispatch discreet WhatsApp acknowledgment
                wa_text = (
                    f"Hello {greeting}. We noticed we missed your call to The Bengaluru Clinic. "
                    f"Our front-desk team has logged your inquiry and will call you back promptly "
                    f"({'at 9:30 AM tomorrow' if is_after_hours else 'within 30 minutes'}). "
                    f"If you would like to book a consultation right away, tap 'Book Appointment' or choose an open slot."
                )
                self.whatsapp.send_discreet_message(caller_phone, wa_text, message_type="CALL_ACK")

                self.call_log.append(call_record)
                self.audit("TELEPHONY", f"Missed call captured from {_mask_phone(caller_phone)}. P1 callback task {task.task_id} generated.")
                return {
                    "status": "missed_call_captured",
                    "call_record": call_record,
                    "task_id": task.task_id,
                    "sla_minutes": sla_minutes,
                }

            self.call_log.append(call_record)
            self.audit("TELEPHONY", f"Answered call ({duration_seconds}s) logged with {_mask_phone(caller_phone)} by {agent_id or 'Reception'}")
            return {
                "status": "answered_call_logged",
                "call_record": call_record,
            }

    def initiate_outbound_call(
        self,
        patient_id: str,
        staff_id: str,
        reason: str = "SCHEDULED_CALLBACK",
    ) -> dict:
        """
        Initiates an outbound click-to-call via Cloud Telephony REST API
        connecting clinic staff to the patient.
        Automatically resolves matching callback tasks for this patient.
        """
        with self.lock:
            patient = self.patients.get(patient_id)
            if not patient:
                raise ValueError(f"Patient {patient_id} not found")

            open_tasks = [
                t for t in self.tasks.get_open_tasks()
                if t.patient_id == patient_id and "Missed Call" in t.title
            ]
            resolved_tasks = []
            for t in open_tasks:
                self.tasks.resolve_task(
                    t.task_id,
                    resolved_by=staff_id,
                    resolution_notes=f"Outbound call placed by {staff_id}. Reason: {reason}",
                )
                resolved_tasks.append(t.task_id)

            call_id = f"OUTCALL-{uuid.uuid4().hex[:8].upper()}"
            call_record = {
                "call_id": call_id,
                "caller_phone": patient.phone_number,
                "caller_phone_masked": _mask_phone(patient.phone_number),
                "patient_id": patient.patient_id,
                "patient_name": patient.discrete_name,
                "status": "OUTBOUND_CONNECTED",
                "timestamp": datetime.now().isoformat(),
                "duration_seconds": 0,
                "agent_id": staff_id,
                "reason": reason,
            }
            self.call_log.append(call_record)
            self.audit("TELEPHONY", f"Outbound call placed by {staff_id} to {_mask_phone(patient.phone_number)}")

            return {
                "status": "outbound_call_initiated",
                "call_id": call_id,
                "patient_phone": patient.phone_number,
                "staff_id": staff_id,
                "resolved_task_ids": resolved_tasks,
            }

    # ---------------------------------------------------------
    # 7. Cancellation & Rescheduling
    # ---------------------------------------------------------
    def calculate_active_reminders(self, appointment_time: datetime, booking_time: datetime) -> List[dict]:
        """
        Calculates reminder schedule:
        - 3 days before (72h)
        - 1 day before (24h)
        - Morning of appointment (8:00 AM)
        Skips reminder times that have already elapsed relative to booking_time.
        """
        morning_of = datetime(
            appointment_time.year,
            appointment_time.month,
            appointment_time.day,
            8, 0, 0
        )
        candidates = [
            ("72_HOURS_BEFORE", appointment_time - timedelta(days=3)),
            ("24_HOURS_BEFORE", appointment_time - timedelta(days=1)),
            ("MORNING_OF_APPOINTMENT", morning_of),
        ]
        active = []
        for label, scheduled_at in candidates:
            if scheduled_at > booking_time:
                active.append({"label": label, "scheduled_at": scheduled_at})
        return active

    def cancel_booking(self, booking_id: str, reason: str, initiated_by: str = "PATIENT") -> dict:
        with self.lock:
            booking = self.bookings.get(booking_id)
            if not booking:
                raise ValueError(f"Booking {booking_id} not found")

            if booking.setmore_appointment_id:
                self.setmore.cancel_appointment(booking.setmore_appointment_id)

            booking.state = BookingState.CANCELLED
            booking.cancellation_reason = reason

            refund_id = None
            if booking.payment and booking.payment.status == "CAPTURED" and booking.payment.payment_id:
                refund_id = self.gateway.process_refund(
                    payment_id=booking.payment.payment_id,
                    amount_inr=booking.payment.amount_inr,
                    reason=f"Booking cancelled: {reason}",
                )
                booking.state = BookingState.REFUNDED

            patient = self.patients.get(booking.patient_id)
            if patient:
                greeting = patient_greeting(patient)
                self.whatsapp.send_discreet_message(
                    patient.phone_number,
                    f"Hello {greeting}. Your appointment has been cancelled as requested. "
                    + (f"A refund of INR {booking.payment.amount_inr} has been initiated." if refund_id else ""),
                )

            if refund_id:
                try:
                    recip_email = self._get_recipient_email(booking, patient)
                    if recip_email:
                        html_b, text_b = render_email(
                            template_name="refund_processed",
                            subject="The Bengaluru Clinic · Refund Processed",
                            header_title="Refund Processed",
                            header_subtitle=f"INR {booking.payment.amount_inr:,.2f} refunded",
                            context={
                                "patient_first_name": patient_greeting(patient),
                                "amount_inr": f"{booking.payment.amount_inr:,.2f}",
                                "refund_ref": refund_id,
                                "booking_id": booking.booking_id,
                            }
                        )
                        enqueue_email(
                            to_email=recip_email,
                            template="refund_processed",
                            subject="The Bengaluru Clinic · Refund Processed",
                            html_body=html_b,
                            text_body=text_b,
                            dedupe_key=f"refund_{booking.booking_id}_{refund_id}",
                        )
                        self.audit("EMAIL", f"Patient {patient.patient_id}: Refund email enqueued for {mask_email(recip_email)}")
                except Exception as email_err:
                    self.audit("EMAIL", f"Refund email error: {str(email_err)}")

            self.audit("BOOKING", f"Booking {booking_id} cancelled by {initiated_by}. Reason: {reason}")
            return {"status": "cancelled", "refund_id": refund_id}

    def send_appointment_reminders(self) -> int:
        """
        Sends upcoming appointment reminders (72h, 24h, morning of)
        only to patients who have appointment_reminders enabled.
        """
        with self.lock:
            now = datetime.now()
            enqueued_count = 0
            for booking in self.bookings.values():
                if booking.state != BookingState.CONFIRMED:
                    continue
                slot = self.setmore.slots.get(booking.slot_id)
                if not slot:
                    continue
                patient = self.patients.get(booking.patient_id)
                clinician = self.clinicians.get(booking.clinician_id)
                if not patient or not clinician:
                    continue
                recip_email = self._get_recipient_email(booking, patient)
                if not recip_email:
                    continue

                reminders_enabled = True
                try:
                    from src.db import db_cursor
                    import json
                    with db_cursor(commit=False) as cur:
                        cur.execute("""
                            SELECT s.preferences FROM subscriptions s
                            JOIN users u ON s.user_id = u.id
                            WHERE u.email = ?;
                        """, (recip_email,))
                        row = cur.fetchone()
                        if row and row["preferences"]:
                            prefs = json.loads(row["preferences"])
                            reminders_enabled = prefs.get("appointment_reminders", True)
                except Exception:
                    pass

                if not reminders_enabled:
                    continue

                active_rems = self.calculate_active_reminders(slot.start_time, booking.created_at)
                doc_name = format_doctor_name(clinician.name)
                for rem in active_rems:
                    sched = rem["scheduled_at"]
                    if abs((sched - now).total_seconds()) <= 3600 or sched <= now:
                        dedupe_key = f"reminder_{rem['label']}_{booking.booking_id}"
                        try:
                            html_b, text_b = render_email(
                                template_name="appointment_reminder",
                                subject=f"The Bengaluru Clinic · Appointment Reminder with {doc_name}",
                                header_title="Upcoming Appointment Reminder",
                                header_subtitle=f"{doc_name} · {slot.start_time.strftime('%A, %d %B at %I:%M %p')}",
                                context={
                                    "patient_first_name": patient_greeting(patient),
                                    "doctor_name": doc_name,
                                    "appointment_time_str": slot.start_time.strftime("%A, %d %B %Y at %I:%M %p"),
                                }
                            )
                            qid = enqueue_email(
                                to_email=recip_email,
                                template="appointment_reminder",
                                subject=f"The Bengaluru Clinic · Appointment Reminder with {doc_name}",
                                html_body=html_b,
                                text_body=text_b,
                                dedupe_key=dedupe_key,
                            )
                            if qid:
                                enqueued_count += 1
                                self.audit("EMAIL", f"Patient {patient.patient_id}: {rem['label']} reminder enqueued for {mask_email(recip_email)}")
                        except Exception as e:
                            self.audit("EMAIL", f"Reminder email error: {str(e)}")
            return enqueued_count

    def generate_reminder_message(self, booking_id: str, reminder_label: str) -> str:
        """
        Generates standard reminder message for an upcoming appointment.
        Always addresses the patient by patient_greeting(patient).
        """
        with self.lock:
            booking = self.bookings.get(booking_id)
            if not booking:
                return ""
            patient = self.patients.get(booking.patient_id)
            clinician = self.clinicians.get(booking.clinician_id)
            slot = self.setmore.slots.get(booking.slot_id)
            greeting = patient_greeting(patient)
            doc_name = format_doctor_name(clinician.name if clinician else "")
            slot_time = slot.start_time.strftime("%A, %d %b at %I:%M %p") if slot else "your scheduled time"
            return f"Hello {greeting}. Reminder: Your appointment with {doc_name} is scheduled for {slot_time}."



