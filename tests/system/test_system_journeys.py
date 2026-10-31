"""
System Tests: End-to-End User Journeys Driven Over HTTP.
Verifies complete conversational and failure flows against the live server.
"""

from pathlib import Path
import sys
import unittest

root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from tests.helpers import AppServerFixture


class TestSystemJourneys(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = AppServerFixture()
        cls.client = cls.fixture.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.fixture.__exit__(None, None, None)

    def setUp(self):
        # Reset server simulation state before each journey
        self.client.post("/api/simulate/reset", {})

    def test_journey_1_happy_path_booking(self):
        phone = "+919876543210"

        # 1. Start Happy Path
        resp_start = self.client.post("/api/simulate/start", {"scenario": "happy"})
        self.assertEqual(resp_start.status, 200)

        # 2. Patient types name "Zoya Menon"
        resp_name = self.client.post("/api/chat/message", {
            "phone": phone,
            "text": "Zoya Menon",
            "patient_name": "Zoya Menon",
        })
        self.assertEqual(resp_name.status, 200)
        data_name = resp_name.json()
        self.assertEqual(data_name["kind"], "doctor_picker")
        self.assertEqual(data_name["patient"]["first_name"], "Zoya")

        # 3. Patient picks doctor & slot
        clinicians = data_name["clinicians"]
        chosen_doc = clinicians[0]
        chosen_slot = chosen_doc["slots"][0]

        resp_book = self.client.post("/api/book_slot", {
            "patient_name": "Zoya Menon",
            "patient_phone": phone,
            "clinician_id": chosen_doc["clinician_id"],
            "slot_id": chosen_slot["slot_id"],
            "service_name": chosen_doc["service_label"],
        })
        self.assertEqual(resp_book.status, 200)
        data_book = resp_book.json()
        self.assertEqual(data_book["status"], "success")
        order_id = data_book["order_id"]

        # 4. Patient pays via Razorpay simulation
        resp_pay = self.client.post("/api/simulate/action", {
            "action": "pay_happy",
            "order_id": order_id,
        })
        self.assertEqual(resp_pay.status, 200)
        data_pay = resp_pay.json()
        self.assertEqual(data_pay["status"], "success")
        self.assertIn("Confirmed", data_pay["confirmation_message"])
        self.assertIn("Zoya", data_pay["confirmation_message"])

    def test_journey_2_late_payment_scenario(self):
        phone = "+919876543210"

        # 1. Start Late Payment scenario
        resp_start = self.client.post("/api/simulate/start", {"scenario": "late_payment"})
        self.assertEqual(resp_start.status, 200)

        # 2. Provide typed name "Aarav Iyer"
        resp_name = self.client.post("/api/chat/message", {
            "phone": phone,
            "text": "Aarav Iyer",
            "patient_name": "Aarav Iyer",
        })
        self.assertEqual(resp_name.status, 200)
        data_res = resp_name.json()
        self.assertEqual(data_res["kind"], "scenario_resume")
        self.assertEqual(data_res["patient"]["first_name"], "Aarav")

        # 3. Staff resolves via 1-click Reschedule
        resp_resched = self.client.post("/api/simulate/action", {
            "action": "reschedule_slot_lost",
            "new_slot_id": "SLOT-A3",
        })
        self.assertEqual(resp_resched.status, 200)
        data_resched = resp_resched.json()
        self.assertEqual(data_resched["status"], "success")
        self.assertIn("confirmed", data_resched["whatsapp_message"].lower())
        self.assertIn("Aarav", data_resched["whatsapp_message"])

    def test_journey_3_setmore_outage_scenario_with_retry(self):
        phone = "+919876543210"

        # 1. Start Setmore Outage scenario
        resp_start = self.client.post("/api/simulate/start", {"scenario": "setmore_outage"})
        self.assertEqual(resp_start.status, 200)

        # 2. Provide typed name "Aarav Iyer"
        resp_name = self.client.post("/api/chat/message", {
            "phone": phone,
            "text": "Aarav Iyer",
            "patient_name": "Aarav Iyer",
        })
        self.assertEqual(resp_name.status, 200)
        data_res = resp_name.json()
        self.assertEqual(data_res["kind"], "scenario_resume")

        # 3. Staff clicks 1-click retry
        resp_retry = self.client.post("/api/simulate/action", {"action": "retry_booking"})
        self.assertEqual(resp_retry.status, 200)
        data_retry = resp_retry.json()
        self.assertEqual(data_retry["result"]["status"], "resolved")

    def test_journey_4_shared_phone_pin_gate(self):
        # 1. Start Shared Phone scenario
        resp_start = self.client.post("/api/simulate/start", {"scenario": "shared_phone"})
        self.assertEqual(resp_start.status, 200)

        # 2. Test wrong PIN
        resp_wrong = self.client.post("/api/simulate/action", {"action": "test_wrong_pin"})
        self.assertEqual(resp_wrong.status, 200)
        self.assertFalse(resp_wrong.json()["success"])

        # 3. Test correct PIN
        resp_correct = self.client.post("/api/simulate/action", {"action": "test_correct_pin"})
        self.assertEqual(resp_correct.status, 200)
        self.assertTrue(resp_correct.json()["success"])

    def test_journey_5_psychiatric_crisis_intercept(self):
        phone = "+919876543210"

        # Message with suicidal phrase
        resp_crisis = self.client.post("/api/chat/message", {
            "phone": phone,
            "text": "I feel so hopeless and I want to end my life",
        })
        self.assertEqual(resp_crisis.status, 200)
        data = resp_crisis.json()
        self.assertEqual(data["status"], "crisis")
        self.assertIn("Tele-MANAS", data["reply"])
        self.assertIn("14416", data["reply"])

        # Subsequent message while muted
        resp_muted = self.client.post("/api/chat/message", {
            "phone": phone,
            "text": "Can I book a session?",
        })
        self.assertEqual(resp_muted.status, 200)
        self.assertEqual(resp_muted.json()["status"], "muted")

        # Staff resolves crisis
        resp_res = self.client.post("/api/simulate/action", {"action": "resolve_crisis"})
        self.assertEqual(resp_res.status, 200)

    def test_journey_6_lab_report_2fa_otp(self):
        resp_start = self.client.post("/api/simulate/start", {"scenario": "lab_report"})
        self.assertEqual(resp_start.status, 200)

        # Verify OTP
        resp_otp = self.client.post("/api/simulate/action", {"action": "verify_lab_otp"})
        self.assertEqual(resp_otp.status, 200)
        self.assertEqual(resp_otp.json()["status"], "success")
        self.assertIn("2FA Authenticated", resp_otp.json()["message"])


if __name__ == "__main__":
    unittest.main()
