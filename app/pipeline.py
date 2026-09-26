import uuid
from typing import Optional, List, Dict, Any
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


def _ensure_utc(dt: datetime) -> datetime:
    """Ensures a datetime object is timezone-aware UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_duration(seconds: float) -> str:
    """Formats a duration in seconds into a clean, human-readable string."""
    if seconds < 0:
        return "0s"
    
    total_seconds = int(round(seconds))
    if total_seconds < 60:
        return f"{total_seconds}s"
    
    minutes = total_seconds // 60
    if minutes < 60:
        rem_sec = total_seconds % 60
        return f"{minutes}m {rem_sec}s" if rem_sec > 0 else f"{minutes}m"
    
    hours = minutes // 60
    rem_min = minutes % 60
    if hours < 24:
        return f"{hours}h {rem_min}m" if rem_min > 0 else f"{hours}h"
    
    days = hours // 24
    rem_hours = hours % 24
    if days < 7:
        return f"{days}d {rem_hours}h" if rem_hours > 0 else f"{days}d"
    
    weeks = days // 7
    rem_days = days % 7
    return f"{weeks}w {rem_days}d" if rem_days > 0 else f"{weeks}w"


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


def advance_stage(
    db: Session, candidate_id: str, new_stage: str, event_time: Optional[datetime] = None
) -> StageEvent:
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

    timestamp = _ensure_utc(event_time or datetime.now(timezone.utc))
    new_event = StageEvent(
        id=str(uuid.uuid4()),
        candidate_id=candidate_id,
        from_stage=current_stage,
        to_stage=new_stage,
        timestamp=timestamp,
    )

    try:
        db.add(new_event)
        db.commit()
        db.refresh(new_event)
        return new_event
    except Exception:
        db.rollback()
        raise


def get_history(
    db: Session, candidate_id: str, as_of: Optional[datetime] = None
) -> List[Dict[str, Any]]:
    """
    Returns all stage_events for a candidate in chronological order,
    with computed duration in each stage (and duration in current stage
    computed against as_of or current time).
    """
    candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate:
        raise ValueError(f"Candidate with ID '{candidate_id}' does not exist.")

    events = (
        db.query(StageEvent)
        .filter(StageEvent.candidate_id == candidate_id)
        .order_by(StageEvent.timestamp.asc(), StageEvent.id.asc())
        .all()
    )

    if not events:
        return []

    now = _ensure_utc(as_of or datetime.now(timezone.utc))
    history: List[Dict[str, Any]] = []
    total_events = len(events)

    for i, event in enumerate(events):
        event_time = _ensure_utc(event.timestamp)
        is_current = (i == total_events - 1)

        if not is_current:
            next_event_time = _ensure_utc(events[i + 1].timestamp)
            duration_sec = max(0.0, (next_event_time - event_time).total_seconds())
        else:
            duration_sec = max(0.0, (now - event_time).total_seconds())

        history.append({
            "id": event.id,
            "candidate_id": event.candidate_id,
            "from_stage": event.from_stage,
            "to_stage": event.to_stage,
            "timestamp": event_time,
            "duration_seconds": duration_sec,
            "duration_human": format_duration(duration_sec),
            "is_current": is_current,
        })

    return history


def get_candidate_details(
    db: Session, candidate_id: str, as_of: Optional[datetime] = None
) -> Dict[str, Any]:
    """Returns candidate info together with their full stage history and current status."""
    candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate:
        raise ValueError(f"Candidate with ID '{candidate_id}' does not exist.")

    history = get_history(db, candidate_id, as_of=as_of)
    current_event = history[-1] if history else None
    current_stage = current_event["to_stage"] if current_event else "Unknown"
    time_in_stage_sec = current_event["duration_seconds"] if current_event else 0.0
    time_in_stage_human = current_event["duration_human"] if current_event else "0s"

    return {
        "id": candidate.id,
        "name": candidate.name,
        "email": candidate.email,
        "created_at": _ensure_utc(candidate.created_at),
        "current_stage": current_stage,
        "time_in_current_stage_seconds": time_in_stage_sec,
        "time_in_current_stage_human": time_in_stage_human,
        "allowed_next_stages": get_allowed_next_stages(current_stage),
        "history": history,
    }
