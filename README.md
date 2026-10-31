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
