#!/usr/bin/env python3
"""
CLI Utility for Managing The Bengaluru Clinic Email Engine.
Usage:
  python manage_mail.py status
  python manage_mail.py retry-dead
  python manage_mail.py send-test you@example.com
  python manage_mail.py send-digest-now
"""

from datetime import datetime
import sys
from pathlib import Path

# Ensure root dir is in sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import config
from src.db import db_cursor
from src.mailer import (
    enqueue_email,
    render_email,
    retry_dead_emails,
    trigger_weekly_digest_now,
    _process_queue_batch,
)


def cmd_status():
    """Prints current email queue metrics and transport status."""
    print("=" * 60)
    print(" THE BENGALURU CLINIC - EMAIL SUBSYSTEM STATUS")
    print("=" * 60)
    print(f" Mail Mode        : {config.MAIL_MODE.upper()}")
    print(f" Sender           : {config.MAIL_FROM_NAME} <{config.MAIL_FROM_ADDRESS}>")
    print(f" SMTP Host        : {config.SMTP_HOST}:{config.SMTP_PORT} (TLS: {config.SMTP_USE_TLS})")
    print(f" Database         : {config.DATABASE_PATH}")
    print("-" * 60)

    with db_cursor(commit=False) as cur:
        cur.execute("SELECT status, COUNT(*) as cnt FROM email_queue GROUP BY status;")
        counts = {r["status"]: r["cnt"] for r in cur.fetchall()}

        cur.execute("SELECT COUNT(*) as cnt FROM users;")
        user_count = cur.fetchone()["cnt"]

        cur.execute("SELECT status, COUNT(*) as cnt FROM subscriptions GROUP BY status;")
        sub_counts = {r["status"]: r["cnt"] for r in cur.fetchall()}

    print(f" Total Users      : {user_count}")
    print(f" Subscriptions    : Active={sub_counts.get('ACTIVE', 0)}, Pending={sub_counts.get('PENDING', 0)}, Unsubscribed={sub_counts.get('UNSUBSCRIBED', 0)}")
    print("-" * 60)
    print(" Queue Statistics:")
    print(f"  - QUEUED        : {counts.get('QUEUED', 0)}")
    print(f"  - SENT (SMTP)   : {counts.get('SENT', 0)}")
    print(f"  - SENT-IN-DEV   : {counts.get('SENT-IN-DEV', 0)}")
    print(f"  - FAILED        : {counts.get('FAILED', 0)}")
    print(f"  - DEAD          : {counts.get('DEAD', 0)}")
    print("=" * 60)


def cmd_retry_dead():
    """Resets DEAD emails back to QUEUED."""
    count = retry_dead_emails()
    print(f"[INFO] Successfully reset {count} DEAD emails back to QUEUED status.")


def cmd_send_test(to_email: str):
    """Enqueues and processes a test diagnostic email."""
    if not to_email or "@" not in to_email:
        print("[ERROR] Please specify a valid recipient email address.")
        sys.exit(1)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    transport_desc = f"Local Dev Mailbox (/dev/mailbox)" if config.MAIL_MODE == "dev" else f"SMTP ({config.SMTP_HOST})"

    html_b, text_b = render_email(
        template_name="test_email",
        subject="The Bengaluru Clinic · Diagnostic Mail Test",
        header_title="Mail Subsystem Diagnostic",
        header_subtitle="Verification of Queue & Transport Engine",
        context={
            "patient_name": "Clinic Administrator",
            "mail_mode": config.MAIL_MODE.upper(),
            "recipient_email": to_email,
            "sent_time_str": now_str,
            "transport_info": transport_desc,
        }
    )

    qid = enqueue_email(
        to_email=to_email,
        template="test_email",
        subject="The Bengaluru Clinic · Diagnostic Mail Test",
        html_body=html_b,
        text_body=text_b,
    )
    print(f"[OK] Test email enqueued successfully with Queue ID: {qid}")

    # Process batch immediately
    processed = _process_queue_batch()
    print(f"[OK] Background queue processed ({processed} item(s) dispatched).")


def cmd_send_digest_now():
    """Immediately triggers the rotating weekly digest for active subscribers."""
    count = trigger_weekly_digest_now()
    print(f"[OK] Weekly digest dispatched to {count} active subscriber(s).")
    processed = _process_queue_batch()
    print(f"[OK] Background worker dispatched {processed} email(s).")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1].lower().strip()
    if cmd == "status":
        cmd_status()
    elif cmd == "retry-dead":
        cmd_retry_dead()
    elif cmd == "send-test":
        if len(sys.argv) < 3:
            print("Usage: python manage_mail.py send-test you@example.com")
            sys.exit(1)
        cmd_send_test(sys.argv[2])
    elif cmd == "send-digest-now":
        cmd_send_digest_now()
    else:
        print(f"Unknown command: '{cmd}'")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
