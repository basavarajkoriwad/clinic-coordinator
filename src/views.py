"""
HTML View Templates for The Bengaluru Clinic Auth, Account, Privacy & Dev Mailbox.
Zero-dependency HTML string generators styled with modern dark Tailwind CSS and emerald branding.
"""

from datetime import datetime
import html
import json
from typing import Any, Dict, List, Optional

import config


def _base_page_layout(title: str, content: str, user: Optional[Dict[str, Any]] = None) -> str:
    """Standard wrapper for auth and account pages."""
    auth_links = ""
    if user:
        email_prefix = user.get("email", "").split("@")[0]
        auth_links = f"""
            <span class="text-xs text-slate-400 font-mono">Signed in as <strong class="text-emerald-400">{html.escape(email_prefix)}</strong></span>
            <a href="/account" class="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold transition">Account</a>
            <form action="/logout" method="POST" class="inline m-0">
                <button type="submit" class="px-3 py-1.5 rounded-lg bg-slate-900 hover:bg-rose-950/80 hover:text-rose-300 text-slate-400 text-xs font-semibold transition border border-slate-800">Logout</button>
            </form>
        """
    else:
        auth_links = """
            <a href="/login" class="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold transition">Log In</a>
            <a href="/signup" class="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold transition shadow-sm">Sign Up</a>
        """

    dev_mailbox_pill = ""
    if config.MAIL_MODE == "dev":
        dev_mailbox_pill = """
            <a href="/dev/mailbox" class="px-2.5 py-1 rounded-md bg-amber-950/80 border border-amber-600/60 text-amber-300 text-[11px] font-mono hover:bg-amber-900 transition flex items-center gap-1.5" title="Dev Mailbox">
                <span class="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse"></span>
                Dev Mailbox
            </a>
        """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html.escape(title)} · The Bengaluru Clinic</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; }}
    </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen flex flex-col antialiased">
    <!-- Header -->
    <header class="border-b border-slate-800/80 bg-slate-950/80 backdrop-blur sticky top-0 z-40">
        <div class="max-w-6xl mx-auto px-4 h-16 flex items-center justify-between">
            <div class="flex items-center space-x-3">
                <a href="/" class="flex items-center space-x-2.5 group">
                    <div class="w-8 h-8 rounded-xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400 font-bold group-hover:bg-emerald-500/20 transition">
                        <i class="fa-solid fa-heart-pulse text-sm"></i>
                    </div>
                    <div>
                        <div class="text-sm font-extrabold tracking-tight text-white">The Bengaluru Clinic</div>
                        <div class="text-[10px] text-slate-400">Confidential Clinical Care</div>
                    </div>
                </a>
                {dev_mailbox_pill}
            </div>
            <div class="flex items-center space-x-2">
                <a href="/" class="px-2.5 py-1.5 text-xs text-slate-400 hover:text-white transition">Home</a>
                <a href="/privacy" class="px-2.5 py-1.5 text-xs text-slate-400 hover:text-white transition">Privacy</a>
                {auth_links}
            </div>
        </div>
    </header>

    <!-- Main Content Area -->
    <main class="flex-1 flex items-center justify-center p-4 py-10">
        {content}
    </main>

    <!-- Footer -->
    <footer class="border-t border-slate-900 bg-slate-950/60 py-6 text-center text-xs text-slate-500">
        <div class="max-w-5xl mx-auto px-4 space-y-2">
            <p><strong>{html.escape(config.CLINIC_LEGAL_NAME)}</strong> · Suite 302, 3rd Floor, Indiranagar 100ft Road, Bengaluru 560038</p>
            <p>Direct Desk: {html.escape(config.CLINIC_PHONE)} · Mon – Sat (9:00 AM – 8:00 PM) · <a href="/privacy" class="text-emerald-400 hover:underline">DPDP Privacy Disclosures</a></p>
        </div>
    </footer>
</body>
</html>"""


# ----------------------------------------------------------------------
# 1. Sign Up Page
# ----------------------------------------------------------------------
def render_signup_page(csrf_token: str, error: str = "") -> str:
    err_box = f'<div class="bg-rose-950/80 border border-rose-800 text-rose-300 p-3 rounded-xl text-xs mb-4">{html.escape(error)}</div>' if error else ""
    content = f"""
    <div class="max-w-md w-full bg-slate-900 border border-slate-800 rounded-2xl p-6 sm:p-8 shadow-2xl">
        <div class="text-center mb-6">
            <div class="inline-flex w-10 h-10 rounded-2xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 items-center justify-center mb-3">
                <i class="fa-solid fa-user-plus text-base"></i>
            </div>
            <h1 class="text-xl font-extrabold text-white">Create Patient Account</h1>
            <p class="text-xs text-slate-400 mt-1">Discreet and confidential. Access receipts, invoices, and care vault.</p>
        </div>

        {err_box}

        <form action="/signup" method="POST" class="space-y-4">
            <input type="hidden" name="csrf_token" value="{html.escape(csrf_token)}">
            <div>
                <label class="block text-xs font-semibold text-slate-300 mb-1.5">Email Address</label>
                <input type="email" name="email" required autocomplete="email" placeholder="patient@example.com" class="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-sm text-white placeholder-slate-600 focus:outline-none focus:border-emerald-500 transition font-mono">
            </div>

            <div>
                <label class="block text-xs font-semibold text-slate-300 mb-1.5">Password</label>
                <input type="password" name="password" required minlength="8" placeholder="••••••••••••" class="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-sm text-white placeholder-slate-600 focus:outline-none focus:border-emerald-500 transition">
                <p class="text-[11px] text-slate-500 mt-1">Minimum 8 characters. Stored securely with PBKDF2-HMAC-SHA256.</p>
            </div>

            <button type="submit" class="w-full py-2.5 px-4 bg-emerald-600 hover:bg-emerald-500 text-white font-bold rounded-xl shadow-md transition cursor-pointer text-sm">
                Create Account
            </button>
        </form>

        <div class="mt-6 text-center text-xs text-slate-400">
            Already have an account? <a href="/login" class="text-emerald-400 font-semibold hover:underline">Log in here</a>
        </div>
    </div>
    """
    return _base_page_layout("Sign Up", content)


# ----------------------------------------------------------------------
# 2. Login Page
# ----------------------------------------------------------------------
def render_login_page(csrf_token: str, error: str = "", message: str = "", unverified_email: str = "") -> str:
    err_box = f'<div class="bg-rose-950/80 border border-rose-800 text-rose-300 p-3 rounded-xl text-xs mb-4">{html.escape(error)}</div>' if error else ""
    msg_box = f'<div class="bg-emerald-950/80 border border-emerald-800 text-emerald-300 p-3 rounded-xl text-xs mb-4">{html.escape(message)}</div>' if message else ""
    
    resend_block = ""
    if unverified_email:
        resend_block = f"""
        <div class="mt-4 pt-4 border-t border-slate-800/80 text-center">
            <p class="text-xs text-amber-300 mb-2">Haven't verified your email yet?</p>
            <form action="/resend-verification" method="POST" class="inline m-0">
                <input type="hidden" name="csrf_token" value="{html.escape(csrf_token)}">
                <input type="hidden" name="email" value="{html.escape(unverified_email)}">
                <button type="submit" class="px-3 py-1.5 rounded-lg bg-amber-950/80 hover:bg-amber-900 border border-amber-600/60 text-amber-300 text-xs font-semibold transition cursor-pointer">
                    Resend Verification Email
                </button>
            </form>
        </div>
        """

    content = f"""
    <div class="max-w-md w-full bg-slate-900 border border-slate-800 rounded-2xl p-6 sm:p-8 shadow-2xl">
        <div class="text-center mb-6">
            <div class="inline-flex w-10 h-10 rounded-2xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 items-center justify-center mb-3">
                <i class="fa-solid fa-right-to-bracket text-base"></i>
            </div>
            <h1 class="text-xl font-extrabold text-white">Patient Account Login</h1>
            <p class="text-xs text-slate-400 mt-1">Access your consultation receipts and manage care notifications.</p>
        </div>

        {msg_box}
        {err_box}

        <form action="/login" method="POST" class="space-y-4">
            <input type="hidden" name="csrf_token" value="{html.escape(csrf_token)}">
            <div>
                <label class="block text-xs font-semibold text-slate-300 mb-1.5">Email Address</label>
                <input type="email" name="email" value="{html.escape(unverified_email)}" required autocomplete="email" placeholder="patient@example.com" class="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-sm text-white placeholder-slate-600 focus:outline-none focus:border-emerald-500 transition font-mono">
            </div>

            <div>
                <div class="flex justify-between items-center mb-1.5">
                    <label class="text-xs font-semibold text-slate-300">Password</label>
                    <a href="/forgot" class="text-[11px] text-emerald-400 hover:underline">Forgot password?</a>
                </div>
                <input type="password" name="password" required placeholder="••••••••••••" class="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-sm text-white placeholder-slate-600 focus:outline-none focus:border-emerald-500 transition">
            </div>

            <button type="submit" class="w-full py-2.5 px-4 bg-emerald-600 hover:bg-emerald-500 text-white font-bold rounded-xl shadow-md transition cursor-pointer text-sm">
                Log In
            </button>
        </form>

        {resend_block}

        <div class="mt-6 text-center text-xs text-slate-400">
            Don't have an account? <a href="/signup" class="text-emerald-400 font-semibold hover:underline">Create one here</a>
        </div>
    </div>
    """
    return _base_page_layout("Log In", content)


# ----------------------------------------------------------------------
# 3. Email Verification Page
# ----------------------------------------------------------------------
def render_verify_page(success: bool, message: str) -> str:
    icon = '<i class="fa-solid fa-circle-check text-2xl text-emerald-400"></i>' if success else '<i class="fa-solid fa-circle-exclamation text-2xl text-rose-400"></i>'
    title = "Email Verified Successfully" if success else "Verification Failed"
    btn = '<a href="/login" class="inline-block py-2 px-5 bg-emerald-600 hover:bg-emerald-500 text-white font-bold rounded-xl text-xs transition">Proceed to Login</a>' if success else '<a href="/login" class="inline-block py-2 px-5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl text-xs transition">Return to Login</a>'

    content = f"""
    <div class="max-w-md w-full bg-slate-900 border border-slate-800 rounded-2xl p-8 text-center shadow-2xl">
        <div class="mb-4">{icon}</div>
        <h1 class="text-xl font-bold text-white mb-2">{title}</h1>
        <p class="text-xs text-slate-300 mb-6 leading-relaxed">{html.escape(message)}</p>
        <div>{btn}</div>
    </div>
    """
    return _base_page_layout("Email Verification", content)


# ----------------------------------------------------------------------
# 4. Forgot & Reset Password Pages
# ----------------------------------------------------------------------
def render_forgot_page(csrf_token: str, message: str = "", error: str = "") -> str:
    msg_box = f'<div class="bg-emerald-950/80 border border-emerald-800 text-emerald-300 p-3 rounded-xl text-xs mb-4">{html.escape(message)}</div>' if message else ""
    err_box = f'<div class="bg-rose-950/80 border border-rose-800 text-rose-300 p-3 rounded-xl text-xs mb-4">{html.escape(error)}</div>' if error else ""

    content = f"""
    <div class="max-w-md w-full bg-slate-900 border border-slate-800 rounded-2xl p-6 sm:p-8 shadow-2xl">
        <div class="text-center mb-6">
            <div class="inline-flex w-10 h-10 rounded-2xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 items-center justify-center mb-3">
                <i class="fa-solid fa-key text-base"></i>
            </div>
            <h1 class="text-xl font-extrabold text-white">Reset Your Password</h1>
            <p class="text-xs text-slate-400 mt-1">Enter your registered email to receive a secure single-use reset link.</p>
        </div>

        {msg_box}
        {err_box}

        <form action="/forgot" method="POST" class="space-y-4">
            <input type="hidden" name="csrf_token" value="{html.escape(csrf_token)}">
            <div>
                <label class="block text-xs font-semibold text-slate-300 mb-1.5">Email Address</label>
                <input type="email" name="email" required placeholder="patient@example.com" class="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-sm text-white placeholder-slate-600 focus:outline-none focus:border-emerald-500 transition font-mono">
            </div>

            <button type="submit" class="w-full py-2.5 px-4 bg-emerald-600 hover:bg-emerald-500 text-white font-bold rounded-xl shadow-md transition cursor-pointer text-sm">
                Send Reset Link
            </button>
        </form>

        <div class="mt-6 text-center text-xs text-slate-400">
            Remembered your password? <a href="/login" class="text-emerald-400 font-semibold hover:underline">Back to Login</a>
        </div>
    </div>
    """
    return _base_page_layout("Forgot Password", content)


def render_reset_page(csrf_token: str, token: str, error: str = "", message: str = "") -> str:
    err_box = f'<div class="bg-rose-950/80 border border-rose-800 text-rose-300 p-3 rounded-xl text-xs mb-4">{html.escape(error)}</div>' if error else ""
    msg_box = f'<div class="bg-emerald-950/80 border border-emerald-800 text-emerald-300 p-3 rounded-xl text-xs mb-4">{html.escape(message)}</div>' if message else ""

    content = f"""
    <div class="max-w-md w-full bg-slate-900 border border-slate-800 rounded-2xl p-6 sm:p-8 shadow-2xl">
        <div class="text-center mb-6">
            <div class="inline-flex w-10 h-10 rounded-2xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 items-center justify-center mb-3">
                <i class="fa-solid fa-lock text-base"></i>
            </div>
            <h1 class="text-xl font-extrabold text-white">Choose New Password</h1>
            <p class="text-xs text-slate-400 mt-1">Please enter a new password of at least 8 characters.</p>
        </div>

        {msg_box}
        {err_box}

        <form action="/reset" method="POST" class="space-y-4">
            <input type="hidden" name="csrf_token" value="{html.escape(csrf_token)}">
            <input type="hidden" name="token" value="{html.escape(token)}">
            <div>
                <label class="block text-xs font-semibold text-slate-300 mb-1.5">New Password</label>
                <input type="password" name="new_password" required minlength="8" placeholder="••••••••••••" class="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-sm text-white placeholder-slate-600 focus:outline-none focus:border-emerald-500 transition">
            </div>

            <button type="submit" class="w-full py-2.5 px-4 bg-emerald-600 hover:bg-emerald-500 text-white font-bold rounded-xl shadow-md transition cursor-pointer text-sm">
                Save New Password
            </button>
        </form>
    </div>
    """
    return _base_page_layout("Reset Password", content)


# ----------------------------------------------------------------------
# 5. Patient Account Portal
# ----------------------------------------------------------------------
def render_account_page(
    user: Dict[str, Any],
    subscription: Optional[Dict[str, Any]],
    csrf_token: str,
    message: str = "",
    error: str = "",
) -> str:
    msg_box = f'<div class="bg-emerald-950/80 border border-emerald-800 text-emerald-300 p-3 rounded-xl text-xs mb-6">{html.escape(message)}</div>' if message else ""
    err_box = f'<div class="bg-rose-950/80 border border-rose-800 text-rose-300 p-3 rounded-xl text-xs mb-6">{html.escape(error)}</div>' if error else ""

    sub_status = subscription["status"] if subscription else "NOT_SUBSCRIBED"
    status_badge = {
        "ACTIVE": '<span class="px-2.5 py-0.5 rounded-full bg-emerald-950 border border-emerald-700/80 text-emerald-400 font-bold text-[11px] font-mono">ACTIVE</span>',
        "PENDING": '<span class="px-2.5 py-0.5 rounded-full bg-amber-950 border border-amber-700/80 text-amber-400 font-bold text-[11px] font-mono">PENDING CONFIRMATION</span>',
        "UNSUBSCRIBED": '<span class="px-2.5 py-0.5 rounded-full bg-slate-800 text-slate-400 font-bold text-[11px] font-mono">UNSUBSCRIBED</span>',
        "NOT_SUBSCRIBED": '<span class="px-2.5 py-0.5 rounded-full bg-slate-800 text-slate-400 font-bold text-[11px] font-mono">NOT SUBSCRIBED</span>',
    }.get(sub_status, sub_status)

    # Preferences parsing
    prefs = {"wellness_tips": True, "clinic_news": True, "appointment_reminders": True}
    if subscription and subscription.get("preferences"):
        try:
            prefs.update(json.loads(subscription["preferences"]))
        except Exception:
            pass

    # Double Opt-In Banner (Section 5)
    stay_connected_banner = ""
    if sub_status in ("NOT_SUBSCRIBED", "UNSUBSCRIBED"):
        stay_connected_banner = f"""
        <div class="bg-emerald-950/30 border border-emerald-800/60 rounded-2xl p-5 mb-6">
            <h3 class="text-sm font-bold text-white mb-2 flex items-center gap-2">
                <i class="fa-solid fa-envelope-open-text text-emerald-400"></i>
                Stay Connected with The Bengaluru Clinic
            </h3>
            <p class="text-xs text-slate-300 mb-4 leading-relaxed">
                Receive our curated weekly digest on mindfulness and nervous system regulation, clinic scheduling announcements, and care continuity notices.
            </p>
            <form action="/consent" method="POST" class="space-y-3">
                <input type="hidden" name="csrf_token" value="{html.escape(csrf_token)}">
                <label class="flex items-start space-x-2.5 cursor-pointer text-xs text-slate-300">
                    <input type="checkbox" name="consent" value="1" class="mt-0.5 rounded bg-slate-950 border-slate-700 text-emerald-600 focus:ring-0">
                    <span>I consent to receive occasional clinical wellness tips and care updates. I understand I can withdraw consent or unsubscribe at any time in one click.</span>
                </label>
                <div>
                    <button type="submit" class="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white font-bold rounded-xl text-xs transition shadow-sm cursor-pointer">
                        Send Double Opt-In Confirmation
                    </button>
                </div>
            </form>
        </div>
        """
    elif sub_status == "PENDING":
        stay_connected_banner = f"""
        <div class="bg-amber-950/30 border border-amber-800/60 rounded-2xl p-5 mb-6">
            <h3 class="text-sm font-bold text-amber-300 mb-1 flex items-center gap-2">
                <i class="fa-solid fa-hourglass-half"></i>
                Confirmation Email Sent
            </h3>
            <p class="text-xs text-slate-300 leading-relaxed">
                We emailed a double opt-in confirmation link to your address. Click the link in that email to activate your subscription and receive your Welcome Guide. Check the <a href="/dev/mailbox" class="text-emerald-400 underline">Dev Mailbox</a> to view it.
            </p>
        </div>
        """

    content = f"""
    <div class="max-w-2xl w-full space-y-6">
        <!-- Account Overview Card -->
        <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl">
            <div class="flex items-center justify-between pb-4 border-b border-slate-800">
                <div class="flex items-center space-x-3">
                    <div class="w-10 h-10 rounded-2xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 flex items-center justify-center font-bold">
                        <i class="fa-solid fa-user-shield"></i>
                    </div>
                    <div>
                        <h2 class="text-base font-extrabold text-white">Patient Profile</h2>
                        <p class="text-xs text-slate-400 font-mono">{html.escape(user['email'])}</p>
                    </div>
                </div>
                <div>
                    <span class="px-2.5 py-1 rounded-full bg-emerald-950/80 border border-emerald-800 text-emerald-400 text-xs font-bold font-mono">
                        <i class="fa-solid fa-check-circle text-[10px] mr-1"></i>VERIFIED
                    </span>
                </div>
            </div>

            <div class="grid grid-cols-2 gap-4 pt-4 text-xs">
                <div>
                    <span class="text-slate-500">Account Created</span>
                    <p class="text-slate-300 font-mono mt-0.5">{html.escape(user['created_at'][:10])}</p>
                </div>
                <div>
                    <span class="text-slate-500">Subscription Status</span>
                    <div class="mt-0.5">{status_badge}</div>
                </div>
            </div>
        </div>

        {msg_box}
        {err_box}
        {stay_connected_banner}

        <!-- Subscription Preferences & Actions -->
        <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-5">
            <div class="flex items-center justify-between">
                <div>
                    <h3 class="text-sm font-bold text-white">Communication Preferences</h3>
                    <p class="text-xs text-slate-400">Manage what clinical notifications and articles you receive.</p>
                </div>
            </div>

            <form action="/account/preferences" method="POST" class="space-y-3 pt-2">
                <input type="hidden" name="csrf_token" value="{html.escape(csrf_token)}">
                
                <label class="flex items-center justify-between p-3 rounded-xl bg-slate-950 border border-slate-800/80 cursor-pointer">
                    <div>
                        <div class="text-xs font-semibold text-slate-200">Restorative Wellness Digest</div>
                        <div class="text-[11px] text-slate-500">Weekly non-clinical notes on sleep, nervous system regulation, and boundaries.</div>
                    </div>
                    <input type="checkbox" name="wellness_tips" value="1" {'checked' if prefs.get('wellness_tips') else ''} class="rounded bg-slate-900 border-slate-700 text-emerald-600 focus:ring-0">
                </label>

                <label class="flex items-center justify-between p-3 rounded-xl bg-slate-950 border border-slate-800/80 cursor-pointer">
                    <div>
                        <div class="text-xs font-semibold text-slate-200">Clinic Announcements & Schedules</div>
                        <div class="text-[11px] text-slate-500">Holiday desk hours, new clinical services, and Indiranagar clinic updates.</div>
                    </div>
                    <input type="checkbox" name="clinic_news" value="1" {'checked' if prefs.get('clinic_news') else ''} class="rounded bg-slate-900 border-slate-700 text-emerald-600 focus:ring-0">
                </label>

                <label class="flex items-center justify-between p-3 rounded-xl bg-slate-950 border border-slate-800/80 cursor-pointer">
                    <div>
                        <div class="text-xs font-semibold text-slate-200">Appointment Care Reminders</div>
                        <div class="text-[11px] text-slate-500">72-hour and 24-hour discrete appointment reminders prior to consultations.</div>
                    </div>
                    <input type="checkbox" name="appointment_reminders" value="1" {'checked' if prefs.get('appointment_reminders') else ''} class="rounded bg-slate-900 border-slate-700 text-emerald-600 focus:ring-0">
                </label>

                <div class="pt-2 flex justify-between items-center">
                    <button type="submit" class="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white font-bold rounded-xl text-xs transition shadow-sm cursor-pointer">
                        Save Preferences
                    </button>
                </div>
            </form>

            <div class="pt-4 border-t border-slate-800 flex flex-wrap gap-2 justify-between items-center text-xs">
                <!-- Send test email button -->
                <form action="/account/send-test" method="POST" class="inline m-0">
                    <input type="hidden" name="csrf_token" value="{html.escape(csrf_token)}">
                    <button type="submit" class="px-3.5 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition cursor-pointer flex items-center gap-1.5 font-semibold">
                        <i class="fa-solid fa-paper-plane text-[10px]"></i>
                        Send Test Diagnostic Email
                    </button>
                </form>

                <!-- Unsubscribe / Subscribe toggle -->
                {'<form action="/account/unsubscribe" method="POST" class="inline m-0"><input type="hidden" name="csrf_token" value="' + html.escape(csrf_token) + '"><button type="submit" class="text-xs text-slate-400 hover:text-amber-400 underline">Unsubscribe from all marketing</button></form>' if sub_status == 'ACTIVE' else ''}
            </div>
        </div>

        <!-- Privacy & DPDP Account Deletion Card -->
        <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl">
            <h3 class="text-sm font-bold text-rose-400 mb-1">Data Erasure & Account Deletion (DPDP Act 2023)</h3>
            <p class="text-xs text-slate-400 leading-relaxed mb-4">
                You have the statutory right to request erasure of your patient account, login credentials, active sessions, and communication subscriptions. Statutory doctor tax invoices previously issued are retained as legally required under Indian tax law.
            </p>
            <form action="/account/delete" method="POST" onsubmit="return confirm('Are you sure you wish to delete your account and all associated communication data? This action is irreversible.');">
                <input type="hidden" name="csrf_token" value="{html.escape(csrf_token)}">
                <button type="submit" class="px-4 py-2 rounded-xl bg-rose-950/80 hover:bg-rose-900 border border-rose-800/80 text-rose-300 font-bold text-xs transition cursor-pointer">
                    Delete My Account and Data
                </button>
            </form>
        </div>
    </div>
    """
    return _base_page_layout("Patient Account", content, user=user)


# ----------------------------------------------------------------------
# 6. Double Opt-In Confirmation & Unsubscribe Outcome Pages
# ----------------------------------------------------------------------
def render_confirm_subscription_page(success: bool, message: str) -> str:
    icon = '<i class="fa-solid fa-circle-check text-3xl text-emerald-400"></i>' if success else '<i class="fa-solid fa-triangle-exclamation text-3xl text-amber-400"></i>'
    title = "Subscription Confirmed" if success else "Confirmation Issue"
    
    content = f"""
    <div class="max-w-md w-full bg-slate-900 border border-slate-800 rounded-2xl p-8 text-center shadow-2xl space-y-4">
        <div>{icon}</div>
        <h1 class="text-xl font-bold text-white">{title}</h1>
        <p class="text-xs text-slate-300 leading-relaxed">{html.escape(message)}</p>
        <div class="pt-2">
            <a href="/account" class="inline-block py-2 px-5 bg-emerald-600 hover:bg-emerald-500 text-white font-bold rounded-xl text-xs transition">Go to My Account</a>
        </div>
    </div>
    """
    return _base_page_layout("Subscription Confirmation", content)


def render_unsubscribe_page(success: bool, message: str) -> str:
    content = f"""
    <div class="max-w-md w-full bg-slate-900 border border-slate-800 rounded-2xl p-8 text-center shadow-2xl space-y-4">
        <div><i class="fa-solid fa-envelope-circle-check text-3xl text-slate-400"></i></div>
        <h1 class="text-xl font-bold text-white">Unsubscribed Successfully</h1>
        <p class="text-xs text-slate-300 leading-relaxed">{html.escape(message)}</p>
        <p class="text-[11px] text-slate-500">You will never receive marketing or digest emails again. Important transactional booking confirmations and invoices will still be delivered if you schedule an appointment.</p>
        <div class="pt-2">
            <a href="/" class="inline-block py-2 px-5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl text-xs transition">Return to Home</a>
        </div>
    </div>
    """
    return _base_page_layout("Unsubscribed", content)


# ----------------------------------------------------------------------
# 7. Privacy Policy Page (DPDP Act 2023)
# ----------------------------------------------------------------------
def render_privacy_page(user: Optional[Dict[str, Any]] = None) -> str:
    content = f"""
    <div class="max-w-3xl w-full bg-slate-900 border border-slate-800 rounded-2xl p-6 sm:p-10 shadow-2xl space-y-6 text-xs text-slate-300 leading-relaxed">
        <div class="border-b border-slate-800 pb-4">
            <div class="text-[11px] uppercase tracking-wider text-emerald-400 font-bold font-mono">Statutory Compliance Notice</div>
            <h1 class="text-2xl font-extrabold text-white mt-1">Data Privacy & Protection Policy</h1>
            <p class="text-slate-400 text-xs mt-1">Draft Document · Formatted for Compliance with Digital Personal Data Protection (DPDP) Act, 2023</p>
            <div class="inline-block bg-amber-950/80 border border-amber-700/80 text-amber-300 text-[10px] px-2.5 py-1 rounded-md font-mono mt-3">
                [LEGAL NOTICE]: This policy is a clinical operational draft and subject to formal review by our legal counsel.
            </div>
        </div>

        <section class="space-y-2">
            <h2 class="text-sm font-bold text-white">1. Principles of Discretion & Zero-Diagnosis Transmission</h2>
            <p>The Bengaluru Clinic provides outpatient mental health, relationship therapy, clinical psychology, and sexual health care. Because of the intimate nature of these consultations, all communication channels adhere strictly to a <strong>Zero-Diagnosis rule</strong>.</p>
            <p>Our automated systems (WhatsApp, SMS, and Email) never disclose diagnosis names, therapeutic specialties, or symptoms in subject lines, notification previews, or message headers.</p>
        </section>

        <section class="space-y-2">
            <h2 class="text-sm font-bold text-white">2. What Data We Collect & Why</h2>
            <ul class="list-disc pl-5 space-y-1">
                <li><strong>Identity & Contact:</strong> Patient name, phone number, and verified email address for appointment coordination, cryptographic invoice generation, and emergency clinical safety escalation.</li>
                <li><strong>Payment Identifiers:</strong> Razorpay / Cashfree payment and refund transaction identifiers. We do not store credit card numbers, CVVs, or UPI PINs.</li>
                <li><strong>Consent Records:</strong> Timestamp, consent wording, and cryptographic IP hash for double opt-in communication subscriptions.</li>
            </ul>
        </section>

        <section class="space-y-2">
            <h2 class="text-sm font-bold text-white">3. Marketing Separation & Double Opt-In</h2>
            <p>Transactional messages (payment confirmations, tax invoices, rescheduling notifications) are strictly separated from marketing or educational communications (weekly restorative digests). Marketing emails are delivered exclusively to patients who completed double opt-in verification and can be permanently revoked in a single click.</p>
        </section>

        <section class="space-y-2">
            <h2 class="text-sm font-bold text-white">4. Your Statutory Rights</h2>
            <p>Under the DPDP Act 2023, you have the right to summary, correction, and complete erasure of personal data. You can delete your account and associated subscriptions at any time via your <a href="/account" class="text-emerald-400 underline font-semibold">Account Portal</a>.</p>
        </section>

        <div class="pt-4 border-t border-slate-800 text-center">
            <a href="/" class="inline-block py-2 px-5 bg-emerald-600 hover:bg-emerald-500 text-white font-bold rounded-xl text-xs transition">Return to Clinic Home</a>
        </div>
    </div>
    """
    return _base_page_layout("Privacy Policy", content, user=user)


# ----------------------------------------------------------------------
# 8. Dev Mailbox Interface
# ----------------------------------------------------------------------
def render_dev_mailbox_page(emails: List[Dict[str, Any]], selected_id: Optional[int] = None) -> str:
    """Renders the comprehensive Dev Mailbox for viewing local simulated emails."""
    email_rows = []
    selected_email = None

    for e in emails:
        if selected_id and e["id"] == selected_id:
            selected_email = e
        elif not selected_id and not selected_email:
            selected_email = e

        status_class = {
            "SENT-IN-DEV": "bg-emerald-950/80 text-emerald-400 border border-emerald-700/80",
            "SENT": "bg-blue-950/80 text-blue-400 border border-blue-700/80",
            "QUEUED": "bg-amber-950/80 text-amber-400 border border-amber-700/80",
            "DEAD": "bg-rose-950/80 text-rose-400 border border-rose-700/80",
            "FAILED": "bg-rose-950/80 text-rose-400 border border-rose-700/80",
        }.get(e["status"], "bg-slate-800 text-slate-300")

        att_badge = '<i class="fa-solid fa-paperclip text-[10px] text-amber-400 ml-1" title="Has PDF Attachment"></i>' if e.get("has_attachment") else ''
        is_sel = selected_email and selected_email["id"] == e["id"]
        sel_class = "bg-slate-800/90 border-emerald-500/80" if is_sel else "bg-slate-900 hover:bg-slate-850 border-slate-800"

        email_rows.append(f"""
        <a href="/dev/mailbox?id={e['id']}" class="block p-3 rounded-xl border {sel_class} transition space-y-1">
            <div class="flex items-center justify-between text-[11px]">
                <span class="font-bold text-white truncate max-w-[160px]">{html.escape(e['to_email'])}</span>
                <span class="text-[10px] px-1.5 py-0.2 rounded font-mono font-bold {status_class}">{html.escape(e['status'])}</span>
            </div>
            <div class="text-xs text-slate-300 font-semibold truncate flex items-center justify-between">
                <span class="truncate">{html.escape(e['subject'])}</span>
                {att_badge}
            </div>
            <div class="text-[10px] text-slate-500 font-mono flex justify-between">
                <span>{html.escape(e['template'])}</span>
                <span>{html.escape(e['created_at'][11:19] if len(e['created_at']) >= 19 else e['created_at'])}</span>
            </div>
        </a>
        """)

    email_list_html = "\n".join(email_rows) if email_rows else '<div class="text-xs text-slate-500 italic p-4 text-center">No emails in queue yet. Trigger a booking or signup to generate test emails.</div>'

    # Preview section
    if selected_email:
        att_btn = ""
        if selected_email.get("has_attachment"):
            att_name = selected_email.get("attachment_name") or "invoice.pdf"
            att_btn = f"""
            <a href="/api/dev/emails/{selected_email['id']}/attachment" class="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-bold transition flex items-center gap-1.5 shadow-sm">
                <i class="fa-solid fa-download"></i>
                Download {html.escape(att_name)}
            </a>
            """

        preview_html = f"""
        <div class="flex-1 flex flex-col h-full bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-2xl">
            <!-- Email Meta Bar -->
            <div class="p-4 bg-slate-950 border-b border-slate-800 flex flex-wrap items-center justify-between gap-3">
                <div class="space-y-1">
                    <h2 class="text-sm font-extrabold text-white">{html.escape(selected_email['subject'])}</h2>
                    <div class="text-xs text-slate-400 font-mono flex items-center gap-3">
                        <span><strong>To:</strong> {html.escape(selected_email['to_email'])}</span>
                        <span><strong>Template:</strong> {html.escape(selected_email['template'])}</span>
                        <span><strong>Status:</strong> {html.escape(selected_email['status'])}</span>
                    </div>
                </div>
                <div class="flex items-center space-x-2">
                    {att_btn}
                </div>
            </div>

            <!-- Tabs: Rendered HTML vs Plain Text -->
            <div class="px-4 py-2 bg-slate-900 border-b border-slate-800 flex items-center justify-between text-xs">
                <div class="flex space-x-2">
                    <button onclick="showMailTab('html')" id="tabBtnHtml" class="px-3 py-1 rounded-md bg-emerald-600 text-white font-bold transition">Rendered HTML</button>
                    <button onclick="showMailTab('text')" id="tabBtnText" class="px-3 py-1 rounded-md bg-slate-800 text-slate-300 font-medium transition hover:text-white">Plain Text</button>
                </div>
                <span class="text-[11px] text-slate-500 font-mono">Queue ID: #{selected_email['id']}</span>
            </div>

            <!-- Tab Content -->
            <div class="flex-1 relative overflow-hidden bg-white">
                <iframe id="frameMailHtml" srcdoc="{html.escape(selected_email['html_body'])}" class="w-full h-full border-0"></iframe>
                <div id="paneMailText" class="hidden w-full h-full p-6 bg-slate-950 text-slate-200 font-mono text-xs overflow-auto whitespace-pre-wrap leading-relaxed select-text">
{html.escape(selected_email['text_body'])}
                </div>
            </div>
        </div>
        """
    else:
        preview_html = """
        <div class="flex-1 flex items-center justify-center bg-slate-900 border border-slate-800 rounded-2xl text-xs text-slate-500 italic p-8">
            Select an email from the left sidebar to preview its MIME rendering.
        </div>
        """

    content = f"""
    <div class="max-w-7xl w-full flex flex-col h-[85vh] space-y-3">
        <!-- Dev Banner -->
        <div class="bg-amber-950/80 border border-amber-600/80 rounded-xl px-4 py-2.5 flex items-center justify-between text-xs text-amber-200">
            <div class="flex items-center gap-2">
                <i class="fa-solid fa-triangle-exclamation text-amber-400"></i>
                <span><strong>DEV MAILBOX:</strong> Simulated inbox for development and testing. Outgoing emails are intercepted safely and not sent to real inboxes.</span>
            </div>
            <div class="flex items-center gap-2">
                <a href="/api/dev/emails" target="_blank" class="text-amber-400 hover:underline font-mono text-[11px]">JSON Feed</a>
            </div>
        </div>

        <!-- Split Mailbox Workspace -->
        <div class="flex-1 grid grid-cols-1 md:grid-cols-12 gap-4 overflow-hidden">
            <!-- Sidebar: Email List (4 cols) -->
            <div class="md:col-span-4 bg-slate-900 border border-slate-800 rounded-2xl flex flex-col overflow-hidden shadow-xl">
                <div class="p-3.5 bg-slate-950 border-b border-slate-800 flex items-center justify-between">
                    <span class="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-1.5">
                        <i class="fa-solid fa-inbox text-emerald-400"></i>
                        Queued & Sent ({len(emails)})
                    </span>
                    <a href="/dev/mailbox" class="text-[11px] text-emerald-400 hover:underline"><i class="fa-solid fa-rotate-right mr-1"></i>Refresh</a>
                </div>
                <div class="flex-1 overflow-y-auto p-2.5 space-y-2">
                    {email_list_html}
                </div>
            </div>

            <!-- Preview Pane (8 cols) -->
            <div class="md:col-span-8 flex flex-col h-full overflow-hidden">
                {preview_html}
            </div>
        </div>
    </div>

    <script>
        function showMailTab(tab) {{
            const frame = document.getElementById('frameMailHtml');
            const pane = document.getElementById('paneMailText');
            const btnH = document.getElementById('tabBtnHtml');
            const btnT = document.getElementById('tabBtnText');
            if (tab === 'html') {{
                frame.classList.remove('hidden');
                pane.classList.add('hidden');
                btnH.className = 'px-3 py-1 rounded-md bg-emerald-600 text-white font-bold transition';
                btnT.className = 'px-3 py-1 rounded-md bg-slate-800 text-slate-300 font-medium transition hover:text-white';
            }} else {{
                frame.classList.add('hidden');
                pane.classList.remove('hidden');
                btnT.className = 'px-3 py-1 rounded-md bg-emerald-600 text-white font-bold transition';
                btnH.className = 'px-3 py-1 rounded-md bg-slate-800 text-slate-300 font-medium transition hover:text-white';
            }}
        }}
    </script>
    """
    return _base_page_layout("Dev Mailbox", content)
