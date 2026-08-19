import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, DateTime, Text, JSON,
    ForeignKey, Index, func
)
from sqlalchemy.orm import relationship
from app.database import Base

class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_id = Column(Integer, ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False, index=True)
    fallback_source_id = Column(Integer, ForeignKey("sources.id", ondelete="SET NULL"), nullable=True)
    trigger_type = Column(String(20), default="MANUAL", nullable=False)
    status = Column(String(30), nullable=False, index=True) # SUCCESS, FALLBACK_SUCCESS, PARTIAL, FAILED, EMPTY_RESPONSE
    started_at = Column(DateTime(timezone=True), server_default=func.now(), default=lambda: datetime.now(timezone.utc), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    duration_ms = Column(Integer, nullable=True)

    fetched_count = Column(Integer, default=0, nullable=False)
    valid_count = Column(Integer, default=0, nullable=False)
    invalid_count = Column(Integer, default=0, nullable=False)
    new_count = Column(Integer, default=0, nullable=False)
    duplicate_count = Column(Integer, default=0, nullable=False)
    failed_count = Column(Integer, default=0, nullable=False)

    error_message = Column(Text, nullable=True)
    error_details = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    # Relationships
    source = relationship("Source", foreign_keys=[source_id], back_populates="runs")
    fallback_source = relationship("Source", foreign_keys=[fallback_source_id])

    def __repr__(self) -> str:
        return f"<IngestionRun(id='{self.id}', status='{self.status}', fetched={self.fetched_count}, new={self.new_count})>"
