"""
Data models and Enums for the Clinic Booking and Coordination System.
Designed for a sensitive sexual health, mental health, and relationship clinic.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
import sys
from typing import Dict, List, Optional
import uuid

# Ensure root directory is in sys.path when run directly
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))


class BookingState(str, Enum):
    INITIATED = "INITIATED"
    SLOT_HELD = "SLOT_HELD"                          # Temporary hold with TTL
    PAYMENT_PENDING = "PAYMENT_PENDING"              # Payment link sent, awaiting webhook
    CONFIRMED = "CONFIRMED"                          # Payment verified + Setmore confirmed
    HOLD_EXPIRED = "HOLD_EXPIRED"                    # 15-min TTL passed before payment
    PAYMENT_CAPTURED_BOOKING_FAILED = "PAYMENT_CAPTURED_BOOKING_FAILED"  # P0 Exception
    PAYMENT_RECEIVED_SLOT_LOST = "PAYMENT_RECEIVED_SLOT_LOST"            # Late payment exception
    CANCELLED = "CANCELLED"
    REFUND_PENDING = "REFUND_PENDING"
    REFUNDED = "REFUNDED"


class TaskPriority(str, Enum):
    P0_URGENT = "P0_URGENT"    # Clinical red flags, payment captured but unbooked
    P1_HIGH = "P1_HIGH"        # Missed calls, payment link expired with late payment
    P2_MEDIUM = "P2_MEDIUM"    # Routine callbacks, report review booking follow-ups
    P3_LOW = "P3_LOW"          # General administrative enquiries


class TaskStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


def format_doctor_name(name: str) -> str:
    """
    Ensures clinician names always have exactly one 'Dr. ' prefix,
    fixing any 'Dr. Dr.' or missing prefix bugs.
    """
    if not name:
        return "Dr. Clinician"
    cleaned = name.strip()
    while True:
        lower = cleaned.lower()
        if lower.startswith("dr."):
            cleaned = cleaned[3:].strip()
        elif lower.startswith("dr "):
            cleaned = cleaned[3:].strip()
        elif lower == "dr":
            cleaned = ""
            break
        else:
            break
    return f"Dr. {cleaned}" if cleaned else "Dr. Clinician"


@dataclass
class AuditEntry:
    seq: int
    timestamp: str
    category: str  # SYSTEM, BOOKING, PAYMENT, SECURITY, CRISIS, TELEPHONY, STAFF
    message: str
    prev_hash: str
    hash: str


@dataclass
class PatientProfile:
    patient_id: str = field(default_factory=lambda: f"PAT-{uuid.uuid4().hex[:8].upper()}")
    full_name: str = ""
    phone_number: str = ""        # Shared or individual phone number (E.164)
    email: Optional[str] = None
    discrete_name: Optional[str] = None  # Safe name to use in discreet SMS/WhatsApp
    preferred_communication: str = "WHATSAPP"
    consent_recorded: bool = True
    created_at: datetime = field(default_factory=datetime.now)
    pin_salt: Optional[str] = None
    pin_hash: Optional[str] = None
    failed_pin_attempts: int = 0
    locked_until: Optional[datetime] = None


@dataclass
class Clinician:
    clinician_id: str
    name: str
    specialty: str                # e.g., "Psychiatrist", "Sexologist", "Couples Therapist"
    setmore_staff_key: str
    consultation_fee: float       # In INR
    duration_minutes: int         # e.g., 50
    service_label: str = ""       # e.g., "Therapy session", "Psychiatric consultation"


@dataclass
class TimeSlot:
    slot_id: str
    clinician_id: str
    start_time: datetime
    end_time: datetime
    is_held: bool = False
    held_until: Optional[datetime] = None
    is_booked: bool = False
    held_by_booking_id: Optional[str] = None


@dataclass
class PaymentRecord:
    order_id: str
    payment_id: Optional[str] = None
    amount_inr: float = 0.0
    status: str = "CREATED"       # CREATED, AUTHORIZED, CAPTURED, FAILED, REFUNDED
    gateway: str = "RAZORPAY_MOCK"
    payment_link_url: Optional[str] = None
    signature_verified: bool = False
    paid_at: Optional[datetime] = None


@dataclass
class StaffTask:
    task_id: str = field(default_factory=lambda: f"TSK-{uuid.uuid4().hex[:6].upper()}")
    patient_id: str = ""
    title: str = ""
    description: str = ""
    priority: TaskPriority = TaskPriority.P2_MEDIUM
    status: TaskStatus = TaskStatus.OPEN
    assigned_to: Optional[str] = None
    due_date: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.now)
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None
    resolution_notes: Optional[str] = None


@dataclass
class BookingRecord:
    booking_id: str = field(default_factory=lambda: f"BKG-{uuid.uuid4().hex[:8].upper()}")
    patient_id: str = ""
    clinician_id: str = ""
    slot_id: str = ""
    service_name: str = ""
    mode: str = "IN_PERSON"       # "IN_PERSON" or "ONLINE"
    state: BookingState = BookingState.INITIATED
    payment: Optional[PaymentRecord] = None
    setmore_appointment_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    hold_expires_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    cancellation_reason: Optional[str] = None
    retry_count: int = 0
    receipt_email: Optional[str] = None
    notes: List[str] = field(default_factory=list)


if __name__ == "__main__":
    print("=" * 65)
    print("DEMO: [models.py] Data Structures & Shared-Phone Entity Modeling")
    print("=" * 65)
    
    # Demonstrate creating two distinct patients on the same phone number (# DEMO DATA ONLY)
    shared_phone = "+919876500000"
    p1 = PatientProfile(full_name="Pooja Kulkarni", phone_number=shared_phone, discrete_name="Pooja")  # DEMO DATA ONLY
    p2 = PatientProfile(full_name="Sameer Kulkarni", phone_number=shared_phone, discrete_name="Sameer")  # DEMO DATA ONLY
    
    print(f"\n1. Shared Phone Number: {shared_phone}")
    print(f"   -> Profile A: ID={p1.patient_id} | Name={p1.full_name} | Discrete={p1.discrete_name}")
    print(f"   -> Profile B: ID={p2.patient_id} | Name={p2.full_name} | Discrete={p2.discrete_name}")
    print("   [Guaranteed Separation]: Medical records are isolated by Patient ID, not phone number.")
    
    # Demonstrate Clinician & Booking State (# DEMO DATA ONLY)
    doc = Clinician("DOC-101", "Dr. Ananya Sharma", "Sexology & Mental Health", "staff_101", 2500.0, 50, "Therapy session")  # DEMO DATA ONLY
    print(f"\n2. Clinician Profile: {doc.name} ({doc.specialty}) - Fee: INR {doc.consultation_fee}")
    print(f"3. Core State Machine States:")
    for state in BookingState:
        print(f"   - {state.value}")
    print("\n[OK] models.py executed successfully!")
