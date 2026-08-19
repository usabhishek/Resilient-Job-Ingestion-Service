from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Boolean, Float, DateTime, func
from sqlalchemy.orm import relationship
from app.database import Base

class Source(Base):
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(50), unique=True, nullable=False, index=True)
    slug = Column(String(50), unique=True, nullable=False)
    base_url = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    rate_limit_rps = Column(Float, default=2.0, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    jobs = relationship("Job", back_populates="source", cascade="all, delete-orphan")
    runs = relationship("IngestionRun", foreign_keys="[IngestionRun.source_id]", back_populates="source")

    def __repr__(self) -> str:
        return f"<Source(id={self.id}, name='{self.name}', active={self.is_active})>"
