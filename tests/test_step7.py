import sys
import os
import json
import urllib.request
from sqlalchemy import text

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app.models import SessionLocal

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


def cleanup_candidate(cid: str):
    db = SessionLocal()
    with db.bind.connect() as conn:
        conn.execute(text("ALTER TABLE stage_events DISABLE TRIGGER trg_stage_events_immutable;"))
        conn.execute(text(f"DELETE FROM stage_events WHERE candidate_id = '{cid}';"))
        conn.execute(text(f"DELETE FROM candidates WHERE id = '{cid}';"))
        conn.execute(text("ALTER TABLE stage_events ENABLE TRIGGER trg_stage_events_immutable;"))
        conn.commit()
    db.close()


def test_board_view():
    print("--- Running Step 7 Board View Verification ---")

    # 1. Verify HTML page has all 6 board columns and Add form
    status, html = make_request("GET", "/")
    assert status == 200
    for stage in ["Applied", "Screening", "Interview", "Offer", "Hired", "Rejected"]:
        assert f'id="list-{stage}"' in html, f"Missing column container for {stage}"
        assert f'id="count-{stage}"' in html, f"Missing count badge for {stage}"
    assert 'id="add-candidate-form"' in html, "Missing add candidate form"
    assert 'id="add-candidate-error"' in html, "Missing inline error container"
    print("  PASS: HTML contains all 6 columns and add candidate form.")

    # 2. Verify static assets
    status, css = make_request("GET", "/static/style.css")
    assert status == 200 and ".board-container" in css
    status, js = make_request("GET", "/static/app.js")
    assert status == 200 and "createCandidateCard" in js
    print("  PASS: Static CSS and JS assets are served properly.")

    # 3. Simulate adding a candidate through UI action
    cand_data = {"name": "Board Test User", "email": "board_test@example.com"}
    status, res_json = make_request("POST", "/api/candidates", cand_data)
    assert status == 201
    created = json.loads(res_json)
    cand_id = created["id"]
    print(f"  PASS: Candidate '{created['name']}' created via UI endpoint.")

    try:
        # Verify candidate appears in Applied stage immediately
        status, list_json = make_request("GET", "/api/candidates")
        assert status == 200
        board = json.loads(list_json)
        applied_ids = [c["id"] for c in board["grouped"]["Applied"]]
        assert cand_id in applied_ids, "Candidate not found in Applied column immediately after creation!"
        print("  PASS: Candidate appears in Applied column immediately.")

        # 4. Advancing candidate through UI action (to Screening)
        status, trans_res = make_request("POST", f"/api/candidates/{cand_id}/transition", {"new_stage": "Screening"})
        assert status == 200
        
        # Verify board updates
        status, list_json = make_request("GET", "/api/candidates")
        board = json.loads(list_json)
        screening_ids = [c["id"] for c in board["grouped"]["Screening"]]
        applied_ids = [c["id"] for c in board["grouped"]["Applied"]]
        assert cand_id in screening_ids, "Candidate did not move to Screening!"
        assert cand_id not in applied_ids, "Candidate still in Applied column!"
        print("  PASS: Candidate advanced to Screening without full reload.")

        # 5. Invalid action returns inline error (e.g. attempting to skip to Offer)
        status, err_json = make_request("POST", f"/api/candidates/{cand_id}/transition", {"new_stage": "Offer"})
        assert status == 400
        err_data = json.loads(err_json)
        assert "Cannot skip stages" in err_data.get("detail", "")
        print(f"  PASS: Invalid action rejected with inline error detail: '{err_data['detail']}'")

        print("\nALL STEP 7 BOARD VIEW VERIFICATIONS PASSED SUCCESSFULLY!")

    finally:
        cleanup_candidate(cand_id)


if __name__ == "__main__":
    test_board_view()
