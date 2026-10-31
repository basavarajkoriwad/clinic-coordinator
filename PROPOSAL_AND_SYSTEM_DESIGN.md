# Comprehensive System Design & Architecture Proposal
## Multi-Clinician Sexual Health, Mental Health & Relationship Clinic (Bengaluru)

**Objective**: Reliable patient coordination with minimal repetitive staff work, ensuring no pending patient request becomes invisible, while guaranteeing medical-grade privacy and discretion.

---

## 1. Calls and WhatsApp Reception

### 1.1 Preserving the Single Existing Mobile Number
The clinic currently operates on a single ordinary mobile number for voice calls and the WhatsApp Business app.

#### Technical Execution
1. **WhatsApp Plane Migration**:
   - The clinic backs up chat history and deletes/deregisters the number from the WhatsApp Business mobile app.
   - The same E.164 phone number is registered with the **Meta WhatsApp Cloud API** via an enterprise Business Solution Provider (BSP) such as Gupshup or Interakt.
   - This unlocks green-tick verification, automated webhook routing, multi-agent access, and eliminates dependency on a single physical phone.
2. **Voice Call Plane Routing**:
   - **Phase 1 (Immediate - Zero Downtime)**: Enable **Unconditional Call Forwarding** (`*21*<Virtual_DID>#`) on the Airtel/Jio physical SIM to forward inbound PSTN calls to an Indian Cloud Telephony provider (Exotel or Ozonetel). Exotel receives the call, captures original caller CLI, routes to IVR / Voice AI, and logs the call.
   - **Phase 2 (Permanent)**: Execute standard Telecom Mobile Number Portability (MNP) to port the number to an enterprise virtual mobile number / SIP trunk.

### 1.2 Routine AI Administrative Reception & Escape Hatches
- **In-Scope for AI**: Clinic location (Indiranagar), operating hours, consultation fees, clinician bios/specializations, service explanations, and guided booking.
- **Escape Hatch**: Typing "agent", "human", "receptionist", or pressing 0 on IVR immediately transfers the session to front-desk staff.
- **Sentiment & Distress Detection**: Inbound distress triggers instant human takeover.

### 1.3 Shared Staff Inbox
- **Multi-Tenant Staff Access**: Individual role-based logins with 2FA for front desk, billing, and managers.
- **Assignment Rules**: Inquiries auto-route by service or round-robin; staff can manually reassign.
- **Internal Notes & Whispers**: Staff can collaborate with private internal notes hidden from patients.
- **AI Handover**: Staff typing in a conversation automatically mutes the AI bot for that patient.

### 1.4 Call Capture & Callback Task SLA
- All answered and missed calls link to the patient's record.
- Every missed call immediately sends a discrete WhatsApp acknowledgment and creates a **Callback Task** on the staff dashboard with a **30-minute SLA countdown**.
- If unaddressed at 20 minutes, an automated escalation alerts the Clinic Manager.

---

## 2. Booking and Payments

### 2.1 The Booking & Payment Flow
1. Patient selects clinician, service, and slot.
2. Coordinator places a **15-Minute Soft Hold (TTL Lock)** on the slot and creates a Razorpay payment order.
3. Patient receives a discreet WhatsApp payment link (e.g. ₹2,500).
4. Patient pays via UPI / NetBanking / Cards.
5. Razorpay fires a cryptographically signed webhook (`order.paid`).
6. Coordinator verifies HMAC-SHA256 signature, confirms slot in Setmore API, and dispatches a discrete WhatsApp confirmation with a GST-exempt receipt.

### 2.2 Answers to Key Clinic Questions
- **Can a slot be held while payment is pending?** Yes. An atomic 15-minute TTL hold is enforced in the state machine.
- **Can verified payment trigger booking automatically?** Yes. Verified webhooks trigger instantaneous Setmore API confirmations.
- **Which payment gateway and billing software?** **Razorpay** (or Cashfree) for UPI/cards; **Zoho Books** / custom receipt generator. Invoices display SAC 9993 and statutory GST exemption under *Notification No. 12/2017-CT(Rate) Sl. No. 74*.
- **Can invoices and receipts be sent automatically?** Yes, as auto-generated discrete PDFs.
- **Why screenshot verification is banned**: Vulnerable to fake UPI apps, causes operational bottlenecks, and risks leaking patient financial data.

### 2.3 Exception Handling & P0 Staff Tasks
- **Payment Captured but Booking Failed**: P0 Task generated with 10-minute SLA and 1-click retry.
- **Late Payment / Slot Stolen**: P0 Task generated with 15-minute SLA to reassign slot or issue instant refund.
- **Duplicate Payment**: Excess transaction automatically flagged for refund.

---

## 3. Appointment Reminders
- **Cadence**: 72 hours before, 24 hours before, and 8:00 AM on appointment day.
- **Interactive Quick Replies**: [Confirm Attendance], [Request Reschedule], [Speak to Clinic].
- **Dynamic Rules**: Short-notice bookings omit elapsed reminder intervals; rescheduling recalculates schedules; cancellation terminates triggers.
- **Lockscreen Discretion**: Notifications state *"Upcoming consultation with Dr. Sharma at The Bengaluru Clinic"*—never disclosing diagnostic terms like sexual dysfunction or psychiatric illness.

---

## 4. Lab Reports and Review Appointments
- **Reception**: Encrypted webhook / SFTP ingestion from diagnostic labs (e.g., Neuberg, Dr Lal PathLabs) tied to patient MRN.
- **Clinician Authorisation Gate**: Reports remain in `UNAUTHORISED` status until the ordering doctor reviews them.
- **Delivery Protocol**: Zero raw PDFs sent directly over WhatsApp. Instead, a **Secure Expiring Link (7-day TTL)** with **2FA OTP verification** is delivered.
- **Urgent / Critical Results**: System blocks automated release. Status switches to `CLINICAL_ESCALATION` requiring direct clinician telephone counseling.
- **Review Booking**: Releasing a report with a review recommendation automatically includes a 1-click booking invite.

---

## 5. Patient Tracking and Follow-ups

### 5.1 Shared Phone Number Privacy Architecture
- **Primary Key**: Unique Patient ID (`MRN-XXXXX`), never the phone number.
- **Resolution**: A phone number maps to multiple patient profiles. On chat initiation, the bot prompts: *"Are you contacting us regarding: 1) Sameer, 2) Pooja, or 3) Someone new?"* Access to past records requires a 4-digit security PIN.

### 5.2 The 9 Lost-to-Follow-up Cohorts
1. Enquired but never booked (24h courtesy nudge)
2. Sent payment link but not paid (2h reminder)
3. Paid but booking failed (P0 Emergency)
4. Cancelled or No-Show (DNA check-in)
5. Awaiting staff/clinician response (20m SLA breach alert)
6. Reports pending in lab > 48h
7. Report received but review unbooked after 48h
8. Overdue for 4-week medication review
9. Stopped planned course of therapy sessions

### 5.3 Consent & DPDP Act 2023
- Explicit opt-in at registration.
- Unconditional opt-out: Replying `STOP` immediately disables proactive tracking.

---

## 6. Dashboard and Staff Accountability
- **Live Real-Time View**:
  - P0/P1 Exceptions with countdown timers.
  - Missed calls and pending callbacks.
  - Today's appointment schedule & attendance.
  - Reports awaiting clinician release.
- **Patient 360 View**: Chronological audit trail distinguishing automated system updates (blue) from manual staff entries (green, with staff identity).
- **Digests**: Daily 8:30 AM and 7:00 PM operational summaries to management.

---

## 7. AI Scope, Privacy, and Human Oversight
- **Boundary**: Administrative coordination only. AI never diagnoses, prescribes, or interprets tests.
- **Crisis Protocol**: Keywords regarding self-harm, suicide, or assault immediately trigger scripted responses with national helplines (**Tele-MANAS 14416**, **Vandrevala Foundation**), create a P0 emergency task, and alert the on-call doctor.
- **Privacy & Compliance**: Zero model training guarantee (Enterprise LLM with Zero Data Retention), TLS 1.3 transit encryption, AES-256 storage, and strict RBAC separating front desk from clinical notes.
