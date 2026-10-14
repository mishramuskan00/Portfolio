# Apni BAARI — WhatsApp Farmer Slot Booking Bot (SIH26032)

This extends the existing Apni BAARI FastAPI backend (`app.py` + `apni_baari.db`)
with a real farmer-account system, OTP authentication, capacity-safe slot
booking, and a WhatsApp Business Cloud API bot — all sharing one database
with the website and government dashboard. It does not remove or rename any
existing route, page, or table.

## A. What was discovered (existing project)

- **Frontend**: static HTML/CSS/JS (farmer portal + government portal). Polished
  UI, but almost entirely client-side demo data — no forms actually saved
  anything, and the government dashboards were hardcoded numbers.
- **Backend**: one FastAPI app (`app.py`) + SQLite (`apni_baari.db`), with a
  single real table (`tokens`) tracking a one-stage-at-a-time procurement
  token (mandi, crop, quantity, vehicle, slot as free text, stage 1–6).
- **No farmer accounts, no login, no OTP, no slot capacity anywhere.** The
  "OTP" field on `farmer-login.html` only checked that 6 digits were typed;
  nothing was verified. `registration.html`'s submit only generated a random
  ID client-side.
- The existing "WhatsApp bot" widget (`js/whatsapp-bot.js`) was a fully
  scripted, hardcoded-reply UI with no server round-trip at all (confirmed by
  the project's own `FEATURES-ADDED.md`).

Because there was no real farmer/slot system to plug into, this feature
**adds** that system (new tables, new services) rather than duplicating
anything — the 5 mandis and crop/MSP list already in `app.py` were reused as
the seed data for procurement centres and crops.

## B. What was implemented

| File | Purpose |
|---|---|
| `backend/db.py` | Schema for `farmers`, `procurement_centres`, `procurement_slots`, `bookings`, `otp_verifications`, `otp_rate_limit`, `whatsapp_sessions`, `audit_log`, `whatsapp_webhook_events`. Adds to the existing `apni_baari.db`, touches nothing existing. |
| `backend/otp_service.py` | Real OTP generation (secrets, 6-digit), salted-hash storage (never plaintext), expiry, max attempts, hourly rate limiting, pluggable `SMSProvider` (dev console vs. production). |
| `backend/whatsapp_service.py` | Thin wrapper around the real Meta Graph API (`/messages` endpoint) — text, button, and list message senders. Falls back to an in-memory log when no credentials are configured (dev only). |
| `backend/booking_service.py` | Slot booking with atomic capacity enforcement (`UPDATE ... WHERE booked_count < capacity`), race-condition-safe (see tests), duplicate-booking protection, cancellation, rescheduling (all-or-nothing). |
| `backend/farmer_service.py` | Farmer lookup/registration — the single source of truth both the website and WhatsApp check against. |
| `backend/conversation.py` | The bot's full state machine (IDLE → mobile → OTP → main menu → book/cancel/reschedule flows), persisted in `whatsapp_sessions` (survives restarts). |
| `backend/messages.py` | English + Hindi message templates (`t(key, lang, **kwargs)`), so no hard-coded strings live in the conversation logic. |
| `backend/seed.py` | Seeds procurement centres/slots from the existing `MANDIS`/crop data. Idempotent. |
| `backend/webhook_routes.py` | Real `GET /webhook` (Meta verification) and `POST /webhook` (incoming messages), with replay protection and graceful handling of malformed/unknown message types. |
| `backend/api_routes.py` | `/api/farmers/*`, `/api/auth/otp/*`, `/api/centres`, `/api/crops`, `/api/slots/available`, `/api/bookings/*`, `/api/officer/bookings`. |
| `backend/simulator_routes.py` | `/dev/simulate-message`, `/dev/reset-session` — local test harness (disabled when `APP_ENV=production`). |
| `backend/tests/test_core.py` | OTP + booking + **concurrency** unit tests (pure stdlib, no pytest needed). |
| `backend/tests/test_conversation.py` | Full simulated conversation from "Hi" to a completed booking. |
| `app.py` | Added router includes + startup seed call. Nothing existing removed or renamed. |
| `whatsapp_bot_server.py` | **New, separate, independently-runnable** WhatsApp bot process — same DB/services as `app.py`, but only the webhook + demo + health-check, so the bot can be deployed/run without the rest of the website. See section J. |
| `registration.html` | `submitRegistration()` now actually `POST`s to `/api/farmers/register` (falls back to a demo-only ID if the backend is unreachable, with a warning). |
| `whatsapp-simulator.html` | **The real, working chatbot UI** — a browser-based WhatsApp look-alike that talks to the live backend via `/dev/simulate-message`. |
| `js/whatsapp-bot.js` | Added one link from the old scripted widget to the real bot, so the two aren't confused. |
| `gov-procurement.html` | Added a "Live Slot Bookings" table reading `/api/officer/bookings`, refreshing every 8s — shows bookings from both WhatsApp and the website, with a `Source` column. |
| `.env.example`, `.gitignore` | Environment variable template; ensures `.env` is never committed. |

## C. Backend architecture

```
Farmer's WhatsApp
      │
      ▼
Meta WhatsApp Cloud API
      │  (POST /webhook)
      ▼
backend/webhook_routes.py  ── replay protection, parses message type
      │
      ▼
backend/conversation.py    ── state machine (whatsapp_sessions table)
      │
      ├─► backend/otp_service.py     (auth)
      ├─► backend/farmer_service.py  (identity)
      └─► backend/booking_service.py (slots/bookings, atomic capacity)
                │
                ▼
          apni_baari.db (SQLite)
                ▲
                │
      backend/api_routes.py  ◄── registration.html, gov-procurement.html
                ▲
                │
        Farmer website / Government dashboard
```

Both channels — WhatsApp and the website — read and write the exact same
`bookings`/`procurement_slots`/`farmers` tables through the same service
functions. There is no separate/duplicate booking system.

## D. Database changes

New tables (see `backend/db.py` for full schema): `farmers`,
`procurement_centres`, `procurement_slots` (has `capacity` + `booked_count`,
enforced atomically), `bookings` (has `booking_id`, `source` = `whatsapp` or
`website`, `queue_position`, `status`), `otp_verifications` (hash only),
`otp_rate_limit`, `whatsapp_sessions` (persisted conversation state),
`audit_log`, `whatsapp_webhook_events` (replay protection).

## E. API endpoints

```
GET  /webhook                          Meta webhook verification
POST /webhook                          Incoming WhatsApp messages

POST /api/farmers/register             Website registration → creates farmer
GET  /api/farmers/{id}
GET  /api/farmers/{id}/bookings

POST /api/auth/otp/request
POST /api/auth/otp/verify

GET  /api/centres
GET  /api/crops
GET  /api/centres/{id}/slots
GET  /api/slots/available

POST /api/bookings
GET  /api/bookings/{booking_id}
POST /api/bookings/{booking_id}/cancel
POST /api/bookings/{booking_id}/reschedule

GET  /api/officer/bookings             Government dashboard data source

POST /dev/simulate-message             Local test harness only (not Meta)
POST /dev/reset-session                Local test harness only
```

None of the pre-existing routes (`/api/tokens`, `/api/mandis`, `/api/msp`,
`/api/queue/{mandi}`, `/api/quality`, `/api/jforms`, `/api/notifications`,
`/api/officer/call-next`) were changed or removed.

## F. Environment variables

See `.env.example` for the full list with comments. At minimum, to go live:
`WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`,
and (for production OTP) `OTP_MODE=production` plus a real `SMS_PROVIDER`
wired into `backend/otp_service.py::get_sms_provider()`.

## G. Meta WhatsApp Cloud API setup

1. Create a Meta developer account at developers.facebook.com and create an App → add the **WhatsApp** product.
2. Under **WhatsApp → API Setup**, note your test phone number's **Phone Number ID** and generate a temporary (or permanent, via a System User) **Access Token**.
3. Put those in `.env` as `WHATSAPP_PHONE_NUMBER_ID` and `WHATSAPP_ACCESS_TOKEN`.
4. Choose any random string for `WHATSAPP_VERIFY_TOKEN` in `.env`.
5. Run the backend locally: `pip install -r requirements.txt` then `python app.py` (or `uvicorn app:app --reload`).
6. Expose it over HTTPS for Meta to reach (Meta requires HTTPS), e.g. a tunneling tool such as `ngrok http 8000` — copy the resulting `https://...` URL.
7. In **WhatsApp → Configuration → Webhook**, set the Callback URL to `https://YOUR-TUNNEL-URL/webhook` and the Verify Token to the same string as `WHATSAPP_VERIFY_TOKEN`. Meta will call `GET /webhook` — our handler in `backend/webhook_routes.py` answers it.
8. Subscribe to the **messages** webhook field.
9. From a real phone, send "Hi" to your WhatsApp test number and confirm you get the welcome menu.

## H. OTP setup

- **Development** (default): `OTP_MODE=development`. OTPs are printed to the server console and also surfaced in the `whatsapp-simulator.html` demo page (as a yellow "DEV MODE" banner) so you don't need to read server logs during a demo. Nothing fake happens to the booking/database logic — only OTP delivery is short-circuited.
- **Production**: set `OTP_MODE=production` and implement a real provider branch in `backend/otp_service.py::get_sms_provider()` (Twilio, MSG91, etc. — whichever you have credentials for), reading its API key from `.env`. Until that's done, `request_otp()` will deliberately raise rather than silently pretend to send an SMS.

## I. Testing

```bash
# Core OTP + booking + concurrency tests (no pytest/fastapi needed):
python3 backend/tests/test_core.py

# Full simulated WhatsApp conversation, start to finish:
python3 backend/tests/test_conversation.py
```

Both were run and pass, including the critical concurrency test: two threads
racing for the last seat in a capacity-1 slot — exactly one succeeds, the
other gets a graceful "slot just taken" response, and the database's
`booked_count` never exceeds `capacity`.

## J. Running the WhatsApp bot as its own standalone service

`whatsapp_bot_server.py` runs the bot **independently of the website** — its
own process, its own port, no dependency on `app.py` being up:

```bash
python whatsapp_bot_server.py
# or:
uvicorn whatsapp_bot_server:app --host 0.0.0.0 --port 8001
```

It exposes only what a WhatsApp bot needs — `GET/POST /webhook`, `/health`,
and (outside production) the `/dev/*` test harness plus the demo page at `/`
(so opening `http://localhost:8001/` alone gives you the same working chat
UI, with no other server required). It deliberately does **not** expose farmer
registration or the officer dashboard — those stay on `app.py`, since that's
still the single website backend.

It is still **not a second booking system**: both processes import the exact
same `backend/` code and, by default, the exact same `apni_baari.db` file in
the project root — so a booking made through this bot appears on the website
dashboard served by `app.py`, and vice versa, automatically. If you ever
deploy the bot on a different machine than the website, point both processes
at the same database location with the `DATABASE_PATH` environment variable
(e.g. a shared network volume) — `backend/db.py` reads that variable, and
every service module (`booking_service.py`, `otp_service.py`, etc.) is
already agnostic to where the file physically lives. I verified this sharing
behavior directly: a farmer registered through one process's imports is
immediately visible through a second, independent import of the same modules
pointed at the same `DATABASE_PATH`.

Use `app.py` (the full website) when you want everything in one process;
use `whatsapp_bot_server.py` when you specifically want the bot deployable
and runnable on its own.

## K. 2–3 minute SIH demo flow

1. Open `registration.html`, register a farmer with a real 10-digit mobile number.
2. Open `whatsapp-simulator.html`, enter the same mobile number (with country code, e.g. `919876543210`), type **Hi**.
3. Enter the mobile number when asked → OTP is shown in the yellow dev banner → type it in.
4. Tap **Book Slot** → pick a centre → crop → date → slot → **CONFIRM**. Show the `APB-...` booking ID.
5. Switch to `gov-procurement.html` → point at the **Live Slot Bookings** table → the same booking appears there with **Source: 📱 WhatsApp Bot**, refreshed live from the same database.
6. Back in the bot, tap **My Booking** to show it round-trips; optionally demo **Cancel** or open a second simulator tab as a different farmer to show a full slot correctly rejecting a booking.
