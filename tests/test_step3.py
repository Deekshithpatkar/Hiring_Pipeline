import os
import sys
from sqlalchemy import text

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.models import SessionLocal, Candidate, StageEvent
from app.pipeline import (
    create_candidate,
    get_current_stage,
    advance_stage,
    InvalidTransitionError,
    ORDERED_STAGES,
)


def cleanup_candidate(db, candidate_id):
    with db.bind.connect() as conn:
        conn.execute(text("ALTER TABLE stage_events DISABLE TRIGGER trg_stage_events_immutable;"))
        conn.execute(text(f"DELETE FROM stage_events WHERE candidate_id = '{candidate_id}';"))
        conn.execute(text(f"DELETE FROM candidates WHERE id = '{candidate_id}';"))
        conn.execute(text("ALTER TABLE stage_events ENABLE TRIGGER trg_stage_events_immutable;"))
        conn.commit()


def test_valid_path_end_to_end():
    print("Testing valid end-to-end path: Applied -> Screening -> Interview -> Offer -> Hired...")
    db = SessionLocal()
    cand = create_candidate(db, "Happy Path Candidate", "happypath@example.com")
    cand_id = cand.id

    try:
        assert get_current_stage(db, cand_id) == "Applied"

        for next_stage in ["Screening", "Interview", "Offer", "Hired"]:
            event = advance_stage(db, cand_id, next_stage)
            assert event.to_stage == next_stage
            assert get_current_stage(db, cand_id) == next_stage

        print("  PASS: End-to-end forward progression succeeded.")
    finally:
        cleanup_candidate(db, cand_id)
        db.close()


def test_rejections_and_invalid_transitions():
    print("Testing invalid transitions and clear error messages...")
    db = SessionLocal()
    cand = create_candidate(db, "Transition Candidate", "test_trans@example.com")
    cand_id = cand.id

    try:
        # 1. Skipping stage: Applied -> Interview
        try:
            advance_stage(db, cand_id, "Interview")
            assert False, "Should not allow skipping Screening"
        except InvalidTransitionError as e:
            print(f"  PASS: Skipping stage correctly blocked: {e}")
            assert "Cannot skip stages" in str(e)

        # 2. Duplicate transition: Applied -> Applied
        try:
            advance_stage(db, cand_id, "Applied")
            assert False, "Should not allow duplicate transition"
        except InvalidTransitionError as e:
            print(f"  PASS: Duplicate stage correctly blocked: {e}")
            assert "already in 'Applied'" in str(e)

        # Advance to Screening, then Interview
        advance_stage(db, cand_id, "Screening")
        advance_stage(db, cand_id, "Interview")
        assert get_current_stage(db, cand_id) == "Interview"

        # 3. Going backwards: Interview -> Screening
        try:
            advance_stage(db, cand_id, "Screening")
            assert False, "Should not allow moving backwards"
        except InvalidTransitionError as e:
            print(f"  PASS: Moving backwards correctly blocked: {e}")
            assert "Cannot move backwards" in str(e)

        # Advance to Offer, then Hired
        advance_stage(db, cand_id, "Offer")
        advance_stage(db, cand_id, "Hired")
        assert get_current_stage(db, cand_id) == "Hired"

        # 4. Hired -> anything (terminal state)
        for target in ["Applied", "Screening", "Interview", "Offer", "Hired", "Rejected"]:
            try:
                advance_stage(db, cand_id, target)
                assert False, f"Should not allow transition from Hired to {target}"
            except InvalidTransitionError as e:
                assert "terminal stage 'Hired'" in str(e)
        print("  PASS: Hired is completely terminal (all transitions blocked).")

    finally:
        cleanup_candidate(db, cand_id)
        db.close()


def test_rejected_state_from_each_non_terminal_stage():
    print("Testing that Rejected is reachable from every non-terminal stage...")
    db = SessionLocal()

    # Stages before Hired: Applied, Screening, Interview, Offer
    non_terminal_stages = ["Applied", "Screening", "Interview", "Offer"]

    for stage in non_terminal_stages:
        cand = create_candidate(db, f"Reject at {stage}", f"reject_{stage.lower()}@example.com")
        cand_id = cand.id
        try:
            # Advance up to 'stage'
            for s in ORDERED_STAGES[1:ORDERED_STAGES.index(stage) + 1]:
                advance_stage(db, cand_id, s)
            assert get_current_stage(db, cand_id) == stage

            # Now reject
            evt = advance_stage(db, cand_id, "Rejected")
            assert evt.to_stage == "Rejected"
            assert get_current_stage(db, cand_id) == "Rejected"

            # Rejected is terminal: try advancing to anything else
            for target in ["Applied", "Screening", "Interview", "Offer", "Hired", "Rejected"]:
                try:
                    advance_stage(db, cand_id, target)
                    assert False, f"Should not allow transition from Rejected to {target}"
                except InvalidTransitionError as e:
                    assert "terminal stage 'Rejected'" in str(e)

            print(f"  PASS: Rejection from '{stage}' succeeded and confirmed terminal.")
        finally:
            cleanup_candidate(db, cand_id)

    db.close()


if __name__ == "__main__":
    print("--- Running Step 3 Verification ---")
    test_valid_path_end_to_end()
    test_rejections_and_invalid_transitions()
    test_rejected_state_from_each_non_terminal_stage()
    print("\nALL STEP 3 VERIFICATIONS PASSED SUCCESSFULLY!")
