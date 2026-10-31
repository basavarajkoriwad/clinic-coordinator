"""
Configuration management for The Bengaluru Clinic Coordination & Email Engine.
Loads settings from .env file (using a tiny, zero-dependency parser) and environment variables.
"""

import os
from pathlib import Path
from typing import Any, Dict

BASE_DIR = Path(__file__).resolve().parent

def _load_env_file(filepath: Path) -> Dict[str, str]:
    """Tiny, robust .env parser without external dependencies."""
    env_vars: Dict[str, str] = {}
    if not filepath.exists() or not filepath.is_file():
        return env_vars
    
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip()
                # Strip matching surrounding quotes
                if len(val) >= 2 and ((val[0] == '"' and val[-1] == '"') or (val[0] == "'" and val[-1] == "'")):
                    val = val[1:-1]
                env_vars[key] = val
    return env_vars


# Read .env if present
_dot_env = _load_env_file(BASE_DIR / ".env")

def get_setting(key: str, default: Any = "") -> Any:
    """Gets setting from os.environ first, then .env file, then default."""
    if key in os.environ:
        return os.environ[key]
    if key in _dot_env:
        return _dot_env[key]
    return default

def get_bool(key: str, default: bool = False) -> bool:
    val = str(get_setting(key, str(default))).strip().lower()
    return val in ("1", "true", "yes", "on")

def get_int(key: str, default: int = 0) -> int:
    try:
        return int(get_setting(key, default))
    except (ValueError, TypeError):
        return default

def get_float(key: str, default: float = 0.0) -> float:
    try:
        return float(get_setting(key, default))
    except (ValueError, TypeError):
        return default


# Server & Security Settings
BASE_URL = get_setting("BASE_URL", "http://localhost:8000").rstrip("/")
SECRET_KEY = get_setting("SECRET_KEY", "bengaluru-clinic-secret-token-key-2026-secure-pbkdf2")

# Mail Transport Settings
MAIL_MODE = get_setting("MAIL_MODE", "dev").strip().lower()  # "dev" or "smtp"
SMTP_HOST = get_setting("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = get_int("SMTP_PORT", 587)
SMTP_USER = get_setting("SMTP_USER", "")
SMTP_PASSWORD = get_setting("SMTP_PASSWORD", "")
SMTP_USE_TLS = get_bool("SMTP_USE_TLS", True)
MAIL_FROM_NAME = get_setting("MAIL_FROM_NAME", "The Bengaluru Clinic")
MAIL_FROM_ADDRESS = get_setting("MAIL_FROM_ADDRESS", "appointments@bengaluru-clinic.in")
SMTP_TIMEOUT_SECONDS = get_int("SMTP_TIMEOUT_SECONDS", 15)

# Clinic Legal & Compliance Identity
CLINIC_LEGAL_NAME = get_setting("CLINIC_LEGAL_NAME", "The Bengaluru Clinic Healthcare Pvt. Ltd.")
CLINIC_ADDRESS = get_setting("CLINIC_ADDRESS", "Suite 302, 3rd Floor, Indiranagar 100ft Road, Bengaluru, Karnataka 560038")
CLINIC_GSTIN = get_setting("CLINIC_GSTIN", "")  # Optional GSTIN
CLINIC_PHONE = get_setting("CLINIC_PHONE", "+91 80 4000 0000")

# Tax & Invoicing Settings
TAX_RATE_PERCENT = get_float("TAX_RATE_PERCENT", 0.0)
TAX_NOTE = get_setting(
    "TAX_NOTE",
    "Healthcare services by clinical psychologists and medical practitioners are exempt under Notification No. 12/2017-Central Tax (Rate). Tax treatment subject to formal CA review."
)
SAC_CODE = get_setting("SAC_CODE", "999312")
INVOICE_PREFIX = get_setting("INVOICE_PREFIX", "TBC-INV-")

# Database & Storage
DATA_DIR = BASE_DIR / "data"
DATABASE_PATH = DATA_DIR / "clinic.db"
INVOICES_DIR = DATA_DIR / "invoices"
