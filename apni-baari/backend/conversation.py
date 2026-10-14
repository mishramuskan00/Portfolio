"""
Conversation manager: owns the WhatsApp bot's state machine.

Session state is persisted in the `whatsapp_sessions` table (not just an
in-memory dict), so a server restart does not lose anyone's place mid-flow.

handle_incoming() is the single entry point the webhook calls with the raw
text/interactive-id a farmer sent, and returns a list of outbound message
"commands" (dicts) that the webhook layer turns into real WhatsApp API calls
via WhatsAppService. Keeping this function free of any direct WhatsApp API
calls makes it independently testable (see backend/tests/).
"""
from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone

from . import db, otp_service, booking_service, farmer_service
from .messages import t

SESSION_TTL_MINUTES = 15

STATE_IDLE = "IDLE"
STATE_AWAITING_MOBILE = "AWAITING_MOBILE"
STATE_AWAITING_OTP = "AWAITING_OTP"
STATE_MAIN_MENU = "MAIN_MENU"
STATE_SELECTING_CENTRE = "SELECTING_CENTRE"
STATE_SELECTING_CROP = "SELECTING_CROP"
STATE_SELECTING_DATE = "SELECTING_DATE"
STATE_SELECTING_SLOT = "SELECTING_SLOT"
STATE_AWAITING_BOOKING_CONFIRMATION = "AWAITING_BOOKING_CONFIRMATION"
STATE_AWAITING_CANCEL_CONFIRMATION = "AWAITING_CANCEL_CONFIRMATION"
STATE_RESCHEDULE_SELECTING_DATE = "RESCHEDULE_SELECTING_DATE"
STATE_RESCHEDULE_SELECTING_SLOT = "RESCHEDULE_SELECTING_SLOT"


def _get_session(whatsapp_number: str) -> dict:
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM whatsapp_sessions WHERE whatsapp_number=?", (whatsapp_number,)
        ).fetchone()
        if row is None:
            now = db.now_iso()
            conn.execute(
                """INSERT INTO whatsapp_sessions
                   (whatsapp_number, farmer_id, state, context, authenticated, created_at, updated_at)
                   VALUES (?,NULL,?,?,0,?,?)""",
                (whatsapp_number, STATE_IDLE, "{}", now, now),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM whatsapp_sessions WHERE whatsapp_number=?", (whatsapp_number,)
            ).fetchone()
        session = dict(row)
        session["context"] = json.loads(session["context"] or "{}")
        return session
    finally:
        conn.close()


def _save_session(whatsapp_number: str, state: str, context: dict, authenticated: bool, farmer_id: int | None) -> None:
    conn = db.get_conn()
    try:
        expires = (datetime.now(timezone.utc) + timedelta(minutes=SESSION_TTL_MINUTES)).isoformat()
        conn.execute(
            """UPDATE whatsapp_sessions
               SET state=?, context=?, authenticated=?, farmer_id=?, session_expires_at=?, updated_at=?
               WHERE whatsapp_number=?""",
            (state, json.dumps(context), int(authenticated), farmer_id, expires, db.now_iso(), whatsapp_number),
        )
        conn.commit()
    finally:
        conn.close()


def _reset_session(whatsapp_number: str) -> None:
    _save_session(whatsapp_number, STATE_IDLE, {}, False, None)


def _session_expired(session: dict) -> bool:
    if not session["authenticated"] or not session["session_expires_at"]:
        return False
    return datetime.now(timezone.utc) > datetime.fromisoformat(session["session_expires_at"])


def _lang(session: dict) -> str:
    return session["context"].get("lang", "en")


def _main_menu_buttons():
    return [("book", "Book Slot"), ("mybooking", "My Booking"), ("slots", "Check Slots")]


def _fmt_slot(slot: dict) -> str:
    return f"{slot['start_time']}\u2013{slot['end_time']}"


class Reply:
    """Outbound message instruction the webhook layer executes via WhatsAppService."""

    def __init__(self, kind: str, text: str = "", buttons=None, rows=None, button_text: str = "Choose"):
        self.kind = kind  # 'text' | 'buttons' | 'list'
        self.text = text
        self.buttons = buttons or []
        self.rows = rows or []
        self.button_text = button_text

    @staticmethod
    def text_msg(text: str) -> "Reply":
        return Reply("text", text=text)

    @staticmethod
    def buttons_msg(text: str, buttons) -> "Reply":
        return Reply("buttons", text=text, buttons=buttons)

    @staticmethod
    def list_msg(text: str, rows, button_text="Choose") -> "Reply":
        return Reply("list", text=text, rows=rows, button_text=button_text)


def _main_menu_reply(session) -> list[Reply]:
    lang = _lang(session)
    farmer = farmer_service.get_farmer_by_id(session["farmer_id"]) if session["farmer_id"] else None
    greeting = (
        t("greeting_authenticated", lang, name=farmer["full_name"])
        if farmer
        else t("welcome", lang)
    )
    return [Reply.buttons_msg(greeting, _main_menu_buttons())]


def _centres_list(session) -> list[Reply]:
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT id, name FROM procurement_centres WHERE is_active=1 ORDER BY name"
        ).fetchall()
    finally:
        conn.close()
    lang = _lang(session)
    return [Reply.list_msg(t("select_centre", lang), [(str(r["id"]), r["name"]) for r in rows])]


def _crops_list(session) -> list[Reply]:
    from .seed import CROPS

    lang = _lang(session)
    return [Reply.list_msg(t("select_crop", lang), [(c, c) for c in CROPS])]


def _dates_list(session, centre_id: int, crop: str) -> list[Reply]:
    conn = db.get_conn()
    try:
        rows = conn.execute(
            """SELECT DISTINCT slot_date FROM procurement_slots
               WHERE centre_id=? AND crop=? AND is_open=1 AND booked_count < capacity
                     AND slot_date >= date('now')
               ORDER BY slot_date LIMIT 10""",
            (centre_id, crop),
        ).fetchall()
    finally:
        conn.close()
    lang = _lang(session)
    if not rows:
        return [Reply.text_msg(t("no_slots", lang, date="any upcoming date"))]
    return [Reply.list_msg(t("select_date", lang), [(r["slot_date"], r["slot_date"]) for r in rows])]


def _slots_list(session, centre_id: int, crop: str, slot_date: str) -> list[Reply]:
    slots = [
        s
        for s in booking_service.list_available_slots(centre_id, crop)
        if s["slot_date"] == slot_date
    ]
    lang = _lang(session)
    if not slots:
        return [Reply.text_msg(t("no_slots", lang, date=slot_date))]
    rows = [(str(s["id"]), _fmt_slot(s)) for s in slots]
    body = t("select_slot", lang, date=slot_date, slots="")
    return [Reply.list_msg(body, rows)]


def handle_incoming(whatsapp_number: str, raw_text: str, interactive_id: str | None = None) -> list[Reply]:
    text = (raw_text or "").strip()
    selection = interactive_id or text
    lower = text.lower()

    session = _get_session(whatsapp_number)

    if _session_expired(session):
        _reset_session(whatsapp_number)
        session = _get_session(whatsapp_number)
        return [Reply.text_msg(t("session_expired", _lang(session)))] 

    state = session["state"]
    ctx = session["context"]
    lang = _lang(session)

    # Global commands available from (almost) any state.
    if lower in ("hi", "hello", "menu", "start"):
        if session["authenticated"] and session["farmer_id"]:
            _save_session(whatsapp_number, STATE_MAIN_MENU, ctx, True, session["farmer_id"])
            return _main_menu_reply(_get_session(whatsapp_number))
        farmer = farmer_service.get_farmer_by_whatsapp(whatsapp_number)
        if farmer:
            _save_session(whatsapp_number, STATE_AWAITING_OTP, {"mobile": farmer["mobile_number"], "farmer_id": farmer["id"]}, False, None)
            otp_service.request_otp(farmer["mobile_number"])
            return [Reply.text_msg(t("otp_sent", lang))]
        _save_session(whatsapp_number, STATE_AWAITING_MOBILE, {}, False, None)
        return [Reply.text_msg(t("not_registered", lang) + "\n\n" + t("ask_mobile", lang))]

    if lower == "help":
        return [Reply.text_msg(t("help", lang))]

    # --- Unauthenticated flows -------------------------------------------------
    if state == STATE_IDLE:
        _save_session(whatsapp_number, STATE_AWAITING_MOBILE, {}, False, None)
        return [Reply.text_msg(t("ask_mobile", lang))]

    if state == STATE_AWAITING_MOBILE:
        mobile = "".join(ch for ch in text if ch.isdigit())[-10:]
        farmer = farmer_service.get_farmer_by_mobile(mobile)
        if not farmer:
            return [Reply.text_msg(t("mobile_not_found", lang))]
        farmer_service.link_whatsapp_number(farmer["id"], whatsapp_number)
        otp_service.request_otp(mobile)
        _save_session(whatsapp_number, STATE_AWAITING_OTP, {"mobile": mobile, "farmer_id": farmer["id"]}, False, None)
        return [Reply.text_msg(t("otp_sent", lang))]

    if state == STATE_AWAITING_OTP:
        if lower == "resend":
            otp_service.request_otp(ctx["mobile"])
            return [Reply.text_msg(t("otp_sent", lang))]
        try:
            otp_service.verify_otp(ctx["mobile"], text)
        except otp_service.ExpiredOTP:
            return [Reply.text_msg(t("otp_expired", lang))]
        except otp_service.TooManyAttempts:
            return [Reply.text_msg(t("otp_too_many", lang))]
        except otp_service.RateLimited as e:
            return [Reply.text_msg(t("otp_rate_limited", lang, error=str(e)))]
        except otp_service.InvalidOTP as e:
            return [Reply.text_msg(t("otp_invalid", lang, error=str(e)))]

        farmer_id = ctx["farmer_id"]
        _save_session(whatsapp_number, STATE_MAIN_MENU, {"lang": lang}, True, farmer_id)
        session = _get_session(whatsapp_number)
        return [Reply.text_msg(t("otp_verified", lang))] + _main_menu_reply(session)

    # --- Everything below requires authentication -------------------------------
    if not session["authenticated"] or not session["farmer_id"]:
        _reset_session(whatsapp_number)
        return [Reply.text_msg(t("session_expired", lang))]

    farmer_id = session["farmer_id"]

    if state == STATE_MAIN_MENU:
        if selection == "book" or lower in ("book", "book slot", "1"):
            _save_session(whatsapp_number, STATE_SELECTING_CENTRE, {**ctx, "flow": "book"}, True, farmer_id)
            return _centres_list(session)
        if selection == "mybooking" or lower in ("my booking", "mybooking", "2"):
            b = booking_service.get_active_booking_for_farmer(farmer_id)
            if not b:
                return [Reply.text_msg(t("no_active_booking", lang))]
            return [
                Reply.text_msg(
                    t(
                        "my_booking",
                        lang,
                        booking_id=b["booking_id"],
                        centre=b["centre_name"],
                        crop=b["crop"],
                        date=b["slot_date"],
                        time=f"{b['start_time']}\u2013{b['end_time']}",
                        status=b["status"],
                        queue_position=b["queue_position"],
                    )
                )
            ]
        if selection == "slots" or lower in ("slots", "check slots", "3"):
            _save_session(whatsapp_number, STATE_SELECTING_CENTRE, {**ctx, "flow": "browse"}, True, farmer_id)
            return _centres_list(session)
        if lower in ("cancel", "cancel booking", "4"):
            b = booking_service.get_active_booking_for_farmer(farmer_id)
            if not b:
                return [Reply.text_msg(t("no_active_booking", lang))]
            _save_session(whatsapp_number, STATE_AWAITING_CANCEL_CONFIRMATION, {**ctx, "booking_id": b["booking_id"]}, True, farmer_id)
            return [
                Reply.buttons_msg(
                    t("confirm_cancel", lang, booking_id=b["booking_id"]),
                    [("cancel_yes", "CANCEL BOOKING"), ("cancel_no", "KEEP BOOKING")],
                )
            ]
        if lower in ("reschedule", "reschedule booking"):
            b = booking_service.get_active_booking_for_farmer(farmer_id)
            if not b:
                return [Reply.text_msg(t("no_active_booking", lang))]
            _save_session(
                whatsapp_number,
                STATE_RESCHEDULE_SELECTING_DATE,
                {**ctx, "booking_id": b["booking_id"], "centre_id": None, "crop": b["crop"]},
                True,
                farmer_id,
            )
            conn = db.get_conn()
            centre_id = conn.execute(
                "SELECT centre_id FROM procurement_slots WHERE id=?", (b["slot_id"],)
            ).fetchone()["centre_id"]
            conn.close()
            ctx2 = {**ctx, "booking_id": b["booking_id"], "centre_id": centre_id, "crop": b["crop"]}
            _save_session(whatsapp_number, STATE_RESCHEDULE_SELECTING_DATE, ctx2, True, farmer_id)
            return [Reply.text_msg(t("reschedule_pick_date", lang, booking_id=b["booking_id"]))] + _dates_list(
                session, centre_id, b["crop"]
            )
        return [Reply.text_msg(t("unknown_input", lang))] + _main_menu_reply(session)

    if state == STATE_SELECTING_CENTRE:
        try:
            centre_id = int(selection)
        except ValueError:
            return [Reply.text_msg(t("unknown_input", lang))] + _centres_list(session)
        ctx = {**ctx, "centre_id": centre_id}
        _save_session(whatsapp_number, STATE_SELECTING_CROP, ctx, True, farmer_id)
        return _crops_list(session)

    if state == STATE_SELECTING_CROP:
        ctx = {**ctx, "crop": selection}
        _save_session(whatsapp_number, STATE_SELECTING_DATE, ctx, True, farmer_id)
        return _dates_list(session, ctx["centre_id"], ctx["crop"])

    if state == STATE_SELECTING_DATE:
        ctx = {**ctx, "date": selection}
        _save_session(whatsapp_number, STATE_SELECTING_SLOT, ctx, True, farmer_id)
        return _slots_list(session, ctx["centre_id"], ctx["crop"], ctx["date"])

    if state == STATE_SELECTING_SLOT:
        try:
            slot_id = int(selection)
        except ValueError:
            return [Reply.text_msg(t("unknown_input", lang))]
        ctx = {**ctx, "slot_id": slot_id}
        _save_session(whatsapp_number, STATE_AWAITING_BOOKING_CONFIRMATION, ctx, True, farmer_id)
        conn = db.get_conn()
        slot = conn.execute("SELECT * FROM procurement_slots WHERE id=?", (slot_id,)).fetchone()
        centre = conn.execute("SELECT name FROM procurement_centres WHERE id=?", (slot["centre_id"],)).fetchone()
        conn.close()
        farmer = farmer_service.get_farmer_by_id(farmer_id)
        return [
            Reply.buttons_msg(
                t(
                    "confirm_booking",
                    lang,
                    name=farmer["full_name"],
                    centre=centre["name"],
                    crop=slot["crop"],
                    date=slot["slot_date"],
                    time=_fmt_slot(slot),
                ),
                [("confirm_yes", "CONFIRM"), ("confirm_no", "CANCEL")],
            )
        ]

    if state == STATE_AWAITING_BOOKING_CONFIRMATION:
        if selection == "confirm_no" or lower == "cancel":
            _save_session(whatsapp_number, STATE_MAIN_MENU, {"lang": lang}, True, farmer_id)
            return _main_menu_reply(_get_session(whatsapp_number))
        if selection == "confirm_yes" or lower == "confirm":
            try:
                b = booking_service.create_booking(farmer_id, ctx["slot_id"])
            except booking_service.SlotFull:
                _save_session(whatsapp_number, STATE_SELECTING_SLOT, ctx, True, farmer_id)
                return [Reply.text_msg(t("slot_just_taken", lang))] + _slots_list(
                    session, ctx["centre_id"], ctx["crop"], ctx["date"]
                )
            except booking_service.DuplicateBooking as e:
                _save_session(whatsapp_number, STATE_MAIN_MENU, {"lang": lang}, True, farmer_id)
                return [Reply.text_msg(t("duplicate_booking", lang, summary=str(e)))]
            _save_session(whatsapp_number, STATE_MAIN_MENU, {"lang": lang}, True, farmer_id)
            farmer = farmer_service.get_farmer_by_id(farmer_id)
            return [
                Reply.text_msg(
                    t(
                        "booking_success",
                        lang,
                        booking_id=b["booking_id"],
                        name=farmer["full_name"],
                        centre=b["centre_name"],
                        date=b["slot_date"],
                        time=f"{b['start_time']}\u2013{b['end_time']}",
                    )
                )
            ]
        return [Reply.text_msg(t("unknown_input", lang))]

    if state == STATE_AWAITING_CANCEL_CONFIRMATION:
        if selection == "cancel_yes":
            b = booking_service.cancel_booking(ctx["booking_id"], reason="cancelled via WhatsApp")
            _save_session(whatsapp_number, STATE_MAIN_MENU, {"lang": lang}, True, farmer_id)
            return [Reply.text_msg(t("cancelled", lang, booking_id=b["booking_id"]))]
        _save_session(whatsapp_number, STATE_MAIN_MENU, {"lang": lang}, True, farmer_id)
        return [Reply.text_msg(t("cancel_aborted", lang))]

    if state == STATE_RESCHEDULE_SELECTING_DATE:
        ctx = {**ctx, "new_date": selection}
        _save_session(whatsapp_number, STATE_RESCHEDULE_SELECTING_SLOT, ctx, True, farmer_id)
        return _slots_list(session, ctx["centre_id"], ctx["crop"], ctx["new_date"])

    if state == STATE_RESCHEDULE_SELECTING_SLOT:
        try:
            new_slot_id = int(selection)
        except ValueError:
            return [Reply.text_msg(t("unknown_input", lang))]
        try:
            b = booking_service.reschedule_booking(ctx["booking_id"], new_slot_id)
        except booking_service.SlotFull:
            return [Reply.text_msg(t("slot_just_taken", lang))] + _slots_list(
                session, ctx["centre_id"], ctx["crop"], ctx["new_date"]
            )
        _save_session(whatsapp_number, STATE_MAIN_MENU, {"lang": lang}, True, farmer_id)
        return [
            Reply.text_msg(
                t(
                    "reschedule_done",
                    lang,
                    booking_id=b["booking_id"],
                    date=b["slot_date"],
                    time=f"{b['start_time']}\u2013{b['end_time']}",
                )
            )
        ]

    # Fallback
    _save_session(whatsapp_number, STATE_MAIN_MENU, {"lang": lang}, True, farmer_id)
    return [Reply.text_msg(t("unknown_input", lang))] + _main_menu_reply(_get_session(whatsapp_number))
