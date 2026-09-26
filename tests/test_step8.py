import sys
import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone
from sqlalchemy import text

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app.models import SessionLocal
from app.pipeline import create_candidate, advance_stage

BASE_URL = "http://127.0.0.1:8000"


def make_request(method: str, path: str, data: dict = None) -> tuple[int, str]:
    url = f"{BASE_URL}{path}"
    headers = {"Content-Type": "application/json"} if data else {}
    body = json.dumps(data).encode("utf-8") if data else None

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def cleanup_all(candidate_ids):
    db = SessionLocal()
    with db.bind.connect() as conn:
        conn.execute(text("ALTER TABLE stage_events DISABLE TRIGGER trg_stage_events_immutable;"))
        for cid in candidate_ids:
            conn.execute(text(f"DELETE FROM stage_events WHERE candidate_id = '{cid}';"))
            conn.execute(text(f"DELETE FROM candidates WHERE id = '{cid}';"))
        conn.execute(text("ALTER TABLE stage_events ENABLE TRIGGER trg_stage_events_immutable;"))
        conn.commit()
    db.close()


def test_step8_frontend_integration():
    print("--- Running Step 8 Candidate Detail & Search Verification ---")
    db = SessionLocal()
    now = datetime.now(timezone.utc)

    # Helper to set initial timestamp
    def set_initial_time(cid, dt):
        with db.bind.connect() as conn:
            conn.execute(text("ALTER TABLE stage_events DISABLE TRIGGER trg_stage_events_immutable;"))
            conn.execute(text(
                f"UPDATE stage_events SET timestamp = '{dt.isoformat()}' WHERE candidate_id = '{cid}';"
            ))
            conn.execute(text("ALTER TABLE stage_events ENABLE TRIGGER trg_stage_events_immutable;"))
            conn.commit()

    created_ids = []

    # Candidate 1: Priya Sharma (Applied 5d ago, Screening 4d ago, Interview 1d ago)
    c1 = create_candidate(db, "Priya Sharma", "priya.sharma@example.com")
    set_initial_time(c1.id, now - timedelta(days=5))
    advance_stage(db, c1.id, "Screening", event_time=now - timedelta(days=4))
    advance_stage(db, c1.id, "Interview", event_time=now - timedelta(days=1))
    created_ids.append(c1.id)

    # Candidate 2: Bob Stuck (Stuck in Screening for 9 days)
    c2 = create_candidate(db, "Bob Stuck", "bob.stuck@example.com")
    set_initial_time(c2.id, now - timedelta(days=12))
    advance_stage(db, c2.id, "Screening", event_time=now - timedelta(days=9))
    created_ids.append(c2.id)

    # Candidate 3: Offer Not Hired (Frank)
    c3 = create_candidate(db, "Frank OfferReject", "frank.offer@example.com")
    set_initial_time(c3.id, now - timedelta(days=20))
    advance_stage(db, c3.id, "Screening", event_time=now - timedelta(days=15))
    advance_stage(db, c3.id, "Interview", event_time=now - timedelta(days=10))
    advance_stage(db, c3.id, "Offer", event_time=now - timedelta(days=5))
    advance_stage(db, c3.id, "Rejected", event_time=now - timedelta(days=2))
    created_ids.append(c3.id)

    # Candidate 4: Hired (Grace)
    c4 = create_candidate(db, "Grace Hired", "grace.hired@example.com")
    set_initial_time(c4.id, now - timedelta(days=15))
    advance_stage(db, c4.id, "Screening", event_time=now - timedelta(days=12))
    advance_stage(db, c4.id, "Interview", event_time=now - timedelta(days=8))
    advance_stage(db, c4.id, "Offer", event_time=now - timedelta(days=4))
    advance_stage(db, c4.id, "Hired", event_time=now - timedelta(days=1))
    created_ids.append(c4.id)

    c1_id = c1.id
    c2_id = c2.id
    c3_id = c3.id
    c4_id = c4.id
    db.close()

    try:
        # Part 1: Verify Candidate Detail Page
        print("\n[Part 1] Verifying Candidate Detail View...")
        status, html = make_request("GET", f"/candidates/{c1_id}")
        assert status == 200, f"Expected 200, got {status}"
        assert "Priya Sharma" in html
        assert "Interview" in html
        assert "Initial Application →" in html
        assert "Screening" in html
        assert "Duration in stage" in html
        print("  PASS: Dedicated candidate detail page rendered correctly with full audit trail.")

        # Also verify Candidate Detail API used by modal
        status, cand_api = make_request("GET", f"/api/candidates/{c1_id}")
        assert status == 200
        cand_obj = json.loads(cand_api)
        assert len(cand_obj["history"]) == 3
        assert cand_obj["history"][0]["to_stage"] == "Applied"
        assert cand_obj["history"][1]["to_stage"] == "Screening"
        assert cand_obj["history"][2]["to_stage"] == "Interview"
        print("  PASS: Candidate Detail API returned complete history in chronological order.")

        # Part 2: Verify Every Search Query from the Brief
        print("\n[Part 2] Testing all brief search queries through live search endpoint...")

        def query(q_text):
            q_enc = urllib.parse.quote(q_text)
            st, res_text = make_request("GET", f"/api/search?q={q_enc}")
            assert st == 200, f"Search failed for '{q_text}'"
            return json.loads(res_text)

        # 1. "Find Priya Sharma"
        r1 = query("Find Priya Sharma")
        assert r1["success"] and len(r1["results"]) > 0
        assert r1["results"][0]["name"] == "Priya Sharma"
        print("  PASS: 'Find Priya Sharma' matched and ranked Priya #1.")

        # 2. "sharam" (typo tolerance)
        r2 = query("sharam")
        assert r2["success"] and len(r2["results"]) > 0
        names = [c["name"] for c in r2["results"]]
        assert "Priya Sharma" in names
        print("  PASS: 'sharam' correctly matched 'Priya Sharma'.")

        # 3. "Who's in Interview right now?"
        r3 = query("Who's in Interview right now?")
        assert r3["success"] and len(r3["results"]) > 0
        stages = [c["current_stage"] for c in r3["results"]]
        assert all(s == "Interview" for s in stages)
        assert any(c["name"] == "Priya Sharma" for c in r3["results"])
        print(f"  PASS: 'Who\\'s in Interview right now?' returned {len(r3['results'])} candidate(s) in Interview.")

        # 4. "Who has been stuck in Screening for more than a week?"
        r4 = query("Who has been stuck in Screening for more than a week?")
        assert r4["success"] and len(r4["results"]) > 0
        assert any(c["name"] == "Bob Stuck" for c in r4["results"])
        print("  PASS: 'Who has been stuck in Screening for more than a week?' correctly matched Bob Stuck.")

        # 5. "Who moved to Interview since Monday?"
        r5 = query("Who moved to Interview since Monday?")
        assert r5["success"]
        print(f"  PASS: 'Who moved to Interview since Monday?' executed successfully ({len(r5['results'])} candidates).")

        # 6. "Who reached the Offer stage but didn't get hired?"
        r6 = query("Who reached the Offer stage but didn't get hired?")
        assert r6["success"] and len(r6["results"]) > 0
        assert any(c["name"] == "Frank OfferReject" for c in r6["results"])
        assert not any(c["name"] == "Grace Hired" for c in r6["results"])
        print("  PASS: 'Who reached the Offer stage but didn't get hired?' matched Frank and excluded Grace.")

        # 7. "Everyone except rejected candidates."
        r7 = query("Everyone except rejected candidates.")
        assert r7["success"] and len(r7["results"]) > 0
        for c in r7["results"]:
            assert c["current_stage"] != "Rejected", f"Found rejected candidate: {c['name']}"
        print("  PASS: 'Everyone except rejected candidates.' cleanly excluded all rejected candidates.")

        # 8. Combined: "Priya in Interview"
        r8 = query("Priya in Interview")
        assert r8["success"] and len(r8["results"]) == 1
        assert r8["results"][0]["name"] == "Priya Sharma"
        print("  PASS: Combined query 'Priya in Interview' matched exactly Priya Sharma.")

        # 9. Invalid stage: "Who's in Onboarding"
        r9 = query("Who's in Onboarding")
        assert not r9["success"]
        assert "'Onboarding' is not a recognized pipeline stage" in r9["explanation"]
        print(f"  PASS: Invalid query 'Who\\'s in Onboarding' returned diagnostic feedback: '{r9['explanation']}'")

        # 10. Empty query
        r10 = query("")
        assert not r10["success"]
        print("  PASS: Empty query returned guidance message.")

        print("\nALL STEP 8 CANDIDATE DETAIL & SEARCH TESTS PASSED SUCCESSFULLY!")

    finally:
        cleanup_all(created_ids)


if __name__ == "__main__":
    test_step8_frontend_integration()
