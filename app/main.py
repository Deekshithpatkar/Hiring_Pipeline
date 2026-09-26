import os
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, Depends, HTTPException, Query, Request, status
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.models import init_db, get_db, Candidate
from app.pipeline import (
    create_candidate,
    advance_stage,
    get_candidate_details,
    InvalidTransitionError,
    ORDERED_STAGES,
    ALL_STAGES,
)
from app.search import search_candidates


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database tables and immutability triggers on startup
    init_db()
    yield


app = FastAPI(
    title="Mini Hiring Pipeline",
    description="A minimalist, deterministic hiring pipeline with immutable audit trail and natural search.",
    lifespan=lifespan,
)

# Mount static files and Jinja2 templates
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
static_dir = os.path.join(BASE_DIR, "static")
templates_dir = os.path.join(BASE_DIR, "templates")

if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

templates = Jinja2Templates(directory=templates_dir)


# --- Request Models ---

class CandidateCreateRequest(BaseModel):
    name: str
    email: str


class TransitionRequest(BaseModel):
    new_stage: str


# --- Page Route ---

@app.get("/", summary="Render hiring pipeline board view")
def get_board_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"ordered_stages": ORDERED_STAGES},
    )


@app.get("/candidates/{candidate_id}", summary="Render candidate audit history page")
def get_candidate_page(candidate_id: str, request: Request, db: Session = Depends(get_db)):
    try:
        candidate_data = get_candidate_details(db, candidate_id)
        return templates.TemplateResponse(
            request=request,
            name="candidate_detail.html",
            context={"candidate": candidate_data},
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


# --- API Endpoints (Thin wrappers around pipeline.py and search.py) ---

@app.get("/api/candidates", summary="Get all candidates grouped by stage")
def list_candidates(db: Session = Depends(get_db)):
    """Returns all candidates with their derived current stage and duration, grouped by stage."""
    candidates = db.query(Candidate).all()
    grouped: Dict[str, List[Dict[str, Any]]] = {stage: [] for stage in ORDERED_STAGES}
    grouped["Rejected"] = []

    all_details = []
    for candidate in candidates:
        details = get_candidate_details(db, candidate.id)
        current_stage = details["current_stage"]
        if current_stage in grouped:
            grouped[current_stage].append(details)
        all_details.append(details)

    return {
        "grouped": grouped,
        "total": len(all_details),
        "candidates": all_details,
    }


@app.post(
    "/api/candidates",
    status_code=status.HTTP_201_CREATED,
    summary="Create a new candidate in Applied stage",
)
def api_create_candidate(
    req: CandidateCreateRequest, db: Session = Depends(get_db)
):
    """Creates a new candidate and their initial 'Applied' stage event in one atomic transaction."""
    try:
        candidate = create_candidate(db, req.name, req.email)
        details = get_candidate_details(db, candidate.id)
        return details
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create candidate: {str(e)}",
        )


@app.get("/api/candidates/{candidate_id}", summary="Get candidate detail and audit history")
def api_get_candidate(candidate_id: str, db: Session = Depends(get_db)):
    """Returns candidate profile, derived current stage, and full chronological audit trail."""
    try:
        return get_candidate_details(db, candidate_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@app.post(
    "/api/candidates/{candidate_id}/transition",
    summary="Advance candidate to next stage or reject",
)
def api_transition_candidate(
    candidate_id: str, req: TransitionRequest, db: Session = Depends(get_db)
):
    """Validates state machine rules and transitions candidate to new_stage."""
    try:
        event = advance_stage(db, candidate_id, req.new_stage)
        updated_details = get_candidate_details(db, candidate_id)
        return {
            "success": True,
            "transition": {
                "id": event.id,
                "from_stage": event.from_stage,
                "to_stage": event.to_stage,
                "timestamp": event.timestamp,
            },
            "candidate": updated_details,
        }
    except InvalidTransitionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@app.get("/api/search", summary="Search candidates with natural language filters and typo tolerance")
def api_search_candidates(
    q: str = Query("", description="Free-text query or candidate name"),
    db: Session = Depends(get_db),
):
    """Parses natural language query, evaluates structured filters and fuzzy name match, and ranks results."""
    return search_candidates(db, q)
