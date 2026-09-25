# Mini Hiring Pipeline — Build Spec

## Context
Take-home assignment. A recruiter manages candidates for ONE job through fixed stages.
Graded on: correctness of the state machine, immutability of the audit trail, quality
of the search feature, and clarity of reasoning — NOT on UI polish or feature count.

## Hard constraint: keep code minimal
- No auth, no multi-tenancy, no roles, no notifications, no file uploads, no pagination
  libraries, no state-management libraries, no design system, no animations.
- No confirmation dialogs / "are you sure?" popups for actions the backend
  already validates or rejects (e.g. a duplicate or invalid stage transition).
  An invalid or duplicate action should fail with an inline error message
  (same pattern as search's "tell her why"), not a modal asking permission.
- One job, implicit — do not model "jobs" as an entity.
- Prefer the simplest thing a competent developer would write by hand in a few hours,
  not the most "impressive" or "scalable" thing.
- Do not add features not listed below, even if they seem like natural extensions.
- If you (the AI) are about to add abstraction, config, or a library to handle a case
  that isn't in this spec, stop and ask instead of adding it.

## Stack
- Python backend: FastAPI + Postgres (via SQLAlchemy, using its Core/ORM as the
  data-access layer — keeps SQL close to hand while staying DB-portable).
- Frontend: FastAPI serves plain HTML/CSS + vanilla JS (fetch calls to the API).
  No React, no build step, no frontend framework. Jinja2 templates are fine for
  serving the initial HTML shell.
- This is deliberate: the hiring team is testing Python ability specifically,
  so all core logic (state machine, search parsing, data access) must be in
  Python, not offloaded to JS.
- Postgres connection: assumes a Postgres server is already running (locally
  installed, not containerized). The app reads a connection string from an
  environment variable (e.g. `DATABASE_URL`), with a `.env.example` file
  showing the expected format:
  `postgresql://<user>:<password>@localhost:5432/<database_name>`.
  A one-line setup script or documented `psql` command creates the database
  and runs the schema (Step 1 of the build plan) — no other install required
  beyond Postgres itself.
- Must run with: create the venv, `pip install -r requirements.txt`, copy
  `.env.example` to `.env` and fill in the real Postgres password, then
  `uvicorn app.main:app --reload`. Document all of this clearly in the README,
  including that the grader needs their own Postgres server running locally
  with a matching connection string.

## Data model
Two tables only.

```
Candidate
  id          TEXT (uuid), primary key
  name        TEXT
  email       TEXT
  created_at  DATETIME

StageEvent          -- append-only audit log, NEVER updated or deleted.
                     -- Enforce this with a DB-level rule (e.g. REVOKE UPDATE,
                     -- DELETE ON stage_events, or a BEFORE UPDATE/DELETE trigger
                     -- that raises), not just application-code discipline.
  id            TEXT (uuid), primary key
  candidate_id  TEXT, foreign key -> Candidate
  from_stage    TEXT NULL          -- null for the initial "Applied" event
  to_stage      TEXT
  timestamp     DATETIME
```

A candidate's *current stage* is always derived: the `to_stage` of their latest
StageEvent. Do not store current stage as a separate mutable column — that would
let it drift from the audit log.

## Stage machine
Stages, in order: `Applied → Screening → Interview → Offer → Hired`

Rules (enforce server-side; UI must not be the only guard):
- Forward moves: exactly one stage at a time. No skipping.
- `Rejected` is reachable from any stage EXCEPT `Hired` (that's a terminal state
  you can't reject out of) and except `Rejected` itself.
- `Hired` and `Rejected` are terminal: no further transitions from either.
- No reversal (e.g. Interview → Screening is invalid).
- Every transition attempt that's invalid should return a clear reason string,
  not just a generic 400.

Creating a candidate = writing the Candidate row + one StageEvent
(`from_stage: null, to_stage: 'Applied'`).

## Pages / UI (minimal, functional)
1. **Board view** — candidates grouped by current stage (5 columns:
   Applied/Screening/Interview/Offer/Hired; Rejected candidates shown collapsed
   or in a 6th column). Each card: name, time in current stage. Buttons to
   advance or reject, only shown/enabled when valid from that stage.
2. **Candidate detail view** — full StageEvent history in order, with timestamps
   and computed duration in each stage.
3. **Search box** — single input, results list below, see Search spec.
4. **Add candidate** — simple form (name, email).

No routing library — a handful of FastAPI routes (`/`, `/candidates/{id}`,
`/search`) each returning server-rendered HTML (Jinja2) is enough. No frontend
state management — vanilla JS + fetch for the interactive bits (advance/reject
buttons, live search) is enough at this scale.

## Search
One free-text box. Must handle, and combine:
- Fuzzy name match — typo tolerance (e.g. "sharam" → "Sharma"). Since we're on
  Postgres, either enable the `pg_trgm` extension and use trigram similarity
  (`%` operator / `similarity()`) for this in SQL, or implement a small
  Python-side fuzzy match (Levenshtein or `difflib.SequenceMatcher`) — pick ONE,
  justify in README (pg_trgm is more "real" for a production-minded answer;
  pure Python is more self-contained and easier to explain on camera).
- Current-stage filter ("who's in Interview right now").
- Duration-in-current-stage filter ("stuck in Screening for more than a week").
- Stage-transition-date filter ("moved to Interview since Monday") — read from
  StageEvent timestamps.
- Reached-but-not-current filter ("reached Offer but didn't get hired" = has an
  Offer StageEvent AND current stage != Hired).
- Negation ("everyone except rejected candidates").
- Combinations of the above in one query.
- Ranking: exact/structured matches first, fuzzy name score as tiebreak/secondary.
- Invalid or nonsensical input → return a specific explanation of what wasn't
  understood, never a silent empty array.

Implementation approach: parse the query into detected intents (stage keyword,
relative time phrase, negation, name remainder) with straightforward string/regex
logic — do NOT reach for an LLM call or a heavy NLP library for this. It should
be explainable and debuggable as plain code.

## README run instructions (for later — do not write README yet)
Running instructions must include creating a Python virtual environment before
installing requirements, plus setting up the `.env` file with a real Postgres
password, e.g.:
```
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env          # then edit .env with your local Postgres password
uvicorn app.main:app --reload
```
This goes in the README's "how to run it" section, along with a note that the
grader needs a Postgres server already running locally (with a database
created matching the connection string), and the exact command to create the
schema (Step 1 of the build plan).
- PDF summary of architecture (I'll write this from the README).
- GitHub repo with README: how to run it, decisions made and why, what I'd do
  with more time.
- AI chat logs included in repo.
- One documented disagreement with AI tooling during the build.

## What "done" looks like
- `pip install -r requirements.txt && uvicorn app.main:app --reload` works with
  no manual DB setup (auto-create SQLite file + schema on first run).
- Can add a candidate, advance through stages, get blocked on invalid
  transitions, view history with durations, and run all the example search
  queries from the brief successfully.
- Code is readable in one pass — short files, obvious names, minimal
  indirection. No premature abstraction for hypothetical future stages/jobs.
