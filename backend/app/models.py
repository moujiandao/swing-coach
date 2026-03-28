import enum
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, Float, ForeignKey, Integer, JSON, String, Text, Uuid
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


class ProReferenceStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    ready = "ready"
    failed = "failed"


# ---------------------------------------------------------------------------
# Slug utility
# ---------------------------------------------------------------------------

def slugify(name: str) -> str:
    """Convert a display name to a URL-safe slug. 'Roger Federer' -> 'roger-federer'."""
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


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
    # New: FK to ProReference; nullable so old analyses without it still load
    pro_reference_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("pro_references.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Pipeline output fields — all nullable until processing completes
    pose_data: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    phase_scores: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    deviations: Mapped[list | None] = mapped_column(JSON, nullable=True)
    coaching_feedback: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Resampled pro landmarks stored for client-side skeleton overlay
    pro_landmarks: Mapped[Any | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ProReference(Base):
    __tablename__ = "pro_references"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    player_name: Mapped[str] = mapped_column(String(255), nullable=False)
    player_slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    stroke_type: Mapped[StrokeType] = mapped_column(
        SAEnum(StrokeType, name="stroketype", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    video_s3_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    thumbnail_s3_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    npz_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[ProReferenceStatus] = mapped_column(
        SAEnum(ProReferenceStatus, name="proreferencestatus", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=ProReferenceStatus.pending,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    frame_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fps: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class AnalysisCreate(BaseModel):
    stroke_type: StrokeType
    pro_reference: str = "federer"          # legacy string name — kept for backward compat
    pro_reference_id: uuid.UUID | None = None  # preferred: FK to ProReference table


class UploadInitResponse(BaseModel):
    analysis_id: str
    upload_url: str
    s3_key: str


class ConfirmResponse(BaseModel):
    analysis_id: str
    status: str


class AnalysisResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: str | None
    status: AnalysisStatus
    stroke_type: StrokeType
    video_s3_key: str
    pro_reference: str
    pro_reference_id: uuid.UUID | None
    pose_data: Any | None
    phase_scores: dict | None
    deviations: list | None
    coaching_feedback: dict | None
    overall_score: float | None
    error_message: str | None
    pro_landmarks: Any | None
    created_at: datetime
    completed_at: datetime | None
    processing_time_ms: int | None

    @field_serializer("id")
    def serialize_id(self, v: uuid.UUID) -> str:
        return str(v)

    @field_serializer("pro_reference_id")
    def serialize_pro_reference_id(self, v: uuid.UUID | None) -> str | None:
        return str(v) if v is not None else None


class ProReferenceCreate(BaseModel):
    player_name: str
    stroke_type: StrokeType
    metadata_json: dict | None = None


class ProReferenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    player_name: str
    player_slug: str
    stroke_type: StrokeType
    video_s3_key: str | None
    thumbnail_s3_key: str | None
    npz_path: str | None
    status: ProReferenceStatus
    error_message: str | None
    frame_count: int | None
    fps: float | None
    duration_seconds: float | None
    is_builtin: bool
    metadata_json: dict | None
    created_at: datetime
    processed_at: datetime | None

    @field_serializer("id")
    def serialize_id(self, v: uuid.UUID) -> str:
        return str(v)


class ProReferenceListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    player_name: str
    player_slug: str
    stroke_type: StrokeType
    status: ProReferenceStatus
    thumbnail_s3_key: str | None
    is_builtin: bool
    created_at: datetime

    @field_serializer("id")
    def serialize_id(self, v: uuid.UUID) -> str:
        return str(v)
