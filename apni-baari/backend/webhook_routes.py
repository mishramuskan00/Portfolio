"""
FastAPI router implementing the real WhatsApp Business Cloud API webhook
contract (GET for verification, POST for incoming events).

This file is intentionally thin: all decision-making lives in
backend/conversation.py (pure stdlib, independently tested in
backend/tests/). This router's only jobs are:
  1. speak the exact HTTP/JSON shape Meta's webhook expects,
  2. de-duplicate/guard against replay of the same WhatsApp message id,
  3. turn conversation.Reply objects into real WhatsAppService calls.
"""
from __future__ import annotations
import os
import logging
from fastapi import APIRouter, Request, Response, Query

from . import db, conversation
from .whatsapp_service import whatsapp_service

logger = logging.getLogger("apni_baari.webhook")
router = APIRouter()

VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")


@router.get("/webhook")
def verify_webhook(
    hub_mode: str = Query(default="", alias="hub.mode"),
    hub_verify_token: str = Query(default="", alias="hub.verify_token"),
    hub_challenge: str = Query(default="", alias="hub.challenge"),
):
    """Meta calls this once when you configure the webhook URL in the App
    Dashboard. Must echo back hub.challenge as plain text, and ONLY if the
    verify token matches what you configured -- otherwise reject."""
    if hub_mode == "subscribe" and hub_verify_token and hub_verify_token == VERIFY_TOKEN:
        return Response(content=hub_challenge, media_type="text/plain")
    return Response(content="Verification failed", status_code=403)


def _already_processed(message_id: str | None) -> bool:
    """Replay/duplicate-delivery protection: WhatsApp may redeliver the same
    event if it doesn't get a fast 200. We record message ids we've handled
    and skip re-processing them (idempotent webhook)."""
    if not message_id:
        return False
    conn = db.get_conn()
    try:
        exists = conn.execute(
            "SELECT 1 FROM whatsapp_webhook_events WHERE message_id=?", (message_id,)
        ).fetchone()
        if exists:
            return True
        conn.execute(
            "INSERT OR IGNORE INTO whatsapp_webhook_events(message_id, received_at) VALUES (?,?)",
            (message_id, db.now_iso()),
        )
        conn.commit()
        return False
    finally:
        conn.close()


def _extract_messages(payload: dict) -> list[dict]:
    """Meta's webhook payload is deeply nested and can contain zero or more
    messages per call (batching), plus non-message events (status updates,
    etc.) that we should silently ignore rather than error on."""
    out = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for msg in value.get("messages", []) or []:
                out.append(msg)
    return out


def _incoming_text_and_interactive(msg: dict) -> tuple[str, str | None]:
    mtype = msg.get("type")
    if mtype == "text":
        return msg.get("text", {}).get("body", ""), None
    if mtype == "interactive":
        interactive = msg.get("interactive", {})
        if interactive.get("type") == "button_reply":
            br = interactive["button_reply"]
            return br.get("title", ""), br.get("id")
        if interactive.get("type") == "list_reply":
            lr = interactive["list_reply"]
            return lr.get("title", ""), lr.get("id")
    # Unsupported message type (image, audio, location, etc.) -- treat as
    # unrecognised text so the bot responds gracefully instead of crashing.
    return "", None


def _dispatch_replies(to: str, replies: list[conversation.Reply]) -> None:
    for reply in replies:
        try:
            if reply.kind == "text":
                whatsapp_service.send_text_message(to, reply.text)
            elif reply.kind == "buttons":
                whatsapp_service.send_button_message(to, reply.text, reply.buttons)
            elif reply.kind == "list":
                whatsapp_service.send_list_message(to, reply.text, reply.button_text, reply.rows)
        except Exception:  # noqa: BLE001 - never let a send failure break the webhook
            logger.exception("Failed to send WhatsApp message to %s", to)


@router.post("/webhook")
async def receive_webhook(request: Request):
    """Always return HTTP 200 quickly (even on internal errors) so WhatsApp
    does not treat this as a delivery failure and retry-storm the endpoint --
    per Meta's Cloud API guidance and the spec's own requirement."""
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        logger.warning("Received malformed (non-JSON) webhook body")
        return {"status": "ignored"}

    try:
        messages = _extract_messages(payload)
        for msg in messages:
            message_id = msg.get("id")
            if _already_processed(message_id):
                continue
            from_number = msg.get("from")
            if not from_number:
                continue
            text, interactive_id = _incoming_text_and_interactive(msg)
            try:
                replies = conversation.handle_incoming(from_number, text, interactive_id)
            except Exception:  # noqa: BLE001
                logger.exception("Conversation handler error for %s", from_number)
                replies = [conversation.Reply.text_msg(
                    "Something went wrong on our end. Please try again in a moment."
                )]
            _dispatch_replies(from_number, replies)
    except Exception:  # noqa: BLE001
        logger.exception("Unhandled webhook error")

    return {"status": "received"}
