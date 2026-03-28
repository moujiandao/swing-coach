"""
Pro reference management endpoints.

Handles the full lifecycle of user-uploaded pro swing references:
  create → presigned URL → confirm → process (worker) → ready
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ProReference,
    ProReferenceCreate,
    ProReferenceListItem,
    ProReferenceResponse,
    ProReferenceStatus,
    StrokeType,
    slugify,
)
from app.services.db import get_db
from app.services.s3 import delete_object, generate_presigned_upload_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pro-references", tags=["pro-references"])


# ---------------------------------------------------------------------------
# Request / response shapes only used by this router
# ---------------------------------------------------------------------------

class ProReferenceCreateResponse(BaseModel):
    reference_id: str
    upload_url: str
    s3_key: str


class ProReferenceConfirmResponse(BaseModel):
    reference_id: str
    status: str


class ProReferenceReprocessResponse(BaseModel):
    reference_id: str
    status: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _unique_slug(db: AsyncSession, base_slug: str) -> str:
    """Return base_slug if unused, otherwise append -2, -3, etc. until unique."""
    candidate = base_slug
    counter = 2
    while True:
        result = await db.execute(
            select(ProReference).where(ProReference.player_slug == candidate)
        )
        if result.scalar_one_or_none() is None:
            return candidate
        candidate = f"{base_slug}-{counter}"
        counter += 1


async def _get_or_404(db: AsyncSession, reference_id: uuid.UUID) -> ProReference:
    result = await db.execute(
        select(ProReference).where(ProReference.id == reference_id)
    )
    ref = result.scalar_one_or_none()
    if ref is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pro reference not found")
    return ref


# ---------------------------------------------------------------------------
# POST /api/pro-references  — initiate upload
# ---------------------------------------------------------------------------

@router.post("", response_model=ProReferenceCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_pro_reference(
    body: ProReferenceCreate,
    db: AsyncSession = Depends(get_db),
) -> ProReferenceCreateResponse:
    """
    Creates a ProReference record and returns a presigned S3 URL for direct
    video upload. The caller PUTs the video to upload_url, then calls /confirm.
    """
    reference_id = uuid.uuid4()
    timestamp = int(datetime.now(timezone.utc).timestamp())
    s3_key = f"pro-references/{reference_id}/{timestamp}.mp4"

    # Slug encodes player + stroke so a player can have multiple stroke types
    base_slug = f"{slugify(body.player_name)}-{body.stroke_type.value.replace('_', '-')}"
    slug = await _unique_slug(db, base_slug)

    upload_url = generate_presigned_upload_url(s3_key, content_type="video/mp4")

    ref = ProReference(
        id=reference_id,
        player_name=body.player_name,
        player_slug=slug,
        stroke_type=body.stroke_type,
        video_s3_key=s3_key,
        status=ProReferenceStatus.pending,
        is_builtin=False,
        metadata_json=body.metadata_json,
        created_at=datetime.now(timezone.utc),
    )
    db.add(ref)
    await db.flush()

    logger.info(
        "Pro reference upload initiated — id=%s player=%s stroke=%s",
        reference_id, body.player_name, body.stroke_type,
    )
    return ProReferenceCreateResponse(
        reference_id=str(reference_id),
        upload_url=upload_url,
        s3_key=s3_key,
    )


# ---------------------------------------------------------------------------
# POST /api/pro-references/{id}/confirm
# ---------------------------------------------------------------------------

@router.post(
    "/{reference_id}/confirm",
    response_model=ProReferenceConfirmResponse,
    status_code=status.HTTP_200_OK,
)
async def confirm_pro_reference(
    reference_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ProReferenceConfirmResponse:
    """
    Called after the frontend finishes uploading the video to S3.
    Transitions status to 'processing' and enqueues the processing job.
    """
    ref = await _get_or_404(db, reference_id)

    if ref.status != ProReferenceStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Reference is in status '{ref.status.value}', expected 'pending'",
        )

    ref.status = ProReferenceStatus.processing
    await db.flush()

    _enqueue_pro_reference_job(str(reference_id))

    logger.info("Pro reference confirmed — id=%s enqueued", reference_id)
    return ProReferenceConfirmResponse(
        reference_id=str(reference_id),
        status=ProReferenceStatus.processing.value,
    )


# ---------------------------------------------------------------------------
# GET /api/pro-references  — list
# ---------------------------------------------------------------------------

@router.get("", response_model=list[ProReferenceListItem])
async def list_pro_references(
    stroke_type: Optional[StrokeType] = Query(default=None),
    status: Optional[ProReferenceStatus] = Query(default=None),
    include_builtin: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
) -> list[ProReferenceListItem]:
    """Return all pro references, with optional filtering."""
    stmt = select(ProReference)
    if stroke_type is not None:
        stmt = stmt.where(ProReference.stroke_type == stroke_type)
    if status is not None:
        stmt = stmt.where(ProReference.status == status)
    if not include_builtin:
        stmt = stmt.where(ProReference.is_builtin.is_(False))
    stmt = stmt.order_by(ProReference.player_name)

    result = await db.execute(stmt)
    records = result.scalars().all()
    return [ProReferenceListItem.model_validate(r) for r in records]


# ---------------------------------------------------------------------------
# GET /api/pro-references/{id}  — detail
# ---------------------------------------------------------------------------

@router.get("/{reference_id}", response_model=ProReferenceResponse)
async def get_pro_reference(
    reference_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ProReferenceResponse:
    """Return full detail for one pro reference."""
    ref = await _get_or_404(db, reference_id)
    return ProReferenceResponse.model_validate(ref)


# ---------------------------------------------------------------------------
# DELETE /api/pro-references/{id}
# ---------------------------------------------------------------------------

@router.delete("/{reference_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pro_reference(
    reference_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Delete a pro reference. Returns 403 for built-in references.
    Removes the .npz from disk and the video/thumbnail from S3 before
    deleting the DB record.
    """
    ref = await _get_or_404(db, reference_id)

    if ref.is_builtin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Built-in pro references cannot be deleted",
        )

    # Clean up files — best-effort, don't fail the delete if a file is missing
    if ref.npz_path:
        from pathlib import Path
        npz = Path(ref.npz_path)
        if npz.exists():
            npz.unlink()
            logger.info("Deleted .npz: %s", npz)

    if ref.video_s3_key:
        delete_object(ref.video_s3_key)

    if ref.thumbnail_s3_key:
        delete_object(ref.thumbnail_s3_key)

    await db.delete(ref)
    logger.info("Deleted pro reference — id=%s player=%s", reference_id, ref.player_name)


# ---------------------------------------------------------------------------
# POST /api/pro-references/{id}/reprocess
# ---------------------------------------------------------------------------

@router.post(
    "/{reference_id}/reprocess",
    response_model=ProReferenceReprocessResponse,
    status_code=status.HTTP_200_OK,
)
async def reprocess_pro_reference(
    reference_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ProReferenceReprocessResponse:
    """
    Re-run the processing pipeline on an existing pro reference.
    Useful when pipeline code improves. Blocked if already processing.
    """
    ref = await _get_or_404(db, reference_id)

    if ref.status == ProReferenceStatus.processing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Reference is already being processed",
        )

    # Delete stale .npz so the pipeline produces a fresh one
    if ref.npz_path:
        from pathlib import Path
        npz = Path(ref.npz_path)
        if npz.exists():
            npz.unlink()
            logger.info("Deleted stale .npz before reprocess: %s", npz)
        ref.npz_path = None

    ref.status = ProReferenceStatus.processing
    ref.error_message = None
    await db.flush()

    _enqueue_pro_reference_job(str(reference_id))

    logger.info("Pro reference reprocess queued — id=%s", reference_id)
    return ProReferenceReprocessResponse(
        reference_id=str(reference_id),
        status=ProReferenceStatus.processing.value,
    )


# ---------------------------------------------------------------------------
# RQ job dispatch
# ---------------------------------------------------------------------------

def _enqueue_pro_reference_job(reference_id: str) -> None:
    """Enqueue the pro reference processing job via RQ. No-op if Redis unavailable."""
    try:
        from redis import Redis
        from rq import Queue
        from app.worker.pro_reference_tasks import process_pro_reference
        from app.config import get_settings

        q = Queue(connection=Redis.from_url(get_settings().redis_url))
        q.enqueue(process_pro_reference, reference_id)
        logger.info("Pro reference job enqueued — id=%s", reference_id)
    except Exception as exc:
        logger.warning(
            "Could not enqueue pro reference job %s (Redis unavailable?): %s", reference_id, exc
        )
