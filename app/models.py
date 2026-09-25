import os
import uuid
from datetime import datetime, timezone
from dotenv import load_dotenv
from sqlalchemy import (
    create_engine,
    Column,
    String,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set in environment or .env file.")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


class Candidate(Base):
    __tablename__ = "candidates"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    stage_events = relationship(
        "StageEvent",
        back_populates="candidate",
        order_by="StageEvent.timestamp.asc()",
    )


class StageEvent(Base):
    __tablename__ = "stage_events"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    candidate_id = Column(
        String(36),
        ForeignKey("candidates.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    from_stage = Column(String, nullable=True)
    to_stage = Column(String, nullable=False)
    timestamp = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    candidate = relationship("Candidate", back_populates="stage_events")

    __table_args__ = (
        UniqueConstraint("candidate_id", "to_stage", name="uq_candidate_to_stage"),
    )


TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION prevent_stage_events_modification()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'stage_events audit log is immutable and cannot be updated or deleted';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_stage_events_immutable ON stage_events;
CREATE TRIGGER trg_stage_events_immutable
BEFORE UPDATE OR DELETE ON stage_events
FOR EACH ROW
EXECUTE FUNCTION prevent_stage_events_modification();
"""


def init_db():
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(text(TRIGGER_SQL))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


if __name__ == "__main__":
    init_db()
    print("Database tables and immutability trigger created successfully.")
