from __future__ import annotations
from . import db


def get_farmer_by_mobile(mobile_number: str) -> dict | None:
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM farmers WHERE mobile_number=?", (mobile_number,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_farmer_by_whatsapp(whatsapp_number: str) -> dict | None:
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM farmers WHERE whatsapp_number=?", (whatsapp_number,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_farmer_by_id(farmer_id: int) -> dict | None:
    conn = db.get_conn()
    try:
        row = conn.execute("SELECT * FROM farmers WHERE id=?", (farmer_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def link_whatsapp_number(farmer_id: int, whatsapp_number: str) -> None:
    conn = db.get_conn()
    try:
        conn.execute(
            "UPDATE farmers SET whatsapp_number=?, updated_at=? WHERE id=?",
            (whatsapp_number, db.now_iso(), farmer_id),
        )
        conn.commit()
    finally:
        conn.close()


def register_farmer(
    full_name: str,
    mobile_number: str,
    state: str = "",
    district: str = "",
    block: str = "",
    village: str = "",
) -> dict:
    """Used by the website registration API (registration.html). This is the
    single source of truth for farmer accounts that both the website and the
    WhatsApp bot check against."""
    conn = db.get_conn()
    try:
        existing = conn.execute(
            "SELECT 1 FROM farmers WHERE mobile_number=?", (mobile_number,)
        ).fetchone()
        if existing:
            raise ValueError("A farmer with this mobile number is already registered.")
        import random
        from datetime import date as _date

        farmer_code = f"BAARI-{_date.today().year}-{random.randint(100000, 999999)}"
        now = db.now_iso()
        conn.execute(
            """INSERT INTO farmers
               (farmer_id, full_name, mobile_number, state, district, block, village,
                registration_status, verification_status, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?, 'approved', 'verified', ?, ?)""",
            (farmer_code, full_name, mobile_number, state, district, block, village, now, now),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM farmers WHERE mobile_number=?", (mobile_number,)
        ).fetchone()
        db.log_event(conn, "farmer_registered", mobile_number, farmer_code)
        conn.commit()
        return dict(row)
    finally:
        conn.close()
