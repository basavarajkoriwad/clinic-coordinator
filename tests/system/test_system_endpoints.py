"""
System Tests: Comprehensive HTTP API Endpoints & Security Checks.
Starts the real application from app.py on a free port and tests every endpoint over HTTP.
Uses only standard library (urllib, unittest).
"""

import json
from pathlib import Path
import sys
import unittest

root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from tests.helpers import AppServerFixture
from app import ClinicRequestHandler


class TestSystemEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = AppServerFixture()
        cls.client = cls.fixture.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.fixture.__exit__(None, None, None)

    # -------------------------------------------------------------
    # Static Files & Cache Headers
    # -------------------------------------------------------------
    def test_get_index_and_staff_pages_no_cache(self):
        # GET /
        resp_index = self.client.get("/")
        self.assertEqual(resp_index.status, 200)
        self.assertIn("The Bengaluru Clinic", resp_index.text)
        self.assertIn("no-store", resp_index.headers.get("Cache-Control", ""))

        # GET /staff
        resp_staff = self.client.get("/staff")
        self.assertEqual(resp_staff.status, 200)
        self.assertIn("Staff Operations Cockpit", resp_staff.text)
        self.assertIn("no-store", resp_staff.headers.get("Cache-Control", ""))

    def test_staff_html_has_no_post_fetch_calls(self):
        staff_file = root_dir / "staff.html"
        content = staff_file.read_text(encoding="utf-8")
        # Ensure no fetch calls with method POST exist in staff.html
        self.assertNotIn("method: 'POST'", content)
        self.assertNotIn('method: "POST"', content)
        self.assertNotIn("method:'POST'", content)

    # -------------------------------------------------------------
    # CORS Security: No Wildcard Access-Control-Allow-Origin
    # -------------------------------------------------------------
    def test_no_wildcard_cors_header(self):
        resp = self.client.get("/api/status")
        self.assertEqual(resp.status, 200)
        origin_header = resp.headers.get("Access-Control-Allow-Origin", "")
        self.assertNotEqual(origin_header, "*", "Wildcard CORS header '*' must not be present")

    # -------------------------------------------------------------
    # Core GET Endpoints
    # -------------------------------------------------------------
    def test_get_status_endpoint(self):
        resp = self.client.get("/api/status")
        self.assertEqual(resp.status, 200)
        data = resp.json()
        self.assertEqual(data["status"], "online")
        self.assertIn("clinicians", data)
        self.assertIn("open_tasks", data)

    def test_get_availability_endpoint(self):
        resp = self.client.get("/api/availability")
        self.assertEqual(resp.status, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertTrue(len(data["clinicians"]) >= 3)
        for c in data["clinicians"]:
            self.assertIn("display_name", c)
            self.assertIn("fee", c)
            self.assertNotIn("setmore_staff_key", c)  # Internal keys stripped

    def test_get_slots_endpoint(self):
        resp = self.client.get("/api/slots")
        self.assertEqual(resp.status, 200)
        data = resp.json()
        self.assertIn("slots", data)
        self.assertTrue(len(data["slots"]) > 0)

    def test_get_dashboard_endpoint(self):
        resp = self.client.get("/api/dashboard")
        self.assertEqual(resp.status, 200)
        data = resp.json()
        self.assertIn("metrics", data)
        self.assertIn("tasks", data)
        self.assertIn("slots", data)
        self.assertIn("clinicians", data)
        self.assertIn("calls", data)
        self.assertIn("audit_log", data)

    # -------------------------------------------------------------
    # POST Endpoints & Status Codes
    # -------------------------------------------------------------
    def test_post_chat_message(self):
        resp = self.client.post("/api/chat/message", {"phone": "+919876543210", "text": "book"})
        self.assertEqual(resp.status, 200)
        data = resp.json()
        self.assertIn("reply", data)

    def test_post_book_slot_validation_and_conflict(self):
        # 1. Missing fields -> 400
        resp_bad = self.client.post("/api/book_slot", {"patient_name": "Test"})
        self.assertEqual(resp_bad.status, 400)

        # Reset simulator to ensure fresh slots
        self.client.post("/api/simulate/reset", {})

        # 2. Valid booking -> 200
        avail = self.client.get("/api/availability").json()
        doc = avail["clinicians"][0]
        slot_id = doc["slots"][0]["slot_id"]

        resp_ok = self.client.post("/api/book_slot", {
            "patient_name": "Zoya Menon",
            "patient_phone": "+919876543210",
            "clinician_id": doc["clinician_id"],
            "slot_id": slot_id,
            "service_name": doc["service_label"],
        })
        self.assertEqual(resp_ok.status, 200)
        data_ok = resp_ok.json()
        self.assertEqual(data_ok["status"], "success")
        self.assertIn("booking_id", data_ok)
        self.assertIn("order_id", data_ok)

        # 3. Double booking same slot -> 409 Conflict
        resp_conflict = self.client.post("/api/book_slot", {
            "patient_name": "Aarav Iyer",
            "patient_phone": "+919876543211",
            "clinician_id": doc["clinician_id"],
            "slot_id": slot_id,
            "service_name": doc["service_label"],
        })
        self.assertEqual(resp_conflict.status, 409)
        self.assertIn("That time was just taken", resp_conflict.json()["message"])

    def test_post_simulate_scenarios(self):
        scenarios = ["happy", "late_payment", "setmore_outage", "shared_phone", "crisis", "lab_report"]
        for sc in scenarios:
            resp = self.client.post(f"/api/simulate/{sc}", {})
            self.assertEqual(resp.status, 200, f"Scenario {sc} failed with {resp.text}")

        # Reset
        resp_reset = self.client.post("/api/simulate/reset", {})
        self.assertEqual(resp_reset.status, 200)

    def test_post_phone_resolve_and_verify_pin(self):
        # Resolve shared couple phone
        resp_res = self.client.post("/api/phone/resolve", {"phone": "+919876500000"})
        self.assertEqual(resp_res.status, 200)
        data = resp_res.json()
        self.assertEqual(data["status"], "MULTIPLE_PROFILES")
        p_id = data["profiles"][0]["patient_id"]

        # Verify correct PIN
        resp_pin = self.client.post("/api/phone/verify_pin", {"patient_id": p_id, "pin": "4321"})
        self.assertEqual(resp_pin.status, 200)
        self.assertTrue(resp_pin.json()["success"])

    def test_post_telephony_inbound_and_outbound(self):
        # Inbound call
        resp_in = self.client.post("/api/call/inbound", {
            "caller_phone": "+919845011999",
            "call_status": "MISSED",
            "duration_seconds": 0,
        })
        self.assertEqual(resp_in.status, 200)
        data_in = resp_in.json()
        self.assertEqual(data_in["status"], "missed_call_captured")
        patient_id = data_in["call_record"]["patient_id"]

        # Outbound call
        resp_out = self.client.post("/api/call/outbound", {
            "patient_id": patient_id,
            "staff_id": "Staff_Coordinator",
        })
        self.assertEqual(resp_out.status, 200)

    def test_post_webhook_payment(self):
        coord = ClinicRequestHandler.coordinator
        with coord.lock:
            # Create a real pending booking
            p = coord.register_or_get_patient("Zoya Menon", "+919876543299")
            doc = coord.clinicians["DOC-101"]
            slot = coord.setmore.slots["SLOT-A4"]
            b = coord.initiate_booking(p.patient_id, doc.clinician_id, slot.slot_id, doc.specialty)
            order_id = b.payment.order_id

        payload = json.dumps(coord.gateway.generate_webhook_payload(order_id))
        sig = coord.gateway.compute_signature(payload)

        # POST webhook with signature header
        resp = self.client.post("/api/webhook/payment", data=payload, headers={"X-Razorpay-Signature": sig})
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.json()["status"], "success")

    # -------------------------------------------------------------
    # Error Handling & Bad Input
    # -------------------------------------------------------------
    def test_unknown_endpoints_return_404(self):
        resp_get = self.client.get("/api/unknown_endpoint")
        self.assertEqual(resp_get.status, 404)

        resp_post = self.client.post("/api/unknown_endpoint", {})
        self.assertEqual(resp_post.status, 404)

    def test_bad_content_length_returns_400(self):
        # Missing or negative Content-Length
        resp = self.client.post("/api/chat/message", data=None, headers={"Content-Length": "-5"})
        self.assertEqual(resp.status, 400)

    def test_malformed_json_returns_400(self):
        resp = self.client.post("/api/chat/message", data=b"{malformed json", headers={"Content-Type": "application/json"})
        self.assertEqual(resp.status, 400)


if __name__ == "__main__":
    unittest.main()
