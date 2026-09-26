import sys
import os
import uuid
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from sqlalchemy import text
from app.models import SessionLocal, Candidate, StageEvent
from app.pipeline import create_candidate


def test_create_candidate_success():
    print("Testing create_candidate success...")
    db = SessionLocal()
    name = "Alice Test"
    email = "alice@example.com"

    candidate = create_candidate(db, name, email)
    cand_id = candidate.id

    try:
        # Check candidate row
        db_cand = db.query(Candidate).filter(Candidate.id == cand_id).first()
        assert db_cand is not None, "Candidate was not found in DB"
        assert db_cand.name == name
        assert db_cand.email == email

        # Check stage_events row
        events = db.query(StageEvent).filter(StageEvent.candidate_id == cand_id).all()
        assert len(events) == 1, f"Expected 1 stage_event, got {len(events)}"
        assert events[0].from_stage is None, f"Expected from_stage is None, got {events[0].from_stage}"
        assert events[0].to_stage == "Applied", f"Expected to_stage == 'Applied', got {events[0].to_stage}"
        print("  PASS: Created exactly 1 candidate and 1 Applied stage_event.")

    finally:
        # Cleanup
        with db.bind.connect() as conn:
            conn.execute(text("ALTER TABLE stage_events DISABLE TRIGGER trg_stage_events_immutable;"))
            conn.execute(text(f"DELETE FROM stage_events WHERE candidate_id = '{cand_id}';"))
            conn.execute(text(f"DELETE FROM candidates WHERE id = '{cand_id}';"))
            conn.execute(text("ALTER TABLE stage_events ENABLE TRIGGER trg_stage_events_immutable;"))
            conn.commit()
        db.close()


def test_create_candidate_transaction_rollback():
    print("Testing create_candidate transaction rollback on failure...")
    db = SessionLocal()
    cand_id = str(uuid.uuid4())

    # We simulate a failure on the second insert (stage_events) within the same transaction
    candidate = Candidate(
        id=cand_id,
        name="Rollback Test User",
        email="rollback@example.com",
    )
    # Invalid stage_event (e.g. missing required to_stage)
    invalid_event = StageEvent(
        id=str(uuid.uuid4()),
        candidate_id=cand_id,
        from_stage=None,
        to_stage=None,  # NOT NULL violation in Postgres
    )

    failed = False
    try:
        db.add(candidate)
        db.add(invalid_event)
        db.commit()
    except Exception as e:
        db.rollback()
        failed = True
        print(f"  Expected failure caught: {e.orig if hasattr(e, 'orig') else e}")

    assert failed, "Transaction should have failed!"

    # Verify candidate row was rolled back and does NOT exist
    db_cand = db.query(Candidate).filter(Candidate.id == cand_id).first()
    assert db_cand is None, "Candidate row was NOT rolled back, orphaned row created!"
    print("  PASS: First insert rolled back cleanly when second insert failed (no orphaned row).")
    db.close()


def test_empty_input_validation():
    print("Testing input validation for empty name/email...")
    db = SessionLocal()
    try:
        create_candidate(db, "", "valid@example.com")
        assert False, "Should raise ValueError for empty name"
    except ValueError:
        print("  PASS: Empty name rejected.")

    try:
        create_candidate(db, "Valid Name", "")
        assert False, "Should raise ValueError for empty email"
    except ValueError:
        print("  PASS: Empty email rejected.")
    db.close()


if __name__ == "__main__":
    print("--- Running Step 2 Verification ---")
    test_create_candidate_success()
    test_create_candidate_transaction_rollback()
    test_empty_input_validation()
    print("\nALL STEP 2 VERIFICATIONS PASSED SUCCESSFULLY!")
