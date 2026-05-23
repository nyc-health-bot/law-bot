"""
Test that the Gmail SMTP credentials in .env can actually send an email.

Run manually when credentials change:
    python -m pytest test/test_email.py -v -s

Skipped automatically if GMAIL_USER or GMAIL_APP_PASSWORD are not set.
Sends a real email to GMAIL_USER itself (a self-addressed test message).
"""
import os
import smtplib
import ssl
import sys
import unittest
from pathlib import Path

# Load .env whether run directly or via pytest from repo root
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#"):
            continue
        if "=" in _line:
            _k, _, _v = _line.partition("=")
        elif ": " in _line:
            _k, _, _v = _line.partition(": ")
        else:
            continue
        os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))


GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")


@unittest.skipUnless(GMAIL_USER and GMAIL_APP_PASSWORD, "GMAIL_USER / GMAIL_APP_PASSWORD not set")
class TestEmailCredentials(unittest.TestCase):

    def test_smtp_login(self):
        """Gmail app password is valid — SMTP login succeeds without sending."""
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
            # login() raises smtplib.SMTPAuthenticationError on bad credentials
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)

    def test_send_self_test_email(self):
        """Send a test email to GMAIL_USER itself to confirm end-to-end delivery."""
        import email.mime.text as _mime
        msg = _mime.MIMEText("This is an automated credential check from the law-bot test suite.")
        msg["Subject"] = "[law-bot] Email credential test"
        msg["From"] = GMAIL_USER
        msg["To"] = GMAIL_USER

        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, [GMAIL_USER], msg.as_string())


if __name__ == "__main__":
    unittest.main(verbosity=2)
