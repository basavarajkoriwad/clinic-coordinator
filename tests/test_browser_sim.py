"""
End-to-End Simulation of All Browser User Actions described in Section 3.
"""

import json
from pathlib import Path
import sys
import unittest
import urllib.request

root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from tests.helpers import AppServerFixture


class TestBrowserScenariosSimulation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Auto-detect if a live app server is already running on port 8000
        cls.fixture = None
        cls.base_url = "http://127.0.0.1:8000"
        try:
            req = urllib.request.Request(f"{cls.base_url}/api/status", headers={"Cache-Control": "no-cache"})
            with urllib.request.urlopen(req, timeout=0.5) as r:
                if r.status == 200:
                    return
        except Exception:
            pass

        # If port 8000 is not running, spin up an AppServerFixture automatically
        cls.fixture = AppServerFixture()
        cls.fixture.start()
        cls.base_url = f"http://127.0.0.1:{cls.fixture.port}"

    @classmethod
    def tearDownClass(cls):
        if cls.fixture:
            cls.fixture.stop()

    def get(self, path):
        req = urllib.request.Request(f"{self.base_url}{path}", headers={"Cache-Control": "no-cache"})
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read().decode("utf-8"))

    def post(self, path, payload):
        raw = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(f"{self.base_url}{path}", data=raw, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read().decode("utf-8"))

    def setUp(self):
        self.post("/api/simulate/reset", {})

    def tearDown(self):
        self.post("/api/simulate/reset", {})

    def test_section_3_happy_path_zoya_menon(self):
        # 1. Start happy path
        s, d = self.post("/api/simulate/start", {"scenario": "happy"})
        self.assertEqual(s, 200)
        self.assertEqual(d["data"]["scenario"], "happy")
        chat_msgs = d["data"]["chat_messages"]
        self.assertEqual(chat_msgs[1]["action"], "request_name")

        # 2. Test invalid name ("12345")
        s, d_inv = self.post("/api/chat/message", {"phone": "+919876543210", "text": "12345"})
        self.assertEqual(s, 200)
        self.assertEqual(d_inv["action"], "request_name")
        self.assertIn("could not read that name", d_inv["reply"])

        # 3. Test valid name ("Zoya Menon")
        s, d_valid = self.post("/api/chat/message", {"phone": "+919876543210", "text": "Zoya Menon"})
        self.assertEqual(s, 200)
        self.assertEqual(d_valid["kind"], "doctor_picker")
        self.assertIn("Thank you, Zoya", d_valid["reply"])
        self.assertGreaterEqual(len(d_valid["clinicians"]), 3)

        # 4. Pick doctor & slot (e.g. Dr. Rajesh Rao, fee 2000, slot SLOT-R1)
        doc = [c for c in d_valid["clinicians"] if c["clinician_id"] == "DOC-102"][0]
        slot = doc["slots"][0]
        self.assertEqual(doc["fee"], 2000.0)

        # 5. Confirm booking -> 15m hold starts now
        s, bkg = self.post("/api/book_slot", {
            "patient_name": "Zoya Menon",
            "patient_phone": "+919876543210",
            "clinician_id": doc["clinician_id"],
            "slot_id": slot["slot_id"],
            "service_name": doc["service_label"],
        })
        self.assertEqual(s, 200)
        self.assertEqual(bkg["state"], "PAYMENT_PENDING")
        self.assertEqual(bkg["fee"], 2000.0)
        # Payment message has 15 minutes, but NO day or time
        self.assertIn("15 minutes", bkg["whatsapp_message"])
        self.assertNotIn("Tomorrow", bkg["whatsapp_message"])
        self.assertNotIn("10:30 AM", bkg["whatsapp_message"])

        # 6. Staff dashboard shows 1 active hold
        s, dash = self.get("/api/dashboard")
        self.assertEqual(dash["metrics"]["active_holds"], 1)
        self.assertEqual(dash["metrics"]["confirmed_count"], 0)

        # 7. Pay via simulated Razorpay gateway
        s, pay = self.post("/api/simulate/action", {"action": "pay_happy", "order_id": bkg["order_id"]})
        self.assertEqual(s, 200)
        self.assertEqual(pay["fee"], 2000.0)
        self.assertEqual(pay["clinician_name"], "Dr. Rajesh Rao")
        self.assertIn("Appointment Confirmed", pay["confirmation_message"])

        # 8. Staff dashboard shows 1 confirmed and 0 active holds
        s, dash_after = self.get("/api/dashboard")
        self.assertEqual(dash_after["metrics"]["active_holds"], 0)
        self.assertEqual(dash_after["metrics"]["confirmed_count"], 1)

    def test_section_3_close_without_choosing_no_hold(self):
        # Presenter starts happy path and user types a name
        self.post("/api/simulate/start", {"scenario": "happy"})
        self.post("/api/chat/message", {"phone": "+919876543210", "text": "Kabir Khan"})
        
        # User closes pop-up without confirming any slot
        # Verify /staff dashboard shows NO hold placed
        s, dash = self.get("/api/dashboard")
        self.assertEqual(dash["metrics"]["active_holds"], 0)
        self.assertEqual(dash["metrics"]["confirmed_count"], 0)

    def test_section_3_all_scenarios_and_reset(self):
        # Scenario 2: Late Payment (asks for name first, then executes with typed patient)
        s, sc2 = self.post("/api/simulate/start", {"scenario": "late_payment"})
        self.assertEqual(sc2["data"]["explainer"]["badge"], "P0 Urgent Exception")
        s, chat2 = self.post("/api/chat/message", {"phone": "+919876543210", "text": "Aarav Iyer"})
        self.assertEqual(chat2["status"], "scenario_resume")
        s, res2 = self.post("/api/simulate/action", {"action": "reschedule_slot_lost", "new_slot_id": "SLOT-A3"})
        self.assertEqual(res2["result"]["status"], "rescheduled")
        self.post("/api/simulate/reset", {})

        # Scenario 3: Setmore Outage (asks for name first, then executes with typed patient)
        s, sc3 = self.post("/api/simulate/start", {"scenario": "setmore_outage"})
        self.assertEqual(sc3["data"]["explainer"]["badge"], "P0 Critical Exception")
        s, chat3 = self.post("/api/chat/message", {"phone": "+919876543210", "text": "Aarav Iyer"})
        self.assertEqual(chat3["status"], "scenario_resume")
        s, res3 = self.post("/api/simulate/action", {"action": "retry_booking"})
        self.assertEqual(res3["result"]["status"], "resolved")
        self.post("/api/simulate/reset", {})

        # Scenario 4: Shared Phone PIN Gate
        s, sc4 = self.post("/api/simulate/start", {"scenario": "shared_phone"})
        self.assertEqual(sc4["data"]["explainer"]["badge"], "Privacy & Security")
        s, res4_err = self.post("/api/simulate/action", {"action": "test_wrong_pin"})
        self.assertFalse(res4_err["success"])
        s, res4_ok = self.post("/api/simulate/action", {"action": "test_correct_pin"})
        self.assertTrue(res4_ok["success"])
        self.post("/api/simulate/reset", {})

        # Scenario 5: Psychiatric Crisis Intercept
        s, sc5 = self.post("/api/simulate/start", {"scenario": "crisis"})
        self.assertEqual(sc5["data"]["explainer"]["badge"], "Life Safety Protocol")
        s, res5 = self.post("/api/simulate/action", {"action": "resolve_crisis"})
        self.assertEqual(res5["result"]["status"], "resolved")
        self.post("/api/simulate/reset", {})

        # Scenario 6: 2FA Lab Report Vault (asks for name first, then executes with typed patient)
        s, sc6 = self.post("/api/simulate/start", {"scenario": "lab_report"})
        self.assertEqual(sc6["data"]["explainer"]["badge"], "HIPAA / DPDP Compliant")
        s, chat6 = self.post("/api/chat/message", {"phone": "+919876543210", "text": "Aarav Iyer"})
        self.assertEqual(chat6["status"], "scenario_resume")
        s, res6 = self.post("/api/simulate/action", {"action": "verify_lab_otp"})
        self.assertEqual(res6["status"], "success")
        self.post("/api/simulate/reset", {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
