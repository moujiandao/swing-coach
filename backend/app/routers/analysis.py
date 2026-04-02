import logging
import uuid

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Analysis, AnalysisResponse, AnalysisStatus, LANDMARK_CONNECTIONS, OverlayResponse
from app.services.db import get_db
from app.services.s3 import generate_presigned_download_url, generate_presigned_urls

logger = logging.getLogger(__name__)

router = APIRouter(tags=["analysis"])


def _round_landmarks(raw: list) -> list:
    """Round a nested [frame][landmark][coord] list to 4 decimal places."""
    arr = np.array(raw, dtype=np.float64)
    return np.round(arr, 4).tolist()


def _build_keyframe_urls(keyframe_s3_keys: dict | None) -> dict | None:
    """Convert {phase_name: s3_key} → {phase_name: presigned_url}."""
    if not keyframe_s3_keys:
        return None
    keys = list(keyframe_s3_keys.values())
    urls = generate_presigned_urls(keys)
    return dict(zip(keyframe_s3_keys.keys(), urls))


@router.get("/analysis/{analysis_id}", response_model=AnalysisResponse, status_code=status.HTTP_200_OK)
async def get_analysis(
    analysis_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> AnalysisResponse:
    """Returns the current state of an analysis. Frontend polls this every 2s."""
    result = await db.execute(select(Analysis).where(Analysis.id == analysis_id))
    analysis = result.scalar_one_or_none()

    if analysis is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")

    resp = AnalysisResponse.model_validate(analysis)
    return resp.model_copy(update={
        "video_url": generate_presigned_download_url(analysis.video_s3_key),
        "keyframe_urls": _build_keyframe_urls(analysis.keyframe_s3_keys),
    })


@router.get("/analysis/{analysis_id}/overlay", response_model=OverlayResponse, status_code=status.HTTP_200_OK)
async def get_analysis_overlay(
    analysis_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """
    Returns the overlay dataset for canvas rendering.

    Requires the analysis to have completed successfully.  The landmark
    coordinate arrays are rounded to 4 decimal places to reduce payload size.
    The response includes Cache-Control: immutable because overlay data never
    changes after an analysis is complete.
    """
    result = await db.execute(select(Analysis).where(Analysis.id == analysis_id))
    analysis = result.scalar_one_or_none()

    if analysis is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")

    if analysis.status != AnalysisStatus.completed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Overlay not available — analysis status is '{analysis.status.value}'",
        )

    if analysis.aligned_pro_landmarks is None or analysis.pose_data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Overlay data not available for this analysis",
        )

    # Round landmark arrays to 4 decimal places (float32 precision is sufficient)
    user_lm = _round_landmarks(analysis.pose_data)
    pro_lm  = _round_landmarks(analysis.aligned_pro_landmarks)

    payload = OverlayResponse(
        user_landmarks=user_lm,
        pro_landmarks=pro_lm,
        frame_mapping=analysis.frame_mapping or [],
        frame_deviations=analysis.frame_deviations or [],
        phase_boundaries=analysis.phase_boundaries or {},
        fps=analysis.fps or 30.0,
        landmark_connections=LANDMARK_CONNECTIONS,
        detection_mask=analysis.detection_mask,
        video_url=generate_presigned_download_url(analysis.video_s3_key),
        keyframe_urls=_build_keyframe_urls(analysis.keyframe_s3_keys),
    )

    response = JSONResponse(content=payload.model_dump())
    # Presigned URLs expire in 1 hour — use private short-lived cache instead of immutable
    response.headers["Cache-Control"] = "private, max-age=3600"
    return response


@router.post("/analysis/{analysis_id}/cancel", status_code=status.HTTP_200_OK)
async def cancel_analysis(
    analysis_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Cancel a processing analysis by marking it as failed."""
    result = await db.execute(select(Analysis).where(Analysis.id == analysis_id))
    analysis = result.scalar_one_or_none()

    if analysis is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")

    if analysis.status not in (AnalysisStatus.processing, AnalysisStatus.pending):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot cancel analysis in status '{analysis.status.value}'",
        )

    analysis.status = AnalysisStatus.failed
    analysis.error_message = "Cancelled by user"
    await db.flush()

    logger.info("Analysis cancelled — id=%s", analysis_id)
    return {"analysis_id": str(analysis_id), "status": "failed"}


@router.get("/history", response_model=list[AnalysisResponse], status_code=status.HTTP_200_OK)
async def get_history(
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[AnalysisResponse]:
    """Returns past analyses ordered by most recent first."""
    result = await db.execute(
        select(Analysis).order_by(Analysis.created_at.desc()).limit(limit)
    )
    analyses = result.scalars().all()
    return [AnalysisResponse.model_validate(a) for a in analyses]
