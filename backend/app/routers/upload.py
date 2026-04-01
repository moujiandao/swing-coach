import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Analysis,
    AnalysisCreate,
    AnalysisStatus,
    ConfirmResponse,
    ProReference,
    ProReferenceStatus,
    UploadInitResponse,
)
from app.services.db import get_db
from app.services.s3 import generate_presigned_upload_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/upload", tags=["upload"])


@router.post("", response_model=UploadInitResponse, status_code=status.HTTP_201_CREATED)
async def initiate_upload(
    body: AnalysisCreate,
    db: AsyncSession = Depends(get_db),
) -> UploadInitResponse:
    """
    Creates an Analysis record and returns a presigned S3 URL for direct upload.
    The frontend PUTs the video file to upload_url, then calls /confirm.
    """
    analysis_id = uuid.uuid4()
    timestamp = int(datetime.now(timezone.utc).timestamp())
    s3_key = f"uploads/{analysis_id}/{timestamp}.mp4"

    upload_url = generate_presigned_upload_url(s3_key, content_type="video/mp4")

    # If a pro_reference_id was provided, validate it exists and is ready
    pro_ref_name = body.pro_reference
    if body.pro_reference_id is not None:
        ref_result = await db.execute(
            select(ProReference).where(ProReference.id == body.pro_reference_id)
        )
        pro_ref = ref_result.scalar_one_or_none()
        if pro_ref is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Pro reference not found",
            )
        if pro_ref.status != ProReferenceStatus.ready:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Pro reference is not ready (status: {pro_ref.status.value})",
            )
        pro_ref_name = pro_ref.player_slug

    analysis = Analysis(
        id=analysis_id,
        status=AnalysisStatus.pending,
        stroke_type=body.stroke_type,
        pro_reference=pro_ref_name,
        pro_reference_id=body.pro_reference_id,
        video_s3_key=s3_key,
        created_at=datetime.now(timezone.utc),
    )
    db.add(analysis)
    await db.flush()  # write to DB within the transaction

    logger.info(
        "Upload initiated — analysis_id=%s stroke=%s pro_reference_id=%s",
        analysis_id, body.stroke_type, body.pro_reference_id,
    )
    return UploadInitResponse(
        analysis_id=str(analysis_id),
        upload_url=upload_url,
        s3_key=s3_key,
    )


@router.post(
    "/{analysis_id}/confirm",
    response_model=ConfirmResponse,
    status_code=status.HTTP_200_OK,
)
async def confirm_upload(
    analysis_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ConfirmResponse:
    """
    Called by the frontend after it finishes uploading the video to S3.
    Transitions status to 'processing' and enqueues the analysis job.
    """
    result = await db.execute(select(Analysis).where(Analysis.id == analysis_id))
    analysis = result.scalar_one_or_none()

    if analysis is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")

    if analysis.status != AnalysisStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Analysis is already in status '{analysis.status.value}', expected 'pending'",
        )

    analysis.status = AnalysisStatus.processing
    await db.flush()

    # Enqueue RQ job — worker implemented in Task 1.5+
    _enqueue_analysis_job(str(analysis_id))

    logger.info("Upload confirmed — analysis_id=%s enqueued", analysis_id)
    return ConfirmResponse(analysis_id=str(analysis_id), status=AnalysisStatus.processing.value)


@router.post("/local/{analysis_id}", status_code=status.HTTP_200_OK)
async def local_upload(
    analysis_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Local dev fallback: receives multipart video upload and writes it to the
    uploads/ directory path stored in analysis.video_s3_key.
    Only used when S3_BUCKET is not configured (file:// presigned URL path).
    """
    result = await db.execute(select(Analysis).where(Analysis.id == analysis_id))
    analysis = result.scalar_one_or_none()
    if analysis is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")

    dest = Path("uploads") / analysis.video_s3_key
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    dest.write_bytes(content)

    logger.info("Local upload saved — analysis_id=%s path=%s", analysis_id, dest)
    return {"ok": True}


def _enqueue_analysis_job(analysis_id: str) -> None:
    """Stub: enqueue the analysis pipeline via RQ. Fully wired in Task 1.5."""
    try:
        from redis import Redis
        from rq import Queue
        from app.worker.tasks import process_analysis
        from app.config import get_settings

        q = Queue(connection=Redis.from_url(get_settings().redis_url))
        q.enqueue(process_analysis, analysis_id, job_timeout=600)
        logger.info("Job enqueued for analysis_id=%s", analysis_id)
    except Exception as exc:
        # Don't fail the HTTP response if Redis is unavailable in dev
        logger.warning("Could not enqueue job for %s (Redis unavailable?): %s", analysis_id, exc)
