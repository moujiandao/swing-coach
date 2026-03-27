import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, Enum as SAEnum, Float, Integer, JSON, String, Text, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from pydantic import BaseModel, ConfigDict, field_serializer


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class AnalysisStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class StrokeType(str, enum.Enum):
    forehand = "forehand"
    backhand_one = "backhand_one"
    backhand_two = "backhand_two"
    serve_flat = "serve_flat"
    serve_kick = "serve_kick"
    serve_slice = "serve_slice"
    volley = "volley"


# ---------------------------------------------------------------------------
# SQLAlchemy ORM model
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[AnalysisStatus] = mapped_column(
        SAEnum(AnalysisStatus, name="analysisstatus", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=AnalysisStatus.pending,
    )
    stroke_type: Mapped[StrokeType] = mapped_column(
        SAEnum(StrokeType, name="stroketype", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    video_s3_key: Mapped[str] = mapped_column(String(512), nullable=False)
    pro_reference: Mapped[str] = mapped_column(String(255), nullable=False)

    # Pipeline output fields — all nullable until processing completes
    pose_data: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    phase_scores: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    deviations: Mapped[list | None] = mapped_column(JSON, nullable=True)
    coaching_feedback: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class AnalysisCreate(BaseModel):
    stroke_type: StrokeType
    pro_reference: str = "federer"


class AnalysisResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: str | None
    status: AnalysisStatus
    stroke_type: StrokeType
    video_s3_key: str
    pro_reference: str
    pose_data: Any | None
    phase_scores: dict | None
    deviations: list | None
    coaching_feedback: dict | None
    overall_score: float | None
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None
    processing_time_ms: int | None

    @field_serializer("id")
    def serialize_id(self, v: uuid.UUID) -> str:
        return str(v)
