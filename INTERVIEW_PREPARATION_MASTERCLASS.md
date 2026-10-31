# Masterclass Technical Interview Guide & Architecture Deep-Dive
## Patient Coordination Engine for a Sexual Health, Mental Health & Relationship Clinic (Bengaluru)

---

## 1. Project Origin: What We Built from Scratch & Why

### The Core Problem Statement
A multidisciplinary clinic in Bengaluru (specializing in psychiatric care, psychosexual therapy, sexology, and couples counseling) faced high administrative overhead and operational leakage:
* Inbound inquiries landed on a single mobile handset running consumer WhatsApp Business and SIM cellular calls.
* Front-desk staff manually cross-referenced bank SMS alerts and Setmore calendars.
* Patients sharing a single phone number (e.g., married couples or parent/teen) were at extreme risk of confidential medical record contamination.
* Late UPI payments created calendar double-bookings and lost patient inquiries.

### The Architectural Blueprint Built from Scratch
We engineered an event-driven coordination state machine that enforces medical-grade privacy and financial determinism:
1. **Decoupled Identity Engine**: Phone number is demoted from a Primary Key to an Access Channel. Patients are indexed by unique UUID / MRN (`PAT-XXXXXXXX`), supporting $1:N$ phone-to-patient profile mapping.
2. **Pessimistic Time-to-Live (TTL) Slot Reservation**: When a patient chooses a slot, an atomic 15-minute hold is placed on Setmore while a dynamic payment link is generated.
3. **Cryptographically Verified Financial Ledger**: Screenshot-based confirmation is strictly banned. Confirmations require HMAC-SHA256 signature verification over payment gateway webhooks.
4. **Deterministic Failure Triage**: Edge cases (late payments, API timeouts, slot collisions) transition to explicit error states (`PAYMENT_RECEIVED_SLOT_LOST`, `PAYMENT_CAPTURED_BOOKING_FAILED`) and generate prioritized Staff Tasks with enforced SLA countdowns.
5. **Zero-Leakage Communication**: Lock-screen notifications omit all clinical diagnoses and stigmatizing terminology.

---

## 2. Exhaustive Code Walkthrough: Block by Block

### 2.1 Data Models & Privacy (`src/models.py`)
```python
class BookingState(str, Enum):
    INITIATED = "INITIATED"
    SLOT_HELD = "SLOT_HELD"                          # 15-min soft hold active
    PAYMENT_PENDING = "PAYMENT_PENDING"              # Payment link sent, awaiting webhook
    CONFIRMED = "CONFIRMED"                          # Verified payment + Setmore sync
    HOLD_EXPIRED = "HOLD_EXPIRED"                    # 15-min TTL elapsed
    PAYMENT_CAPTURED_BOOKING_FAILED = "PAYMENT_CAPTURED_BOOKING_FAILED"  # P0 API failure
    PAYMENT_RECEIVED_SLOT_LOST = "PAYMENT_RECEIVED_SLOT_LOST"            # Late payment race
    CANCELLED = "CANCELLED"
    REFUND_PENDING = "REFUND_PENDING"
    REFUNDED = "REFUNDED"
```
* **Why String Enums?**: Inheriting from `(str, Enum)` ensures clean JSON serialization without custom encoder overrides when persisting to databases or emitting event streams.
* **`PatientProfile`**: Contains `patient_id` (UUID4 hex), `full_name`, `discrete_name` (used for lock-screen messages), and `consent_recorded` (DPDP Act compliance flag).

---

### 2.2 Mock Integrations & External Services (`src/mock_services.py`)

#### A. Setmore API Simulation (`MockSetmoreService`)
* **Slot Management**: Stores slots keyed by `slot_id`.
* **Atomic Hold Logic (`hold_slot`)**:
  ```python
  if slot.is_held and slot.held_until and slot.held_until > now and slot.held_by_booking_id != booking_id:
      return False
  ```
  Prevents race conditions where two concurrent web threads attempt to lock the same clinician hour.
* **Failure Injection**: A toggle (`simulate_api_failure = True`) allows testing how the system handles Setmore HTTP 500 outages.

#### B. Cryptographic Payment Gateway (`MockPaymentGateway`)
* Simulates Razorpay/Cashfree order generation.
* **Cryptographic Verification**:
  ```python
  def compute_signature(self, payload_body: str) -> str:
      return hmac.new(self.webhook_secret.encode('utf-8'), payload_body.encode('utf-8'), hashlib.sha256).hexdigest()

  def verify_webhook_signature(self, payload_body: str, signature: str) -> bool:
      expected = self.compute_signature(payload_body)
      return hmac.compare_digest(expected, signature)
  ```
  * **Interview Point**: We use `hmac.compare_digest()` instead of `==` to prevent **timing attacks** (constant-time string comparison).

#### C. Staff Task & SLA Engine (`TaskManager`)
* Every exception creates a `StaffTask` with an explicit priority (`P0_URGENT`, `P1_HIGH`, `P2_MEDIUM`), a named owner, and an SLA timestamp (`datetime.now() + timedelta(minutes=sla)`).

---

### 2.3 Central State Machine (`src/coordinator.py`)

#### A. Shared-Phone Disambiguation (`resolve_patient_by_phone`)
```python
def resolve_patient_by_phone(self, phone_number: str) -> Tuple[str, List[PatientProfile]]:
    pids = self.phone_to_patients.get(phone_number, [])
    if not pids: return "NOT_FOUND", []
    if len(pids) == 1: return "SINGLE", [self.patients[pids[0]]]
    return "MULTIPLE_PROFILES", [self.patients[pid] for pid in pids]
```
If `MULTIPLE_PROFILES` is returned, the front-end prompts the user for profile selection and PIN entry before revealing private data.

#### B. Webhook Ingestion & Exception Handlers (`handle_payment_webhook`)
1. **Security Gate**: Calls `verify_webhook_signature()`. If false, rejects payload and logs a security task.
2. **Idempotency Gate**: Checks `payment_id in self.processed_payment_ids`. If present, returns early to prevent duplicate bookings or double charges.
3. **Late Payment Trap**: Checks if `now > booking.hold_expires_at` and `slot.is_booked`. If true, transitions to `PAYMENT_RECEIVED_SLOT_LOST`, generates a P0 task with 15-minute SLA, and alerts the patient.
4. **Upstream CalDAV/API Failure Trap**: Wraps Setmore confirmation in a `try...except` block. If Setmore throws an exception, money is marked captured, state transitions to `PAYMENT_CAPTURED_BOOKING_FAILED`, and a P0 task is generated for the Clinic Manager with a 1-click retry action.

---

## 3. The 10 Critical Failure Modes & How They Are Solved

Here are the 10 real-world failure scenarios you should present during your interview:

```
┌────┬───────────────────────────────────────────┬────────────────────────────────────────────────────────┐
│ #  │ FAILURE SCENARIO                          │ ARCHITECTURAL / CODE SOLUTION                          │
├────┼───────────────────────────────────────────┼────────────────────────────────────────────────────────┤
│ 1  │ Payment Gateway Webhook Replay / Retry    │ In-memory/Redis Idempotency Cache on payment_id        │
│ 2  │ Late Payment After Slot Hold Expired      │ PAYMENT_RECEIVED_SLOT_LOST state + P0 15m Staff SLA    │
│ 3  │ Setmore Calendar API Outage (HTTP 500)    │ PAYMENT_CAPTURED_BOOKING_FAILED + 1-Click Sync Retry   │
│ 4  │ Forged / Tampered Webhook Attack          │ HMAC-SHA256 constant-time verification                │
│ 5  │ Couples Shared-Phone Record Leakage       │ Unique Patient MRN + Multi-Profile PIN selector        │
│ 6  │ WhatsApp Lock-Screen Diagnostic Stigma    │ Privacy-preserving message templates                   │
│ 7  │ Diagnostic Lab Uploads Critical Result    │ Automated dispatch hard-stop + Clinician Urgent Gate   │
│ 8  │ Missed Inbound Patient Call / Lost Lead   │ Webhook capture + WhatsApp ack + 30m Staff SLA timer   │
│ 9  │ Acute Psychiatric Emergency / Crisis      │ Regex/NLP red-line match + Tele-MANAS hotline + P0 ping│
│ 10 │ Patient Revokes Consent (DPDP Act 2023)   │ "Reply STOP" webhook halts all proactive cron triggers │
└────┴───────────────────────────────────────────┴────────────────────────────────────────────────────────┘
```

### Deep Dive into the Top 5 Interview Failures:

#### Failure 1: The Payment Webhook Replay Attack / Network Retry
* **The Problem**: Payment gateways (Razorpay, Stripe) retry webhooks up to 5 times if the clinic's server takes $>5$ seconds to respond. Without protection, a patient could be billed twice or have multiple duplicate slots created on the calendar.
* **Our Solution**: Idempotency Key Guard. The system inspects `payment_entity["id"]`. If it already exists in the processed set or Redis cache, the system returns HTTP 200 OK with `"Duplicate webhook ignored (idempotent)"` without executing downstream booking calls.

#### Failure 2: The Race Condition (Late Payment after Hold Expired)
* **The Problem**: A patient is given a 15-minute hold on Friday 11:00 AM. They walk away, eat lunch, and pay via UPI 30 minutes later. In the interim, a walk-in patient at the clinic booked that same slot.
* **Our Solution**: The state machine checks the slot status at the exact millisecond the webhook arrives. Detecting a conflict, it transitions to `PAYMENT_RECEIVED_SLOT_LOST`. It does **not** crash or double-book. It immediately creates a P0 Staff Task with a 15-minute SLA for the receptionist to call the patient, offer an alternate slot, or issue a 1-click refund.

#### Failure 3: Upstream Calendar Outage (Payment Captured, Booking Failed)
* **The Problem**: Razorpay successfully captures ₹2,500 from the patient's bank account, but Setmore's API times out or returns HTTP 500.
* **Our Solution**: The transaction is wrapped in an atomic try-catch block. The payment is recorded as `CAPTURED`. The booking state switches to `PAYMENT_CAPTURED_BOOKING_FAILED`. An instant P0 task alerts the Clinic Manager with full metadata (`payment_id`, `patient_id`, `slot_id`), and the patient receives a reassuring message: *"Payment received! We are registering your appointment on the calendar and will update you shortly."*

#### Failure 4: Shared-Phone Identity Contamination
* **The Problem**: A husband and wife are both seeing therapists at the clinic for relationship counseling. The husband texts from their shared home number asking for his appointment history.
* **Our Solution**: The phone number is decoupled from identity. The database maps `Phone -> [PatientProfile A, PatientProfile B]`. When an inbound chat arrives, the bot prompts: *"Are you contacting us regarding 1) Sameer or 2) Pooja?"* Accessing clinical notes or history requires a 4-digit discrete security PIN.

#### Failure 5: Acute Psychiatric Crisis / Red-Line Detection
* **The Problem**: A patient experiencing suicidal ideation or acute sexual assault trauma texts the clinic WhatsApp after hours. An administrative AI bot responding with *"Our hours are 9 AM to 6 PM"* could lead to fatal consequences.
* **Our Solution**: The NLP layer evaluates messages against clinical emergency patterns (self-harm, suicide, severe domestic trauma). If triggered, the administrative bot immediately silences itself, sends a hardcoded crisis response providing national 24/7 helplines (**Tele-MANAS 14416** and **Vandrevala Foundation**), and sends an emergency P0 push notification to the on-call doctor.
