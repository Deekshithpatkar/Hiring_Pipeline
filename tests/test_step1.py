import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import uuid
from datetime import datetime, timezone
from sqlalchemy import text
from app.models import SessionLocal, Candidate, StageEvent, init_db

def run_step1_verification():
    print("--- Running Step 1 Verification ---")
    init_db()
    db = SessionLocal()

    test_candidate_id = str(uuid.uuid4())
    test_event_id = str(uuid.uuid4())

    try:
        # 1. Verify tables exist
        with db.bind.connect() as conn:
            result = conn.execute(text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';"
            )).fetchall()
            table_names = [r[0] for r in result]
            print(f"1. Tables in public schema: {table_names}")
            assert "candidates" in table_names, "candidates table missing!"
            assert "stage_events" in table_names, "stage_events table missing!"
            print("   PASS: candidates and stage_events tables exist.")

        # Create a test candidate and initial stage_event
        cand = Candidate(
            id=test_candidate_id,
            name="Verification Test User",
            email="verify@test.com",
            created_at=datetime.now(timezone.utc),
        )
        db.add(cand)
        db.commit()

        evt = StageEvent(
            id=test_event_id,
            candidate_id=test_candidate_id,
            from_stage=None,
            to_stage="Applied",
            timestamp=datetime.now(timezone.utc),
        )
        db.add(evt)
        db.commit()
        print("   Test candidate and Applied event created.")

        # 2. Try an UPDATE on stage_events row — must be rejected by DB trigger
        update_blocked = False
        try:
            db.execute(text(
                f"UPDATE stage_events SET to_stage = 'Screening' WHERE id = '{test_event_id}'"
            ))
            db.commit()
        except Exception as e:
            db.rollback()
            update_blocked = True
            print(f"   PASS: UPDATE correctly blocked by DB trigger: {e.orig}")

        assert update_blocked, "FAIL: UPDATE on stage_events was NOT blocked!"

        # 3. Try a DELETE on stage_events row — must be rejected by DB trigger
        delete_blocked = False
        try:
            db.execute(text(
                f"DELETE FROM stage_events WHERE id = '{test_event_id}'"
            ))
            db.commit()
        except Exception as e:
            db.rollback()
            delete_blocked = True
            print(f"   PASS: DELETE correctly blocked by DB trigger: {e.orig}")

        assert delete_blocked, "FAIL: DELETE on stage_events was NOT blocked!"

        # 4. Try inserting two stage_events for same candidate with same to_stage
        duplicate_blocked = False
        try:
            dup_evt = StageEvent(
                id=str(uuid.uuid4()),
                candidate_id=test_candidate_id,
                from_stage="Applied",
                to_stage="Applied",  # duplicate to_stage for this candidate
                timestamp=datetime.now(timezone.utc),
            )
            db.add(dup_evt)
            db.commit()
        except Exception as e:
            db.rollback()
            duplicate_blocked = True
            print(f"   PASS: Duplicate to_stage correctly blocked by UniqueConstraint: {e.orig}")

        assert duplicate_blocked, "FAIL: Duplicate to_stage insert was NOT blocked!"

        print("\nALL STEP 1 VERIFICATIONS PASSED SUCCESSFULLY!")

    finally:
        # Cleanup test data using a raw query bypassing trigger if needed or leaving it
        # Since DELETE on stage_events is blocked by trigger, let's see:
        # Can we drop the test candidate? Because FK is ON DELETE RESTRICT,
        # we can temporarily disable trigger to clean up test row, or leave test row or delete candidate
        with db.bind.connect() as conn:
            conn.execute(text("ALTER TABLE stage_events DISABLE TRIGGER trg_stage_events_immutable;"))
            conn.execute(text(f"DELETE FROM stage_events WHERE candidate_id = '{test_candidate_id}';"))
            conn.execute(text(f"DELETE FROM candidates WHERE id = '{test_candidate_id}';"))
            conn.execute(text("ALTER TABLE stage_events ENABLE TRIGGER trg_stage_events_immutable;"))
            conn.commit()
        db.close()

if __name__ == "__main__":
    run_step1_verification()
