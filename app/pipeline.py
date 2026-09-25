import uuid
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models import Candidate, StageEvent


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
