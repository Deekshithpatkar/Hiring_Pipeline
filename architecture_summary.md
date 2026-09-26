# Architecture Summary — Mini Hiring Pipeline

**GitHub Repository**: [https://github.com/Deekshithpatkar/Hiring_Pipeline](https://github.com/Deekshithpatkar/Hiring_Pipeline)  
**Author**: Deekshith Patkar  
**Assignment**: Mini Hiring Pipeline  

---

## 1. System Overview & Core Principles

The Mini Hiring Pipeline is designed around three strict principles:
1. **The audit trail is the single source of truth**: No separate mutable `current_stage` column exists. The candidate's current stage is derived dynamically from their latest recorded stage event.
2. **Database-enforced immutability**: Once an audit event is written, it can never be altered or deleted. This is enforced directly at the database engine level by a PostgreSQL trigger.
3. **Deterministic, explainable business logic**: All state machine transitions and search parsing rules are written in plain, readable Python without heavy frameworks, LLM calls, or unpredictable NLP abstractions.

---

## 2. Architecture Diagram

```
+-------------------------------------------------------------------------+
|                           CLIENT LAYER                                  |
|  - Vanilla HTML5 / CSS / JavaScript (fetch API)                         |
|  - Kanban Board View with 6 Stage Columns (Count Badges)                |
|  - Real-Time Debounced Natural Language Search Box                      |
|  - Interactive Candidate History Timeline Modal & Deep-Link Pages       |
|  - Strict Inline Error Messaging (Zero Modals / Dialog Popups)          |
+------------------------------------+------------------------------------+
                                     | HTTP REST & Static Assets
                                     v
+-------------------------------------------------------------------------+
|                        APPLICATION LAYER (FastAPI)                      |
|  - app/main.py: Thin route handlers & Jinja2 Template Serving           |
|  - OpenAPI Documentation at /docs                                       |
+--------------------+-------------------------------+--------------------+
                     |                               |
                     v                               v
+----------------------------------+ +------------------------------------+
|  STATE MACHINE (app/pipeline.py) | |   SEARCH ENGINE (app/search.py)    |
|  - create_candidate (Atomic Tx)  | |  - Rule-based regex intent parser  |
|  - advance_stage (State Machine) | |  - Relative time & date resolver   |
|  - get_history (Duration Math)   | |  - Typo tolerance (difflib 0.75)   |
|  - get_candidate_details         | |  - Diagnostic explanation engine   |
+--------------------+-------------+ +--------------------+---------------+
                     |                                    |
                     +-----------------+------------------+
                                       | SQLAlchemy ORM
                                       v
+-------------------------------------------------------------------------+
|                        DATABASE LAYER (PostgreSQL)                      |
|                                                                         |
|  TABLE: candidates                                                      |
|    - id (UUID PK)                                                       |
|    - name (TEXT)                                                        |
|    - email (TEXT)                                                       |
|    - created_at (TIMESTAMPTZ)                                           |
|                                                                         |
|  TABLE: stage_events (APPEND-ONLY AUDIT LOG)                            |
|    - id (UUID PK)                                                       |
|    - candidate_id (FK -> candidates.id, RESTRICT)                       |
|    - from_stage (TEXT NULL)                                             |
|    - to_stage (TEXT)                                                    |
|    - timestamp (TIMESTAMPTZ)                                            |
|    - CONSTRAINT uq_candidate_to_stage (candidate_id, to_stage UNIQUE)   |
|    - TRIGGER trg_stage_events_immutable (BEFORE UPDATE/DELETE RAISE)   |
+-------------------------------------------------------------------------+
```

---

## 3. Data Model & Immutability Guarantees

### Schema
- `candidates`: Primary demographic and timestamp information.
- `stage_events`: Append-only audit trail logging every stage transition (`from_stage → to_stage`).

### Immutability Trigger (PostgreSQL PL/pgSQL)
```sql
CREATE OR REPLACE FUNCTION prevent_stage_events_modification()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'stage_events audit log is immutable and cannot be updated or deleted';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_stage_events_immutable
BEFORE UPDATE OR DELETE ON stage_events
FOR EACH ROW
EXECUTE FUNCTION prevent_stage_events_modification();
```
* **Why**: Application-level discipline is insufficient for audit compliance. The trigger guarantees that even if a raw SQL query or admin tool executes an `UPDATE` or `DELETE`, PostgreSQL immediately aborts the transaction.

### Preventing Duplicate Events
The uniqueness constraint `uq_candidate_to_stage (candidate_id, to_stage)` ensures that a candidate can never enter the same stage twice, preserving a strictly linear progression.

---

## 4. State Machine Implementation

The pipeline enforces the sequence:
$$\text{Applied} \longrightarrow \text{Screening} \longrightarrow \text{Interview} \longrightarrow \text{Offer} \longrightarrow \text{Hired}$$

### Transition Rules
1. **Forward Moves**: Must move forward by exactly one stage at a time. Skipping stages (e.g. `Applied → Interview`) is strictly forbidden and returns an explanatory message.
2. **Reversals**: Moving backwards (e.g. `Interview → Screening`) is disallowed.
3. **Rejections**: `Rejected` can be reached from any non-terminal stage (`Applied`, `Screening`, `Interview`, `Offer`).
4. **Terminal States**: Both `Hired` and `Rejected` are terminal states; no further transitions can occur from either.
5. **Inline Error Handling**: Invalid attempts return a clear `400 Bad Request` with an exact explanation (e.g. *"Cannot skip stages. Next valid forward stage from 'Applied' is 'Screening', not 'Interview'."*), which the frontend renders inline without intrusive confirmation popups.

---

## 5. Search Engine & Ranking

The search system parses free-text queries using deterministic, modular Python components:

1. **Intent & Entity Extraction**:
   - **Stages**: Case-insensitive matching against valid pipeline stages.
   - **Relative Time**: Converts phrases like `"more than a week"`, `"2 days"`, `"an hour"` into exact elapsed seconds.
   - **Transition Dates**: Resolves relative days like `"since Monday"`, `"yesterday"` into UTC timestamps.
   - **Negative Filters**: Detects negation words (`"except"`, `"excluding"`, `"not in"`) to invert filter criteria.
   - **Reached-but-not-current**: Recognizes patterns like `"reached Offer but didn't get hired"` to inspect candidate event history against their current stage.
2. **Typo Tolerance & Fuzzy Matching**:
   - Token-level and full-string similarity matching via Python's standard library `difflib.SequenceMatcher`.
   - Threshold set to $\ge 0.75$, allowing common typos like `"sharam" \rightarrow "Sharma"` while preventing false positives.
3. **Ranking**:
   - Exact matches scored highest, followed by fuzzy matches and timestamp tiebreaks.
4. **Diagnostic Explanations**:
   - When a recruiter enters an unrecognized stage (e.g. `"Who's in Onboarding"`), the engine explains:
     `"'Onboarding' is not a recognized pipeline stage. Valid pipeline stages are: Applied, Screening, Interview, Offer, Hired, Rejected."`
   - Rather than returning a silent empty list, every unrecognized or empty query returns actionable feedback.

---

## 6. Verification & Test Coverage

The project includes automated verification test suites for every step in `tests/`:
- `test_step1.py`: Table existence, trigger rejection of `UPDATE`/`DELETE`, and duplicate rejection.
- `test_step2.py`: Atomic candidate creation and rollback verification.
- `test_step3.py`: Valid progression and full rejection of skipping, reversals, and terminal moves.
- `test_step4.py`: Audit history ordering and dynamic elapsed duration calculations.
- `test_step5.py`: All 5 search sub-steps (stages, durations, transition dates, typo tolerance, diagnostics).
- `test_step6.py`: Thin FastAPI endpoint request/response contracts and OpenAPI docs.
- `test_step7.py`: Dynamic Kanban board view, live card movements, and inline error rendering.
- `test_step8.py`: Complete candidate detail audit views and live search query execution.
