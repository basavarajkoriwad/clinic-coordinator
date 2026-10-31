"""
Integration Tests for REST Endpoints in app.py.
Verifies GET /api/availability, POST /api/chat/message, POST /api/book_slot,
POST /api/simulate/action, and GET /api/dashboard.
"""

from datetime import datetime
import json
import threading
import time
import unittest
import urllib.request
import urllib.error

from app import ClinicWebHandler
from src.coordinator import ClinicBookingCoordinator
from src.mock_services import MockPaymentGateway, MockSetmoreService, MockWhatsAppService, TaskManager
from src.simulator import ScenarioSimulator, seed_demo_data
from http.server import ThreadingHTTPServer


class TestApiIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Setup coordinator and server on an ephemeral test port
        cls.port = 8899
        setmore = MockSetmoreService()
        gateway = MockPaymentGateway()
        whatsapp = MockWhatsAppService()
        tasks = TaskManager()

        cls.coord = ClinicBookingCoordinator(setmore, gateway, whatsapp, tasks, slot_ttl_minutes=15)
        seed_demo_data(cls.coord)
        cls.sim = ScenarioSimulator(cls.coord)

        ClinicWebHandler.coordinator = cls.coord
        ClinicWebHandler.simulator = cls.sim

        cls.server = ThreadingHTTPServer(("127.0.0.1", cls.port), ClinicWebHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        # Reset simulator state between tests
        self.sim.reset()

    def _get(self, path):
        url = f"http://127.0.0.1:{self.port}{path}"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return resp.status, data
        except urllib.error.HTTPError as e:
            data = json.loads(e.read().decode("utf-8"))
            return e.code, data

    def _post(self, path, payload):
        url = f"http://127.0.0.1:{self.port}{path}"
        raw = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=raw, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return resp.status, data
        except urllib.error.HTTPError as e:
            data = json.loads(e.read().decode("utf-8"))
            return e.code, data

    def test_01_get_availability(self):
        code, data = self._get("/api/availability")
        self.assertEqual(code, 200)
        self.assertEqual(data["status"], "success")
        self.assertIn("clinicians", data)
        self.assertGreaterEqual(len(data["clinicians"]), 3)

        for c in data["clinicians"]:
            self.assertIn("clinician_id", c)
            self.assertIn("display_name", c)
            self.assertIn("fee", c)
            self.assertIn("slots", c)
            self.assertNotIn("setmore_staff_key", c)
            self.assertTrue(c["display_name"].startswith("Dr. "))
            for s in c["slots"]:
                self.assertIn("slot_id", s)
                self.assertIn("label", s)

    def test_02_chat_flow_name_and_doctor_picker(self):
        phone = "+919876543210"

        # 1. Start happy path scenario
        code, sim_data = self._post("/api/simulate/start", {"scenario": "happy"})
        self.assertEqual(code, 200)
        self.assertEqual(sim_data["data"]["scenario"], "happy")

        # 2. Type an invalid name (digits)
        code, r_invalid = self._post("/api/chat/message", {"phone": phone, "text": "12345"})
        self.assertEqual(code, 200)
        self.assertEqual(r_invalid["action"], "request_name")
        self.assertIn("could not read that name", r_invalid["reply"])

        # 3. Type a valid name ("Zoya Menon")
        code, r_valid = self._post("/api/chat/message", {"phone": phone, "text": "Zoya Menon"})
        self.assertEqual(code, 200)
        self.assertEqual(r_valid["kind"], "doctor_picker")
        self.assertIn("Thank you, Zoya", r_valid["reply"])
        self.assertEqual(r_valid["patient"]["first_name"], "Zoya")
        self.assertEqual(r_valid["patient"]["name"], "Zoya Menon")
        self.assertIn("clinicians", r_valid)
        self.assertGreater(len(r_valid["clinicians"]), 0)

    def test_03_book_slot_strict_validation_and_conflict(self):
        # Missing fields should return 400
        code, err = self._post("/api/book_slot", {})
        self.assertEqual(code, 400)
        self.assertIn("Missing required booking details", err["message"])

        # Mismatched slot and clinician -> 400
        code, err = self._post("/api/book_slot", {
            "patient_name": "Zoya Menon",
            "patient_phone": "+919876543210",
            "clinician_id": "DOC-102",  # Rajesh Rao
            "slot_id": "SLOT-101",     # Belongs to DOC-101
        })
        self.assertEqual(code, 400)
        self.assertIn("does not belong to clinician", err["message"])

        # Successful booking -> 200
        code, res = self._post("/api/book_slot", {
            "patient_name": "Zoya Menon",
            "patient_phone": "+919876543210",
            "clinician_id": "DOC-101",
            "slot_id": "SLOT-101",
            "service_name": "Sexual & Relationship Therapy",
        })
        self.assertEqual(code, 200)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["fee"], 2500.0)
        self.assertIn("15 minutes", res["whatsapp_message"])
        # Strictly NO slot day or time in payment message
        self.assertNotIn("Tomorrow", res["whatsapp_message"])
        self.assertNotIn("10:00 AM", res["whatsapp_message"])

        # Concurrency: Another patient tries to book the same slot -> 409
        code_conflict, res_conflict = self._post("/api/book_slot", {
            "patient_name": "Farhan Akhtar",
            "patient_phone": "+919999911111",
            "clinician_id": "DOC-101",
            "slot_id": "SLOT-101",
            "service_name": "Sexual & Relationship Therapy",
        })
        self.assertEqual(code_conflict, 409)
        self.assertIn("That time was just taken. Please choose another", res_conflict["message"])

    def test_04_payment_completion_and_dashboard_metrics(self):
        # 1. Book slot for Zoya
        code, book_res = self._post("/api/book_slot", {
            "patient_name": "Zoya Menon",
            "patient_phone": "+919876543210",
            "clinician_id": "DOC-101",
            "slot_id": "SLOT-101",
        })
        self.assertEqual(code, 200)
        order_id = book_res["order_id"]

        # 2. Check dashboard has 1 active hold
        code, dash_before = self._get("/api/dashboard")
        self.assertEqual(dash_before["metrics"]["active_holds"], 1)
        self.assertEqual(dash_before["metrics"]["confirmed_count"], 0)

        # 3. Simulate payment
        code, pay_res = self._post("/api/simulate/action", {
            "action": "pay_happy",
            "order_id": order_id,
        })
        self.assertEqual(code, 200)
        self.assertIn("Appointment Confirmed", pay_res["confirmation_message"])

        # 4. Check dashboard has 1 confirmed appointment and 0 active holds
        code, dash_after = self._get("/api/dashboard")
        self.assertEqual(dash_after["metrics"]["confirmed_count"], 1)
        self.assertEqual(dash_after["metrics"]["active_holds"], 0)

    def test_05_name_entry_no_book_prompt_and_fees_timings(self):
        phone = "+919876543210"
        self._post("/api/simulate/reset", {})

        # 1. Patient directly types name "Zoya Menon"
        code, resp_name = self._post("/api/chat/message", {"phone": phone, "text": "Zoya Menon"})
        self.assertEqual(code, 200)
        self.assertEqual(resp_name["kind"], "doctor_picker")
        self.assertIn("Thank you, Zoya", resp_name["reply"])
        self.assertNotIn("type 'book'", resp_name["reply"].lower())
        self.assertEqual(resp_name["patient"]["first_name"], "Zoya")

        # 2. Inquire Fees & Timings -> no name question, returns fees
        code, resp_fees = self._post("/api/chat/message", {"phone": phone, "text": "What are the consultation fees?"})
        self.assertEqual(code, 200)
        self.assertEqual(resp_fees["kind"], "fees_info")
        self.assertIn("Consultation Fees & Timings", resp_fees["reply"])
        self.assertNotIn("may i have your full name", resp_fees["reply"].lower())

        # 3. Type "book" -> opens doctor picker directly, greets by first name
        code, resp_book = self._post("/api/chat/message", {"phone": phone, "text": "book"})
        self.assertEqual(code, 200)
        self.assertEqual(resp_book["kind"], "doctor_picker")
        self.assertIn("Welcome back, Zoya", resp_book["reply"])

        # 4. Reset clears the stored name
        self._post("/api/simulate/reset", {})
        code, resp_reset_book = self._post("/api/chat/message", {"phone": phone, "text": "book"})
        self.assertEqual(code, 200)
        self.assertEqual(resp_reset_book["kind"], "request_name")
        self.assertIn("May I have your full name", resp_reset_book["reply"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
