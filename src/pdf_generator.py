"""
Pure Python Minimal PDF Generator & Tax Invoice Engine for The Bengaluru Clinic.
Implements ISO 32000-1 / PDF 1.4 generation without any third-party libraries.
Generates compliant GST / Clinical Tax Invoices and Indian Rupee amount-to-words conversion.
"""

from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
import secrets
from typing import Any, Dict, Optional, Tuple

import config
from src.db import db_cursor, hash_token


# ----------------------------------------------------------------------
# Pure Python Indian Rupee Number to Words Converter
# ----------------------------------------------------------------------

ONES = [
    "", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
    "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
    "Seventeen", "Eighteen", "Nineteen"
]
TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _two_digits_to_words(n: int) -> str:
    if n < 20:
        return ONES[n]
    tens_val = TENS[n // 10]
    ones_val = ONES[n % 10]
    return f"{tens_val} {ones_val}".strip()


def _three_digits_to_words(n: int) -> str:
    hundreds = n // 100
    rem = n % 100
    res = []
    if hundreds > 0:
        res.append(f"{ONES[hundreds]} Hundred")
    if rem > 0:
        res.append(_two_digits_to_words(rem))
    return " ".join(res).strip()


def amount_to_indian_words(amount: float) -> str:
    """
    Converts a float rupee amount into formal Indian English words.
    Example: 2500.00 -> 'Rupees Two Thousand Five Hundred Only'
    Example: 15450.50 -> 'Rupees Fifteen Thousand Four Hundred Fifty and Fifty Paise Only'
    """
    if amount is None or amount < 0:
        return "Rupees Zero Only"

    rupees = int(amount)
    paise = int(round((amount - rupees) * 100))

    if rupees == 0 and paise == 0:
        return "Rupees Zero Only"

    # Indian numbering: Crores (10,000,000), Lakhs (100,000), Thousands (1,000), Hundreds (100)
    crores = rupees // 10000000
    rem = rupees % 10000000
    lakhs = rem // 100000
    rem = rem % 100000
    thousands = rem // 1000
    rem = rem % 1000

    parts = []
    if crores > 0:
        parts.append(f"{_two_digits_to_words(crores)} Crore")
    if lakhs > 0:
        parts.append(f"{_two_digits_to_words(lakhs)} Lakh")
    if thousands > 0:
        parts.append(f"{_two_digits_to_words(thousands)} Thousand")
    if rem > 0:
        parts.append(_three_digits_to_words(rem))

    words = " ".join(parts).strip()
    res = f"Rupees {words}" if words else "Rupees Zero"

    if paise > 0:
        res += f" and {_two_digits_to_words(paise)} Paise"

    return f"{res} Only"


# ----------------------------------------------------------------------
# Financial Year & Sequential Invoice Numbering
# ----------------------------------------------------------------------

def get_current_financial_year(dt: Optional[datetime] = None) -> str:
    """Returns Indian Financial Year format, e.g., '2026-27' (April 1 to March 31)."""
    now = dt or datetime.now()
    if now.month >= 4:
        start_year = now.year
        end_year = (now.year + 1) % 100
    else:
        start_year = now.year - 1
        end_year = now.year % 100
    return f"{start_year}-{end_year:02d}"


def get_next_invoice_number(booking_id: str, total_amount: float) -> Tuple[str, int, str]:
    """
    Generates or retrieves the unique, sequential invoice number for a booking.
    Format: TBC-INV-<FY>-<00001> (never reused).
    Returns (invoice_number, sequence, raw_access_token).
    """
    fy = get_current_financial_year()
    raw_access_token = secrets.token_urlsafe(32)
    token_hash = hash_token(raw_access_token)
    expires_at = (datetime.now(timezone.utc) + timedelta(days=60)).isoformat()
    now_str = datetime.now(timezone.utc).isoformat()

    with db_cursor(commit=True) as cur:
        # Check if invoice already exists for this booking
        cur.execute("SELECT invoice_number, sequence, access_token_hash FROM invoices WHERE booking_id = ?;", (booking_id,))
        existing = cur.fetchone()
        if existing:
            # If exists, update access token and return existing invoice number
            cur.execute("""
                UPDATE invoices
                SET access_token_hash = ?, access_token_expires_at = ?
                WHERE booking_id = ?;
            """, (token_hash, expires_at, booking_id))
            return existing["invoice_number"], existing["sequence"], raw_access_token

        # Compute next sequence for current financial year
        cur.execute("SELECT MAX(sequence) as max_seq FROM invoices WHERE financial_year = ?;", (fy,))
        row = cur.fetchone()
        next_seq = (row["max_seq"] or 0) + 1 if row else 1

        inv_num = f"{config.INVOICE_PREFIX}{fy}-{next_seq:04d}"
        pdf_rel_path = f"invoices/{inv_num}.pdf"

        cur.execute("""
            INSERT INTO invoices (
                invoice_number, booking_id, financial_year, sequence,
                created_at, pdf_path, access_token_hash, access_token_expires_at, total_amount
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            inv_num, booking_id, fy, next_seq,
            now_str, pdf_rel_path, token_hash, expires_at, total_amount
        ))

    return inv_num, next_seq, raw_access_token


# ----------------------------------------------------------------------
# Pure Python Minimal ISO 32000 PDF Generator
# ----------------------------------------------------------------------

def _escape_pdf_text(text: str) -> str:
    """Escapes special characters in PDF literal text strings."""
    if not text:
        return ""
    # Replace non-ASCII characters with safe ASCII equivalents
    safe_chars = []
    for ch in str(text):
        if ch in ("\\", "(", ")"):
            safe_chars.append("\\" + ch)
        elif ord(ch) < 128:
            safe_chars.append(ch)
        elif ch in ("₹", "₨"):
            safe_chars.append("INR ")
        elif ch in ("–", "—"):
            safe_chars.append("-")
        elif ch in ("‘", "’"):
            safe_chars.append("'")
        elif ch in ("“", "”"):
            safe_chars.append('"')
        elif ch == "·":
            safe_chars.append("-")
        else:
            safe_chars.append("?")
    return "".join(safe_chars)


class MinimalPDFBuilder:
    """Lightweight pure-Python PDF document builder."""
    def __init__(self):
        self.stream_commands = []
        # Page dimensions: A4 (595.28 x 841.89 points)
        self.page_width = 595.28
        self.page_height = 841.89

    def add_rect(self, x: float, y: float, w: float, h: float, fill_rgb: Optional[Tuple[float, float, float]] = None, stroke_rgb: Optional[Tuple[float, float, float]] = None):
        """Draws a rectangle with optional fill and stroke."""
        cmd = []
        if fill_rgb:
            cmd.append(f"{fill_rgb[0]:.3f} {fill_rgb[1]:.3f} {fill_rgb[2]:.3f} rg")
        if stroke_rgb:
            cmd.append(f"{stroke_rgb[0]:.3f} {stroke_rgb[1]:.3f} {stroke_rgb[2]:.3f} RG")
        cmd.append(f"{x:.2f} {y:.2f} {w:.2f} {h:.2f} re")
        if fill_rgb and stroke_rgb:
            cmd.append("B")
        elif fill_rgb:
            cmd.append("f")
        elif stroke_rgb:
            cmd.append("S")
        self.stream_commands.append(" ".join(cmd))

    def add_line(self, x1: float, y1: float, x2: float, y2: float, stroke_rgb: Tuple[float, float, float] = (0.8, 0.8, 0.8), width: float = 1.0):
        """Draws a stroked line."""
        self.stream_commands.append(f"{width:.2f} w {stroke_rgb[0]:.3f} {stroke_rgb[1]:.3f} {stroke_rgb[2]:.3f} RG {x1:.2f} y1:.2f m {x2:.2f} {y2:.2f} l S".replace("y1:.2f", f"{y1:.2f}"))

    def add_text(self, text: str, x: float, y: float, font: str = "/F1", size: float = 10, rgb: Tuple[float, float, float] = (0.1, 0.1, 0.1)):
        """Places text at (x, y) coordinates from bottom-left."""
        escaped = _escape_pdf_text(text)
        cmd = f"BT {rgb[0]:.3f} {rgb[1]:.3f} {rgb[2]:.3f} rg {font} {size:.1f} Tf 1 0 0 1 {x:.2f} {y:.2f} Tm ({escaped}) Tj ET"
        self.stream_commands.append(cmd)

    def build_pdf_bytes(self) -> bytes:
        """Assembles a valid ISO 32000 / PDF 1.4 binary file with cross-reference table."""
        content_stream_text = "\n".join(self.stream_commands)
        content_stream_bytes = content_stream_text.encode("latin1")
        stream_len = len(content_stream_bytes)

        # Object definitions
        objects = []
        
        # Obj 1: Catalog
        objects.append(b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj")
        
        # Obj 2: Pages
        objects.append(b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj")
        
        # Obj 3: Page (A4)
        objects.append(
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595.28 841.89] "
            b"/Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents 6 0 R >>\nendobj"
        )
        
        # Obj 4: Regular Font (Helvetica)
        objects.append(b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>\nendobj")
        
        # Obj 5: Bold Font (Helvetica-Bold)
        objects.append(b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>\nendobj")
        
        # Obj 6: Contents Stream
        stream_obj = (
            f"6 0 obj\n<< /Length {stream_len} >>\nstream\n".encode("latin1") +
            content_stream_bytes +
            b"\nendstream\nendobj"
        )
        objects.append(stream_obj)

        # Header
        header = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
        
        # Compute xref offsets
        offsets = [0]
        cur_offset = len(header)
        for obj in objects:
            offsets.append(cur_offset)
            cur_offset += len(obj) + 1  # newline after object

        # Assemble body
        body = b"\n".join(objects) + b"\n"
        xref_offset = len(header) + len(body)

        # Xref section
        xref_lines = [f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("latin1")]
        for off in offsets[1:]:
            xref_lines.append(f"{off:010d} 00000 n \n".encode("latin1"))
        xref_bytes = b"".join(xref_lines)

        # Trailer
        trailer = (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("latin1")

        return header + body + xref_bytes + trailer


def generate_tax_invoice_pdf(
    invoice_number: str,
    invoice_date: datetime,
    patient_full_name: str,
    doctor_name: str,
    appointment_time: datetime,
    fee_inr: float,
    payment_reference: str,
    payment_mode: str = "UPI / Razorpay Gateway",
    booking_id: str = "BKG-UNKNOWN",
) -> Tuple[bytes, Path]:
    """
    Generates a professional, legally structured Indian Clinical Tax Invoice PDF in pure Python.
    Complies strictly with zero-diagnosis rules (service listed strictly as 'Consultation').
    Saves a copy to data/invoices/<invoice_number>.pdf and returns (pdf_bytes, file_path).
    """
    pdf = MinimalPDFBuilder()

    # Emerald Brand Banner Header
    pdf.add_rect(30, 740, 535, 72, fill_rgb=(0.024, 0.306, 0.231))  # Emerald #064e3b
    pdf.add_text(config.CLINIC_LEGAL_NAME.upper(), 45, 786, font="/F2", size=14, rgb=(1.0, 1.0, 1.0))
    pdf.add_text("CLINICAL CONSULTATION TAX INVOICE", 45, 770, font="/F2", size=10, rgb=(0.655, 0.953, 0.816))
    pdf.add_text(config.CLINIC_ADDRESS, 45, 752, font="/F1", size=8, rgb=(0.8, 0.9, 0.85))

    # Invoice Metadata Box (Right Header)
    pdf.add_rect(380, 655, 185, 70, fill_rgb=(0.96, 0.98, 0.97), stroke_rgb=(0.85, 0.9, 0.88))
    pdf.add_text(f"INVOICE NO: {invoice_number}", 390, 708, font="/F2", size=9, rgb=(0.02, 0.4, 0.25))
    pdf.add_text(f"Date: {invoice_date.strftime('%d-%b-%Y')}", 390, 694, font="/F1", size=8.5, rgb=(0.2, 0.2, 0.2))
    pdf.add_text(f"Booking ID: {booking_id}", 390, 680, font="/F1", size=8.5, rgb=(0.2, 0.2, 0.2))
    gst_text = f"GSTIN: {config.CLINIC_GSTIN}" if config.CLINIC_GSTIN else "GSTIN: Exempt / Unregistered"
    pdf.add_text(gst_text, 390, 666, font="/F1", size=8, rgb=(0.4, 0.4, 0.4))

    # Bill To (Patient Details - Zero Diagnosis Protected)
    pdf.add_rect(30, 655, 340, 70, fill_rgb=(0.98, 0.98, 0.98), stroke_rgb=(0.9, 0.9, 0.9))
    pdf.add_text("BILLED TO (PATIENT):", 40, 710, font="/F2", size=8, rgb=(0.4, 0.4, 0.4))
    pdf.add_text(patient_full_name, 40, 694, font="/F2", size=11, rgb=(0.1, 0.1, 0.1))
    pdf.add_text("Place of Supply: Karnataka (State Code 29)", 40, 678, font="/F1", size=8.5, rgb=(0.3, 0.3, 0.3))
    pdf.add_text("Category: Outpatient Clinical Care", 40, 664, font="/F1", size=8, rgb=(0.4, 0.4, 0.4))

    # Appointment Particulars Bar
    pdf.add_rect(30, 610, 535, 35, fill_rgb=(0.94, 0.97, 0.95), stroke_rgb=(0.85, 0.9, 0.88))
    pdf.add_text(f"Attending Clinician: {doctor_name}", 42, 626, font="/F2", size=9.5, rgb=(0.02, 0.35, 0.22))
    pdf.add_text(f"Appointment Date & Time: {appointment_time.strftime('%A, %d %B %Y at %I:%M %p')}", 42, 615, font="/F1", size=8.5, rgb=(0.25, 0.25, 0.25))

    # Itemized Table Header
    pdf.add_rect(30, 570, 535, 25, fill_rgb=(0.02, 0.4, 0.25))
    pdf.add_text("SL", 40, 579, font="/F2", size=8.5, rgb=(1, 1, 1))
    pdf.add_text("SERVICE DESCRIPTION", 70, 579, font="/F2", size=8.5, rgb=(1, 1, 1))
    pdf.add_text("SAC CODE", 270, 579, font="/F2", size=8.5, rgb=(1, 1, 1))
    pdf.add_text("MODE", 350, 579, font="/F2", size=8.5, rgb=(1, 1, 1))
    pdf.add_text("RATE (INR)", 430, 579, font="/F2", size=8.5, rgb=(1, 1, 1))
    pdf.add_text("AMOUNT (INR)", 495, 579, font="/F2", size=8.5, rgb=(1, 1, 1))

    # Table Row 1 (Strictly 'Consultation' - Zero Diagnosis compliant)
    pdf.add_rect(30, 520, 535, 50, fill_rgb=(1, 1, 1), stroke_rgb=(0.9, 0.9, 0.9))
    pdf.add_text("01", 40, 546, font="/F1", size=9, rgb=(0.3, 0.3, 0.3))
    pdf.add_text("Consultation", 70, 550, font="/F2", size=9.5, rgb=(0.1, 0.1, 0.1))
    pdf.add_text("Clinical Psychology / Medical Healthcare Service", 70, 536, font="/F1", size=7.5, rgb=(0.4, 0.4, 0.4))
    pdf.add_text(config.SAC_CODE, 270, 546, font="/F1", size=9, rgb=(0.3, 0.3, 0.3))
    pdf.add_text("In-Person", 350, 546, font="/F1", size=9, rgb=(0.3, 0.3, 0.3))
    pdf.add_text(f"{fee_inr:,.2f}", 430, 546, font="/F1", size=9, rgb=(0.2, 0.2, 0.2))
    pdf.add_text(f"{fee_inr:,.2f}", 500, 546, font="/F2", size=9, rgb=(0.1, 0.1, 0.1))

    # Calculation Subtotal and Tax
    tax_percent = config.TAX_RATE_PERCENT
    tax_amount = round(fee_inr * (tax_percent / 100.0), 2)
    grand_total = fee_inr + tax_amount

    pdf.add_rect(330, 430, 235, 80, fill_rgb=(0.98, 0.98, 0.98), stroke_rgb=(0.85, 0.85, 0.85))
    pdf.add_text("Subtotal:", 345, 492, font="/F1", size=8.5, rgb=(0.4, 0.4, 0.4))
    pdf.add_text(f"INR {fee_inr:,.2f}", 490, 492, font="/F1", size=8.5, rgb=(0.2, 0.2, 0.2))

    tax_label = f"GST ({tax_percent:.1f}%):" if tax_percent > 0 else "GST (Exempt):"
    pdf.add_text(tax_label, 345, 474, font="/F1", size=8.5, rgb=(0.4, 0.4, 0.4))
    pdf.add_text(f"INR {tax_amount:,.2f}", 490, 474, font="/F1", size=8.5, rgb=(0.2, 0.2, 0.2))

    pdf.add_line(340, 462, 555, 462, stroke_rgb=(0.8, 0.8, 0.8), width=0.5)
    pdf.add_text("TOTAL PAID:", 345, 444, font="/F2", size=10, rgb=(0.02, 0.35, 0.22))
    pdf.add_text(f"INR {grand_total:,.2f}", 475, 444, font="/F2", size=11, rgb=(0.02, 0.35, 0.22))

    # Payment Summary Box (Left)
    pdf.add_rect(30, 430, 285, 80, fill_rgb=(0.98, 0.98, 0.98), stroke_rgb=(0.88, 0.88, 0.88))
    pdf.add_text("PAYMENT CONFIRMATION:", 40, 492, font="/F2", size=8, rgb=(0.4, 0.4, 0.4))
    pdf.add_text(f"Status: PAID IN FULL", 40, 476, font="/F2", size=9, rgb=(0.02, 0.4, 0.25))
    pdf.add_text(f"Payment Mode: {payment_mode}", 40, 460, font="/F1", size=8, rgb=(0.3, 0.3, 0.3))
    pdf.add_text(f"Gateway Reference: {payment_reference}", 40, 444, font="/F1", size=7.5, rgb=(0.4, 0.4, 0.4))

    # Amount in Words Banner
    pdf.add_rect(30, 385, 535, 32, fill_rgb=(0.94, 0.97, 0.95), stroke_rgb=(0.85, 0.9, 0.88))
    pdf.add_text("Amount in Words:", 40, 404, font="/F2", size=7.5, rgb=(0.4, 0.4, 0.4))
    words_str = amount_to_indian_words(grand_total)
    pdf.add_text(words_str, 40, 392, font="/F2", size=8.5, rgb=(0.02, 0.35, 0.22))

    # Tax & Statutory Notes
    pdf.add_rect(30, 305, 535, 68, fill_rgb=(0.99, 0.99, 0.99), stroke_rgb=(0.92, 0.92, 0.92))
    pdf.add_text("TAX EXEMPTION & REGULATORY NOTE:", 40, 357, font="/F2", size=7.5, rgb=(0.4, 0.4, 0.4))
    pdf.add_text(config.TAX_NOTE[:115], 40, 343, font="/F1", size=7.5, rgb=(0.35, 0.35, 0.35))
    if len(config.TAX_NOTE) > 115:
        pdf.add_text(config.TAX_NOTE[115:230], 40, 331, font="/F1", size=7.5, rgb=(0.35, 0.35, 0.35))
    pdf.add_text("Note: Formal tax classification and accounting treatment must be confirmed by the clinic's statutory CA.", 40, 317, font="/F1", size=7, rgb=(0.5, 0.5, 0.5))

    # Sign-off & Computer Generated Notice
    pdf.add_line(30, 180, 565, 180, stroke_rgb=(0.85, 0.85, 0.85), width=0.5)
    pdf.add_text("This is a computer-generated tax invoice. No physical signature is required.", 155, 160, font="/F2", size=8.5, rgb=(0.4, 0.4, 0.4))
    pdf.add_text(f"Generated at: {datetime.now().strftime('%d-%b-%Y %I:%M:%S %p IST')} · The Bengaluru Clinic Engine", 145, 145, font="/F1", size=7.5, rgb=(0.55, 0.55, 0.55))

    pdf_bytes = pdf.build_pdf_bytes()

    # Save to disk
    pdf_path = config.INVOICES_DIR / f"{invoice_number}.pdf"
    with open(pdf_path, "wb") as f:
        f.write(pdf_bytes)

    return pdf_bytes, pdf_path
