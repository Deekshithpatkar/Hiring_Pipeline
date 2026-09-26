# AI Chat Logs

This folder contains the complete, unaltered AI conversation logs from the development of the Mini Hiring Pipeline project with Google Antigravity.

## Contents
- **`transcript.jsonl`**: The raw, chronological JSON-lines trajectory log of all user prompts, agent reasoning, tool executions, and step-by-step verification milestones.

## Build Steps Trajectory
1. **Step 0**: Environment setup (Python 3.14 venv, dependencies, PostgreSQL connection verification).
2. **Step 1**: Database schema definition (`candidates`, `stage_events`), Postgres trigger for append-only immutability, uniqueness constraints.
3. **Step 2**: Candidate creation logic with atomic transaction guarantees in `pipeline.py`.
4. **Step 3**: Stage machine state transitions (`Applied → Screening → Interview → Offer → Hired`) and specific rejection error strings.
5. **Step 4**: Candidate audit trail history computation with exact stage durations.
6. **Step 5**: Rule-based natural language search parser (typo tolerance, relative timeframes, negations, combinations, ranking, and invalid input feedback).
7. **Step 6**: FastAPI thin REST endpoints and OpenAPI documentation.
8. **Step 7**: Vanilla HTML/CSS/JS frontend board view with dynamic columns and inline error reporting.
9. **Step 8**: Candidate detail history modal, dedicated deep-link pages, and live search integration.
10. **Step 9**: End-to-end verification, cleanup, and documentation.
