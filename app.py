"""
Local Web Application Server for The Bengaluru Clinic Coordination & Email Engine.
Serves:
- Interactive web cockpit (/) and staff operations dashboard (/staff)
- Patient accounts, login, signup, email verification, password reset, double opt-in subscriptions
- Dev Mailbox (/dev/mailbox) for inspecting simulated emails and downloading PDF tax invoices
- Cryptographic Signed Invoice Download (/invoice/<token>)
- Multithreaded REST APIs with RLock concurrency protection and rate limiting
"""

from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import sys
import threading
import time
from urllib.parse import urlparse, parse_qs, unquote_plus, quote_plus
import webbrowser

# Set project directory
PROJECT_DIR = Path(__file__).resolve().parent
os.chdir(PROJECT_DIR)

# Ensure root is in sys.path
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import config
from src.db import db_cursor, hash_token
from src.models import (
    BookingState,
    Clinician,
    PatientProfile,
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
from src.coordinator import ClinicBookingCoordinator, patient_greeting
from src.simulator import ScenarioSimulator, seed_demo_data
from src.auth import (
    create_user,
    verify_user_email,
    resend_verification_token,
    create_password_reset_token,
    reset_user_password,
    verify_password,
    create_session,
    get_user_from_session,
    delete_session,
    delete_user_account_and_data,
    generate_csrf_token,
    verify_csrf_token,
    check_rate_limit,
)
from src.mailer import (
    enqueue_email,
    render_email,
    mask_email,
    start_mail_worker,
    start_weekly_digest_scheduler,
    get_dev_mailbox_emails,
    get_email_record_by_id,
    get_email_attachment_bytes,
    _process_queue_batch,
)
from src.views import (
    render_login_page,
    render_signup_page,
    render_verify_page,
    render_forgot_page,
    render_reset_page,
    render_account_page,
    render_confirm_subscription_page,
    render_unsubscribe_page,
    render_privacy_page,
    render_dev_mailbox_page,
)


class ClinicWebHandler(SimpleHTTPRequestHandler):
    coordinator: ClinicBookingCoordinator = None
    simulator: ScenarioSimulator = None

    @classmethod
    def setup_coordinator(cls):
        setmore = MockSetmoreService()
        gateway = MockPaymentGateway()
        whatsapp = MockWhatsAppService()
        tasks = TaskManager()

        cls.coordinator = ClinicBookingCoordinator(setmore, gateway, whatsapp, tasks, slot_ttl_minutes=15)
        seed_demo_data(cls.coordinator)
        cls.simulator = ScenarioSimulator(cls.coordinator)

        # Start active background worker thread for 15-minute slot hold cleanup & task SLA escalations
        start_background_worker(cls.coordinator, interval_seconds=10)

        # Start email queue worker and weekly digest scheduler
        start_mail_worker()
        start_weekly_digest_scheduler()

    initialize_backend = setup_coordinator

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    # ------------------------------------------------------------------
    # HTTP Helper Utilities
    # ------------------------------------------------------------------
    def _get_client_ip(self) -> str:
        """Extracts client IP address."""
        forwarded = self.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return self.client_address[0] if self.client_address else "127.0.0.1"

    def _get_session_token(self) -> Optional[str]:
        """Extracts session_id cookie value."""
        cookie_header = self.headers.get("Cookie")
        if not cookie_header:
            return None
        cookie = SimpleCookie()
        try:
            cookie.load(cookie_header)
            if "session_id" in cookie:
                return cookie["session_id"].value
        except Exception:
            return None
        return None

    def _get_authenticated_user(self) -> Optional[dict]:
        """Returns authenticated user dictionary if session is valid."""
        token = self._get_session_token()
        return get_user_from_session(token)

    def _send_json(self, status_code: int, data: dict):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        req_origin = self.headers.get("Origin")
        if req_origin and req_origin != "*":
            self.send_header("Access-Control-Allow-Origin", req_origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Razorpay-Signature")
        self.end_headers()
        self.wfile.write(json.dumps(data, default=str).encode("utf-8"))

    def _send_html(self, status_code: int, html_str: str, extra_headers: Optional[list] = None):
        body_bytes = html_str.encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body_bytes)))
        if extra_headers:
            for k, v in extra_headers:
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body_bytes)

    def _send_redirect(self, location: str, cookies: Optional[list] = None):
        self.send_response(303)
        self.send_header("Location", location)
        if cookies:
            for c in cookies:
                self.send_header("Set-Cookie", c)
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        req_origin = self.headers.get("Origin")
        if req_origin and req_origin != "*":
            self.send_header("Access-Control-Allow-Origin", req_origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Razorpay-Signature")
        self.end_headers()

    # ------------------------------------------------------------------
    # GET Handlers
    # ------------------------------------------------------------------
    def do_GET(self):
        coord = self.coordinator
        parsed = urlparse(self.path)
        path_only = parsed.path
        query_params = parse_qs(parsed.query)

        # 1. Staff Dashboard State Endpoint
        if path_only == "/api/dashboard":
            with coord.lock:
                now = datetime.now()
                open_tasks_raw = list(coord.tasks.tasks.values())
                
                priority_order = {
                    TaskPriority.P0_URGENT: 0,
                    TaskPriority.P1_HIGH: 1,
                    TaskPriority.P2_MEDIUM: 2,
                    TaskPriority.P3_LOW: 3,
                }
                status_order = {
                    TaskStatus.OPEN: 0,
                    TaskStatus.ESCALATED: 1,
                    TaskStatus.IN_PROGRESS: 2,
                    TaskStatus.RESOLVED: 3,
                }
                sorted_tasks = sorted(
                    open_tasks_raw,
                    key=lambda t: (status_order.get(t.status, 4), priority_order.get(t.priority, 4), t.due_date or datetime.max),
                )

                tasks_data = []
                for t in sorted_tasks:
                    is_overdue = t.due_date and now >= t.due_date and t.status in (TaskStatus.OPEN, TaskStatus.ESCALATED)
                    time_left_sec = int((t.due_date - now).total_seconds()) if t.due_date else None
                    patient = coord.patients.get(t.patient_id)
                    p_greeting = patient_greeting(patient) if patient else "System"
                    p_identity = f"{p_greeting} (****{patient.phone_number[-4:]})" if (patient and len(patient.phone_number) >= 4) else p_greeting
                    tasks_data.append({
                        "task_id": t.task_id,
                        "title": t.title,
                        "description": t.description,
                        "priority": t.priority.value,
                        "status": t.status.value,
                        "assigned_to": t.assigned_to,
                        "due_date": t.due_date.isoformat() if t.due_date else None,
                        "created_at": t.created_at.isoformat() if t.created_at else None,
                        "resolved_at": t.resolved_at.isoformat() if t.resolved_at else None,
                        "resolution_notes": t.resolution_notes,
                        "is_overdue": is_overdue,
                        "time_left_seconds": time_left_sec,
                        "patient_name": p_identity,
                    })

                confirmed_count = sum(1 for b in coord.bookings.values() if b.state == BookingState.CONFIRMED)
                holds_count = sum(1 for b in coord.bookings.values() if b.state in (BookingState.SLOT_HELD, BookingState.PAYMENT_PENDING))
                p0_active = sum(1 for t in open_tasks_raw if t.priority == TaskPriority.P0_URGENT and t.status in (TaskStatus.OPEN, TaskStatus.ESCALATED))
                p1_active = sum(1 for t in open_tasks_raw if t.priority == TaskPriority.P1_HIGH and t.status in (TaskStatus.OPEN, TaskStatus.ESCALATED))
                total_open = sum(1 for t in open_tasks_raw if t.status in (TaskStatus.OPEN, TaskStatus.ESCALATED))

                slots_data = []
                for s in sorted(coord.setmore.slots.values(), key=lambda x: x.start_time):
                    clinician = coord.clinicians.get(s.clinician_id)
                    slots_data.append({
                        "slot_id": s.slot_id,
                        "clinician_id": s.clinician_id,
                        "clinician_name": format_doctor_name(clinician.name if clinician else ""),
                        "start_time": s.start_time.isoformat(),
                        "is_held": s.is_held,
                        "held_until": s.held_until.isoformat() if s.held_until else None,
                        "is_booked": s.is_booked,
                        "held_by_booking_id": s.held_by_booking_id,
                        "available": coord.setmore.check_availability(s.slot_id),
                    })

                clinicians_data = [
                    {
                        "clinician_id": c.clinician_id,
                        "name": format_doctor_name(c.name),
                        "specialty": c.specialty,
                        "consultation_fee": c.consultation_fee,
                        "duration_minutes": c.duration_minutes,
                    }
                    for c in coord.clinicians.values()
                ]

                calls_data = list(reversed(coord.call_log[-15:]))
                audit_data = [
                    {
                        "seq": e.seq,
                        "timestamp": e.timestamp,
                        "category": e.category,
                        "message": e.message,
                        "hash": e.hash[:16] + "...",
                    }
                    for e in reversed(coord.audit_log[-20:])
                ]

                # Count emails in database
                emails_count = 0
                try:
                    with db_cursor(commit=False) as cur:
                        cur.execute("SELECT COUNT(*) as cnt FROM email_queue WHERE status IN ('SENT', 'SENT-IN-DEV');")
                        emails_count = cur.fetchone()["cnt"]
                except Exception:
                    pass

                data = {
                    "metrics": {
                        "confirmed_count": confirmed_count,
                        "active_holds": holds_count,
                        "total_open_tasks": total_open,
                        "p0_urgent_tasks": p0_active,
                        "p1_high_tasks": p1_active,
                        "calls_count": len(coord.call_log),
                        "emails_sent": emails_count,
                    },
                    "tasks": tasks_data,
                    "slots": slots_data,
                    "clinicians": clinicians_data,
                    "calls": calls_data,
                    "audit_log": audit_data,
                    "ai_muted_phones": list(coord.ai_muted_phones),
                    "active_scenario": self.simulator.active_scenario,
                }
                return self._send_json(200, data)

        # 2. General Status Endpoint
        if path_only == "/api/status":
            with coord.lock:
                open_tasks = coord.tasks.get_open_tasks()
                p0_tasks = coord.tasks.get_open_tasks(TaskPriority.P0_URGENT)
                emails_count = 0
                try:
                    with db_cursor(commit=False) as cur:
                        cur.execute("SELECT COUNT(*) as cnt FROM email_queue WHERE status IN ('SENT', 'SENT-IN-DEV');")
                        emails_count = cur.fetchone()["cnt"]
                except Exception:
                    pass

                return self._send_json(200, {
                    "status": "online",
                    "clinicians": len(coord.clinicians),
                    "open_tasks": len(open_tasks),
                    "p0_tasks": len(p0_tasks),
                    "active_bookings": len(coord.bookings),
                    "emails_sent": emails_count,
                    "active_scenario": self.simulator.active_scenario,
                })

        # 3. Available Doctors & Slots Endpoint
        if path_only == "/api/availability":
            with coord.lock:
                avail = coord.get_availability()
                return self._send_json(200, {"status": "success", "clinicians": avail})

        # 4. Available Slots Endpoint
        if path_only == "/api/slots":
            with coord.lock:
                slots_data = []
                for s in coord.setmore.slots.values():
                    clinician = coord.clinicians.get(s.clinician_id)
                    slots_data.append({
                        "slot_id": s.slot_id,
                        "clinician_id": s.clinician_id,
                        "clinician_name": format_doctor_name(clinician.name if clinician else ""),
                        "start_time": s.start_time.isoformat(),
                        "is_held": s.is_held,
                        "is_booked": s.is_booked,
                        "available": coord.setmore.check_availability(s.slot_id),
                    })
                return self._send_json(200, {"slots": slots_data})

        # -------------------------------------------------------------
        # Patient Accounts & Authentication Pages
        # -------------------------------------------------------------
        if path_only == "/signup":
            user = self._get_authenticated_user()
            if user:
                return self._send_redirect("/account")
            csrf = generate_csrf_token(self._get_client_ip())
            return self._send_html(200, render_signup_page(csrf))

        if path_only == "/login":
            user = self._get_authenticated_user()
            if user:
                return self._send_redirect("/account")
            csrf = generate_csrf_token(self._get_client_ip())
            msg = query_params.get("msg", [""])[0]
            err = query_params.get("error", [""])[0]
            unverified = query_params.get("unverified", [""])[0]
            return self._send_html(200, render_login_page(csrf, error=err, message=msg, unverified_email=unverified))

        if path_only == "/verify":
            token = query_params.get("token", [""])[0]
            success, message = verify_user_email(token)
            return self._send_html(200 if success else 400, render_verify_page(success, message))

        if path_only == "/forgot":
            csrf = generate_csrf_token(self._get_client_ip())
            msg = query_params.get("msg", [""])[0]
            err = query_params.get("error", [""])[0]
            return self._send_html(200, render_forgot_page(csrf, message=msg, error=err))

        if path_only == "/reset":
            token = query_params.get("token", [""])[0]
            csrf = generate_csrf_token(self._get_client_ip())
            return self._send_html(200, render_reset_page(csrf, token=token))

        if path_only == "/account":
            user = self._get_authenticated_user()
            if not user:
                return self._send_redirect("/login")
            
            with db_cursor(commit=False) as cur:
                cur.execute("SELECT status, preferences FROM subscriptions WHERE user_id = ?;", (user["id"],))
                sub_row = cur.fetchone()
                sub_dict = dict(sub_row) if sub_row else None

            csrf = generate_csrf_token(self._get_session_token() or self._get_client_ip())
            msg = query_params.get("msg", [""])[0]
            err = query_params.get("error", [""])[0]
            return self._send_html(200, render_account_page(user, sub_dict, csrf, message=msg, error=err))

        # Double Opt-In Subscription Confirmation Link
        if path_only == "/confirm-subscription":
            token = query_params.get("token", [""])[0]
            if not token:
                return self._send_html(400, render_confirm_subscription_page(False, "Missing confirmation token."))
            
            t_hash = hash_token(token.strip())
            now_str = datetime.now(timezone.utc).isoformat()
            ip_hash = hash_token(self._get_client_ip())

            with db_cursor(commit=True) as cur:
                cur.execute("SELECT user_id, preferences FROM subscriptions WHERE confirm_token_hash = ?;", (t_hash,))
                sub_row = cur.fetchone()
                if not sub_row:
                    return self._send_html(400, render_confirm_subscription_page(False, "Invalid or already confirmed subscription link."))

                u_id = sub_row["user_id"]
                cur.execute("""
                    UPDATE subscriptions
                    SET status = 'ACTIVE',
                        consent_at = ?,
                        consent_ip_hash = ?,
                        confirm_token_hash = NULL
                    WHERE user_id = ?;
                """, (now_str, ip_hash, u_id))

                cur.execute("SELECT email FROM users WHERE id = ?;", (u_id,))
                u_email = cur.fetchone()["email"]

            # Automatically trigger Welcome / About email (Section 5)
            unsub_url = f"{config.BASE_URL}/unsubscribe?token=unsub_{u_id}_{hash_token(u_email)[:16]}"
            html_b, text_b = render_email(
                template_name="welcome_about",
                subject="Welcome to The Bengaluru Clinic · Confidential Clinical Care",
                header_title="Welcome to Our Practice",
                header_subtitle="Confidential Outpatient Care in Indiranagar",
                context={
                    "patient_name": u_email.split("@")[0].capitalize(),
                    "unsubscribe_url": unsub_url,
                },
                unsubscribe_url=unsub_url,
            )
            enqueue_email(
                to_email=u_email,
                template="welcome_about",
                subject="Welcome to The Bengaluru Clinic · Confidential Clinical Care",
                html_body=html_b,
                text_body=text_b,
                dedupe_key=f"welcome_about_{u_id}",
            )

            return self._send_html(200, render_confirm_subscription_page(True, "Your subscription is now ACTIVE. We have sent your Welcome Guide to your inbox."))

        # One-Click Unsubscribe Handler (Section 5)
        if path_only == "/unsubscribe":
            token = query_params.get("token", [""])[0]
            with db_cursor(commit=True) as cur:
                if token and token.startswith("unsub_"):
                    parts = token.split("_")
                    if len(parts) >= 2 and parts[1].isdigit():
                        uid = int(parts[1])
                        cur.execute("UPDATE subscriptions SET status = 'UNSUBSCRIBED' WHERE user_id = ?;", (uid,))
                        cur.execute("""
                            INSERT INTO email_log (queue_id, event, timestamp)
                            VALUES (NULL, 'UNSUBSCRIBED', ?);
                        """, (datetime.now(timezone.utc).isoformat(),))
            return self._send_html(200, render_unsubscribe_page(True, "You have been successfully unsubscribed from all marketing communications."))

        # Privacy Policy Page
        if path_only == "/privacy":
            user = self._get_authenticated_user()
            return self._send_html(200, render_privacy_page(user))

        # Signed, Expiring Tax Invoice Download Route (Section 7)
        if path_only.startswith("/invoice/"):
            token = path_only.split("/invoice/")[-1].strip()
            if not token:
                return self._send_json(404, {"error": "Missing invoice token"})
            
            t_hash = hash_token(token)
            with db_cursor(commit=False) as cur:
                cur.execute("""
                    SELECT invoice_number, pdf_path, access_token_expires_at
                    FROM invoices
                    WHERE access_token_hash = ?;
                """, (t_hash,))
                inv_row = cur.fetchone()

            if not inv_row:
                return self._send_json(404, {"error": "Invoice not found or access token invalid."})

            exp = datetime.fromisoformat(inv_row["access_token_expires_at"])
            if datetime.now(timezone.utc) > exp:
                return self._send_json(410, {"error": "This invoice download link has expired."})

            pdf_file = config.DATA_DIR / inv_row["pdf_path"]
            if not pdf_file.exists():
                pdf_file = config.INVOICES_DIR / f"{inv_row['invoice_number']}.pdf"

            if not pdf_file.exists():
                return self._send_json(404, {"error": "Invoice PDF file not found on disk."})

            with open(pdf_file, "rb") as f:
                pdf_bytes = f.read()

            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", f'inline; filename="{inv_row["invoice_number"]}.pdf"')
            self.send_header("Content-Length", str(len(pdf_bytes)))
            self.end_headers()
            self.wfile.write(pdf_bytes)
            return

        # Dev Mailbox (Section 6)
        if path_only == "/dev/mailbox":
            is_local = self._get_client_ip() in ("127.0.0.1", "::1", "localhost")
            if config.MAIL_MODE != "dev" and not is_local:
                return self._send_json(403, {"error": "Dev mailbox is accessible only in dev mode or locally."})
            
            sel_id_str = query_params.get("id", [None])[0]
            sel_id = int(sel_id_str) if sel_id_str and sel_id_str.isdigit() else None
            emails = get_dev_mailbox_emails(50)
            return self._send_html(200, render_dev_mailbox_page(emails, sel_id))

        if path_only == "/api/dev/emails":
            emails = get_dev_mailbox_emails(100)
            return self._send_json(200, {"emails": emails})

        if path_only.startswith("/api/dev/emails/") and path_only.endswith("/attachment"):
            parts = path_only.split("/")
            try:
                email_id = int(parts[4])
                att = get_email_attachment_bytes(email_id)
                if not att:
                    return self._send_json(404, {"error": "Attachment not found"})
                att_name, att_bytes = att
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf" if att_name.endswith(".pdf") else "application/octet-stream")
                self.send_header("Content-Disposition", f'attachment; filename="{att_name}"')
                self.send_header("Content-Length", str(len(att_bytes)))
                self.end_headers()
                self.wfile.write(att_bytes)
                return
            except Exception as e:
                return self._send_json(400, {"error": str(e)})

        if path_only == "/api/auth/me":
            user = self._get_authenticated_user()
            return self._send_json(200, {"logged_in": bool(user), "user": user})

        # -------------------------------------------------------------
        # Static HTML Pages
        # -------------------------------------------------------------
        if path_only in ("/staff", "/staff.html"):
            self.path = "/staff.html"
            return super().do_GET()

        if path_only in ("/", "/index.html"):
            self.path = "/index.html"
            return super().do_GET()

        if path_only.startswith("/api/"):
            return self._send_json(404, {"status": "error", "message": f"Endpoint {self.path} not found"})

        return super().do_GET()

    # ------------------------------------------------------------------
    # POST Handlers
    # ------------------------------------------------------------------
    def do_POST(self):
        coord = self.coordinator
        simulator = self.simulator
        client_ip = self._get_client_ip()
        parsed_url = urlparse(self.path)
        path_only = parsed_url.path

        cl_header = self.headers.get("Content-Length")
        if cl_header is None:
            return self._send_json(400, {"status": "error", "message": "Missing Content-Length header"})
        try:
            content_length = int(cl_header)
            if content_length < 0:
                return self._send_json(400, {"status": "error", "message": "Invalid negative Content-Length"})
        except (ValueError, TypeError):
            return self._send_json(400, {"status": "error", "message": "Invalid Content-Length header"})

        raw_body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else ""
        content_type = self.headers.get("Content-Type", "")

        # Parse form or JSON body
        if "application/x-www-form-urlencoded" in content_type:
            parsed_form = parse_qs(raw_body)
            body = {k: v[0] for k, v in parsed_form.items()}
        elif raw_body.strip():
            try:
                body = json.loads(raw_body)
            except Exception as e:
                return self._send_json(400, {"status": "error", "message": f"Malformed JSON: {str(e)}"})
        else:
            body = {}

        # -------------------------------------------------------------
        # Auth POST Handlers
        # -------------------------------------------------------------
        if path_only == "/signup":
            csrf = body.get("csrf_token", "")
            if not verify_csrf_token(csrf, client_ip):
                return self._send_html(403, render_signup_page(csrf, error="CSRF security validation failed. Please try again."))

            allowed, retry_sec = check_rate_limit("signup", client_ip)
            if not allowed:
                return self._send_html(429, render_signup_page(csrf, error=f"Too many signup attempts. Please wait {retry_sec} seconds before trying again."))

            email = body.get("email", "").strip()
            password = body.get("password", "")
            try:
                user, raw_verify_token = create_user(email, password)
                # Enqueue single-use verification email (Section 4)
                verify_url = f"{config.BASE_URL}/verify?token={raw_verify_token}"
                html_b, text_b = render_email(
                    template_name="verify_email",
                    subject="The Bengaluru Clinic · Verify Your Email Address",
                    header_title="Verify Your Email Address",
                    header_subtitle="Activate your patient account",
                    context={
                        "patient_name": email.split("@")[0].capitalize(),
                        "verify_url": verify_url,
                    }
                )
                enqueue_email(
                    to_email=email,
                    template="verify_email",
                    subject="The Bengaluru Clinic · Verify Your Email Address",
                    html_body=html_b,
                    text_body=text_b,
                    dedupe_key=f"verify_{user['id']}_{raw_verify_token[:8]}",
                )
                return self._send_redirect(f"/login?msg=Account+created+successfully.+Please+check+your+email+to+verify+your+address.")
            except Exception as e:
                return self._send_html(400, render_signup_page(csrf, error=str(e)))

        if path_only == "/login":
            csrf = body.get("csrf_token", "")
            if not verify_csrf_token(csrf, client_ip):
                return self._send_html(403, render_login_page(csrf, error="CSRF validation failed. Please try again."))

            email = body.get("email", "").strip().lower()
            password = body.get("password", "")

            # Rate limit per IP and per email
            allowed_ip, retry_ip = check_rate_limit("login_ip", client_ip)
            allowed_email, retry_email = check_rate_limit("login_email", email)
            if not allowed_ip or not allowed_email:
                wait_sec = max(retry_ip, retry_email)
                return self._send_html(429, render_login_page(csrf, error=f"Too many failed login attempts. Account temporarily locked for {wait_sec} seconds."))

            with db_cursor(commit=False) as cur:
                cur.execute("SELECT id, password_hash, salt, email_verified FROM users WHERE email = ?;", (email,))
                user_row = cur.fetchone()

            if not user_row or not verify_password(password, user_row["password_hash"], user_row["salt"]):
                return self._send_html(401, render_login_page(csrf, error="Invalid email or password."))

            if not user_row["email_verified"]:
                return self._send_html(403, render_login_page(
                    csrf,
                    error="Your email address has not been verified yet. Please check your inbox or resend verification.",
                    unverified_email=email
                ))

            # Success: create session
            session_token = create_session(user_row["id"])
            secure_flag = "; Secure" if config.BASE_URL.startswith("https") else ""
            cookie_val = f"session_id={session_token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=604800{secure_flag}"
            return self._send_redirect("/account", cookies=[cookie_val])

        if path_only == "/logout":
            token = self._get_session_token()
            if token:
                delete_session(token)
            cookie_expired = "session_id=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"
            return self._send_redirect("/login?msg=You+have+been+logged+out.", cookies=[cookie_expired])

        if path_only == "/resend-verification":
            csrf = body.get("csrf_token", "")
            email = body.get("email", "").strip().lower()
            allowed, retry_sec = check_rate_limit("resend", client_ip)
            if not allowed:
                return self._send_html(429, render_login_page(csrf, error=f"Please wait {retry_sec} seconds before resending verification."))

            raw_tok = resend_verification_token(email)
            if raw_tok:
                verify_url = f"{config.BASE_URL}/verify?token={raw_tok}"
                html_b, text_b = render_email(
                    template_name="verify_email",
                    subject="The Bengaluru Clinic · Verify Your Email Address",
                    header_title="Verify Your Email Address",
                    header_subtitle="Activate your patient account",
                    context={
                        "patient_name": email.split("@")[0].capitalize(),
                        "verify_url": verify_url,
                    }
                )
                enqueue_email(
                    to_email=email,
                    template="verify_email",
                    subject="The Bengaluru Clinic · Verify Your Email Address",
                    html_body=html_b,
                    text_body=text_b,
                    dedupe_key=f"resend_verify_{email}_{raw_tok[:8]}",
                )
            return self._send_redirect("/login?msg=If+an+unverified+account+exists,+a+new+verification+link+has+been+sent.")

        if path_only == "/forgot":
            csrf = body.get("csrf_token", "")
            if not verify_csrf_token(csrf, client_ip):
                return self._send_html(403, render_forgot_page(csrf, error="CSRF validation failed."))

            allowed, retry_sec = check_rate_limit("forgot", client_ip)
            if not allowed:
                return self._send_html(429, render_forgot_page(csrf, error=f"Please wait {retry_sec} seconds."))

            email = body.get("email", "").strip().lower()
            res = create_password_reset_token(email)
            if res:
                u, raw_reset_token = res
                reset_url = f"{config.BASE_URL}/reset?token={raw_reset_token}"
                html_b, text_b = render_email(
                    template_name="reset_password",
                    subject="The Bengaluru Clinic · Password Reset Request",
                    header_title="Reset Your Password",
                    header_subtitle="Secure single-use password reset link",
                    context={
                        "patient_name": email.split("@")[0].capitalize(),
                        "reset_url": reset_url,
                    }
                )
                enqueue_email(
                    to_email=email,
                    template="reset_password",
                    subject="The Bengaluru Clinic · Password Reset Request",
                    html_body=html_b,
                    text_body=text_b,
                    dedupe_key=f"reset_{u['id']}_{raw_reset_token[:8]}",
                )
            # Generic response: never reveals whether an email exists
            return self._send_redirect("/forgot?msg=If+an+account+exists+for+that+email,+password+reset+instructions+have+been+sent.")

        if path_only == "/reset":
            csrf = body.get("csrf_token", "")
            if not verify_csrf_token(csrf, client_ip):
                return self._send_html(403, render_login_page(csrf, error="CSRF validation failed."))

            token = body.get("token", "").strip()
            new_password = body.get("new_password", "")
            ok, msg = reset_user_password(token, new_password)
            if ok:
                return self._send_redirect("/login?msg=Password+reset+successful.+Please+log+in+with+your+new+password.")
            else:
                return self._send_html(400, render_reset_page(csrf, token=token, error=msg))

        if path_only == "/consent":
            user = self._get_authenticated_user()
            if not user:
                return self._send_redirect("/login")
            
            session_tok = self._get_session_token()
            csrf = body.get("csrf_token", "")
            if not verify_csrf_token(csrf, session_tok or client_ip):
                return self._send_redirect("/account?error=Security+validation+failed.")

            if body.get("consent") == "1":
                raw_confirm = secrets.token_urlsafe(32)
                t_hash = hash_token(raw_confirm)
                raw_unsub = secrets.token_urlsafe(32)
                u_hash = hash_token(raw_unsub)
                consent_wording = "I consent to receive occasional clinical wellness tips and care updates. I understand I can withdraw consent or unsubscribe at any time in one click."
                prefs_json = json.dumps({"wellness_tips": True, "clinic_news": True, "appointment_reminders": True})
                
                with db_cursor(commit=True) as cur:
                    cur.execute("""
                        INSERT INTO subscriptions (
                            user_id, status, confirm_token_hash, unsub_token_hash,
                            consent_text, consent_at, consent_ip_hash, preferences
                        ) VALUES (?, 'PENDING', ?, ?, ?, NULL, NULL, ?)
                        ON CONFLICT(user_id) DO UPDATE SET
                            status = 'PENDING',
                            confirm_token_hash = excluded.confirm_token_hash,
                            unsub_token_hash = excluded.unsub_token_hash,
                            consent_text = excluded.consent_text;
                    """, (user["id"], t_hash, u_hash, consent_wording, prefs_json))

                # Enqueue double opt-in confirmation email
                confirm_url = f"{config.BASE_URL}/confirm-subscription?token={raw_confirm}"
                html_b, text_b = render_email(
                    template_name="confirm_subscription",
                    subject="The Bengaluru Clinic · Confirm Your Subscription",
                    header_title="Confirm Your Subscription",
                    header_subtitle="Double opt-in communication verification",
                    context={
                        "patient_name": user["email"].split("@")[0].capitalize(),
                        "confirm_url": confirm_url,
                    }
                )
                enqueue_email(
                    to_email=user["email"],
                    template="confirm_subscription",
                    subject="The Bengaluru Clinic · Confirm Your Subscription",
                    html_body=html_b,
                    text_body=text_b,
                    dedupe_key=f"confirm_sub_{user['id']}_{raw_confirm[:8]}",
                )
                return self._send_redirect("/account?msg=Confirmation+email+sent.+Please+check+your+inbox+or+Dev+Mailbox.")
            return self._send_redirect("/account")

        if path_only == "/account/preferences":
            user = self._get_authenticated_user()
            if not user:
                return self._send_redirect("/login")
            
            session_tok = self._get_session_token()
            csrf = body.get("csrf_token", "")
            if not verify_csrf_token(csrf, session_tok or client_ip):
                return self._send_redirect("/account?error=Security+validation+failed.")

            prefs = {
                "wellness_tips": body.get("wellness_tips") == "1",
                "clinic_news": body.get("clinic_news") == "1",
                "appointment_reminders": body.get("appointment_reminders") == "1",
            }
            with db_cursor(commit=True) as cur:
                cur.execute("UPDATE subscriptions SET preferences = ? WHERE user_id = ?;", (json.dumps(prefs), user["id"]))
            return self._send_redirect("/account?msg=Communication+preferences+saved+successfully.")

        if path_only == "/account/send-test":
            user = self._get_authenticated_user()
            if not user:
                return self._send_redirect("/login")
            
            session_tok = self._get_session_token()
            csrf = body.get("csrf_token", "")
            if not verify_csrf_token(csrf, session_tok or client_ip):
                return self._send_redirect("/account?error=Security+validation+failed.")

            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            html_b, text_b = render_email(
                template_name="test_email",
                subject="The Bengaluru Clinic · Test Diagnostic Message",
                header_title="Mail Subsystem Diagnostic",
                header_subtitle="Local Queue & Transport Engine Verification",
                context={
                    "patient_name": user["email"].split("@")[0].capitalize(),
                    "mail_mode": config.MAIL_MODE.upper(),
                    "recipient_email": user["email"],
                    "sent_time_str": now_str,
                    "transport_info": "Local Dev Mailbox" if config.MAIL_MODE == "dev" else f"SMTP ({config.SMTP_HOST})",
                }
            )
            enqueue_email(
                to_email=user["email"],
                template="test_email",
                subject="The Bengaluru Clinic · Test Diagnostic Message",
                html_body=html_b,
                text_body=text_b,
            )
            return self._send_redirect("/account?msg=Test+email+enqueued.+Check+the+Dev+Mailbox+to+view+it.")

        if path_only == "/account/unsubscribe":
            user = self._get_authenticated_user()
            if not user:
                return self._send_redirect("/login")
            with db_cursor(commit=True) as cur:
                cur.execute("UPDATE subscriptions SET status = 'UNSUBSCRIBED' WHERE user_id = ?;", (user["id"],))
            return self._send_redirect("/account?msg=You+have+been+unsubscribed+from+all+marketing+communications.")

        if path_only == "/account/delete":
            user = self._get_authenticated_user()
            if not user:
                return self._send_redirect("/login")
            session_tok = self._get_session_token()
            csrf = body.get("csrf_token", "")
            if not verify_csrf_token(csrf, session_tok or client_ip):
                return self._send_redirect("/account?error=Security+validation+failed.")

            delete_user_account_and_data(user["id"])
            cookie_expired = "session_id=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"
            return self._send_redirect("/?msg=Your+account+and+associated+communication+data+have+been+permanently+erased.", cookies=[cookie_expired])

        # RFC 8058 One-Click Unsubscribe via POST
        if path_only == "/unsubscribe":
            token = body.get("token", "") or parse_qs(urlparse(self.path).query).get("token", [""])[0]
            if token and token.startswith("unsub_"):
                parts = token.split("_")
                if len(parts) >= 2 and parts[1].isdigit():
                    uid = int(parts[1])
                    with db_cursor(commit=True) as cur:
                        cur.execute("UPDATE subscriptions SET status = 'UNSUBSCRIBED' WHERE user_id = ?;", (uid,))
            return self._send_json(200, {"status": "unsubscribed"})

        # -------------------------------------------------------------
        # Scenario Simulator Endpoints
        # -------------------------------------------------------------
        if self.path in ("/api/simulate/pay", "/api/simulate/pay/"):
            with coord.lock:
                order_id = body.get("order_id") or simulator.scenario_state.get("order_id")
                booking_id = coord.order_to_booking.get(order_id)
                booking = coord.bookings.get(booking_id) if booking_id else None
                fee = booking.payment.amount_inr if (booking and booking.payment) else 2500.0

                # Check if patient logged in or optional receipt email provided
                user = self._get_authenticated_user()
                if booking and user and not booking.receipt_email:
                    booking.receipt_email = user["email"]

                payload = {
                    "event": "payment.captured",
                    "payload": {
                        "payment": {
                            "entity": {
                                "id": f"pay_{secrets.token_hex(8)}",
                                "order_id": order_id,
                                "amount": int(fee * 100),
                                "currency": "INR",
                                "status": "captured"
                            }
                        }
                    }
                }
                payload_str = json.dumps(payload)
                sig = coord.gateway.compute_signature(payload_str)
                res = coord.handle_payment_webhook(payload_str, sig)
                return self._send_json(200, res)

        if self.path == "/api/simulate/action":
            action = body.get("action")
            order_id = body.get("order_id")
            receipt_email = body.get("receipt_email")

            with coord.lock:
                # If patient is logged in and no explicit email passed, use account email
                user = self._get_authenticated_user()
                effective_email = receipt_email or (user["email"] if user else None)

                if order_id in coord.order_to_booking:
                    b_id = coord.order_to_booking[order_id]
                    b = coord.bookings.get(b_id)
                    if b and effective_email:
                        b.receipt_email = effective_email

                res = simulator.trigger_action(action, order_id=order_id)
                return self._send_json(200, res)

        if self.path == "/api/simulate/scenario":
            scenario_id = body.get("scenario_id")
            patient_name = body.get("patient_name")
            with coord.lock:
                res = simulator.run_scenario(scenario_id, patient_name=patient_name)
                return self._send_json(200, res)

        if self.path == "/api/simulate/reset":
            with coord.lock:
                res = simulator.reset()
                return self._send_json(200, res)

        if self.path in ("/api/simulate/start", "/api/simulate/start/"):
            scenario_name = body.get("scenario") or body.get("scenario_name") or "happy"
            phone = body.get("phone", "+919876543210")
            with coord.lock:
                res = simulator.start_scenario(scenario_name, phone=phone)
                return self._send_json(200, {"status": "success", "data": res})

        # -------------------------------------------------------------
        # Booking & WhatsApp Chat Endpoints
        # -------------------------------------------------------------
        if self.path == "/api/book_slot":
            patient_name = body.get("patient_name")
            patient_phone = body.get("patient_phone")
            clinician_id = body.get("clinician_id")
            slot_id = body.get("slot_id")
            service = body.get("service_name") or body.get("service", "Individual Therapy")
            receipt_email = body.get("receipt_email")

            if not patient_name or not patient_phone or not clinician_id or not slot_id:
                return self._send_json(400, {"status": "error", "message": "Missing required booking details (patient_name, patient_phone, clinician_id, slot_id)"})

            with coord.lock:
                clinician = coord.clinicians.get(clinician_id)
                slot = coord.setmore.slots.get(slot_id)
                if not clinician or not slot:
                    return self._send_json(400, {"status": "error", "message": "Clinician or slot not found"})

                if slot.clinician_id != clinician_id:
                    return self._send_json(400, {"status": "error", "message": f"Slot {slot_id} does not belong to clinician {clinician_id}"})

                if not coord.setmore.check_availability(slot_id):
                    return self._send_json(409, {"status": "error", "message": "That time was just taken. Please choose another."})

                user = self._get_authenticated_user()
                effective_email = receipt_email or (user["email"] if user else None)
                patient = coord.register_or_get_patient(patient_name, patient_phone, email=effective_email)

                try:
                    booking = coord.initiate_booking(patient.patient_id, clinician_id, slot_id, service_name=service)
                    if effective_email:
                        booking.receipt_email = effective_email

                    wa_msgs = coord.whatsapp.get_messages_for_phone(patient_phone)
                    latest_msg = wa_msgs[-1]["content"] if wa_msgs else ""
                    return self._send_json(200, {
                        "status": "success",
                        "booking_id": booking.booking_id,
                        "order_id": booking.payment.order_id if booking.payment else None,
                        "state": booking.state.value,
                        "fee": float(clinician.consultation_fee),
                        "payment_link_url": booking.payment.payment_link_url if booking.payment else None,
                        "hold_expires_at": booking.hold_expires_at.isoformat() if booking.hold_expires_at else None,
                        "whatsapp_message": latest_msg,
                    })
                except Exception as e:
                    return self._send_json(409, {"status": "conflict", "message": str(e)})
        if self.path.startswith("/api/simulate/"):
            sc = self.path.split("/api/simulate/")[-1].strip("/")
            if sc in ("happy", "late_payment", "setmore_outage", "shared_phone", "crisis", "lab_report"):
                phone = body.get("phone", "+919876543210")
                with coord.lock:
                    res = simulator.start_scenario(sc, phone=phone)
                    return self._send_json(200, {"status": "success", "data": res, "scenario": sc})

        if self.path == "/api/phone/resolve":
            phone = body.get("phone", "+919876500000")
            with coord.lock:
                status_res, profiles = coord.resolve_patient_by_phone(phone)
                return self._send_json(200, {
                    "status": status_res,
                    "profiles": [{"patient_id": p.patient_id, "name": p.full_name} for p in profiles]
                })

        if self.path == "/api/phone/verify_pin":
            patient_id = body.get("patient_id")
            pin = body.get("pin", "")
            with coord.lock:
                ok, msg = coord.verify_patient_pin(patient_id, pin)
                return self._send_json(200, {"success": ok, "message": msg})

        if self.path == "/api/chat/message":
            phone = body.get("phone", "+919876543210")
            text = body.get("text", "").strip()
            patient_name_input = body.get("patient_name")
            name_candidate = (patient_name_input or text).strip()

            with coord.lock:
                # 0. Check if phone is muted due to crisis
                if phone in coord.ai_muted_phones:
                    return self._send_json(200, {
                        "status": "muted",
                        "reply": "Automated chat is temporarily muted. A clinical supervisor has been notified and is reaching out to you.",
                    })

                # 1. Crisis Check First
                if coord.check_crisis_message(text):
                    task = coord.handle_crisis_trigger(phone, text)
                    return self._send_json(200, {
                        "status": "crisis",
                        "action": "crisis_intercept",
                        "reply": "I hear that you are going through a painful time. Please reach out right away to the Tele-MANAS 24/7 mental health helpline at 14416 or call emergency services at 112. A clinical supervisor has been notified.",
                        "task_id": task.task_id if task else None,
                    })

                # 2. Check if this is a name entry or name is being submitted
                conv_state = coord.get_conversation_state(phone)
                is_name_step = conv_state == "AWAITING_NAME" or (patient_name_input and coord.validate_patient_name(patient_name_input))
                
                if is_name_step:
                    if not coord.validate_patient_name(name_candidate):
                        return self._send_json(200, {
                            "status": "request_name",
                            "action": "request_name",
                            "reply": "I'm sorry, I could not read that name. Please enter your first and last name (letters only):",
                        })

                    # Valid name typed
                    patient = coord.register_or_get_patient(name_candidate, phone)
                    coord.set_conversation_state(phone, "AWAITING_SLOT")
                    first_name = patient_greeting(patient)

                    # If an interactive scenario was started and waiting for patient name:
                    if simulator.active_scenario == "late_payment":
                        res = simulator.execute_late_payment_with_patient(patient)
                        return self._send_json(200, {"status": "scenario_resume", "kind": "scenario_resume", **res})
                    elif simulator.active_scenario == "setmore_outage":
                        res = simulator.execute_setmore_outage_with_patient(patient)
                        return self._send_json(200, {"status": "scenario_resume", "kind": "scenario_resume", **res})
                    elif simulator.active_scenario == "lab_report":
                        res = simulator.execute_lab_report_with_patient(patient)
                        return self._send_json(200, {"status": "scenario_resume", "kind": "scenario_resume", **res})

                    clinicians = coord.get_availability()
                    return self._send_json(200, {
                        "status": "success",
                        "kind": "doctor_picker",
                        "reply": f"Thank you, {first_name}. Here are the doctors available for you. Please choose your preferred clinician and appointment time:",
                        "patient": {
                            "patient_id": patient.patient_id,
                            "name": patient.full_name,
                            "first_name": first_name,
                            "phone": patient.phone_number,
                        },
                        "clinicians": clinicians,
                    })

                # Check general commands
                text_lower = text.lower()
                status_res, profiles = coord.resolve_patient_by_phone(phone)
                stored_patient = profiles[0] if (profiles and profiles[0].full_name not in ("Patient", "Unknown")) else None

                if any(w in text_lower for w in ["book", "appointment", "doctor"]):
                    if stored_patient:
                        coord.set_conversation_state(phone, "AWAITING_SLOT")
                        clinicians = coord.get_availability()
                        first_name = patient_greeting(stored_patient)
                        return self._send_json(200, {
                            "status": "success",
                            "kind": "doctor_picker",
                            "reply": f"Welcome back, {first_name}. Here are the doctors available for you. Please choose your preferred clinician and appointment time:",
                            "patient": {
                                "patient_id": stored_patient.patient_id,
                                "name": stored_patient.full_name,
                                "first_name": first_name,
                                "phone": stored_patient.phone_number,
                            },
                            "clinicians": clinicians,
                        })
                    else:
                        coord.set_conversation_state(phone, "AWAITING_NAME")
                        return self._send_json(200, {
                            "status": "request_name",
                            "kind": "request_name",
                            "action": "request_name",
                            "reply": "Welcome to The Bengaluru Clinic. May I have your full name, please?",
                        })

                if any(w in text_lower for w in ["fee", "timing", "hours", "cost", "price"]):
                    return self._send_json(200, {
                        "status": "success",
                        "kind": "fees_info",
                        "reply": "Consultation Fees & Timings: Consultation fees range from INR 2,000 to INR 3,000 depending on the specialist. Clinic hours are Monday to Saturday, 9:00 AM to 8:00 PM. Type 'book' to schedule an appointment.",
                    })

                # Default fallback: check if name candidate is valid name
                if coord.validate_patient_name(name_candidate):
                    patient = coord.register_or_get_patient(name_candidate, phone)
                    coord.set_conversation_state(phone, "AWAITING_SLOT")
                    clinicians = coord.get_availability()
                    first_name = patient_greeting(patient)
                    return self._send_json(200, {
                        "status": "success",
                        "kind": "doctor_picker",
                        "reply": f"Thank you, {first_name}. Here are the doctors available for you. Please choose your preferred clinician and appointment time:",
                        "patient": {
                            "patient_id": patient.patient_id,
                            "name": patient.full_name,
                            "first_name": first_name,
                            "phone": patient.phone_number,
                        },
                        "clinicians": clinicians,
                    })

                return self._send_json(200, {
                    "status": "success",
                    "reply": "Thank you for reaching out to The Bengaluru Clinic. Type 'book' to schedule a consultation, or call us directly using the phone icon above.",
                })

        if self.path == "/api/booking/initiate":
            patient_id = body.get("patient_id")
            clinician_id = body.get("clinician_id")
            slot_id = body.get("slot_id")
            service = body.get("service", "Consultation")
            mode = body.get("mode", "IN_PERSON")
            receipt_email = body.get("receipt_email")

            with coord.lock:
                user = self._get_authenticated_user()
                effective_email = receipt_email or (user["email"] if user else None)
                try:
                    booking = coord.initiate_booking(patient_id, clinician_id, slot_id, service, mode)
                    if effective_email:
                        booking.receipt_email = effective_email
                    return self._send_json(200, {
                        "status": "success",
                        "booking_id": booking.booking_id,
                        "order_id": booking.payment.order_id if booking.payment else None,
                        "amount_inr": booking.payment.amount_inr if booking.payment else 0.0,
                        "hold_expires_at": booking.hold_expires_at.isoformat() if booking.hold_expires_at else None,
                    })
                except Exception as e:
                    return self._send_json(409, {"status": "conflict", "message": str(e)})

        if self.path in ("/api/booking/webhook", "/api/webhook/payment"):
            sig = self.headers.get("X-Razorpay-Signature", "")
            with coord.lock:
                res = coord.handle_payment_webhook(raw_body, sig)
                status_code = 200 if res.get("status") in ("success", "duplicate_ignored", "exception", "ok") else 400
                return self._send_json(status_code, res)

        if self.path == "/api/call/inbound":
            phone = body.get("caller_phone", "+919876543210")
            status = body.get("call_status", "ANSWERED")
            duration = int(body.get("duration_seconds", 0))
            caller_name = body.get("caller_name")
            with coord.lock:
                res = coord.handle_inbound_call(phone, status, duration, caller_name=caller_name)
                return self._send_json(200, res)

        if self.path == "/api/call/outbound":
            patient_id = body.get("patient_id")
            if not patient_id and "target_phone" in body:
                _, profs = coord.resolve_patient_by_phone(body["target_phone"])
                if profs:
                    patient_id = profs[0].patient_id
                else:
                    patient = coord.register_or_get_patient("Patient", body["target_phone"])
                    patient_id = patient.patient_id
            if not patient_id:
                patient_id = "PAT-UNKNOWN"
            staff_id = body.get("staff_id", "FrontDesk_1")
            reason = body.get("reason", "SCHEDULED_CALLBACK")
            with coord.lock:
                res = coord.initiate_outbound_call(patient_id, staff_id, reason=reason)
                return self._send_json(200, res)

        if self.path == "/api/task/resolve":
            task_id = body.get("task_id")
            action = body.get("action")
            staff_id = body.get("staff_id", "Clinic_Manager")
            new_slot_id = body.get("new_slot_id")

            with coord.lock:
                if action in ("reschedule", "refund"):
                    task = coord.tasks.tasks.get(task_id)
                    booking_id = None
                    if task:
                        for b in coord.bookings.values():
                            if b.patient_id == task.patient_id and b.state == BookingState.PAYMENT_RECEIVED_SLOT_LOST:
                                booking_id = b.booking_id
                                break
                    if not booking_id and coord.bookings:
                        booking_id = list(coord.bookings.keys())[-1]

                    if booking_id:
                        res = coord.resolve_slot_lost_exception(booking_id, action, staff_id, new_slot_id)
                        return self._send_json(200, res)
                    else:
                        coord.tasks.resolve_task(task_id, staff_id, f"Resolved via {action}")
                        return self._send_json(200, {"status": "resolved"})
                elif action == "retry_sync":
                    res = simulator.trigger_action("retry_setmore_sync")
                    return self._send_json(200, res)
                else:
                    res = coord.tasks.resolve_task(task_id, staff_id, "Manually marked resolved.")
                    return self._send_json(200, {"status": "resolved" if res else "not_found"})

        if self.path == "/api/phone/setup_pin":
            patient_id = body.get("patient_id", "")
            pin = body.get("pin", "")
            with coord.lock:
                ok, msg = coord.setup_patient_pin(patient_id, pin)
                return self._send_json(200, {"success": ok, "message": msg})

        if self.path == "/api/phone/verify_pin":
            patient_id = body.get("patient_id", "")
            pin = body.get("pin", "")
            with coord.lock:
                ok, msg = coord.verify_patient_pin(patient_id, pin)
                return self._send_json(200, {"success": ok, "message": msg})

        return self._send_json(404, {"status": "not_found", "message": "Unknown API endpoint"})


# Alias for backward compatibility
ClinicRequestHandler = ClinicWebHandler


def start_background_worker(coordinator: ClinicBookingCoordinator, interval_seconds: int = 10):
    """
    Background daemon thread actively sweeping stale 15-minute slot holds,
    auto-escalating overdue staff task SLAs, and checking appointment care reminders.
    """
    def worker():
        while True:
            time.sleep(interval_seconds)
            try:
                with coordinator.lock:
                    expired = coordinator.expire_stale_holds()
                    if expired:
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] [BACKEND TTL WORKER] Expired {len(expired)} stale slot holds back into open inventory.")
                    escalated = coordinator.escalate_overdue_tasks()
                    if escalated:
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] [SLA WORKER] Escalated {len(escalated)} overdue tasks.")
                    coordinator.send_appointment_reminders()
            except Exception as e:
                print(f"[BACKEND WORKER ERROR] {e}")

    thread = threading.Thread(target=worker, daemon=True, name="BackendCoordinatorWorker")
    thread.start()


def run_web_server(port=8000):
    ClinicWebHandler.setup_coordinator()
    server_address = ("127.0.0.1", port)
    httpd = ThreadingHTTPServer(server_address, ClinicWebHandler)

    url = f"http://localhost:{port}"
    print("=" * 72)
    print(" THE BENGALURU CLINIC -- CLINICAL COORDINATION & EMAIL ENGINE")
    print("=" * 72)
    print(f" Web Server Running at: {url}")
    print(f" - WhatsApp Patient Simulator: {url}/")
    print(f" - Read-Only Staff Operations Cockpit: {url}/staff")
    print(f" - Patient Auth & Accounts: {url}/login | {url}/signup | {url}/account")
    print(f" - Dev Mailbox: {url}/dev/mailbox")
    print(f" - DPDP Privacy Disclosures: {url}/privacy")
    print(f" - Mail Mode: {config.MAIL_MODE.upper()}")
    print(" - Multithreaded Concurrency & RLock: ACTIVE")
    print(" - Backend 15-Minute Hold Expiry & SLA Escalation Worker: ACTIVE")
    print(" - Background Queue Worker & Digest Scheduler: ACTIVE")
    print(" Press Ctrl+C in this terminal to stop the server.")
    print("=" * 72)

    try:
        webbrowser.open(url)
    except Exception:
        pass

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[INFO] Web server stopped cleanly.")
        sys.exit(0)


if __name__ == "__main__":
    run_web_server(8000)
