"""
Local WhatsApp test harness -- NOT part of the real WhatsApp Cloud API.

Per spec section 39 ("Demo Mode"): this simulates incoming WhatsApp payloads
so the exact same conversation/booking/OTP backend code can be demoed without
live Meta credentials. It calls the identical conversation.handle_incoming()
entry point the real /webhook uses -- nothing about the booking logic,
database, OTP security, or capacity enforcement is different or faked here.

Only ever mounted for local development; see app.py.
"""
from __future__ import annotations
from fastapi import APIRouter
from pydantic import BaseModel

from . import conversation, otp_service

router = APIRouter(prefix="/dev")


class SimulateIn(BaseModel):
    from_number: str
    text: str = ""
    interactive_id: str | None = None


@router.post("/simulate-message")
def simulate_message(x: SimulateIn):
    replies = conversation.handle_incoming(x.from_number, x.text, x.interactive_id)
    out = []
    for r in replies:
        out.append(
            {
                "kind": r.kind,
                "text": r.text,
                "buttons": r.buttons,
                "rows": r.rows,
                "button_text": r.button_text,
            }
        )
    mobile_digits = "".join(ch for ch in x.text if ch.isdigit())
    debug_otp = None
    if otp_service.OTP_MODE != "production":
        # Best-effort: if the farmer just typed their mobile number, surface
        # the dev OTP that was generated for it so a demo doesn't need to
        # tail server logs. Harmless: only active outside production, and
        # this mirrors exactly what's already printed to the console.
        for candidate in (mobile_digits[-10:], x.from_number):
            val = otp_service.debug_peek_last_otp(candidate)
            if val:
                debug_otp = val
                break
    return {"replies": out, "debug_otp": debug_otp}


@router.post("/reset-session")
def reset_session(from_number: str):
    conversation._reset_session(from_number)  # noqa: SLF001 - dev-only reset
    return {"ok": True}
