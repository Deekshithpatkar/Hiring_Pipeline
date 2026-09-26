# Mini Hiring Pipeline

A focused, robust, minimal web application for recruiters to manage candidates for a job through a deterministic hiring pipeline, view an immutable audit history with stage durations, and search candidates using natural language filters and typo-tolerant name matching.

Built for the take-home technical assignment with strict constraints: minimal code, zero premature abstractions, no heavyweight frontend frameworks, and rock-solid state machine and database guarantees.

---

## Architecture Overview

```
                      +---------------------------------------+
                      |   Browser UI (HTML5 / Vanilla JS)     |
                      |   Board, Live Search, Audit Modal     |
                      +-------------------+-------------------+
                                          | Fetch JSON / HTML
                                          v
                      +---------------------------------------+
                      |       FastAPI Web Layer (main.py)     |
                      |    Thin endpoints, Jinja2 Shell       |
                      +---------+-------------------+---------+
                                |                   |
               State Machine    v                   v    Natural Search
        +----------------------------+     +----------------------------+
        |     pipeline.py            |     |     search.py              |
        | - Atomic Candidate Create  |     | - Rule-based intent parser |
        | - Validated Stage Advance  |     | - Relative time filters    |
        | - Derived Stage & Duration |     | - Typo-tolerant matcher    |
        +---------------+------------+     +----------------------------+
                        |
                        v SQLAlchemy ORM
        +---------------------------------------------------------------+
        |                    PostgreSQL Database                        |
        |  1. candidates (id, name, email, created_at)                  |
        |  2. stage_events (id, candidate_id, from, to, timestamp)      |
        |     * Immutable: Enforced by Postgres BEFORE trigger          |
        |     * Unique: (candidate_id, to_stage) constraint             |
        +---------------------------------------------------------------+
```

---

## Key Architectural Decisions & Why

### 1. Fully Derived Stage from an Append-Only Audit Log
* **Decision**: We do **not** store a `current_stage` column in the `candidates` table. Instead, a candidate's current stage is always derived as the `to_stage` of their latest `StageEvent`.
* **Why**: Having a mutable `current_stage` column alongside an audit log introduces the risk of state drift (e.g. if one updates and the other fails). By making `stage_events` the single source of truth, the audit log and current stage can never fall out of sync.

### 2. Database-Level Immutability Enforcement
* **Decision**: Immutability is enforced at the database level using a PostgreSQL `BEFORE UPDATE OR DELETE` trigger on `stage_events` that raises an exception, in addition to application-level discipline.
* **Why**: Relying solely on application code for audit trail integrity is fragile—anyone connecting via a database console, admin script, or ORM could alter history. A trigger guarantees that once an audit event is written, it cannot be edited or deleted by anyone.

### 3. Server-Side Deterministic State Machine
* **Decision**: Transitions (`Applied → Screening → Interview → Offer → Hired`) are strictly enforced server-side. Skipping stages, reversing stages, or moving out of terminal states (`Hired`, `Rejected`) is rejected with clear, explanatory error messages.
* **Why**: Client-side UI checks are easily bypassed. Clear server-side validation messages (e.g., *"Cannot skip stages. Next valid forward stage from 'Applied' is 'Screening', not 'Interview'."*) allow the frontend to display inline feedback to the recruiter without needing modal permission popups.

### 4. Deterministic, Explainable Search (No LLMs / Heavy NLP)
* **Decision**: Search uses a rule-based parser in pure Python (regex + structured intent matching + `difflib.SequenceMatcher`).
* **Why**: LLM-based search or heavy NLP libraries introduce latency, API costs, hallucinations, and non-deterministic behavior. Our rule-based parser is 100% deterministic, runs in under 1 millisecond, handles typo tolerance (e.g. `"sharam"` -> `"Sharma"`), relative timeframes (`"stuck in Screening for more than a week"`, `"moved to Interview since Monday"`), negations (`"everyone except rejected"`), and explicitly explains unrecognized inputs (e.g. `'Onboarding' is not a recognized pipeline stage`).

### 5. Vanilla Frontend with Zero Build Steps
* **Decision**: Plain HTML5, vanilla CSS, and vanilla JS (`fetch`). Jinja2 serves the initial shell.
* **Why**: Eliminates build-tool complexity (npm, webpack, node_modules), loads instantaneously, and keeps all business logic in Python where it is easily testable and inspectable.

---

## AI Collaboration & Disagreement

**Where I disagreed with the AI**:
During the initial build phase (Step 1), the AI began placing test verification scripts (`verify_step1.py`, `test_db_connection.py`) directly into the project root directory alongside the core source code. 

I intervened and disagreed with cluttering the root directory with one-off test scripts:
1. I instructed the AI to consolidate all test and verification files into a dedicated `tests/` directory.
2. I requested adding `tests/` to `.gitignore` so that only clean production source code (`app/`, `requirements.txt`, `.env.example`, etc.) is tracked in Git.

This kept the repository clean, professional, and easy to grade without temporary verification artifacts cluttering the project structure.

---

## Prerequisites

1. **Python**: Python 3.10+ (tested on Python 3.14).
2. **PostgreSQL**: A running PostgreSQL server (local installation).
3. A database named `hiring_pipeline` created in your local Postgres:
   ```sql
   CREATE DATABASE hiring_pipeline;
   ```

---

## How to Run It Locally

### Step 1. Clone the Repository & Enter Directory
```bash
git clone https://github.com/Deekshithpatkar/Hiring_Pipeline.git
cd Hiring_Pipeline
```

### Step 2. Create and Activate Virtual Environment
```bash
# Windows
python -m venv venv
.\venv\Scripts\activate

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

### Step 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 4. Configure Environment Variables
Copy `.env.example` to `.env` and update it with your local PostgreSQL credentials:
```bash
# Windows
copy .env.example .env

# macOS / Linux
cp .env.example .env
```

Edit `.env` with your actual Postgres username and password:
```env
DATABASE_URL=postgresql+psycopg2://postgres:your_password@localhost:5432/hiring_pipeline
```

### Step 5. Run the Application
```bash
uvicorn app.main:app --reload
```

The database tables (`candidates`, `stage_events`) and PostgreSQL immutability trigger are automatically created on first startup!

Open your browser to:
- **Board UI**: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- **Interactive OpenAPI Documentation**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

---

## What I'd Do With More Time

1. **Multi-Job & Requisition Support**: Extend data model to support multiple active job postings with customizable stage sequences per department.
2. **Candidate Resumes & Attachments**: Integrate local or S3 object storage for PDF resume uploads, parsing candidate skills, and indexing resume text.
3. **Database-level Trigram Search (`pg_trgm`)**: Enable PostgreSQL `pg_trgm` extension for sub-millisecond similarity queries across millions of candidate records.
4. **WebSocket Real-Time Board Updates**: Stream pipeline updates so multiple recruiters collaborating on the same job see live card movements without polling.
5. **Interview Scheduling & Calendar Sync**: Wire direct Google Calendar / Outlook integration for interview stage transitions.
6. **Audit Export & Compliance**: Provide one-click GDPR/EEOC audit log export in PDF/CSV format with cryptographic hash verification of event immutability.
