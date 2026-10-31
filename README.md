# The Bengaluru Clinic — Patient Coordination & Booking Coordinator

Production-grade patient coordination system and booking state machine for sensitive healthcare (sexual health, CBT, and psychiatry) in Bengaluru.

Built with pure Python standard library on the backend (`http.server`) and vanilla HTML/Tailwind CDN on the frontend. No npm or external pip packages required.

---

## Quick Start: Running the Web App

1. **Start the local web server:**
   ```powershell
   python app.py
   ```

2. **Open the applications in your browser:**
   - **Patient WhatsApp Interface & Presenter Simulation Bar:**
     [http://localhost:8000](http://localhost:8000)
   - **Staff Operations Cockpit (Read-Only Live Exception Dashboard):**
     [http://localhost:8000/staff](http://localhost:8000/staff)

---

## Running the Full Test Suite (116 Tests)

The comprehensive test suite is structured into four testing layers according to industry standards:
- **`tests/unit/`**: Isolated unit tests for models, mock service adapters, and coordinator helpers (PBKDF2 salt/hashing, constant-time compare, name validation with Unicode, crisis regex, OTP generation/expiry, audit hash chain).
- **`tests/integration/`**: Cross-module integration tests (happy path booking, 15-minute hold sweep, late payment slot conflicts, Setmore 500 outage with 60m hold extension & retry escalation, webhook security, shared-phone PIN gate, crisis intercept, 20-thread concurrency race).
- **`tests/system/`**: End-to-end tests driving the running HTTP server over network sockets (verifies every endpoint, status codes, Cache-Control no-store, absence of wildcard CORS headers, read-only staff page, and full multi-step user journeys).
- **`tests/acceptance/`**: Business requirements written as executable scenarios.

### Execution Options:
- **Option 1: Using the automated runner:**
  ```powershell
  python run_tests.py
  ```
- **Option 2: Using standard unittest module:**
  ```powershell
  python -m unittest discover -s tests -v
  ```
- **Option 3: Directly from VS Code Testing Panel:**
  Open VS Code in this directory. The `.vscode/settings.json` is preconfigured to discover all 116 tests across the `tests/` hierarchy. Run or debug them with 1-click in the Testing sidebar.

---

## VS Code Launch Configurations

Preconfigured in `.vscode/launch.json`:
- **Run clinic app (`app.py`)**: Starts the web server on `http://127.0.0.1:8000`.
- **Run tests (`run_tests.py`)**: Executes the entire 47-test test suite and outputs test results.
- **Run CLI Interactive Demo (`demo.py`)**: Runs terminal-based interactive walkthrough.

---

## Key Features

- **Patient Choice Flow:** Patient types their own name, reviews available clinicians with live fees/durations, and selects time slots.
- **Name Persistence:** First name (`patient_greeting`) is stored and reused across every message, reminder, task, and audit entry.
- **Privacy & Safety:** Staff dashboard displays only first name and last 4 digits (`FirstName (****Last4)`).
- **Zero Premature Holds:** 15-minute countdown hold only locks upon explicit user confirmation.
- **P0 Exception Safeguards:** Auto-detects late payments (slot lost) and Setmore 500 outages with 1-click staff resolutions.
- **Psychiatric Crisis Intercept:** Immediate word-boundary regex detection, AI muting, emergency 24/7 helplines, and 5-min SLA psychiatrist task.

# TASK: Upgrade "The Bengaluru Clinic" demo: working scenarios, call option, cursor fix, separate read-only staff dashboard

You are editing an existing project IN PLACE in this workspace. Do all the work end to end: edit the files, run the server, test in the browser, fix what breaks, and only then report back. Do not ask me clarifying questions; where something is ambiguous, follow the decisions written below. Do not stop at a plan.

## 0. Project context (what exists today)
- Backend: pure Python, standard library only (`http.server`). Files: `app.py` (web server + API), `src/models.py`, `src/mock_services.py`, `src/coordinator.py` (booking state machine), `src/failure_scenarios.py`, a CLI demo script, a unittest runner that discovers `tests/`.
- Frontend: one file, `index.html` (HTML + Tailwind via CDN + a `<script>` block of vanilla JavaScript). No framework. Keep it that way: no npm, no build step, no new Python packages.
- Current layout: left = WhatsApp phone mockup (patient), right = staff dashboard, top = "Presenter Simulation Bar" with 6 buttons (Happy Path, Late Payment, Setmore 500 Outage, Shared Phone PIN Gate, Psychiatric Crisis Intercept, Lab Report 2FA) + Reset.
- Keep the existing dark Tailwind visual style, fonts, colours and phone mockup design.

## 1. Problems to fix (observed behaviour)
1. Clicking "Late Payment / Slot Lost", "Setmore 500 Outage", "Shared Phone PIN Gate" or "Psychiatric Crisis Intercept" only sends the chat message "I want to book an appointment" and shows booking buttons. It should run that scenario and show the problem AND its solution.
2. After clicking Happy Path, the other buttons are blocked. After Reset the cursor on buttons is wrong (hand vs arrow). Root cause to fix: `updateSimulatorButtonsUI` uses `pointer-events-none`, which prevents the `not-allowed` cursor from ever showing; and only the 'happy' scenario disables the other buttons, while scenarios 2-6 set `activeScenario` and then silently ignore clicks (`console.warn`) while the cursor still shows a hand.
3. The staff dashboard is currently fake, client-side-only HTML mixed into the booking page, with hardcoded numbers and buttons that mutate state. It must become a separate, read-only, backend-driven view.
4. The WhatsApp header phone icon does nothing. There is no way to call the clinic from the chat.

## 2. Requirements already agreed (must be included)
- When a patient is sent to pay, NO slot day/time and NO orange "Slot Reserved" countdown banner is shown to the patient anywhere on the WhatsApp screen. The payment message contains only: the secure payment link, a reminder that they have 15 minutes to pay and the hold expires automatically if not, and that confirmation will be sent after successful payment. Remove the `holdBanner` element and its JS. The 15-minute hold still runs on the BACKEND (existing TTL + expiry worker thread).
- Hold-expiry message (backend `expire_stale_holds` and frontend) must not mention slot day/time: only that the payment window ended, the hold was released, and they can book again. Fix the "Dr. Dr." double prefix bug wherever a clinician name is formatted (use a helper `format_doctor_name()` that adds "Dr. " only if missing).
- Both appear in `src/coordinator.py` (`initiate_booking`, `expire_stale_holds`) and `index.html` (`startBooking`, hold timer expiry notice).

## 3. Target architecture
```
app.py                    API + static serving; ThreadingHTTPServer
src/coordinator.py        state machine + new methods below + audit log + RLock
src/models.py             new fields/enums below
src/mock_services.py      small additions below
src/failure_scenarios.py  reuse intercept_psychiatric_crisis, SecureReportVault
src/simulator.py          NEW: server-side scenario runner (step based)
index.html                patient WhatsApp simulator + Presenter bar ONLY
staff.html                NEW: read-only staff dashboard, served at /staff
tests/                    update + add tests
```
- `index.html` in "Split Mode" shows the staff dashboard by embedding `<iframe src="/staff">` in the right pane (so the demo keeps the two-pane look). "Patient View" hides the iframe. "Staff View" shows only the iframe full width. Also add an "Open Staff Dashboard" link that opens `/staff` in a new tab.
- The staff dashboard must have ZERO code paths that change booking state. It only reads `GET /api/dashboard` (poll every 2 seconds, show a "Last updated" time and a red "Disconnected" pill if the fetch fails).

## 4. Backend work

### 4.1 Server hardening (app.py)
- Use `ThreadingHTTPServer`. Add `threading.RLock` to the coordinator and wrap every coordinator call (handlers and the expiry worker) in `with coordinator.lock:`.
- Wrap every `do_GET`/`do_POST` body in try/except returning clean JSON errors (400 for bad input/JSON/Content-Length, 404, 500). Validate required fields on `/api/book_slot` instead of defaulting to a fake patient.
- Remove `Access-Control-Allow-Origin: *` (frontend is same-origin).
- Serve `/` -> `index.html`, `/staff` -> `staff.html`.
- Extend the background worker to also call `coordinator.escalate_overdue_tasks()` every 10s (see 4.4).

### 4.2 Data model additions (src/models.py)
- `PatientProfile`: add `pin_salt`, `pin_hash`, `failed_pin_attempts: int = 0`, `locked_until: Optional[datetime] = None`.
- `TaskStatus` already has ESCALATED; make `TaskManager.get_open_tasks` keep including it.
- Add `AuditEntry` dataclass: `seq, timestamp, category, message, prev_hash, hash`.

### 4.3 Audit ledger (coordinator)
- `self.audit_log: List[AuditEntry]`, method `audit(category, message)` that appends an entry whose `hash = sha256(prev_hash + timestamp + category + message)` (genuinely append-only hash chain, so "immutable ledger" is truthful). Call it on EVERY state transition, task creation/resolution/escalation, call event, security event, webhook result. Never put full phone numbers, diagnoses or clinical specialty in audit text: use patient_id and last 4 digits only.

### 4.4 New coordinator methods
- `retry_failed_booking(booking_id, staff_id)`: for state PAYMENT_CAPTURED_BOOKING_FAILED. Re-attempt `setmore.confirm_appointment`. On success: CONFIRMED, send confirmation WhatsApp, resolve the related task. On failure: increment `booking.retry_count`; after 2 failed retries mark the task ESCALATED and add a note recommending manual calendar entry or refund.
- `resolve_slot_lost(booking_id, action, staff_id, new_slot_id=None)`: `action="reschedule"` -> hold+confirm the new slot, CONFIRMED, WhatsApp confirmation, resolve task. `action="refund"` -> `gateway.process_refund`, state REFUND_PENDING then REFUNDED, WhatsApp refund notice, resolve task.
- `escalate_overdue_tasks()`: any OPEN task past `due_date` becomes ESCALATED (priority unchanged) and is audited once. Dashboard shows these as "SLA BREACHED".
- `extend_hold` (mock_services): when payment is captured but Setmore fails, extend the slot hold to 60 minutes so another patient cannot take a slot that someone has already paid for.
- Fix late-payment detection in `handle_payment_webhook`: if the hold expired and the slot is no longer available to THIS booking (booked by another OR actively held by another), take the slot-lost path. If the hold expired but the slot is still free, confirm normally.
- In the webhook: reject events other than `order.paid`; verify the captured amount equals `booking.payment.amount_inr * 100`; wrap payload parsing in try/except so a signed-but-malformed body returns a clean error; add the payment_id to `processed_payment_ids` only AFTER the booking attempt has been recorded.
- Shared phone PIN: `set_patient_pin(patient_id, pin)` (PBKDF2-HMAC-SHA256, per-patient random salt via `secrets`), `verify_patient_pin(patient_id, pin)` using `hmac.compare_digest`; 3 wrong attempts -> `locked_until = now + 15 min`, create a P1 task "Identity verification by phone required" for FrontDesk_Lead, audit it; success resets the counter.
- Crisis: per-phone `ai_muted_phones: set`. While a phone is muted, `/api/chat/message` returns no automated bot content for it, only a single calm line the first time ("A member of our clinical team is reaching out to you."). Only `resolve_crisis(task_id, staff_id)` un-mutes.
- Call events: `handle_inbound_call` already exists; make sure answered and missed calls are both added to a `self.call_log` list and audited.

### 4.5 New API endpoints
- `GET  /api/dashboard` -> one snapshot: `metrics` (p0_active, p1_active, callbacks_due, confirmed_today, escalated, awaiting_payment), `tasks` (open + last 10 resolved, each with priority, status, title, description (no full phones), owner, due_date, seconds_remaining, breached), `bookings` (id, patient discrete name, clinician name, state, payment status, created_at; no clinical specialty), `slots`, `clinicians`, `calls` (last 20), `audit` (last 100 with seq + hash prefix).
- `POST /api/chat/message` `{phone, text}` -> runs `intercept_psychiatric_crisis` FIRST (use word-boundary regex, include: suicide, suicidal, kill myself, end my life, ending my life, want to die, hang myself, self harm, self-harm, "can't go on"), then human-handover detection, then normal intent routing; returns `{replies:[{text, buttons?, kind}], ai_muted}`. Fix the front-end's old `low.includes('die')` false positive ("diet", "studied") by removing client-side crisis detection entirely: the backend decides.
- `POST /api/phone/resolve` `{phone}` -> `{status, profiles:[{patient_id, discrete_name}]}` (first names only, NO service/specialty info, because the phone is shared).
- `POST /api/phone/verify_pin` `{patient_id, pin}` -> `{ok, attempts_left, locked, appointments?}`; on success return only that patient's upcoming appointments with discreet wording.
- `POST /api/simulate/pay` `{booking_id}` -> DEMO ONLY: builds the signed webhook server-side and passes it through the real `handle_payment_webhook`. Label it clearly as demo-only in code comments.
- `POST /api/simulate/reset` -> rebuilds all state (new coordinator, seed clinicians/slots/patients, clears audit, call log, mutes) and returns ok.
- `POST /api/simulate/<scenario>` `{step, choice?}` for `happy`, `late_payment`, `setmore_outage`, `shared_phone`, `crisis`, `lab_report` (see section 6). Returns `{step, done, delay_ms, chat:[...], audit_note, explain:{...}, choices?:[...]}`.
- `POST /api/call/inbound` and `/api/call/outbound` keep working.
- Seed data (in a `seed_demo_data()` function reused by reset): Dr. Ananya Sharma (SLOT-101 tomorrow 11:00, SLOT-103 tomorrow 16:00), Dr. Rajesh Rao (SLOT-202 tomorrow 14:00), demo patient Rohan (+919888811111), shared-phone couple Pooja and Sameer Kulkarni on +919876500000 with demo PINs 4321 and 8765, a pre-existing missed-call task so the dashboard is not empty. Compute dates from today, never hardcode "Friday, 31 October 2026".

## 5. Frontend work: index.html (patient simulator + presenter only)
- Remove the staff column markup, fake metric cards, fake task cards, fake audit log and all of their JS (`createTaskCard`, `resolveTask`, `appendAudit` writing to DOM, etc.). Staff data now lives only in `staff.html`.
- All booking actions call the backend: `startBooking` -> `POST /api/book_slot`; payment modal confirm -> `POST /api/simulate/pay`. Render the WhatsApp text returned by the backend, not text duplicated in JS.
- Escape/neutralise all text inserted into the chat: use `textContent` / DOM nodes, never `innerHTML` with user text (a message like `<img src=x onerror=alert(1)>` must display literally). Button onclick strings must be replaced by `addEventListener` with closures.
- Define at top: `const CLINIC_PHONE = "+918040000000"` (placeholder, clearly commented as replaceable) and a `currentPatient` object (name, phone). Do not reuse a patient's number as the clinic number.
- Make "Chime" toggle, view switcher and quick-action pills work with the new structure. Add a "Call Clinic" quick-action pill.

## 6. Scenario behaviour (each must show the PROBLEM, the SAFEGUARD, and the SOLUTION)
General rule: clicking a scenario button calls `POST /api/simulate/<scenario>` with step 0, then plays the following steps automatically with `delay_ms` between them (typing indicator before each clinic message). Each step really executes on the backend, so the staff dashboard updates for real. Alongside the phone, show a "Scenario Explainer" card (in index.html under the presenter bar) filled from `explain`: Problem / How the system detects it / Automatic safeguard / Staff action / Patient outcome, with a step progress indicator (Step 2 of 5). Steps that need a decision return `choices`, rendered as buttons in the explainer card (presenter picks).

1. **Happy Path:** patient asks to book -> clinician + slot buttons -> hold + payment link message (no day/time, no banner) -> patient pays in the modal -> signed webhook -> CONFIRMED -> confirmation WhatsApp with receipt link. Dashboard: booking goes PAYMENT_PENDING -> CONFIRMED.
2. **Late Payment / Slot Lost (P0):** (a) patient books and receives link; (b) backend time-travels the hold 20 min back and the expiry worker releases it, patient gets expiry message; (c) a walk-in patient books the same slot (real second booking); (d) original patient pays anyway: webhook -> PAYMENT_RECEIVED_SLOT_LOST, P0 task (15 min SLA, FrontDesk_Lead), reassurance WhatsApp, calendar double-booking prevented; (e) `choices`: "Reschedule to alternate slot (SLOT-103)" or "Issue instant refund" -> calls `resolve_slot_lost`, task resolved, patient gets the matching WhatsApp. Explainer must say why money is never lost and nobody is double-booked.
3. **Setmore 500 API Outage (P0):** (a) patient books; (b) Setmore failure injected; patient pays -> payment captured, Setmore returns 500 -> PAYMENT_CAPTURED_BOOKING_FAILED, slot hold extended to 60 min, P0 task (10 min SLA, Clinic_Manager), reassurance WhatsApp; (c) `choices`: "Retry sync while Setmore is still down" (fails, retry_count 1, then 2 -> task ESCALATED with recommendation: manual calendar entry or refund) and "Retry after Setmore recovers" (turns failure off, `retry_failed_booking` succeeds, CONFIRMED, confirmation WhatsApp, task resolved).
4. **Shared Phone PIN Gate:** message arrives from +919876500000 -> `/api/phone/resolve` -> MULTIPLE_PROFILES -> chat shows first-name buttons only ("I am Pooja" / "I am Sameer"), NO therapy/specialty labels -> chosen profile triggers a PIN prompt; while in PIN mode the chat input becomes `type="password"`, numeric, 4 digits, placeholder "Enter 4-digit PIN" and the typed digits are never echoed in the chat bubble (show "••••") -> `/api/phone/verify_pin`. Wrong PIN: "Incorrect PIN. 2 attempts left." Correct PIN: only that person's upcoming appointments in discreet wording. 3 wrong: lockout message, P1 task for identity verification by phone, audit entry. The explainer shows the demo PINs (4321 Pooja, 8765 Sameer), labelled "demo only". Provide presenter `choices` shortcuts: "Enter correct PIN", "Enter wrong PIN", "Fail 3 times".
5. **Psychiatric Crisis Intercept (P0):** patient message (typed or scripted: "I cannot take this pain anymore, I feel like ending my life tonight") goes to `/api/chat/message` -> intercept -> chat shows a calm, caring message with Tele-MANAS 14416 (24/7, free) and Vandrevala Foundation +91 9999 666 555 (24/7), each as a tappable call button (`tel:` link) plus "Call The Bengaluru Clinic". Backend: AI muted for that phone, P0 task (5 min SLA, Duty_Psychiatrist). The chat only says the on-call clinician "has been alerted" if the backend response actually contains the created task id. Further patient messages get no bot booking replies. `choices`: "Duty psychiatrist calls patient" -> `resolve_crisis`, task resolved with note, AI un-muted. If the task passes its 5-minute SLA unresolved the worker escalates it and the dashboard shows "SLA BREACHED". Tone: no bullet-point spam in the patient message, no dismissive language.
6. **Lab Report 2FA Vault:** keep working through the same mechanism. Generate the OTP with `secrets.randbelow` (per token, 5-minute expiry, max 3 attempts), never one hardcoded OTP for everyone; show the OTP only in the explainer card as "demo only", not in the chat. Add a dashboard metric for reports pending.

## 7. Presenter bar: state machine and cursor fix
- Implement ONE controller `setScenarioState(active)` used by every scenario. `active` is `null` or the scenario id.
- When `active !== null`: ALL six scenario buttons (including the active one) are set `disabled`, the active one gets a visible ring + "Running" label, the others get `opacity-40` and `cursor-not-allowed`, each with `title="Scenario running. Click Reset to start another."`. Reset stays enabled.
- Do NOT use `pointer-events-none` anywhere (it hides the cursor). Use the `disabled` attribute plus Tailwind `disabled:cursor-not-allowed disabled:opacity-40`; enabled buttons use `cursor-pointer`.
- Remove the silent `console.warn` early-return. Disabled buttons simply cannot be clicked.
- Reset must: call `POST /api/simulate/reset`, clear chat, stop all timers, clear pending timeouts (keep an array of timeout ids and clear them), reset the explainer card, restore all buttons (`removeAttribute('disabled')`, remove every added class and the title), restore pointer cursor, re-post the welcome message. Verify clicking each scenario works again after Reset, repeatedly, in any order.
- When a scenario finishes, show "Scenario complete. Click Reset to run another." in the explainer card (buttons stay locked until Reset, as before).

## 8. Call option in WhatsApp
- Header phone icon becomes a real `<button>` with `aria-label="Call clinic"`. Also add the "Call Clinic" quick pill and a "Call us" button in bubbles where it makes sense (missed-call ack, crisis message, payment-problem messages).
- Click opens an in-phone call overlay: avatar, "The Bengaluru Clinic", "Calling..." ringing animation (2.5 s), then a presenter choice inside the overlay: "Clinic answers" or "No answer". "Clinic answers" -> `POST /api/call/inbound` with ANSWERED, overlay shows a running call timer and an "End call" button, call logged. "No answer" -> MISSED, overlay closes, chat receives the backend's WhatsApp acknowledgement (30-minute callback, or "9:30 AM tomorrow" when after 8 PM / before 9 AM), a P1 callback task appears on the dashboard.
- Also render the number as a `tel:` link so it actually dials on a real phone.

## 9. staff.html: separate read-only dashboard
- Reuse the same dark Tailwind look. Header: clinic name, "Staff Operations Dashboard", a visible "READ-ONLY VIEW" badge, live clock, connection pill, "Last updated hh:mm:ss".
- Sections, all driven by `GET /api/dashboard`: (1) metric cards (P0/P1 active, callbacks due, confirmed today, SLA breached, awaiting payment); (2) prioritised task queue: sorted P0 -> P3 then by due time, each with priority badge, status badge, owner, description, and a LIVE SLA countdown computed client-side from `seconds_remaining` (turns red and shows "BREACHED +mm:ss" when overdue; P0 rows have the soft pulse); resolved tasks shown dimmed in a collapsible "Recently resolved" list; (3) bookings table with colour-coded state badges (PAYMENT_PENDING amber, CONFIRMED green, HOLD_EXPIRED grey, PAYMENT_RECEIVED_SLOT_LOST / PAYMENT_CAPTURED_BOOKING_FAILED red, REFUNDED blue); (4) clinician rosters with live slot status (Available / Held / Booked); (5) call log (answered/missed, duration, last 4 digits only); (6) audit ledger, newest first, showing seq, time, category colour and hash prefix.
- No action buttons that change data. No hardcoded demo numbers: an empty queue shows "No active alerts".
- Chime on a NEW P0 task (track seen task ids), with a mute toggle.
- Show only discreet first names and last-4 phone digits; never specialty or diagnosis text next to a patient.
- Must work both standalone at `/staff` and inside the iframe.

## 10. Tests
Inspect `tests/` and keep existing tests passing (update tests where I have intentionally changed message text). Add tests for: payment message has no slot date/time; `format_doctor_name` has no double "Dr."; late payment with slot taken -> SLOT_LOST + P0 task; late payment with slot still free -> CONFIRMED; Setmore failure -> FAILED state + extended hold + retry success/escalation; webhook rejects wrong event type and wrong amount; malformed signed payload returns clean error; PIN success, wrong PIN, lockout after 3, lockout expiry; crisis regex catches the phrases above and does NOT trigger on "diet", "studied", "audience"; AI mute/unmute; overdue task escalation; audit chain integrity (recompute hashes). Run the full suite and fix failures.

## 11. Verification (do this yourself before reporting)
1. Run the unit tests: all green.
2. Start `python app.py`, open the app in the browser tool, and click through EVERY scenario one by one with Reset in between; also click scenarios in a different order, and click each twice. Confirm: correct chat output, explainer card content, dashboard updates within ~2 s, buttons lock and unlock, cursor is `not-allowed` on disabled buttons and a hand on enabled ones after Reset.
3. Test the call flow (answered + missed), the PIN flow (wrong, correct, lockout), the XSS string in the chat input, and that no orange "Slot Reserved" banner ever appears.
4. Open `/staff` in a second tab and confirm it updates live while you run scenarios in the first.
5. Check the browser console and the server log for errors. Fix them.

## 12. Deliverable
Reply with: the list of files changed/created, the exact commands to run the app and tests, and a short checklist of each requirement above marked done or not done (with the reason if not). Do not leave TODOs, placeholder functions, or "implement later" comments.




# AMENDMENT TO THE PREVIOUS TASK: patient enters their own name, then chooses a doctor and time from a pop-up

This amendment overrides any conflicting part of the main prompt. Apply it to the same workspace, edit files directly on disk, run and test everything yourself, and do not ask me questions.

## A. New Happy Path flow (patient chooses everything)
The patient must NOT be assigned a name or a doctor by the system. The flow is:

1. Presenter clicks "Happy Path Booking". The chat shows the patient message "I want to book an appointment" (this is the only scripted line).
2. The bot replies: "Welcome to The Bengaluru Clinic. May I have your full name, please?" The chat input placeholder becomes "Type your full name". The Presenter Bar stays locked per the earlier state-machine rules.
3. The presenter/patient TYPES a name in the real chat input. Validate on the backend: 2 to 60 characters, letters, spaces, dots, apostrophes and hyphens only. If invalid, the bot says "Sorry, I could not read that name. Please type your full name again." and keeps waiting. The crisis check (`intercept_psychiatric_crisis`) still runs first on every message, including this one.
4. On a valid name, the bot replies "Thank you, <FirstName>. Here are the doctors available for you." and a **pop-up sheet** slides up inside the phone screen (not a browser alert): title "Available Doctors", a close (X) button, and one card per clinician showing: doctor name (formatted with `format_doctor_name()`), consultation type, session length, fee in ₹, and a row of tappable **time chips** for that doctor's available slots, each labelled with a readable day and time (for example "Tomorrow, 11:00 AM", then "Sat 1 Nov, 4:00 PM"). Only slots that are truly available right now (`check_availability`) are shown. Held or booked slots are not listed.
5. The patient taps a time chip. The sheet shows a short confirm step: doctor, day/time, fee, with "Confirm and get payment link" and "Back" buttons. Closing the sheet without confirming places NO hold.
6. On confirm, call `POST /api/book_slot`. The 15-minute hold starts now (never earlier). If the slot was taken in the meantime, the backend returns 409 with a clear message, the chat says "That time was just taken. Please choose another", and the sheet reopens with a refreshed list.
7. The chat then shows the payment message exactly as defined in the main prompt: secure link, 15-minute reminder, confirmation after payment. NO slot day/time and NO orange banner in this message. (The day/time MAY appear in the doctor pop-up above and in the final confirmation message after successful payment, because the patient needs it there.)
8. Pay modal, webhook, CONFIRMED and the staff dashboard behave as before. The payment amount comes from the chosen doctor's fee. It must no longer be a hardcoded 2,500. Fix the modal total and the button label ("Pay ₹ X") to use the real fee.
9. If no slots are available for any doctor: bot says "No appointments are available right now. Our team will call you back." and creates a P2 callback task. The sheet does not open.
10. If the patient types a name while the same phone already has a profile with that exact name, reuse it (`register_or_get_patient`); a different name on the same phone creates a separate profile (shared-phone behaviour stays).

## B. Remove every hardcoded patient/doctor name
- Search the whole project (`index.html`, `app.py`, `src/*.py`, the CLI demo, `tests/`) for these strings: Rohan, Rohan Mehta, Rohan Verma, Arjun, Arjun Nair, Meera, Meera Joshi, Meghali, Kavita, Pooja, Sameer, Priya, "Dr. Sharma", "Dr. Ananya", "Dr. Rajesh".
- Real (non-demo) flows must take names ONLY from the patient's typed input (stored in `currentPatient` on the frontend and in the `PatientProfile` on the backend) and from the clinician records (`Clinician.name`). Every message, task title, audit entry and expiry notice must use `patient.discrete_name` (first name) or `format_doctor_name(clinician.name)`.
- Fix `failure_scenarios.py` so the expiry nudge no longer says "Dr. Sharma" (use the booking's clinician, or a generic phrase).
- Remove the `app.py` fallback defaults ("Rohan Mehta", fake phone, default clinician and slot). Missing patient_name, patient_phone, clinician_id or slot_id returns 400.
- Scripted demo personas for scenarios 2 to 6 may exist ONLY in one backend constant `DEMO_PERSONAS` in `src/simulator.py` (name, phone, PIN for the shared-phone couple). The frontend must read persona names from the API response and contain no patient names. In scenarios 2, 3 and 6 the explainer card labels the persona "Demo patient". Add a one-line comment saying they are demo data only.
- The CLI demo scripts and the `if __name__ == "__main__"` blocks may keep sample names, but each must be marked with a comment `# DEMO DATA ONLY`.
- Run a final grep for the strings above and show me the output in your report, listing any remaining occurrence and why it is allowed.

## C. Backend changes
- New `GET /api/availability` returning clinicians with: `clinician_id`, `display_name` (via `format_doctor_name`), `service_label` (patient-friendly, for example "Therapy session" or "Psychiatric consultation"), `duration_minutes`, `fee`, and `slots:[{slot_id, start_iso, label}]` (available only, sorted by time). Do not expose internal fields like `setmore_staff_key`.
- `GET /api/slots` stays for compatibility but must use the same availability check.
- Seed in `seed_demo_data()`: at least 3 future slots per clinician across the next 2 working days (clinic is Mon to Sat, 9 AM to 8 PM; skip Sundays), computed from today's date. Keep SLOT-101, SLOT-103 and SLOT-202 ids so earlier scenarios still work. Different doctors have different fees and durations.
- `POST /api/chat/message` gains a per-phone conversation state (`AWAITING_NAME`, `AWAITING_SLOT`, `IDLE`) stored in the coordinator (under the lock). In `AWAITING_NAME` it validates the name, registers the patient, switches to `AWAITING_SLOT` and returns a reply of `kind: "doctor_picker"` containing the availability payload so the frontend opens the sheet.
- `POST /api/book_slot` returns 409 (not 400) when the slot is unavailable. It validates that the slot belongs to the clinician sent.
- Reset clears conversation state.

## D. Frontend changes (index.html)
- Add the doctor pop-up sheet (bottom sheet inside the phone screen, dark text on light WhatsApp-style card, matching the existing look), with the time chips, confirm step, close button, Escape key support, and focus trapping. Build all DOM with `createElement`/`textContent` (no `innerHTML` with any user or API text).
- Chat input supports a "name entry" mode (placeholder, 60 char limit, shows what the patient types normally) like the existing PIN mode, and returns to normal after.
- Replace the hardcoded `startBooking('Dr. ...', 'SLOT-101', ...)` buttons in fees/booking replies, expiry notices and everywhere else: those buttons now just reopen the doctor pop-up from `/api/availability`.
- The quick-action pill "Book Appointment" and typing "book" or "appointment" in the chat both start this same flow (ask name first only if `currentPatient` is empty; if the name is already known, greet by name and open the pop-up directly).
- The 15-minute expiry message offers a single "Choose another time" button that reopens the pop-up.
- Reset clears `currentPatient`, closes the sheet and restores the chat input.

## E. Tests
Add tests for: valid and invalid names; name flow state transitions (`AWAITING_NAME` to `AWAITING_SLOT`); availability endpoint excludes held and booked slots and exposes no internal keys; booking returns 409 on a taken slot; the fee in the payment record equals the chosen clinician's fee; no hold exists before the patient confirms a slot; no hardcoded patient names in any outbound WhatsApp text (build messages for a patient called "Zoya Menon" and assert the text contains "Zoya" and none of the old names); crisis text typed as the "name" still triggers the crisis path; `format_doctor_name` handles "Dr. X", "dr. x" and "X".

## F. Verification (do it yourself, then report)
1. Run all unit tests: green.
2. Start `python app.py`. Click Happy Path, type the name "Zoya Menon", confirm the pop-up lists every doctor with times, pick a time, confirm, check that the payment message has no day/time and no banner, pay, and confirm the confirmation message uses "Zoya" and the correct doctor and fee.
3. Repeat with a different name after Reset. Try an invalid name (e.g. "12345"), closing the pop-up without choosing (confirm no hold appears on `/staff`), and a slot taken by another booking mid-flow (expect 409 handling).
4. Confirm `/staff` shows the booking under the typed first name, with no hardcoded names anywhere.
5. Show the final grep output from section B and the browser console and server log (no errors).

Report the files changed, the commands to run, and a requirement checklist (done / not done with reason).





CONTEXT: A previous large upgrade has already been applied to this workspace. Before changing anything, open and read the current versions of app.py, index.html, staff.html, src/coordinator.py, src/models.py, src/mock_services.py, src/failure_scenarios.py, src/simulator.py and tests/. Build on what exists. Do not recreate files or rewrite working parts. If something referred to below (format_doctor_name, DEMO_PERSONAS, per-phone chat state, explainer card, setScenarioState) is missing or named differently, adapt to what is there and mention it in your report. Edit files directly on disk, run the tests and the app yourself, do not ask me questions, and keep the staff dashboard read-only.

# TASK: Patient types their own name, then chooses a doctor and time from a pop-up

## A. New Happy Path flow (patient chooses everything)
The system must NOT assign a patient name or a doctor. Flow:

1. Presenter clicks "Happy Path Booking". The chat shows the only scripted line: "I want to book an appointment".
2. Bot replies: "Welcome to The Bengaluru Clinic. May I have your full name, please?" Chat input placeholder becomes "Type your full name" (60 char limit). The Presenter Bar stays locked per the existing state-machine rules.
3. The user TYPES a name in the real chat input. Backend validation: 2 to 60 chars, letters, spaces, dots, apostrophes, hyphens only. If invalid: "Sorry, I could not read that name. Please type your full name again." and keep waiting. The crisis check (`intercept_psychiatric_crisis`) still runs first on every message, including this one.
4. On a valid name, bot says "Thank you, <FirstName>. Here are the doctors available for you." and a **pop-up bottom sheet** slides up inside the phone screen (not a browser alert): title "Available Doctors", close (X) button, one card per clinician showing doctor name (via `format_doctor_name()`), consultation type, session length, fee in ₹, and tappable **time chips** for that doctor's available slots with readable labels (e.g. "Tomorrow, 11:00 AM", "Sat 1 Nov, 4:00 PM"). Only slots where `check_availability` is true right now are shown.
5. Tapping a chip shows a confirm step: doctor, day/time, fee, with "Confirm and get payment link" and "Back". Closing the sheet without confirming places NO hold.
6. On confirm, call `POST /api/book_slot`. The 15-minute hold starts now, never earlier. If the slot was taken meanwhile, backend returns 409, chat says "That time was just taken. Please choose another", and the sheet reopens with a refreshed list.
7. Chat then shows the payment message: secure link, 15-minute reminder, confirmation after payment. NO slot day/time and NO orange banner in this message. (Day/time may appear in the doctor pop-up and in the final confirmation after payment.)
8. Pay modal, webhook, CONFIRMED and the staff dashboard behave as before. Payment amount comes from the chosen doctor's fee. Remove the hardcoded 2,500: modal total and button label ("Pay ₹ X") use the real fee.
9. If no slots are available for any doctor: bot says "No appointments are available right now. Our team will call you back." and creates a P2 callback task. The sheet does not open.
10. A typed name matching an existing profile on the same phone reuses it (`register_or_get_patient`); a different name on the same phone creates a separate profile.

## B. Remove every hardcoded patient/doctor name
- Search the whole project (index.html, app.py, src/*.py, CLI demo, tests/) for: Rohan, Rohan Mehta, Rohan Verma, Arjun, Arjun Nair, Meera, Meera Joshi, Meghali, Kavita, Pooja, Sameer, Priya, "Dr. Sharma", "Dr. Ananya", "Dr. Rajesh".
- Real flows take names ONLY from the typed input (`currentPatient` on frontend, `PatientProfile` on backend) and from `Clinician.name`. Every message, task title, audit entry and expiry notice uses `patient.discrete_name` or `format_doctor_name(clinician.name)`.
- Fix `failure_scenarios.py` so the expiry nudge no longer says "Dr. Sharma" (use the booking's clinician or a generic phrase).
- Remove `app.py` fallback defaults (fake name, fake phone, default clinician/slot). Missing patient_name, patient_phone, clinician_id or slot_id returns 400.
- Scripted personas for scenarios 2 to 6 may exist ONLY in one backend constant `DEMO_PERSONAS` in `src/simulator.py` (with a comment "DEMO DATA ONLY"). Frontend reads persona names from API responses and contains no patient names. The explainer card labels them "Demo patient".
- CLI demo scripts and `if __name__ == "__main__"` blocks may keep sample names, each marked `# DEMO DATA ONLY`.
- Run a final grep for the strings above and show the output in your report, with a reason for any remaining occurrence.

## C. Backend
- New `GET /api/availability`: clinicians with `clinician_id`, `display_name`, `service_label` (e.g. "Therapy session", "Psychiatric consultation"), `duration_minutes`, `fee`, `slots:[{slot_id, start_iso, label}]` (available only, sorted). Do not expose internal fields like `setmore_staff_key`.
- `GET /api/slots` stays but uses the same availability check.
- `seed_demo_data()`: at least 3 future slots per clinician across the next 2 working days (Mon to Sat, 9 AM to 8 PM, skip Sundays), computed from today. Keep SLOT-101, SLOT-103, SLOT-202 so earlier scenarios work. Doctors have different fees and durations.
- `POST /api/chat/message` gets per-phone conversation state (`AWAITING_NAME`, `AWAITING_SLOT`, `IDLE`) stored in the coordinator under the lock. In `AWAITING_NAME` it validates the name, registers the patient, moves to `AWAITING_SLOT`, and returns a reply of `kind: "doctor_picker"` with the availability payload so the frontend opens the sheet.
- `POST /api/book_slot` returns 409 when the slot is unavailable and validates the slot belongs to the clinician sent.
- Reset clears conversation state.

## D. Frontend (index.html)
- Add the bottom-sheet doctor pop-up inside the phone screen (matching the existing look) with time chips, confirm step, close button, Escape support and focus trapping. Build all DOM with `createElement`/`textContent`, never `innerHTML` with user or API text.
- Chat input gets a "name entry" mode (like PIN mode) and returns to normal afterwards.
- Replace every hardcoded `startBooking('Dr. ...', 'SLOT-...', ...)` button (fees reply, booking reply, expiry notices, etc.) with a button that reopens the pop-up from `/api/availability`.
- The "Book Appointment" quick pill and typing "book" or "appointment" start this same flow (ask name only if `currentPatient` is empty; if known, greet by name and open the pop-up directly).
- The 15-minute expiry message has one "Choose another time" button that reopens the pop-up.
- Reset clears `currentPatient`, closes the sheet and restores the chat input.

## E. Tests
Add tests for: valid and invalid names; state transitions AWAITING_NAME to AWAITING_SLOT; availability excludes held and booked slots and exposes no internal keys; booking returns 409 on a taken slot; payment record fee equals the chosen clinician's fee; no hold exists before the patient confirms; no old hardcoded names in outbound WhatsApp text (use a patient "Zoya Menon", assert "Zoya" present and old names absent); crisis text typed as the "name" still triggers the crisis path; `format_doctor_name` handles "Dr. X", "dr. x" and "X". Keep all existing tests passing.

## F. Verification (do it yourself, then report)
1. Run all unit tests: green.
2. Start `python app.py`. Click Happy Path, type "Zoya Menon", confirm the pop-up lists every doctor with times, pick a time, confirm, check the payment message has no day/time and no banner, pay, confirm the confirmation uses "Zoya", the right doctor and fee.
3. After Reset repeat with another name. Also test: invalid name "12345"; closing the pop-up without choosing (confirm no hold on `/staff`); a slot taken mid-flow (expect 409 handling).
4. Confirm `/staff` shows the booking under the typed first name and no hardcoded names.
5. Show the grep output from section B, the browser console and the server log (no errors).

Report: files changed, commands to run, and a checklist of each requirement (done / not done with reason).








FOLLOW-UP INSTRUCTION: APPLY AND DEPLOY THE CHANGES

Apply every change from the previous task (patient types name, doctor pop-up with time chips, hardcoded names removed) directly to the files in the open workspace folder, so they appear in VS Code. Do not give me code snippets to copy. Do not say "done" until every step below has been completed and verified.

1. APPLY ON DISK
- Edit the existing files in place. Do not create a copy of the project in another folder.
- Save every modified file. When finished, run `git status` and `git diff --stat` (or list file modification times if git is not set up) and show me which files changed.
- Make sure no old duplicate files (for example an old index.html in another folder) are being served instead.

2. MAKE THE WEBSITE ACTUALLY SHOW THE NEW VERSION
- In app.py, add these headers to every static response (index.html, staff.html, and any other files): `Cache-Control: no-store, no-cache, must-revalidate` and `Pragma: no-cache`, so the browser never shows an old cached page.
- Find any process already listening on port 8000 and stop it, then start the server fresh with `python app.py`. Confirm the new code is running by calling `GET /api/availability` and showing me the response.
- Add a visible version label in the footer of index.html and staff.html (for example "Build: <current date and time>") so I can see at a glance that the page is the new one.

3. TEST IN THE BROWSER (do not skip)
- Open http://localhost:8000, hard reload, and click through: Happy Path -> type "Zoya Menon" -> doctor pop-up appears with all available doctors and times -> pick a time -> confirm -> payment message shows no day/time and no orange banner -> pay -> confirmation uses "Zoya", the correct doctor and the correct fee.
- Click Reset, then run it again with a different name. Test an invalid name ("12345"). Close the pop-up without choosing and confirm /staff shows no hold.
- Run each of the other scenarios once, with Reset in between. Buttons must lock while one is running, unlock after Reset, and the cursor must be a hand when enabled and not-allowed when disabled.
- Open http://localhost:8000/staff in a second tab and confirm it updates live and has no buttons that change data.

4. QUALITY CHECKS
- Run the full unit test suite and fix any failure.
- Check the browser console and the server log. Fix every error and warning that comes from our code.
- Run the grep for hardcoded names from the previous task and show the output.

5. REPORT
Reply with: the files changed, the exact commands to start the app and run the tests, the build label now visible on the page, a screenshot description of each step in section 3, and a done / not done checklist. If anything could not be completed, say exactly what and why. Do not leave TODOs or placeholders.













prompts used to build the project
