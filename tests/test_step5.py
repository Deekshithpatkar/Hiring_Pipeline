import os
import sys
from datetime import datetime, timedelta, timezone
from sqlalchemy import text

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.models import SessionLocal
from app.pipeline import create_candidate, advance_stage
from app.search import (
    parse_query,
    compute_name_score,
    search_candidates,
)


def cleanup_all(db, candidate_ids):
    with db.bind.connect() as conn:
        conn.execute(text("ALTER TABLE stage_events DISABLE TRIGGER trg_stage_events_immutable;"))
        for cid in candidate_ids:
            conn.execute(text(f"DELETE FROM stage_events WHERE candidate_id = '{cid}';"))
            conn.execute(text(f"DELETE FROM candidates WHERE id = '{cid}';"))
        conn.execute(text("ALTER TABLE stage_events ENABLE TRIGGER trg_stage_events_immutable;"))
        conn.commit()


def setup_test_candidates(db, now):
    """
    Creates a rich set of candidates for testing all search scenarios:
    1. Priya Sharma: currently in Interview
    2. Rohan Sharma: currently in Screening
    3. Bob Stuck: in Screening for 10 days
    4. Carol Quick: in Screening for 2 days
    5. Dave Recent: moved to Interview 2 days ago (Tuesday)
    6. Eve Old: moved to Interview 30 days ago
    7. Frank ReachedOffer: reached Offer, but got Rejected
    8. Grace Hired: reached Offer, and got Hired
    9. Harry RejectedEarly: rejected from Screening
    """
    cands = {}
    created_ids = []

    def set_initial_time(cid, dt):
        with db.bind.connect() as conn:
            conn.execute(text("ALTER TABLE stage_events DISABLE TRIGGER trg_stage_events_immutable;"))
            conn.execute(text(
                f"UPDATE stage_events SET timestamp = '{dt.isoformat()}' WHERE candidate_id = '{cid}';"
            ))
            conn.execute(text("ALTER TABLE stage_events ENABLE TRIGGER trg_stage_events_immutable;"))
            conn.commit()

    # 1. Priya Sharma (currently in Interview)
    c1 = create_candidate(db, "Priya Sharma", "priya@example.com")
    set_initial_time(c1.id, now - timedelta(days=5))
    advance_stage(db, c1.id, "Screening", event_time=now - timedelta(days=4))
    advance_stage(db, c1.id, "Interview", event_time=now - timedelta(days=1))
    cands["priya"] = c1.id
    created_ids.append(c1.id)

    # 2. Rohan Sharma (currently in Screening)
    c2 = create_candidate(db, "Rohan Sharma", "rohan@example.com")
    set_initial_time(c2.id, now - timedelta(days=3))
    advance_stage(db, c2.id, "Screening", event_time=now - timedelta(days=2))
    cands["rohan"] = c2.id
    created_ids.append(c2.id)

    # 3. Bob Stuck (in Screening for 10 days)
    c3 = create_candidate(db, "Bob Stuck", "bob@example.com")
    set_initial_time(c3.id, now - timedelta(days=15))
    advance_stage(db, c3.id, "Screening", event_time=now - timedelta(days=10))
    cands["bob"] = c3.id
    created_ids.append(c3.id)

    # 4. Carol Quick (in Screening for 2 days)
    c4 = create_candidate(db, "Carol Quick", "carol@example.com")
    set_initial_time(c4.id, now - timedelta(days=4))
    advance_stage(db, c4.id, "Screening", event_time=now - timedelta(days=2))
    cands["carol"] = c4.id
    created_ids.append(c4.id)

    # 5. Dave Recent (moved to Interview 2 days ago)
    c5 = create_candidate(db, "Dave Recent", "dave@example.com")
    set_initial_time(c5.id, now - timedelta(days=6))
    advance_stage(db, c5.id, "Screening", event_time=now - timedelta(days=4))
    advance_stage(db, c5.id, "Interview", event_time=now - timedelta(days=2))
    cands["dave"] = c5.id
    created_ids.append(c5.id)

    # 6. Eve Old (moved to Interview 30 days ago)
    c6 = create_candidate(db, "Eve Old", "eve@example.com")
    set_initial_time(c6.id, now - timedelta(days=40))
    advance_stage(db, c6.id, "Screening", event_time=now - timedelta(days=35))
    advance_stage(db, c6.id, "Interview", event_time=now - timedelta(days=30))
    cands["eve"] = c6.id
    created_ids.append(c6.id)

    # 7. Frank ReachedOffer (reached Offer, then Rejected)
    c7 = create_candidate(db, "Frank ReachedOffer", "frank@example.com")
    set_initial_time(c7.id, now - timedelta(days=20))
    advance_stage(db, c7.id, "Screening", event_time=now - timedelta(days=15))
    advance_stage(db, c7.id, "Interview", event_time=now - timedelta(days=10))
    advance_stage(db, c7.id, "Offer", event_time=now - timedelta(days=5))
    advance_stage(db, c7.id, "Rejected", event_time=now - timedelta(days=2))
    cands["frank"] = c7.id
    created_ids.append(c7.id)

    # 8. Grace Hired (reached Offer, then Hired)
    c8 = create_candidate(db, "Grace Hired", "grace@example.com")
    set_initial_time(c8.id, now - timedelta(days=20))
    advance_stage(db, c8.id, "Screening", event_time=now - timedelta(days=15))
    advance_stage(db, c8.id, "Interview", event_time=now - timedelta(days=10))
    advance_stage(db, c8.id, "Offer", event_time=now - timedelta(days=5))
    advance_stage(db, c8.id, "Hired", event_time=now - timedelta(days=1))
    cands["grace"] = c8.id
    created_ids.append(c8.id)

    # 9. Harry RejectedEarly (rejected from Screening)
    c9 = create_candidate(db, "Harry RejectedEarly", "harry@example.com")
    set_initial_time(c9.id, now - timedelta(days=8))
    advance_stage(db, c9.id, "Screening", event_time=now - timedelta(days=6))
    advance_stage(db, c9.id, "Rejected", event_time=now - timedelta(days=3))
    cands["harry"] = c9.id
    created_ids.append(c9.id)

    return cands, created_ids


def test_search_all_substeps():
    print("--- Running Step 5 Verification ---")
    db = SessionLocal()

    # Fixed 'now' as Friday, Jan 23 2026 12:00:00 UTC
    now = datetime(2026, 1, 23, 12, 0, 0, tzinfo=timezone.utc)
    cands, created_ids = setup_test_candidates(db, now)

    try:
        # Sub-step 5a: Stage & Negation detection
        print("\n[5a] Testing Stage & Negation detection...")
        res_interview = search_candidates(db, "Who's in Interview right now?", as_of=now)
        assert res_interview["success"]
        interview_ids = {r["id"] for r in res_interview["results"]}
        assert cands["priya"] in interview_ids
        assert cands["dave"] in interview_ids
        assert cands["eve"] in interview_ids
        assert cands["rohan"] not in interview_ids
        print(f"  PASS: 'Who\\'s in Interview right now?' returned {len(interview_ids)} candidates.")

        res_except = search_candidates(db, "Everyone except rejected candidates", as_of=now)
        assert res_except["success"]
        except_ids = {r["id"] for r in res_except["results"]}
        assert cands["frank"] not in except_ids  # frank is rejected
        assert cands["harry"] not in except_ids  # harry is rejected
        assert cands["priya"] in except_ids
        assert cands["grace"] in except_ids
        print(f"  PASS: 'Everyone except rejected candidates' excluded rejected candidates.")

        # Sub-step 5b: Time phrase detection
        print("\n[5b] Testing Time phrase detection...")
        # Bob in Screening for 10 days (> 1 week), Carol only 2 days
        res_stuck = search_candidates(db, "Who has been stuck in Screening for more than a week?", as_of=now)
        assert res_stuck["success"]
        stuck_ids = {r["id"] for r in res_stuck["results"]}
        assert cands["bob"] in stuck_ids
        assert cands["carol"] not in stuck_ids
        print("  PASS: 'stuck in Screening for more than a week' correctly matched Bob (>10d) and excluded Carol (2d).")

        # Dave moved to Interview 2 days ago (Wednesday, Jan 21). Last Monday was Jan 19.
        # Eve moved 30 days ago (December).
        res_since = search_candidates(db, "Who moved to Interview since Monday?", as_of=now)
        assert res_since["success"]
        since_ids = {r["id"] for r in res_since["results"]}
        assert cands["dave"] in since_ids
        assert cands["priya"] in since_ids  # moved 1 day ago
        assert cands["eve"] not in since_ids  # moved 30 days ago
        print("  PASS: 'moved to Interview since Monday' matched Dave and Priya, excluded Eve.")

        # Sub-step 5c: "reached but not current"
        print("\n[5c] Testing 'reached but not current' detection...")
        res_reached = search_candidates(db, "Who reached the Offer stage but didn't get hired?", as_of=now)
        assert res_reached["success"]
        reached_ids = {r["id"] for r in res_reached["results"]}
        assert cands["frank"] in reached_ids  # reached Offer, now Rejected
        assert cands["grace"] not in reached_ids  # reached Offer and got Hired
        print("  PASS: 'reached Offer stage but didn't get hired' matched Frank and excluded Grace.")

        # Sub-step 5d: Fuzzy name matching
        print("\n[5d] Testing Fuzzy name matching...")
        res_fuzzy = search_candidates(db, "sharam", as_of=now)
        assert res_fuzzy["success"]
        fuzzy_names = [r["name"] for r in res_fuzzy["results"]]
        assert "Priya Sharma" in fuzzy_names
        assert "Rohan Sharma" in fuzzy_names
        print("  PASS: 'sharam' correctly matched Sharma candidates.")

        res_full = search_candidates(db, "Find Priya Sharma", as_of=now)
        assert res_full["success"]
        # Priya Sharma should rank first
        assert res_full["results"][0]["name"] == "Priya Sharma"
        print("  PASS: 'Find Priya Sharma' ranked exact match first.")

        # Sub-step 5e: Combining, ranking, and invalid input
        print("\n[5e] Testing Combined queries & Invalid query explanations...")
        # Combined: Name + Stage
        res_combined = search_candidates(db, "Priya in Interview", as_of=now)
        assert res_combined["success"]
        assert len(res_combined["results"]) == 1
        assert res_combined["results"][0]["name"] == "Priya Sharma"
        print("  PASS: Combined query 'Priya in Interview' matched only Priya.")

        # Invalid stage: "Who's in Onboarding"
        res_invalid_stage = search_candidates(db, "Who's in Onboarding", as_of=now)
        assert not res_invalid_stage["success"]
        assert "'Onboarding' is not a recognized pipeline stage" in res_invalid_stage["explanation"]
        print(f"  PASS: Invalid stage returned explanation: '{res_invalid_stage['explanation']}'")

        # Nonsensical query: "flying cars"
        res_gibberish = search_candidates(db, "flying cars", as_of=now)
        assert not res_gibberish["success"] or res_gibberish["count"] == 0
        assert res_gibberish["explanation"] is not None
        print(f"  PASS: Nonsensical query returned explanation: '{res_gibberish['explanation']}'")

        print("\nALL 5 SUB-STEPS (5a, 5b, 5c, 5d, 5e) PASSED WITH 100% SUCCESS!")

    finally:
        cleanup_all(db, created_ids)
        db.close()


if __name__ == "__main__":
    test_search_all_substeps()
