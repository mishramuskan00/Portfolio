"""
REST API surface used by:
  - registration.html (POST /api/farmers/register)
  - the government/officer dashboard pages (GET /api/officer/bookings, etc.)
  - anything else that wants slot/booking data without going through WhatsApp

Deliberately namespaced under /api and added via app.include_router() in
app.py -- it does not touch or rename any of the existing /api/* routes
already defined directly on `app` in app.py (tokens, mandis, msp, queue...).
"""
from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import db, otp_service, booking_service, farmer_service
from .seed import CROPS

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------- Farmers --
class FarmerRegisterIn(BaseModel):
    full_name: str
    mobile_number: str
    state: str = ""
    district: str = ""
    block: str = ""
    village: str = ""


@router.post("/farmers/register")
def register_farmer(x: FarmerRegisterIn):
    mobile = "".join(ch for ch in x.mobile_number if ch.isdigit())[-10:]
    if len(mobile) != 10:
        raise HTTPException(400, "Enter a valid 10-digit mobile number.")
    try:
        farmer = farmer_service.register_farmer(
            x.full_name.strip(), mobile, x.state, x.district, x.block, x.village
        )
    except ValueError as e:
        raise HTTPException(409, str(e))
    return farmer


@router.get("/farmers/{farmer_id}")
def get_farmer(farmer_id: int):
    farmer = farmer_service.get_farmer_by_id(farmer_id)
    if not farmer:
        raise HTTPException(404, "Farmer not found")
    return farmer


@router.get("/farmers/{farmer_id}/bookings")
def get_farmer_bookings(farmer_id: int):
    conn = db.get_conn()
    try:
        rows = conn.execute(
            """SELECT b.booking_id, b.status, b.source, b.queue_position,
                      s.slot_date, s.start_time, s.end_time, s.crop, c.name as centre_name
               FROM bookings b
               JOIN procurement_slots s ON s.id=b.slot_id
               JOIN procurement_centres c ON c.id=s.centre_id
               WHERE b.farmer_id=? ORDER BY b.created_at DESC""",
            (farmer_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# -------------------------------------------------------------------- OTP --
class OTPRequestIn(BaseModel):
    mobile_number: str


class OTPVerifyIn(BaseModel):
    mobile_number: str
    otp: str


@router.post("/auth/otp/request")
def request_otp(x: OTPRequestIn):
    farmer = farmer_service.get_farmer_by_mobile(x.mobile_number)
    if not farmer:
        raise HTTPException(404, "No farmer registered with this mobile number.")
    try:
        result = otp_service.request_otp(x.mobile_number)
    except otp_service.RateLimited as e:
        raise HTTPException(429, str(e))
    return {"ok": result.ok, "provider": result.provider}


@router.post("/auth/otp/verify")
def verify_otp(x: OTPVerifyIn):
    try:
        otp_service.verify_otp(x.mobile_number, x.otp)
    except otp_service.ExpiredOTP as e:
        raise HTTPException(410, str(e))
    except otp_service.TooManyAttempts as e:
        raise HTTPException(429, str(e))
    except otp_service.InvalidOTP as e:
        raise HTTPException(400, str(e))
    return {"verified": True}


# --------------------------------------------------------- Centres/slots --
@router.get("/centres")
def list_centres():
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT id, name, state FROM procurement_centres WHERE is_active=1 ORDER BY name"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/crops")
def list_crops():
    return CROPS


@router.get("/centres/{centre_id}/slots")
def centre_slots(centre_id: int, crop: str | None = None):
    return booking_service.list_available_slots(centre_id, crop)


@router.get("/slots/available")
def slots_available(crop: str | None = None):
    conn = db.get_conn()
    try:
        q = """SELECT s.*, c.name as centre_name FROM procurement_slots s
               JOIN procurement_centres c ON c.id = s.centre_id
               WHERE s.is_open=1 AND s.slot_date >= date('now') AND s.booked_count < s.capacity"""
        params = []
        if crop:
            q += " AND s.crop=?"
            params.append(crop)
        q += " ORDER BY s.slot_date, s.start_time"
        rows = conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ------------------------------------------------------------- Bookings --
class BookingCreateIn(BaseModel):
    farmer_id: int
    slot_id: int
    source: str = "website"


@router.post("/bookings")
def create_booking(x: BookingCreateIn):
    try:
        return booking_service.create_booking(x.farmer_id, x.slot_id, x.source)
    except booking_service.SlotFull as e:
        raise HTTPException(409, str(e))
    except booking_service.DuplicateBooking as e:
        raise HTTPException(409, str(e))
    except booking_service.SlotUnavailable as e:
        raise HTTPException(400, str(e))


@router.get("/bookings/{booking_id}")
def get_booking(booking_id: str):
    try:
        return booking_service.get_booking(booking_id)
    except booking_service.NotFound:
        raise HTTPException(404, "Booking not found")


class CancelIn(BaseModel):
    reason: str = ""


@router.post("/bookings/{booking_id}/cancel")
def cancel_booking(booking_id: str, x: CancelIn = CancelIn()):
    try:
        return booking_service.cancel_booking(booking_id, x.reason)
    except booking_service.NotFound:
        raise HTTPException(404, "Booking not found")
    except booking_service.BookingError as e:
        raise HTTPException(409, str(e))


class RescheduleIn(BaseModel):
    new_slot_id: int


@router.post("/bookings/{booking_id}/reschedule")
def reschedule_booking(booking_id: str, x: RescheduleIn):
    try:
        return booking_service.reschedule_booking(booking_id, x.new_slot_id)
    except booking_service.NotFound:
        raise HTTPException(404, "Booking not found")
    except booking_service.SlotFull as e:
        raise HTTPException(409, str(e))
    except booking_service.BookingError as e:
        raise HTTPException(400, str(e))


# --------------------------------------------------------- Officer view --
@router.get("/officer/bookings")
def officer_bookings(centre_id: int | None = None, status: str | None = None):
    """Powers the government/officer dashboard. Every booking made through
    WhatsApp OR the website lands in the same `bookings` table, so this one
    query is the single source of truth both channels read from."""
    conn = db.get_conn()
    try:
        q = """SELECT b.booking_id, b.status, b.source, b.queue_position, b.created_at,
                      f.full_name, f.farmer_id as farmer_code, f.mobile_number,
                      s.slot_date, s.start_time, s.end_time, s.crop,
                      c.id as centre_id, c.name as centre_name
               FROM bookings b
               JOIN farmers f ON f.id = b.farmer_id
               JOIN procurement_slots s ON s.id = b.slot_id
               JOIN procurement_centres c ON c.id = s.centre_id
               WHERE 1=1"""
        params: list = []
        if centre_id:
            q += " AND c.id=?"
            params.append(centre_id)
        if status:
            q += " AND b.status=?"
            params.append(status)
        q += " ORDER BY b.created_at DESC LIMIT 200"
        rows = conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
