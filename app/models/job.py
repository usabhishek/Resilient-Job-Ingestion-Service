import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Text, JSON,
    ForeignKey, UniqueConstraint, Index, func
)
from sqlalchemy.orm import relationship
from app.database import Base

class Job(Base):
    __tablename__ = "jobs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_id = Column(Integer, ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False, index=True)
    external_id = Column(String(255), nullable=False)
    title = Column(String(255), nullable=False)
    company = Column(String(100), nullable=False, index=True)
    location = Column(String(255), nullable=False, default="Remote / Unspecified")
    description = Column(Text, nullable=True)
    job_url = Column(String(1024), nullable=False)
    posted_at = Column(DateTime, nullable=True, index=True)
    raw_payload = Column(JSON, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    updated_at = Column(DateTime, server_default=func.now(), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationship to Source
    source = relationship("Source", back_populates="jobs")

    # Table Constraints & Composite Indexes
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_source_external_id"),
        Index("idx_jobs_source_external", "source_id", "external_id"),
    )

    def __repr__(self) -> str:
        return f"<Job(id='{self.id}', title='{self.title}', company='{self.company}', source_id={self.source_id})>"
