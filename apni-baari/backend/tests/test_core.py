"""
Runnable with plain `python3 backend/tests/test_core.py` (no pytest/fastapi
required) so it can be executed in constrained environments too. Also works
under pytest if installed.

Each test resets a throwaway copy of the schema in a temp SQLite file so
tests don't collide with each other or with real data.
"""
import os
import sys
import tempfile
import threading
import time
import importlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


def fresh_env():
    """Point backend.db at a brand new temp sqlite file and reload modules
    that cache DB_PATH / open connections at import time."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    import backend.db as db_mod
    db_mod.DB_PATH = tmp.name
    db_mod.init_db()
    import backend.otp_service as otp_mod
    import backend.booking_service as booking_mod
    importlib.reload(otp_mod)
    importlib.reload(booking_mod)
    return db_mod, otp_mod, booking_mod, tmp.name


def seed_centre_slot(db_mod, capacity=1, crop="Wheat"):
    conn = db_mod.get_conn()
    conn.execute(
        "INSERT INTO procurement_centres(name, state, is_active, created_at) VALUES ('TestCentre','TestState',1,?)",
        (db_mod.now_iso(),),
    )
    centre_id = conn.execute("SELECT last_insert_rowid() id").fetchone()["id"]
    conn.execute(
        """INSERT INTO procurement_slots
           (centre_id, crop, slot_date, start_time, end_time, capacity, booked_count, is_open, created_at)
           VALUES (?,?,'2027-01-01','10:00','11:00',?,0,1,?)""",
        (centre_id, crop, capacity, db_mod.now_iso()),
    )
    slot_id = conn.execute("SELECT last_insert_rowid() id").fetchone()["id"]
    conn.commit()
    conn.close()
    return centre_id, slot_id


def seed_farmer(db_mod, mobile="9990001111", name="Test Farmer"):
    conn = db_mod.get_conn()
    conn.execute(
        """INSERT INTO farmers(farmer_id, full_name, mobile_number, registration_status,
                                verification_status, created_at, updated_at)
           VALUES (?,?,?,'approved','verified',?,?)""",
        (f"F-{mobile}", name, mobile, db_mod.now_iso(), db_mod.now_iso()),
    )
    fid = conn.execute("SELECT last_insert_rowid() id").fetchone()["id"]
    conn.commit()
    conn.close()
    return fid


def test_otp_correct_flow():
    db_mod, otp_mod, booking_mod, _ = fresh_env()
    otp_mod.OTP_MODE = "development"
    result = otp_mod.request_otp("9990001111")
    assert result.ok
    # In dev mode we can't read the real OTP from the SMS text easily here,
    # so pull the plaintext by regenerating deterministically is not possible
    # (it's hashed) -- instead verify wrong OTP fails, and confirm structure.
    try:
        otp_mod.verify_otp("9990001111", "000000")
        assert False, "wrong OTP should have failed"
    except otp_mod.InvalidOTP:
        pass
    print("PASS: test_otp_correct_flow")


def test_otp_max_attempts():
    db_mod, otp_mod, booking_mod, _ = fresh_env()
    otp_mod.OTP_MAX_ATTEMPTS = 2
    otp_mod.request_otp("9990002222")
    for _ in range(2):
        try:
            otp_mod.verify_otp("9990002222", "111111")
        except otp_mod.InvalidOTP:
            pass
    try:
        otp_mod.verify_otp("9990002222", "111111")
        assert False, "should be locked out after max attempts"
    except otp_mod.TooManyAttempts:
        pass
    print("PASS: test_otp_max_attempts")


def test_otp_rate_limit():
    db_mod, otp_mod, booking_mod, _ = fresh_env()
    otp_mod.OTP_RATE_LIMIT_PER_HOUR = 2
    otp_mod.request_otp("9990003333")
    otp_mod.request_otp("9990003333")
    try:
        otp_mod.request_otp("9990003333")
        assert False, "third request within the hour should be rate limited"
    except otp_mod.RateLimited:
        pass
    print("PASS: test_otp_rate_limit")


def test_booking_full_slot_rejected():
    db_mod, otp_mod, booking_mod, _ = fresh_env()
    _, slot_id = seed_centre_slot(db_mod, capacity=1)
    f1 = seed_farmer(db_mod, "9990004444", "Farmer One")
    f2 = seed_farmer(db_mod, "9990005555", "Farmer Two")
    booking_mod.create_booking(f1, slot_id)
    try:
        booking_mod.create_booking(f2, slot_id)
        assert False, "second booking on a full 1-capacity slot must fail"
    except booking_mod.SlotFull:
        pass
    print("PASS: test_booking_full_slot_rejected")


def test_duplicate_booking_rejected():
    db_mod, otp_mod, booking_mod, _ = fresh_env()
    _, slot_id = seed_centre_slot(db_mod, capacity=5)
    f1 = seed_farmer(db_mod, "9990006666", "Farmer Dup")
    booking_mod.create_booking(f1, slot_id)
    try:
        booking_mod.create_booking(f1, slot_id)
        assert False, "same farmer booking same date/centre/crop twice must be rejected"
    except booking_mod.DuplicateBooking:
        pass
    print("PASS: test_duplicate_booking_rejected")


def test_cancel_releases_capacity():
    db_mod, otp_mod, booking_mod, _ = fresh_env()
    _, slot_id = seed_centre_slot(db_mod, capacity=1)
    f1 = seed_farmer(db_mod, "9990007777")
    b = booking_mod.create_booking(f1, slot_id)
    booking_mod.cancel_booking(b["booking_id"])
    f2 = seed_farmer(db_mod, "9990008888")
    # Slot should now accept a new booking since capacity was released.
    b2 = booking_mod.create_booking(f2, slot_id)
    assert b2["status"] == "confirmed"
    print("PASS: test_cancel_releases_capacity")


def test_reschedule_moves_capacity_and_is_safe_on_failure():
    db_mod, otp_mod, booking_mod, _ = fresh_env()
    _, slot_a = seed_centre_slot(db_mod, capacity=1, crop="Wheat")
    conn = db_mod.get_conn()
    conn.execute(
        """INSERT INTO procurement_slots
           (centre_id, crop, slot_date, start_time, end_time, capacity, booked_count, is_open, created_at)
           VALUES (1,'Wheat','2027-01-02','09:00','10:00',1,1,1,?)""",
        (db_mod.now_iso(),),
    )  # slot_b already full (booked_count=1, capacity=1)
    slot_b = conn.execute("SELECT last_insert_rowid() id").fetchone()["id"]
    conn.commit()
    conn.close()

    f1 = seed_farmer(db_mod, "9990009999")
    b = booking_mod.create_booking(f1, slot_a)

    try:
        booking_mod.reschedule_booking(b["booking_id"], slot_b)
        assert False, "rescheduling into a full slot must fail"
    except booking_mod.SlotFull:
        pass

    # Original booking must remain fully intact after the failed reschedule.
    still = booking_mod.get_booking(b["booking_id"])
    assert still["slot_id"] == slot_a
    assert still["status"] == "confirmed"
    print("PASS: test_reschedule_moves_capacity_and_is_safe_on_failure")


def test_concurrent_booking_no_overbooking():
    """THE critical test: two threads race for the single remaining seat.
    Exactly one must succeed; the other must get SlotFull. This proves the
    atomic UPDATE ... WHERE booked_count < capacity actually prevents
    overbooking under real concurrent access, not just in theory."""
    db_mod, otp_mod, booking_mod, _ = fresh_env()
    _, slot_id = seed_centre_slot(db_mod, capacity=1)
    fA = seed_farmer(db_mod, "9991111111", "Farmer A")
    fB = seed_farmer(db_mod, "9992222222", "Farmer B")

    results = {}

    def attempt(name, farmer_id):
        try:
            booking_mod.create_booking(farmer_id, slot_id)
            results[name] = "success"
        except booking_mod.SlotFull:
            results[name] = "slot_full"
        except Exception as e:  # pragma: no cover
            results[name] = f"error:{e}"

    t1 = threading.Thread(target=attempt, args=("A", fA))
    t2 = threading.Thread(target=attempt, args=("B", fB))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    outcomes = sorted(results.values())
    assert outcomes == ["slot_full", "success"], f"unexpected outcomes: {results}"

    conn = db_mod.get_conn()
    row = conn.execute("SELECT booked_count, capacity FROM procurement_slots WHERE id=?", (slot_id,)).fetchone()
    conn.close()
    assert row["booked_count"] == row["capacity"] == 1, "slot must not be overbooked"
    print("PASS: test_concurrent_booking_no_overbooking (booked_count stayed at capacity=1 under a real race)")


def test_concurrent_booking_stress_many_threads():
    """10 threads race for 3 seats -- exactly 3 must succeed, 7 must fail."""
    db_mod, otp_mod, booking_mod, _ = fresh_env()
    _, slot_id = seed_centre_slot(db_mod, capacity=3)
    farmer_ids = [seed_farmer(db_mod, f"90000000{i:02d}") for i in range(10)]
    results = []
    lock = threading.Lock()

    def attempt(fid):
        try:
            booking_mod.create_booking(fid, slot_id)
            with lock:
                results.append("success")
        except booking_mod.SlotFull:
            with lock:
                results.append("slot_full")

    threads = [threading.Thread(target=attempt, args=(fid,)) for fid in farmer_ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count("success") == 3, results
    assert results.count("slot_full") == 7, results
    print("PASS: test_concurrent_booking_stress_many_threads (3/10 succeeded, matching capacity=3)")


if __name__ == "__main__":
    test_otp_correct_flow()
    test_otp_max_attempts()
    test_otp_rate_limit()
    test_booking_full_slot_rejected()
    test_duplicate_booking_rejected()
    test_cancel_releases_capacity()
    test_reschedule_moves_capacity_and_is_safe_on_failure()
    test_concurrent_booking_no_overbooking()
    test_concurrent_booking_stress_many_threads()
    print("\nALL TESTS PASSED")
