import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import json
import urllib.request
import urllib.error
import urllib.parse
from sqlalchemy import text

from app.models import SessionLocal

BASE_URL = "http://127.0.0.1:8000"


def make_request(method: str, path: str, data: dict = None) -> tuple[int, dict]:
    url = f"{BASE_URL}{path}"
    headers = {"Content-Type": "application/json"} if data else {}
    body = json.dumps(data).encode("utf-8") if data else None

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            status = resp.status
            content = resp.read().decode("utf-8")
            try:
                return status, json.loads(content)
            except json.JSONDecodeError:
                return status, {"raw": content}
    except urllib.error.HTTPError as e:
        status = e.code
        content = e.read().decode("utf-8")
        try:
            return status, json.loads(content)
        except json.JSONDecodeError:
            return status, {"raw": content}


def cleanup_candidate(cid: str):
    db = SessionLocal()
    with db.bind.connect() as conn:
        conn.execute(text("ALTER TABLE stage_events DISABLE TRIGGER trg_stage_events_immutable;"))
        conn.execute(text(f"DELETE FROM stage_events WHERE candidate_id = '{cid}';"))
        conn.execute(text(f"DELETE FROM candidates WHERE id = '{cid}';"))
        conn.execute(text("ALTER TABLE stage_events ENABLE TRIGGER trg_stage_events_immutable;"))
        conn.commit()
    db.close()


def test_api_routes():
    print("--- Running Step 6 API Route Verification ---")

    # 1. GET / (HTML Board view)
    status_code, body = make_request("GET", "/")
    assert status_code == 200, f"Expected 200 on /, got {status_code}"
    assert "Mini Hiring Pipeline" in body["raw"], "Page title not found in HTML"
    print("  PASS: GET / returned HTML shell.")

    # 2. GET /docs (FastAPI OpenAPI docs)
    status_code, body = make_request("GET", "/docs")
    assert status_code == 200, f"Expected 200 on /docs, got {status_code}"
    print("  PASS: GET /docs returned OpenAPI documentation UI.")

    # 3. POST /api/candidates (Validation error with empty name)
    status_code, err_body = make_request("POST", "/api/candidates", {"name": "", "email": "test@example.com"})
    assert status_code == 400, f"Expected 400 on empty name, got {status_code}"
    assert "Candidate name cannot be empty" in err_body.get("detail", "")
    print(f"  PASS: POST /api/candidates empty name returned clean 400: '{err_body['detail']}'")

    # 4. POST /api/candidates (Success)
    status_code, created = make_request("POST", "/api/candidates", {"name": "API Test User", "email": "api_test@example.com"})
    assert status_code == 201, f"Expected 201, got {status_code}"
    cand_id = created["id"]
    assert created["name"] == "API Test User"
    assert created["current_stage"] == "Applied"
    print(f"  PASS: POST /api/candidates created candidate ID {cand_id} in Applied stage.")

    try:
        # 5. GET /api/candidates (List & Grouped by stage)
        status_code, list_data = make_request("GET", "/api/candidates")
        assert status_code == 200
        assert "grouped" in list_data
        applied_names = [c["name"] for c in list_data["grouped"]["Applied"]]
        assert "API Test User" in applied_names
        print("  PASS: GET /api/candidates includes new candidate in Applied column.")

        # 6. GET /api/candidates/{id} (Candidate detail & audit history)
        status_code, details = make_request("GET", f"/api/candidates/{cand_id}")
        assert status_code == 200
        assert details["id"] == cand_id
        assert len(details["history"]) == 1
        assert details["history"][0]["to_stage"] == "Applied"
        print("  PASS: GET /api/candidates/{id} returned candidate details and history.")

        # 7. GET /api/candidates/invalid-id (404 Not Found)
        status_code, not_found = make_request("GET", "/api/candidates/00000000-0000-0000-0000-000000000000")
        assert status_code == 404
        assert "does not exist" in not_found.get("detail", "")
        print(f"  PASS: GET non-existent candidate returned clean 404: '{not_found['detail']}'")

        # 8. POST /api/candidates/{id}/transition (Invalid transition: skipping to Interview)
        status_code, invalid_trans = make_request("POST", f"/api/candidates/{cand_id}/transition", {"new_stage": "Interview"})
        assert status_code == 400, f"Expected 400 on invalid transition, got {status_code}"
        assert "Cannot skip stages" in invalid_trans.get("detail", "")
        print(f"  PASS: Invalid transition returned clean 400 JSON: '{invalid_trans['detail']}'")

        # 9. POST /api/candidates/{id}/transition (Valid transition: to Screening)
        status_code, trans_res = make_request("POST", f"/api/candidates/{cand_id}/transition", {"new_stage": "Screening"})
        assert status_code == 200
        assert trans_res["success"] is True
        assert trans_res["transition"]["to_stage"] == "Screening"
        assert trans_res["candidate"]["current_stage"] == "Screening"
        print("  PASS: Valid transition advanced candidate to Screening.")

        # 10. GET /api/search?q=... (Natural search query)
        q = urllib.parse.quote("API Test User")
        status_code, search_res = make_request("GET", f"/api/search?q={q}")
        assert status_code == 200
        assert search_res["success"] is True
        assert len(search_res["results"]) >= 1
        assert search_res["results"][0]["id"] == cand_id
        print("  PASS: GET /api/search returned matching candidate.")

        # 11. GET /api/search?q=Who's in Onboarding (Invalid stage explanation)
        q_inv = urllib.parse.quote("Who's in Onboarding")
        status_code, inv_search_res = make_request("GET", f"/api/search?q={q_inv}")
        assert status_code == 200
        assert inv_search_res["success"] is False
        assert "not a recognized pipeline stage" in inv_search_res["explanation"]
        print(f"  PASS: GET /api/search with invalid stage returned explanation: '{inv_search_res['explanation']}'")

        print("\nALL STEP 6 API ROUTE VERIFICATIONS PASSED SUCCESSFULLY!")

    finally:
        cleanup_candidate(cand_id)


if __name__ == "__main__":
    test_api_routes()
