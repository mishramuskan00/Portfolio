"""
WhatsAppService: thin wrapper around the real Meta WhatsApp Business Cloud
API (Graph API). All outbound message sending goes through here so no raw
API calls are scattered through webhook/controller code.

Requires: WHATSAPP_ACCESS_TOKEN, WHATSAPP_PHONE_NUMBER_ID env vars in
production. In OTP_MODE=development without those vars set, sends are
logged locally instead of calling out to Meta (see `enabled` below) so the
conversation logic can be developed/tested without live credentials.
"""
from __future__ import annotations
import os
import json
import urllib.request
import urllib.error

GRAPH_API_VERSION = os.environ.get("WHATSAPP_GRAPH_API_VERSION", "v20.0")
ACCESS_TOKEN = os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")


class WhatsAppService:
    def __init__(self):
        self.enabled = bool(ACCESS_TOKEN and PHONE_NUMBER_ID)
        self.sent_log: list[dict] = []  # used by tests / dev mode to inspect what was "sent"

    def _base_url(self) -> str:
        return f"https://graph.facebook.com/{GRAPH_API_VERSION}/{PHONE_NUMBER_ID}/messages"

    def _post(self, payload: dict) -> dict:
        if not self.enabled:
            # Dev/no-credentials fallback: record instead of calling Meta.
            self.sent_log.append(payload)
            return {"simulated": True, "payload": payload}
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            self._base_url(),
            data=body,
            headers={
                "Authorization": f"Bearer {ACCESS_TOKEN}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            detail = e.read().decode()
            raise RuntimeError(f"WhatsApp API error {e.code}: {detail}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"WhatsApp API unreachable: {e}")

    def send_text_message(self, to: str, text: str) -> dict:
        return self._post(
            {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": text},
            }
        )

    def send_button_message(self, to: str, body_text: str, buttons: list[tuple[str, str]]) -> dict:
        """buttons: list of (id, title) pairs, max 3 per WhatsApp's limit."""
        return self._post(
            {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": body_text},
                    "action": {
                        "buttons": [
                            {"type": "reply", "reply": {"id": bid, "title": title[:20]}}
                            for bid, title in buttons[:3]
                        ]
                    },
                },
            }
        )

    def send_list_message(
        self, to: str, body_text: str, button_text: str, rows: list[tuple[str, str]]
    ) -> dict:
        """rows: list of (id, title) pairs, up to 10."""
        return self._post(
            {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "interactive",
                "interactive": {
                    "type": "list",
                    "body": {"text": body_text},
                    "action": {
                        "button": button_text[:20],
                        "sections": [
                            {
                                "title": "Options",
                                "rows": [
                                    {"id": rid, "title": title[:24]}
                                    for rid, title in rows[:10]
                                ],
                            }
                        ],
                    },
                },
            }
        )


whatsapp_service = WhatsAppService()
