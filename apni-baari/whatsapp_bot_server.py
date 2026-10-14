"""
Apni BAARI — standalone WhatsApp bot server.

This is a SEPARATE process from app.py (the main website backend). Run it on
its own when you want the WhatsApp bot to live independently of the website
-- e.g. deployed on a different host/port, or as the only thing running
during a live WhatsApp demo, without needing the rest of the site up.

    python whatsapp_bot_server.py
    # or:
    uvicorn whatsapp_bot_server:app --host 0.0.0.0 --port 8001

IMPORTANT -- this is still NOT a second/duplicate booking system. It reads
and writes the exact same apni_baari.db SQLite file (and exact same
backend/ services: conversation.py, booking_service.py, otp_service.py,
farmer_service.py) that app.py uses. As long as both processes can see the
same database file, a booking made via WhatsApp here shows up on the website
and government dashboard served by app.py, and vice versa -- that's enforced
by both processes importing the identical backend/db.py, not by any syncing
logic. If you deploy the bot on a different machine than the website, point
both at the same file via the DATABASE_PATH environment variable (e.g. a
shared network volume), or swap backend/db.py for a networked database
later -- the service layer (booking_service.py etc.) doesn't care where the
file lives.

Endpoints exposed here:
    GET  /webhook            Meta webhook verification
    POST /webhook            Real incoming WhatsApp messages
    GET  /health             Liveness check for your host/uptime monitor
    /                         The browser-based bot demo (whatsapp-simulator.html)
    /dev/*                    Local test harness (disabled if APP_ENV=production)

Deliberately NOT included here: the /api/tokens, /api/mandis, /api/msp,
farmer registration, or officer-dashboard endpoints -- those stay on the
main website's app.py. If you need farmer registration or the officer
dashboard reachable from wherever this bot is deployed too, run
`uvicorn app:app` instead (it includes everything this file does, plus the
full website) -- use this standalone file specifically when you want the bot
by itself.
"""
from __future__ import annotations
import os
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.webhook_routes import router as whatsapp_webhook_router
from backend.seed import seed as seed_procurement_data

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("apni_baari.whatsapp_bot_server")

BASE = Path(__file__).resolve().parent

app = FastAPI(
    title="Apni BAARI WhatsApp Bot (standalone)",
    description="Runs the WhatsApp farmer slot-booking bot independently of the website.",
)

# Allow the demo page (and, if you host the website elsewhere, the website
# itself) to call this service's /api-equivalent routes cross-origin.
# Tighten this to your real domains before going to production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ALLOW_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(whatsapp_webhook_router)

if os.environ.get("APP_ENV", "development") != "production":
    from backend.simulator_routes import router as whatsapp_sim_router
    app.include_router(whatsapp_sim_router)


@app.on_event("startup")
def _startup():
    seed_procurement_data()
    logger.info("Apni BAARI WhatsApp bot server ready. DB: %s", os.environ.get("DATABASE_PATH", "apni_baari.db (default, project root)"))


@app.get("/health")
def health():
    return {"status": "ok", "service": "whatsapp-bot"}


@app.get("/")
def demo_home():
    """Serves the same browser-based bot demo used from the website, so this
    process is fully self-contained for testing/demoing without app.py
    running at all."""
    return FileResponse(BASE / "whatsapp-simulator.html")


# Static assets the demo page needs (its own CSS/JS, plus the logo it shows).
app.mount("/js", StaticFiles(directory=BASE / "js"), name="bot-js")
app.mount("/css", StaticFiles(directory=BASE / "css"), name="bot-css")

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8001"))
    uvicorn.run("whatsapp_bot_server:app", host="0.0.0.0", port=port, reload=False)
