# अपनी BAARI — SIH Demo Runbook

## Launch
1. Open the folder in VS Code.
2. Run `run.bat`, or `py -3 -m uvicorn app:app --host 127.0.0.1 --port 8000 --reload`.
3. Open `http://127.0.0.1:8000/`.

## 3-minute presentation flow
1. **Farmer:** Open `ई-उपार्जन`, book Mandi + crop + quantity + vehicle + slot. Show generated `AB-2026-XXXX` pass.
2. **Live queue:** Show six-stage tracker, EWT, vehicle throughput and Gate Check-in.
3. **Smart layer:** Select Bhopal/Karnal to show >40% rain policy, covered-shed recommendation and rescheduling.
4. **Government analytics:** Show the five-mandi Leaflet heatmap.
5. **AI:** Start grain scan, show moisture/foreign/broken/grade, then transfer to officer form.
6. **Communication:** Demonstrate WhatsApp-style bot and IVR keypad/voice.
7. **Offline:** Generate emergency token, switch network/offline simulation, then sync after reconnect.
8. **Officer:** Click `अगला किसान बुलाएं` and show audio + SMS trigger.
9. **Payment:** Enter gross/tare, generate Form J, show net quantity, MSP payout and PFMS UTR.

## Backend
SQLite database is created automatically as `apni_baari.db`. API routes are under `/api/*` and are used by the e-Procurement page. The prototype intentionally uses simulated weather/AI/SMS/PFMS values; production deployment should replace those adapters with approved government/provider APIs.
