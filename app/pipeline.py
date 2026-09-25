import uuid
from typing import Optional, List
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import desc
from app.models import Candidate, StageEvent

ORDERED_STAGES: List[str] = ["Applied", "Screening", "Interview", "Offer", "Hired"]
TERMINAL_STAGES = {"Hired", "Rejected"}
ALL_STAGES = set(ORDERED_STAGES) | {"Rejected"}


class InvalidTransitionError(ValueError):
    """Raised when an invalid stage transition is attempted."""
    pass


def create_candidate(db: Session, name: str, email: str) -> Candidate:
    """Creates a new candidate and their initial 'Applied' stage event in one atomic transaction."""
    name = (name or "").strip()
    email = (email or "").strip()

    if not name:
        raise ValueError("Candidate name cannot be empty.")
    if not email:
        raise ValueError("Candidate email cannot be empty.")

    now = datetime.now(timezone.utc)
    candidate_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())

    candidate = Candidate(
        id=candidate_id,
        name=name,
        email=email,
        created_at=now,
    )

    initial_event = StageEvent(
        id=event_id,
        candidate_id=candidate_id,
        from_stage=None,
        to_stage="Applied",
        timestamp=now,
    )

    try:
        db.add(candidate)
        db.add(initial_event)
        db.commit()
        db.refresh(candidate)
        return candidate
    except Exception:
        db.rollback()
        raise


def get_latest_event(db: Session, candidate_id: str) -> Optional[StageEvent]:
    """Returns the most recent StageEvent for a candidate."""
    return (
        db.query(StageEvent)
        .filter(StageEvent.candidate_id == candidate_id)
        .order_by(desc(StageEvent.timestamp), desc(StageEvent.id))
        .first()
    )


def get_current_stage(db: Session, candidate_id: str) -> str:
    """Derives current stage from the candidate's latest StageEvent."""
    latest_event = get_latest_event(db, candidate_id)
    if not latest_event:
        # Check if candidate exists to give the right error
        candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
        if not candidate:
            raise ValueError(f"Candidate with ID '{candidate_id}' does not exist.")
        raise ValueError(f"Candidate '{candidate_id}' has no stage events recorded.")
    return latest_event.to_stage


def get_allowed_next_stages(current_stage: str) -> List[str]:
    """Returns a list of valid next stages from current_stage."""
    if current_stage in TERMINAL_STAGES:
        return []
    
    allowed = []
    if current_stage in ORDERED_STAGES:
        idx = ORDERED_STAGES.index(current_stage)
        if idx + 1 < len(ORDERED_STAGES):
            allowed.append(ORDERED_STAGES[idx + 1])
    
    # Rejected is reachable from any stage except Hired and Rejected itself
    if current_stage != "Hired" and current_stage != "Rejected":
        allowed.append("Rejected")

    return allowed


def advance_stage(db: Session, candidate_id: str, new_stage: str) -> StageEvent:
    """
    Validates and advances a candidate to new_stage.
    Appends a new StageEvent to the audit trail.
    Raises InvalidTransitionError with a specific explanation if invalid.
    """
    new_stage = (new_stage or "").strip()
    if new_stage not in ALL_STAGES:
        raise InvalidTransitionError(f"'{new_stage}' is not a recognized pipeline stage.")

    current_stage = get_current_stage(db, candidate_id)

    # Check if current stage is terminal
    if current_stage in TERMINAL_STAGES:
        raise InvalidTransitionError(
            f"Cannot advance candidate from terminal stage '{current_stage}'."
        )

    # Check duplicate transition
    if new_stage == current_stage:
        raise InvalidTransitionError(
            f"Candidate is already in '{current_stage}' stage."
        )

    # Moving to Rejected is allowed from any non-terminal stage
    if new_stage == "Rejected":
        pass
    else:
        # Check forward moves along ORDERED_STAGES
        current_idx = ORDERED_STAGES.index(current_stage)
        new_idx = ORDERED_STAGES.index(new_stage)

        if new_idx < current_idx:
            raise InvalidTransitionError(
                f"Cannot move backwards from '{current_stage}' to '{new_stage}'. Reversing stages is not permitted."
            )

        if new_idx > current_idx + 1:
            expected_next = ORDERED_STAGES[current_idx + 1]
            raise InvalidTransitionError(
                f"Cannot skip stages. Next valid forward stage from '{current_stage}' is '{expected_next}', not '{new_stage}'."
            )

    now = datetime.now(timezone.utc)
    new_event = StageEvent(
        id=str(uuid.uuid4()),
        candidate_id=candidate_id,
        from_stage=current_stage,
        to_stage=new_stage,
        timestamp=now,
    )

    try:
        db.add(new_event)
        db.commit()
        db.refresh(new_event)
        return new_event
    except Exception:
        db.rollback()
        raise
