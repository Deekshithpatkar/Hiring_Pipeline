import os
import sys
from datetime import datetime, timedelta, timezone
from sqlalchemy import text

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.models import SessionLocal
from app.pipeline import (
    create_candidate,
    advance_stage,
    get_history,
    get_candidate_details,
)


def cleanup_candidate(db, candidate_id):
    with db.bind.connect() as conn:
        conn.execute(text("ALTER TABLE stage_events DISABLE TRIGGER trg_stage_events_immutable;"))
        conn.execute(text(f"DELETE FROM stage_events WHERE candidate_id = '{candidate_id}';"))
        conn.execute(text(f"DELETE FROM candidates WHERE id = '{candidate_id}';"))
        conn.execute(text("ALTER TABLE stage_events ENABLE TRIGGER trg_stage_events_immutable;"))
        conn.commit()


def test_candidate_history_and_durations():
    print("Testing candidate history and computed durations across 3 stages...")
    db = SessionLocal()

    # Fixed base time in UTC
    t0 = datetime(2026, 1, 10, 10, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(hours=2)           # Spent 2 hours in Applied
    t2 = t1 + timedelta(days=3)            # Spent 3 days in Screening
    as_of_1 = t2 + timedelta(minutes=45)   # In Interview for 45 minutes

    cand = create_candidate(db, "Audit History Test", "history@example.com")
    cand_id = cand.id

    try:
        # Override initial event timestamp to t0 for precise math testing
        with db.bind.connect() as conn:
            conn.execute(text("ALTER TABLE stage_events DISABLE TRIGGER trg_stage_events_immutable;"))
            conn.execute(text(
                f"UPDATE stage_events SET timestamp = '{t0.isoformat()}' WHERE candidate_id = '{cand_id}';"
            ))
            conn.execute(text("ALTER TABLE stage_events ENABLE TRIGGER trg_stage_events_immutable;"))
            conn.commit()

        # Advance to Screening at t1
        advance_stage(db, cand_id, "Screening", event_time=t1)

        # Advance to Interview at t2
        advance_stage(db, cand_id, "Interview", event_time=t2)

        # 1. Fetch history as of as_of_1
        history = get_history(db, cand_id, as_of=as_of_1)
        assert len(history) == 3, f"Expected 3 events, got {len(history)}"

        # Check order
        stages = [e["to_stage"] for e in history]
        assert stages == ["Applied", "Screening", "Interview"], f"Unexpected stage order: {stages}"

        # Check event 1 (Applied)
        assert history[0]["from_stage"] is None
        assert history[0]["to_stage"] == "Applied"
        assert history[0]["duration_seconds"] == 2 * 3600.0, f"Expected 7200s, got {history[0]['duration_seconds']}"
        assert history[0]["duration_human"] == "2h"
        assert not history[0]["is_current"]

        # Check event 2 (Screening)
        assert history[1]["from_stage"] == "Applied"
        assert history[1]["to_stage"] == "Screening"
        assert history[1]["duration_seconds"] == 3 * 86400.0, f"Expected 259200s, got {history[1]['duration_seconds']}"
        assert history[1]["duration_human"] == "3d"
        assert not history[1]["is_current"]

        # Check event 3 (Interview - current)
        assert history[2]["from_stage"] == "Screening"
        assert history[2]["to_stage"] == "Interview"
        assert history[2]["duration_seconds"] == 45 * 60.0, f"Expected 2700s, got {history[2]['duration_seconds']}"
        assert history[2]["duration_human"] == "45m"
        assert history[2]["is_current"]

        print("  PASS: All 3 stages show in correct order with exact computed durations.")

        # 2. Test dynamic update of time in current stage as time advances
        as_of_2 = as_of_1 + timedelta(hours=1, minutes=15)  # +75 minutes = total 2 hours in Interview
        history_later = get_history(db, cand_id, as_of=as_of_2)
        current_event_later = history_later[-1]

        expected_duration = (45 + 75) * 60.0  # 120 minutes = 7200s = 2h
        assert current_event_later["duration_seconds"] == expected_duration, (
            f"Expected {expected_duration}s, got {current_event_later['duration_seconds']}"
        )
        assert current_event_later["duration_human"] == "2h"
        print("  PASS: Time in current stage updates dynamically with elapsed time.")

        # 3. Test get_candidate_details aggregation
        details = get_candidate_details(db, cand_id, as_of=as_of_1)
        assert details["current_stage"] == "Interview"
        assert details["time_in_current_stage_seconds"] == 45 * 60.0
        assert details["time_in_current_stage_human"] == "45m"
        assert "Offer" in details["allowed_next_stages"]
        assert "Rejected" in details["allowed_next_stages"]
        print("  PASS: Candidate details wrapper returns correct current state and allowed actions.")

    finally:
        cleanup_candidate(db, cand_id)
        db.close()


if __name__ == "__main__":
    print("--- Running Step 4 Verification ---")
    test_candidate_history_and_durations()
    print("\nALL STEP 4 VERIFICATIONS PASSED SUCCESSFULLY!")
