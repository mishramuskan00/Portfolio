"""
BookingService: slot booking with real capacity enforcement, race-condition
safety, duplicate-booking protection, cancellation and rescheduling.

Concurrency approach (SQLite):
  Every booking-mutating operation runs inside a transaction opened with
  `BEGIN IMMEDIATE`, which takes SQLite's write lock immediately (not just at
  first write). Combined with a single atomic
      UPDATE procurement_slots SET booked_count = booked_count + 1
      WHERE id = ? AND booked_count < capacity AND is_open = 1
  the capacity check and the increment happen as one indivisible database
  operation. If two requests race for the last seat, only one UPDATE affects
  a row (rowcount == 1); the loser's UPDATE affects 0 rows and is told the
  slot is full/just taken. A process-local lock is layered on top so threads
  within this single process serialize cleanly too, and `PRAGMA busy_timeout`
  (see db.py) makes a second process/thread wait rather than error out.
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone

from . import db


class BookingError(Exception):
    pass


class SlotFull(BookingError):
    pass


class SlotUnavailable(BookingError):
    pass


class DuplicateBooking(BookingError):
    pass


class NotFound(BookingError):
    pass


def _generate_booking_id(conn, slot_date: str) -> str:
    ymd = slot_date.replace("-", "")
    for _ in range(20):
        row = conn.execute("SELECT COUNT(*) c FROM bookings").fetchone()
        seq = row["c"] + 1
        candidate = f"APB-{ymd}-{seq:06d}"
        exists = conn.execute(
            "SELECT 1 FROM bookings WHERE booking_id=?", (candidate,)
        ).fetchone()
        if not exists:
            return candidate
        # extremely unlikely fallback: append random suffix
        import secrets as _s
        candidate = f"APB-{ymd}-{seq:06d}{_s.token_hex(1)}"
        if not conn.execute(
            "SELECT 1 FROM bookings WHERE booking_id=?", (candidate,)
        ).fetchone():
            return candidate
    raise BookingError("Could not generate a unique booking ID")


def create_booking(farmer_id: int, slot_id: int, source: str = "whatsapp") -> dict:
    conn = db.get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            slot = conn.execute(
                "SELECT * FROM procurement_slots WHERE id=?", (slot_id,)
            ).fetchone()
            if slot is None or not slot["is_open"]:
                raise SlotUnavailable("This slot is no longer available.")

            slot_dt = datetime.strptime(slot["slot_date"], "%Y-%m-%d").date()
            if slot_dt < date.today():
                raise SlotUnavailable("Cannot book a slot in the past.")

            # Duplicate-booking protection: same farmer, same date+centre+crop,
            # already has an active (confirmed) booking.
            dup = conn.execute(
                """SELECT b.booking_id FROM bookings b
                   JOIN procurement_slots s ON s.id = b.slot_id
                   WHERE b.farmer_id=? AND b.status='confirmed'
                     AND s.slot_date=? AND s.centre_id=? AND s.crop=?""",
                (farmer_id, slot["slot_date"], slot["centre_id"], slot["crop"]),
            ).fetchone()
            if dup:
                raise DuplicateBooking(
                    f"You already have booking {dup['booking_id']} for this date."
                )

            # Atomic capacity check + reserve, in one statement.
            cur = conn.execute(
                """UPDATE procurement_slots
                   SET booked_count = booked_count + 1
                   WHERE id = ? AND is_open = 1 AND booked_count < capacity""",
                (slot_id,),
            )
            if cur.rowcount == 0:
                raise SlotFull(
                    "Sorry, this slot was just booked / is full. Please choose another slot."
                )

            queue_position = conn.execute(
                "SELECT booked_count FROM procurement_slots WHERE id=?", (slot_id,)
            ).fetchone()["booked_count"]

            booking_id = _generate_booking_id(conn, slot["slot_date"])
            now = db.now_iso()
            conn.execute(
                """INSERT INTO bookings
                   (booking_id, farmer_id, slot_id, queue_position, status, source, created_at, updated_at)
                   VALUES (?,?,?,?, 'confirmed', ?, ?, ?)""",
                (booking_id, farmer_id, slot_id, queue_position, source, now, now),
            )
            db.log_event(conn, "booking_created", str(farmer_id), booking_id)
            conn.commit()
        except BookingError:
            conn.rollback()
            raise
        return get_booking(booking_id)
    finally:
        conn.close()


def get_booking(booking_id: str) -> dict:
    conn = db.get_conn()
    try:
        row = conn.execute(
            """SELECT b.*, s.slot_date, s.start_time, s.end_time, s.crop,
                      c.name as centre_name, f.full_name, f.farmer_id as farmer_code
               FROM bookings b
               JOIN procurement_slots s ON s.id = b.slot_id
               JOIN procurement_centres c ON c.id = s.centre_id
               JOIN farmers f ON f.id = b.farmer_id
               WHERE b.booking_id=?""",
            (booking_id,),
        ).fetchone()
        if not row:
            raise NotFound("Booking not found")
        return dict(row)
    finally:
        conn.close()


def get_active_booking_for_farmer(farmer_id: int) -> dict | None:
    conn = db.get_conn()
    try:
        row = conn.execute(
            """SELECT b.booking_id FROM bookings b
               WHERE b.farmer_id=? AND b.status='confirmed'
               ORDER BY b.created_at DESC LIMIT 1""",
            (farmer_id,),
        ).fetchone()
        if not row:
            return None
        return get_booking(row["booking_id"])
    finally:
        conn.close()


def cancel_booking(booking_id: str, reason: str = "") -> dict:
    conn = db.get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            b = conn.execute(
                "SELECT * FROM bookings WHERE booking_id=?", (booking_id,)
            ).fetchone()
            if not b:
                raise NotFound("Booking not found")
            if b["status"] != "confirmed":
                raise BookingError(f"Booking is already {b['status']}.")
            now = db.now_iso()
            conn.execute(
                "UPDATE bookings SET status='cancelled', cancel_reason=?, updated_at=? WHERE id=?",
                (reason, now, b["id"]),
            )
            conn.execute(
                "UPDATE procurement_slots SET booked_count = MAX(0, booked_count - 1) WHERE id=?",
                (b["slot_id"],),
            )
            db.log_event(conn, "booking_cancelled", str(b["farmer_id"]), booking_id)
            conn.commit()
        except BookingError:
            conn.rollback()
            raise
        return get_booking(booking_id)
    finally:
        conn.close()


def reschedule_booking(booking_id: str, new_slot_id: int) -> dict:
    """Atomically release the old slot and reserve the new one. If the new
    slot is full, the original booking is left completely untouched."""
    conn = db.get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            b = conn.execute(
                "SELECT * FROM bookings WHERE booking_id=?", (booking_id,)
            ).fetchone()
            if not b:
                raise NotFound("Booking not found")
            if b["status"] != "confirmed":
                raise BookingError(f"Booking is already {b['status']}.")

            new_slot = conn.execute(
                "SELECT * FROM procurement_slots WHERE id=?", (new_slot_id,)
            ).fetchone()
            if not new_slot or not new_slot["is_open"]:
                raise SlotUnavailable("Selected slot is not available.")

            cur = conn.execute(
                """UPDATE procurement_slots
                   SET booked_count = booked_count + 1
                   WHERE id = ? AND is_open = 1 AND booked_count < capacity""",
                (new_slot_id,),
            )
            if cur.rowcount == 0:
                # Original booking untouched -- rollback whole transaction.
                raise SlotFull("That slot is full. Please pick another.")

            conn.execute(
                "UPDATE procurement_slots SET booked_count = MAX(0, booked_count - 1) WHERE id=?",
                (b["slot_id"],),
            )
            queue_position = conn.execute(
                "SELECT booked_count FROM procurement_slots WHERE id=?", (new_slot_id,)
            ).fetchone()["booked_count"]
            now = db.now_iso()
            conn.execute(
                """UPDATE bookings SET slot_id=?, queue_position=?, status='confirmed', updated_at=?
                   WHERE id=?""",
                (new_slot_id, queue_position, now, b["id"]),
            )
            db.log_event(conn, "booking_rescheduled", str(b["farmer_id"]), booking_id)
            conn.commit()
        except BookingError:
            conn.rollback()
            raise
        return get_booking(booking_id)
    finally:
        conn.close()


def list_available_slots(centre_id: int, crop: str | None = None) -> list[dict]:
    conn = db.get_conn()
    try:
        q = """SELECT * FROM procurement_slots
               WHERE centre_id=? AND is_open=1 AND slot_date >= date('now')
                     AND booked_count < capacity"""
        params = [centre_id]
        if crop:
            q += " AND crop=?"
            params.append(crop)
        q += " ORDER BY slot_date, start_time"
        rows = conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
