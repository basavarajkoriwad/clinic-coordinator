# 5-Minute Client Presentation Guide & Demo Script
## How to Pitch This Solution to the Clinic Leadership

Use this quick guide when presenting to your clients in VS Code or in a meeting.

---

### Step 1: Open the Project in VS Code
In your PowerShell terminal:
```powershell
code "$HOME\Documents\clinic-coordinator"
```

---

### Step 2: The 30-Second Elevator Pitch
> *"We designed a coordination engine specifically tailored for a sensitive sexual health, mental health, and relationship clinic in Bengaluru. It solves three critical operational challenges:*
> 1. *It eliminates repetitive staff workload by automating slot holds, payment collection, and calendar bookings.*
> 2. *It ensures no patient request becomes invisible through guaranteed callback SLAs and real-time P0/P1 staff exception dashboards.*
> 3. *It guarantees patient discretion and privacy—ensuring couples sharing one phone never have their medical notes mixed up, and lockscreen messages never reveal stigmatizing medical diagnoses."*

---

### Step 3: The 2-Minute Live Code Demonstration
Open the VS Code integrated terminal (`Ctrl + ~`) and run:
```powershell
python demo.py
```

Point out the two scenarios to your client:
1. **Scenario 1 (The Happy Path)**:
   - Show how the patient receives a discrete payment link with a 15-minute hold.
   - Show how the payment gateway webhook verifies the transaction using HMAC cryptography and automatically confirms the appointment on Setmore.
2. **Scenario 2 (The Failure Case)**:
   - Explain: *"What happens if a patient pays late after their slot hold expired and someone else took the slot?"*
   - Show how the coordinator catches this race condition, prevents double-booking the doctor, and immediately creates a **P0 Emergency Task** on the staff dashboard with a 15-minute SLA.

---

### Step 4: The 1-Minute Automated Test Verification
Run:
```powershell
python run_tests.py
```
Show the client:
> *"We have written automated tests covering every failure mode—including upstream API outages, late payments, replay attacks, and shared-phone number disambiguation. All 7 tests pass 100%."*

---

### Step 5: Walk Through the Complete System Design Document
Open `PROPOSAL_AND_SYSTEM_DESIGN.md` in VS Code and press `Ctrl + Shift + V` to view the formatted proposal covering:
1. Keeping the existing phone number via WhatsApp Cloud API and Call Forwarding/MNP.
2. Razorpay integration and GST-exempt healthcare invoicing (SAC 9993).
3. Secure OTP-protected lab report links (no raw PDFs on WhatsApp).
4. Crisis escalation protocols (Tele-MANAS helpline routing).
5. Indian DPDP Act 2023 compliance and Zero Model Training guarantees.
