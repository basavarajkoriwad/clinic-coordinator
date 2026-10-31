"""
Unit Tests for Pure Python PDF Generator, Indian Rupee Amount to Words, and Tax Invoices.
"""

from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import unittest

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

import config
from src.db import init_db, db_cursor
from src.pdf_generator import (
    amount_to_indian_words,
    get_current_financial_year,
    get_next_invoice_number,
    generate_tax_invoice_pdf,
)


class TestPDFAndInvoice(unittest.TestCase):
    def setUp(self):
        init_db()

    def test_amount_to_indian_words(self):
        # Edge cases and normal consultation fees
        self.assertEqual(amount_to_indian_words(0), "Rupees Zero Only")
        self.assertEqual(amount_to_indian_words(1), "Rupees One Only")
        self.assertEqual(amount_to_indian_words(18), "Rupees Eighteen Only")
        self.assertEqual(amount_to_indian_words(50), "Rupees Fifty Only")
        self.assertEqual(amount_to_indian_words(500), "Rupees Five Hundred Only")
        self.assertEqual(amount_to_indian_words(1500), "Rupees One Thousand Five Hundred Only")
        self.assertEqual(amount_to_indian_words(2500), "Rupees Two Thousand Five Hundred Only")
        self.assertEqual(amount_to_indian_words(2500.50), "Rupees Two Thousand Five Hundred and Fifty Paise Only")
        self.assertEqual(amount_to_indian_words(100000), "Rupees One Lakh Only")
        self.assertEqual(amount_to_indian_words(10000000), "Rupees One Crore Only")

    def test_current_financial_year(self):
        # Indian FY runs from 1-April to 31-March
        march_date = datetime(2026, 3, 15, tzinfo=timezone.utc)
        self.assertEqual(get_current_financial_year(march_date), "2025-26")

        april_date = datetime(2026, 4, 1, tzinfo=timezone.utc)
        self.assertEqual(get_current_financial_year(april_date), "2026-27")

        october_date = datetime(2026, 10, 30, tzinfo=timezone.utc)
        self.assertEqual(get_current_financial_year(october_date), "2026-27")

    def test_sequential_invoice_numbering(self):
        # Generate two consecutive invoices
        inv1, seq1, token1 = get_next_invoice_number("TEST-BKG-001", 2500.0)
        inv2, seq2, token2 = get_next_invoice_number("TEST-BKG-002", 2500.0)

        self.assertTrue(inv1.startswith(config.INVOICE_PREFIX))
        self.assertTrue(inv2.startswith(config.INVOICE_PREFIX))
        self.assertEqual(seq2, seq1 + 1)
        self.assertNotEqual(inv1, inv2)
        self.assertNotEqual(token1, token2)

        # Verify entry in DB
        with db_cursor(commit=False) as cur:
            cur.execute("SELECT invoice_number, total_amount FROM invoices WHERE invoice_number = ?;", (inv1,))
            row = cur.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["total_amount"], 2500.0)

    def test_generate_tax_invoice_pdf(self):
        inv_num = "TBC-INV-2026-27-9999"
        inv_date = datetime(2026, 10, 30, 10, 30)
        patient_name = "Zoya Menon"
        doctor_name = "Dr. Priya Nair"
        appt_time = datetime(2026, 11, 2, 11, 0)
        fee = 2500.0
        pay_ref = "pay_live_test_12345"
        booking_id = "BKG-TEST-ZOYA"

        pdf_bytes, pdf_path = generate_tax_invoice_pdf(
            invoice_number=inv_num,
            invoice_date=inv_date,
            patient_full_name=patient_name,
            doctor_name=doctor_name,
            appointment_time=appt_time,
            fee_inr=fee,
            payment_reference=pay_ref,
            payment_mode="UPI / Razorpay Gateway",
            booking_id=booking_id,
        )

        # Assert valid ISO 32000-1 / PDF 1.4 header
        self.assertTrue(pdf_bytes.startswith(b"%PDF-1.4"))
        self.assertTrue(pdf_bytes.strip().endswith(b"%%EOF"))
        self.assertIn(b"xref", pdf_bytes)
        self.assertIn(b"trailer", pdf_bytes)
        self.assertGreater(len(pdf_bytes), 3000)

        # Verify file written to disk
        self.assertTrue(pdf_path.exists())
        self.assertEqual(pdf_path.read_bytes(), pdf_bytes)

        # Text stream checks (in PDF bytes)
        pdf_str = pdf_bytes.decode("latin-1", errors="ignore")
        self.assertIn("INVOICE NO: " + inv_num, pdf_str)
        self.assertIn("Zoya Menon", pdf_str)
        self.assertIn("Dr. Priya Nair", pdf_str)
        self.assertIn("Two Thousand Five Hundred", pdf_str)
        self.assertIn("CLINICAL CONSULTATION TAX INVOICE", pdf_str)

        # Privacy verification: no diagnosis or clinical notes in invoice
        for forbidden in ["erectile", "dysfunction", "depression", "anxiety", "schizophrenia", "bipolar"]:
            self.assertNotIn(forbidden, pdf_str.lower())

        # Clean up created test pdf
        if pdf_path.exists():
            pdf_path.unlink()


if __name__ == "__main__":
    unittest.main()
