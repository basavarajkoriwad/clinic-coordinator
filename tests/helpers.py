"""
Shared test fixtures and test utilities for unit, integration, system, and acceptance tests.
Pure Python standard library only (unittest, urllib, threading, socket).
"""

from datetime import datetime, timedelta
import http.client
import json
from pathlib import Path
import socket
import sys
import threading
import time
from typing import Dict, List, Optional, Tuple, Any
import urllib.error
import urllib.request

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
from src.mock_services import (
    MockPaymentGateway,
    MockSetmoreService,
    MockWhatsAppService,
    TaskManager,
)
from src.coordinator import ClinicBookingCoordinator, patient_greeting
from src.simulator import ScenarioSimulator, seed_demo_data
from app import ClinicWebHandler as ClinicRequestHandler


def create_fresh_coordinator(slot_ttl_minutes: int = 15) -> ClinicBookingCoordinator:
    """
    Creates an isolated ClinicBookingCoordinator with mock dependencies.
    """
    setmore = MockSetmoreService()
    gateway = MockPaymentGateway(webhook_secret="mock_secret_key_clinic_2026")
    whatsapp = MockWhatsAppService()
    tasks = TaskManager()
    return ClinicBookingCoordinator(
        setmore_service=setmore,
        payment_gateway=gateway,
        whatsapp_service=whatsapp,
        task_manager=tasks,
        slot_ttl_minutes=slot_ttl_minutes,
    )


def seed_test_clinicians_and_slots(coord: ClinicBookingCoordinator):
    """
    Seeds clean test clinicians and future time slots.
    """
    seed_demo_data(coord)


def find_free_port() -> int:
    """Finds an available TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        s.listen(1)
        port = s.getsockname()[1]
        return port


class TestHttpClientResponse:
    def __init__(self, status: int, headers: dict, body: bytes):
        self.status = status
        self.status_code = status
        self.headers = headers
        self.body = body
        self.text = body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.text)


class TestHttpClient:
    """
    Lightweight HTTP client using standard library urllib only.
    """
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def request(self, method: str, path: str, data: Any = None, headers: Optional[dict] = None) -> TestHttpClientResponse:
        url = f"{self.base_url}{path}"
        req_headers = {"User-Agent": "ClinicTestRunner/1.0"}
        if headers:
            req_headers.update(headers)

        body_bytes = None
        if data is not None:
            if isinstance(data, (dict, list)):
                body_bytes = json.dumps(data).encode("utf-8")
                if "Content-Type" not in req_headers:
                    req_headers["Content-Type"] = "application/json"
            elif isinstance(data, str):
                body_bytes = data.encode("utf-8")
            elif isinstance(data, bytes):
                body_bytes = data

        req = urllib.request.Request(url, data=body_bytes, headers=req_headers, method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                resp_headers = dict(resp.headers.items())
                resp_body = resp.read()
                return TestHttpClientResponse(resp.status, resp_headers, resp_body)
        except urllib.error.HTTPError as err:
            err_headers = dict(err.headers.items()) if err.headers else {}
            err_body = err.read() if hasattr(err, "read") else b""
            return TestHttpClientResponse(err.code, err_headers, err_body)

    def get(self, path: str, headers: Optional[dict] = None) -> TestHttpClientResponse:
        return self.request("GET", path, headers=headers)

    def post(self, path: str, data: Any = None, headers: Optional[dict] = None) -> TestHttpClientResponse:
        return self.request("POST", path, data=data, headers=headers)


class AppServerFixture:
    """
    Context manager that starts the real application server from app.py
    on a free port in a background thread and cleanly shuts it down.
    """
    def __init__(self, port: Optional[int] = None):
        self.port = port or find_free_port()
        self.server: Optional[http.server.HTTPServer] = None
        self.thread: Optional[threading.Thread] = None
        self.client: Optional[TestHttpClient] = None

    def start(self):
        # Configure handler class
        ClinicRequestHandler.initialize_backend()
        self.server = http.server.HTTPServer(("127.0.0.1", self.port), ClinicRequestHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

        self.client = TestHttpClient(f"http://127.0.0.1:{self.port}")

        # Wait until server is listening
        ready = False
        start_time = time.time()
        while time.time() - start_time < 5.0:
            try:
                resp = self.client.get("/api/status")
                if resp.status == 200:
                    ready = True
                    break
            except Exception:
                time.sleep(0.05)

        if not ready:
            self.stop()
            raise RuntimeError(f"AppServerFixture failed to start on port {self.port} within 5s")

    def stop(self):
        if self.server:
            try:
                self.server.shutdown()
                self.server.server_close()
            except Exception:
                pass
            self.server = None
        if self.thread:
            self.thread.join(timeout=1.0)
            self.thread = None

    def __enter__(self):
        self.start()
        return self.client

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
