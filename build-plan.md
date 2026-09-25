# Build plan — Mini Hiring Pipeline

Work through these steps in order. Do NOT let Antigravity generate the whole
app in one pass. Give it one step at a time, run the verification for that
step, confirm it passes, THEN move to the next step. If a step's verification
fails, fix that step before proceeding — do not build on top of a broken step.

Reference `spec.md` for the full requirements each step below draws from.

---

## Step 0 — Environment setup
**Build:**
- Create a Python virtual environment.
- Create `requirements.txt` with: fastapi, uvicorn, sqlalchemy, psycopg2-binary
  (or asyncpg if going async), jinja2, python-multipart, python-dotenv.
- Create a `.env.example` file with:
  `DATABASE_URL=postgresql://<user>:<password>@localhost:5432/hiring_pipeline`
- Copy it to `.env` and fill in your real local Postgres username/password.
- Manually create the database in your already-running local Postgres, e.g.:
  `createdb hiring_pipeline` (or via `psql`: `CREATE DATABASE hiring_pipeline;`)
- Create the project folder structure:
  ```
  app/
    main.py          # FastAPI routes only
    models.py         # SQLAlchemy table definitions
    pipeline.py        # state machine logic (create, advance, history)
    search.py          # search parsing + ranking logic
    templates/          # Jinja2 HTML
    static/             # a bit of vanilla JS/CSS
  requirements.txt
  .env.example
  ```

**Verify:**
- [ ] `python -m venv venv && source venv/bin/activate && pip install -r requirements.txt` completes with no errors
- [ ] `createdb hiring_pipeline` (or equivalent) succeeds against your local Postgres
- [ ] The app can read `DATABASE_URL` from `.env` and successfully open a
      connection to that database (a simple `SELECT 1` test is enough)

---

## Step 1 — Database schema
**Build:**
- Define the two tables in `models.py`: `candidates` and `stage_events`, exactly
  as specified (append-only `stage_events`, no `current_stage` column anywhere).
- Add the DB-level guard against editing/deleting `stage_events` rows (a
  `REVOKE UPDATE, DELETE` or a trigger).
- Add the uniqueness rule discussed: a candidate cannot have two events with
  the same `to_stage`.
- A simple script or Alembic migration to create these tables on startup.

**Verify:**
- [ ] Tables exist in Postgres after running the setup script (`\dt` in psql)
- [ ] Manually try an `UPDATE` or `DELETE` on a `stage_events` row (with a test
      row inserted) — it must be rejected by the database itself, not just by
      your Python code
- [ ] Manually try inserting two `stage_events` rows for the same candidate
      with the same `to_stage` — the second insert must fail

---

## Step 2 — Candidate creation
**Build:**
- `create_candidate(name, email)` in `pipeline.py`: inserts into `candidates`
  AND inserts the initial `Applied` event into `stage_events`, in one
  transaction.

**Verify:**
- [ ] Calling this function creates exactly one row in `candidates` and exactly
      one row in `stage_events` (`from_stage = NULL`, `to_stage = 'Applied'`)
- [ ] If you force the second insert to fail (e.g. temporarily break it), the
      first insert also rolls back — no orphaned candidate with no stage
- [ ] Write this as an actual small test, not just a manual check, if time allows

---

## Step 3 — Stage transitions (the state machine)
**Build:**
- `get_current_stage(candidate_id)` — derives current stage from the latest
  `stage_events` row.
- `advance_stage(candidate_id, new_stage)` — validates against the allowed-
  transitions map, then inserts (never updates) into `stage_events`.
- Clear, specific error messages for every invalid case (skipping a stage,
  moving from a terminal stage, moving backwards, duplicate stage).

**Verify:**
- [ ] Valid path works end to end: Applied → Screening → Interview → Offer → Hired
- [ ] Each of these is correctly rejected, with a clear reason:
  - Applied → Interview (skipping Screening)
  - Interview → Screening (going backwards)
  - Hired → anything (terminal state)
  - Rejected → anything (terminal state)
  - Rejected from every non-terminal stage IS allowed — confirm this works
  - Same transition submitted twice in a row (duplicate)
- [ ] Write these as actual test cases, not just manual clicking — this is the
      part most likely to be scrutinized closely

---

## Step 4 — Candidate history / audit trail view
**Build:**
- `get_history(candidate_id)` — returns all `stage_events` for a candidate, in
  order, with a computed "time in this stage" for each entry (and "time in
  current stage" for the most recent one, computed against now).

**Verify:**
- [ ] A candidate who has moved through 3 stages shows all 3 events, in
      correct order, with correct durations
- [ ] "Time in current stage" updates correctly as time passes (test by
      checking the math against a known timestamp, not just eyeballing it)

---

## Step 5 — Search parsing and ranking
Build this in isolated pieces — do not let it become one giant function.

**Build (sub-step 5a — stage + negation detection):**
- Detect stage names in the query string.
- Detect negation words ("except," "didn't," "not," "but") and flip the
  relevant filter.

**Verify 5a:**
- [ ] "who's in Interview" → filters to current_stage = Interview
- [ ] "everyone except rejected candidates" → filters to current_stage != Rejected

**Build (sub-step 5b — time phrase detection):**
- Detect relative time phrases ("more than a week," "since Monday") and turn
  them into actual date comparisons.

**Verify 5b:**
- [ ] "stuck in Screening for more than a week" → current_stage = Screening AND
      time_in_stage > 7 days
- [ ] "moved to Interview since Monday" → has a stage_event with to_stage =
      Interview AND timestamp > last Monday's date

**Build (sub-step 5c — "reached but not current" detection):**
- Detect phrasing like "reached Offer but didn't get hired."

**Verify 5c:**
- [ ] Correctly finds candidates with an Offer event whose current stage != Hired

**Build (sub-step 5d — fuzzy name matching):**
- Whatever text is left after removing stage/time/negation words is treated
  as a name query, matched with typo tolerance.

**Verify 5d:**
- [ ] "sharam" correctly matches a candidate named "Sharma"
- [ ] An exact name match ranks above a fuzzy match

**Build (sub-step 5e — combining + ranking + invalid input):**
- Run all detected filters together (AND).
- Score/rank results, best match first.
- If something in the query isn't understood (e.g. a stage name that doesn't
  exist), return a clear explanation instead of an empty result.

**Verify 5e:**
- [ ] A combined query (e.g. a name + a stage) returns correctly filtered and
      ranked results
- [ ] "who's in Onboarding" (not a real stage) returns an explanation, not an
      empty list
- [ ] Every example query listed in the brief works correctly — go through
      them one by one

---

## Step 6 — API routes
**Build:**
- Thin FastAPI routes wrapping the functions from Steps 2, 3, 4, 5. Routes
  should contain no business logic themselves — just call into `pipeline.py`
  / `search.py` and handle request/response shape.

**Verify:**
- [ ] Every route works via a manual request (curl, or FastAPI's built-in
      `/docs` page) before touching the frontend at all
- [ ] Error cases (invalid transition, unrecognized search term) return a
      clear JSON error, not a raw 500

---

## Step 7 — Frontend (board view)
**Build:**
- One page showing candidates grouped by current stage.
- Advance/reject buttons per candidate, disabled or hidden when not valid
  from that stage.
- "Add candidate" form.

**Verify:**
- [ ] Adding a candidate through the UI shows them under Applied immediately
- [ ] Advancing/rejecting through the UI updates the board without a full
      page reload feeling clunky (a simple fetch + re-render is enough)
- [ ] Invalid actions are not even clickable, or show the backend's error
      message inline — no confirmation popups

---

## Step 8 — Frontend (candidate detail + search)
**Build:**
- Clicking a candidate opens their history view with durations.
- The search box, wired to the search route, showing ranked results and
  linking into candidate detail.

**Verify:**
- [ ] History view matches what Step 4 returns, readable and in order
- [ ] Every example search query from the brief works correctly through the
      actual UI, not just the API

---

## Step 9 — Final pass
**Build:**
- Nothing new — only cleanup. Remove dead code, check for anything added
  beyond the spec (no confirmation dialogs, no extra entities, no unused
  libraries).

**Verify:**
- [ ] From a clean clone: venv + `pip install` + `.env` setup + `uvicorn` works
      with no steps beyond what's documented in the README
- [ ] Full run-through: add a candidate, move them through every valid stage,
      hit a couple of invalid transitions, run 5+ example searches from the
      brief, open a candidate's history

---

## After this plan — not part of it yet
- README (how to run it, decisions + why, what you'd do with more time,
  including the venv creation step)
- Architecture summary PDF
- Export AI chat logs
- Identify and document one real AI disagreement from the build process
- Rehearse the 12-minute demo before the real recording
