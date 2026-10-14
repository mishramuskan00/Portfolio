"""
Seeds procurement_centres and procurement_slots from the mandi/crop data that
already exists in app.py (MANDIS, MSP dicts), so the WhatsApp bot and the
website are quoting the same centres/crops instead of inventing new ones.

Run once: `python3 -m backend.seed`
Safe to re-run -- uses INSERT OR IGNORE / checks before inserting.
"""
from __future__ import annotations
from datetime import date, timedelta

from . import db

MANDIS = ["Karnal", "Khanna", "Bhopal", "Kota", "Nizamabad"]
CROPS = ["Wheat", "Paddy", "Mustard", "Gram"]
SLOT_TIMES = [
    ("09:00", "10:00"),
    ("10:00", "11:00"),
    ("11:00", "12:00"),
    ("14:00", "15:00"),
]
DEFAULT_CAPACITY = 20
DAYS_AHEAD = 14


def seed() -> None:
    conn = db.get_conn()
    try:
        centre_ids = {}
        for name in MANDIS:
            row = conn.execute(
                "SELECT id FROM procurement_centres WHERE name=?", (name,)
            ).fetchone()
            if row:
                centre_ids[name] = row["id"]
                continue
            conn.execute(
                "INSERT INTO procurement_centres(name, state, is_active, created_at) VALUES (?,?,1,?)",
                (name, "", db.now_iso()),
            )
            centre_ids[name] = conn.execute("SELECT last_insert_rowid() id").fetchone()["id"]
        conn.commit()

        today = date.today()
        created = 0
        for name, centre_id in centre_ids.items():
            for d in range(DAYS_AHEAD):
                slot_date = (today + timedelta(days=d)).isoformat()
                for crop in CROPS:
                    for start, end in SLOT_TIMES:
                        exists = conn.execute(
                            """SELECT 1 FROM procurement_slots
                               WHERE centre_id=? AND crop=? AND slot_date=? AND start_time=?""",
                            (centre_id, crop, slot_date, start),
                        ).fetchone()
                        if exists:
                            continue
                        conn.execute(
                            """INSERT INTO procurement_slots
                               (centre_id, crop, slot_date, start_time, end_time, capacity,
                                booked_count, is_open, created_at)
                               VALUES (?,?,?,?,?,?,0,1,?)""",
                            (centre_id, crop, slot_date, start, end, DEFAULT_CAPACITY, db.now_iso()),
                        )
                        created += 1
        conn.commit()
        print(f"Seed complete: {len(centre_ids)} centres, {created} new slots created.")
    finally:
        conn.close()


if __name__ == "__main__":
    seed()
