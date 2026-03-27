"""
Tests covering acceptance criteria for Task 1.2:
 - Migration runs successfully against local SQLite
 - Can create and query an Analysis record programmatically
 - Pydantic schemas serialize/deserialize correctly
 - Enum values are validated on input
"""
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import (
    Analysis,
    AnalysisCreate,
    AnalysisResponse,
    AnalysisStatus,
    Base,
    StrokeType,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


async def make_engine():
    engine = create_async_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


def sample_analysis(**kwargs) -> Analysis:
    # SQLAlchemy column defaults only apply at INSERT time, so set them explicitly here
    defaults = dict(
        id=uuid.uuid4(),
        status=AnalysisStatus.pending,
        video_s3_key="uploads/test/video.mp4",
        stroke_type=StrokeType.forehand,
        pro_reference="federer",
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(kwargs)
    return Analysis(**defaults)


# ---------------------------------------------------------------------------
# AC1: Migration runs against SQLite
# ---------------------------------------------------------------------------

def test_alembic_upgrade_runs_on_sqlite(tmp_path):
    """alembic upgrade head should succeed against a fresh SQLite file."""
    import subprocess
    import sys

    db_path = tmp_path / "test_migration.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"

    backend_dir = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env={**os.environ, "DATABASE_URL": db_url},
        cwd=str(backend_dir),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"alembic upgrade failed:\n{result.stderr}"
    assert db_path.exists(), "SQLite file was not created"


# ---------------------------------------------------------------------------
# AC2: Create and query an Analysis record
# ---------------------------------------------------------------------------

async def test_create_and_query_analysis():
    engine = await make_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)

    record = sample_analysis()
    async with factory() as session:
        session.add(record)
        await session.commit()
        analysis_id = record.id

    async with factory() as session:
        result = await session.execute(select(Analysis).where(Analysis.id == analysis_id))
        fetched = result.scalar_one()

    assert fetched.id == analysis_id
    assert fetched.stroke_type == StrokeType.forehand
    assert fetched.status == AnalysisStatus.pending
    assert fetched.pro_reference == "federer"
    await engine.dispose()


async def test_update_analysis_status():
    engine = await make_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)

    record = sample_analysis()
    async with factory() as session:
        session.add(record)
        await session.commit()
        analysis_id = record.id

    async with factory() as session:
        result = await session.execute(select(Analysis).where(Analysis.id == analysis_id))
        fetched = result.scalar_one()
        fetched.status = AnalysisStatus.completed
        fetched.overall_score = 78.5
        fetched.completed_at = datetime.now(timezone.utc)
        await session.commit()

    async with factory() as session:
        result = await session.execute(select(Analysis).where(Analysis.id == analysis_id))
        updated = result.scalar_one()

    assert updated.status == AnalysisStatus.completed
    assert updated.overall_score == 78.5
    await engine.dispose()


async def test_json_fields_roundtrip():
    engine = await make_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)

    phase_scores = {"backswing": 82.1, "forward_swing": 71.5, "contact": 90.0, "follow_through": 68.3}
    deviations = [{"joint": "elbow_angle", "phase": "backswing", "angle_diff": 12.5, "description": "Elbow too high"}]
    coaching_feedback = {"summary": "Good contact point.", "priority_fixes": [], "positive_notes": ["Great follow-through"]}

    record = sample_analysis(
        phase_scores=phase_scores,
        deviations=deviations,
        coaching_feedback=coaching_feedback,
    )
    async with factory() as session:
        session.add(record)
        await session.commit()
        analysis_id = record.id

    async with factory() as session:
        result = await session.execute(select(Analysis).where(Analysis.id == analysis_id))
        fetched = result.scalar_one()

    assert fetched.phase_scores == phase_scores
    assert fetched.deviations == deviations
    assert fetched.coaching_feedback == coaching_feedback
    await engine.dispose()


# ---------------------------------------------------------------------------
# AC3: Pydantic schemas serialize/deserialize correctly
# ---------------------------------------------------------------------------

def test_analysis_create_schema_defaults():
    schema = AnalysisCreate(stroke_type=StrokeType.forehand)
    assert schema.pro_reference == "federer"
    assert schema.stroke_type == StrokeType.forehand


def test_analysis_response_from_orm():
    analysis = sample_analysis()
    response = AnalysisResponse.model_validate(analysis)
    # id should serialize as a string
    data = response.model_dump()
    assert isinstance(data["id"], str)
    assert data["status"] == "pending"
    assert data["stroke_type"] == "forehand"
    assert data["pro_reference"] == "federer"


def test_analysis_response_json_roundtrip():
    analysis = sample_analysis(
        overall_score=85.0,
        phase_scores={"contact": 92.0},
    )
    response = AnalysisResponse.model_validate(analysis)
    json_str = response.model_dump_json()
    assert '"overall_score":85.0' in json_str or '"overall_score": 85.0' in json_str
    assert "contact" in json_str


# ---------------------------------------------------------------------------
# AC4: Enum validation on input
# ---------------------------------------------------------------------------

def test_stroke_type_enum_valid_values():
    for stroke in ["forehand", "backhand_one", "backhand_two", "serve_flat", "serve_kick", "serve_slice", "volley"]:
        schema = AnalysisCreate(stroke_type=stroke)
        assert schema.stroke_type.value == stroke


def test_stroke_type_enum_rejects_invalid():
    with pytest.raises(ValidationError) as exc_info:
        AnalysisCreate(stroke_type="smash")
    assert "stroke_type" in str(exc_info.value)


def test_analysis_status_enum_values():
    for status in AnalysisStatus:
        assert status.value in ("pending", "processing", "completed", "failed")


def test_analysis_create_requires_stroke_type():
    with pytest.raises(ValidationError):
        AnalysisCreate()
