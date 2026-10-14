"""
Database layer for the Apni BAARI WhatsApp booking system.

Extends the EXISTING apni_baari.db SQLite database (the same file app.py
already uses for the `tokens` table) with new tables:

    farmers, procurement_centres, procurement_slots, bookings,
    otp_verifications, whatsapp_sessions, audit_log

No existing table is touched or dropped. This module is safe to import
alongside the existing app.py without breaking anything already there.
"""
from __future__ import annotations
import sqlite3
import threading
from pathlib import Path
from datetime import datetime, timezone

BASE = Path(__file__).resolve().parent.parent
# Same database file the main app.py already uses (for the `tokens` table).
# Can be overridden with DATABASE_PATH so the WhatsApp bot process and the
# website process can be run separately while still sharing one source of
# truth (e.g. both pointed at a shared volume in production).
import os as _os
DB_PATH = Path(_os.environ.get("DATABASE_PATH", str(BASE / "apni_baari.db")))

# One lock per process to serialize the "check capacity then insert" critical
# section for SQLite (which does not support SELECT ... FOR UPDATE). This is
# combined with a transaction using BEGIN IMMEDIATE, which takes a database
# level write-lock, so it is also correct across multiple processes/workers,
# not just threads within one process.
_write_lock = threading.Lock()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # busy_timeout lets a second connection wait for a lock instead of
    # immediately raising "database is locked" during a concurrent booking.
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS farmers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    farmer_id TEXT UNIQUE NOT NULL,
    full_name TEXT NOT NULL,
    mobile_number TEXT UNIQUE NOT NULL,
    whatsapp_number TEXT,
    state TEXT,
    district TEXT,
    block TEXT,
    village TEXT,
    procurement_center_id INTEGER,
    registration_status TEXT DEFAULT 'pending',
    verification_status TEXT DEFAULT 'unverified',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (procurement_center_id) REFERENCES procurement_centres(id)
);
CREATE INDEX IF NOT EXISTS idx_farmers_mobile ON farmers(mobile_number);
CREATE INDEX IF NOT EXISTS idx_farmers_whatsapp ON farmers(whatsapp_number);

CREATE TABLE IF NOT EXISTS procurement_centres (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    state TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS procurement_slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    centre_id INTEGER NOT NULL,
    crop TEXT NOT NULL,
    slot_date TEXT NOT NULL,           -- YYYY-MM-DD
    start_time TEXT NOT NULL,          -- HH:MM
    end_time TEXT NOT NULL,            -- HH:MM
    capacity INTEGER NOT NULL,
    booked_count INTEGER NOT NULL DEFAULT 0,
    is_open INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    FOREIGN KEY (centre_id) REFERENCES procurement_centres(id),
    UNIQUE(centre_id, crop, slot_date, start_time)
);
CREATE INDEX IF NOT EXISTS idx_slots_date ON procurement_slots(slot_date);
CREATE INDEX IF NOT EXISTS idx_slots_centre ON procurement_slots(centre_id);

CREATE TABLE IF NOT EXISTS bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_id TEXT UNIQUE NOT NULL,       -- e.g. APB-20260910-000123
    farmer_id INTEGER NOT NULL,
    slot_id INTEGER NOT NULL,
    queue_position INTEGER,
    status TEXT NOT NULL DEFAULT 'confirmed',   -- confirmed|cancelled|rescheduled|completed
    source TEXT NOT NULL DEFAULT 'whatsapp',    -- whatsapp|website
    cancel_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (farmer_id) REFERENCES farmers(id),
    FOREIGN KEY (slot_id) REFERENCES procurement_slots(id)
);
CREATE INDEX IF NOT EXISTS idx_bookings_booking_id ON bookings(booking_id);
CREATE INDEX IF NOT EXISTS idx_bookings_farmer ON bookings(farmer_id);
CREATE INDEX IF NOT EXISTS idx_bookings_slot ON bookings(slot_id);
CREATE INDEX IF NOT EXISTS idx_bookings_status ON bookings(status);

CREATE TABLE IF NOT EXISTS otp_verifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mobile_number TEXT NOT NULL,
    otp_hash TEXT NOT NULL,
    purpose TEXT NOT NULL DEFAULT 'login',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    consumed INTEGER NOT NULL DEFAULT 0,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_otp_mobile ON otp_verifications(mobile_number);

CREATE TABLE IF NOT EXISTS otp_rate_limit (
    mobile_number TEXT PRIMARY KEY,
    window_start TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS whatsapp_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    whatsapp_number TEXT UNIQUE NOT NULL,
    farmer_id INTEGER,
    state TEXT NOT NULL DEFAULT 'IDLE',
    context TEXT NOT NULL DEFAULT '{}',   -- JSON blob: centre/crop/date/slot selections in progress
    authenticated INTEGER NOT NULL DEFAULT 0,
    session_expires_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (farmer_id) REFERENCES farmers(id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    actor TEXT,               -- whatsapp number, farmer_id, 'system', etc.
    detail TEXT,               -- free-text / JSON, NEVER an OTP value
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS whatsapp_webhook_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT UNIQUE,
    received_at TEXT NOT NULL
);
"""


def init_db() -> None:
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def log_event(conn: sqlite3.Connection, event_type: str, actor: str | None, detail: str = "") -> None:
    conn.execute(
        "INSERT INTO audit_log(event_type, actor, detail, created_at) VALUES (?,?,?,?)",
        (event_type, actor, detail, now_iso()),
    )


init_db()
