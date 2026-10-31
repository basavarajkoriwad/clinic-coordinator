"""
Mock external services for Setmore API, Payment Gateway (Razorpay/Cashfree),
Discreet WhatsApp Notifications, and Staff Task/Exception Management.
"""

from datetime import datetime, timedelta
import hashlib
import hmac
import json
from pathlib import Path
import re
import sys
from typing import Dict, List, Optional

# Ensure root directory is in sys.path when run directly
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from src.models import (
    Clinician,
    TimeSlot,
    BookingRecord,
    BookingState,
    PaymentRecord,
    StaffTask,
    TaskPriority,
    TaskStatus,
)


class MockSetmoreService:
    """
    Simulates Setmore calendar appointments, clinician scheduling,
    and availability checking with support for failure injection.
    """
    def __init__(self):
        self.slots: Dict[str, TimeSlot] = {}
        self.appointments: Dict[str, dict] = {}
        self.simulate_api_failure = False  # For testing 500 error injection

    def add_slot(self, slot: TimeSlot):
        self.slots[slot.slot_id] = slot

    def check_availability(self, slot_id: str) -> bool:
        slot = self.slots.get(slot_id)
        if not slot:
            return False
        # If currently booked, unavailable
        if slot.is_booked:
            return False
        # If held and hold has not expired, unavailable
        if slot.is_held and slot.held_until and datetime.now() < slot.held_until:
            return False
        return True

    def hold_slot(self, slot_id: str, booking_id: str, ttl_minutes: int = 15) -> bool:
        slot = self.slots.get(slot_id)
        if not slot:
            return False
        
        # Check if already booked or actively held by someone else
        now = datetime.now()
        if slot.is_booked:
            return False
        if slot.is_held and slot.held_until and slot.held_until > now and slot.held_by_booking_id != booking_id:
            return False

        slot.is_held = True
        slot.held_until = now + timedelta(minutes=ttl_minutes)
        slot.held_by_booking_id = booking_id
        return True

    def release_hold(self, slot_id: str):
        slot = self.slots.get(slot_id)
        if slot and not slot.is_booked:
            slot.is_held = False
            slot.held_until = None
            slot.held_by_booking_id = None

    def extend_hold(self, slot_id: str, additional_minutes: int = 60) -> bool:
        """
        Extends an existing hold by additional_minutes (default 60 min for staff grace period).
        """
        slot = self.slots.get(slot_id)
        if not slot or slot.is_booked:
            return False
        now = datetime.now()
        base = slot.held_until if (slot.held_until and slot.held_until > now) else now
        slot.is_held = True
        slot.held_until = base + timedelta(minutes=additional_minutes)
        return True

    def confirm_appointment(self, booking: BookingRecord) -> str:
        """
        Confirms appointment in Setmore.
        Raises RuntimeError if simulated failure is active or slot is taken.
        """
        if self.simulate_api_failure:
            raise RuntimeError("Setmore API Error 500: Internal Server Timeout / CalDAV sync failure")

        slot = self.slots.get(booking.slot_id)
        if not slot:
            raise ValueError(f"Slot {booking.slot_id} does not exist in Setmore")

        # Check if slot was stolen by another confirmed booking
        if slot.is_booked and slot.held_by_booking_id != booking.booking_id:
            raise ValueError(f"Slot {booking.slot_id} is already booked by another patient!")

        appointment_id = f"SETMORE-APT-{datetime.now().strftime('%Y%m%d%H%M%S')}-{booking.booking_id[-4:]}"
        slot.is_booked = True
        slot.is_held = False
        slot.held_until = None
        slot.held_by_booking_id = booking.booking_id

        self.appointments[appointment_id] = {
            "appointment_id": appointment_id,
            "booking_id": booking.booking_id,
            "patient_id": booking.patient_id,
            "clinician_id": booking.clinician_id,
            "start_time": slot.start_time.isoformat(),
            "end_time": slot.end_time.isoformat(),
            "service": booking.service_name,
            "status": "CONFIRMED",
        }
        return appointment_id

    def cancel_appointment(self, appointment_id: str) -> bool:
        if appointment_id in self.appointments:
            apt = self.appointments[appointment_id]
            apt["status"] = "CANCELLED"
            for slot in self.slots.values():
                if slot.held_by_booking_id == apt["booking_id"]:
                    slot.is_booked = False
                    slot.is_held = False
                    slot.held_by_booking_id = None
            return True
        return False


class MockPaymentGateway:
    """
    Simulates Razorpay / Cashfree order creation, webhook generation,
    cryptographic HMAC-SHA256 signature verification, and refunds.
    """
    def __init__(self, webhook_secret: str = "mock_secret_key_clinic_2026"):
        self.webhook_secret = webhook_secret
        self.orders: Dict[str, dict] = {}
        self.payments: Dict[str, dict] = {}
        self.refunds: Dict[str, dict] = {}

    def create_order(self, booking_id: str, amount_inr: float, patient_phone: str) -> PaymentRecord:
        order_id = f"order_{booking_id.lower().replace('-', '_')}"
        payment_link = f"https://pay.bengaluru-clinic.in/pay/{order_id}"
        
        self.orders[order_id] = {
            "order_id": order_id,
            "booking_id": booking_id,
            "amount_inr": amount_inr,
            "phone": patient_phone,
            "status": "CREATED",
            "created_at": datetime.now(),
        }
        return PaymentRecord(
            order_id=order_id,
            amount_inr=amount_inr,
            status="CREATED",
            gateway="RAZORPAY_MOCK",
            payment_link_url=payment_link,
        )

    def generate_webhook_payload(self, order_id: str, payment_id: Optional[str] = None, event: str = "order.paid") -> dict:
        """
        Simulates the payload sent by payment gateway to clinic webhook endpoint.
        """
        order = self.orders.get(order_id, {})
        pid = payment_id or f"pay_{hashlib.md5(order_id.encode()).hexdigest()[:10]}"
        payload = {
            "event": event,
            "payload": {
                "payment": {
                    "entity": {
                        "id": pid,
                        "order_id": order_id,
                        "amount": int(order.get("amount_inr", 0) * 100),  # In paise
                        "currency": "INR",
                        "status": "captured",
                        "method": "upi",
                    }
                },
                "order": {
                    "entity": {
                        "id": order_id,
                        "status": "paid",
                    }
                }
            }
        }
        return payload

    def compute_signature(self, payload_body: str) -> str:
        """
        Computes HMAC-SHA256 signature using the secret key.
        """
        return hmac.new(
            self.webhook_secret.encode('utf-8'),
            payload_body.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

    def verify_webhook_signature(self, payload_body: str, signature: str) -> bool:
        expected = self.compute_signature(payload_body)
        return hmac.compare_digest(expected, signature)

    def process_refund(self, payment_id: str, amount_inr: float, reason: str) -> str:
        refund_id = f"rfnd_{hashlib.md5(payment_id.encode()).hexdigest()[:10]}"
        self.refunds[refund_id] = {
            "refund_id": refund_id,
            "payment_id": payment_id,
            "amount_inr": amount_inr,
            "reason": reason,
            "timestamp": datetime.now().isoformat(),
        }
        return refund_id


class MockWhatsAppService:
    """
    Simulates sending discreet WhatsApp Business messages and invoices.
    Enforces privacy by ensuring sensitive clinical diagnoses are not exposed in preview text.
    """
    def __init__(self):
        self.sent_messages: List[dict] = []

    def send_discreet_message(self, to_phone: str, message_text: str, message_type: str = "NOTIFICATION"):
        # Privacy filter: sanitizes explicit clinical conditions from notification preview text
        cleaned = message_text
        for term in ["Sexual Dysfunction", "Erectile Dysfunction", "Premature Ejaculation", "HIV", "STI"]:
            cleaned = re.sub(re.escape(term), "Consultation", cleaned, flags=re.IGNORECASE)
        self.sent_messages.append({
            "to": to_phone,
            "type": message_type,
            "content": cleaned,
            "timestamp": datetime.now(),
        })

    def get_messages_for_phone(self, phone: str) -> List[dict]:
        return [m for m in self.sent_messages if m["to"] == phone]


class TaskManager:
    """
    Central queue for staff oversight, SLAs, and P0/P1 exceptions.
    Ensures 'no pending patient request becomes invisible'.
    """
    def __init__(self):
        self.tasks: Dict[str, StaffTask] = {}

    def create_task(
        self,
        patient_id: str,
        title: str,
        description: str = "",
        priority: TaskPriority = TaskPriority.P2_MEDIUM,
        sla_minutes: int = 60,
        assigned_to: Optional[str] = "FrontDesk_Pool"
    ) -> StaffTask:
        due = datetime.now() + timedelta(minutes=sla_minutes)
        task = StaffTask(
            patient_id=patient_id,
            title=title,
            description=description,
            priority=priority,
            status=TaskStatus.OPEN,
            assigned_to=assigned_to,
            due_date=due,
        )
        self.tasks[task.task_id] = task
        return task

    def get_open_tasks(self, priority: Optional[TaskPriority] = None) -> List[StaffTask]:
        open_tasks = [t for t in self.tasks.values() if t.status in (TaskStatus.OPEN, TaskStatus.ESCALATED)]
        if priority:
            open_tasks = [t for t in open_tasks if t.priority == priority]
        return open_tasks

    def resolve_task(self, task_id: str, resolved_by: str, resolution_notes: str) -> bool:
        if task_id in self.tasks:
            task = self.tasks[task_id]
            task.status = TaskStatus.RESOLVED
            task.resolved_at = datetime.now()
            task.resolved_by = resolved_by
            task.resolution_notes = f"Resolved by {resolved_by}: {resolution_notes}"
            return True
        return False


if __name__ == "__main__":
    print("=" * 65)
    print("DEMO: [mock_services.py] Testing Mock Integrations Independently")
    print("=" * 65)
    
    # 1. Test Payment Gateway HMAC Signature
    pg = MockPaymentGateway()
    order = pg.create_order("BKG-TEST-123", 2500.0, "+919888800000")
    print(f"\n1. Mock Payment Gateway:")
    print(f"   Created Order ID: {order.order_id}")
    print(f"   Payment Link URL: {order.payment_link_url}")
    payload = json.dumps(pg.generate_webhook_payload(order.order_id))
    valid_sig = pg.compute_signature(payload)
    print(f"   HMAC-SHA256 Signature: {valid_sig[:24]}...")
    print(f"   Signature Verified Genuine: {pg.verify_webhook_signature(payload, valid_sig)}")
    print(f"   Forged Signature Rejected: {not pg.verify_webhook_signature(payload, 'tampered_fake_sig')}")
    
    # 2. Test WhatsApp Service
    wa = MockWhatsAppService()
    wa.send_discreet_message("+919888800000", "Hello! Your appointment slot is held.")
    print(f"\n2. Mock WhatsApp Service:")
    print(f"   Sent Messages Count: {len(wa.sent_messages)}")
    print(f"   Message Content: {wa.sent_messages[0]['content']}")

    # 3. Test TaskManager & SLA Queue
    tm = TaskManager()
    task = tm.create_task(
        patient_id="PAT-999",
        title="Missed Call from +91-98765-XXXXX",
        description="Patient called twice outside clinic hours. Callback required.",
        priority=TaskPriority.P1_HIGH,
        sla_minutes=30,
        assigned_to="FrontDesk_Lead"
    )
    print(f"\n3. Task Manager Queue:")
    print(f"   Task Created: ID={task.task_id} | Priority={task.priority.value}")
    print(f"   Assigned To: {task.assigned_to} | Due: {task.due_date.strftime('%H:%M:%S')}")
    print("\n[OK] mock_services.py executed successfully!")
