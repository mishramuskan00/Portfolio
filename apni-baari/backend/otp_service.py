"""
OTPService: real OTP generation / hashed storage / expiry / rate limiting,
with a pluggable SMS provider so a real provider (Twilio, MSG91, etc.) can be
dropped in later purely via environment variables -- no code changes needed
in the booking/webhook logic.

Pure stdlib (hashlib, secrets, sqlite3) -- no FastAPI/pydantic dependency,
so this module can be exercised directly (see backend/tests/).
"""
from __future__ import annotations
import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from . import db

OTP_MODE = os.environ.get("OTP_MODE", "development")  # development | production
OTP_EXPIRY_MINUTES = int(os.environ.get("OTP_EXPIRY_MINUTES", "5"))
OTP_MAX_ATTEMPTS = int(os.environ.get("OTP_MAX_ATTEMPTS", "5"))
OTP_RATE_LIMIT_PER_HOUR = int(os.environ.get("OTP_RATE_LIMIT", "5"))
OTP_HASH_SALT = os.environ.get("OTP_HASH_SALT", "apni-baari-dev-salt-change-in-prod")


class OTPError(Exception):
    """Base class for OTP-flow errors the caller should turn into a farmer-facing message."""


class RateLimited(OTPError):
    pass


class InvalidOTP(OTPError):
    pass


class ExpiredOTP(OTPError):
    pass


class TooManyAttempts(OTPError):
    pass


@dataclass
class SMSResult:
    ok: bool
    provider: str
    detail: str = ""


class SMSProvider:
    """Abstract SMS provider. Swap the implementation used by OTPService via env vars."""

    name = "abstract"

    def send(self, mobile_number: str, message: str) -> SMSResult:
        raise NotImplementedError


class ConsoleDevProvider(SMSProvider):
    """
    Development-only provider: prints the OTP to the server console instead of
    sending a real SMS. Only ever used when OTP_MODE=development. Must NEVER
    be selected when OTP_MODE=production (see get_sms_provider below).

    _last_sent is an in-process, never-persisted-to-disk mirror of exactly
    what was printed to the console, purely so local dev tooling (the
    browser-based bot simulator, and these tests) can display/assert on the
    OTP without a human re-typing it from server logs. This never runs
    outside OTP_MODE=development and is never written to the database (the
    database only ever stores the salted hash -- see _hash_otp below).
    """

    name = "console-dev"
    _last_sent: dict[str, str] = {}

    def send(self, mobile_number: str, message: str) -> SMSResult:
        print(f"[DEV OTP] To {mobile_number}: {message}")
        # Pull the 6-digit code back out of the message we just built, purely
        # for the in-memory dev mirror described above.
        import re

        m = re.search(r"\b(\d{6})\b", message)
        if m:
            ConsoleDevProvider._last_sent[mobile_number] = m.group(1)
        return SMSResult(ok=True, provider=self.name, detail="printed to console")


class UnconfiguredProductionProvider(SMSProvider):
    """
    Placeholder that makes it impossible to silently "fake" OTP delivery in
    production. Wire in a real provider (Twilio/MSG91/etc.) by implementing
    SMSProvider.send() using that provider's SDK/HTTP API and returning it
    from get_sms_provider() when OTP_MODE=production and the provider name
    env var is set.
    """

    name = "unconfigured"

    def send(self, mobile_number: str, message: str) -> SMSResult:
        raise OTPError(
            "OTP_MODE=production but no real SMS provider is configured. "
            "Set SMS_PROVIDER and its credentials (see .env.example), and "
            "implement/select a concrete SMSProvider in otp_service.py."
        )


def get_sms_provider() -> SMSProvider:
    if OTP_MODE == "production":
        # Extend this branch with real providers, e.g.:
        # if os.environ.get("SMS_PROVIDER") == "twilio": return TwilioProvider(...)
        # if os.environ.get("SMS_PROVIDER") == "msg91": return MSG91Provider(...)
        return UnconfiguredProductionProvider()
    return ConsoleDevProvider()


def debug_peek_last_otp(mobile_number: str) -> str | None:
    """DEV/TEST ONLY. Returns the last OTP the console-dev provider "sent" to
    this number, from the in-memory mirror -- never from the database (which
    only ever holds a salted hash). Raises if called while OTP_MODE=production
    so this can never accidentally leak a real OTP in a live deployment."""
    if OTP_MODE == "production":
        raise OTPError("debug_peek_last_otp is disabled when OTP_MODE=production")
    return ConsoleDevProvider._last_sent.get(mobile_number)


def _hash_otp(otp: str, mobile_number: str) -> str:
    return hmac.new(
        OTP_HASH_SALT.encode(), f"{mobile_number}:{otp}".encode(), hashlib.sha256
    ).hexdigest()


def _generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _check_rate_limit(conn, mobile_number: str) -> None:
    now = datetime.now(timezone.utc)
    row = conn.execute(
        "SELECT * FROM otp_rate_limit WHERE mobile_number=?", (mobile_number,)
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO otp_rate_limit(mobile_number, window_start, count) VALUES (?,?,1)",
            (mobile_number, now.isoformat()),
        )
        return
    window_start = datetime.fromisoformat(row["window_start"])
    if now - window_start > timedelta(hours=1):
        conn.execute(
            "UPDATE otp_rate_limit SET window_start=?, count=1 WHERE mobile_number=?",
            (now.isoformat(), mobile_number),
        )
        return
    if row["count"] >= OTP_RATE_LIMIT_PER_HOUR:
        raise RateLimited(
            f"Too many OTP requests. Please try again later "
            f"(limit {OTP_RATE_LIMIT_PER_HOUR}/hour)."
        )
    conn.execute(
        "UPDATE otp_rate_limit SET count=count+1 WHERE mobile_number=?",
        (mobile_number,),
    )


def request_otp(mobile_number: str, purpose: str = "login") -> SMSResult:
    """Generate an OTP, store its hash, and send it via the configured provider.

    NOTE: uses explicit commit/rollback (not `with conn:`) because a
    RateLimited error must still persist the rate-limit counter it just
    incremented -- `with conn:` would roll that back on the raise.
    """
    conn = db.get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            _check_rate_limit(conn, mobile_number)
        except RateLimited:
            conn.commit()  # keep the counter increment even though we're erroring out
            raise
        # Invalidate any prior un-consumed OTPs for this number+purpose so
        # only the most recent one is ever valid (prevents stale-OTP reuse).
        conn.execute(
            "UPDATE otp_verifications SET consumed=1 WHERE mobile_number=? AND purpose=? AND consumed=0",
            (mobile_number, purpose),
        )
        otp = _generate_otp()
        otp_hash = _hash_otp(otp, mobile_number)
        expires_at = (
            datetime.now(timezone.utc) + timedelta(minutes=OTP_EXPIRY_MINUTES)
        ).isoformat()
        conn.execute(
            """INSERT INTO otp_verifications
               (mobile_number, otp_hash, purpose, attempts, max_attempts, consumed, expires_at, created_at)
               VALUES (?,?,?,0,?,0,?,?)""",
            (mobile_number, otp_hash, purpose, OTP_MAX_ATTEMPTS, expires_at, db.now_iso()),
        )
        db.log_event(conn, "otp_requested", mobile_number, purpose)
        conn.commit()
        provider = get_sms_provider()
        message = f"Your Apni BAARI OTP is {otp}. Valid for {OTP_EXPIRY_MINUTES} minutes. Do not share it."
        return provider.send(mobile_number, message)
    finally:
        conn.close()


def verify_otp(mobile_number: str, otp: str, purpose: str = "login") -> bool:
    """Verify OTP; raises InvalidOTP / ExpiredOTP / TooManyAttempts on failure.

    NOTE: uses explicit commit before every raise, deliberately not `with
    conn:`, because each failure path (wrong OTP, expired, max attempts)
    must persist the state change it just made (attempt count, consumed
    flag) even though the function is about to raise.
    """
    conn = db.get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """SELECT * FROM otp_verifications
               WHERE mobile_number=? AND purpose=? AND consumed=0
               ORDER BY id DESC LIMIT 1""",
            (mobile_number, purpose),
        ).fetchone()
        if row is None:
            conn.commit()
            raise InvalidOTP("No active OTP found. Please request a new one.")

        if row["attempts"] >= row["max_attempts"]:
            conn.execute(
                "UPDATE otp_verifications SET consumed=1 WHERE id=?", (row["id"],)
            )
            db.log_event(conn, "otp_max_attempts", mobile_number, purpose)
            conn.commit()
            raise TooManyAttempts("Maximum attempts exceeded. Please request a new OTP.")

        expires_at = datetime.fromisoformat(row["expires_at"])
        if datetime.now(timezone.utc) > expires_at:
            conn.execute(
                "UPDATE otp_verifications SET consumed=1 WHERE id=?", (row["id"],)
            )
            db.log_event(conn, "otp_expired", mobile_number, purpose)
            conn.commit()
            raise ExpiredOTP("OTP has expired. Please request a new one.")

        candidate_hash = _hash_otp(otp, mobile_number)
        if not hmac.compare_digest(candidate_hash, row["otp_hash"]):
            remaining = row["max_attempts"] - (row["attempts"] + 1)
            conn.execute(
                "UPDATE otp_verifications SET attempts=attempts+1 WHERE id=?",
                (row["id"],),
            )
            db.log_event(conn, "otp_failed_attempt", mobile_number, purpose)
            conn.commit()
            raise InvalidOTP(f"Incorrect OTP. {max(remaining, 0)} attempt(s) remaining.")

        conn.execute(
            "UPDATE otp_verifications SET consumed=1 WHERE id=?", (row["id"],)
        )
        db.log_event(conn, "otp_verified", mobile_number, purpose)
        conn.commit()
        return True
    finally:
        conn.close()
